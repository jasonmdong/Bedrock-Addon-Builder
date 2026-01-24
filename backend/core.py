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
    "scale": 1.0
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
LLM_SYSTEM_PROMPT = """You edit Bedrock mob specs.
Respond with a single JSON object matching the provided schema.
Respect the existing namespace and only change fields the user mentions.
Always include every required key (identifier, display_name, short_name, engine_min, hp, damage, speed,
collision_box, geometry, render_controller, texture_hint, egg_base, egg_overlay, scale)."""
