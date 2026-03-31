#!/usr/bin/env python3
"""Test the robust JSON extraction function."""

import json
import sys
sys.path.insert(0, '/c/Users/caitl/Bedrock-Addon-Builder')

from backend.llm.animation_generation import _extract_json_from_response

# Test case 1: Pure JSON (should pass)
print("Test 1: Pure JSON")
pure_json = '{"format_version": "1.8.0", "animations": {"test": {}}}'
result = _extract_json_from_response(pure_json)
assert result is not None, "Failed to extract pure JSON"
assert result.get("format_version") == "1.8.0", "Incorrect format_version"
print("[PASS]")

# Test case 2: JSON with preamble text (now common issue)
print("\nTest 2: JSON with preamble")
with_preamble = """Here's the animation JSON you requested:

{
  "format_version": "1.8.0",
  "animations": {
    "animation.test.walk": {
      "loop": true,
      "bones": {}
    }
  }
}

I've created a simple walk animation."""

result = _extract_json_from_response(with_preamble)
assert result is not None, "Failed to extract JSON with preamble"
assert result.get("format_version") == "1.8.0", "Incorrect format_version in preamble test"
print("[PASS]")

# Test case 3: JSON with trailing text
print("\nTest 3: JSON with trailing text")
with_trailing = """{
  "format_version": "1.8.0",
  "animations": {"test": {}}
}

This is the animation controller."""

result = _extract_json_from_response(with_trailing)
assert result is not None, "Failed to extract JSON with trailing text"
print("[PASS]")

# Test case 4: Multi-line complex JSON
print("\nTest 4: Complex multi-line JSON")
complex_json = """{
  "format_version": "1.8.0",
  "animations": {
    "animation.mob.walk": {
      "loop": true,
      "anim_time_update": "query.modified_distance_moved",
      "bones": {
        "leg0": {
          "rotation": [
            "Math.cos(q.anim_time) * 45",
            0,
            0
          ]
        },
        "leg1": {
          "rotation": [
            "Math.cos(q.anim_time + 3.14159) * 45",
            0,
            0
          ]
        }
      }
    }
  }
}"""

result = _extract_json_from_response(complex_json)
assert result is not None, "Failed to extract complex JSON"
assert "animation.mob.walk" in result.get("animations", {}), "Missing animation"
print("[PASS]")

# Test case 5: Malformed JSON (should fail gracefully)
print("\nTest 5: Malformed JSON")
malformed = '{"format_version": "1.8.0", "incomplete": }'
result = _extract_json_from_response(malformed)
print(f"  Result (expected None): {result}")
print("[PASS]")

# Test case 6: Real-world Claude response simulation
print("\nTest 6: Simulating Claude response")
claude_response = """I'll create a walk animation for your mob with proper bone rotations.

{
  "format_version": "1.8.0",
  "animations": {
    "animation.dragonfly.walk": {
      "loop": true,
      "anim_time_update": "query.modified_distance_moved",
      "bones": {
        "wing1": {
          "rotation": ["Math.sin(q.anim_time * 3.0) * 30", 0, 0]
        },
        "wing2": {
          "rotation": ["Math.sin(q.anim_time * 3.0 + 3.14159) * 30", 0, 0]
        }
      }
    },
    "animation.dragonfly.idle": {
      "loop": true,
      "anim_time_update": "query.time_of_day_cycle",
      "bones": {
        "wing1": {
          "rotation": ["Math.sin(q.anim_time * 1.0) * 5", 0, 0]
        }
      }
    }
  }
}

The animations use query.modified_distance_moved for walk and query.time_of_day_cycle for idle."""

result = _extract_json_from_response(claude_response)
assert result is not None, "Failed to extract from Claude-like response"
assert result.get("format_version") == "1.8.0", "Incorrect format_version from Claude response"
assert "animation.dragonfly.walk" in result.get("animations", {}), "Missing walk animation"
print("[PASS]")

print("\n" + "="*50)
print("All tests passed!")
print("="*50)
