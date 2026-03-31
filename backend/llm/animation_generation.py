"""LLM-powered animation generation for Bedrock mobs.

Generates animation.json files from geometry by:
  1. Extracting bone names from geometry_json
  2. Fetching MCP animation templates (walk, idle, fly, etc.)
  3. Building system prompt with available bones
  4. Calling LLM to generate animation JSON
  5. Validating bone references via MCP
  
Pipeline:
  geometry_json → extract bones → system prompt + templates → LLM → 
  animation.json → MCP validation → validated animation
"""

import json
import logging
import time
from typing import Optional
import asyncio

from backend.core.core import (
    LLM_MODEL_NAME, 
    DEEPSEEK_MODEL_NAME, 
    GEMINI_MODEL_NAME, 
    CLAUDE_MODEL_NAME, 
    OLLAMA_MODEL_NAME,
    OLLAMA_BASE_URL,
    DEFAULT_LLM_PROVIDER,
)
from backend.llm.mcp_context import (
    MCPContext, MCPValidationResult, retrieve_context_sync, mcp_validate_sync
)
from backend.schemas.spec_utils import SpecValidationError

log = logging.getLogger(__name__)

# Animation format_version - supports all bone animation features
ANIMATION_FORMAT_VERSION = "1.8.0"


def _extract_json_from_response(content: str) -> Optional[dict]:
    """Robustly extract JSON from LLM response content.
    
    Tries multiple strategies to extract valid JSON:
    1. Direct JSON parsing (response is pure JSON)
    2. Find JSON block by matching braces (non-greedy with "animations" key)
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
    
    # Strategy 2: Look for text starting with '{' and containing "animations" key
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
                        # Verify it looks like animation JSON
                        if isinstance(parsed, dict) and ("animations" in parsed or "format_version" in parsed):
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
                    if isinstance(parsed, dict) and ("animations" in parsed or "format_version" in parsed):
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
    print(f"[EXTRACT-JSON] Failed all extraction strategies on content: {content[:200]}...")
    return None


def validate_animation_format(animation_json: Optional[dict], mob_name: str) -> tuple[bool, list[str]]:
    """Validate animation.json format and structure.
    
    Checks:
    1. animation_json is a dict
    2. Contains "format_version" key
    3. Contains "animations" dict
    4. All animation keys are properly named (start with "animation.")
    5. No unnamed animations in the dict
    6. Each animation is a dict
    
    Returns:
        (is_valid: bool, errors: list[str])
    """
    errors = []
    
    if not animation_json:
        errors.append("animation_json is None or empty")
        return False, errors
    
    if not isinstance(animation_json, dict):
        errors.append(f"animation_json is not a dict, got {type(animation_json)}")
        return False, errors
    
    if "format_version" not in animation_json:
        errors.append("Missing 'format_version' key")
    
    if "animations" not in animation_json:
        errors.append("Missing 'animations' key")
        return False, errors
    
    animations = animation_json.get("animations", {})
    if not isinstance(animations, dict):
        errors.append(f"'animations' is not a dict, got {type(animations)}")
        return False, errors
    
    if not animations:
        errors.append("'animations' dict is empty")
        return False, errors
    
    # Validate each animation
    for anim_key, anim_value in animations.items():
        # Check if key is properly named
        if not anim_key.startswith("animation."):
            errors.append(f"Animation key '{anim_key}' does not start with 'animation.'")
        
        # Check if it's a dict (not a string, number, etc.)
        if not isinstance(anim_value, dict):
            errors.append(f"Animation '{anim_key}' is not a dict, got {type(anim_value)}")
    
    return len(errors) == 0, errors


def validate_animation_controller_format(controller_json: Optional[dict], mob_name: str) -> tuple[bool, list[str]]:
    """Validate animation_controllers.json format and structure.
    
    Checks:
    1. controller_json is a dict
    2. Contains "format_version" key
    3. Contains "animation_controllers" dict
    4. Each controller has "initial_state" and "states" keys
    5. All state names in transitions are referenced in states
    
    Returns:
        (is_valid: bool, errors: list[str])
    """
    errors = []
    
    if not controller_json:
        errors.append("animation_controller_json is None or empty")
        return False, errors
    
    if not isinstance(controller_json, dict):
        errors.append(f"animation_controller_json is not a dict, got {type(controller_json)}")
        return False, errors
    
    if "format_version" not in controller_json:
        errors.append("Missing 'format_version' key")
    
    if "animation_controllers" not in controller_json:
        errors.append("Missing 'animation_controllers' key")
        return False, errors
    
    controllers = controller_json.get("animation_controllers", {})
    if not isinstance(controllers, dict):
        errors.append(f"'animation_controllers' is not a dict, got {type(controllers)}")
        return False, errors
    
    if not controllers:
        errors.append("'animation_controllers' dict is empty")
        return False, errors
    
    # Validate each controller
    for ctrl_key, ctrl_value in controllers.items():
        if not isinstance(ctrl_value, dict):
            errors.append(f"Controller '{ctrl_key}' is not a dict, got {type(ctrl_value)}")
            continue
        
        if "initial_state" not in ctrl_value:
            errors.append(f"Controller '{ctrl_key}' missing 'initial_state'")
        
        if "states" not in ctrl_value:
            errors.append(f"Controller '{ctrl_key}' missing 'states'")
            continue
        
        states = ctrl_value.get("states", {})
        if not isinstance(states, dict):
            errors.append(f"Controller '{ctrl_key}' 'states' is not a dict")
            continue
        
        # Check for state reference consistency
        all_state_names = set(states.keys())
        for state_name, state_value in states.items():
            if isinstance(state_value, dict):
                transitions = state_value.get("transitions", [])
                if isinstance(transitions, list):
                    for transition in transitions:
                        if isinstance(transition, dict):
                            for target_state in transition.keys():
                                if target_state not in all_state_names:
                                    errors.append(f"State '{state_name}' references unknown state '{target_state}'")
    
    return len(errors) == 0, errors


def ensure_animations_and_controller(
    animation_json: Optional[dict],
    animation_controller_json: Optional[dict],
    mob_name: str,
    geometry_json: dict,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> tuple[Optional[dict], Optional[dict], list[str]]:
    """Ensure both animation.json and animation_controller.json exist and are valid.
    
    If one is missing, generates it from the other.
    If both are missing, returns (None, None, [errors]).
    
    Args:
        animation_json: The animation.json dict (or None)
        animation_controller_json: The animation_controllers.json dict (or None)
        mob_name: Short name of the mob
        geometry_json: Geometry dict for generating animations
        provider: LLM provider for generation
        api_key: API key for cloud providers
    
    Returns:
        (validated_animation, validated_controller, validation_messages)
    """
    messages = []
    
    # Validate existing animations
    if animation_json:
        is_valid, errors = validate_animation_format(animation_json, mob_name)
        if not is_valid:
            messages.extend([f"[ANIM-VALIDATION] {e}" for e in errors])
            animation_json = None  # Mark as invalid
        else:
            messages.append(f"[ANIM-VALIDATION] animation.json is valid ({len(animation_json.get('animations', {}))} animations)")
    
    # Validate existing controller
    if animation_controller_json:
        is_valid, errors = validate_animation_controller_format(animation_controller_json, mob_name)
        if not is_valid:
            messages.extend([f"[CTRL-VALIDATION] {e}" for e in errors])
            animation_controller_json = None  # Mark as invalid
        else:
            messages.append(f"[CTRL-VALIDATION] animation_controller.json is valid")
    
    # If we have animation but no controller, generate controller
    if animation_json and not animation_controller_json:
        print(f"[AUTO-GEN-CTRL] Generating missing animation controller from animation")
        from backend.llm.animation_controllers_generation import llm_generate_animation_controller
        
        result = llm_generate_animation_controller(
            animation_json, mob_name, provider, api_key
        )
        animation_controller_json = result.get("animation_controller")
        
        if animation_controller_json:
            is_valid, errors = validate_animation_controller_format(animation_controller_json, mob_name)
            if is_valid:
                messages.append(f"[AUTO-GEN-CTRL] Successfully generated animation controller")
            else:
                messages.extend([f"[AUTO-GEN-CTRL-ERROR] {e}" for e in errors])
                animation_controller_json = None
        else:
            messages.append(f"[AUTO-GEN-CTRL] Failed to generate animation controller: {result.get('error')}")
    
    # If we have controller but no animation, generate basic animation
    elif animation_controller_json and not animation_json:
        print(f"[AUTO-GEN-ANIM] Generating missing animation from controller")
        
        # Extract animation names from controller
        controllers = animation_controller_json.get("animation_controllers", {})
        animation_names = set()
        for ctrl in controllers.values():
            for state in ctrl.get("states", {}).values():
                anims = state.get("animations", [])
                if isinstance(anims, list):
                    animation_names.update(anims)
        
        if animation_names:
            prompt = f"Generate animation.json with these animations: {', '.join(animation_names)}"
        else:
            prompt = f"Generate animation.json with walk and idle animations"
        
        result = llm_generate_animation(
            prompt, geometry_json, mob_name, provider=provider, api_key=api_key
        )
        animation_json = result.get("animation")
        
        if animation_json:
            is_valid, errors = validate_animation_format(animation_json, mob_name)
            if is_valid:
                messages.append(f"[AUTO-GEN-ANIM] Successfully generated animation")
            else:
                messages.extend([f"[AUTO-GEN-ANIM-ERROR] {e}" for e in errors])
                animation_json = None
        else:
            messages.append(f"[AUTO-GEN-ANIM] Failed to generate animation: {result.get('error')}")
    
    # If both are missing, we can't generate without at least one
    elif not animation_json and not animation_controller_json:
        messages.append("[ENSURE-ANIM] Both animation.json and animation_controller.json are missing")
        return None, None, messages
    
    return animation_json, animation_controller_json, messages


def _extract_bones_from_geometry(geometry_json: dict) -> list[str]:
    """Extract all bone names from geometry.
    
    Reads minecraft:geometry entries and gathers all bone names,
    avoiding duplicates and filtering out "root" if present.
    """
    bones = []
    if not isinstance(geometry_json, dict):
        return bones
    
    for geometry in geometry_json.get("minecraft:geometry", []):
        for bone in geometry.get("bones", []):
            bone_name = bone.get("name")
            if bone_name and bone_name != "root":
                bones.append(bone_name)
    
    return list(dict.fromkeys(bones))  # Remove duplicates, preserve order


def _get_animation_system_prompt(
    bone_names: list[str],
    mob_name: str,
    geometry_id: str,
) -> str:
    """Build system prompt for animation generation with available bones."""
    
    bones_str = ", ".join(bone_names) if bone_names else "root"
    
    return f"""You are an expert Minecraft Bedrock animation developer.

Generate a VALID animation.json file for the mob '{mob_name}'.

AVAILABLE BONES (from geometry '{geometry_id}'):
{bones_str}

REQUIRED FORMAT:
{{
  "format_version": "1.8.0",
  "animations": {{
    "animation.{mob_name}.walk": {{
      "loop": true,
      "anim_time_update": "query.modified_distance_moved",
      "bones": {{
        // Bone animations here - ONLY use bones from the list above
      }}
    }},
    "animation.{mob_name}.idle": {{
      "loop": true,
      "anim_time_update": "query.time_of_day_cycle",
      "bones": {{
        // Subtle idle animations
      }}
    }}
  }}
}}

CRITICAL RULES:
1. format_version MUST be "1.8.0"
2. Animation identifiers MUST start with "animation.{mob_name}."
3. ALL bone references MUST be from the available bones list above
4. NEVER reference bones that don't exist
5. Return ONLY the JSON, no extra text
6. Include at least 2 animations: walk and idle
7. Use standard Bedrock keyframe syntax: "rotation", "position", "scale"

ANIMATION TECHNIQUES:
- Walk: Rotate legs in opposite phase (leg0 rotates forward, leg1 back)
- Idle: Subtle head bob or tail rotation (small angles)
- Run: Faster walk cycle with more rotation
- Fly: Continuous wing rotation with body lean"""


def _fetch_animation_template_sync(animation_type: str) -> Optional[dict]:
    """Fetch animation template from MCP bedrock-samples.
    
    Tries to retrieve example animations (walk, idle, fly) from
    Mojang's bedrock-samples repository via MCP.
    """
    try:
        # First try MCP context retrieval
        from backend.llm.mcp_context import retrieve_context_sync
        
        context = retrieve_context_sync(
            prompt=f"animation template for {animation_type}",
            category="animations",
        )
        
        if context and context.template_text:
            try:
                return json.loads(context.template_text)
            except json.JSONDecodeError:
                log.warning(f"MCP template for {animation_type} is not valid JSON")
                return None
    except Exception as e:
        log.debug(f"MCP animation template retrieval failed: {e}")
    
    return None


def _call_animation_openai(
    prompt: str,
    system_prompt: str,
    api_key: str,
) -> Optional[dict]:
    """Call OpenAI GPT-4 to generate animation."""
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
        log.error(f"OpenAI animation generation failed: {e}")
        return None


def _call_animation_deepseek(
    prompt: str,
    system_prompt: str,
    api_key: str,
) -> Optional[dict]:
    """Call DeepSeek to generate animation."""
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
        log.error(f"DeepSeek animation generation failed: {e}")
        return None


def _call_animation_gemini(
    prompt: str,
    system_prompt: str,
    api_key: str,
) -> Optional[dict]:
    """Call Gemini to generate animation."""
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
        log.error(f"Gemini animation generation failed: {e}")
        return None


def _call_animation_claude(
    prompt: str,
    system_prompt: str,
    api_key: str,
) -> Optional[dict]:
    """Call Claude to generate animation."""
    print(f"[CLAUDE-ANIMATION] Starting Claude animation generation")
    try:
        import httpx
        
        # Validate API key before sending
        if not api_key:
            print(f"[CLAUDE-ANIMATION] ERROR: api_key is empty or None!")
            return None
        print(f"[CLAUDE-ANIMATION] API key length: {len(api_key)} chars, starts with: {api_key[:10]}...")
        
        client = httpx.Client(timeout=30)
        print(f"[CLAUDE-ANIMATION] Sending request to Anthropic API with model: {CLAUDE_MODEL_NAME}")
        print(f"[CLAUDE-ANIMATION] Endpoint: https://api.anthropic.com/v1/messages")
        print(f"[CLAUDE-ANIMATION] Headers: x-api-key present, anthropic-version: 2023-06-01")
        
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
        print(f"[CLAUDE-ANIMATION] Response status: {response.status_code}")
        
        if response.status_code == 404:
            print(f"[CLAUDE-ANIMATION] 404 Error - Response body: {response.text[:500]}")
            print(f"[CLAUDE-ANIMATION] This typically means an invalid API key or wrong model name")
            print(f"[CLAUDE-ANIMATION] Model being used: {CLAUDE_MODEL_NAME}")
        
        response.raise_for_status()
        result = response.json()
        print(f"[CLAUDE-ANIMATION] Response keys: {list(result.keys())}")
        content = result["content"][0]["text"]
        print(f"[CLAUDE-ANIMATION] Response content (first 500 chars): {content[:500]}")
        
        # Extract JSON from response using robust extraction
        parsed = _extract_json_from_response(content)
        if parsed:
            print(f"[CLAUDE-ANIMATION] Successfully extracted JSON, keys: {list(parsed.keys())}")
        else:
            print(f"[CLAUDE-ANIMATION] Failed to extract valid JSON from response")
        return parsed
    except Exception as e:
        print(f"[CLAUDE-ANIMATION] Exception occurred: {type(e).__name__}: {e}")
        log.error(f"Claude animation generation failed: {e}")
        return None


def _call_animation_ollama(
    prompt: str,
    system_prompt: str,
) -> Optional[dict]:
    """Call Ollama (local) to generate animation."""
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
        log.error(f"Ollama animation generation failed: {e}")
        return None


def _call_animation_provider(
    prompt: str,
    system_prompt: str,
    provider: str,
    api_key: Optional[str] = None,
) -> Optional[dict]:
    """Route animation generation to the selected provider."""
    print(f"[ANIMATION-PROVIDER] Called with provider: {provider}, api_key present: {bool(api_key)}")
    
    # Normalize provider names (handle both "openai" and "openai-gpt-4o" formats)
    provider_lower = provider.lower() if provider else ""
    
    if provider_lower.startswith("openai") and api_key:
        print(f"[ANIMATION-PROVIDER] Routing to OpenAI")
        return _call_animation_openai(prompt, system_prompt, api_key)
    elif provider_lower.startswith("deepseek") and api_key:
        print(f"[ANIMATION-PROVIDER] Routing to DeepSeek")
        return _call_animation_deepseek(prompt, system_prompt, api_key)
    elif provider_lower.startswith("gemini") and api_key:
        print(f"[ANIMATION-PROVIDER] Routing to Gemini")
        return _call_animation_gemini(prompt, system_prompt, api_key)
    elif provider_lower.startswith("claude") and api_key:
        print(f"[ANIMATION-PROVIDER] Routing to Claude with model: {CLAUDE_MODEL_NAME}")
        return _call_animation_claude(prompt, system_prompt, api_key)
    elif provider_lower.startswith("ollama"):
        print(f"[ANIMATION-PROVIDER] Routing to Ollama")
        return _call_animation_ollama(prompt, system_prompt)
    
    log.error(f"Unknown provider: {provider}")
    print(f"[ANIMATION-PROVIDER] ERROR - Unknown provider: {provider}")
    return None


def llm_generate_animation(
    prompt: str,
    geometry_json: dict,
    mob_name: str,
    current_animation: Optional[dict] = None,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict:
    """Generate animation.json for a mob via LLM.
    
    Args:
        prompt: User instruction for animation (e.g., "walking and idle animations")
        geometry_json: The geometry for the mob (used to extract bone names)
        mob_name: Short name of the mob (used in animation IDs)
        current_animation: Optional existing animation to iterate on
        provider: LLM provider (openai, deepseek, gemini, claude, ollama)
        api_key: API key for cloud providers
    
    Returns:
        dict with:
          - animation: The generated animation.json (dict)
          - mcp_verified: Whether MCP validation passed
          - bone_count: Number of bones found
          - provider: LLM provider used
          - error: Error message if generation failed
    """
    
    print(f"[ANIMATION-GEN] === START llm_generate_animation ===")
    print(f"[ANIMATION-GEN] prompt: {prompt[:100]}")
    print(f"[ANIMATION-GEN] mob_name: {mob_name}")
    print(f"[ANIMATION-GEN] provider: {provider}")
    print(f"[ANIMATION-GEN] api_key present: {bool(api_key)}")
    
    if not provider:
        provider = DEFAULT_LLM_PROVIDER
        print(f"[ANIMATION-GEN] provider was None, using default: {provider}")
    
    start_time = time.time()
    bones = _extract_bones_from_geometry(geometry_json)
    geometry_id = "geometry.custom"
    print(f"[ANIMATION-GEN] Extracted bones: {bones}")
    
    try:
        if geometry_json and "minecraft:geometry" in geometry_json:
            desc = geometry_json["minecraft:geometry"][0].get("description", {})
            geometry_id = desc.get("identifier", "geometry.custom")
            print(f"[ANIMATION-GEN] geometry_id from description: {geometry_id}")
    except (IndexError, KeyError):
        print(f"[ANIMATION-GEN] Failed to extract geometry_id, using default: {geometry_id}")
        pass
    
    # Build system prompt
    system_prompt = _get_animation_system_prompt(bones, mob_name, geometry_id)
    
    # Fetch MCP templates for context enrichment
    walk_template = _fetch_animation_template_sync("walk")
    idle_template = _fetch_animation_template_sync("idle")
    
    template_context = ""
    if walk_template or idle_template:
        template_context = "\nREFERENCE ANIMATIONS FROM MOJANG:\n"
        if walk_template:
            template_context += f"Walk example: {json.dumps(walk_template, indent=2)}\n"
        if idle_template:
            template_context += f"Idle example: {json.dumps(idle_template, indent=2)}\n"
    
    # Build user prompt
    full_prompt = f"""{prompt}

Current mob bones: {', '.join(bones) if bones else 'root'}
Geometry: {geometry_id}

{template_context}

Generate a complete, valid animation.json with proper bone references."""
    
    print(f"[ANIMATION-GEN] Calling provider: {provider}")
    # Call LLM
    animation_dict = _call_animation_provider(
        full_prompt, system_prompt, provider, api_key
    )
    print(f"[ANIMATION-GEN] Response from provider: {type(animation_dict)}")
    print(f"[ANIMATION-GEN] animation_dict is None: {animation_dict is None}")
    if animation_dict:
        print(f"[ANIMATION-GEN] animation_dict keys: {list(animation_dict.keys())}")
        print(f"[ANIMATION-GEN] animation_dict preview: {json.dumps(animation_dict, indent=2)[:500]}")
    
    if not animation_dict:
        print(f"[ANIMATION-GEN] animation_dict is None/empty, returning error response")
        return {
            "animation": None,
            "mcp_verified": False,
            "bone_count": len(bones),
            "provider": provider,
            "error": "LLM failed to generate animation",
        }
    
    # Validate via MCP
    print(f"[ANIMATION-GEN] Validating animation via MCP")
    mcp_valid = False
    try:
        validation = mcp_validate_sync(
            content=animation_dict,
            schema_type="animation",
        )
        mcp_valid = validation.valid if validation else False
        print(f"[ANIMATION-GEN] MCP validation result: {mcp_valid}")
    except Exception as e:
        print(f"[ANIMATION-GEN] MCP validation exception: {e}")
        log.warning(f"MCP animation validation failed: {e}")
    
    # Ensure format_version
    if "format_version" not in animation_dict:
        animation_dict["format_version"] = ANIMATION_FORMAT_VERSION
        print(f"[ANIMATION-GEN] Added missing format_version: {ANIMATION_FORMAT_VERSION}")
    
    elapsed = time.time() - start_time
    
    final_result = {
        "animation": animation_dict,
        "mcp_verified": mcp_valid,
        "bone_count": len(bones),
        "provider": provider,
        "elapsed_ms": int(elapsed * 1000),
    }
    print(f"[ANIMATION-GEN] === END llm_generate_animation ===")
    print(f"[ANIMATION-GEN] Final result: {json.dumps(final_result, indent=2, default=str)[:1000]}")
    return final_result


def batch_generate_animations(
    prompts: list[str],
    geometry_json: dict,
    mob_names: list[str],
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> list[dict]:
    """Generate animations for multiple mobs.
    
    Args:
        prompts: List of animation prompts
        geometry_json: Shared geometry
        mob_names: List of mob names
        provider: LLM provider
        api_key: API key
    
    Returns:
        List of animation generation results
    """
    results = []
    for prompt, mob_name in zip(prompts, mob_names):
        result = llm_generate_animation(
            prompt=prompt,
            geometry_json=geometry_json,
            mob_name=mob_name,
            provider=provider,
            api_key=api_key,
        )
        results.append(result)
    
    return results
