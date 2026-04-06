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
)
from backend.llm.mcp_context import mcp_validate_sync

log = logging.getLogger(__name__)

# Animation controller format_version
AC_FORMAT_VERSION = "1.8.0"


def _fetch_mojang_animation_controller_sample(mob_name: str) -> Optional[dict]:
    """Fetch animation_controllers.json sample from Mojang's bedrock-samples GitHub repository.
    
    Downloads actual animation controller examples from:
    https://github.com/Mojang/bedrock-samples/tree/main/resource_pack/animation_controllers
    
    Args:
        mob_name: Mob name (e.g., 'chicken', 'cow', 'zombie')
    
    Returns:
        Parsed animation controller JSON dict or None if not found
    """
    import urllib.request
    import urllib.error
    
    base_url = "https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/animation_controllers"
    
    candidates = [
        f"{mob_name}.animation_controllers.json",
    ]
    
    for filename in candidates:
        url = f"{base_url}/{filename}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BedrockAddonBuilder/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                print(f"[MOJANG-CTRL] ✓ Fetched {filename} from bedrock-samples")
                return data
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
            continue
    
    print(f"[MOJANG-CTRL] ✗ Could not fetch animation controller for '{mob_name}' from bedrock-samples")
    return None


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

⚠️  CRITICAL NOTICE: The "animations" arrays in your states will be overwritten by code 
to ensure correct short-name to full-ID mappings. YOU DO NOT NEED TO GET THEM PERFECT.
Focus on: state names, transitions, and conditions.

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


def _get_claude_model_name(provider: str) -> str:
    """Determine Claude model ID from provider string.
    
    Maps provider variants to actual model IDs:
    - "claude-sonnet-4.6" or "claude-sonnet" → claude-3-5-sonnet (latest)
    - "claude-opus" → claude-opus-4-20250514 (latest)
    - Default → CLAUDE_MODEL_NAME (from env or default)
    """
    provider_lower = provider.lower() if provider else ""
    
    if "opus" in provider_lower:
        return "claude-opus-4-20250514"
    elif "sonnet" in provider_lower:
        # Use latest Sonnet model (same as in llm.py)
        return "claude-sonnet-4-20250514"
    else:
        # Fall back to configured default
        return CLAUDE_MODEL_NAME


def _call_ac_claude(
    prompt: str,
    system_prompt: str,
    api_key: str,
    provider: str = "claude",
) -> Optional[dict]:
    """Call Claude to generate animation controller.
    
    Args:
        prompt: User prompt
        system_prompt: System prompt
        api_key: Anthropic API key
        provider: Provider string (e.g., "claude-sonnet-4.6" or "claude-opus") to select model
    """
    try:
        import httpx
        
        model = _get_claude_model_name(provider)
        print(f"[AC-CLAUDE] Using model: {model} (provider: {provider})")
        
        client = httpx.Client(timeout=30)
        response = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": model,
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


def _validate_animation_controller_with_retry(
    ac_dict: dict,
    mob_name: str,
    provider: str,
    api_key: Optional[str],
    max_retries: int = 3,
) -> tuple[Optional[dict], bool]:
    """Validate animation controller and retry with LLM feedback if validation fails.
    
    Similar to animation validation, feed validation errors back to the LLM to
    fix small issues rather than discarding the whole generation.
    
    Args:
        ac_dict: The generated animation_controllers.json as dict
        mob_name: Name of the mob
        provider: LLM provider to use for fixes
        api_key: API key for the provider
        max_retries: Maximum number of validation attempts (default 3)
    
    Returns:
        tuple of (validated_ac_dict or None, was_valid_on_first_try)
    """
    print(f"[AC-VALIDATE] Starting validation with up to {max_retries} retries")
    
    for attempt in range(1, max_retries + 1):
        print(f"[AC-VALIDATE] Attempt {attempt}/{max_retries}")
        
        # Validate current animation controller
        try:
            validation = mcp_validate_sync(
                content=ac_dict,
                schema_type="animation_controller",
            )
            is_valid = validation.valid if validation else False
            errors = validation.errors if validation else []
        except Exception as e:
            print(f"[AC-VALIDATE] Validation exception: {e}")
            is_valid = False
            errors = [str(e)]
        
        if is_valid:
            print(f"[AC-VALIDATE] ✓ Validation passed on attempt {attempt}")
            return (ac_dict, attempt == 1)
        
        print(f"[AC-VALIDATE] ✗ Validation failed: {len(errors)} error(s)")
        for err in errors[:3]:
            print(f"[AC-VALIDATE]   - {err}")
        
        # If this was the last attempt, return None
        if attempt >= max_retries:
            print(f"[AC-VALIDATE] ✗ Max retries ({max_retries}) reached, giving up")
            return (None, False)
        
        # Build fix-up prompt
        error_summary = "\n".join(f"  • {err}" for err in errors[:5])
        
        fix_prompt = f"""You previously generated an animation_controllers.json for '{mob_name}' that failed validation.

Validation errors:
{error_summary}

Current animation controller:
{json.dumps(ac_dict, indent=2)}

Fix ONLY the specific errors mentioned above. Keep state structure intact.
Return only the corrected animation_controllers.json, nothing else."""
        
        fix_system_prompt = """You are fixing a Minecraft Bedrock animation_controllers.json with validation errors.
Read the errors and fix ONLY those issues. Do not change state structure or transitions.
Return only valid JSON addressing the specific errors."""
        
        print(f"[AC-VALIDATE] Calling LLM to fix validation errors (attempt {attempt+1})")
        
        fixed_dict = _call_ac_provider(
            fix_prompt, fix_system_prompt, provider, api_key
        )
        
        if fixed_dict:
            print(f"[AC-VALIDATE] LLM returned fixed controller, re-validating")
            ac_dict = fixed_dict
        else:
            print(f"[AC-VALIDATE] LLM failed to return fixed controller, trying again")
    
    print(f"[AC-VALIDATE] Failed all {max_retries} validation attempts")
    return (None, False)


def _call_ac_provider(
    prompt: str,
    system_prompt: str,
    provider: str,
    api_key: Optional[str] = None,
) -> Optional[dict]:
    """Route animation controller generation to the selected provider.
    
    Supports flexible provider matching with .startswith() to handle variants
    like "openai-gpt-4o" or "deepseek-chat".
    
    Falls back to environment variables if api_key not provided:
    - OpenAI: OPENAI_API_KEY
    - DeepSeek: DEEPSEEK_API_KEY
    - Gemini: GEMINI_API_KEY
    - Claude: ANTHROPIC_API_KEY
    """
    
    # Normalize provider and get api_key from environment if not passed
    provider_lower = provider.lower() if provider else ""
    
    print(f"[AC-PROVIDER] Called with provider: {provider_lower}, api_key present: {bool(api_key)}")
    
    if provider_lower.startswith("openai"):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if api_key:
            print(f"[AC-PROVIDER] Routing to OpenAI")
            return _call_ac_openai(prompt, system_prompt, api_key)
        else:
            log.error(f"[AC-PROVIDER] OpenAI selected but no API key in args or OPENAI_API_KEY env")
            print(f"[AC-PROVIDER] ERROR: OpenAI selected but no OPENAI_API_KEY")
            return None
    
    elif provider_lower.startswith("deepseek"):
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if api_key:
            print(f"[AC-PROVIDER] Routing to DeepSeek")
            return _call_ac_deepseek(prompt, system_prompt, api_key)
        else:
            log.error(f"[AC-PROVIDER] DeepSeek selected but no API key in args or DEEPSEEK_API_KEY env")
            print(f"[AC-PROVIDER] ERROR: DeepSeek selected but no DEEPSEEK_API_KEY")
            return None
    
    elif provider_lower.startswith("gemini"):
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if api_key:
            print(f"[AC-PROVIDER] Routing to Gemini")
            return _call_ac_gemini(prompt, system_prompt, api_key)
        else:
            log.error(f"[AC-PROVIDER] Gemini selected but no API key in args or GEMINI_API_KEY env")
            print(f"[AC-PROVIDER] ERROR: Gemini selected but no GEMINI_API_KEY")
            return None
    
    elif provider_lower.startswith("claude"):
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            print(f"[AC-PROVIDER] Routing to Claude")
            return _call_ac_claude(prompt, system_prompt, api_key, provider=provider)
        else:
            log.error(f"[AC-PROVIDER] Claude selected but no API key in args or ANTHROPIC_API_KEY env")
            print(f"[AC-PROVIDER] ERROR: Claude selected but no ANTHROPIC_API_KEY")
            return None
    
    elif provider_lower.startswith("ollama"):
        print(f"[AC-PROVIDER] Routing to Ollama")
        return _call_ac_ollama(prompt, system_prompt)
    
    else:
        log.error(f"[AC-PROVIDER] Unknown provider: {provider}")
        print(f"[AC-PROVIDER] ERROR - Unknown provider: {provider}")
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
    
    # Fetch Mojang animation controller sample from bedrock-samples
    mojang_ctrl_sample = _fetch_mojang_animation_controller_sample(mob_name) or _fetch_mojang_animation_controller_sample("chicken")
    
    # Extract animation names for prompt context
    animation_names = list(animation_json.get("animations", {}).keys())
    
    # Build template context with Mojang samples
    template_context = ""
    if mojang_ctrl_sample:
        template_context = "\n╔═══════════════════════════════════════════════════════════╗\n"
        template_context += "║  OFFICIAL MOJANG CONTROLLER SAMPLE FROM BEDROCK-SAMPLES    ║\n"
        template_context += "╚═══════════════════════════════════════════════════════════╝\n"
        
        ctrls = mojang_ctrl_sample.get("animation_controllers", {})
        first_ctrl = next(iter(ctrls.items())) if ctrls else None
        if first_ctrl:
            ctrl_name, ctrl_data = first_ctrl
            template_context += f"\n🎬 Example controller structure (from Mojang bedrock-samples):\n"
            template_context += f'{{"  "{ctrl_name}": {json.dumps(ctrl_data, indent=2)[:1500]}...\n\n'
        else:
            template_context += json.dumps(mojang_ctrl_sample, indent=2)[:1500] + "...\n\n"
        
        template_context += "⚠️  Use this Mojang example as reference for:\n"
        template_context += "   - State transition conditions (query.is_moving, query.is_sprinting, etc.)\n"
        template_context += "   - Animation controller naming patterns\n"
        template_context += "   - Transition logic structure\n"
    
    # Build user prompt
    full_prompt = f"""Generate an animation controller for mob '{mob_name}'.

Available animations: {', '.join(animation_names)}

{template_context}

Create realistic state transitions:
- idle state when not moving
- walking state when moving (use query.is_moving)
- running state if sprinting (use query.is_sprinting)
- smooth transitions between all states

⚠️  IMPORTANT: The "animations" arrays in your states will be automatically fixed by the system
to match the available animations. Focus on getting the STATE NAMES, TRANSITIONS, and CONDITIONS right.
The animation reference names will be corrected in post-processing.

Use the Mojang reference above as a template for state structure and transition syntax.

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
    
    # Validate via MCP with automatic retry on validation errors
    print(f"[AC-GEN] Validating animation controller via MCP (with retry loop)")
    validated_ac, was_first_try_valid = _validate_animation_controller_with_retry(
        ac_dict,
        mob_name=mob_name,
        provider=provider,
        api_key=api_key,
        max_retries=3,
    )
    
    mcp_valid = validated_ac is not None
    if validated_ac:
        ac_dict = validated_ac
        print(f"[AC-GEN] ✓ MCP validation passed (first try: {was_first_try_valid})")
    else:
        print(f"[AC-GEN] ✗ MCP validation failed after retries, will return null controller")
    
    # Enforce short-name wiring in controller states
    # This replaces whatever animations arrays the LLM generated with deterministic
    # short-name to full-ID mappings, eliminating confusion between names and IDs
    if ac_dict and "animation_controllers" in ac_dict:
        from backend.llm.animation_generation import _build_controller_states
        
        # Extract animation short names from the animation_json that was passed in
        animation_short_names = []
        if animation_json and isinstance(animation_json, dict):
            for full_id in animation_json.get("animations", {}).keys():
                # Extract short name from full ID (e.g., "animation.mob.idle" → "idle")
                if full_id.startswith("animation."):
                    parts = full_id.split(".")
                    if len(parts) >= 3:
                        short_name = ".".join(parts[2:])
                        animation_short_names.append(short_name)
        
        # Fix each controller's states
        for ctrl_name, ctrl_data in ac_dict["animation_controllers"].items():
            if isinstance(ctrl_data, dict) and "states" in ctrl_data:
                ctrl_data["states"] = _build_controller_states(
                    ctrl_data["states"],
                    mob_name,
                    animation_short_names
                )
                print(f"[AC-WIRING] Fixed animation references in controller '{ctrl_name}'")
    
    # Ensure format_version
    if ac_dict and "format_version" not in ac_dict:
        ac_dict["format_version"] = AC_FORMAT_VERSION
    
    elapsed = time.time() - start_time
    
    return {
        "animation_controller": ac_dict,
        "mcp_verified": mcp_valid,
        "provider": provider,
        "elapsed_ms": int(elapsed * 1000),
    }
