"""LLM integration for spec editing via OpenAI and DeepSeek."""
import json
import os
from typing import Optional

from core import LLM_MODEL_NAME, DEEPSEEK_MODEL_NAME, GEMINI_MODEL_NAME, CLAUDE_MODEL_NAME, DEFAULT_LLM_PROVIDER, LLM_SYSTEM_PROMPT
from schemas_loader import SPEC_SCHEMA
from spec_utils import validate_spec, SpecValidationError

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    import google.generativeai as genai
except Exception:
    genai = None

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
    schema_text = json.dumps(SPEC_SCHEMA or {}, indent=2)
    messages = [
        {
            "role": "system",
            "content": f"{LLM_SYSTEM_PROMPT}\nSchema:\n{schema_text}"
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
        schema_text = json.dumps(SPEC_SCHEMA or {}, indent=2)

        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": f"{LLM_SYSTEM_PROMPT}\nSchema:\n{schema_text}"
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
    if genai is None:
        raise RuntimeError("google-generativeai package is not installed.")
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Provide GEMINI_API_KEY (either in the form field or as an environment variable).")

    print("[LLM] calling Gemini model", GEMINI_MODEL_NAME)
    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL_NAME,
            system_instruction=f"{LLM_SYSTEM_PROMPT}\nSchema:\n{json.dumps(SPEC_SCHEMA, indent=2)}"
        )
        response = model.generate_content(
            f"Current spec:\n{json.dumps(current, indent=2)}\n\nInstruction:\n{prompt.strip()}",
            generation_config={"response_mime_type": "application/json"}
        )
        content = response.text
        candidate = json.loads(content)
        return validate_spec(candidate)
    except Exception as exc:
        print(f"[LLM] Gemini request failed: {exc}")
        raise RuntimeError(f"Gemini request failed: {exc}") from exc


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
        schema_text = json.dumps(SPEC_SCHEMA or {}, indent=2)
        
        response = client.messages.create(
            model=CLAUDE_MODEL_NAME,
            max_tokens=2048,
            system=f"{LLM_SYSTEM_PROMPT}\nSchema:\n{schema_text}",
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
    if provider_key == "deepseek":
        return _call_deepseek(prompt, current, api_key)
    if provider_key == "gemini":
        return _call_gemini(prompt, current, api_key)
    if provider_key == "claude":
        return _call_claude(prompt, current, api_key)
    return _call_openai(prompt, current, api_key)
