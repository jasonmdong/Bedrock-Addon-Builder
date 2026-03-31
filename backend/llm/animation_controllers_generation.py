"""LLM-powered animation controller generation for Bedrock mobs.

Generates animation_controllers.json files (state machines) by:
  1. Accepting animation definitions from animation.json
  2. Generating a state machine that transitions between animations
  3. Using LLM to create realistic animation controller logic
  4. Validating via MCP schemas
  
An animation controller defines the state machine:
  idle → walking → running → idle
  
With conditions like:
  - query.is_moving determines idle vs walk
  - query.ground_speed determines walk vs run
"""

import json
import logging
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
)
from backend.llm.mcp_context import mcp_validate_sync

log = logging.getLogger(__name__)

# Animation controller format_version
AC_FORMAT_VERSION = "1.8.0"


def _extract_json_from_response(content: str) -> Optional[dict]:
    """Robustly extract JSON from LLM response content.
    
    Tries multiple strategies to extract valid JSON:
    1. Direct JSON parsing (response is pure JSON)
    2. Find JSON block by matching braces (non-greedy with "states" key)
    3. Scan for lines starting with '{' and parse from there
    4. Try to find and parse nested objects
    
    Returns parsed JSON dict or None if extraction fails.
    """
    import re
    
    # Strategy 1: Try direct parsing
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: Look for text starting with '{' and containing "states" key
    # This is more specific than the greedy r'\{.*\}' pattern
    try:
        # Find the first line that starts with whitespace followed by '{' or just '{'
        for line_idx, line in enumerate(content.split('\n')):
            stripped = line.lstrip()
            if stripped.startswith('{'):
                # Try to parse from this line onwards
                remainder = '\n'.join(content.split('\n')[line_idx:])
                
                # Use controlled bracket matching instead of greedy regex
                brace_count = 0
                end_idx = 0
                for i, char in enumerate(remainder):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end_idx = i + 1
                            break
                
                if end_idx > 0:
                    json_str = remainder[:end_idx]
                    try:
                        parsed = json.loads(json_str)
                        # Verify it looks like animation controller JSON
                        if isinstance(parsed, dict) and ("states" in parsed or "format_version" in parsed):
                            return parsed
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    
    # Strategy 3: Find largest JSON object by looking for balanced braces
    # This handles cases where there's JSON with surrounding text
    try:
        brace_positions = []
        brace_stack = []
        
        for i, char in enumerate(content):
            if char == '{':
                brace_stack.append(i)
            elif char == '}':
                if brace_stack:
                    start = brace_stack.pop()
                    if not brace_stack:  # Found a complete top-level object
                        brace_positions.append((start, i + 1))
        
        # Try the largest object first
        if brace_positions:
            brace_positions.sort(key=lambda x: x[1] - x[0], reverse=True)
            for start, end in brace_positions:
                try:
                    json_str = content[start:end]
                    parsed = json.loads(json_str)
                    if isinstance(parsed, dict) and ("states" in parsed or "format_version" in parsed):
                        return parsed
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    
    # Strategy 4: Fallback - try the old greedy regex as last resort
    # but with less greedy matching
    try:
        match = re.search(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}', content)
        if match:
            return json.loads(match.group())
    except json.JSONDecodeError:
        pass
    
    # No valid JSON found
    print(f"[EXTRACT-JSON-AC] Failed all extraction strategies on content: {content[:200]}...")
    return None


def _get_ac_system_prompt(animations: dict, mob_name: str) -> str:
    """Build system prompt for animation controller generation."""
    
    animation_names = list(animations.get("animations", {}).keys())
    animations_str = "\n".join(f"  - {name}" for name in animation_names)
    
    return f"""You are an expert Minecraft Bedrock animation controller developer.

Generate a VALID animation_controllers.json file for the mob '{mob_name}'.

AVAILABLE ANIMATIONS:
{animations_str}

REQUIRED FORMAT:
{{
  "format_version": "1.8.0",
  "animation_controllers": {{
    "controller.animation.{mob_name}": {{
      "initial_state": "idle",
      "states": {{
        "idle": {{
          "animations": ["animation.{mob_name}.idle"],
          "transitions": [
            {{"walking": "query.is_moving && !query.is_sprinting"}},
            {{"running": "query.is_sprinting"}}
          ]
        }},
        "walking": {{
          "animations": ["animation.{mob_name}.walk"],
          "transitions": [
            {{"idle": "!query.is_moving"}},
            {{"running": "query.is_sprinting"}}
          ]
        }},
        "running": {{
          "animations": ["animation.{mob_name}.walk"],
          "transitions": [
            {{"idle": "!query.is_moving"}},
            {{"walking": "!query.is_sprinting"}}
          ]
        }}
      }}
    }}
  }}
}}

CRITICAL RULES:
1. format_version MUST be "1.8.0"
2. Controller ID MUST be "controller.animation.{mob_name}"
3. State names MUST match actual animation names
4. Use query.* conditions like: query.is_moving, query.is_sprinting, query.is_airborne, query.is_swimming
5. Return ONLY the JSON, no extra text
6. Minimum 2 states (idle, moving)
7. All referenced animations MUST exist in the animations list above

AVAILABLE QUERY CONDITIONS:
- query.is_moving - Mob is moving
- query.is_sprinting - Mob is sprinting/running
- query.is_airborne - Mob is in the air
- query.is_swimming - Mob is in water
- query.is_on_ground - Mob is on solid ground
- query.ground_speed - Current movement speed (0.0-1.0+)
- query.anim_time - Current animation time"""


def _call_ac_openai(
    prompt: str,
    system_prompt: str,
    api_key: str,
) -> Optional[dict]:
    """Call OpenAI to generate animation controller."""
    try:
        import httpx
        
        client = httpx.Client(timeout=30)
        response = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": LLM_MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 2000,
            },
        )
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        # Extract JSON from response using robust extraction
        return _extract_json_from_response(content)
    except Exception as e:
        log.error(f"OpenAI AC generation failed: {e}")
        return None


def _call_ac_deepseek(
    prompt: str,
    system_prompt: str,
    api_key: str,
) -> Optional[dict]:
    """Call DeepSeek to generate animation controller."""
    try:
        import httpx
        
        client = httpx.Client(timeout=30)
        response = client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": DEEPSEEK_MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 2000,
            },
        )
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        # Extract JSON from response using robust extraction
        return _extract_json_from_response(content)
    except Exception as e:
        log.error(f"DeepSeek AC generation failed: {e}")
        return None


def _call_ac_gemini(
    prompt: str,
    system_prompt: str,
    api_key: str,
) -> Optional[dict]:
    """Call Gemini to generate animation controller."""
    try:
        import httpx
        
        client = httpx.Client(timeout=30)
        response = client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
            params={"key": api_key},
            json={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": f"{system_prompt}\n\n{prompt}"}
                        ],
                    }
                ],
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2000},
            },
        )
        response.raise_for_status()
        result = response.json()
        content = result["candidates"][0]["content"]["parts"][0]["text"]
        
        # Extract JSON from response using robust extraction
        return _extract_json_from_response(content)
    except Exception as e:
        log.error(f"Gemini AC generation failed: {e}")
        return None


def _call_ac_claude(
    prompt: str,
    system_prompt: str,
    api_key: str,
) -> Optional[dict]:
    """Call Claude to generate animation controller."""
    try:
        import httpx
        
        client = httpx.Client(timeout=30)
        response = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": CLAUDE_MODEL_NAME,
                "max_tokens": 2000,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
            },
        )
        response.raise_for_status()
        result = response.json()
        content = result["content"][0]["text"]
        
        # Extract JSON from response using robust extraction
        return _extract_json_from_response(content)
    except Exception as e:
        log.error(f"Claude AC generation failed: {e}")
        return None


def _call_ac_ollama(
    prompt: str,
    system_prompt: str,
) -> Optional[dict]:
    """Call Ollama to generate animation controller."""
    try:
        import httpx
        
        client = httpx.Client(timeout=60)
        response = client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL_NAME,
                "prompt": f"{system_prompt}\n\n{prompt}",
                "stream": False,
                "temperature": 0.7,
            },
        )
        response.raise_for_status()
        result = response.json()
        content = result.get("response", "")
        
        # Extract JSON from response using robust extraction
        return _extract_json_from_response(content)
    except Exception as e:
        log.error(f"Ollama AC generation failed: {e}")
        return None


def _call_ac_provider(
    prompt: str,
    system_prompt: str,
    provider: str,
    api_key: Optional[str] = None,
) -> Optional[dict]:
    """Route animation controller generation to the selected provider."""
    
    if provider == "openai" and api_key:
        return _call_ac_openai(prompt, system_prompt, api_key)
    elif provider == "deepseek" and api_key:
        return _call_ac_deepseek(prompt, system_prompt, api_key)
    elif provider == "gemini" and api_key:
        return _call_ac_gemini(prompt, system_prompt, api_key)
    elif provider == "claude" and api_key:
        return _call_ac_claude(prompt, system_prompt, api_key)
    elif provider == "ollama":
        return _call_ac_ollama(prompt, system_prompt)
    
    log.error(f"Unknown provider: {provider}")
    return None


def llm_generate_animation_controller(
    animation_json: dict,
    mob_name: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict:
    """Generate animation_controllers.json for a mob via LLM.
    
    Args:
        animation_json: The generated animation.json dict
        mob_name: Short name of the mob
        provider: LLM provider (openai, deepseek, gemini, claude, ollama)
        api_key: API key for cloud providers
    
    Returns:
        dict with:
          - animation_controller: The generated controller.json (dict)
          - mcp_verified: Whether MCP validation passed
          - provider: LLM provider used
          - error: Error message if generation failed
    """
    
    if not provider:
        provider = DEFAULT_LLM_PROVIDER
    
    start_time = time.time()
    
    # Build system prompt with available animations
    system_prompt = _get_ac_system_prompt(animation_json, mob_name)
    
    # Extract animation names for prompt context
    animation_names = list(animation_json.get("animations", {}).keys())
    
    # Build user prompt
    full_prompt = f"""Generate an animation controller for mob '{mob_name}'.

Available animations: {', '.join(animation_names)}

Create realistic state transitions:
- idle state when not moving
- walking state when moving (use query.is_moving)
- running state if sprinting (use query.is_sprinting)
- smooth transitions between all states

Make it a complete, valid animation_controllers.json."""
    
    # Call LLM
    ac_dict = _call_ac_provider(
        full_prompt, system_prompt, provider, api_key
    )
    
    if not ac_dict:
        return {
            "animation_controller": None,
            "mcp_verified": False,
            "provider": provider,
            "error": "LLM failed to generate animation controller",
        }
    
    # Validate via MCP
    mcp_valid = False
    try:
        validation = mcp_validate_sync(
            content=ac_dict,
            schema_type="animation_controller",
        )
        mcp_valid = validation.valid if validation else False
    except Exception as e:
        log.warning(f"MCP animation controller validation failed: {e}")
    
    # Ensure format_version
    if "format_version" not in ac_dict:
        ac_dict["format_version"] = AC_FORMAT_VERSION
    
    elapsed = time.time() - start_time
    
    return {
        "animation_controller": ac_dict,
        "mcp_verified": mcp_valid,
        "provider": provider,
        "elapsed_ms": int(elapsed * 1000),
    }
