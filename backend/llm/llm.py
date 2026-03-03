"""LLM integration for spec editing via OpenAI and DeepSeek."""
import json
import logging
import os
import time
from typing import Optional

from backend.core.core import LLM_MODEL_NAME, DEEPSEEK_MODEL_NAME, GEMINI_MODEL_NAME, CLAUDE_MODEL_NAME, OLLAMA_MODEL_NAME, OLLAMA_BASE_URL, DEFAULT_LLM_PROVIDER, LLM_SYSTEM_PROMPT, BACKEND_DIR
from backend.schemas.schemas_loader import SPEC_SCHEMA
from backend.schemas.spec_utils import validate_spec, SpecValidationError
from backend.llm.category_context import (
    CATEGORY_CONTEXT, CATEGORY_SCHEMAS, VANILLA_REF, detect_category,
)
from backend.llm.mcp_context import (
    MCPContext, MCPValidationResult, DesignModelResult,
    retrieve_context_sync, mcp_validate_sync, is_retryable,
    mcp_design_model_sync,
)

log = logging.getLogger(__name__)

# Optional logging - gracefully handle if not available
try:
    from llm_logger import log_llm_call
    from llm_scoring import check_semantic_consistency
    LOGGING_ENABLED = True
except ImportError:
    LOGGING_ENABLED = False
    def log_llm_call(*args, **kwargs): pass
    def check_semantic_consistency(spec): return None


def _prepare_spec_for_llm(spec: dict) -> str:
    """Serialize a spec for inclusion in the LLM user message.

    Strips bulky fields the LLM doesn't need (raw geometry data, internal
    metadata) to stay within token budgets.  Keeps the geometry *reference*
    (e.g. "geometry.ghast") so the LLM knows what model is active.
    """
    slim = {k: v for k, v in spec.items()
            if k not in ("geometry_json", "_template_base", "_texture_b64",
                         "_mcp_meta", "_mcp_design")}
    # Note: geometry_json stripped — LLM uses "geometry" field for reference
    if spec.get("geometry_json") and spec["geometry_json"].get("minecraft:geometry"):
        slim["geometry_json"] = "(present — omitted for token budget)"
    return json.dumps(slim, indent=2)


MAX_SYSTEM_PROMPT_CHARS = 25_000  # ~6K tokens — keeps total well under 80K


def _get_full_system_prompt(
    category: str = "entity_logic_ai",
    mcp_context: Optional[MCPContext] = None,
) -> str:
    """Build a system prompt dynamically based on the content category.

    Layers (ordered for LLM attention — most important first and last):
      1. Base LLM_SYSTEM_PROMPT (shared rules from core.py)
      2. MCP authoritative schema (dynamic, from Minecraft Creator Tools)
      3. Category-specific context (static examples, structure, rules)
      4. MCP model templates (dynamic, if geometry-related)
      5. Mob-spec schema (always included for entity category)
    """
    prompt = LLM_SYSTEM_PROMPT

    # MCP authoritative schema — placed early for primacy effect
    if mcp_context and mcp_context.schema_text:
        prompt += "\n\n--- AUTHORITATIVE BEDROCK SCHEMA (from Minecraft Creator Tools) ---\n"
        prompt += "Use this schema as the ground truth for valid fields, types, and value ranges:\n"
        prompt += mcp_context.schema_text
        prompt += "\n--- END SCHEMA ---"

    cat_context = CATEGORY_CONTEXT.get(category, "")
    if cat_context:
        prompt += f"\n\n{cat_context}"

    # MCP model templates — placed after examples so LLM has structure context
    if mcp_context and mcp_context.template_text:
        prompt += "\n\n--- MODEL TEMPLATES (from Minecraft Creator Tools) ---\n"
        prompt += "Use these as starting points when creating or modifying geometry:\n"
        prompt += mcp_context.template_text
        prompt += "\n--- END TEMPLATES ---"

    cat_schema = CATEGORY_SCHEMAS.get(category)
    if cat_schema:
        prompt += f"\n\nSchema:\n{json.dumps(cat_schema, indent=2)}"
    elif category == "entity_logic_ai" and SPEC_SCHEMA:
        prompt += f"\n\nSchema:\n{json.dumps(SPEC_SCHEMA, indent=2)}"

    mcp_tag = ""
    if mcp_context and mcp_context.has_content:
        mcp_tag = f", mcp_sources={mcp_context.source_tools}"

    if len(prompt) > MAX_SYSTEM_PROMPT_CHARS:
        prompt = prompt[:MAX_SYSTEM_PROMPT_CHARS] + "\n... [system prompt truncated for token budget]"
        print(f"[LLM] WARNING: System prompt truncated from {len(prompt)} to {MAX_SYSTEM_PROMPT_CHARS} chars")

    print(f"[LLM] System prompt built for category={category} "
          f"(context={'yes' if cat_context else 'no'}, "
          f"schema={'yes' if (cat_schema or (category == 'entity_logic_ai' and SPEC_SCHEMA)) else 'no'}"
          f"{mcp_tag})")

    return prompt

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    from google import genai
    GENAI_AVAILABLE = True
except Exception:
    genai = None
    GENAI_AVAILABLE = False

try:
    import anthropic
except Exception:
    anthropic = None


def _get_openai_client(api_key: Optional[str]):
    """Get an OpenAI-compatible client routed through GitHub Models."""
    if OpenAI is None:
        raise RuntimeError("openai package is not installed. Install the 'openai' package.")
    key = api_key or os.environ.get("GITHUB_TOKEN")
    if not key:
        raise RuntimeError("Provide GITHUB_TOKEN (either in the form field or as an environment variable).")
    return OpenAI(
        base_url="https://models.github.ai/inference",
        api_key=key,
    )


def _call_openai(prompt: str, current: dict, api_key: Optional[str],
                 category: str = "entity_logic_ai",
                 mcp_context: Optional[MCPContext] = None) -> dict:
    """Call OpenAI to rewrite a spec based on a user prompt."""
    print("[LLM] calling OpenAI model", LLM_MODEL_NAME)
    client = _get_openai_client(api_key)
    sys_prompt = _get_full_system_prompt(category, mcp_context)
    user_content = f"Current spec:\n{_prepare_spec_for_llm(current)}\n\nInstruction:\n{prompt.strip()}"
    total_chars = len(sys_prompt) + len(user_content)
    print(f"[LLM] Request size: system={len(sys_prompt)} user={len(user_content)} total={total_chars} chars (~{total_chars//4} tokens)")
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_content}
    ]
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL_NAME,
            response_format={"type": "json_object"},
            messages=messages
        )
        content = resp.choices[0].message.content
    except Exception as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc
    try:
        candidate = json.loads(content)
    except Exception as exc:
        raise RuntimeError(f"LLM returned invalid JSON: {exc}") from exc
    if category == "entity_logic_ai":
        return validate_spec(candidate)
    return candidate


def _call_deepseek(prompt: str, current: dict, api_key: Optional[str],
                   category: str = "entity_logic_ai",
                   mcp_context: Optional[MCPContext] = None) -> dict:
    """Call DeepSeek to rewrite a spec based on a user prompt."""
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("Provide DEEPSEEK_API_KEY (either in the form field or as an environment variable).")

    print("[LLM] calling DeepSeek via OpenAI client")
    try:
        client = OpenAI(api_key=key, base_url="https://api.deepseek.com")

        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": _get_full_system_prompt(category, mcp_context)
                },
                {
                    "role": "user",
                    "content": f"Current spec:\n{_prepare_spec_for_llm(current)}\n\nInstruction:\n{prompt.strip()}"
                }
            ],
            stream=False,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        candidate = json.loads(content)
        if category == "entity_logic_ai":
            return validate_spec(candidate)
        return candidate
    except Exception as exc:
        print(f"[LLM] DeepSeek request failed: {exc}")
        raise RuntimeError(f"DeepSeek request failed: {exc}") from exc


def _call_gemini(prompt: str, current: dict, api_key: Optional[str],
                 category: str = "entity_logic_ai",
                 mcp_context: Optional[MCPContext] = None) -> dict:
    """Call Google Gemini to rewrite a spec based on a user prompt."""
    if not GENAI_AVAILABLE:
        raise RuntimeError("google-genai package is not installed. Run: pip install google-genai")
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Provide GEMINI_API_KEY (either in the form field or as an environment variable).")

    print("[LLM] calling Gemini model", GEMINI_MODEL_NAME)
    try:
        client = genai.Client(api_key=key)
        
        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=f"Current spec:\n{_prepare_spec_for_llm(current)}\n\nInstruction:\n{prompt.strip()}",
            config={
                "system_instruction": _get_full_system_prompt(category, mcp_context),
                "response_mime_type": "application/json"
            }
        )
        content = response.text
        candidate = json.loads(content)
        if category == "entity_logic_ai":
            return validate_spec(candidate)
        return candidate
    except Exception as exc:
        print(f"[LLM] Gemini request failed: {exc}")
        raise RuntimeError(f"Gemini request failed: {exc}") from exc


def _call_ollama(prompt: str, current: dict, api_key: Optional[str] = None,
                 category: str = "entity_logic_ai",
                 mcp_context: Optional[MCPContext] = None) -> dict:
    """Call local Ollama to rewrite a spec based on a user prompt.
    
    Ollama uses OpenAI-compatible API, so we use the OpenAI client with a custom base URL.
    No API key required for local Ollama.
    """
    if OpenAI is None:
        raise RuntimeError("openai package is not installed. Install the 'openai' package.")
    
    print("[LLM] calling Ollama model", OLLAMA_MODEL_NAME)
    try:
        client = OpenAI(
            base_url=f"{OLLAMA_BASE_URL}/v1",
            api_key="ollama"
        )
        
        messages = [
            {
                "role": "system",
                "content": _get_full_system_prompt(category, mcp_context)
            },
            {
                "role": "user",
                "content": f"Current spec:\n{_prepare_spec_for_llm(current)}\n\nInstruction:\n{prompt.strip()}\n\nRespond with ONLY the updated JSON spec, no explanation."
            }
        ]
        
        response = client.chat.completions.create(
            model=OLLAMA_MODEL_NAME,
            messages=messages,
            temperature=0.2
        )
        
        content = response.choices[0].message.content
        
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        candidate = json.loads(content.strip())
        if category == "entity_logic_ai":
            return validate_spec(candidate)
        return candidate
    except Exception as exc:
        print(f"[LLM] Ollama request failed: {exc}")
        raise RuntimeError(f"Ollama request failed: {exc}") from exc


def _call_claude(prompt: str, current: dict, api_key: Optional[str],
                 category: str = "entity_logic_ai",
                 mcp_context: Optional[MCPContext] = None) -> dict:
    """Call Anthropic Claude to rewrite a spec based on a user prompt."""
    if anthropic is None:
        raise RuntimeError("anthropic package is not installed.")
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Provide ANTHROPIC_API_KEY (either in the form field or as an environment variable).")

    print("[LLM] calling Claude model", CLAUDE_MODEL_NAME)
    try:
        client = anthropic.Anthropic(api_key=key)
        
        response = client.messages.create(
            model=CLAUDE_MODEL_NAME,
            max_tokens=2048,
            system=_get_full_system_prompt(category, mcp_context),
            messages=[
                {
                    "role": "user",
                    "content": f"Current spec:\n{_prepare_spec_for_llm(current)}\n\nInstruction:\n{prompt.strip()}"
                }
            ]
        )
        content = response.content[0].text
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
            
        candidate = json.loads(content)
        if category == "entity_logic_ai":
            return validate_spec(candidate)
        return candidate
    except Exception as exc:
        print(f"[LLM] Claude request failed: {exc}")
        raise RuntimeError(f"Claude request failed: {exc}") from exc


def _call_provider(
    prompt: str, current: dict, provider_key: str,
    api_key: Optional[str], category: str,
    mcp_context: Optional[MCPContext] = None,
) -> dict:
    """Route to the appropriate LLM provider."""
    if provider_key == "deepseek":
        return _call_deepseek(prompt, current, api_key, category, mcp_context)
    elif provider_key == "gemini":
        return _call_gemini(prompt, current, api_key, category, mcp_context)
    elif provider_key == "claude":
        return _call_claude(prompt, current, api_key, category, mcp_context)
    elif provider_key == "ollama":
        return _call_ollama(prompt, current, api_key, category, mcp_context)
    else:
        return _call_openai(prompt, current, api_key, category, mcp_context)


def llm_rewrite_spec(prompt: str, current: dict, provider: str,
                     api_key: Optional[str],
                     category: str = "entity_logic_ai") -> dict:
    """Route to appropriate LLM provider and rewrite a spec.

    Pipeline:
      1. Retrieve MCP context (schemas, templates) — non-blocking fallback
      2. Call LLM with enriched prompt
      3. Validate output with MCP validateContent — advisory
      4. If MCP finds retryable errors, retry once with error feedback
      5. Return spec + metadata
    """
    provider_key = (provider or DEFAULT_LLM_PROVIDER or "openai").lower()

    # Auto-detect what the input spec actually is
    detected_category = detect_category(current)
    if not category:
        category = detected_category

    # If the user's selected category differs from the spec's actual type,
    # augment the prompt so the LLM knows it's a conversion task.
    effective_prompt = prompt
    if category != detected_category:
        from backend.llm.category_context import CATEGORY_LABELS
        src_label = CATEGORY_LABELS.get(detected_category, detected_category)
        dst_label = CATEGORY_LABELS.get(category, category)
        effective_prompt = (
            f"[CONVERSION: The input is a {src_label} spec but the desired output "
            f"is a {dst_label} spec. Convert the structure accordingly.]\n\n"
            f"{prompt}"
        )
        print(f"[LLM] Category conversion: {detected_category} → {category}")

    print(f"[LLM] category={category} (detected={detected_category})")

    # --- Step 1: MCP context retrieval (additive, never blocking) ---
    mcp_ctx = retrieve_context_sync(effective_prompt, category, current)
    if mcp_ctx and mcp_ctx.has_content:
        print(f"[LLM] MCP context retrieved in {mcp_ctx.retrieval_ms}ms "
              f"(sources={mcp_ctx.source_tools})")

    start_time = time.time()
    output_spec = None
    error_msg = None
    validation_passed = True
    semantic_score = None
    mcp_validation: Optional[MCPValidationResult] = None

    try:
        # --- Step 2: LLM call with enriched prompt ---
        output_spec = _call_provider(
            effective_prompt, current, provider_key, api_key, category, mcp_ctx,
        )
        
        # Run semantic consistency check
        if LOGGING_ENABLED and output_spec:
            score_result = check_semantic_consistency(output_spec)
            if score_result:
                semantic_score = score_result.score

        # --- Step 3: MCP post-validation (advisory) ---
        if output_spec:
            mcp_validation = mcp_validate_sync(output_spec)

        # --- Step 4: Retry once if MCP found retryable errors ---
        if (mcp_validation and not mcp_validation.valid
                and mcp_validation.available
                and is_retryable(mcp_validation.errors)):
            error_feedback = "\n".join(f"- {e}" for e in mcp_validation.errors[:10])
            retry_prompt = (
                f"Original instruction: {prompt}\n\n"
                f"Your previous output had these validation errors from "
                f"Minecraft Creator Tools:\n{error_feedback}\n\n"
                f"Please fix these issues and return the corrected spec."
            )
            print(f"[LLM] MCP validation found {len(mcp_validation.errors)} error(s), "
                  f"retrying with error feedback")
            try:
                output_spec = _call_provider(
                    retry_prompt, output_spec, provider_key,
                    api_key, category, mcp_ctx,
                )
                # Re-validate after retry
                mcp_validation = mcp_validate_sync(output_spec)
            except Exception as retry_exc:
                log.warning("[LLM] Retry after MCP validation failed: %s", retry_exc)

    except SpecValidationError as exc:
        validation_passed = False
        error_msg = str(exc)
        raise
    except Exception as exc:
        error_msg = str(exc)
        raise
    finally:
        duration_ms = int((time.time() - start_time) * 1000)
        if LOGGING_ENABLED:
            log_llm_call(
                provider=provider_key,
                prompt=prompt,
                input_spec=current,
                output_spec=output_spec,
                error=error_msg,
                validation_passed=validation_passed,
                semantic_score=semantic_score,
                duration_ms=duration_ms
            )
    
    # --- Step 5: MCP texture generation if mob type changed ---
    texture_b64 = ""
    if output_spec and category == "entity_logic_ai":
        old_name = (current.get("display_name") or "").lower()
        new_name = (output_spec.get("display_name") or "").lower()
        if old_name and new_name and old_name != new_name:
            geo = output_spec.get("geometry_json")
            if geo and isinstance(geo, dict) and geo.get("minecraft:geometry"):
                safe_id = (output_spec.get("short_name") or "custom_mob").replace(":", "_")
                print(f"[LLM] Mob type changed ({old_name} → {new_name}), "
                      f"generating MCP texture for {safe_id}")
                try:
                    design_result = mcp_design_model_sync(geo, safe_id, prompt)
                    if design_result.available and design_result.texture_b64:
                        texture_b64 = design_result.texture_b64
                        print(f"[LLM] MCP texture generated ({len(texture_b64)} chars)")
                except Exception as tex_exc:
                    log.warning("[LLM] MCP texture generation failed: %s", tex_exc)

    # Attach MCP metadata to the spec for the route handler to surface
    if output_spec is not None:
        output_spec["_mcp_meta"] = {
            "augmented": bool(mcp_ctx and mcp_ctx.has_content),
            "context_sources": mcp_ctx.source_tools if mcp_ctx else [],
            "retrieval_ms": mcp_ctx.retrieval_ms if mcp_ctx else 0,
            "validation": {
                "ran": bool(mcp_validation and mcp_validation.available),
                "valid": mcp_validation.valid if mcp_validation else True,
                "messages": (mcp_validation.errors[:5] if mcp_validation else []),
            },
        }
        if texture_b64:
            output_spec["_texture_b64"] = texture_b64

    return output_spec


GEOMETRY_SYSTEM_PROMPT = """You are a Minecraft Bedrock Edition geometry generator. You generate valid minecraft:geometry JSON for custom mobs and entities.

Output format is a valid minecraft:geometry JSON object. The structure must be:
{
  "format_version": "1.12.0",
  "minecraft:geometry": [
    {
      "description": {
        "identifier": "geometry.custom_mob",
        "texture_width": 64,
        "texture_height": 64,
        "visible_bounds_width": 2,
        "visible_bounds_height": 2,
        "visible_bounds_offset": [0, 1, 0]
      },
      "bones": [
        {
          "name": "root",
          "pivot": [0, 0, 0]
        },
        {
          "name": "body",
          "parent": "root",
          "pivot": [0, 12, 0],
          "cubes": [
            {
              "origin": [-4, 8, -3],
              "size": [8, 8, 6],
              "uv": [0, 0]
            }
          ]
        }
      ]
    }
  ]
}

Key rules:
1. All coordinates use Y-up coordinate system (Y is vertical)
2. pivot defines the rotation point for a bone
3. origin is the minimum corner of a cube (not center)
4. size is [width_x, height_y, depth_z]
5. Parent bones must be defined before children reference them
6. Humanoid mobs typically have: root, body, head, left_arm, right_arm, left_leg, right_leg
7. Quadruped mobs typically have: root, body, head, leg0-3
8. Use appropriate UV coordinates for box UV mapping

When modifying existing geometry, preserve the structure and only change what's requested.
Output ONLY valid JSON, no explanations."""


def _get_geometry_system_prompt(mcp_template_text: str = "") -> str:
    """Get the system prompt for geometry generation, optionally with MCP templates."""
    prompt = GEOMETRY_SYSTEM_PROMPT
    if mcp_template_text:
        prompt += "\n\n--- MODEL TEMPLATES (from Minecraft Creator Tools) ---\n"
        prompt += "Use these as starting points instead of inventing geometry from scratch:\n"
        prompt += mcp_template_text
        prompt += "\n--- END TEMPLATES ---"
    return prompt


def _fetch_geometry_template_sync(prompt: str) -> str:
    """Fetch a geometry template from MCP based on the user's prompt."""
    from backend.llm.mcp_context import _detect_template_type, _fetch_templates
    import asyncio
    import concurrent.futures

    template_type = _detect_template_type(prompt, "entity_logic_ai")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            text = pool.submit(
                asyncio.run,
                _fetch_templates(prompt, "entity_logic_ai"),
            ).result(timeout=10)
        if text:
            print(f"[LLM-GEOMETRY] Fetched MCP template type={template_type} ({len(text)} chars)")
        return text or ""
    except Exception as e:
        log.warning("[LLM-GEOMETRY] MCP template fetch failed: %s", e)
        return ""


def llm_generate_geometry(
    prompt: str,
    current_geometry: dict | None,
    provider: str,
    api_key: str | None,
    mob_name: str = "custom_mob",
) -> dict:
    """Generate or modify Bedrock geometry JSON using LLM, then generate a
    matching texture via MCP designModel.

    Returns dict with keys:
      - Standard geometry keys (format_version, minecraft:geometry, etc.)
      - "_texture_b64": base64 data URL of the generated texture (or "")
      - "_mcp_design": bool indicating if MCP texture generation was used
    """
    provider_key = (provider or DEFAULT_LLM_PROVIDER or "openai").lower()

    start_time = time.time()
    output = None
    error_msg = None

    mcp_template_text = _fetch_geometry_template_sync(prompt)

    user_content = prompt.strip()
    if current_geometry:
        user_content = f"Current geometry:\n{json.dumps(current_geometry, indent=2)}\n\nInstruction:\n{prompt.strip()}"
    elif mcp_template_text:
        user_content = (
            f"Starting from the model templates provided in the system prompt, "
            f"create or modify geometry to match this request:\n{prompt.strip()}"
        )

    try:
        if provider_key == "deepseek":
            output = _call_geometry_deepseek(user_content, api_key, mcp_template_text)
        elif provider_key == "gemini":
            output = _call_geometry_gemini(user_content, api_key, mcp_template_text)
        elif provider_key == "claude":
            output = _call_geometry_claude(user_content, api_key, mcp_template_text)
        elif provider_key == "ollama":
            output = _call_geometry_ollama(user_content, api_key, mcp_template_text)
        else:
            output = _call_geometry_openai(user_content, api_key, mcp_template_text)

    except Exception as exc:
        error_msg = str(exc)
        raise
    finally:
        duration_ms = int((time.time() - start_time) * 1000)
        print(f"[LLM] Geometry generation took {duration_ms}ms, provider={provider_key}")

    # After LLM generates geometry, use MCP to create a matching texture
    texture_b64 = ""
    mcp_design_used = False
    if output and isinstance(output, dict) and output.get("minecraft:geometry"):
        safe_name = mob_name.replace(":", "_").replace(" ", "_").lower()
        print(f"[LLM-GEOMETRY] Calling MCP designModel for texture (model={safe_name})")
        design_result = mcp_design_model_sync(output, safe_name, prompt)
        if design_result.available and design_result.texture_b64:
            texture_b64 = design_result.texture_b64
            mcp_design_used = True
            print(f"[LLM-GEOMETRY] MCP texture generated ({len(texture_b64)} chars)")
            if design_result.geometry:
                output = design_result.geometry
        elif design_result.error:
            print(f"[LLM-GEOMETRY] MCP texture failed: {design_result.error}")

    output["_texture_b64"] = texture_b64
    output["_mcp_design"] = mcp_design_used

    return output


def _call_geometry_openai(user_content: str, api_key: str | None,
                          mcp_template_text: str = "") -> dict:
    """Call OpenAI to generate geometry."""
    client = _get_openai_client(api_key)
    messages = [
        {"role": "system", "content": _get_geometry_system_prompt(mcp_template_text)},
        {"role": "user", "content": user_content}
    ]
    resp = client.chat.completions.create(
        model=LLM_MODEL_NAME,
        response_format={"type": "json_object"},
        messages=messages
    )
    return json.loads(resp.choices[0].message.content)


def _call_geometry_deepseek(user_content: str, api_key: str | None,
                            mcp_template_text: str = "") -> dict:
    """Call DeepSeek to generate geometry."""
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("Provide DEEPSEEK_API_KEY")
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL_NAME,
        messages=[
            {"role": "system", "content": _get_geometry_system_prompt(mcp_template_text)},
            {"role": "user", "content": user_content}
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(resp.choices[0].message.content)


def _call_geometry_gemini(user_content: str, api_key: str | None,
                          mcp_template_text: str = "") -> dict:
    """Call Gemini to generate geometry."""
    if not GENAI_AVAILABLE:
        raise RuntimeError("google-genai package not installed")
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Provide GEMINI_API_KEY")
    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=GEMINI_MODEL_NAME,
        contents=user_content,
        config={
            "system_instruction": _get_geometry_system_prompt(mcp_template_text),
            "response_mime_type": "application/json"
        }
    )
    return json.loads(response.text)


def _call_geometry_claude(user_content: str, api_key: str | None,
                          mcp_template_text: str = "") -> dict:
    """Call Claude to generate geometry."""
    if anthropic is None:
        raise RuntimeError("anthropic package not installed")
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Provide ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=CLAUDE_MODEL_NAME,
        max_tokens=4096,
        system=_get_geometry_system_prompt(mcp_template_text),
        messages=[{"role": "user", "content": user_content}]
    )
    content = response.content[0].text
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content)


def _call_geometry_ollama(user_content: str, api_key: str | None,
                          mcp_template_text: str = "") -> dict:
    """Call Ollama to generate geometry."""
    if OpenAI is None:
        raise RuntimeError("openai package not installed")
    client = OpenAI(base_url=f"{OLLAMA_BASE_URL}/v1", api_key="ollama")
    response = client.chat.completions.create(
        model=OLLAMA_MODEL_NAME,
        messages=[
            {"role": "system", "content": _get_geometry_system_prompt(mcp_template_text)},
            {"role": "user", "content": user_content + "\n\nRespond with ONLY the JSON, no explanation."}
        ],
        temperature=0.2
    )
    content = response.choices[0].message.content
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())

