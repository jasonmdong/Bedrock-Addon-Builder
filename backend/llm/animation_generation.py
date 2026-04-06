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
import os
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


def _build_entity_animations_block(mob_id: str, animation_short_names: list[str]) -> dict:
    """Programmatically build the entity.json animations block.
    
    This function eliminates short-name/full-ID confusion by building the
    animations block deterministically in code instead of from LLM output.
    
    Args:
        mob_id: Short mob name (e.g., "zombie", "elephant")
        animation_short_names: List of animation short names (e.g., ["idle", "walk", "run"])
    
    Returns:
        dict with:
          - "{mob_id}_controller": "controller.animation.{mob_id}"  (controller reference)
          - "{shortname}": "animation.{mob_id}.{shortname}"  (for each animation)
    
    Example:
        >>> _build_entity_animations_block("zombie", ["idle", "walk", "run"])
        {
            "zombie_controller": "controller.animation.zombie",
            "idle": "animation.zombie.idle",
            "walk": "animation.zombie.walk",
            "run": "animation.zombie.run"
        }
    """
    controller_id = f"controller.animation.{mob_id}"
    block = {f"{mob_id}_controller": controller_id}
    
    for short_name in animation_short_names:
        animation_id = f"animation.{mob_id}.{short_name}"
        block[short_name] = animation_id
    
    print(f"[WIRING] Built entity animations block: {json.dumps(block, indent=2)}")
    return block


def _build_controller_states(states: dict, mob_id: str, animation_names: list[str]) -> dict:
    """Programmatically enforce short-name references in controller states.
    
    Takes LLM-generated states and fixes the animations arrays to use
    deterministic short-name to full-ID mappings. This prevents the LLM
    from generating incorrect animation references.
    
    Args:
        states: Dict of states from LLM (e.g., {"idle": {...}, "walk": {...}})
        mob_id: Short mob name (e.g., "zombie")
        animation_names: List of available animation short names (e.g., ["idle", "walk", "run"])
    
    Returns:
        Fixed states dict with correct animations arrays
    
    Logic:
        - For each state, the animations array should list the full animation IDs
        - By convention: state "idle" animates "animation.{mob_id}.idle"
        - Common state → animation mappings:
          - "idle" → "animation.{mob_id}.idle"
          - "walking" → "animation.{mob_id}.walk"  (fuzzy match)
          - "running" → "animation.{mob_id}.run"   (fuzzy match)
        - States without a matching animation get empty array (OK - no bone animation)
    """
    animation_name_set = set(animation_names)
    
    # Build fuzzy matching rules for common variations
    fuzzy_mappings = {
        "walking": "walk",
        "running": "run",
        "flying": "fly",
        "swim": "swimming",
        "swimming": "swim",
    }
    
    for state_name, state_data in states.items():
        correct_animations = []
        
        # Try exact match first
        if state_name in animation_name_set:
            # CRITICAL: Animation controller references SHORT NAMES (the keys from entity.json animations block)
            # NOT full IDs. The entity.json mapping handles ID translation.
            # E.g., entity.json has "idle": "animation.elephant.idle"
            # Controller just references "idle" and the entity maps it to the full ID
            correct_animations = [state_name]
        # Try fuzzy match (e.g., "walking" might map to "walk" animation)
        elif state_name in fuzzy_mappings:
            alt_name = fuzzy_mappings[state_name]
            if alt_name in animation_name_set:
                correct_animations = [alt_name]  # Use the matched animation short name
        # Try reverse fuzzy match (e.g., state "walk" from "walking" animation)
        else:
            for anim_name in animation_names:
                if anim_name in fuzzy_mappings and fuzzy_mappings[anim_name] == state_name:
                    correct_animations = [anim_name]  # Use the animation short name
                    break
        
        # States without matching animation are OK - they can transition to other states
        # but don't play a bone animation themselves
        state_data["animations"] = correct_animations
        
        print(f"[WIRING] State '{state_name}': animations = {correct_animations}")
    
    return states


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


def _normalize_animation_json(animation_json: Optional[dict], mob_name: str, bone_names: list[str] = None) -> Optional[dict]:
    """Fix malformed animation JSON structure.
    
    If the LLM returns bones at the root level instead of wrapped in an
    "animations" object, detect and fix it. This is a common failure mode.
    
    Args:
        animation_json: Potentially malformed animation dict
        mob_name: Short name of mob for animation key generation
        bone_names: List of valid bone names (for reconstruction if needed)
    
    Returns:
        Corrected animation dict, or None if it can't be salvaged
    """
    if not isinstance(animation_json, dict):
        return None
    
    # If it already has proper structure, return as-is
    if "format_version" in animation_json and "animations" in animation_json:
        return animation_json
    
    # Detect if bones are at root level or if "rotation" is used as a bone name (common malformation)
    root_keys = set(animation_json.keys())
    bone_like_keys = {k for k in root_keys if k not in ("format_version", "animations", "animation_controllers")}
    
    # Check for "rotation" bone (indicates malformed output where bones are confused with bone properties)
    has_rotation_as_bone = "rotation" in animation_json
    
    if (bone_like_keys and "animations" not in animation_json) or has_rotation_as_bone:
        print(f"[ANIM-NORMALIZE] Detected malformed structure: bones at root level or 'rotation' as bone name")
        print(f"[ANIM-NORMALIZE] Root keys: {root_keys}")
        
        # Extract format_version if present
        format_version = animation_json.get("format_version", ANIMATION_FORMAT_VERSION)
        
        # Gather bones and other animation data
        bones_data = {}
        for key in bone_like_keys:
            if key != "rotation":  # Skip the malformed "rotation" at root
                bones_data[key] = animation_json[key]
        
        # If we have rotation at root and no real bones, it's the keyframe data
        if has_rotation_as_bone or not bones_data:
            rotation_data = animation_json.get("rotation", {})
            # Create animations using all available bones or the provided list
            available_bones = bone_names if bone_names else list(bones_data.keys()) if bones_data else ["body", "head"]
            
            if available_bones:
                fixed = {
                    "format_version": format_version,
                    "animations": {
                        f"animation.{mob_name}.idle": {
                            "loop": True,
                            "anim_time_update": "query.anim_time",
                            "bones": {bone: {"rotation": rotation_data} for bone in available_bones if rotation_data}
                        },
                        f"animation.{mob_name}.walk": {
                            "loop": True,
                            "anim_time_update": "query.modified_distance_moved",
                            "bones": {bone: {"rotation": rotation_data} for bone in available_bones if rotation_data}
                        },
                        f"animation.{mob_name}.run": {
                            "loop": True,
                            "anim_time_update": "query.modified_distance_moved",
                            "bones": {bone: {"rotation": rotation_data} for bone in available_bones if rotation_data}
                        }
                    }
                }
                print(f"[ANIM-NORMALIZE] Fixed structure: created 3 animations with {len(available_bones)} bones each ({', '.join(available_bones[:3])}...)")
                return fixed
        else:
            # We have multiple root-level keys that are bone names
            fixed = {
                "format_version": format_version,
                "animations": {
                    f"animation.{mob_name}.idle": {
                        "loop": True,
                        "anim_time_update": "query.anim_time",
                        "bones": bones_data
                    },
                    f"animation.{mob_name}.walk": {
                        "loop": True,
                        "anim_time_update": "query.modified_distance_moved",
                        "bones": bones_data
                    },
                    f"animation.{mob_name}.run": {
                        "loop": True,
                        "anim_time_update": "query.modified_distance_moved",
                        "bones": bones_data
                    }
                }
            }
            print(f"[ANIM-NORMALIZE] Fixed structure: created 3 animations (idle, walk, run)")
            return fixed
    
    return animation_json


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


def _fetch_mojang_animation_sample(mob_name: str) -> Optional[dict]:
    """Fetch animation.json sample from Mojang's bedrock-samples GitHub repository.
    
    Downloads actual animation examples from:
    https://github.com/Mojang/bedrock-samples/tree/main/resource_pack/animations
    
    Args:
        mob_name: Mob name (e.g., 'chicken', 'cow', 'zombie')
    
    Returns:
        Parsed animation JSON dict or None if not found
    """
    import urllib.request
    import urllib.error
    
    base_url = "https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/animations"
    
    # Try common animation file names
    candidates = [
        f"{mob_name}.animation.json",
        f"{mob_name}.animation_controllers.json",
    ]
    
    for filename in candidates:
        url = f"{base_url}/{filename}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BedrockAddonBuilder/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                print(f"[MOJANG-ANIM] ✓ Fetched {filename} from bedrock-samples")
                return data
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
            continue
    
    print(f"[MOJANG-ANIM] ✗ Could not fetch animation samples for '{mob_name}' from bedrock-samples")
    return None


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


def _get_animation_skeleton(mob_name: str, anim_type: str, bones: list[str]) -> str:
    """Return a pre-structured JSON skeleton for the LLM to fill in.
    
    Instead of asking the LLM to generate valid JSON from scratch (which leads to
    malformed structures and invented bone names), provide a complete skeleton where
    the LLM only needs to replace FILL_IN placeholders with Molang expressions.
    
    This eliminates:
    1. Malformed bone structures (structure is already valid)
    2. Invented bone names (all bones are pre-defined)
    
    Args:
        mob_name: Mob short name (for animation IDs)
        anim_type: 'idle', 'walk', 'run', 'fly', 'swim', 'slither', etc.
        bones: List of valid bone names from geometry
    
    Returns:
        JSON string with complete skeleton ready for LLM to fill in
    """
    skeleton_dict = {
        "format_version": "1.8.0",
        "animations": {
            f"animation.{mob_name}.{anim_type}": {
                "loop": True,
                "bones": {
                    bone: {"rotation": ["FILL_IN_X", "FILL_IN_Y", "FILL_IN_Z"]}
                    for bone in bones
                }
            }
        }
    }
    
    # Only add anim_time_update for non-idle animations
    # For idle, let Minecraft use the default query.anim_time (removes redundancy and prevents logic loops)
    if anim_type != "idle":
        anim_data = skeleton_dict["animations"][f"animation.{mob_name}.{anim_type}"]
        if anim_type in ["walk", "run", "slither"]:
            # Movement-based animations use distance moved for frame synchronization
            anim_data["anim_time_update"] = "query.modified_distance_moved"
        else:
            # Other animations use time (swim, fly, float, etc.)
            anim_data["anim_time_update"] = "query.anim_time"
    
    return json.dumps(skeleton_dict, indent=2)


def _validate_animation_with_retry(
    animation_dict: dict,
    mob_name: str,
    bones: list[str],
    provider: str,
    api_key: Optional[str],
    max_retries: int = 3,
) -> tuple[Optional[dict], bool]:
    """Validate animation and retry with LLM feedback if validation fails.
    
    Instead of discarding generations with small validation errors, feed the
    error messages back to the LLM and ask it to fix them. This turns 5-line
    errors into fixable problems rather than complete failures.
    
    Args:
        animation_dict: The generated animation.json as dict
        mob_name: Name of the mob (for error messages)
        bones: List of valid bone names
        provider: LLM provider to use for fixes
        api_key: API key for the provider
        max_retries: Maximum number of validation attempts (default 3)
    
    Returns:
        tuple of (validated_animation_dict or None, was_valid_on_first_try)
    """
    print(f"[ANIMATION-VALIDATE] Starting validation with up to {max_retries} retries")
    
    for attempt in range(1, max_retries + 1):
        print(f"[ANIMATION-VALIDATE] Attempt {attempt}/{max_retries}")
        
        # Validate current animation
        try:
            validation = mcp_validate_sync(
                content=animation_dict,
                schema_type="animation",
            )
            is_valid = validation.valid if validation else False
            errors = validation.errors if validation else []
        except Exception as e:
            print(f"[ANIMATION-VALIDATE] Validation exception: {e}")
            is_valid = False
            errors = [str(e)]
        
        if is_valid:
            print(f"[ANIMATION-VALIDATE] ✓ Validation passed on attempt {attempt}")
            return (animation_dict, attempt == 1)
        
        print(f"[ANIMATION-VALIDATE] ✗ Validation failed: {len(errors)} error(s)")
        for err in errors[:3]:  # Log first 3 errors
            print(f"[ANIMATION-VALIDATE]   - {err}")
        
        # If this was the last attempt, return None without retrying
        if attempt >= max_retries:
            print(f"[ANIMATION-VALIDATE] ✗ Max retries ({max_retries}) reached, giving up")
            return (None, False)
        
        # Build fix-up prompt with current animation and errors
        error_summary = "\n".join(f"  • {err}" for err in errors[:5])
        
        fix_prompt = f"""You previously generated an animation.json for '{mob_name}' that failed validation.

Here are the validation errors you must fix:
{error_summary}

The current animation is:
{json.dumps(animation_dict, indent=2)}

Fix these specific errors in the animation above. Return ONLY the corrected animation.json, nothing else. 
Keep all bones and structure intact - only fix the issues mentioned."""
        
        fix_system_prompt = """You are fixing a Minecraft Bedrock animation.json that has validation errors.
Your task: Read the errors provided and fix ONLY those issues in the animation JSON.
Do not change bone names, add/remove bones, or alter the overall structure.
Return only valid JSON that addresses the specific errors mentioned."""
        
        print(f"[ANIMATION-VALIDATE] Calling LLM to fix validation errors (attempt {attempt+1})")
        
        # Call LLM with fix prompt
        fixed_dict = _call_animation_provider(
            fix_prompt, fix_system_prompt, provider, api_key
        )
        
        if fixed_dict:
            print(f"[ANIMATION-VALIDATE] LLM returned fixed animation, re-validating")
            animation_dict = fixed_dict
        else:
            print(f"[ANIMATION-VALIDATE] LLM failed to return fixed animation, trying again with original")
            # Try again with original on next iteration
    
    print(f"[ANIMATION-VALIDATE] Failed all {max_retries} validation attempts")
    return (None, False)


def _get_animation_system_prompt(
    bone_names: list[str],
    mob_name: str,
    geometry_id: str,
) -> str:
    """Build system prompt for animation generation with available bones."""
    
    return f"""You are an expert Minecraft Bedrock animation developer with deep knowledge of Molang expressions.

YOUR TASK: You will receive THREE pre-structured JSON skeletons (one for idle, walk, run).
Each skeleton is complete and valid - every bone is already defined.
You MUST fill in the FILL_IN_X, FILL_IN_Y, FILL_IN_Z placeholders with Molang expressions.

⚠️  CRITICAL RULES:
1. DO NOT add or remove any bones
2. DO NOT change any keys or structure
3. DO NOT use keyframe objects (timestamps)
4. ONLY replace FILL_IN_X/Y/Z with Molang expressions or "0"
5. Return ONLY the completed JSON, no markdown, no explanation

═══════════════════════════════════════════════════════════
MOLANG SINGLE-EXPRESSION FORMAT
═══════════════════════════════════════════════════════════

Each rotation is an array of 3 strings: [X_expression, Y_expression, Z_expression]
Each element is either:
  - "0" (no rotation on this axis)
  - A Molang expression like: "math.sin(query.anim_time * 2.5) * 3"

MOLANG BASICS:
- math.sin(t) = oscillates from -1 to +1
- 57.3 = radians-to-degrees conversion factor (180/π)
- 57.3 * 0.5 ≈ 28.65° (max ±28.65°)
- 57.3 * 0.8 ≈ 45.84° (max ±45.84°)

QUERIES:
- query.anim_time = time counter (used for idle)
- query.modified_distance_moved = walk distance (used for walk/run)

═══════════════════════════════════════════════════════════
ANIMATION-SPECIFIC GUIDANCE
═══════════════════════════════════════════════════════════

IDLE (query.anim_time):
- Slow gentle oscillation (frequency 1.0-3.0, amplitude usually 0.05-0.15)
- Head/ears: ±5-8° = math.sin(query.anim_time * 2.0) * 57.3 * 0.1
- Tail: ±10-15° = math.sin(query.anim_time * 2.2) * 57.3 * 0.2
- Body: ±2-3° = math.sin(query.anim_time * 1.5) * 57.3 * 0.04

WALK (query.modified_distance_moved, frequency 38.17):
- ±30-40° leg swings: math.sin(query.modified_distance_moved * 38.17) * 57.3 * 0.5
- Opposite leg = NEGATE: -math.sin(query.modified_distance_moved * 38.17) * 57.3 * 0.5
- Body sway: ±2-3° = math.sin(query.modified_distance_moved * 38.17) * 57.3 * 0.04

RUN (query.modified_distance_moved, frequency 76.35 = 2x walk):
- ±45-60° leg swings: math.sin(query.modified_distance_moved * 76.35) * 57.3 * 0.8
- Opposite leg = NEGATE: -math.sin(query.modified_distance_moved * 76.35) * 57.3 * 0.8
- Body lean: ±15-20° = math.sin(query.modified_distance_moved * 76.35) * 57.3 * 0.3

═══════════════════════════════════════════════════════════
ROTATION MAGNITUDE REFERENCE
═══════════════════════════════════════════════════════════

Format: max_degrees = 57.3 * multiplier

- 57.3 * 0.03 = ±1.7°
- 57.3 * 0.04 = ±2.3°
- 57.3 * 0.05 = ±2.9°
- 57.3 * 0.1 = ±5.7°
- 57.3 * 0.15 = ±8.6°
- 57.3 * 0.2 = ±11.5°
- 57.3 * 0.3 = ±17.2°
- 57.3 * 0.4 = ±22.9°
- 57.3 * 0.5 = ±28.65° (walk leg swing)
- 57.3 * 0.6 = ±34.4°
- 57.3 * 0.8 = ±45.84° (run leg swing)

EXAMPLES FOR REFERENCE:

Idle head bob (±5°):
  "head": {{"rotation": ["math.sin(query.anim_time * 2.0) * 57.3 * 0.08", 0, 0]}}

Walk body sway (±3°):
  "body": {{"rotation": [0, "math.sin(query.modified_distance_moved * 38.17) * 57.3 * 0.05", 0]}}

Walk left leg (±30°):
  "leg_front_left": {{"rotation": ["math.sin(query.modified_distance_moved * 38.17) * 57.3 * 0.5", 0, 0]}}

Walk right leg opposite phase (±30°):
  "leg_front_right": {{"rotation": ["-math.sin(query.modified_distance_moved * 38.17) * 57.3 * 0.5", 0, 0]}}

Run body lean (±20°):
  "body": {{"rotation": ["math.sin(query.modified_distance_moved * 76.35) * 57.3 * 0.35", 0, 0]}}

═══════════════════════════════════════════════════════════
YOUR PROCESS
═══════════════════════════════════════════════════════════

1. Read the skeleton JSON carefully
2. Identify each bone name (these are correct - use them exactly)
3. For each FILL_IN_X, FILL_IN_Y, FILL_IN_Z, choose:
   - "0" if that bone doesn't rotate on that axis in this animation
   - A Molang expression using the patterns above
4. Replace all FILL_IN_X/Y/Z values
5. Return ONLY the completed JSON
6. DO NOT modify any other part of the structure"""


def _fetch_animation_template_sync(animation_type: str) -> Optional[dict]:
    """DEPRECATED: Fetch animation template from MCP bedrock-samples.
    
    This function is no longer used for generation context.
    We now use only GitHub/Mojang samples (Molang format) to avoid format confusion.
    
    Kept for backward compatibility, but animations are generated from Mojang Molang
    examples (via _fetch_mojang_animation_sample) instead of MCP keyframe templates.
    
    Args:
        animation_type: Type of animation (e.g., "walk", "idle")
    
    Returns:
        dict or None (always returns None in current implementation)
    """
    # This function is deprecated and no longer used for generation
    # Animation templates are now exclusively sourced from GitHub bedrock-samples
    # in Molang format to prevent format confusion
    print(f"[ANIM-TEMPLATE] DEPRECATED: MCP template fetch no longer used for {animation_type}")
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


def _get_animation_claude_model_name(provider: str) -> str:
    """Determine Claude model ID from provider string.
    
    Maps provider variants to actual model IDs:
    - "claude-sonnet-4.6" or "claude-sonnet" → claude-sonnet-4-20250514 (latest)
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


def _call_animation_claude(
    prompt: str,
    system_prompt: str,
    api_key: str,
    provider: str = "claude",
) -> Optional[dict]:
    """Call Claude to generate animation.
    
    Args:
        prompt: User prompt
        system_prompt: System prompt
        api_key: Anthropic API key
        provider: Provider string (e.g., "claude-sonnet-4.6" or "claude-opus") to select model
    """
    print(f"[CLAUDE-ANIMATION] Starting Claude animation generation")
    try:
        import httpx
        
        # Validate API key before sending
        if not api_key:
            print(f"[CLAUDE-ANIMATION] ERROR: api_key is empty or None!")
            return None
        print(f"[CLAUDE-ANIMATION] API key length: {len(api_key)} chars, starts with: {api_key[:10]}...")
        
        model = _get_animation_claude_model_name(provider)
        
        client = httpx.Client(timeout=30)
        print(f"[CLAUDE-ANIMATION] Sending request to Anthropic API with model: {model} (provider: {provider})")
        print(f"[CLAUDE-ANIMATION] Endpoint: https://api.anthropic.com/v1/messages")
        print(f"[CLAUDE-ANIMATION] Headers: x-api-key present, anthropic-version: 2023-06-01")
        
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
        print(f"[CLAUDE-ANIMATION] Response status: {response.status_code}")
        
        if response.status_code == 404:
            print(f"[CLAUDE-ANIMATION] 404 Error - Response body: {response.text[:500]}")
            print(f"[CLAUDE-ANIMATION] This typically means an invalid API key or wrong model name")
            print(f"[CLAUDE-ANIMATION] Model being used: {model}")
        
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
    """Route animation generation to the selected provider.
    
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
    
    print(f"[ANIMATION-PROVIDER] Called with provider: {provider_lower}, api_key present: {bool(api_key)}")
    
    if provider_lower.startswith("openai"):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if api_key:
            print(f"[ANIMATION-PROVIDER] Routing to OpenAI")
            return _call_animation_openai(prompt, system_prompt, api_key)
        else:
            log.error(f"[ANIMATION-PROVIDER] OpenAI selected but no API key in args or OPENAI_API_KEY env")
            print(f"[ANIMATION-PROVIDER] ERROR: OpenAI selected but no OPENAI_API_KEY")
            return None
    
    elif provider_lower.startswith("deepseek"):
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if api_key:
            print(f"[ANIMATION-PROVIDER] Routing to DeepSeek")
            return _call_animation_deepseek(prompt, system_prompt, api_key)
        else:
            log.error(f"[ANIMATION-PROVIDER] DeepSeek selected but no API key in args or DEEPSEEK_API_KEY env")
            print(f"[ANIMATION-PROVIDER] ERROR: DeepSeek selected but no DEEPSEEK_API_KEY")
            return None
    
    elif provider_lower.startswith("gemini"):
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if api_key:
            print(f"[ANIMATION-PROVIDER] Routing to Gemini")
            return _call_animation_gemini(prompt, system_prompt, api_key)
        else:
            log.error(f"[ANIMATION-PROVIDER] Gemini selected but no API key in args or GEMINI_API_KEY env")
            print(f"[ANIMATION-PROVIDER] ERROR: Gemini selected but no GEMINI_API_KEY")
            return None
    
    elif provider_lower.startswith("claude"):
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            print(f"[ANIMATION-PROVIDER] Routing to Claude with model: {CLAUDE_MODEL_NAME}")
            return _call_animation_claude(prompt, system_prompt, api_key, provider=provider)
        else:
            log.error(f"[ANIMATION-PROVIDER] Claude selected but no API key in args or ANTHROPIC_API_KEY env")
            print(f"[ANIMATION-PROVIDER] ERROR: Claude selected but no ANTHROPIC_API_KEY")
            return None
    
    elif provider_lower.startswith("ollama"):
        print(f"[ANIMATION-PROVIDER] Routing to Ollama")
        return _call_animation_ollama(prompt, system_prompt)
    
    else:
        log.error(f"[ANIMATION-PROVIDER] Unknown provider: {provider}")
        print(f"[ANIMATION-PROVIDER] ERROR - Unknown provider: {provider}")
        return None


def _classify_locomotion(
    mob_name: str,
    bones: list[str],
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict:
    """Classify mob locomotion type to determine required animation states.
    
    Instead of always generating idle/walk/run, ask the LLM to classify
    the mob's movement type and return only the states that are needed.
    
    Args:
        mob_name: Short name of the mob
        bones: List of bone names from geometry
        provider: LLM provider (openai, deepseek, gemini, claude, ollama)
        api_key: API key for cloud providers
    
    Returns:
        dict with:
          - type: locomotion type (e.g., "quadruped", "biped", "flying", etc.)
          - states: list of required animation states (e.g., ["idle", "walk", "run"])
          - reasoning: brief explanation of the classification
    
    Example outputs:
        {"type": "biped", "states": ["idle", "walk", "run"], "reasoning": "..."}
        {"type": "flying", "states": ["idle", "fly"], "reasoning": "..."}
        {"type": "aquatic", "states": ["idle", "swim"], "reasoning": "..."}
        {"type": "stationary", "states": ["idle"], "reasoning": "..."}
    """
    if not provider:
        provider = DEFAULT_LLM_PROVIDER
    
    bones_str = ", ".join(bones) if bones else "root"
    
    system_prompt = f"""You are an expert Minecraft mob animator classifying movement types.

Analyze the mob '{mob_name}' with these bones: {bones_str}

Classify the locomotion type and determine what animation states are needed.

Return ONLY valid JSON (no markdown, no explanation):
{{
  "type": "quadruped|biped|flying|aquatic|slithering|stationary|...",
  "states": ["idle", "walk", "run"],
  "reasoning": "brief explanation"
}}

GUIDELINES:
- type: The primary locomotion style
- states: Only the animation types this mob actually needs
- Examples:
  - Quadruped (horse, wolf): ["idle", "walk", "run"]
  - Biped (zombie, player): ["idle", "walk", "run"]
  - Flying (parrot, phantom): ["idle", "fly"]
  - Aquatic (fish): ["idle", "swim"]
  - Slithering (snake): ["idle", "slither"]
  - Stationary (block-like): ["idle"]
  - Mixed (pegasus): ["idle", "walk", "run", "fly"]"""
    
    user_prompt = f"""Classify the locomotion type for mob '{mob_name}' with bones: {bones_str}

Return ONLY the JSON classification."""
    
    print(f"[LOCOMOTION-CLASS] Classifying {mob_name} with {len(bones)} bones")
    
    classification_dict = _call_animation_provider(
        user_prompt, system_prompt, provider, api_key
    )
    
    if not classification_dict:
        # Default to biped if classification fails
        print(f"[LOCOMOTION-CLASS] ✗ Classification failed, defaulting to biped")
        return {
            "type": "biped",
            "states": ["idle", "walk", "run"],
            "reasoning": "Classification failed - using standard biped animation set as fallback",
        }
    
    # Validate the classification response
    required_keys = {"type", "states", "reasoning"}
    if not all(key in classification_dict for key in required_keys):
        print(f"[LOCOMOTION-CLASS] ✗ Invalid classification response: missing keys")
        print(f"[LOCOMOTION-CLASS]   Got: {list(classification_dict.keys())}")
        return {
            "type": "biped",
            "states": ["idle", "walk", "run"],
            "reasoning": "Classification response was invalid - using standard biped as fallback",
        }
    
    # Ensure states is a list
    if not isinstance(classification_dict.get("states"), list):
        print(f"[LOCOMOTION-CLASS] ✗ States must be a list, got: {type(classification_dict.get('states'))}")
        classification_dict["states"] = ["idle", "walk", "run"]
    
    print(f"[LOCOMOTION-CLASS] ✓ Classified as '{classification_dict['type']}' with states: {classification_dict['states']}")
    print(f"[LOCOMOTION-CLASS]   Reasoning: {classification_dict['reasoning']}")
    
    return classification_dict


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
    
    # Fetch Mojang animation samples from bedrock-samples repository
    # These are REAL examples from Minecraft in Molang format
    # We use ONLY Mojang samples to avoid format confusion (no MCP keyframe templates)
    mojang_anim_sample = _fetch_mojang_animation_sample(mob_name) or _fetch_mojang_animation_sample("chicken")
    mojang_ctrl_sample = _fetch_mojang_animation_controller_sample(mob_name) or _fetch_mojang_animation_controller_sample("chicken")
    
    # Build template context using ONLY Mojang samples (Molang format)
    # We explicitly avoid MCP keyframe templates which would create format confusion
    template_context = ""
    if mojang_anim_sample or mojang_ctrl_sample:
        template_context = "\n╔═══════════════════════════════════════════════════════════╗\n"
        template_context += "║  OFFICIAL MOJANG ANIMATION SAMPLES (Molang Format)          ║\n"
        template_context += "║  Source: github.com/Mojang/bedrock-samples                  ║\n"
        template_context += "╚═══════════════════════════════════════════════════════════╝\n"
        
        if mojang_anim_sample:
            template_context += f"\n📋 REAL animation.json from {mob_name} (or chicken as fallback):\n"
            template_context += "Format: Molang expressions (NOT keyframes)\n"
            # Show just the first animation as an example
            anims = mojang_anim_sample.get("animations", {})
            first_anim = next(iter(anims.items())) if anims else None
            if first_anim:
                anim_name, anim_data = first_anim
                template_context += f"\nExample animation (Molang single-expression format):\n"
                template_context += f'{json.dumps(anim_data, indent=2)[:1200]}...\n'
            else:
                template_context += json.dumps(mojang_anim_sample, indent=2)[:1500] + "...\n"
        
        if mojang_ctrl_sample:
            template_context += f"\n🎬 REAL animation_controllers.json state transitions:\n"
            ctrls = mojang_ctrl_sample.get("animation_controllers", {})
            first_ctrl = next(iter(ctrls.items())) if ctrls else None
            if first_ctrl:
                ctrl_name, ctrl_data = first_ctrl
                template_context += f'{json.dumps(ctrl_data, indent=2)[:1200]}...\n'
            else:
                template_context += json.dumps(mojang_ctrl_sample, indent=2)[:1500] + "...\n"
        
        template_context += "\n⚠️  Use Molang expressions EXACTLY as shown in the samples above.\n"
    
    # Classify locomotion type to determine which animation states are needed
    print(f"[ANIMATION-GEN] Classifying locomotion type for {mob_name}")
    locomotion = _classify_locomotion(mob_name, bones, provider, api_key)
    animation_states = locomotion.get("states", ["idle", "walk", "run"])
    locomotion_type = locomotion.get("type", "biped")
    
    print(f"[ANIMATION-GEN] Locomotion type: {locomotion_type}")
    print(f"[ANIMATION-GEN] Required animation states: {animation_states}")
    
    # Build animation skeletons ONLY for the required states (pre-structured JSON for LLM to fill in)
    skeletons = {}
    for state in animation_states:
        skeletons[state] = _get_animation_skeleton(mob_name, state, bones)
        print(f"[ANIMATION-GEN] Generated skeleton for state: {state}")
    
    # Build user prompt that tells LLM to fill in the skeletons
    skeleton_sections = ""
    for state in animation_states:
        skeleton_sections += f"""
═══════════════════════════════════════════════════════════
{state.upper()} SKELETON:
═══════════════════════════════════════════════════════════
{skeletons[state]}
"""
    
    full_prompt = f"""Complete these animation skeletons for mob '{mob_name}' (type: {locomotion_type}).

Bones available: {', '.join(bones) if bones else 'root'}
Required states: {', '.join(animation_states)}

Each skeleton below is already valid and complete - all bones are pre-defined.
Your task: Replace each FILL_IN_X, FILL_IN_Y, FILL_IN_Z with either:
  - "0" (no rotation on that axis)
  - A Molang expression (e.g., "math.sin(query.anim_time * 2.0) * 57.3 * 0.1")

DO NOT:
  - Add or remove any bones
  - Change any keys or structure
  - Use keyframe objects (timestamps)

{skeleton_sections}
═══════════════════════════════════════════════════════════
CRITICAL BONE ANIMATION RULES FOR THIS MOB:
═══════════════════════════════════════════════════════════
Locomotion Type: {locomotion_type.upper()}
Required Animation States: {', '.join(animation_states)}

⚠️  BONE ANIMATION REQUIREMENTS:
- For MOVEMENT states (walk, run, slither): Leg/locomotion bones MUST have Molang motion math
- For IDLE state: Legs typically stay "0", only breathing/idle motion
- For FLIGHT (fly): Wing bones MUST have flapping motion, legs can be "0"
- For WATER (swim): Body/tail bones MUST wave, legs can be "0"

Match bone types to your mob:
- leg_*, limb_*, hind_* → Movement bones (must animate in walk/run)
- wing_*, arm_* → Appendage bones (animate for flying/arm swinging)
- body, spine, torso → Core bones (sway/lean in movement)
- tail, fin_* → Balance bones (oscillate or wave)
- head, jaw, ear_* → Detail bones (optional mini-animations)

═══════════════════════════════════════════════════════════
GUIDANCE FOR FILLING IN VALUES:
═══════════════════════════════════════════════════════════

{template_context}"""
    
    # Build animation-specific guidance based on the actual states needed
    animation_guidance = "\nANIMATION PATTERNS TO FOLLOW:\n\n"
    
    for state in animation_states:
        if state == "idle":
            animation_guidance += """IDLE (use query.anim_time, slow cycles):
  - Head bob: math.sin(query.anim_time * 2.0) * 57.3 * 0.08 (≈±5°)
  - Tail: math.sin(query.anim_time * 2.2) * 57.3 * 0.2 (≈±11°)
  - Body: math.sin(query.anim_time * 1.5) * 57.3 * 0.04 (≈±2°)
  - ⚠️  LEGS should be "0" for idle (no motion)

"""
        elif state == "walk":
            animation_guidance += """WALK (use query.modified_distance_moved * 38.17):
  - ALL LEG BONES MUST HAVE ROTATION (do not leave them as "0")
  - Left leg bones: math.sin(query.modified_distance_moved * 38.17) * 57.3 * 0.5 (≈±29°)
  - Right leg bones (opposite phase): -math.sin(query.modified_distance_moved * 38.17) * 57.3 * 0.5
  - Body sway: math.sin(query.modified_distance_moved * 38.17) * 57.3 * 0.04 (≈±2°)
  - ⚠️  CRITICAL: If the mob has leg bones (leg_*, limb_*, hind_*, etc.), they MUST have motion math
  - ⚠️  Set bones to "0" ONLY if they don't affect locomotion (e.g., tail, head in some cases)

"""
        elif state == "run":
            animation_guidance += """RUN (use query.modified_distance_moved * 76.35 = 2x walk frequency):
  - ALL LEG BONES MUST HAVE ROTATION (do not leave them as "0")
  - Left leg bones: math.sin(query.modified_distance_moved * 76.35) * 57.3 * 0.8 (≈±46°)
  - Right leg bones (opposite phase): -math.sin(query.modified_distance_moved * 76.35) * 57.3 * 0.8
  - Body lean: math.sin(query.modified_distance_moved * 76.35) * 57.3 * 0.3 (≈±17°)
  - ⚠️  CRITICAL: Legs must animate faster than walk (76.35 vs 38.17) to match sprint speed
  - ⚠️  Set bones to "0" ONLY if they don't affect locomotion

"""
        elif state == "fly":
            animation_guidance += """FLY (use query.anim_time or query.ground_speed):
  - WING BONES MUST HAVE ROTATION (all wing_* bones need motion)
  - Wing flap: math.sin(query.anim_time * 4.0) * 57.3 * 0.8 (fast flapping, ≈±45°)
  - Body tilt: math.sin(query.anim_time * 2.0) * 57.3 * 0.2 (gentle banking, ≈±11°)
  - Tail: math.sin(query.anim_time * 2.5) * 57.3 * 0.3 (±17° balance)
  - ⚠️  CRITICAL: Wings must flap for flight to look convincing
  - ⚠️  Legs can be "0" (not used in flight)

"""
        elif state == "swim":
            animation_guidance += """SWIM (use query.anim_time or query.ground_speed):
  - BODY WAVE MOTION REQUIRED (all body segments need serpentine movement)
  - Body wave: math.sin(query.anim_time * 3.0) * 57.3 * 0.5 (serpentine motion, ≈±29°)
  - Tail swish: math.sin(query.anim_time * 3.5) * 57.3 * 0.6 (±34°)
  - Fins: math.sin(query.anim_time * 2.5) * 57.3 * 0.4 (±23° balance)
  - ⚠️  CRITICAL: Body and tail must move for swimming animation
  - ⚠️  Legs can be "0" (fins/tail do the swimming)

"""
        elif state == "slither":
            animation_guidance += """SLITHER (use query.modified_distance_moved * 30):
  - Body wave: math.sin(query.modified_distance_moved * 30) * 57.3 * 0.4 (lateral undulation, ≈±23°)
  - Head lead: math.sin(query.modified_distance_moved * 30 - 1) * 57.3 * 0.3 (±17°, offset phase)

"""
        # For other states, just mention they should use appropriate timing
        elif state not in ["idle", "walk", "run", "fly", "swim", "slither"]:
            animation_guidance += f"""{state.upper()} (use appropriate query timing):
  - Refer to the Mojang samples for reference patterns
  - Use query.anim_time for idle-like looping states
  - Use query.modified_distance_moved for movement-based states

"""
    
    full_prompt += animation_guidance
    full_prompt += f"""
Return ONLY the {len(animation_states)} completed JSON objects combined into one animation.json, nothing else."""
    
    print(f"[ANIMATION-GEN] Calling provider with skeleton templates")

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
    
    # With skeleton templates, malformed structures should be extremely rare
    # But keep normalization as fallback in case LLM majorly deviates
    print(f"[ANIMATION-GEN] Checking animation structure (skeletons should make this unnecessary)")
    animation_dict = _normalize_animation_json(animation_dict, mob_name, bone_names=bones)
    if not animation_dict:
        print(f"[ANIMATION-GEN] ⚠️  Structure was severely malformed despite skeleton template")
        return {
            "animation": None,
            "mcp_verified": False,
            "bone_count": len(bones),
            "provider": provider,
            "error": "Failed to normalize animation structure",
        }
    
    # Post-validation: As a final safety check, verify no "rotation" bone names exist
    # (with skeletons this should never happen)
    print(f"[ANIMATION-GEN] Final validation: Checking for 'rotation' as bone name (should not occur with skeletons)")
    if "animations" in animation_dict:
        for anim_name, anim_data in animation_dict.get("animations", {}).items():
            if isinstance(anim_data, dict) and "bones" in anim_data:
                anim_bones = anim_data["bones"]
                # Check if ONLY bone name is "rotation" (should not happen with skeletons)
                if set(anim_bones.keys()) == {"rotation"}:
                    print(f"[ANIMATION-GEN] ⚠️  UNEXPECTED: animation '{anim_name}' still has 'rotation' as bone name")
                    rotation_expr = anim_bones["rotation"]
                    # Replace with actual bone names, keeping the Molang expression
                    fixed_bones = {}
                    for bone_name in bones if bones else ["body", "head"]:
                        fixed_bones[bone_name] = {"rotation": rotation_expr}
                    anim_data["bones"] = fixed_bones
                    print(f"[ANIMATION-GEN] ✓ FIXED: Replaced 'rotation' bone name with actual bones: {list(fixed_bones.keys())}")
    
    # Validate via MCP with automatic retry on validation errors
    print(f"[ANIMATION-GEN] Validating animation via MCP (with retry loop)")
    validated_animation, was_first_try_valid = _validate_animation_with_retry(
        animation_dict,
        mob_name=mob_name,
        bones=bones,
        provider=provider,
        api_key=api_key,
        max_retries=3,
    )
    
    mcp_valid = validated_animation is not None
    if validated_animation:
        animation_dict = validated_animation
        print(f"[ANIMATION-GEN] ✓ MCP validation passed (first try: {was_first_try_valid})")
    else:
        print(f"[ANIMATION-GEN] ✗ MCP validation failed after retries, will return null animation")
    
    # Ensure format_version
    if animation_dict and "format_version" not in animation_dict:
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


def validate_physics_animation_sync(
    animation_json: dict,
    animation_controller_json: dict,
    mob_name: str,
) -> dict:
    """Validate that physics and animation are properly synced.
    
    Checks for two failure modes:
    1. LOGIC FAILURE: Controller transitions never trigger (wrong state names, missing transitions)
    2. VISUAL FAILURE: Controller switches states but animations don't move bones
    
    Returns:
        {
            "is_synced": bool,
            "issues": list[str],
            "warnings": list[str],
            "logic_failure_risk": bool,
            "visual_failure_risk": bool,
            "summary": str
        }
    """
    issues = []
    warnings = []
    logic_failure_risk = False
    visual_failure_risk = False
    
    if not animation_json or not animation_controller_json:
        return {
            "is_synced": False,
            "issues": ["Missing animation.json or animation_controller.json"],
            "warnings": [],
            "logic_failure_risk": True,
            "visual_failure_risk": False,
            "summary": "Cannot validate - missing animation files"
        }
    
    # ───────────────────────────────────────────────────────────────────
    # LOGIC FAILURE CHECK: Controller state transitions must match animation names
    # ───────────────────────────────────────────────────────────────────
    print(f"\n[VALIDATE-SYNC] Checking {mob_name} for physics-animation sync issues...")
    
    # Get animation names from animation.json
    anim_names = set(animation_json.get("animations", {}).keys())
    if not anim_names:
        issues.append("animation.json has no animations defined")
        logic_failure_risk = True
    else:
        print(f"[VALIDATE-SYNC] Found animations: {anim_names}")
    
    # Extract state names and their transitions from controller
    controllers = animation_controller_json.get("animation_controllers", {})
    for ctrl_name, ctrl_data in controllers.items():
        print(f"[VALIDATE-SYNC] Checking controller: {ctrl_name}")
        
        states = ctrl_data.get("states", {})
        if not states:
            issues.append(f"{ctrl_name}: No states defined")
            logic_failure_risk = True
            continue
        
        # Check 1: All animations referenced in states must exist
        for state_name, state_data in states.items():
            state_anims = state_data.get("animations", [])
            if not state_anims:
                warnings.append(f"State '{state_name}' has no animations (OK if it's a transition-only state)")
                continue
            
            for anim_ref in state_anims:
                # anim_ref should be a SHORT NAME (e.g., "idle", "walk", "run")
                # NOT a full ID (e.g., "animation.mob.idle")
                
                # Find the full ID that matches this short name
                full_id = f"animation.{mob_name}.{anim_ref}"
                
                if full_id not in anim_names:
                    # If the full ID doesn't exist, check if it's just the short name
                    if anim_ref in anim_names:
                        warnings.append(f"State '{state_name}' references '{anim_ref}' (short name), but should reference full ID '{full_id}'")
                    else:
                        issues.append(f"State '{state_name}' references animation '{anim_ref}', but it doesn't exist in animation.json")
                        issues.append(f"  Available animations: {anim_names}")
                        logic_failure_risk = True
        
        # Check 2: Critical transitions for movement must exist
        has_idle = "idle" in states
        has_walk = "walk" in states
        has_run = "run" in states
        
        if not has_idle:
            warnings.append(f"{ctrl_name}: No 'idle' state (mob might not stand still)")
        
        if has_walk or has_run:
            # Check that movement states have transitions back to idle
            if has_walk:
                walk_transitions = states["walk"].get("transitions", [])
                has_return = any("idle" in str(t) for t in walk_transitions)
                if not has_return:
                    warnings.append("'walk' state has no transition back to idle")
            
            if has_run:
                run_transitions = states["run"].get("transitions", [])
                has_return = any("idle" in str(t) for t in run_transitions)
                if not has_return:
                    warnings.append("'run' state has no transition back to idle")
        
        # Check 3: Verify critical query syntax in transitions
        for state_name, state_data in states.items():
            transitions = state_data.get("transitions", [])
            for transition in transitions:
                if isinstance(transition, dict):
                    for target_state, condition in transition.items():
                        # Check if condition looks valid
                        if "query" not in str(condition):
                            if target_state != "idle":  # Transitioning without query might be OK for fallback
                                warnings.append(f"Transition from '{state_name}' to '{target_state}' has no query condition: {condition}")
    
    # ───────────────────────────────────────────────────────────────────
    # VISUAL FAILURE CHECK: Animations must actually move bones
    # ───────────────────────────────────────────────────────────────────
    print(f"[VALIDATE-SYNC] Checking animation bones for motion...")
    
    for anim_name, anim_data in animation_json.get("animations", {}).items():
        bones = anim_data.get("bones", {})
        if not bones:
            warnings.append(f"Animation '{anim_name}' has no bones (does it rely on loop-only timing?)")
            continue
        
        # For movement animations (walk, run), all bones should have some rotation
        is_movement_anim = any(move_type in anim_name.lower() for move_type in ["walk", "run", "slither"])
        
        if is_movement_anim:
            static_bones = []
            for bone_name, bone_data in bones.items():
                rotation = bone_data.get("rotation", [0, 0, 0])
                
                # Check if rotation is static (all zeros or all strings "0")
                is_static = (
                    rotation == [0, 0, 0] or
                    rotation == ["0", "0", "0"] or
                    all(str(r) == "0" for r in rotation)
                )
                
                if is_static:
                    static_bones.append(bone_name)
            
            if static_bones:
                # For walk/run, at least SOME bones should move (legs, body)
                # Check if static bones are just decorative (head, tail, ears)
                decorative = {"head", "ear", "tail", "jaw", "snout", "fin"}
                static_non_decorative = [
                    b for b in static_bones 
                    if not any(d in b.lower() for d in decorative)
                ]
                
                if static_non_decorative:
                    issues.append(f"Movement animation '{anim_name}' has static leg/body bones: {static_non_decorative}")
                    visual_failure_risk = True
                elif len(static_bones) > len(bones) * 0.5:  # More than 50% static
                    warnings.append(f"Movement animation '{anim_name}' is mostly static bones: {static_bones}")
                    visual_failure_risk = True
        
        else:  # Idle animation
            # For idle, it's OK to have mostly static bones
            motion_bones = []
            for bone_name, bone_data in bones.items():
                rotation = bone_data.get("rotation", [0, 0, 0])
                is_static = (
                    rotation == [0, 0, 0] or
                    rotation == ["0", "0", "0"] or
                    all(str(r) == "0" for r in rotation)
                )
                if not is_static:
                    motion_bones.append(bone_name)
            
            if not motion_bones:
                warnings.append(f"Idle animation '{anim_name}' has no motion (completely static - OK if intentional)")
    
    # ───────────────────────────────────────────────────────────────────
    # FINAL ASSESSMENT
    # ───────────────────────────────────────────────────────────────────
    is_synced = len(issues) == 0
    
    summary = ""
    if logic_failure_risk and visual_failure_risk:
        summary = "🔴 CRITICAL: Both logic and visual failures detected - mob will definitely glide"
    elif logic_failure_risk:
        summary = "🔴 CRITICAL: Logic failure detected - animation controller won't transition to walk/run (will stay idle)"
    elif visual_failure_risk:
        summary = "🟡 WARNING: Visual failure detected - controller switches states but legs don't move (gliding effect)"
    elif warnings:
        summary = "🟢 OK with warnings - should work but check warnings for edge cases"
    else:
        summary = "✅ PASS - Physics and animation should be properly synced"
    
    print(f"[VALIDATE-SYNC] {summary}")
    if issues:
        print(f"[VALIDATE-SYNC] Issues ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")
    if warnings:
        print(f"[VALIDATE-SYNC] Warnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  ⚠️  {warning}")
    
    return {
        "is_synced": is_synced,
        "issues": issues,
        "warnings": warnings,
        "logic_failure_risk": logic_failure_risk,
        "visual_failure_risk": visual_failure_risk,
        "summary": summary
    }


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
