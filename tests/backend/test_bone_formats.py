"""
Test the updated get_bone_data to handle both geometry formats
"""

import get_bone_data

print("=" * 80)
print("Testing Bone Data Extraction - Both Formats")
print("=" * 80)

# Test 1: Standard minecraft:geometry format
print("\nTest 1: Standard Format (minecraft:geometry)")
print("-" * 80)
standard_format = {
    "format_version": "1.12.0",
    "minecraft:geometry": [
        {
            "description": {
                "identifier": "geometry.creeper",
                "texture_width": 64,
                "texture_height": 32
            },
            "bones": [
                {
                    "name": "body",
                    "pivot": [0.0, 18.0, 0.0],
                    "cubes": [
                        {"origin": [-4.0, 6.0, -2.0], "size": [8, 12, 4], "uv": [16, 16]}
                    ]
                },
                {
                    "name": "head",
                    "parent": "body",
                    "pivot": [0.0, 18.0, 0.0],
                    "cubes": [
                        {"origin": [-4.0, 18.0, -4.0], "size": [8, 8, 8], "uv": [0, 0]}
                    ]
                }
            ]
        }
    ]
}

result = get_bone_data.extract_bone_metadata(standard_format)
if result:
    print(f"✓ Success! Found {result['bone_count']} bones")
    print(f"  Bones: {[b['name'] for b in result['bones']]}")
else:
    print("✗ Failed to extract bones")

# Test 2: Alternative geometry.{name} format
print("\nTest 2: Alternative Format (geometry.bat)")
print("-" * 80)
alternative_format = {
    "format_version": "1.8.0",
    "geometry.bat": {
        "visible_bounds_width": 1,
        "visible_bounds_height": 1,
        "visible_bounds_offset": [0, 0.5, 0],
        "bones": [
            {
                "name": "head",
                "pivot": [0.0, 24.0, 0.0],
                "cubes": [
                    {
                        "origin": [-3.0, 21.0, -3.0],
                        "size": [6, 6, 6],
                        "uv": [0, 0]
                    }
                ]
            },
            {
                "name": "body",
                "pivot": [0.0, 24.0, 0.0],
                "cubes": [
                    {
                        "origin": [-3.0, 17.0, -3.0],
                        "size": [6, 2, 6],
                        "uv": [0, 16]
                    }
                ]
            }
        ]
    }
}

result = get_bone_data.extract_bone_metadata(alternative_format)
if result:
    print(f"✓ Success! Found {result['bone_count']} bones")
    print(f"  Bones: {[b['name'] for b in result['bones']]}")
else:
    print("✗ Failed to extract bones")

# Test 3: No bones (should return None)
print("\nTest 3: No Bones (should return None)")
print("-" * 80)
no_bones = {
    "format_version": "1.8.0",
    "minecraft:geometry": [
        {
            "description": {"identifier": "geometry.item"},
            "bones": []
        }
    ]
}

result = get_bone_data.extract_bone_metadata(no_bones)
if result is None:
    print("✓ Correctly returned None for empty bones")
else:
    print(f"✗ Should have returned None, got: {result}")

# Test 4: None input (should return None)
print("\nTest 4: None Input (should return None)")
print("-" * 80)
result = get_bone_data.extract_bone_metadata(None)
if result is None:
    print("✓ Correctly returned None for None input")
else:
    print(f"✗ Should have returned None, got: {result}")

# Test 5: Invalid format (should return None)
print("\nTest 5: Invalid Format (should return None)")
print("-" * 80)
invalid = {
    "format_version": "1.8.0",
    "some_other_key": {}
}

result = get_bone_data.extract_bone_metadata(invalid)
if result is None:
    print("✓ Correctly returned None for invalid format")
else:
    print(f"✗ Should have returned None, got: {result}")

print("\n" + "=" * 80)
print("All Tests Complete!")
print("=" * 80)

