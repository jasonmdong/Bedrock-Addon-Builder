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
    "animation_json": {},
    "animation_controller_json": {},
    "animation_controller": "",
    "texture_instructions": [],
    "loot_drops": []
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

# Paths - BASE_DIR is project root
# Since core.py is at backend/core/core.py:
# .parent = backend/core
# .parent.parent = backend
# .parent.parent.parent = project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = BACKEND_DIR / "schemas" / "mob_spec.schema.json"
SPECS_DIR = BASE_DIR / "data" / "specs"
FRONTEND_DIR = BASE_DIR / "frontend"

# Regex validators
IDENTIFIER_RE = re.compile(r"^[a-z0-9_]+:[a-z0-9_]+$")
SHORT_NAME_RE = re.compile(r"^[a-z0-9_]+$")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# LLM configuration
LLM_MODEL_NAME = os.environ.get("LLM_MODEL", "openai/gpt-4.1")
DEEPSEEK_MODEL_NAME = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
<<<<<<< HEAD
CLAUDE_MODEL_NAME = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
=======
CLAUDE_MODEL_NAME = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")
>>>>>>> dd7b2cf1f8157a2e63658ed680f797c20840bc1c
OLLAMA_MODEL_NAME = os.environ.get("OLLAMA_MODEL", "llama3")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")

# Log LLM configuration on startup
import sys
if not getattr(sys, '_llm_config_logged', False):
    print(f"[LLM-CONFIG] LLM_MODEL_NAME: {LLM_MODEL_NAME}")
    print(f"[LLM-CONFIG] DEEPSEEK_MODEL_NAME: {DEEPSEEK_MODEL_NAME}")
    print(f"[LLM-CONFIG] GEMINI_MODEL_NAME: {GEMINI_MODEL_NAME}")
    print(f"[LLM-CONFIG] CLAUDE_MODEL_NAME: {CLAUDE_MODEL_NAME}")
    print(f"[LLM-CONFIG] OLLAMA_MODEL_NAME: {OLLAMA_MODEL_NAME}")
    print(f"[LLM-CONFIG] DEFAULT_LLM_PROVIDER: {DEFAULT_LLM_PROVIDER}")
    sys._llm_config_logged = True

# local dev flag toggle (need to fix server side sync still)
LOCAL_LLM_DEV = True

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
   - 'geometry' (string): The geometry reference ID. For known vanilla mobs, use the vanilla geometry ID (e.g. "geometry.ghast", "geometry.cow", "geometry.zombie", "geometry.spider", "geometry.creeper", "geometry.chicken", "geometry.pig", "geometry.wolf", "geometry.skeleton", "geometry.blaze", "geometry.enderman", "geometry.slime", "geometry.iron_golem"). The app will auto-fetch the real Mojang geometry for rendering.
   - 'geometry_json' (object): ONLY use for truly custom/invented shapes that don't exist in vanilla Minecraft. Set to {} (empty object) when using a vanilla geometry reference.
3. VISUALS:
   - 'color_rgb' (array): Set the base color [R, G, B]. IMPORTANT: Update this when changing mob type (e.g. ghast=[246,246,246], zombie=[76,122,58], creeper=[76,175,80], spider=[58,42,26], blaze=[245,205,50]).
   - 'texture_instructions' (array): Per-bone color and pattern directives applied to the procedural texture.
     IMPORTANT: Use ONE entry per body part or pattern. Do NOT combine multiple body parts in one string.
     Format: ["<color> <body_part>", "<pattern>"] where body_part is head/body/leg/arm/tail/ear/face.
     Color words: red, blue, green, yellow, orange, purple, pink, brown, black, white, gray, gold, cyan, dark red, light blue, bright red, etc. Or hex like #CC0000.
     Pattern words: spots, stripes, scales, patches, fur, glow, rocky, dotted, banded.
     GOOD: ["red head", "dark green body", "dark green legs", "scales"]
     BAD:  ["Head: red, Body: green with scales"]  ← do NOT combine like this
     Always include at least a pattern keyword entry when relevant.

GEOMETRY RULES:
- For VANILLA Minecraft mobs (ghast, cow, zombie, creeper, spider, chicken, pig, wolf, skeleton, blaze, enderman, slime, iron_golem, etc.), use the vanilla geometry reference and set geometry_json={}.
  Example: user says "turn it into a ghast" → geometry="geometry.ghast", geometry_json={}.
- For NON-VANILLA creatures (elephant, dragon, dinosaur, unicorn, robot, etc.), you MUST generate custom geometry_json with an appropriate body shape. Do NOT use a cow/pig/zombie model as a substitute — build the right shape.
  Example: user says "make an elephant" → geometry="geometry.custom_elephant", geometry_json={full custom geometry with large body, trunk, big ears, thick legs}.
- When you generate custom geometry_json, use this format:
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

LOOT DROPS:
- When the user asks the mob to drop specific items on death, you MUST add TWO things:
  1. In 'components': "minecraft:loot": {"table": "loot_tables/entities/<short_name>.json"}
  2. A top-level 'loot_drops' array with STRUCTURED entries:
     "loot_drops": [{"item": "minecraft:diamond", "count_min": 1, "count_max": 3, "chance": 1.0}]
- Each entry MUST have: "item" (full Bedrock item ID like "minecraft:diamond"), "count_min" (int), "count_max" (int), "chance" (float 0.0-1.0)
- Common item IDs: minecraft:diamond, minecraft:gold_ingot, minecraft:iron_ingot, minecraft:emerald, minecraft:bone, minecraft:leather, minecraft:blaze_rod, minecraft:ender_pearl, minecraft:nether_star, minecraft:coal, minecraft:redstone, minecraft:netherite_scrap, minecraft:arrow, minecraft:fire_charge, minecraft:magma_cream, minecraft:ghast_tear, minecraft:egg, minecraft:cooked_beef
- ALWAYS include loot_drops when the user mentions drops/loot/items on death

CRITICAL RULES:
1. ALWAYS return a single VALID JSON object matching the schema.
2. Include ALL required keys: identifier, display_name, short_name, engine_min, hp, damage, speed, collision_box, geometry, geometry_json, render_controller, texture_hint, texture_instructions, color_rgb, egg_base, egg_overlay, scale, components.
3. Use vanilla geometry for vanilla mobs. Generate custom geometry_json for non-vanilla creatures (elephant, dragon, etc.).
4. BONE NAMING FOR ANIMATIONS: If you use custom geometry_json, use standard bone names: 'head', 'body', 'leg0', 'leg1', 'leg2', 'leg3'.
5. To delete a default component, set it to null in 'components'.
6. For explosive behavior, you MUST have both "minecraft:behavior.swell" and "minecraft:explode".
7. ALWAYS update color_rgb when changing the mob type — it controls the texture color.
8. PRESERVE GEOMETRY ON ITERATION: If the current spec has geometry_json marked as "(CUSTOM GEOMETRY PRESENT — DO NOT REPLACE)", keep geometry and geometry_json EXACTLY as they are. Only change geometry if the user explicitly asks to change the mob's shape/model/body. For behavior-only changes (loot, damage, speed, abilities, etc.), keep the existing geometry and geometry_json unchanged. Set geometry_json to {} ONLY if switching to a vanilla geometry reference.
"""
