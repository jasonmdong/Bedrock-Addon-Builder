"""Core constants, configuration, and defaults."""
import os
import re
from pathlib import Path

# Default mob specification
DEFAULTS = {
    "identifier": "cont_stoo:stoopidcow",
    "display_name": "Stoopid Cow",
    "short_name": "stoopidcow",
    "engine_min": [1, 21, 110],
    "hp": 20,
    "damage": 4,
    "speed": 0.30,  # a bit faster so pursuit is noticeable
    "collision_box": {"width": 0.9, "height": 1.4},
    "geometry": "geometry.cow",
    "render_controller": "controller.render.default",
    "texture_hint": "solid red 128x128",
    "egg_base": "#FF0000",
    "egg_overlay": "#550000",
    "scale": 1.0,
    "color_rgb": [255, 0, 0],
    "geometry_json": {},
    "texture_instructions": []
}

# Named color palette for texture hints
COLOR_WORDS = {
    "red": (255, 0, 0),
    "blue": (40, 120, 255),
    "green": (0, 180, 80),
    "yellow": (240, 200, 0),
    "purple": (160, 60, 220),
    "white": (255, 255, 255),
    "black": (10, 10, 10),
    "orange": (255, 140, 0),
    "pink": (255, 105, 180),
    "cyan": (0, 200, 200),
}

# Paths - BASE_DIR is project root (parent of backend/)
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BACKEND_DIR / "schemas" / "mob_spec.schema.json"
SPECS_DIR = BASE_DIR / "data" / "specs"
FRONTEND_DIR = BASE_DIR / "frontend"

# Regex validators
IDENTIFIER_RE = re.compile(r"^[a-z0-9_]+:[a-z0-9_]+$")
SHORT_NAME_RE = re.compile(r"^[a-z0-9_]+$")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# LLM configuration
LLM_MODEL_NAME = os.environ.get("LLM_MODEL", "gpt-4o")
DEEPSEEK_MODEL_NAME = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-1.5-pro")
CLAUDE_MODEL_NAME = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20240620")
DEFAULT_LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")

# World template candidates (now in data/templates/)
DATA_DIR = BASE_DIR / "data"
WORLD_TEMPLATE_BASES = [
    DATA_DIR / "templates" / "base_world",
    DATA_DIR / "templates" / "base_world.mcworld",
    DATA_DIR / "templates" / "base_world.zip",
    DATA_DIR / "base_world",
    DATA_DIR / "base_world.mcworld",
    DATA_DIR / "base_world.zip",
]

# LLM system prompt
LLM_SYSTEM_PROMPT = """You are an expert Minecraft Bedrock Add-on developer.
You edit Mob Specifications (MobSpec) to fulfill user requests.

FIELDS OVERVIEW:
1. BEHAVIOR: Use the 'components' object to add/remove AI goals.
2. GEOMETRY: 
   - 'geometry' (string): Use for vanilla models (e.g. "geometry.cow").
   - 'geometry_json' (object): Use for CUSTOM 3D models. Provide a full 'minecraft:geometry' object.
3. VISUALS:
   - 'color_rgb' (array): Set the base color [R, G, B].
   - 'texture_instructions' (array): Describe the texture style (e.g. ["scales", "glowing eyes", "lava cracks"]).

GEOMETRY JSON FORMAT:
{
  "format_version": "1.12.0",
  "minecraft:geometry": [
    {
      "description": { "identifier": "geometry.custom", "texture_width": 64, "texture_height": 64 },
      "bones": [
        { "name": "root", "pivot": [0, 0, 0], "cubes": [ { "origin": [-4,0,-4], "size": [8,8,8], "uv": [0,0] } ] }
      ]
    }
  ]
}

CRITICAL RULES:
1. ALWAYS return a single VALID JSON object matching the schema.
2. Include ALL required keys: identifier, display_name, short_name, engine_min, hp, damage, speed, collision_box, geometry, geometry_json, render_controller, texture_hint, texture_instructions, color_rgb, egg_base, egg_overlay, scale, components.
3. If the user wants a custom shape (e.g. "three heads"), use 'geometry_json'.
4. BONE NAMING FOR ANIMATIONS: If you want the mob to use vanilla walk/look animations, you MUST use standard bone names in 'geometry_json': 'head', 'body', 'leg0', 'leg1', 'leg2', 'leg3'.
5. To delete a default component, set it to null in 'components'.
6. For explosive behavior, you MUST have both "minecraft:behavior.swell" and "minecraft:explode".
"""
