#!/usr/bin/env python3
"""Test animation validation functions."""

import json
import sys
sys.path.insert(0, '/c/Users/caitl/Bedrock-Addon-Builder')

from backend.llm.animation_generation import (
    validate_animation_format,
    validate_animation_controller_format,
    ensure_animations_and_controller
)

print("Testing animation validation functions\n")
print("="*60)

# Test 1: Valid animation.json
print("\nTest 1: Valid animation.json")
valid_animation = {
    "format_version": "1.8.0",
    "animations": {
        "animation.test.walk": {
            "loop": True,
            "bones": {}
        },
        "animation.test.idle": {
            "loop": True,
            "bones": {}
        }
    }
}

is_valid, errors = validate_animation_format(valid_animation, "test")
assert is_valid, f"Should be valid, errors: {errors}"
assert len(errors) == 0, f"Should have no errors, got: {errors}"
print("[PASS] Valid animation accepted")

# Test 2: Animation with unnamed key (INVALID)
print("\nTest 2: Animation with invalid key name")
invalid_animation = {
    "format_version": "1.8.0",
    "animations": {
        "animation.test.walk": {
            "loop": True,
            "bones": {}
        },
        "invalid_unnamed_key": {  # This is the problem - doesn't start with "animation."
            "loop": True,
            "bones": {}
        }
    }
}

is_valid, errors = validate_animation_format(invalid_animation, "test")
assert not is_valid, "Should be invalid"
assert any("does not start with 'animation.'" in e for e in errors), f"Should detect unnamed key, got: {errors}"
print(f"[PASS] Invalid key detected: {errors[0]}")

# Test 3: Animation with non-dict value
print("\nTest 3: Animation with non-dict value")
bad_animation = {
    "format_version": "1.8.0",
    "animations": {
        "animation.test.walk": {
            "loop": True,
            "bones": {}
        },
        "animation.test.broken": "this should be a dict, not a string"
    }
}

is_valid, errors = validate_animation_format(bad_animation, "test")
assert not is_valid, "Should be invalid"
assert any("is not a dict" in e for e in errors), f"Should detect non-dict value, got: {errors}"
print(f"[PASS] Non-dict value detected: {errors[0]}")

# Test 4: Valid animation_controller.json
print("\nTest 4: Valid animation_controller.json")
valid_controller = {
    "format_version": "1.8.0",
    "animation_controllers": {
        "controller.animation.test": {
            "initial_state": "idle",
            "states": {
                "idle": {
                    "animations": ["animation.test.idle"],
                    "transitions": [
                        {"walking": "query.is_moving"}
                    ]
                },
                "walking": {
                    "animations": ["animation.test.walk"],
                    "transitions": [
                        {"idle": "!query.is_moving"}
                    ]
                }
            }
        }
    }
}

is_valid, errors = validate_animation_controller_format(valid_controller, "test")
assert is_valid, f"Should be valid, errors: {errors}"
assert len(errors) == 0, f"Should have no errors, got: {errors}"
print("[PASS] Valid controller accepted")

# Test 5: Controller with invalid state reference
print("\nTest 5: Controller with invalid state reference")
bad_controller = {
    "format_version": "1.8.0",
    "animation_controllers": {
        "controller.animation.test": {
            "initial_state": "idle",
            "states": {
                "idle": {
                    "animations": ["animation.test.idle"],
                    "transitions": [
                        {"nonexistent_state": "query.is_moving"}
                    ]
                }
            }
        }
    }
}

is_valid, errors = validate_animation_controller_format(bad_controller, "test")
assert not is_valid, "Should be invalid"
assert any("references unknown state" in e for e in errors), f"Should detect bad reference, got: {errors}"
print(f"[PASS] Bad state reference detected: {errors[0]}")

# Test 6: Missing format_version
print("\nTest 6: Missing format_version")
no_version_animation = {
    "animations": {
        "animation.test.walk": {"loop": True, "bones": {}}
    }
}

is_valid, errors = validate_animation_format(no_version_animation, "test")
assert not is_valid, "Should be invalid"
assert any("format_version" in e for e in errors), f"Should detect missing version, got: {errors}"
print(f"[PASS] Missing format_version detected: {errors[0]}")

# Test 7: Missing animations key
print("\nTest 7: Missing animations key")
no_animations = {
    "format_version": "1.8.0"
}

is_valid, errors = validate_animation_format(no_animations, "test")
assert not is_valid, "Should be invalid"
assert any("animations" in e for e in errors), f"Should detect missing animations, got: {errors}"
print(f"[PASS] Missing animations detected: {errors[0]}")

# Test 8: Empty animations dict
print("\nTest 8: Empty animations dict")
empty_animations = {
    "format_version": "1.8.0",
    "animations": {}
}

is_valid, errors = validate_animation_format(empty_animations, "test")
assert not is_valid, "Should be invalid"
assert any("empty" in e for e in errors), f"Should detect empty animations, got: {errors}"
print(f"[PASS] Empty animations detected: {errors[0]}")

# Test 9: None animation
print("\nTest 9: None animation")
is_valid, errors = validate_animation_format(None, "test")
assert not is_valid, "Should be invalid"
assert any("None" in e for e in errors), f"Should detect None, got: {errors}"
print(f"[PASS] None animation detected: {errors[0]}")

print("\n" + "="*60)
print("All validation tests passed! [OK]")
print("="*60)
