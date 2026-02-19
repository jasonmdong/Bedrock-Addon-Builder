import json


def extract_bone_metadata(geometry_data):
    """
    Parses a Bedrock geometry file to extract the skeletal hierarchy
    and pivot points for the bone_metadata DB field.

    Supports two formats:
    1. Standard: {"minecraft:geometry": [{"bones": [...]}]}
    2. Alternative: {"geometry.entity_name": {"bones": [...]}}

    Args:
        geometry_data: Either a dict (already parsed JSON) or a JSON string

    Returns:
        Dict with bone metadata, or None if no valid data
    """
    try:
        # Return None if no geometry data provided
        if geometry_data is None:
            return None

        # If it's a string, parse it; if it's already a dict, use it directly
        if isinstance(geometry_data, str):
            data = json.loads(geometry_data)
        elif isinstance(geometry_data, dict):
            data = geometry_data
        else:
            print(f"  ⚠ Invalid geometry data type: {type(geometry_data)}")
            return None

        bones_list = None

        # Try standard format first: "minecraft:geometry" array
        geometries = data.get("minecraft:geometry", [])
        if geometries and len(geometries) > 0:
            bones_list = geometries[0].get("bones", [])

        # If no bones found, try alternative format: "geometry.{name}" keys
        if not bones_list:
            # Look for keys starting with "geometry."
            for key in data.keys():
                if key.startswith("geometry."):
                    geometry_obj = data[key]
                    if isinstance(geometry_obj, dict) and "bones" in geometry_obj:
                        bones_list = geometry_obj.get("bones", [])
                        print(f"  Found bones in alternative format: {key}")
                        break

        # If still no bones found, return None
        if not bones_list:
            print(f"  ⚠ No bones found in geometry (tried both formats)")
            return None

        # Create metadata dictionary with bone information
        metadata = {
            "bone_count": len(bones_list),
            "bones": []
        }

        for bone in bones_list:
            # We only keep the logic: name, hierarchy, and joint location
            bone_info = {
                "name": bone.get("name"),
                "parent": bone.get("parent"),  # None if it's the root bone (like 'body')
                "pivot": bone.get("pivot", [0, 0, 0])
            }
            metadata["bones"].append(bone_info)

        print(f"  Extracted {len(bones_list)} bones")
        return metadata

    except Exception as e:
        print(f"  ✗ Error parsing geometry for bone metadata: {e}")
        return None

# Usage for your SQL Insert:
# metadata_for_db = json.dumps(extract_bone_metadata(raw_json_from_github))