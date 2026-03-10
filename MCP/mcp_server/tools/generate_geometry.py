"""
Tool: generate_mob_geometry — Uses GPT-4o to design a custom Bedrock geometry
(3D model) for a mob. The geometry is a JSON file with bones and cubes that
define the mob's unique body shape.

The output is a valid Bedrock geometry JSON that goes in:
  resource_packs/<pack>/models/entity/<mob>.geo.json
"""

import json
import os
import re
from openai import OpenAI


MODEL_NAME = os.environ.get("MOB_FORGE_GEOMETRY_MODEL") or os.environ.get("MOB_FORGE_MODEL") or "gpt-4o-mini"


GEOMETRY_SYSTEM_PROMPT = """You are an expert Minecraft Bedrock Edition 3D modeler.
Given a mob description, you design a CUSTOM geometry JSON that defines the mob's
unique 3D body shape using bones and cubes.

## BEDROCK GEOMETRY FORMAT
The geometry file uses format_version "1.12.0" and contains a "minecraft:geometry" array.
Each geometry has:
- description: identifier, texture_width, texture_height, visible_bounds_*
- bones: array of bones, each with name, parent, pivot, and cubes

Each CUBE has:
- origin: [x, y, z] — bottom-left corner position
- size: [width, height, depth] — dimensions in pixels (1 pixel = 1/16 block)
- uv: [u, v] — top-left corner of this cube's UV on the texture (Box UV mode)

## COORDINATE SYSTEM & SCALE
- Y is UP (ground is Y=0)
- Pivot points define where a bone rotates from
- Origin is the bottom-left-front corner of a cube
- **16 units = 1 Minecraft block**. A player is 32 units tall (2 blocks).
- A chicken is ~12 units tall. A cow is ~20 units. A zombie is 32. A horse is 26.
- An elephant should be ~40-48 units tall. A giraffe ~56-64. Scale appropriately!

## BOX UV MAPPING
With Box UV, each cube automatically maps to a rectangular region on the texture.
The UV coordinate [u, v] is the top-left corner. The cube's faces are laid out as:
  - Top/bottom faces at the top
  - Front/back/left/right faces below
A cube of size [W, H, D] uses a UV region of width (2*D + 2*W) x height (D + H).

## DESIGN RULES
1. Output ONLY valid JSON — no markdown, no code fences, no commentary.
2. Use format_version "1.12.0".
3. The geometry identifier MUST be "geometry.<mob_name>" (e.g., "geometry.jungle_elephant").
4. Use texture_width and texture_height of 64x64 (or 128x128 for large/complex mobs).
5. Design the mob to LOOK LIKE what it is:
   - An elephant needs: large barrel body, 4 thick legs, big head, trunk, large ears, small tail
   - A dragon needs: long body, 4 legs, 2 wings, long neck, head with horns, tail
   - A spider needs: round head, oval body, 8 thin legs
   - A wolf needs: head with snout, body, 4 slim legs, tail
6. Every mob MUST have a "body" bone as the main parent.
7. Keep cubes blocky — this is Minecraft! Sizes should be whole numbers.
8. Ground level is Y=0. Feet/bottom of legs should be near Y=0.
9. Center the mob on X=0, Z=0.
10. **SIZE MATTERS! 16 units = 1 block. A player is 32 units (2 blocks) tall.**
    - Tiny mobs (rabbit, bat): 6-10 units tall
    - Small mobs (chicken, cat): 10-16 units tall
    - Medium mobs (cow, pig, wolf): 16-24 units tall
    - Large mobs (horse, polar_bear): 24-32 units tall
    - Very large mobs (elephant, giraffe, dragon): 36-64 units tall
    - Massive mobs (iron golem, warden): 40-48 units tall
    Scale the WIDTH and DEPTH proportionally. An elephant body should be ~16 wide, ~28 deep.

## EXAMPLE: Simple quadruped (cow-like)
{
  "format_version": "1.12.0",
  "minecraft:geometry": [
    {
      "description": {
        "identifier": "geometry.custom_cow",
        "texture_width": 64,
        "texture_height": 64,
        "visible_bounds_width": 2,
        "visible_bounds_height": 2,
        "visible_bounds_offset": [0, 1, 0]
      },
      "bones": [
        {
          "name": "body",
          "pivot": [0, 13, 0],
          "cubes": [
            {"origin": [-6, 11, -5], "size": [12, 10, 18], "uv": [0, 0]}
          ]
        },
        {
          "name": "head",
          "parent": "body",
          "pivot": [0, 20, -6],
          "cubes": [
            {"origin": [-4, 16, -14], "size": [8, 8, 8], "uv": [0, 28]}
          ]
        },
        {
          "name": "leg_front_left",
          "parent": "body",
          "pivot": [4, 11, -3],
          "cubes": [
            {"origin": [2, 0, -5], "size": [4, 11, 4], "uv": [36, 0]}
          ]
        },
        {
          "name": "leg_front_right",
          "parent": "body",
          "pivot": [-4, 11, -3],
          "cubes": [
            {"origin": [-6, 0, -5], "size": [4, 11, 4], "uv": [36, 15]}
          ]
        },
        {
          "name": "leg_back_left",
          "parent": "body",
          "pivot": [4, 11, 11],
          "cubes": [
            {"origin": [2, 0, 9], "size": [4, 11, 4], "uv": [52, 0]}
          ]
        },
        {
          "name": "leg_back_right",
          "parent": "body",
          "pivot": [-4, 11, 11],
          "cubes": [
            {"origin": [-6, 0, 9], "size": [4, 11, 4], "uv": [52, 15]}
          ]
        }
      ]
    }
  ]
}

## EXAMPLE: Humanoid (zombie-like)
{
  "format_version": "1.12.0",
  "minecraft:geometry": [
    {
      "description": {
        "identifier": "geometry.custom_zombie",
        "texture_width": 64,
        "texture_height": 64,
        "visible_bounds_width": 1,
        "visible_bounds_height": 2,
        "visible_bounds_offset": [0, 1, 0]
      },
      "bones": [
        {
          "name": "body",
          "pivot": [0, 24, 0],
          "cubes": [
            {"origin": [-4, 12, -2], "size": [8, 12, 4], "uv": [16, 16]}
          ]
        },
        {
          "name": "head",
          "parent": "body",
          "pivot": [0, 24, 0],
          "cubes": [
            {"origin": [-4, 24, -4], "size": [8, 8, 8], "uv": [0, 0]}
          ]
        },
        {
          "name": "right_arm",
          "parent": "body",
          "pivot": [-5, 22, 0],
          "cubes": [
            {"origin": [-8, 12, -2], "size": [4, 12, 4], "uv": [40, 16]}
          ]
        },
        {
          "name": "left_arm",
          "parent": "body",
          "pivot": [5, 22, 0],
          "cubes": [
            {"origin": [4, 12, -2], "size": [4, 12, 4], "uv": [32, 48]}
          ]
        },
        {
          "name": "right_leg",
          "parent": "body",
          "pivot": [-2, 12, 0],
          "cubes": [
            {"origin": [-4, 0, -2], "size": [4, 12, 4], "uv": [0, 16]}
          ]
        },
        {
          "name": "left_leg",
          "parent": "body",
          "pivot": [2, 12, 0],
          "cubes": [
            {"origin": [0, 0, -2], "size": [4, 12, 4], "uv": [16, 48]}
          ]
        }
      ]
    }
  ]
}

## EXAMPLE: Flying mob (dragon/phantom-like)
{
  "format_version": "1.12.0",
  "minecraft:geometry": [
    {
      "description": {
        "identifier": "geometry.custom_dragon",
        "texture_width": 128,
        "texture_height": 128,
        "visible_bounds_width": 4,
        "visible_bounds_height": 3,
        "visible_bounds_offset": [0, 1.5, 0]
      },
      "bones": [
        {
          "name": "body",
          "pivot": [0, 12, 0],
          "cubes": [
            {"origin": [-4, 10, -8], "size": [8, 6, 20], "uv": [0, 0]}
          ]
        },
        {
          "name": "head",
          "parent": "body",
          "pivot": [0, 14, -8],
          "cubes": [
            {"origin": [-3, 12, -16], "size": [6, 5, 8], "uv": [0, 26]}
          ]
        },
        {
          "name": "tail",
          "parent": "body",
          "pivot": [0, 12, 12],
          "cubes": [
            {"origin": [-2, 11, 12], "size": [4, 3, 12], "uv": [56, 0]}
          ]
        },
        {
          "name": "wing_left",
          "parent": "body",
          "pivot": [4, 14, 0],
          "cubes": [
            {"origin": [4, 13, -4], "size": [16, 1, 12], "uv": [0, 39]}
          ]
        },
        {
          "name": "wing_right",
          "parent": "body",
          "pivot": [-4, 14, 0],
          "cubes": [
            {"origin": [-20, 13, -4], "size": [16, 1, 12], "uv": [0, 52]}
          ]
        },
        {
          "name": "leg_front_left",
          "parent": "body",
          "pivot": [3, 10, -4],
          "cubes": [
            {"origin": [1, 0, -6], "size": [4, 10, 4], "uv": [56, 15]}
          ]
        },
        {
          "name": "leg_front_right",
          "parent": "body",
          "pivot": [-3, 10, -4],
          "cubes": [
            {"origin": [-5, 0, -6], "size": [4, 10, 4], "uv": [56, 29]}
          ]
        }
      ]
    }
  ]
}

## YOUR TASK
Design a UNIQUE geometry for the requested mob. Make it look like that creature!
Be creative with the bone structure — add distinctive features (trunk, horns, wings,
tail, fins, tentacles, etc.) that make the mob recognizable.

Output ONLY the geometry JSON. No extra text."""


def get_client() -> OpenAI:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable is required.")
    return OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
    )


def validate_geometry(geo_data: dict) -> dict:
    """Validate and fix geometry JSON to ensure Bedrock compatibility."""
    if "format_version" not in geo_data:
        geo_data["format_version"] = "1.12.0"

    geos = geo_data.get("minecraft:geometry", [])
    if not geos:
        raise ValueError("Missing minecraft:geometry array")

    geo = geos[0]
    desc = geo.get("description", {})
    if "identifier" not in desc:
        raise ValueError("Missing geometry identifier")
    if not desc["identifier"].startswith("geometry."):
        desc["identifier"] = f"geometry.{desc['identifier']}"

    if "texture_width" not in desc:
        desc["texture_width"] = 64
    if "texture_height" not in desc:
        desc["texture_height"] = 64

    bones = geo.get("bones", [])
    if not bones:
        raise ValueError("Geometry has no bones")

    # Ensure there's a body bone
    bone_names = {b["name"] for b in bones}
    if "body" not in bone_names:
        # Try to find a root-like bone and rename it
        for b in bones:
            if b.get("parent") is None or b["name"] == "root":
                if "cubes" in b and b["cubes"]:
                    b["name"] = "body"
                    break

    return geo_data


async def generate_mob_geometry(
    mob_name: str,
    description: str = "",
    collision_width: float = 0.9,
    collision_height: float = 1.4,
) -> str:
    """
    Generate a custom Bedrock geometry (3D model) for a mob.

    Args:
        mob_name: Snake_case name (e.g., "jungle_elephant")
        description: Natural language description of what the mob looks like
        collision_width: Entity collision box width (for scale reference)
        collision_height: Entity collision box height (for scale reference)

    Returns:
        JSON with the geometry data and metadata.
    """
    client = get_client()

    # Scale: 16 geometry units = 1 Minecraft block
    # collision_height is in blocks, multiply by 16 to get geometry units
    height_units = int(collision_height * 16)
    width_units = int(collision_width * 16)

    user_msg = (
        f"Mob name: {mob_name}\n"
        f"Description: {description}\n"
        f"The geometry identifier must be: geometry.{mob_name}\n\n"
        f"SIZE REQUIREMENTS (16 units = 1 block, player = 32 units tall):\n"
        f"- This mob should be approximately {height_units} units tall and {width_units} units wide.\n"
        f"- That equals roughly {collision_height:.1f} blocks tall and {collision_width:.1f} blocks wide.\n"
        f"- The TOP of the head/highest point should be near Y={height_units}.\n"
        f"- The BOTTOM of the feet should be at Y=0.\n\n"
        f"Design a unique 3D model for this creature. Make it look like a {description or mob_name}!\n"
        f"Output ONLY the geometry JSON."
    )

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": GEOMETRY_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.7,
        max_tokens=8192,
    )

    raw_text = response.choices[0].message.content.strip()

    # Strip markdown fences
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines)

    json_match = re.search(r'\{[\s\S]*\}', raw_text)
    if json_match:
        raw_text = json_match.group()

    try:
        geo_data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Failed to parse geometry JSON: {str(e)}",
            "raw_response": raw_text[:500],
        })

    try:
        geo_data = validate_geometry(geo_data)
    except ValueError as e:
        return json.dumps({
            "error": f"Geometry validation failed: {str(e)}",
        })

    # Extract texture size from the geometry
    geo = geo_data["minecraft:geometry"][0]
    desc = geo["description"]
    tex_w = desc.get("texture_width", 64)
    tex_h = desc.get("texture_height", 64)

    return json.dumps({
        "status": "success",
        "geometry": geo_data,
        "geometry_id": desc["identifier"],
        "texture_width": tex_w,
        "texture_height": tex_h,
        "bone_count": len(geo.get("bones", [])),
    })
