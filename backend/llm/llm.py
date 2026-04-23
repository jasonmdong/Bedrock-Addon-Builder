"""LLM integration for spec editing via OpenAI and DeepSeek."""
import json
import logging
import os
import time
from typing import Optional

from backend.core.core import (
    LLM_MODEL_NAME,
    DEEPSEEK_MODEL_NAME,
    GEMINI_MODEL_NAME,
    CLAUDE_MODEL_NAME,
    OLLAMA_MODEL_NAME,
    OLLAMA_BASE_URL,
    DEFAULT_LLM_PROVIDER,
    LLM_SYSTEM_PROMPT_COMPACT,
    build_llm_system_prompt,
)
from backend.schemas.schemas_loader import SPEC_SCHEMA
from backend.schemas.spec_utils import validate_spec, sanitize_spec, SpecValidationError
from backend.llm.category_context import (
    CATEGORY_CONTEXT, CATEGORY_SCHEMAS, detect_category, ENTITY_COMPONENT_REFERENCE_TEXT,
)
from backend.llm.mcp_context import (
    MCPContext, MCPValidationResult, DesignModelResult,
    retrieve_context_sync, mcp_validate_sync, is_retryable,
    mcp_design_model_sync,
)
from backend.llm.dynamic_context import (
    DynamicContext, build_dynamic_context,
)
from backend.llm.prompt_intents import (
    PromptIntentProfile, extract_prompt_intents,
)
from backend.llm.orchestrator import (
    build_plan, format_plan_for_prompt, should_use_orchestration,
    plan_is_simple, apply_plan,
)
from backend.llm.texture_gen import generate_mob_texture
from backend.llm.component_sanitizer import sanitize_spec

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
    Includes a summary of custom geometry bones so the LLM knows NOT to
    replace it with a vanilla geometry.
    """
    slim = {k: v for k, v in spec.items()
            if k not in ("geometry_json", "_template_base", "_texture_b64",
                         "_mcp_meta", "_mcp_design")}
    # Summarize custom geometry so the LLM knows it exists
    geo = spec.get("geometry_json")
    if geo and isinstance(geo, dict) and geo.get("minecraft:geometry"):
        bones = []
        for geom in geo["minecraft:geometry"]:
            for bone in geom.get("bones", []):
                bname = bone.get("name", "?")
                cubes = bone.get("cubes", [])
                bones.append(f"{bname}({len(cubes)} cubes)")
        desc = geom.get("description", {}) if geo["minecraft:geometry"] else {}
        geo_id = desc.get("identifier", "custom")
        tw = desc.get("texture_width", 64)
        th = desc.get("texture_height", 64)
        slim["geometry_json"] = (
            f"(CUSTOM GEOMETRY PRESENT — DO NOT REPLACE) "
            f"id={geo_id}, atlas={tw}x{th}, "
            f"bones=[{', '.join(bones)}]"
        )
    return json.dumps(slim, indent=2)


def _sanitize_geometry_json(candidate: dict) -> dict:
    """Clean up geometry_json before validation.

    If the LLM echoed back the placeholder string instead of a dict,
    replace it with {} so validate_spec doesn't reject the spec.
    The real geometry will be restored by _preserve_geometry later.
    """
    geo = candidate.get("geometry_json")
    if isinstance(geo, str):
        candidate["geometry_json"] = {}
    return candidate


def _has_custom_geometry(spec: dict) -> bool:
    """Return True if the spec has a non-empty custom geometry_json."""
    geo = spec.get("geometry_json")
    return bool(geo and isinstance(geo, dict) and geo.get("minecraft:geometry"))


def _preserve_geometry(output_spec: dict, input_spec: dict) -> dict:
    """Carry forward custom geometry from input if the LLM dropped it.

    The LLM doesn't receive the full geometry_json (too large for token
    budget).  If the input spec had custom geometry and the LLM returned
    an empty geometry_json (or echoed the placeholder string), we restore
    the original geometry + geometry_json so the user's custom model
    isn't lost during iterative edits.
    """
    if not _has_custom_geometry(input_spec):
        return output_spec

    # If the LLM echoed back the placeholder string, clear it so we restore below
    out_geo = output_spec.get("geometry_json")
    if isinstance(out_geo, str):
        output_spec["geometry_json"] = {}

    # If the LLM generated NEW custom geometry, keep it
    if _has_custom_geometry(output_spec):
        return output_spec

    # LLM dropped the custom geometry — restore from input
    output_spec["geometry_json"] = input_spec["geometry_json"]
    # Also restore the geometry reference ID if the LLM changed it to
    # a vanilla one (e.g. "geometry.chicken" instead of the original
    # custom ID like "geometry.custom_fire_dragon")
    input_geo_id = input_spec.get("geometry", "")
    output_geo_id = output_spec.get("geometry", "")
    if input_geo_id.startswith("geometry.custom") and not output_geo_id.startswith("geometry.custom"):
        output_spec["geometry"] = input_geo_id
        print(f"[LLM] Restored custom geometry: {input_geo_id} (LLM had changed to {output_geo_id})")
    else:
        print(f"[LLM] Preserved custom geometry_json from input spec")

    return output_spec


# ---------------------------------------------------------------------------
# Geometry auto-fetch: database → GitHub vanilla → LLM generation
# ---------------------------------------------------------------------------

# Mobs whose geometry can be fetched from Mojang's bedrock-samples repo
_VANILLA_GEOMETRY_NAMES = {
    "bat", "bee", "blaze", "cat", "cave_spider", "chicken", "cod", "cow",
    "creeper", "dolphin", "donkey", "drowned", "elder_guardian", "enderman",
    "endermite", "evoker", "fox", "ghast", "goat", "guardian", "hoglin",
    "horse", "husk", "iron_golem", "llama", "magma_cube", "mooshroom",
    "mule", "ocelot", "panda", "parrot", "phantom", "pig", "piglin",
    "pillager", "polar_bear", "pufferfish", "rabbit", "ravager", "salmon",
    "sheep", "shulker", "silverfish", "skeleton", "slime", "snow_golem",
    "spider", "squid", "stray", "strider", "trader_llama", "tropical_fish",
    "turtle", "vex", "villager", "vindicator", "wandering_trader", "witch",
    "wither", "wither_skeleton", "wolf", "zoglin", "zombie",
    "zombie_pigman", "zombie_villager", "zombified_piglin",
    "axolotl", "glow_squid", "warden", "allay", "frog", "tadpole",
    "camel", "sniffer", "armadillo", "breeze", "bogged",
}


def _is_vanilla_mob(display_name: str, geometry_ref: str) -> bool:
    """Check if the mob can be resolved from vanilla Bedrock geometry.
    
    Only return True if the display_name matches the geometry_ref (same vanilla animal).
    This prevents skipping auto-fetch for renamed mobs like "Elephant" with "geometry.cow".
    """
    name = display_name.lower().replace(" ", "_")
    geo_name = geometry_ref.replace("geometry.", "").lower()
    # Only skip auto-fetch if display_name and geometry match AND both are vanilla
    # (e.g., "Cow" + "geometry.cow" is vanilla, but "Elephant" + "geometry.cow" is not)
    return name == geo_name and name in _VANILLA_GEOMETRY_NAMES



def _auto_fetch_geometry(
    output_spec: dict,
    prompt: str,
    provider_key: str,
    api_key: Optional[str],
) -> dict:
    """If the LLM returned empty geometry_json for a non-vanilla mob, try to
    fill it from the database or generate it.

    Modifies output_spec in place and returns it.
    """
    # Skip if already has custom geometry
    if _has_custom_geometry(output_spec):
        print(f"[LLM-GEOFETCH] Skipping auto-fetch: spec already has custom geometry")
        return output_spec

    display_name = output_spec.get("display_name", "")
    geometry_ref = output_spec.get("geometry", "")

    # Skip vanilla mobs — frontend fetches their geometry from GitHub
    if _is_vanilla_mob(display_name, geometry_ref):
        print(f"[LLM-GEOFETCH] Skipping auto-fetch: '{display_name}' (geometry={geometry_ref}) is vanilla")
        return output_spec

    print(f"[LLM-GEOFETCH] Non-vanilla mob '{display_name}' (geometry={geometry_ref}) has no geometry, generating via LLM...")
    try:
        from backend.llm.animation_generation import llm_generate_animation
        from backend.llm.animation_controllers_generation import llm_generate_animation_controller
        
        short_name = output_spec.get("short_name", "custom_mob")
        geo_prompt = f"Create a {display_name} mob geometry"
        geo_result = llm_generate_geometry(
            prompt=geo_prompt,
            current_geometry=None,
            provider=provider_key,
            api_key=api_key,
            mob_name=short_name,
        )
        if geo_result and geo_result.get("minecraft:geometry"):
            # Strip internal keys
            clean_geo = {k: v for k, v in geo_result.items() if not k.startswith("_")}
            output_spec["geometry_json"] = clean_geo
            # Use texture from geometry generation if we don't have one yet
            if geo_result.get("_texture_b64") and not output_spec.get("_texture_b64"):
                output_spec["_texture_b64"] = geo_result["_texture_b64"]
            # Update geometry reference
            geo_list = clean_geo.get("minecraft:geometry", [])
            if geo_list and isinstance(geo_list[0], dict):
                geo_id = geo_list[0].get("description", {}).get("identifier", "")
                if geo_id:
                    output_spec["geometry"] = geo_id
            print(f"[LLM] Auto-generated geometry for '{display_name}'")
            
            # Auto-generate animations for the geometry
            try:
                anim_result = llm_generate_animation(
                    prompt=f"Create animations for: {geo_prompt}",
                    geometry_json=clean_geo,
                    mob_name=short_name,
                    provider=provider_key,
                    api_key=api_key,
                )
                animation = anim_result.get("animation")
                if animation:
                    output_spec["animation_json"] = animation
                    print(f"[LLM-GEOFETCH] Auto-generated animations with {anim_result.get('bone_count', '?')} bones")
                    print(f"[LLM-GEOFETCH] animation_json saved to spec: {json.dumps(animation, indent=2)[:500]}...")
                    
                    # Auto-generate animation controller
                    try:
                        ac_result = llm_generate_animation_controller(
                            animation_json=animation,
                            mob_name=short_name,
                            provider=provider_key,
                            api_key=api_key,
                        )
                        animation_controller = ac_result.get("animation_controller")
                        if animation_controller:
                            output_spec["animation_controller_json"] = animation_controller
                            output_spec["animation_controller"] = f"controller.animation.{short_name}"
                            print(f"[LLM-GEOFETCH] Auto-generated animation controller")
                            print(f"[LLM-GEOFETCH] animation_controller_json saved to spec: {json.dumps(animation_controller, indent=2)[:500]}...")
                            print(f"[LLM-GEOFETCH] animation_controller (id) saved to spec: {output_spec['animation_controller']}")
                        else:
                            print(f"[LLM-GEOFETCH] Warning: animation_controller is None or empty")
                    except Exception as ac_err:
                        print(f"[LLM-GEOFETCH] Warning: failed to generate controller: {ac_err}")
                else:
                    print(f"[LLM-GEOFETCH] Warning: animation generation returned None or empty")
                    print(f"[LLM-GEOFETCH] anim_result keys: {list(anim_result.keys()) if anim_result else 'None'}")
            except Exception as anim_err:
                print(f"[LLM-GEOFETCH] Warning: animation generation failed: {anim_err}")
                import traceback
                traceback.print_exc()
    except Exception as e:
        log.warning("[LLM] Auto geometry generation failed: %s", e)
        print(f"[LLM] Auto geometry generation failed for '{display_name}': {e}")

    return output_spec


MAX_SYSTEM_PROMPT_CHARS = 25_000  # ~6K tokens — keeps total well under 80K


def _get_full_system_prompt(
    user_prompt: str,
    current_spec: Optional[dict] = None,
    category: str = "entity_logic_ai",
    mcp_context: Optional[MCPContext] = None,
    dynamic_ctx: Optional[DynamicContext] = None,
    intent_profile: Optional[PromptIntentProfile] = None,
) -> str:
    """Build a system prompt dynamically based on the content category.

    Layers (ordered for LLM attention — most important first and last):
      1. Base LLM_SYSTEM_PROMPT (shared rules from core.py)
      2. MCP authoritative schema (dynamic, from Minecraft Creator Tools)
      3. Category-specific context (static examples, structure, rules)
      4. MCP model templates (dynamic, if geometry-related)
      5. Mob-spec schema (always included for entity category)
      6. Dynamic context (prompt-analyzed behavior docs + vanilla examples)
      7. Structured user intent extraction
    """
    user_prompt_l = (user_prompt or "").lower()
    has_custom_geo = bool(current_spec) and _has_custom_geometry(current_spec)

    # Decide which base sections to include.
    # Geometry/preservation are only injected when the prompt is actually
    # geometry-related — having a custom geometry model doesn't mean every
    # prompt needs those sections (e.g. "increase hp by 10" shouldn't).
    include_geometry = False
    include_geometry_preservation = False
    include_visuals = False
    include_loot = False

    # Keywords that suggest the user cares about shape/appearance and the LLM
    # might inadvertently touch geometry fields.
    _geo_adjacent_keywords = (
        "texture", "color", "colour", "scale", "size", "shape", "model",
        "geometry", "bone", "skin", "appearance", "look", "visual",
    )
    prompt_touches_visuals = any(k in user_prompt_l for k in _geo_adjacent_keywords)

    if intent_profile:
        # Geometry: explicit request OR generic "geometry_edit" signal
        if intent_profile.constraints.get("geometry_requested") or any(
            s.name == "geometry_edit" for s in intent_profile.signals
        ):
            include_geometry = True
        # Preservation: only when mob has custom geo AND prompt could affect appearance
        if has_custom_geo and (
            intent_profile.constraints.get("preserve_geometry")
            or prompt_touches_visuals
        ):
            include_geometry_preservation = True

        # Visuals: explicit request OR "visual_edit" signal
        if intent_profile.constraints.get("visual_requested") or any(
            s.name == "visual_edit" for s in intent_profile.signals
        ):
            include_visuals = True

    # Fallback: if no intent profile, still protect custom geometry on visual prompts
    if has_custom_geo and prompt_touches_visuals and not include_geometry_preservation:
        include_geometry_preservation = True

    # Loot: simple keyword heuristic (not yet a first-class intent)
    if any(k in user_prompt_l for k in ("drop", "drops", "loot", "on death", "upon death")):
        include_loot = True

    sections_included = []
    if category == "entity_logic_ai":
        sections_included.append("behavior")
    if include_geometry:
        sections_included.append("geometry")
    if include_geometry_preservation:
        sections_included.append("geometry_preservation")
    if include_visuals:
        sections_included.append("visuals")
    if include_loot:
        sections_included.append("loot")

    prompt = build_llm_system_prompt(
        include_behavior=(category == "entity_logic_ai"),
        include_geometry=include_geometry,
        include_geometry_rules=include_geometry,
        include_geometry_preservation=include_geometry_preservation,
        include_visuals=include_visuals,
        include_loot=include_loot,
    )

    # MCP authoritative schema — placed early for primacy effect
    if mcp_context and mcp_context.schema_text:
        prompt += "\n\n--- AUTHORITATIVE BEDROCK SCHEMA (from Minecraft Creator Tools) ---\n"
        prompt += "Use this schema as the ground truth for valid fields, types, and value ranges:\n"
        prompt += mcp_context.schema_text
        prompt += "\n--- END SCHEMA ---"

    cat_context = CATEGORY_CONTEXT.get(category, "")
    if cat_context:
        prompt += f"\n\n{cat_context}"

    # Extremely large vanilla component reference — include only when
    # (1) MCP schema is unavailable and (2) the user is likely asking for
    # exact component-field correctness.
    wants_exact_fields = any(
        k in user_prompt_l
        for k in ("valid fields", "valid_fields", "exact fields", "field names", "schema", "component reference")
    )
    if category == "entity_logic_ai" and wants_exact_fields and not (mcp_context and mcp_context.schema_text):
        if ENTITY_COMPONENT_REFERENCE_TEXT:
            prompt += f"\n\n{ENTITY_COMPONENT_REFERENCE_TEXT}"

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

    # Dynamic context — placed last for recency effect (LLMs attend more to end)
    if dynamic_ctx and dynamic_ctx.has_content:
        prompt += f"\n\n{dynamic_ctx.context_text}"

    if intent_profile and intent_profile.has_content:
        prompt += f"\n\n{intent_profile.to_prompt_block()}"

    mcp_tag = ""
    if mcp_context and mcp_context.has_content:
        mcp_tag = f", mcp_sources={mcp_context.source_tools}"
    dyn_tag = ""
    if dynamic_ctx and dynamic_ctx.has_content:
        intent_names = [i.name for i in dynamic_ctx.intents]
        dyn_tag = f", dynamic_intents={intent_names}"

    char_count = len(prompt)
    # Rough token estimate: ~4 chars per token
    token_estimate = char_count // 4

    if char_count > MAX_SYSTEM_PROMPT_CHARS:
        prompt = prompt[:MAX_SYSTEM_PROMPT_CHARS] + "\n... [system prompt truncated for token budget]"
        print(f"[LLM] WARNING: System prompt truncated to {MAX_SYSTEM_PROMPT_CHARS} chars (~{MAX_SYSTEM_PROMPT_CHARS // 4} tokens)")

    print(
        f"[LLM] Dynamic prompt built | category={category} | "
        f"sections=[{', '.join(sections_included) if sections_included else 'base'}] | "
        f"~{token_estimate} tokens ({char_count} chars)"
        f"{mcp_tag}{dyn_tag}"
    )

    return prompt, token_estimate, sections_included


def _get_legacy_system_prompt_for_tests(
    user_prompt: str,
    current_spec: Optional[dict] = None,
    category: str = "entity_logic_ai",
    mcp_context: Optional[MCPContext] = None,
    dynamic_ctx: Optional[DynamicContext] = None,
    intent_profile: Optional[PromptIntentProfile] = None,
) -> str:
    """Build a 'legacy-sized' prompt for regression tests.

    This approximates the previous behavior where we included a very large,
    mostly-static system prompt plus broad category context.
    """
    # Base prompt: include all sections
    prompt = build_llm_system_prompt(
        include_behavior=(category == "entity_logic_ai"),
        include_geometry=True,
        include_geometry_rules=True,
        include_geometry_preservation=True,
        include_visuals=True,
        include_loot=True,
    )

    # MCP schema early (same as real builder)
    if mcp_context and mcp_context.schema_text:
        prompt += "\n\n--- AUTHORITATIVE BEDROCK SCHEMA (from Minecraft Creator Tools) ---\n"
        prompt += "Use this schema as the ground truth for valid fields, types, and value ranges:\n"
        prompt += mcp_context.schema_text
        prompt += "\n--- END SCHEMA ---"

    cat_context = CATEGORY_CONTEXT.get(category, "")
    if cat_context:
        prompt += f"\n\n{cat_context}"

    # Legacy behavior: the vanilla component reference was effectively always present
    # for entity prompts (embedded inside CATEGORY_CONTEXT).
    if category == "entity_logic_ai" and ENTITY_COMPONENT_REFERENCE_TEXT:
        prompt += f"\n\n{ENTITY_COMPONENT_REFERENCE_TEXT}"

    # MCP templates
    if mcp_context and mcp_context.template_text:
        prompt += "\n\n--- MODEL TEMPLATES (from Minecraft Creator Tools) ---\n"
        prompt += "Use these as starting points when creating or modifying geometry:\n"
        prompt += mcp_context.template_text
        prompt += "\n--- END TEMPLATES ---"

    # Schema
    cat_schema = CATEGORY_SCHEMAS.get(category)
    if cat_schema:
        prompt += f"\n\nSchema:\n{json.dumps(cat_schema, indent=2)}"
    elif category == "entity_logic_ai" and SPEC_SCHEMA:
        prompt += f"\n\nSchema:\n{json.dumps(SPEC_SCHEMA, indent=2)}"

    # Dynamic context + intent (same as real builder)
    if dynamic_ctx and dynamic_ctx.has_content:
        prompt += f"\n\n{dynamic_ctx.context_text}"
    if intent_profile and intent_profile.has_content:
        prompt += f"\n\n{intent_profile.to_prompt_block()}"

    if len(prompt) > MAX_SYSTEM_PROMPT_CHARS:
        prompt = prompt[:MAX_SYSTEM_PROMPT_CHARS] + "\n... [system prompt truncated for token budget]"
    return prompt


def _get_compact_system_prompt(
    category: str = "entity_logic_ai",
    intent_profile: Optional[PromptIntentProfile] = None,
) -> str:
    """Build a compact system prompt for lower token usage."""
    prompt = LLM_SYSTEM_PROMPT_COMPACT
    if intent_profile and intent_profile.has_content:
        prompt += f"\n\n{intent_profile.to_prompt_block()}"
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
                 mcp_context: Optional[MCPContext] = None,
                 dynamic_ctx: Optional[DynamicContext] = None,
                 intent_profile: Optional[PromptIntentProfile] = None) -> dict:
    """Call OpenAI to rewrite a spec based on a user prompt."""
    print("[LLM] calling OpenAI model", LLM_MODEL_NAME)
    client = _get_openai_client(api_key)
    sys_prompt, _tok, _sec = _get_full_system_prompt(prompt, current, category, mcp_context, dynamic_ctx, intent_profile)
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
    _sanitize_geometry_json(candidate)
    if category == "entity_logic_ai":
        candidate = sanitize_spec(candidate)
        return validate_spec(candidate)
    return candidate


def _call_deepseek(prompt: str, current: dict, api_key: Optional[str],
                   category: str = "entity_logic_ai",
                   mcp_context: Optional[MCPContext] = None,
                   dynamic_ctx: Optional[DynamicContext] = None,
                   intent_profile: Optional[PromptIntentProfile] = None) -> dict:
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
                    "content": _get_full_system_prompt(prompt, current, category, mcp_context, dynamic_ctx, intent_profile)[0]
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
        _sanitize_geometry_json(candidate)
        if category == "entity_logic_ai":
            return validate_spec(candidate)
        return candidate
    except Exception as exc:
        print(f"[LLM] DeepSeek request failed: {exc}")
        raise RuntimeError(f"DeepSeek request failed: {exc}") from exc


def _call_gemini(prompt: str, current: dict, api_key: Optional[str],
                 category: str = "entity_logic_ai",
                 mcp_context: Optional[MCPContext] = None,
                 dynamic_ctx: Optional[DynamicContext] = None,
                 intent_profile: Optional[PromptIntentProfile] = None) -> dict:
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
                "system_instruction": _get_full_system_prompt(prompt, current, category, mcp_context, dynamic_ctx, intent_profile)[0],
                "response_mime_type": "application/json"
            }
        )
        content = response.text
        candidate = json.loads(content)
        _sanitize_geometry_json(candidate)
        if category == "entity_logic_ai":
            candidate = sanitize_spec(candidate)
            return validate_spec(candidate)
        return candidate
    except Exception as exc:
        print(f"[LLM] Gemini request failed: {exc}")
        raise RuntimeError(f"Gemini request failed: {exc}") from exc


def _call_ollama(prompt: str, current: dict, api_key: Optional[str] = None,
                 category: str = "entity_logic_ai",
                 mcp_context: Optional[MCPContext] = None,
                 dynamic_ctx: Optional[DynamicContext] = None,
                 intent_profile: Optional[PromptIntentProfile] = None) -> dict:
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
                "content": _get_full_system_prompt(prompt, current, category, mcp_context, dynamic_ctx, intent_profile)[0]
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
        _sanitize_geometry_json(candidate)
        if category == "entity_logic_ai":
            return validate_spec(candidate)
        return candidate
    except Exception as exc:
        print(f"[LLM] Ollama request failed: {exc}")
        raise RuntimeError(f"Ollama request failed: {exc}") from exc


def _call_claude(prompt: str, current: dict, api_key: Optional[str],
                 category: str = "entity_logic_ai",
                 mcp_context: Optional[MCPContext] = None,
                 dynamic_ctx: Optional[DynamicContext] = None,
                 intent_profile: Optional[PromptIntentProfile] = None,
                 model_name: Optional[str] = None) -> dict:
    """Call Anthropic Claude to rewrite a spec based on a user prompt."""
    if anthropic is None:
        raise RuntimeError("anthropic package is not installed.")
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Provide ANTHROPIC_API_KEY (either in the form field or as an environment variable).")

    model_to_use = model_name or CLAUDE_MODEL_NAME
    print("[LLM] calling Claude model", model_to_use)
    try:
        client = anthropic.Anthropic(api_key=key)
        
        response = client.messages.create(
            model=model_to_use,
            max_tokens=2048,
            system=_get_full_system_prompt(prompt, current, category, mcp_context, dynamic_ctx, intent_profile)[0],
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
        _sanitize_geometry_json(candidate)
        candidate = sanitize_spec(candidate)
        candidate = sanitize_spec(candidate)
        candidate = sanitize_spec(candidate)
        candidate = sanitize_spec(candidate)
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
    dynamic_ctx: Optional[DynamicContext] = None,
    intent_profile: Optional[PromptIntentProfile] = None,
) -> dict:
    """Route to the appropriate LLM provider."""
    if provider_key == "deepseek":
        return _call_deepseek(prompt, current, api_key, category, mcp_context, dynamic_ctx, intent_profile)
    elif provider_key == "gemini":
        return _call_gemini(prompt, current, api_key, category, mcp_context, dynamic_ctx, intent_profile)
    elif provider_key == "claude" or provider_key == "claude-sonnet":
        return _call_claude(prompt, current, api_key, category, mcp_context, dynamic_ctx, intent_profile, model_name="claude-sonnet-4-20250514")
    elif provider_key == "claude-opus":
        return _call_claude(prompt, current, api_key, category, mcp_context, dynamic_ctx, intent_profile, model_name="claude-opus-4-20250514")
    elif provider_key == "ollama":
        return _call_ollama(prompt, current, api_key, category, mcp_context, dynamic_ctx, intent_profile)
    else:
        return _call_openai(prompt, current, api_key, category, mcp_context, dynamic_ctx, intent_profile)


def _short_summary(text: str, limit: int = 140) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _stage_record(name: str, status: str, summary: str = "", **artifacts) -> dict:
    stage = {
        "name": name,
        "status": status,
        "summary": _short_summary(summary),
    }
    if artifacts:
        stage["artifacts"] = artifacts
    return stage


def _build_repair_prompt(
    original_prompt: str,
    validation_errors: list[str],
    intent_profile: Optional[PromptIntentProfile],
) -> str:
    lines = [
        "Repair the current spec. Do not redesign it from scratch.",
        f"Original instruction: {original_prompt.strip()}",
    ]
    if intent_profile and intent_profile.has_content:
        lines.append("")
        lines.append(intent_profile.to_prompt_block())
    lines.append("")
    lines.append("Validation issues to fix:")
    for error in validation_errors[:10]:
        lines.append(f"- {error}")
    lines.append("")
    lines.append("Return the corrected complete spec as JSON only.")
    return "\n".join(lines)


def llm_rewrite_spec(prompt: str, current: dict, provider: str,
                     api_key: Optional[str],
                     category: str = "entity_logic_ai",
                     use_plan: bool = False) -> dict:
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

    intent_profile = extract_prompt_intents(effective_prompt, category)
    if intent_profile.has_content:
        signal_names = [signal.name for signal in intent_profile.signals]
        print(f"[LLM] Intent extraction: signals={signal_names}, template_hint={intent_profile.template_hint}")

    pipeline_meta = {
        "category": category,
        "detected_category": detected_category,
        "intent_profile": intent_profile.to_dict(),
        "stages": [
            _stage_record(
                "intent_extraction",
                "completed",
                "Structured prompt facts extracted",
                intent_profile=intent_profile.to_dict(),
            )
        ],
    }
    repair_meta = {
        "attempted": False,
        "succeeded": False,
        "errors": [],
    }

    # --- Step 1a: MCP context retrieval (additive, never blocking) ---
    mcp_ctx = retrieve_context_sync(effective_prompt, category, current)
    if mcp_ctx and mcp_ctx.has_content:
        print(f"[LLM] MCP context retrieved in {mcp_ctx.retrieval_ms}ms "
              f"(sources={mcp_ctx.source_tools})")
        pipeline_meta["stages"].append(
            _stage_record(
                "mcp_context",
                "completed",
                f"Retrieved context from {', '.join(mcp_ctx.source_tools)}",
                retrieval_ms=mcp_ctx.retrieval_ms,
                sources=mcp_ctx.source_tools,
            )
        )
    else:
        pipeline_meta["stages"].append(
            _stage_record("mcp_context", "skipped", "No MCP context retrieved")
        )

    # --- Step 1b: Dynamic context injection (prompt-analyzed) ---
    dyn_ctx = build_dynamic_context(effective_prompt, category)
    if dyn_ctx.has_content:
        intent_names = [i.name for i in dyn_ctx.intents]
        print(f"[LLM] Dynamic context: intents={intent_names}, "
              f"examples={dyn_ctx.example_mobs_used}, "
              f"chars={dyn_ctx.total_chars}")
        pipeline_meta["stages"].append(
            _stage_record(
                "dynamic_context",
                "completed",
                f"Injected intent docs for {', '.join(intent_names)}",
                intents=intent_names,
                examples=dyn_ctx.example_mobs_used,
                chars=dyn_ctx.total_chars,
            )
        )
    else:
        pipeline_meta["stages"].append(
            _stage_record("dynamic_context", "skipped", "No dynamic context selected")
        )

    # Capture prompt token count + sections for pipeline metadata
    _, _prompt_tokens, _prompt_sections = _get_full_system_prompt(
        effective_prompt, current, category, mcp_ctx, dyn_ctx, intent_profile
    )
    pipeline_meta["prompt_tokens"] = _prompt_tokens
    pipeline_meta["prompt_sections"] = _prompt_sections

    start_time = time.time()
    output_spec = None
    error_msg = None
    validation_passed = True
    semantic_score = None
    mcp_validation: Optional[MCPValidationResult] = None

    # --- Step 1c: Orchestration — plan then execute (auto for ollama, opt-in otherwise) ---
    orchestrated_prompt = effective_prompt
    orchestrator_meta = None
    if should_use_orchestration(effective_prompt, provider_key, force=use_plan):
        plan = build_plan(effective_prompt, current, provider_key, api_key, category)
        if plan and plan.has_changes:
            if plan_is_simple(plan):
                # Direct apply — no Phase 2 LLM call needed
                try:
                    output_spec = apply_plan(plan, current)
                    if category == "entity_logic_ai":
                        output_spec = sanitize_spec(output_spec)
                        output_spec = validate_spec(output_spec)
                    orchestrator_meta = {
                        "plan": plan.to_dict(),
                        "applied_directly": True,
                        "fell_back_to_llm": False,
                    }
                    pipeline_meta["stages"].append(
                        _stage_record(
                            "planning",
                            "completed",
                            "Plan applied directly without a second generation pass",
                            plan=plan.to_dict(),
                            applied_directly=True,
                        )
                    )
                    print(f"[ORCHESTRATOR] Plan applied directly (no Phase 2)")
                except Exception as exc:
                    log.warning("[ORCHESTRATOR] Direct apply failed, falling back to Phase 2: %s", exc)
                    output_spec = None  # reset so Phase 2 runs
                    orchestrated_prompt = format_plan_for_prompt(effective_prompt, plan)
                    orchestrator_meta = {
                        "plan": plan.to_dict(),
                        "applied_directly": False,
                        "fell_back_to_llm": True,
                    }
                    pipeline_meta["stages"].append(
                        _stage_record(
                            "planning",
                            "completed",
                            "Simple plan generated; using guided rewrite fallback",
                            plan=plan.to_dict(),
                            applied_directly=False,
                        )
                    )
            else:
                # Complex plan — use Phase 2 (full LLM rewrite guided by plan)
                orchestrated_prompt = format_plan_for_prompt(effective_prompt, plan)
                orchestrator_meta = {
                    "plan": plan.to_dict(),
                    "applied_directly": False,
                    "fell_back_to_llm": True,
                }
                pipeline_meta["stages"].append(
                    _stage_record(
                        "planning",
                        "completed",
                        "Complex plan generated for guided rewrite",
                        plan=plan.to_dict(),
                        applied_directly=False,
                    )
                )
                print(f"[ORCHESTRATOR] Complex plan, using Phase 2 ({len(orchestrated_prompt)} chars)")
        else:
            pipeline_meta["stages"].append(
                _stage_record("planning", "skipped", "Planner returned no actionable changes")
            )
            print("[ORCHESTRATOR] Plan empty or failed, using direct prompt")
    else:
        pipeline_meta["stages"].append(
            _stage_record("planning", "skipped", "Planning disabled for this provider/prompt")
        )

    try:
        # --- Step 2: LLM call with enriched prompt (skip if plan was applied directly) ---
        if output_spec is None:
            output_spec = _call_provider(
                orchestrated_prompt, current, provider_key, api_key, category, mcp_ctx, dyn_ctx, intent_profile,
            )
            pipeline_meta["stages"].append(
                _stage_record(
                    "generation",
                    "completed",
                    f"Generated spec with provider {provider_key}",
                    provider=provider_key,
                )
            )
        else:
            pipeline_meta["stages"].append(
                _stage_record("generation", "skipped", "Generation skipped because the plan was applied directly")
            )

        # --- Step 2b: Preserve custom geometry if LLM dropped it ---
        if output_spec and category == "entity_logic_ai":
            output_spec = _preserve_geometry(output_spec, current)

        # --- Step 2c: Auto-fetch geometry for non-vanilla mobs with empty geometry ---
        if output_spec and category == "entity_logic_ai":
            output_spec = _auto_fetch_geometry(
                output_spec, prompt, provider_key, api_key,
            )

        # Run semantic consistency check
        if LOGGING_ENABLED and output_spec:
            score_result = check_semantic_consistency(output_spec)
            if score_result:
                semantic_score = score_result.score

        # --- Step 3: MCP post-validation (advisory) ---
        if output_spec:
            mcp_validation = mcp_validate_sync(output_spec)
            if mcp_validation and mcp_validation.available:
                pipeline_meta["stages"].append(
                    _stage_record(
                        "validation",
                        "completed" if mcp_validation.valid else "failed",
                        "MCP validation completed",
                        valid=mcp_validation.valid,
                        errors=mcp_validation.errors[:5],
                    )
                )
            else:
                pipeline_meta["stages"].append(
                    _stage_record("validation", "skipped", "MCP validation unavailable")
                )

        # --- Step 4: Retry once if MCP found retryable errors ---
        if (mcp_validation and not mcp_validation.valid
                and mcp_validation.available
                and is_retryable(mcp_validation.errors)):
            retry_prompt = _build_repair_prompt(prompt, mcp_validation.errors, intent_profile)
            print(f"[LLM] MCP validation found {len(mcp_validation.errors)} error(s), "
                  f"retrying with error feedback")
            repair_meta["attempted"] = True
            repair_meta["errors"] = mcp_validation.errors[:10]
            try:
                output_spec = _call_provider(
                    retry_prompt, output_spec, provider_key,
                    api_key, category, mcp_ctx, dyn_ctx, intent_profile,
                )
                # Re-validate after retry
                mcp_validation = mcp_validate_sync(output_spec)
                repair_meta["succeeded"] = bool(mcp_validation and mcp_validation.valid)
                pipeline_meta["stages"].append(
                    _stage_record(
                        "repair",
                        "completed" if repair_meta["succeeded"] else "failed",
                        "Validation-driven repair pass completed",
                        valid_after_repair=mcp_validation.valid if mcp_validation else None,
                        errors=(mcp_validation.errors[:5] if mcp_validation else []),
                    )
                )
            except Exception as retry_exc:
                log.warning("[LLM] Retry after MCP validation failed: %s", retry_exc)
                repair_meta["errors"] = repair_meta["errors"] + [str(retry_exc)]
                pipeline_meta["stages"].append(
                    _stage_record("repair", "failed", str(retry_exc))
                )
        else:
            pipeline_meta["stages"].append(
                _stage_record("repair", "skipped", "No retryable validation errors")
            )

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
    
    # --- Step 5: Texture generation ---
    # Always generate a texture for entity specs so the 3D viewer and
    # painter have something to display.  Priority:
    #   1. MCP designModel (best quality, requires mctools running)
    #   2. Procedural UV-aware generator (always available, body-part
    #      coloring, patterns, eyes, etc.)
    texture_b64 = ""
    if output_spec and category == "entity_logic_ai":
        geo = output_spec.get("geometry_json")
        has_geo = geo and isinstance(geo, dict) and geo.get("minecraft:geometry")

        # Try MCP texture first
        if has_geo:
            safe_id = (output_spec.get("short_name") or "custom_mob").replace(":", "_")
            try:
                design_result = mcp_design_model_sync(
                    geo, safe_id, prompt,
                    color_rgb=output_spec.get("color_rgb"),
                    display_name=output_spec.get("display_name", ""),
                )
                if design_result.available and design_result.texture_b64:
                    texture_b64 = design_result.texture_b64
                    if design_result.geometry:
                        output_spec["geometry_json"] = design_result.geometry
                    print(f"[LLM] MCP texture generated ({len(texture_b64)} chars)")
            except Exception as tex_exc:
                log.warning("[LLM] MCP texture generation failed: %s", tex_exc)

        # Fallback: procedural UV-mapped texture
        if not texture_b64 and has_geo:
            try:
                texture_b64 = generate_mob_texture(
                    geometry_json=geo,
                    display_name=output_spec.get("display_name", ""),
                    color_rgb=output_spec.get("color_rgb"),
                    texture_hint=output_spec.get("texture_hint", ""),
                    short_name=output_spec.get("short_name", "custom_mob"),
                    texture_instructions=output_spec.get("texture_instructions"),
                )
                if texture_b64:
                    print(f"[LLM] Procedural texture generated ({len(texture_b64)} chars)")
            except Exception as tex_exc:
                log.warning("[LLM] Procedural texture generation failed: %s", tex_exc)

    pipeline_meta["stages"].append(
        _stage_record(
            "texture",
            "completed" if texture_b64 else "skipped",
            "Generated entity texture" if texture_b64 else "No texture generated",
            generated=bool(texture_b64),
        )
    )

    # Attach MCP metadata to the spec for the route handler to surface
    if output_spec is not None:
        output_spec["_mcp_meta"] = {
            "augmented": bool(mcp_ctx and mcp_ctx.has_content) or bool(dyn_ctx and dyn_ctx.has_content),
            "context_sources": mcp_ctx.source_tools if mcp_ctx else [],
            "retrieval_ms": mcp_ctx.retrieval_ms if mcp_ctx else 0,
            "intent_profile": intent_profile.to_dict(),
            "dynamic_context": {
                "intents": [i.name for i in dyn_ctx.intents] if dyn_ctx else [],
                "examples_used": dyn_ctx.example_mobs_used if dyn_ctx else [],
                "chars_injected": dyn_ctx.total_chars if dyn_ctx else 0,
            },
            "validation": {
                "ran": bool(mcp_validation and mcp_validation.available),
                "valid": mcp_validation.valid if mcp_validation else True,
                "messages": (mcp_validation.errors[:5] if mcp_validation else []),
            },
        }
        if texture_b64:
            output_spec["_texture_b64"] = texture_b64
        if orchestrator_meta:
            output_spec["_orchestrator_meta"] = orchestrator_meta
        output_spec["_pipeline_meta"] = {
            **pipeline_meta,
            "repair": repair_meta,
        }

    # Sanitize components: strip nulls, remove invalid fields, resolve conflicts,
    # validate projectiles. This catches LLM hallucinations that Bedrock silently ignores.
    if output_spec:
        output_spec = sanitize_spec(output_spec)

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
        "visible_bounds_width": 6,
        "visible_bounds_height": 6,
        "visible_bounds_offset": [0, 2, 0]
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
        elif provider_key == "claude" or provider_key == "claude-sonnet":
            output = _call_geometry_claude(user_content, api_key, mcp_template_text, model_name="claude-sonnet-4-20250514")
        elif provider_key == "claude-opus":
            output = _call_geometry_claude(user_content, api_key, mcp_template_text, model_name="claude-opus-4-20250514")
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

    # After LLM generates geometry, create a matching texture
    # Priority: MCP designModel → procedural generator
    texture_b64 = ""
    mcp_design_used = False
    if output and isinstance(output, dict) and output.get("minecraft:geometry"):
        safe_name = mob_name.replace(":", "_").replace(" ", "_").lower()
        print(f"[LLM-GEOMETRY] Calling MCP designModel for texture (model={safe_name})")
        design_result = mcp_design_model_sync(
            output, safe_name, prompt,
            display_name=mob_name,
        )
        if design_result.available and design_result.texture_b64:
            texture_b64 = design_result.texture_b64
            mcp_design_used = True
            print(f"[LLM-GEOMETRY] MCP texture generated ({len(texture_b64)} chars)")
            if design_result.geometry:
                output = design_result.geometry
        elif design_result.error:
            print(f"[LLM-GEOMETRY] MCP texture failed: {design_result.error}")

        # Fallback: procedural UV-mapped texture
        if not texture_b64:
            try:
                texture_b64 = generate_mob_texture(
                    geometry_json=output,
                    display_name=mob_name,
                    short_name=safe_name,
                )
                if texture_b64:
                    print(f"[LLM-GEOMETRY] Procedural texture generated ({len(texture_b64)} chars)")
            except Exception as tex_exc:
                log.warning("[LLM-GEOMETRY] Procedural texture failed: %s", tex_exc)

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
                          mcp_template_text: str = "",
                          model_name: Optional[str] = None) -> dict:
    """Call Claude to generate geometry."""
    if anthropic is None:
        raise RuntimeError("anthropic package not installed")
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Provide ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=key)
    model_to_use = model_name or CLAUDE_MODEL_NAME
    print("[LLM] calling Claude model for geometry", model_to_use)
    response = client.messages.create(
        model=model_to_use,
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

