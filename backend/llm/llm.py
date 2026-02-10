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
