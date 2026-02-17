"""LLM integration for spec editing via OpenAI and DeepSeek."""
import json
import os
import time
from typing import Optional

from backend.core.core import LLM_MODEL_NAME, DEEPSEEK_MODEL_NAME, GEMINI_MODEL_NAME, CLAUDE_MODEL_NAME, OLLAMA_MODEL_NAME, OLLAMA_BASE_URL, DEFAULT_LLM_PROVIDER, LLM_SYSTEM_PROMPT, BACKEND_DIR
from backend.schemas.schemas_loader import SPEC_SCHEMA
from backend.schemas.spec_utils import validate_spec, SpecValidationError

# Optional logging - gracefully handle if not available
try:
    from llm_logger import log_llm_call
    from llm_scoring import check_semantic_consistency
    LOGGING_ENABLED = True
except ImportError:
    LOGGING_ENABLED = False
    def log_llm_call(*args, **kwargs): pass
    def check_semantic_consistency(spec): return None

# Load vanilla reference if available
VANILLA_REF = {}
ref_path = BACKEND_DIR / "data" / "vanilla_reference.json"
if ref_path.exists():
    try:
        VANILLA_REF = json.loads(ref_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Failed to load vanilla reference: {e}")

def _get_full_system_prompt() -> str:
    """Get the full system prompt including vanilla reference context."""
    schema_text = json.dumps(SPEC_SCHEMA or {}, indent=2)
    prompt = f"{LLM_SYSTEM_PROMPT}\n\nSchema:\n{schema_text}"
    if VANILLA_REF:
        ref_text = json.dumps(VANILLA_REF, indent=2)
        prompt += f"\n\nVanilla Reference (from bedrock-samples):\n{ref_text}"
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
    """Get an OpenAI client with the provided or environment API key."""
    if OpenAI is None:
        raise RuntimeError("openai package is not installed. Install the 'openai' package.")
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Provide OPENAI_API_KEY (either in the form field or as an environment variable).")
    return OpenAI(api_key=key)


def _call_openai(prompt: str, current: dict, api_key: Optional[str]) -> dict:
    """Call OpenAI to rewrite a spec based on a user prompt."""
    print("[LLM] calling OpenAI model", LLM_MODEL_NAME)
    client = _get_openai_client(api_key)
    messages = [
        {
            "role": "system",
            "content": _get_full_system_prompt()
        },
        {
            "role": "user",
            "content": f"Current spec:\n{json.dumps(current, indent=2)}\n\nInstruction:\n{prompt.strip()}"
        }
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
    return validate_spec(candidate)


def _call_deepseek(prompt: str, current: dict, api_key: Optional[str]) -> dict:
    """Call DeepSeek to rewrite a spec based on a user prompt."""
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("Provide DEEPSEEK_API_KEY (either in the form field or as an environment variable).")

    print("[LLM] calling DeepSeek via OpenAI client")
    try:
        # DeepSeek is OpenAI-compatible
        client = OpenAI(api_key=key, base_url="https://api.deepseek.com")

        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": _get_full_system_prompt()
                },
                {
                    "role": "user",
                    "content": f"Current spec:\n{json.dumps(current, indent=2)}\n\nInstruction:\n{prompt.strip()}"
                }
            ],
            stream=False,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        candidate = json.loads(content)
        return validate_spec(candidate)
    except Exception as exc:
        print(f"[LLM] DeepSeek request failed: {exc}")
        raise RuntimeError(f"DeepSeek request failed: {exc}") from exc


def _call_gemini(prompt: str, current: dict, api_key: Optional[str]) -> dict:
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
            contents=f"Current spec:\n{json.dumps(current, indent=2)}\n\nInstruction:\n{prompt.strip()}",
            config={
                "system_instruction": _get_full_system_prompt(),
                "response_mime_type": "application/json"
            }
        )
        content = response.text
        candidate = json.loads(content)
        return validate_spec(candidate)
    except Exception as exc:
        print(f"[LLM] Gemini request failed: {exc}")
        raise RuntimeError(f"Gemini request failed: {exc}") from exc


def _call_ollama(prompt: str, current: dict, api_key: Optional[str] = None) -> dict:
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
            api_key="ollama"  # Ollama doesn't need a real key but OpenAI client requires one
        )
        
        messages = [
            {
                "role": "system",
                "content": _get_full_system_prompt()
            },
            {
                "role": "user",
                "content": f"Current spec:\n{json.dumps(current, indent=2)}\n\nInstruction:\n{prompt.strip()}\n\nRespond with ONLY the updated JSON spec, no explanation."
            }
        ]
        
        response = client.chat.completions.create(
            model=OLLAMA_MODEL_NAME,
            messages=messages,
            temperature=0.2  # Lower temperature for more consistent/deterministic outputs
        )
        
        content = response.choices[0].message.content
        
        # Try to extract JSON from the response (Ollama may include markdown)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        candidate = json.loads(content.strip())
        return validate_spec(candidate)
    except Exception as exc:
        print(f"[LLM] Ollama request failed: {exc}")
        raise RuntimeError(f"Ollama request failed: {exc}") from exc


def _call_claude(prompt: str, current: dict, api_key: Optional[str]) -> dict:
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
            system=_get_full_system_prompt(),
            messages=[
                {
                    "role": "user",
                    "content": f"Current spec:\n{json.dumps(current, indent=2)}\n\nInstruction:\n{prompt.strip()}"
                }
            ]
        )
        content = response.content[0].text
        # Claude might wrap JSON in backticks, let's extract it if so
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
            
        candidate = json.loads(content)
        return validate_spec(candidate)
    except Exception as exc:
        print(f"[LLM] Claude request failed: {exc}")
        raise RuntimeError(f"Claude request failed: {exc}") from exc


def llm_rewrite_spec(prompt: str, current: dict, provider: str, api_key: Optional[str]) -> dict:
    """Route to appropriate LLM provider and rewrite a spec."""
    provider_key = (provider or DEFAULT_LLM_PROVIDER or "openai").lower()
    
    start_time = time.time()
    output_spec = None
    error_msg = None
    validation_passed = True
    semantic_score = None
    
    try:
        if provider_key == "deepseek":
            output_spec = _call_deepseek(prompt, current, api_key)
        elif provider_key == "gemini":
            output_spec = _call_gemini(prompt, current, api_key)
        elif provider_key == "claude":
            output_spec = _call_claude(prompt, current, api_key)
        elif provider_key == "ollama":
            output_spec = _call_ollama(prompt, current, api_key)
        else:
            output_spec = _call_openai(prompt, current, api_key)
        
        # Run semantic consistency check
        if LOGGING_ENABLED and output_spec:
            score_result = check_semantic_consistency(output_spec)
            if score_result:
                semantic_score = score_result.score
        
    except SpecValidationError as exc:
        validation_passed = False
        error_msg = str(exc)
        raise
    except Exception as exc:
        error_msg = str(exc)
        raise
    finally:
        # Log the call (success or failure)
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


def _get_geometry_system_prompt() -> str:
    """Get the system prompt for geometry generation."""
    return GEOMETRY_SYSTEM_PROMPT


def llm_generate_geometry(prompt: str, current_geometry: dict | None, provider: str, api_key: str | None) -> dict:
    """Generate or modify Bedrock geometry JSON using LLM."""
    provider_key = (provider or DEFAULT_LLM_PROVIDER or "openai").lower()
    
    start_time = time.time()
    output = None
    error_msg = None
    
    user_content = prompt.strip()
    if current_geometry:
        user_content = f"Current geometry:\n{json.dumps(current_geometry, indent=2)}\n\nInstruction:\n{prompt.strip()}"
    
    try:
        if provider_key == "deepseek":
            output = _call_geometry_deepseek(user_content, api_key)
        elif provider_key == "gemini":
            output = _call_geometry_gemini(user_content, api_key)
        elif provider_key == "claude":
            output = _call_geometry_claude(user_content, api_key)
        elif provider_key == "ollama":
            output = _call_geometry_ollama(user_content, api_key)
        else:
            output = _call_geometry_openai(user_content, api_key)
            
    except Exception as exc:
        error_msg = str(exc)
        raise
    finally:
        duration_ms = int((time.time() - start_time) * 1000)
        print(f"[LLM] Geometry generation took {duration_ms}ms, provider={provider_key}")
    
    return output


def _call_geometry_openai(user_content: str, api_key: str | None) -> dict:
    """Call OpenAI to generate geometry."""
    client = _get_openai_client(api_key)
    messages = [
        {"role": "system", "content": _get_geometry_system_prompt()},
        {"role": "user", "content": user_content}
    ]
    resp = client.chat.completions.create(
        model=LLM_MODEL_NAME,
        response_format={"type": "json_object"},
        messages=messages
    )
    return json.loads(resp.choices[0].message.content)


def _call_geometry_deepseek(user_content: str, api_key: str | None) -> dict:
    """Call DeepSeek to generate geometry."""
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("Provide DEEPSEEK_API_KEY")
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL_NAME,
        messages=[
            {"role": "system", "content": _get_geometry_system_prompt()},
            {"role": "user", "content": user_content}
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(resp.choices[0].message.content)


def _call_geometry_gemini(user_content: str, api_key: str | None) -> dict:
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
            "system_instruction": _get_geometry_system_prompt(),
            "response_mime_type": "application/json"
        }
    )
    return json.loads(response.text)


def _call_geometry_claude(user_content: str, api_key: str | None) -> dict:
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
        system=_get_geometry_system_prompt(),
        messages=[{"role": "user", "content": user_content}]
    )
    content = response.content[0].text
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content)


def _call_geometry_ollama(user_content: str, api_key: str | None) -> dict:
    """Call Ollama to generate geometry."""
    if OpenAI is None:
        raise RuntimeError("openai package not installed")
    client = OpenAI(base_url=f"{OLLAMA_BASE_URL}/v1", api_key="ollama")
    response = client.chat.completions.create(
        model=OLLAMA_MODEL_NAME,
        messages=[
            {"role": "system", "content": _get_geometry_system_prompt()},
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

