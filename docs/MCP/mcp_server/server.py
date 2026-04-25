"""
Mob Forge MCP Server — Main entry point.
Registers 3 tools for Minecraft Bedrock mob generation and runs on stdio.
"""

import json
import os
import sys

# Ensure the mcp_server directory is on sys.path so 'from tools.xxx' imports work
# regardless of the working directory the subprocess is started in.
_server_dir = os.path.dirname(os.path.abspath(__file__))
if _server_dir not in sys.path:
    sys.path.insert(0, _server_dir)

from mcp.server.fastmcp import FastMCP

# Create the MCP server
mcp = FastMCP("Mob Forge")


# ─── Tool 1: generate_mob ──────────────────────────────────────────────────────

@mcp.tool()
async def generate_mob(description: str, difficulty: str = "medium") -> str:
    """
    Generate a Minecraft Bedrock entity from a natural language description.

    Args:
        description: Natural language description of the desired mob
                     (e.g., "A fire-breathing dragon that flies and has 100 HP")
        difficulty: Difficulty preset - "easy", "medium", or "hard".
                    Affects stat ranges and abilities.

    Returns:
        JSON string with the complete Bedrock entity spec and metadata.
    """
    try:
        from tools.generate_mob import generate_mob as _generate_mob
    except ImportError as e:
        print(f"[MCP ERROR] Failed to import generate_mob: {e}", file=sys.stderr)
        return json.dumps({"error": f"Import failed: {e}"})
    return await _generate_mob(description, difficulty)


# ─── Tool 2: build_mob_pack ────────────────────────────────────────────────────

@mcp.tool()
async def build_mob_pack(mobs: list[dict], pack_name: str = "custom_mobs") -> str:
    """
    Build .mcpack files from one or more mob entity specs.

    Args:
        mobs: List of mob objects, each containing "entity" (the Bedrock entity JSON)
              and optionally "metadata" and "texture_base64".
        pack_name: Name for the addon pack.

    Returns:
        JSON with base64-encoded .mcpack files and filenames.
    """
    try:
        from tools.build_mob_pack import build_mob_pack as _build_mob_pack
    except ImportError as e:
        print(f"[MCP ERROR] Failed to import build_mob_pack: {e}", file=sys.stderr)
        return json.dumps({"error": f"Import failed: {e}"})
    return await _build_mob_pack(mobs, pack_name)


# ─── Tool 3: generate_mob_texture ──────────────────────────────────────────────

@mcp.tool()
async def generate_mob_texture(
    mob_name: str,
    description: str = "",
    style: str = "biped",
    colors: list[str] | None = None,
    size: int = 16,
) -> str:
    """
    Generate a pixel-art texture for a Minecraft mob.

    Args:
        mob_name: Name of the mob.
        description: Description of the mob's appearance.
        style: Body style — "biped", "quadruped", "dragon", "slime", or "spider".
        colors: Hex color palette (e.g., ["#FF4400", "#FFaa00", "#220000"]).
        size: Texture size (16 or 32).

    Returns:
        JSON with base64-encoded PNG texture and dimensions.
    """
    try:
        from tools.generate_texture import generate_mob_texture as _generate_mob_texture
    except ImportError as e:
        print(f"[MCP ERROR] Failed to import generate_mob_texture: {e}", file=sys.stderr)
        return json.dumps({"error": f"Import failed: {e}"})
    return await _generate_mob_texture(mob_name, description, style, colors, size)


# ─── Tool 4: build_mcworld ────────────────────────────────────────────────────

@mcp.tool()
async def build_mcworld(mobs: list[dict], pack_name: str = "custom_mobs") -> str:
    """
    Build a .mcworld file — a complete Minecraft Bedrock world with custom mobs
    already summoned near spawn.

    Args:
        mobs: List of mob objects, each containing "entity", "metadata",
              and optionally "texture_base64".
        pack_name: Name for the world and addon packs.

    Returns:
        JSON with base64-encoded .mcworld file and filename.
    """
    try:
        from tools.build_mcworld import build_mcworld as _build_mcworld
    except ImportError as e:
        print(f"[MCP ERROR] Failed to import build_mcworld: {e}", file=sys.stderr)
        return json.dumps({"error": f"Import failed: {e}"})
    return await _build_mcworld(mobs, pack_name)


# ─── Tool 5: generate_mob_geometry ─────────────────────────────────────────────

@mcp.tool()
async def generate_mob_geometry(
    mob_name: str,
    description: str = "",
    collision_width: float = 0.9,
    collision_height: float = 1.4,
) -> str:
    """
    Generate a custom Bedrock geometry (3D model) for a mob.

    Args:
        mob_name: Snake_case mob name (e.g., "jungle_elephant").
        description: What the mob looks like.
        collision_width: Entity collision box width for scale reference.
        collision_height: Entity collision box height for scale reference.

    Returns:
        JSON with the geometry data, geometry_id, and texture dimensions.
    """
    try:
        from tools.generate_geometry import generate_mob_geometry as _gen_geo
    except ImportError as e:
        print(f"[MCP ERROR] Failed to import generate_mob_geometry: {e}", file=sys.stderr)
        return json.dumps({"error": f"Import failed: {e}"})
    return await _gen_geo(mob_name, description, collision_width, collision_height)


# ─── Run ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
