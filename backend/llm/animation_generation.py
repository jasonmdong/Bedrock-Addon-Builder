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


def _build_motion_skeleton(
    locomotion_type: str,
    bone_names: list,
    animation_state: str,
    mob_name: str,
) -> dict:
    """Build a motion-aware skeleton with non-zero keyframe templates.
    
    Creates skeletons based on locomotion type, only including relevant bones
    for the animation state, with example keyframes the LLM fills in/adjusts.
    
    Args:
        locomotion_type: "biped", "quadruped", "flying", "aquatic", "slithering", "stationary"
        bone_names: List of all available bone names from geometry
        animation_state: "idle", "walk", "run", "fly", "swim", "slither"
        mob_name: Short mob name for animation IDs
    
    Returns:
        Dict with animation ID and skeleton ready for LLM to refine
    """
    animation_id = f"animation.{mob_name}.{animation_state}"
    
    # Identify bone types by name patterns
    leg_bones = [b for b in bone_names if any(x in b.lower() for x in ["leg", "limb", "hind", "front", "paw"])]
    wing_bones = [b for b in bone_names if any(x in b.lower() for x in ["wing", "feather"])]
    tail_bones = [b for b in bone_names if "tail" in b.lower()]
    core_bones = [b for b in bone_names if b.lower() in ["body", "head", "torso", "neck", "trunk"]]
    
    skeleton = {
        "format_version": "1.8.0",
        "animations": {
            animation_id: {
                "loop": True,
                "anim_time_update": "query.anim_time" if animation_state == "idle" else "query.modified_distance_moved",
                "bones": {}
            }
        }
    }
    
    bones_dict = skeleton["animations"][animation_id]["bones"]
    
    # Build skeleton based on locomotion type and animation state
    if animation_state == "idle":
        # Idle: subtle sway for core bones only (avoid clashing with walk/run)
        if core_bones:
            for bone in core_bones[:3]:  # body, head, trunk
                bones_dict[bone] = {
                    "rotation": {
                        "0.0": [0, 0, 0],
                        "2.0": [2, 0, 0],
                        "4.0": [0, 0, 0]
                    }
                }
    
    elif animation_state == "walk":
        if locomotion_type == "quadruped" and len(leg_bones) >= 4:
            # Quadruped walk: diagonal pairs, period ~1.3 blocks, ±35°
            bones_dict["leg0"] = {"rotation": {"0.0": [0, 0, 0], "0.325": [35, 0, 0], "0.65": [0, 0, 0]}}
            bones_dict["leg1"] = {"rotation": {"0.0": [-35, 0, 0], "0.325": [0, 0, 0], "0.65": [-35, 0, 0]}}
            bones_dict["leg2"] = {"rotation": {"0.0": [-35, 0, 0], "0.325": [0, 0, 0], "0.65": [-35, 0, 0]}}
            bones_dict["leg3"] = {"rotation": {"0.0": [0, 0, 0], "0.325": [35, 0, 0], "0.65": [0, 0, 0]}}
        elif locomotion_type == "biped" and len(leg_bones) >= 2:
            # Biped walk: alternating legs, ±40°
            bones_dict[leg_bones[0]] = {"rotation": {"0.0": [0, 0, 0], "0.25": [40, 0, 0], "0.5": [0, 0, 0]}}
            bones_dict[leg_bones[1]] = {"rotation": {"0.0": [-40, 0, 0], "0.25": [0, 0, 0], "0.5": [-40, 0, 0]}}
        else:
            # Fallback: animate available legs if type uncertain
            for i, leg in enumerate(leg_bones[:4]):
                phase_offset = 180 if i % 2 else 0
                bones_dict[leg] = {"rotation": {"0.0": [0, 0, 0], "0.5": [30 if i % 2 else -30, 0, 0], "1.0": [0, 0, 0]}}
    
    elif animation_state == "run":
        if locomotion_type == "quadruped" and len(leg_bones) >= 4:
            # Quadruped run: faster diagonal, period ~0.8 blocks, ±45°
            bones_dict["leg0"] = {"rotation": {"0.0": [0, 0, 0], "0.2": [45, 0, 0], "0.4": [0, 0, 0]}}
            bones_dict["leg1"] = {"rotation": {"0.0": [-45, 0, 0], "0.2": [0, 0, 0], "0.4": [-45, 0, 0]}}
            bones_dict["leg2"] = {"rotation": {"0.0": [-45, 0, 0], "0.2": [0, 0, 0], "0.4": [-45, 0, 0]}}
            bones_dict["leg3"] = {"rotation": {"0.0": [0, 0, 0], "0.2": [45, 0, 0], "0.4": [0, 0, 0]}}
        elif locomotion_type == "biped" and len(leg_bones) >= 2:
            # Biped run: faster alternating, ±50°
            bones_dict[leg_bones[0]] = {"rotation": {"0.0": [0, 0, 0], "0.15": [50, 0, 0], "0.3": [0, 0, 0]}}
            bones_dict[leg_bones[1]] = {"rotation": {"0.0": [-50, 0, 0], "0.15": [0, 0, 0], "0.3": [-50, 0, 0]}}
    
    elif animation_state == "fly" and wing_bones:
        # Flying: wings flap, ±60°, period ~0.3
        for i, wing in enumerate(wing_bones[:2]):
            bones_dict[wing] = {"rotation": {"0.0": [0, 0, 0], "0.15": [60, 0, 0], "0.3": [0, 0, 0]}}
    
    elif animation_state == "swim" and (tail_bones or core_bones):
        # Swimming: body/tail wave, ±30°
        for bone in (tail_bones or core_bones)[:2]:
            bones_dict[bone] = {"rotation": {"0.0": [0, 0, 0], "0.4": [30, 0, 0], "0.8": [0, 0, 0]}}
    
    elif animation_state == "slither" and (tail_bones or core_bones):
        # Slithering: body wave, ±25°
        for bone in (tail_bones or core_bones)[:3]:
            bones_dict[bone] = {"rotation": {"0.0": [0, 0, 0], "0.3": [25, 0, 0], "0.6": [0, 0, 0]}}
    
    return skeleton


def _classify_locomotion_from_bones(bone_names: list) -> str:
    """Classify locomotion type based on available bone names.
    
    Uses simple heuristics:
    - 4+ leg bones → quadruped
    - 2 leg bones → biped
    - Wing bones, no legs → flying
    - Tail+swimming context → aquatic
    - Else → quadruped (default)
    """
    leg_bones = [b for b in bone_names if any(x in b.lower() for x in ["leg", "limb", "hind", "front", "paw"])]
    wing_bones = [b for b in bone_names if any(x in b.lower() for x in ["wing", "feather"])]
    tail_bones = [b for b in bone_names if "tail" in b.lower()]
    
    if wing_bones and not leg_bones:
        return "flying"
    elif tail_bones and len(leg_bones) < 2:
        return "aquatic"
    elif len(leg_bones) == 2:
        return "biped"
    elif len(leg_bones) >= 4:
        return "quadruped"
    else:
        return "quadruped"  # Default fallback


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

═══════════════════════════════════════════════════════════
CRITICAL: BONE NAMES vs BONE PROPERTIES
═══════════════════════════════════════════════════════════

❌ WRONG - "rotation" used as bone name (GAME IGNORES THIS):
{{
  "animations": {{
    "animation.elephant.idle": {{
      "loop": true,
      "bones": {{
        "rotation": {{              ← WRONG: "rotation" is NOT a bone! The game sees no valid bones.
          "0.0": [0, 0, 0]
        }}
      }}
    }}
  }}
}}

✅ CORRECT - Real bone names with rotation property:
{{
  "animations": {{
    "animation.elephant.idle": {{
      "loop": true,
      "anim_time_update": "query.anim_time",
      "bones": {{
        "body": {{                  ← CORRECT: "body" is a real bone from the geometry
          "rotation": {{            ← CORRECT: "rotation" is a property of the bone
            "0.0": [0, 0, 0]
          }}
        }},
        "head": {{                  ← CORRECT: "head" is another real bone
          "rotation": {{
            "0.0": [0, 0, 5]
          }}
        }}
      }}
    }}
  }}
}}

═══════════════════════════════════════════════════════════
EXACT STRUCTURE TO MATCH
═══════════════════════════════════════════════════════════

{{
  "format_version": "1.8.0",
  "animations": {{
    "animation.{mob_name}.idle": {{
      "loop": true,
      "anim_time_update": "query.anim_time",
      "bones": {{
        "body": {{"rotation": {{"0.0": [0, 0, 0], "0.5": [2, 0, 0], "1.0": [0, 0, 0]}} }},
        "head": {{"rotation": {{"0.0": [0, 0, 0], "0.5": [-3, 0, 0], "1.0": [0, 0, 0]}} }}
      }}
    }},
    "animation.{mob_name}.walk": {{
      "loop": true,
      "anim_time_update": "query.modified_distance_moved",
      "bones": {{
        "body": {{"rotation": {{"0.0": [0, 0, 0]}} }},
        "front_left_leg": {{"rotation": {{"0.0": [0, 0, 0], "0.25": [35, 0, 0], "0.5": [0, 0, 0]}} }},
        "front_right_leg": {{"rotation": {{"0.0": [0, 0, 0], "0.5": [-35, 0, 0], "0.75": [0, 0, 0]}} }}
      }}
    }},
    "animation.{mob_name}.run": {{
      "loop": true,
      "anim_time_update": "query.modified_distance_moved",
      "bones": {{
        "body": {{"rotation": {{"0.0": [0, 0, 0], "0.25": [5, 0, 0], "0.75": [-5, 0, 0]}} }},
        "head": {{"rotation": {{"0.0": [0, 0, 0]}} }}
      }}
    }}
  }}
}}

═══════════════════════════════════════════════════════════
CRITICAL RULES (MUST DO ALL OF THESE):
═══════════════════════════════════════════════════════════

1. format_version MUST be "1.8.0" at top level
2. ALL animations MUST be inside "animations" object (never at root)
3. EVERY animation MUST have ALL 3 of these:
   - "loop": true
   - "anim_time_update": "query.anim_time" (for idle) OR "query.modified_distance_moved" (for walk/run)
   - "bones": {{ ... }}  (object with bone names as keys)

4. INSIDE THE "bones" OBJECT:
   - Keys = ACTUAL BONE NAMES from: {bones_str}
   - Values = bone definition with "rotation" (or "position", "scale") as properties
   - NEVER use "rotation" as a key at the bones level
   - Example: "body": {{ "rotation": {{ "0.0": [x, y, z] }} }}
   - NEVER do: "rotation": {{ "0.0": [x, y, z] }}

5. ANIMATION NAMES must follow pattern: "animation.{mob_name}.ANIMTYPE"
   - "animation.{mob_name}.idle"
   - "animation.{mob_name}.walk"
   - "animation.{mob_name}.run"

6. Keyframe format: "timestamp": [rotation_x, rotation_y, rotation_z]
   - Example: "0.0": [0, 0, 0], "0.5": [10, 0, 0], "1.0": [0, 0, 0]
   - Timestamps can be decimals (0.0, 0.25, 0.5, etc.)

7. Return ONLY valid JSON, no markdown, no explanation, no code blocks"""


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
    
    # Classify locomotion type from bones
    locomotion_type = _classify_locomotion_from_bones(bones)
    print(f"[ANIMATION-GEN] Classified locomotion: {locomotion_type}")
    
    # Build targeted skeletons based on locomotion type
    # These provide non-zero keyframe templates for the LLM to refine
    idle_skeleton = _build_motion_skeleton(locomotion_type, bones, "idle", mob_name)
    walk_skeleton = _build_motion_skeleton(locomotion_type, bones, "walk", mob_name)
    run_skeleton = _build_motion_skeleton(locomotion_type, bones, "run", mob_name)
    
    print(f"[ANIMATION-GEN] Built skeletons for: idle, walk, run")
    print(f"[ANIMATION-GEN] Idle bones: {list(idle_skeleton['animations'][f'animation.{mob_name}.idle']['bones'].keys())}")
    print(f"[ANIMATION-GEN] Walk bones: {list(walk_skeleton['animations'][f'animation.{mob_name}.walk']['bones'].keys())}")
    print(f"[ANIMATION-GEN] Run bones: {list(run_skeleton['animations'][f'animation.{mob_name}.run']['bones'].keys())}")
    
    # Fetch Mojang reference templates for structural context/verification
    walk_template = _fetch_animation_template_sync("walk")
    idle_template = _fetch_animation_template_sync("idle")
    
    template_context = ""
    if walk_template or idle_template:
        template_context = "\n═══════════════════════════════════════════════════════════\nREFERENCE STRUCTURE FROM MOJANG BEDROCK-SAMPLES:\n═══════════════════════════════════════════════════════════\n"
        if idle_template:
            template_context += f"(Idle example shows overall JSON structure - notice format_version, animations object, bone definitions)\n"
            template_context += f"{json.dumps(idle_template, indent=2)[:1000]}...\n\n"
        if walk_template:
            template_context += f"(Walk example shows how bones are animated with keyframes and timing)\n"
            template_context += f"{json.dumps(walk_template, indent=2)[:1000]}...\n"
    
    # Build user prompt with targeted skeletons as primary templates
    skeletons_json = {
        "format_version": "1.8.0",
        "animations": {
            **idle_skeleton["animations"],
            **walk_skeleton["animations"],
            **run_skeleton["animations"],
        }
    }
    
    full_prompt = f"""{prompt}

IMPORTANT: Below are pre-built animation skeletons for a {locomotion_type} mob.
Your job is to REFINE THEM, not generate from scratch.
- Adjust keyframe timing if needed
- Change rotation values to be more pronounced/realistic
- Remove any bones that don't make sense for {mob_name}
- Add subtle motion to idle if the bones support it

PRE-BUILT SKELETONS FOR {mob_name} (locomotion type: {locomotion_type}):
{json.dumps(skeletons_json, indent=2)}

{template_context}

Return the complete, refined animation.json. Keep the same animation IDs and bone names, just improve the motion values."""
    
    print(f"[ANIMATION-GEN] Calling provider: {provider}")
    # Call LLM to refine the skeletons
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
    
    # Normalize malformed structure (if bones are at root instead of in "animations" object)
    print(f"[ANIMATION-GEN] Normalizing animation structure")
    animation_dict = _normalize_animation_json(animation_dict, mob_name, bone_names=bones)
    if not animation_dict:
        print(f"[ANIMATION-GEN] Normalization failed, returning error")
        return {
            "animation": None,
            "mcp_verified": False,
            "bone_count": len(bones),
            "provider": provider,
            "error": "Failed to normalize animation structure",
        }
    
    # Post-validation: Fix any animations that still have "rotation" as the only bone name
    print(f"[ANIMATION-GEN] Post-validation: Checking for malformed bone structures")
    if "animations" in animation_dict:
        for anim_name, anim_data in animation_dict.get("animations", {}).items():
            if isinstance(anim_data, dict) and "bones" in anim_data:
                anim_bones = anim_data["bones"]
                # Check if ONLY bone name is "rotation" (malformation)
                if set(anim_bones.keys()) == {"rotation"}:
                    print(f"[ANIMATION-GEN] ✗ FOUND MALFORMED: animation '{anim_name}' uses 'rotation' as bone name")
                    rotation_data = anim_bones["rotation"]
                    # Replace with actual bone names
                    fixed_bones = {}
                    for bone_name in bones if bones else ["body", "head"]:
                        fixed_bones[bone_name] = {"rotation": rotation_data}
                    anim_data["bones"] = fixed_bones
                    print(f"[ANIMATION-GEN] ✓ FIXED: Replaced 'rotation' bone with actual bones: {list(fixed_bones.keys())}")
    
    # Validate via MCP
    print(f"[ANIMATION-GEN] Validating animation via MCP")
    mcp_valid = False
    try:
        validation = mcp_validate_sync(animation_dict)
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
