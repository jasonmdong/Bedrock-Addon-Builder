#!/usr/bin/env python3
"""
LLM Evaluation Framework for Bedrock Addon Builder.

Loads test cases from data/test_cases.json, runs them through an LLM provider,
and validates outputs using strict requirement checks and semantic consistency rules.

Usage:
    python scripts/evaluate_llm.py                          # mock (default)
    python scripts/evaluate_llm.py --provider anthropic      # Claude
    python scripts/evaluate_llm.py --provider openai         # GPT-4o
    python scripts/evaluate_llm.py --provider openai --model gpt-4o-mini
    python scripts/evaluate_llm.py --provider ollama           # local Ollama (llama3)
    python scripts/evaluate_llm.py --provider ollama --model mistral
    python scripts/evaluate_llm.py -v -c entity_logic_ai     # verbose + filter
"""
import json
import re
import os
import sys
import copy
import uuid as _uuid_mod
import argparse
import requests
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
TEST_CASES_PATH = PROJECT_ROOT / "data" / "test_cases.json"

# ---------------------------------------------------------------------------
# ANSI colors (graceful fallback on Windows without VT support)
# ---------------------------------------------------------------------------
try:
    os.system("")  # enable VT100 on Windows 10+
except Exception:
    pass

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


# =============================================================================
# STEP 1 — Load test cases
# =============================================================================

def load_test_cases(path: Path = TEST_CASES_PATH) -> list[dict]:
    """Load and parse test_cases.json, filtering out __divider__ objects."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    tests = data.get("tests", [])
    return [t for t in tests if "__divider__" not in t]


# =============================================================================
# STEP 2 — LLM provider logic
# =============================================================================

# Optional imports — fail gracefully so mock always works
try:
    import anthropic as _anthropic_mod
except ImportError:
    _anthropic_mod = None

try:
    from openai import OpenAI as _OpenAI
except ImportError:
    _OpenAI = None

# Default models per provider
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "ollama": "llama3.2",
}

OLLAMA_BASE_URL = "http://localhost:11435"

# ---------------------------------------------------------------------------
# Context injection — mirrors backend/llm.py's _get_full_system_prompt()
# ---------------------------------------------------------------------------

# Load schemas + vanilla reference from backend (same files the backend uses)
SCHEMAS_DIR = PROJECT_ROOT / "backend" / "schemas"
VANILLA_REF_PATH = PROJECT_ROOT / "backend" / "data" / "vanilla_reference.json"

# Map each category to its schema file
_CATEGORY_SCHEMA_FILES = {
    "entity_logic_ai": "mob_spec.schema.json",
    "items_weaponry": "item_spec.schema.json",
    "blocks_furniture": "block_spec.schema.json",
    "loot_recipes": "loot_spec.schema.json",
    "scripting_components": "manifest_spec.schema.json",
}

_CATEGORY_SCHEMAS: dict[str, dict] = {}
for _cat, _fname in _CATEGORY_SCHEMA_FILES.items():
    _spath = SCHEMAS_DIR / _fname
    if _spath.exists():
        try:
            _CATEGORY_SCHEMAS[_cat] = json.loads(_spath.read_text(encoding="utf-8"))
        except Exception:
            pass

_VANILLA_REF: dict = {}
if VANILLA_REF_PATH.exists():
    try:
        _VANILLA_REF = json.loads(VANILLA_REF_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Strategy-based system prompts
# ---------------------------------------------------------------------------

# zero_shot — minimal rules, no examples, no schemas
_ZERO_SHOT_SYSTEM_PROMPT = """You are an expert Minecraft Bedrock Edition add-on developer.
You will be given a JSON input and a natural-language instruction.
Your job is to modify or create the JSON to fulfill the instruction.

CRITICAL RULES:
1. Return ONLY a single valid JSON object. No markdown, no explanation, no extra text.
2. Preserve all existing fields unless the instruction explicitly asks to change them.
3. Do NOT invent components that don't exist in Bedrock Edition.
4. Component dependencies: behavior.swell requires explode, tameable requires behavior.beg,
   shooter requires behavior.ranged_attack, rideable requires input_ground_controlled.
"""

# few_shot — full rules (same base), plus CATEGORY_CONTEXT and schemas are appended
_BASE_SYSTEM_PROMPT = """You are an expert Minecraft Bedrock Edition add-on developer.
You will be given a JSON input and a natural-language instruction.
Your job is to modify or create the JSON to fulfill the instruction.

CRITICAL RULES:
1. Return ONLY a single valid JSON object. No markdown, no explanation, no extra text.
2. Preserve all existing fields unless the instruction explicitly asks to change them.
3. Do NOT invent components that don't exist in Bedrock Edition.
4. Component dependencies: behavior.swell requires explode, tameable requires behavior.beg,
   shooter requires behavior.ranged_attack, rideable requires input_ground_controlled.
"""

# reasoning — appended AFTER the few_shot prompt (replaces the "JSON only" rule)
_REASONING_ADDENDUM = """

ADDITIONAL REASONING INSTRUCTIONS:
Before writing any JSON, you MUST think step-by-step inside <thinking> tags.
In your <thinking> block:
  a. Restate what the instruction is asking for.
  b. List every component you plan to add or modify.
  c. For EACH component, check its dependencies:
     - minecraft:behavior.melee_attack requires minecraft:attack AND minecraft:behavior.nearest_attackable_target
     - minecraft:behavior.swell requires minecraft:explode
     - minecraft:tameable requires minecraft:behavior.beg
     - minecraft:shooter requires minecraft:behavior.ranged_attack
     - minecraft:rideable requires minecraft:input_ground_controlled
     - minecraft:behavior.breed requires minecraft:breedable AND minecraft:behavior.tempt
  d. Verify you are NOT mixing entity/item/block components (e.g. no minecraft:health on items).
  e. Confirm all required fields have correct types (arrays, objects, integers, strings).
After </thinking>, output the final JSON inside a ```json code fence.
"""

# Category-specific context with structural examples
CATEGORY_CONTEXT = {
    "entity_logic_ai": """
CATEGORY: Entity Logic & AI (minecraft:entity)

STRUCTURE:
{
  "format_version": "1.21.0",
  "minecraft:entity": {
    "description": { "identifier": "namespace:mob_name", "is_spawnable": true, "is_summonable": true },
    "components": {
      "minecraft:health": { "value": 20, "max": 20 },
      "minecraft:movement": { "value": 0.3 },
      "minecraft:navigation.walk": {},
      "minecraft:movement.basic": {},
      "minecraft:attack": { "damage": 5 },
      "minecraft:behavior.melee_attack": { "priority": 3, "speed_multiplier": 1.0 },
      "minecraft:behavior.nearest_attackable_target": {
        "priority": 2,
        "entity_types": [
          { "filters": { "test": "is_family", "value": "player" }, "max_dist": 16 }
        ]
      }
    }
  }
}

KEY RULES:
- AI goals use "minecraft:behavior.*" components with a "priority" field (lower = higher priority).
- To make a mob attack, you need ALL THREE: minecraft:attack (damage), minecraft:behavior.melee_attack (AI goal), and minecraft:behavior.nearest_attackable_target (targeting).
- Targeting uses "entity_types" array with "filters" to select targets.
- For breeding: minecraft:breedable + minecraft:behavior.breed + minecraft:behavior.tempt.
- For defense: minecraft:behavior.defend_village_target + minecraft:behavior.hurt_by_target.
- For taming: minecraft:tameable (with tame_items array) + minecraft:behavior.beg.
- For ranged attacks: minecraft:shooter (with def string) + minecraft:behavior.ranged_attack.
- For explosions: minecraft:behavior.swell + minecraft:explode (with fuse_length and power).
- For riding: minecraft:rideable (with seat_count, family_types, seats) + minecraft:input_ground_controlled.
- minecraft:behavior.panic has "speed_multiplier" (float, e.g. 1.5 for 50% faster).
- minecraft:knockback_resistance has "value" (float 0.0-1.0).
- NEVER add item-only components (minecraft:damage, minecraft:durability, minecraft:shooter) to entities.

COMPONENT REFERENCE:
""" + json.dumps(_VANILLA_REF, indent=2) if _VANILLA_REF else "",

    "items_weaponry": """
CATEGORY: Items & Weaponry (minecraft:item)

STRUCTURE:
{
  "format_version": "1.21.0",
  "minecraft:item": {
    "description": { "identifier": "namespace:item_name", "category": "equipment" },
    "components": {
      "minecraft:damage": 10,
      "minecraft:durability": { "max_durability": 500 },
      "minecraft:hand_equipped": true
    }
  }
}

EXAMPLE — Sword with 12 damage:
{
  "format_version": "1.21.0",
  "minecraft:item": {
    "description": { "identifier": "custom:diamond_greatsword", "category": "equipment" },
    "components": {
      "minecraft:damage": 12,
      "minecraft:durability": { "max_durability": 500 },
      "minecraft:hand_equipped": true
    }
  }
}

EXAMPLE — Crossbow with shooter:
{
  "format_version": "1.21.0",
  "minecraft:item": {
    "description": { "identifier": "custom:crossbow", "category": "equipment" },
    "components": {
      "minecraft:shooter": {
        "ammunition": [ { "item": "minecraft:arrow", "use_offhand": true } ]
      },
      "minecraft:durability": { "max_durability": 300 }
    }
  }
}

EXAMPLE — Pickaxe with digger:
{
  "format_version": "1.21.0",
  "minecraft:item": {
    "description": { "identifier": "custom:fortune_pick", "category": "equipment" },
    "components": {
      "minecraft:digger": {
        "destroy_speeds": [ { "block": "minecraft:stone", "speed": 8 } ]
      },
      "minecraft:durability": { "max_durability": 1000 },
      "minecraft:hand_equipped": true
    }
  }
}

KEY RULES:
- Item components go inside minecraft:item > components.
- NEVER add entity components to items: NO minecraft:health, NO minecraft:behavior.*, NO minecraft:attack, NO minecraft:navigation.*, NO minecraft:entity_sensor.
- minecraft:damage is a simple integer (not an object).
- minecraft:durability is an object: { "max_durability": <int> }.
- minecraft:shooter.ammunition is an array of objects with "item" and "use_offhand".
- minecraft:digger.destroy_speeds is an array of { "block": "<id>", "speed": <number> }.
- minecraft:food is an object: { "nutrition": <int>, "saturation_modifier": <float> }.
- minecraft:armor is an object: { "protection": <int> }.
- minecraft:wearable is an object: { "slot": "slot.armor.chest" } (or .head, .legs, .feet, slot.weapon.offhand).
- minecraft:cooldown is an object: { "duration": <float seconds>, "category": "<string>" }.
- minecraft:repairable is an object: { "repair_items": [ { "items": ["minecraft:iron_ingot"] } ] }.
- minecraft:projectile is an object: { "minimum_critical_power": <float> }.
- minecraft:max_stack_size is a simple integer (e.g. 16, 64).
""",

    "blocks_furniture": """
CATEGORY: Blocks & Furniture (minecraft:block)

STRUCTURE:
{
  "format_version": "1.21.0",
  "minecraft:block": {
    "description": { "identifier": "namespace:block_name" },
    "components": {
      "minecraft:geometry": "geometry.custom_model",
      "minecraft:collision_box": { "origin": [-8, 0, -8], "size": [16, 16, 16] },
      "minecraft:selection_box": { "origin": [-8, 0, -8], "size": [16, 16, 16] }
    }
  }
}

EXAMPLE — Chair with custom geometry:
{
  "format_version": "1.21.0",
  "minecraft:block": {
    "description": { "identifier": "custom:wooden_chair" },
    "components": {
      "minecraft:geometry": "geometry.custom_chair",
      "minecraft:collision_box": { "origin": [-6, 0, -6], "size": [12, 8, 12] }
    }
  }
}

EXAMPLE — Glowing lamp:
{
  "format_version": "1.21.0",
  "minecraft:block": {
    "description": { "identifier": "custom:glowing_lamp" },
    "components": {
      "minecraft:light_emission": 15,
      "minecraft:geometry": "geometry.lamp",
      "minecraft:selection_box": { "origin": [-4, 0, -4], "size": [8, 10, 8] }
    }
  }
}

EXAMPLE — Transparent block with material instances:
{
  "format_version": "1.21.0",
  "minecraft:block": {
    "description": { "identifier": "custom:glass_table" },
    "components": {
      "minecraft:geometry": "geometry.glass_table",
      "minecraft:material_instances": {
        "*": { "render_method": "alpha_test", "texture": "glass_table" }
      },
      "minecraft:collision_box": { "origin": [-8, 12, -8], "size": [16, 4, 16] },
      "minecraft:selection_box": { "origin": [-8, 0, -8], "size": [16, 16, 16] }
    }
  }
}

KEY RULES:
- Block components go inside minecraft:block > components.
- Geometry references MUST start with "geometry." (e.g. "geometry.custom_chair").
- collision_box and selection_box use "origin" [x,y,z] and "size" [w,h,d]. Max size per axis is 16.
- minecraft:light_emission is an integer 0-15.
- For transparency, use minecraft:material_instances with "render_method": "alpha_test" or "blend".
- minecraft:destructible_by_mining is an object: { "seconds_to_destroy": <float> }.
- minecraft:destructible_by_explosion is an object: { "explosion_resistance": <float> }.
- minecraft:crafting_table is an object: { "crafting_tags": ["crafting_table"], "table_name": "<string>" }.
- For rotation, add traits to description: "traits": { "minecraft:placement_direction": { "enabled_states": ["minecraft:cardinal_direction"] } }.
- material_instances can have per-face keys: "*" (default), "up", "down", "north", "south", "east", "west".
- NEVER add entity components to blocks: NO minecraft:health, NO minecraft:behavior.*, NO minecraft:navigation.*.
""",

    "loot_recipes": """
CATEGORY: Loot Tables & Recipes

LOOT TABLE STRUCTURE:
{
  "format_version": "1.21.0",
  "pools": [
    {
      "rolls": 1,
      "entries": [
        { "type": "item", "name": "minecraft:diamond", "weight": 1 }
      ]
    }
  ]
}

EXAMPLE — Mob loot with rare drop:
{
  "format_version": "1.21.0",
  "pools": [
    {
      "rolls": { "min": 0, "max": 2 },
      "entries": [
        { "type": "item", "name": "minecraft:rotten_flesh", "weight": 1 }
      ]
    },
    {
      "rolls": 1,
      "conditions": [ { "condition": "random_chance", "chance": 0.10 } ],
      "entries": [
        { "type": "item", "name": "minecraft:iron_ingot", "weight": 1 }
      ]
    }
  ]
}

EXAMPLE — Loot with set_count function:
{
  "format_version": "1.21.0",
  "pools": [
    {
      "rolls": 1,
      "entries": [
        {
          "type": "item",
          "name": "minecraft:gold_ingot",
          "weight": 1,
          "functions": [ { "function": "set_count", "count": { "min": 2, "max": 4 } } ]
        }
      ]
    }
  ]
}

SHAPED RECIPE STRUCTURE:
{
  "format_version": "1.21.0",
  "minecraft:recipe_shaped": {
    "description": { "identifier": "namespace:recipe_name" },
    "pattern": [ "D", "D", "S" ],
    "key": {
      "D": { "item": "minecraft:diamond" },
      "S": { "item": "minecraft:stick" }
    },
    "result": { "item": "custom:item_name", "count": 1 }
  }
}

SHAPELESS RECIPE STRUCTURE:
{
  "format_version": "1.21.0",
  "minecraft:recipe_shapeless": {
    "description": { "identifier": "namespace:recipe_name" },
    "ingredients": [
      { "item": "minecraft:red_dye" },
      { "item": "minecraft:yellow_dye" }
    ],
    "result": { "item": "minecraft:orange_dye", "count": 2 }
  }
}

FURNACE RECIPE STRUCTURE:
{
  "format_version": "1.21.0",
  "minecraft:recipe_furnace": {
    "description": { "identifier": "namespace:recipe_name" },
    "input": "minecraft:raw_iron",
    "output": "minecraft:iron_ingot"
  }
}

KEY RULES:
- Every pool MUST have "rolls" (integer or {"min": N, "max": N}) and "entries" (array).
- Every entry MUST have "type" (usually "item") and "name".
- "conditions" is optional, placed at pool level. Valid: random_chance, killed_by_player, has_mark_variant.
- "functions" is optional, placed at entry level. Valid: set_count, set_damage, enchant_randomly, enchant_with_levels.
- For shaped recipes: "key" MUST be an Object (NOT an array). Keys are single characters matching the pattern.
- "pattern" is an array of strings representing the crafting grid rows (1-3 rows).
- For shapeless recipes: "ingredients" is an array of { "item": "<id>" } objects.
- For furnace recipes: "input" and "output" are simple item ID strings.
- "result" must have "item" key; "count" is optional (defaults to 1).
""",

    "scripting_components": """
CATEGORY: Scripting & Custom Components (manifest.json)

MANIFEST STRUCTURE:
{
  "format_version": 2,
  "header": {
    "name": "Pack Name",
    "description": "Pack description",
    "uuid": "<valid-uuid-v4>",
    "version": [1, 0, 0],
    "min_engine_version": [1, 21, 0]
  },
  "modules": [
    {
      "type": "script",
      "uuid": "<different-valid-uuid-v4>",
      "version": [1, 0, 0],
      "entry": "scripts/main.js"
    }
  ],
  "dependencies": [
    { "module_name": "@minecraft/server", "version": "1.12.0" }
  ]
}

EXAMPLE — Script pack with GameTest:
{
  "format_version": 2,
  "header": {
    "name": "GameTest Pack",
    "description": "Pack for game testing",
    "uuid": "d4e5f6a7-b8c9-4d0e-9f2a-3b4c5d6e7f8a",
    "version": [1, 0, 0],
    "min_engine_version": [1, 21, 0]
  },
  "modules": [
    {
      "type": "script",
      "uuid": "e5f6a7b8-c9d0-4e1f-8a3b-4c5d6e7f8a9b",
      "version": [1, 0, 0],
      "entry": "scripts/main.js"
    }
  ],
  "dependencies": [
    { "module_name": "@minecraft/server", "version": "1.12.0" },
    { "module_name": "@minecraft/server-gametest", "version": "1.0.0" }
  ]
}

EXAMPLE — Data module (no scripting):
{
  "format_version": 2,
  "header": { "name": "Data Pack", "description": "A basic data pack", "uuid": "<uuid-v4>", "version": [1, 0, 0], "min_engine_version": [1, 21, 0] },
  "modules": [ { "type": "data", "uuid": "<different-uuid-v4>", "version": [1, 0, 0] } ]
}

EXAMPLE — Resource pack:
{
  "format_version": 2,
  "header": { "name": "Texture Pack", "description": "Custom textures", "uuid": "<uuid-v4>", "version": [1, 0, 0], "min_engine_version": [1, 21, 0] },
  "modules": [ { "type": "resources", "uuid": "<different-uuid-v4>", "version": [1, 0, 0] } ]
}

EXAMPLE — World template:
{
  "format_version": 2,
  "header": { "name": "Adventure World", "description": "An adventure map", "uuid": "<uuid-v4>", "version": [1, 0, 0], "min_engine_version": [1, 21, 0], "lock_template_options": true },
  "modules": [ { "type": "world_template", "uuid": "<different-uuid-v4>", "version": [1, 0, 0] } ]
}

KEY RULES:
- format_version is the integer 2 (not a string).
- UUIDs MUST be valid v4 format: xxxxxxxx-xxxx-4xxx-[89ab]xxx-xxxxxxxxxxxx (lowercase hex).
- header.uuid and each module uuid MUST be different from each other.
- Module types: "script" (behavior pack scripts), "data" (behavior pack data), "resources" (resource pack), "world_template" (world template).
- Script modules MUST have "type": "script" and "entry": "scripts/<filename>.js".
- Data/resources/world_template modules do NOT need an "entry" field.
- version and min_engine_version are arrays of 3 integers: [major, minor, patch].
- dependencies use "module_name" (e.g. "@minecraft/server") and "version" (string).
- A manifest can have multiple modules (e.g. one "data" + one "script").
""",
}


def _build_system_prompt(category: str, strategy: str = "few_shot") -> str:
    """Build a system prompt whose richness depends on *strategy*.

    Strategies:
      - **zero_shot**  — Minimal rules only.  No examples, no schemas.
      - **few_shot**   — Full prompt with CATEGORY_CONTEXT examples + schemas.
      - **reasoning**  — Same as few_shot, plus a reasoning addendum that
                         instructs the model to think inside <thinking> tags.
    """
    if strategy == "zero_shot":
        return _ZERO_SHOT_SYSTEM_PROMPT

    # few_shot and reasoning both start from the full prompt
    prompt = _BASE_SYSTEM_PROMPT

    # Add category-specific context with structural examples
    cat_context = CATEGORY_CONTEXT.get(category, "")
    if cat_context:
        prompt += cat_context

    # Add schema reference for this category
    cat_schema = _CATEGORY_SCHEMAS.get(category)
    if cat_schema:
        schema_title = cat_schema.get("title", category)
        prompt += f"\n\n{schema_title} Schema:\n{json.dumps(cat_schema, indent=2)}"

    # Append reasoning instructions for the reasoning strategy
    if strategy == "reasoning":
        prompt += _REASONING_ADDENDUM

    return prompt


def _extract_json(text: str) -> dict:
    """Extract JSON from an LLM response that may contain free text, thinking
    blocks, and/or markdown fences.

    Extraction priority:
      1. Content inside a ```json ... ``` fenced code block.
      2. Content inside a bare ``` ... ``` fenced code block.
      3. First outer '{' to last outer '}' (greedy brace match).

    Before any extraction, <thinking>...</thinking> blocks are stripped so
    they cannot interfere with JSON parsing.
    """
    cleaned = text.strip()

    # --- Strip <thinking> blocks (may appear with CoT prompting) ---
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.DOTALL).strip()

    # --- Strategy 1: ```json ... ``` fence ---
    m = re.search(r"```json\s*(.*?)```", cleaned, re.DOTALL)
    if m:
        return json.loads(m.group(1).strip())

    # --- Strategy 2: bare ``` ... ``` fence ---
    m = re.search(r"```\s*(.*?)```", cleaned, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        if candidate.startswith("{"):
            return json.loads(candidate)

    # --- Strategy 3: greedy brace match (first '{' to last '}') ---
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first != -1 and last > first:
        return json.loads(cleaned[first:last + 1])

    # Last resort — try the whole string
    return json.loads(cleaned)


# Strict UUIDv4 regex: 8-4-4-4-12 hex with version nibble = 4, variant = [89ab]
_VALID_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

# Loose pattern: anything that *looks* like it was meant to be a UUID
# (e.g. "UUID_HERE", "123-abc", partial hex strings with dashes, placeholder text)
_LOOKS_LIKE_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|"
    r"uuid|placeholder",
    re.IGNORECASE,
)


def sanitize_json_uuids(data, *, _path: str = "$") -> None:
    """Recursively walk *data* (mutated in place) and replace invalid UUIDs.

    Detection rules:
      - Any key named ``uuid`` whose value is a string that does NOT match
        the strict UUIDv4 regex gets a fresh ``uuid.uuid4()``.
      - Any string value elsewhere that *looks* like a malformed UUID
        (matches the loose pattern but fails strict) is also replaced.

    A console warning is printed for every replacement so the caller knows
    the LLM produced a bad value.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            child_path = f"{_path}.{key}"
            if isinstance(value, str) and key.lower() == "uuid":
                if not _VALID_UUID4_RE.match(value.lower()):
                    new_uuid = str(_uuid_mod.uuid4())
                    print(f"  {YELLOW}[WARN] Replaced invalid UUID '{value}' "
                          f"with '{new_uuid}' at {child_path}{RESET}")
                    data[key] = new_uuid
            elif isinstance(value, str) and _LOOKS_LIKE_UUID_RE.search(value):
                if not _VALID_UUID4_RE.match(value.lower()):
                    new_uuid = str(_uuid_mod.uuid4())
                    print(f"  {YELLOW}[WARN] Replaced invalid UUID '{value}' "
                          f"with '{new_uuid}' at {child_path}{RESET}")
                    data[key] = new_uuid
            elif isinstance(value, (dict, list)):
                sanitize_json_uuids(value, _path=child_path)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            sanitize_json_uuids(item, _path=f"{_path}[{i}]")


def _build_user_message(test_case: dict) -> str:
    """Build the user message from a test case."""
    return (
        f"Current JSON:\n{json.dumps(test_case['input_spec'], indent=2)}\n\n"
        f"Instruction:\n{test_case['prompt']}"
    )


def _call_anthropic(test_case: dict, model: str, strategy: str = "few_shot") -> dict:
    """Call Anthropic Claude API."""
    if _anthropic_mod is None:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set.")
    system_prompt = _build_system_prompt(test_case.get("category", ""), strategy=strategy)
    client = _anthropic_mod.Anthropic(api_key=key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": _build_user_message(test_case)}],
    )
    return _extract_json(response.content[0].text)


def _call_openai(test_case: dict, model: str, strategy: str = "few_shot") -> dict:
    """Call OpenAI API with JSON mode."""
    if _OpenAI is None:
        raise RuntimeError("openai package not installed. Run: pip install openai")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY environment variable not set.")
    system_prompt = _build_system_prompt(test_case.get("category", ""), strategy=strategy)
    client = _OpenAI(api_key=key)
    # When reasoning strategy is used, disable json_object mode so the model
    # can emit free-text reasoning before the JSON block.
    kwargs: dict = {}
    if strategy != "reasoning":
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(
        model=model,
        **kwargs,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _build_user_message(test_case)},
        ],
    )
    return _extract_json(response.choices[0].message.content)


def _call_ollama(test_case: dict, model: str, strategy: str = "few_shot") -> dict:
    """Call a local Ollama instance via its REST API.

    Tries /api/chat first (Ollama >=0.1.14), falls back to /api/generate
    for older versions.
    """
    user_msg = _build_user_message(test_case)
    system_prompt = _build_system_prompt(test_case.get("category", ""), strategy=strategy)
    prompt_combined = f"{system_prompt}\n\n{user_msg}"

    # --- Try /api/chat first (newer Ollama) ---
    print(f"  {DIM}[ollama] requesting {model}...{RESET}", flush=True)
    chat_url = f"{OLLAMA_BASE_URL}/api/chat"
    chat_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
    }
    # Only force JSON format when NOT using reasoning (model needs free-text)
    if strategy != "reasoning":
        chat_payload["format"] = "json"
    try:
        resp = requests.post(chat_url, json=chat_payload, timeout=300)
        if resp.status_code != 404:
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            if not content:
                raise RuntimeError(
                    f"Ollama returned empty response for '{model}'. "
                    "The model may have hit a context-length limit or failed to generate."
                )
            return _extract_json(content)
    except requests.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. "
            "Is Ollama running? Start it with: ollama serve"
        )
    except requests.Timeout:
        raise RuntimeError(f"Ollama request timed out after 300s for model '{model}'.")
    except requests.HTTPError as exc:
        raise RuntimeError(f"Ollama HTTP error: {exc}")

    # --- Fallback to /api/generate (older Ollama) ---
    gen_url = f"{OLLAMA_BASE_URL}/api/generate"
    gen_payload = {
        "model": model,
        "prompt": prompt_combined,
        "stream": False,
    }
    if strategy != "reasoning":
        gen_payload["format"] = "json"
    try:
        resp = requests.post(gen_url, json=gen_payload, timeout=300)
        resp.raise_for_status()
    except requests.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. "
            "Is Ollama running? Start it with: ollama serve"
        )
    except requests.Timeout:
        raise RuntimeError(f"Ollama request timed out after 300s for model '{model}'.")
    except requests.HTTPError as exc:
        raise RuntimeError(f"Ollama HTTP error: {exc}")

    data = resp.json()
    content = data.get("response", "")
    if not content:
        raise RuntimeError(
            f"Ollama returned empty response. Is model '{model}' pulled? "
            f"Run: ollama pull {model}"
        )
    return _extract_json(content)


def query_llm(test_case: dict, provider: str, model: str | None = None,
              strategy: str = "few_shot") -> dict:
    """Route a test case to the appropriate LLM provider and return parsed JSON."""
    if provider == "mock":
        return mock_response(test_case)

    resolved_model = model or DEFAULT_MODELS.get(provider, "")
    if not resolved_model:
        raise RuntimeError(f"No default model for provider '{provider}'. Use --model.")

    if provider == "anthropic":
        return _call_anthropic(test_case, resolved_model, strategy=strategy)
    elif provider == "openai":
        return _call_openai(test_case, resolved_model, strategy=strategy)
    elif provider == "ollama":
        return _call_ollama(test_case, resolved_model, strategy=strategy)
    else:
        raise RuntimeError(f"Unknown provider '{provider}'.")




def mock_response(test_case: dict) -> dict:
    """Return a hardcoded mock LLM output based on category and test name.

    - entity_logic_ai: returns a *flawed* response (missing a required component)
      so the scorer can demonstrate failure detection.
    - items_weaponry / blocks_furniture / loot_recipes / scripting_components:
      return valid responses that should pass all checks.
    """
    name = test_case["name"]
    category = test_case["category"]
    output = copy.deepcopy(test_case["input_spec"])

    # ----- Entity Logic & AI ------------------------------------------------
    if category == "entity_logic_ai":
        comps = output.get("minecraft:entity", {}).get("components", {})
        if name == "wolf_hunts_creepers":
            # Flawed: missing minecraft:attack component to test failure detection
            comps.update({
                "minecraft:behavior.nearest_attackable_target": {
                    "priority": 2,
                    "entity_types": [
                        {"filters": {"test": "is_family", "value": "creeper"}, "max_dist": 16}
                    ]
                },
                "minecraft:behavior.melee_attack": {"priority": 3, "speed_multiplier": 1.2},
            })
        elif name == "breedable_farm_animal":
            comps.update({
                "minecraft:breedable": {"breed_items": ["minecraft:wheat"]},
                "minecraft:behavior.breed": {"priority": 3, "speed_multiplier": 1.0},
                "minecraft:behavior.tempt": {"priority": 4, "speed_multiplier": 1.0, "items": ["minecraft:wheat"]},
            })
        elif name == "guard_patrol_ai":
            comps.update({
                "minecraft:behavior.defend_village_target": {"priority": 1},
                "minecraft:behavior.hurt_by_target": {"priority": 2},
                "minecraft:behavior.melee_attack": {"priority": 3, "speed_multiplier": 1.0},
                "minecraft:attack": {"damage": 5},
            })
        elif name == "simple_passive_mob":
            comps.update({
                "minecraft:behavior.random_stroll": {"priority": 6, "speed_multiplier": 1.0},
                "minecraft:behavior.look_at_player": {"priority": 7, "look_distance": 8},
            })
        elif name == "panic_on_hurt":
            comps["minecraft:behavior.panic"] = {"priority": 1, "speed_multiplier": 1.5}
        elif name == "tameable_pet":
            comps.update({
                "minecraft:tameable": {"tame_items": ["minecraft:bone"]},
                "minecraft:behavior.beg": {"priority": 9, "items": ["minecraft:bone"]},
            })
        elif name == "skeleton_archer":
            comps["minecraft:shooter"] = {"def": "minecraft:arrow"}
            comps["minecraft:behavior.ranged_attack"] = {"priority": 3, "attack_interval_min": 1.0, "attack_interval_max": 3.0, "attack_radius": 15.0}
            comps["minecraft:behavior.nearest_attackable_target"] = {"priority": 2, "entity_types": [{"filters": {"test": "is_family", "value": "player"}, "max_dist": 16}]}
        elif name == "creeper_exploder":
            comps.update({
                "minecraft:behavior.swell": {"priority": 2, "start_distance": 2.5, "stop_distance": 6.0},
                "minecraft:explode": {"fuse_length": 1.5, "power": 3, "causes_fire": False},
                "minecraft:behavior.nearest_attackable_target": {"priority": 1, "entity_types": [{"filters": {"test": "is_family", "value": "player"}, "max_dist": 16}]},
            })
        elif name == "rideable_mount":
            comps.update({
                "minecraft:rideable": {"seat_count": 1, "family_types": ["player"], "seats": [{"position": [0, 1.5, 0]}]},
                "minecraft:input_ground_controlled": {},
            })
        elif name == "multi_behavior_boss":
            comps.update({
                "minecraft:health": {"value": 100, "max": 100},
                "minecraft:attack": {"damage": 8},
                "minecraft:behavior.melee_attack": {"priority": 3, "speed_multiplier": 1.0},
                "minecraft:behavior.nearest_attackable_target": {"priority": 2, "entity_types": [{"filters": {"test": "is_family", "value": "player"}, "max_dist": 32}]},
                "minecraft:knockback_resistance": {"value": 0.5},
            })

    # ----- Items & Weaponry (valid) -----------------------------------------
    elif category == "items_weaponry":
        comps = output.get("minecraft:item", {}).get("components", {})
        ITEM_MOCKS = {
            "diamond_greatsword": {"minecraft:damage": 12, "minecraft:durability": {"max_durability": 500}, "minecraft:hand_equipped": True},
            "explosive_crossbow": {"minecraft:shooter": {"ammunition": [{"item": "minecraft:arrow", "use_offhand": True}]}, "minecraft:durability": {"max_durability": 300}},
            "fortune_pickaxe": {"minecraft:digger": {"destroy_speeds": [{"block": "minecraft:stone", "speed": 8}]}, "minecraft:durability": {"max_durability": 1000}, "minecraft:hand_equipped": True},
            "simple_stick_weapon": {"minecraft:damage": 4, "minecraft:hand_equipped": True},
            "food_item": {"minecraft:food": {"nutrition": 8, "saturation_modifier": 0.8}},
            "throwable_item": {"minecraft:projectile": {"minimum_critical_power": 0.5}, "minecraft:max_stack_size": 16},
            "armor_chestplate": {"minecraft:armor": {"protection": 8}, "minecraft:durability": {"max_durability": 400}, "minecraft:wearable": {"slot": "slot.armor.chest"}},
            "cooldown_ability_item": {"minecraft:damage": 5, "minecraft:durability": {"max_durability": 200}, "minecraft:cooldown": {"duration": 3, "category": "magic_wand"}, "minecraft:hand_equipped": True},
            "multi_component_tool": {"minecraft:damage": 6, "minecraft:durability": {"max_durability": 800}, "minecraft:digger": {"destroy_speeds": [{"block": "minecraft:planks", "speed": 6}]}, "minecraft:repairable": {"repair_items": [{"items": ["minecraft:iron_ingot"]}]}, "minecraft:hand_equipped": True},
            "shield_item": {"minecraft:durability": {"max_durability": 250}, "minecraft:wearable": {"slot": "slot.weapon.offhand"}},
        }
        if name in ITEM_MOCKS:
            output["minecraft:item"]["components"] = ITEM_MOCKS[name]

    # ----- Blocks & Furniture (valid) ---------------------------------------
    elif category == "blocks_furniture":
        BLOCK_MOCKS = {
            "wooden_chair": {"minecraft:geometry": "geometry.custom_chair", "minecraft:collision_box": {"origin": [-6, 0, -6], "size": [12, 8, 12]}},
            "glowing_lamp": {"minecraft:light_emission": 15, "minecraft:geometry": "geometry.lamp", "minecraft:selection_box": {"origin": [-4, 0, -4], "size": [8, 10, 8]}},
            "glass_table": {"minecraft:geometry": "geometry.glass_table", "minecraft:material_instances": {"*": {"render_method": "alpha_test", "texture": "glass_table"}}, "minecraft:collision_box": {"origin": [-8, 12, -8], "size": [16, 4, 16]}, "minecraft:selection_box": {"origin": [-8, 0, -8], "size": [16, 16, 16]}},
            "simple_slab": {"minecraft:geometry": "geometry.slab", "minecraft:collision_box": {"origin": [-8, 0, -8], "size": [16, 8, 16]}},
            "basic_decorative_block": {"minecraft:geometry": "geometry.pillar"},
            "light_dimmer_block": {"minecraft:light_emission": 7, "minecraft:geometry": "geometry.torch"},
            "destructible_block": {"minecraft:geometry": "geometry.crate", "minecraft:destructible_by_mining": {"seconds_to_destroy": 5}, "minecraft:destructible_by_explosion": {"explosion_resistance": 10}},
            "rotatable_furniture": {"minecraft:geometry": "geometry.bookshelf", "minecraft:collision_box": {"origin": [-8, 0, -8], "size": [16, 16, 16]}},
            "crafting_station_block": {"minecraft:geometry": "geometry.crafting_station", "minecraft:material_instances": {"*": {"render_method": "opaque", "texture": "crafting_station"}}, "minecraft:collision_box": {"origin": [-8, 0, -8], "size": [16, 16, 16]}, "minecraft:selection_box": {"origin": [-8, 0, -8], "size": [16, 16, 16]}, "minecraft:crafting_table": {"crafting_tags": ["crafting_table"], "table_name": "Custom Crafting Station"}},
            "multi_face_textured_block": {"minecraft:geometry": "geometry.display_case", "minecraft:material_instances": {"*": {"render_method": "opaque", "texture": "wood"}, "up": {"render_method": "alpha_test", "texture": "glass"}}, "minecraft:collision_box": {"origin": [-8, 0, -8], "size": [16, 16, 16]}, "minecraft:selection_box": {"origin": [-8, 0, -8], "size": [16, 16, 16]}},
        }
        if name in BLOCK_MOCKS:
            output["minecraft:block"]["components"] = BLOCK_MOCKS[name]
        if name == "rotatable_furniture":
            output["minecraft:block"]["description"]["traits"] = {"minecraft:placement_direction": {"enabled_states": ["minecraft:cardinal_direction"]}}

    # ----- Loot Tables & Recipes (valid) ------------------------------------
    elif category == "loot_recipes":
        LOOT_MOCKS = {
            "shaped_sword_recipe": {"format_version": "1.21.0", "minecraft:recipe_shaped": {"description": {"identifier": "custom:diamond_sword_recipe"}, "pattern": ["D", "D", "S"], "key": {"D": {"item": "minecraft:diamond"}, "S": {"item": "minecraft:stick"}}, "result": {"item": "custom:diamond_greatsword", "count": 1}}},
            "zombie_loot_table": {"format_version": "1.21.0", "pools": [{"rolls": {"min": 0, "max": 2}, "entries": [{"type": "item", "name": "minecraft:rotten_flesh", "weight": 1}]}, {"rolls": 1, "conditions": [{"condition": "random_chance", "chance": 0.10}], "entries": [{"type": "item", "name": "minecraft:iron_ingot", "weight": 1}]}]},
            "nested_treasure_loot": {"format_version": "1.21.0", "pools": [{"rolls": 1, "entries": [{"type": "item", "name": "minecraft:gold_ingot", "weight": 1, "functions": [{"function": "set_count", "count": {"min": 2, "max": 4}}]}]}, {"rolls": 1, "conditions": [{"condition": "random_chance", "chance": 0.50}], "entries": [{"type": "item", "name": "minecraft:diamond", "weight": 1}, {"type": "item", "name": "minecraft:emerald", "weight": 2}]}]},
            "simple_single_drop": {"format_version": "1.21.0", "pools": [{"rolls": 1, "entries": [{"type": "item", "name": "minecraft:apple", "weight": 1}]}]},
            "simple_shapeless_recipe": {"format_version": "1.21.0", "minecraft:recipe_shapeless": {"description": {"identifier": "custom:orange_dye_recipe"}, "ingredients": [{"item": "minecraft:red_dye"}, {"item": "minecraft:yellow_dye"}], "result": {"item": "minecraft:orange_dye", "count": 2}}},
            "furnace_recipe": {"format_version": "1.21.0", "minecraft:recipe_furnace": {"description": {"identifier": "custom:smelt_silver"}, "input": "custom:raw_silver", "output": "custom:silver_ingot"}},
            "weighted_mob_loot": {"format_version": "1.21.0", "pools": [{"rolls": {"min": 1, "max": 3}, "entries": [{"type": "item", "name": "minecraft:bone", "weight": 3}, {"type": "item", "name": "minecraft:arrow", "weight": 2}]}]},
            "shaped_armor_recipe": {"format_version": "1.21.0", "minecraft:recipe_shaped": {"description": {"identifier": "custom:iron_chestplate_recipe"}, "pattern": ["I I", "III", "III"], "key": {"I": {"item": "minecraft:iron_ingot"}}, "result": {"item": "minecraft:iron_chestplate", "count": 1}}},
            "enchanted_loot_functions": {"format_version": "1.21.0", "pools": [{"rolls": {"min": 1, "max": 3}, "entries": [{"type": "item", "name": "minecraft:iron_sword", "weight": 1, "functions": [{"function": "enchant_randomly"}]}]}, {"rolls": 1, "entries": [{"type": "item", "name": "minecraft:arrow", "weight": 1, "functions": [{"function": "set_count", "count": {"min": 4, "max": 8}}]}]}, {"rolls": 1, "conditions": [{"condition": "random_chance", "chance": 0.25}], "entries": [{"type": "item", "name": "minecraft:diamond", "weight": 1}]}]},
            "conditional_player_kill_loot": {"format_version": "1.21.0", "pools": [{"rolls": {"min": 0, "max": 2}, "entries": [{"type": "item", "name": "minecraft:bone", "weight": 1}]}, {"rolls": 1, "conditions": [{"condition": "killed_by_player"}, {"condition": "random_chance", "chance": 0.025}], "entries": [{"type": "item", "name": "minecraft:skull", "weight": 1}]}]},
        }
        if name in LOOT_MOCKS:
            output = LOOT_MOCKS[name]

    # ----- Scripting & Custom Components (valid) ----------------------------
    elif category == "scripting_components":
        _uuid_h = "a1b2c3d4-e5f6-4a7b-9c0d-0e1f2a3b4c5d"
        _uuid_m = "f1e2d3c4-b5a6-4978-9a0b-0c1d2e3f4a5b"
        _uuid_m2 = "c3d4e5f6-a7b8-4c9d-8e1f-2a3b4c5d6e7f"
        header_name = test_case["input_spec"].get("header", {}).get("name", "Pack")
        header_desc = test_case["input_spec"].get("header", {}).get("description", "A pack")
        base = {"format_version": 2, "header": {"name": header_name, "description": header_desc, "uuid": _uuid_h, "version": [1, 0, 0], "min_engine_version": [1, 21, 0]}}

        if name == "simple_data_module":
            base["modules"] = [{"type": "data", "uuid": _uuid_m, "version": [1, 0, 0]}]
            output = base
        elif name == "resource_pack_manifest":
            base["modules"] = [{"type": "resources", "uuid": _uuid_m, "version": [1, 0, 0]}]
            output = base
        elif name == "versioned_manifest":
            base["header"]["version"] = [2, 1, 0]
            base["header"]["min_engine_version"] = [1, 21, 50]
            base["modules"] = [{"type": "data", "uuid": _uuid_m, "version": [2, 1, 0]}]
            output = base
        elif name == "script_manifest_basic":
            base["modules"] = [{"type": "script", "uuid": _uuid_m, "version": [1, 0, 0], "entry": "scripts/main.js"}]
            base["dependencies"] = [{"module_name": "@minecraft/server", "version": "1.12.0"}]
            output = base
        elif name == "custom_component_def":
            base["modules"] = [{"type": "script", "uuid": _uuid_m, "version": [1, 0, 0], "entry": "scripts/main.js"}]
            base["dependencies"] = [{"module_name": "@minecraft/server", "version": "1.12.0"}]
            output = base
        elif name == "script_with_ui":
            base["modules"] = [{"type": "script", "uuid": _uuid_m, "version": [1, 0, 0], "entry": "scripts/ui_handler.js"}]
            base["dependencies"] = [{"module_name": "@minecraft/server", "version": "1.12.0"}, {"module_name": "@minecraft/server-ui", "version": "1.2.0"}]
            output = base
        elif name == "world_template_manifest":
            base["header"]["lock_template_options"] = True
            base["modules"] = [{"type": "world_template", "uuid": _uuid_m, "version": [1, 0, 0]}]
            output = base
        elif name == "gametest_module":
            base["modules"] = [{"type": "script", "uuid": _uuid_m, "version": [1, 0, 0], "entry": "scripts/main.js"}]
            base["dependencies"] = [{"module_name": "@minecraft/server", "version": "1.12.0"}, {"module_name": "@minecraft/server-gametest", "version": "1.0.0"}]
            output = base
        elif name == "multi_module_manifest":
            base["modules"] = [{"type": "data", "uuid": _uuid_m, "version": [1, 0, 0]}, {"type": "script", "uuid": _uuid_m2, "version": [1, 0, 0], "entry": "scripts/main.js"}]
            base["dependencies"] = [{"module_name": "@minecraft/server", "version": "1.12.0"}]
            output = base
        elif name == "full_addon_manifest":
            base["modules"] = [{"type": "script", "uuid": _uuid_m, "version": [1, 0, 0], "entry": "scripts/addon.js"}]
            base["dependencies"] = [{"module_name": "@minecraft/server", "version": "1.12.0"}, {"module_name": "@minecraft/server-ui", "version": "1.2.0"}, {"module_name": "@minecraft/server-gametest", "version": "1.0.0"}]
            base["metadata"] = {"authors": ["TestAuthor"]}
            output = base

    return output


# =============================================================================
# STEP 3 — Strict requirement validation
# =============================================================================

def _get_nested_value(obj, path: str):
    """Resolve a dot-separated path against a nested dict/list structure.

    Supports:
      - simple dot paths:  "minecraft:entity.components.minecraft:attack.damage"
      - wildcard array:    "pools[*].entries[*].type"
      - indexed array:     "pools[0].rolls"
      - wildcard object:   "minecraft:block.components.minecraft:material_instances.*"
    """
    if not path:
        return obj

    # Split on '.' but keep bracket expressions attached to their key
    tokens = _tokenize_path(path)
    return _resolve_tokens(obj, tokens)


def _tokenize_path(path: str) -> list[str]:
    """Split a dotted path into tokens, preserving bracket notation.

    Handles Bedrock-style keys that contain dots, e.g.
    ``minecraft:behavior.panic`` or ``minecraft:navigation.walk``.
    Strategy: after splitting on '.', greedily re-join consecutive tokens
    when the combined key exists as a ``minecraft:`` namespaced component
    (i.e. the first part starts with ``minecraft:`` and the combined key
    is a known pattern like ``minecraft:behavior.X``).
    """
    raw = []
    current = ""
    for ch in path:
        if ch == ".":
            if current:
                raw.append(current)
                current = ""
        else:
            current += ch
    if current:
        raw.append(current)

    # Re-join tokens that form compound minecraft: keys.
    # e.g. ["minecraft:behavior", "panic", "speed_multiplier"]
    #   -> ["minecraft:behavior.panic", "speed_multiplier"]
    # A compound key is formed when a token starts with "minecraft:" and
    # the next token does NOT start with "minecraft:" and is NOT a bracket
    # accessor, wildcard, or known structural key.
    _STRUCTURAL = {"components", "description", "header", "modules",
                   "dependencies", "pools", "entries", "result", "key",
                   "pattern", "metadata", "traits", "format_version"}
    tokens: list[str] = []
    i = 0
    while i < len(raw):
        t = raw[i]
        # If this token starts with "minecraft:" and the next token looks
        # like a sub-key of a compound component name (not structural,
        # not a bracket, not another minecraft: prefix, not "*")
        if (t.startswith("minecraft:") and i + 1 < len(raw)
                and not raw[i + 1].startswith("minecraft:")
                and not raw[i + 1].startswith("[")
                and raw[i + 1] != "*"
                and raw[i + 1] not in _STRUCTURAL
                and "[" not in raw[i + 1]):
            # Peek ahead: try compound key, but only if the next-next
            # token exists (meaning there's still a field after the key)
            # OR if this is the last segment (the key itself is the leaf).
            if i + 2 < len(raw):
                tokens.append(f"{t}.{raw[i + 1]}")
                i += 2
            else:
                # Last two tokens — don't merge, the second is the leaf field
                tokens.append(t)
                i += 1
        else:
            tokens.append(t)
            i += 1
    return tokens


def _resolve_tokens(obj, tokens: list[str]):
    """Recursively resolve a list of path tokens against obj."""
    if not tokens:
        return obj
    if obj is None:
        return None

    token = tokens[0]
    rest = tokens[1:]

    # Wildcard array: "pools[*]"
    m = re.match(r"^(.+)\[\*\]$", token)
    if m:
        key = m.group(1)
        arr = obj.get(key) if isinstance(obj, dict) else None
        if not isinstance(arr, list):
            return None
        results = []
        for item in arr:
            r = _resolve_tokens(item, rest)
            if r is None:
                continue
            # Flatten nested lists from chained wildcards so that
            # pools[*].entries[*].type yields ["item","item"] not [["item"],["item"]]
            if isinstance(r, list) and rest and any(
                re.match(r"^.+\[\*\]$", t) or t == "*" for t in rest
            ):
                results.extend(r)
            else:
                results.append(r)
        return results if results else None

    # Indexed array: "pools[0]"
    m = re.match(r"^(.+)\[(\d+)\]$", token)
    if m:
        key = m.group(1)
        idx = int(m.group(2))
        arr = obj.get(key) if isinstance(obj, dict) else None
        if not isinstance(arr, list) or idx >= len(arr):
            return None
        return _resolve_tokens(arr[idx], rest)

    # Wildcard object key: "*"
    if token == "*":
        if not isinstance(obj, dict):
            return None
        results = [_resolve_tokens(v, rest) for v in obj.values()]
        results = [r for r in results if r is not None]
        return results if results else None

    # Regular key
    if isinstance(obj, dict):
        return _resolve_tokens(obj.get(token), rest)

    # If obj is a list (from a previous wildcard), resolve each element
    if isinstance(obj, list):
        results = [_resolve_tokens(item, [token] + rest) for item in obj]
        results = [r for r in results if r is not None]
        return results if results else None

    return None


def _find_components(output: dict) -> dict:
    """Extract the components dict from any top-level wrapper."""
    for key in ("minecraft:entity", "minecraft:item", "minecraft:block"):
        if key in output:
            return output[key].get("components", {}) or {}
    return output.get("components", {}) or {}


def check_strict_requirements(test_case: dict, output: dict) -> list[dict]:
    """Validate required_components, forbidden_components, required_fields, should_not_change."""
    checks: list[dict] = []
    components = _find_components(output)

    # ---- required_components ------------------------------------------------
    for comp in test_case.get("required_components", []):
        present = comp in components and components[comp] is not None
        checks.append({
            "type": "required_component",
            "target": comp,
            "passed": present,
            "message": f"Required component '{comp}'" + (" present" if present else " MISSING"),
        })

    # ---- forbidden_components -----------------------------------------------
    for comp in test_case.get("forbidden_components", []):
        absent = comp not in components or components[comp] is None
        checks.append({
            "type": "forbidden_component",
            "target": comp,
            "passed": absent,
            "message": f"Forbidden component '{comp}'" + (" absent" if absent else " PRESENT"),
        })

    # ---- required_fields ----------------------------------------------------
    for field_path, constraints in test_case.get("required_fields", {}).items():
        value = _get_nested_value(output, field_path)
        passed = True
        messages: list[str] = []

        if value is None:
            passed = False
            messages.append(f"Field '{field_path}' is missing")
        else:
            # Detect if this value came from a wildcard expansion.
            # Wildcard paths (e.g. modules[*].type) resolve to a list of
            # per-element values.  For scalar constraints (equals, type=string,
            # pattern, min, max) we validate *each* element individually.
            is_wildcard = "[*]" in field_path or field_path.endswith(".*")
            scalars = value if (is_wildcard and isinstance(value, list)) else [value]

            # equals
            if "equals" in constraints:
                for sv in scalars:
                    if sv != constraints["equals"]:
                        passed = False
                        messages.append(f"Expected {constraints['equals']}, got {sv}")
                        break
            # min / max (scalar)
            if "min" in constraints:
                for sv in scalars:
                    if isinstance(sv, (list, dict)):
                        continue
                    try:
                        if float(sv) < float(constraints["min"]):
                            passed = False
                            messages.append(f"Expected >= {constraints['min']}, got {sv}")
                            break
                    except (TypeError, ValueError):
                        passed = False
                        messages.append(f"Cannot compare '{sv}' to min {constraints['min']}")
                        break
            if "max" in constraints:
                for sv in scalars:
                    if isinstance(sv, (list, dict)):
                        continue
                    try:
                        if float(sv) > float(constraints["max"]):
                            passed = False
                            messages.append(f"Expected <= {constraints['max']}, got {sv}")
                            break
                    except (TypeError, ValueError):
                        passed = False
                        messages.append(f"Cannot compare '{sv}' to max {constraints['max']}")
                        break
            # contains (substring)
            if "contains" in constraints:
                if constraints["contains"] not in str(value):
                    passed = False
                    messages.append(f"Expected to contain '{constraints['contains']}', got '{value}'")
            # type — for wildcard scalars check each element
            if "type" in constraints:
                expected_type = constraints["type"]
                for sv in scalars:
                    if expected_type == "array" and not isinstance(sv, list):
                        passed = False
                        messages.append(f"Expected array, got {type(sv).__name__}")
                        break
                    elif expected_type == "object" and not isinstance(sv, dict):
                        passed = False
                        messages.append(f"Expected object, got {type(sv).__name__}")
                        break
                    elif expected_type == "string" and not isinstance(sv, str):
                        passed = False
                        messages.append(f"Expected string, got {type(sv).__name__}")
                        break
                    elif expected_type == "integer" and not isinstance(sv, int):
                        passed = False
                        messages.append(f"Expected integer, got {type(sv).__name__}")
                        break
            # type_any — value can be any of the listed types
            if "type_any" in constraints:
                allowed = constraints["type_any"]
                type_map = {"integer": int, "object": dict, "string": str, "array": list}
                for sv in scalars:
                    ok = any(isinstance(sv, type_map[t]) for t in allowed if t in type_map)
                    if not ok:
                        passed = False
                        messages.append(f"Expected one of {allowed}, got {type(sv).__name__}")
                        break
            # min_length / max_length (for arrays)
            if "min_length" in constraints:
                target = value if not is_wildcard else value
                if isinstance(target, list) and not is_wildcard:
                    if len(target) < constraints["min_length"]:
                        passed = False
                        messages.append(f"Expected min length {constraints['min_length']}, got {len(target)}")
                elif is_wildcard:
                    for sv in scalars:
                        if isinstance(sv, list) and len(sv) < constraints["min_length"]:
                            passed = False
                            messages.append(f"Expected min length {constraints['min_length']}, got {len(sv)}")
                            break
            if "max_length" in constraints and isinstance(value, list) and not is_wildcard:
                if len(value) > constraints["max_length"]:
                    passed = False
                    messages.append(f"Expected max length {constraints['max_length']}, got {len(value)}")
            # exact_length
            if "exact_length" in constraints:
                for sv in scalars:
                    if isinstance(sv, list) and len(sv) != constraints["exact_length"]:
                        passed = False
                        messages.append(f"Expected length {constraints['exact_length']}, got {len(sv)}")
                        break
            # items_type (check all items in array)
            if "items_type" in constraints:
                arrs = scalars if is_wildcard else [value]
                type_map = {"number": (int, float), "string": str, "integer": int}
                expected_py = type_map.get(constraints["items_type"])
                if expected_py:
                    for arr in arrs:
                        if isinstance(arr, list):
                            for i, item in enumerate(arr):
                                if not isinstance(item, expected_py):
                                    passed = False
                                    messages.append(f"Item [{i}] expected {constraints['items_type']}, got {type(item).__name__}")
                                    break
            # items_max (all items <= value)
            if "items_max" in constraints:
                arrs = scalars if is_wildcard else [value]
                for arr in arrs:
                    if isinstance(arr, list):
                        for i, item in enumerate(arr):
                            try:
                                if float(item) > float(constraints["items_max"]):
                                    passed = False
                                    messages.append(f"Item [{i}] = {item} exceeds max {constraints['items_max']}")
                                    break
                            except (TypeError, ValueError):
                                pass
            # pattern (regex match for strings)
            if "pattern" in constraints:
                for sv in scalars:
                    if isinstance(sv, str) and not re.search(constraints["pattern"], sv):
                        label = constraints.get("pattern_name", constraints["pattern"])
                        passed = False
                        messages.append(f"Value '{sv}' does not match pattern {label}")
                        break
            # has_key (check dict has a key)
            if "has_key" in constraints:
                targets = scalars
                for t in targets:
                    if isinstance(t, dict) and constraints["has_key"] not in t:
                        passed = False
                        messages.append(f"Object missing key '{constraints['has_key']}'")
                        break
            # contains_any (list of values, at least one must appear)
            if "contains_any" in constraints:
                flat = json.dumps(value)
                found = any(v in flat for v in constraints["contains_any"])
                if not found:
                    passed = False
                    messages.append(f"None of {constraints['contains_any']} found")

        checks.append({
            "type": "required_field",
            "target": field_path,
            "passed": passed,
            "message": "; ".join(messages) if messages else "OK",
        })

    # ---- should_not_change --------------------------------------------------
    for field_path in test_case.get("should_not_change", []):
        original = _get_nested_value(test_case["input_spec"], field_path)
        current = _get_nested_value(output, field_path)
        passed = original == current
        checks.append({
            "type": "unchanged_field",
            "target": field_path,
            "passed": passed,
            "message": f"'{field_path}' unchanged" if passed else f"'{field_path}' changed: {original} → {current}",
        })

    return checks


# =============================================================================
# STEP 4 — Semantic consistency (ported from backend/llm_scoring.py)
# =============================================================================

COMPONENT_DEPENDENCIES = {
    "minecraft:behavior.swell": ["minecraft:explode"],
    "minecraft:behavior.tempt": ["minecraft:navigation.walk"],
    "minecraft:shooter": ["minecraft:behavior.ranged_attack"],
    "minecraft:rideable": ["minecraft:input_ground_controlled"],
    "minecraft:tameable": ["minecraft:behavior.beg"],
    "minecraft:healable": ["minecraft:tameable"],
}

COMPONENT_FIELD_IMPLICATIONS = {
    "minecraft:is_baby": {"scale": {"max": 0.9}},
    "minecraft:can_fly": {"speed": {"min": 0.1}},
}

# Cross-domain rule: entity-only components that must never appear in items/blocks
ENTITY_ONLY_COMPONENTS = {
    "minecraft:health", "minecraft:behavior.melee_attack",
    "minecraft:behavior.ranged_attack", "minecraft:behavior.nearest_attackable_target",
    "minecraft:behavior.random_stroll", "minecraft:behavior.sit",
    "minecraft:navigation.walk", "minecraft:navigation.fly",
    "minecraft:entity_sensor", "minecraft:movement.basic",
}


def check_semantic_consistency(test_case: dict, output: dict) -> list[dict]:
    """Run semantic consistency checks on the LLM output.

    Returns a list of check dicts with type/passed/message.
    """
    checks: list[dict] = []
    category = test_case.get("category", "")
    components = _find_components(output)

    # --- Component dependency rules (entity category only) ---
    if category == "entity_logic_ai":
        for trigger, required_list in COMPONENT_DEPENDENCIES.items():
            if trigger in components:
                for req in required_list:
                    passed = req in components
                    checks.append({
                        "type": "semantic_dependency",
                        "target": f"{trigger} → {req}",
                        "passed": passed,
                        "message": f"'{trigger}' requires '{req}'" if not passed else "OK",
                    })

    # --- Cross-domain: items/blocks must NOT have entity-only components ---
    if category in ("items_weaponry", "blocks_furniture"):
        for comp in components:
            if comp in ENTITY_ONLY_COMPONENTS:
                checks.append({
                    "type": "semantic_cross_domain",
                    "target": comp,
                    "passed": False,
                    "message": f"Entity-only component '{comp}' found in {category} output",
                })

    # --- Loot table structure checks ---
    if category == "loot_recipes":
        pools = output.get("pools")
        if isinstance(pools, list):
            for i, pool in enumerate(pools):
                if "rolls" not in pool:
                    checks.append({
                        "type": "semantic_loot_structure",
                        "target": f"pools[{i}].rolls",
                        "passed": False,
                        "message": f"Pool {i} missing 'rolls' field",
                    })
                entries = pool.get("entries", [])
                for j, entry in enumerate(entries):
                    if "type" not in entry:
                        checks.append({
                            "type": "semantic_loot_structure",
                            "target": f"pools[{i}].entries[{j}].type",
                            "passed": False,
                            "message": f"Entry {j} in pool {i} missing 'type'",
                        })
        # Recipe key-not-array check
        recipe = output.get("minecraft:recipe_shaped", {})
        key_obj = recipe.get("key")
        if key_obj is not None and isinstance(key_obj, list):
            checks.append({
                "type": "semantic_recipe_structure",
                "target": "minecraft:recipe_shaped.key",
                "passed": False,
                "message": "'key' must be an Object, NOT an array",
            })

    # --- Scripting: UUID v4 format ---
    if category == "scripting_components":
        uuid_re = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        )
        header_uuid = output.get("header", {}).get("uuid", "")
        if header_uuid and not uuid_re.match(header_uuid):
            checks.append({
                "type": "semantic_uuid",
                "target": "header.uuid",
                "passed": False,
                "message": f"Invalid UUID v4: '{header_uuid}'",
            })
        for i, mod in enumerate(output.get("modules", [])):
            mod_uuid = mod.get("uuid", "")
            if mod_uuid and not uuid_re.match(mod_uuid):
                checks.append({
                    "type": "semantic_uuid",
                    "target": f"modules[{i}].uuid",
                    "passed": False,
                    "message": f"Invalid UUID v4: '{mod_uuid}'",
                })

    return checks


# =============================================================================
# STEP 5 — Runner & output
# =============================================================================

def run_test(test_case: dict, provider: str = "mock", model: str | None = None,
             verbose: bool = False, strategy: str = "few_shot") -> dict:
    """Run a single test case through LLM + validation. Returns result dict."""
    name = test_case["name"]
    category = test_case["category"]

    try:
        output = query_llm(test_case, provider, model, strategy=strategy)
    except Exception as e:
        return {"name": name, "category": category, "passed": False,
                "score": 0.0, "error": str(e), "checks": []}

    # Post-process: fix invalid UUIDs before validation
    sanitize_json_uuids(output)

    strict_checks = check_strict_requirements(test_case, output)
    semantic_checks = check_semantic_consistency(test_case, output)
    all_checks = strict_checks + semantic_checks

    passed_count = sum(1 for c in all_checks if c["passed"])
    total_count = len(all_checks)
    score = passed_count / total_count if total_count > 0 else 1.0
    all_passed = all(c["passed"] for c in all_checks)

    return {
        "name": name,
        "category": category,
        "passed": all_passed,
        "score": score,
        "checks_passed": passed_count,
        "checks_total": total_count,
        "checks": all_checks,
        "error": None,
        "output": output,
    }


def print_result(result: dict, verbose: bool = False) -> None:
    """Print a single test result with color."""
    status = f"{GREEN}PASS{RESET}" if result["passed"] else f"{RED}FAIL{RESET}"
    score_str = f"{result['score']:.0%}"
    cat = f"{DIM}[{result['category']}]{RESET}"
    print(f"  {status}  {score_str:>5}  {result['name']:<30} {cat}")

    if result.get("error"):
        print(f"         {RED}Error: {result['error']}{RESET}")

    if verbose:
        for c in result["checks"]:
            icon = f"{GREEN}[OK]{RESET}" if c["passed"] else f"{RED}[X]{RESET}"
            print(f"         {icon} [{c['type']}] {c['message']}")


def main():
    parser = argparse.ArgumentParser(description="LLM Evaluation Framework")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show individual check details")
    parser.add_argument("-c", "--category", type=str, default=None,
                        help="Filter by category (e.g. entity_logic_ai, items_weaponry)")
    parser.add_argument("-a", "--all", action="store_true", dest="run_all",
                        help="Run ALL categories and show grand summary")
    parser.add_argument("-p", "--provider", type=str, default="mock",
                        choices=["mock", "anthropic", "openai", "ollama"],
                        help="LLM provider: mock, anthropic, openai, ollama (default: mock)")
    parser.add_argument("-m", "--model", type=str, default=None,
                        help="Model name override (default: provider-specific)")
    parser.add_argument("-s", "--strategy", type=str, default="few_shot",
                        choices=["zero_shot", "few_shot", "reasoning"],
                        help="Prompting strategy: zero_shot, few_shot (default), reasoning")
    parser.add_argument("--ollama-url", type=str, default=None,
                        help="Override Ollama base URL (e.g. http://localhost:11435 for SSH tunnel)")
    parser.add_argument("--launch", action="store_true",
                        help="Launch the first passing result in Minecraft via template.mcworld injection")
    args = parser.parse_args()

    # Allow CLI to override the Ollama endpoint (e.g. SSH tunnel to HPC cluster)
    global OLLAMA_BASE_URL
    if args.ollama_url:
        OLLAMA_BASE_URL = args.ollama_url.rstrip("/")

    # --all overrides --category
    if args.run_all:
        args.category = None

    # Pre-flight check for real providers
    provider = args.provider
    if provider != "mock":
        if provider == "anthropic" and _anthropic_mod is None:
            print(f"{RED}Error: 'anthropic' package not installed. Run: pip install anthropic{RESET}")
            print(f"{YELLOW}Falling back to mock provider.{RESET}")
            provider = "mock"
        elif provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
            print(f"{RED}Error: ANTHROPIC_API_KEY not set.{RESET}")
            print(f"{YELLOW}Falling back to mock provider.{RESET}")
            provider = "mock"
        elif provider == "openai" and _OpenAI is None:
            print(f"{RED}Error: 'openai' package not installed. Run: pip install openai{RESET}")
            print(f"{YELLOW}Falling back to mock provider.{RESET}")
            provider = "mock"
        elif provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
            print(f"{RED}Error: OPENAI_API_KEY not set.{RESET}")
            print(f"{YELLOW}Falling back to mock provider.{RESET}")
            provider = "mock"
        elif provider == "ollama":
            try:
                r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
                r.raise_for_status()
            except Exception:
                print(f"{RED}Error: Cannot reach Ollama at {OLLAMA_BASE_URL}. Is it running?{RESET}")
                print(f"{YELLOW}Falling back to mock provider.{RESET}")
                provider = "mock"

    resolved_model = args.model or DEFAULT_MODELS.get(provider, "mock")

    # Load
    if not TEST_CASES_PATH.exists():
        print(f"{RED}Error: {TEST_CASES_PATH} not found{RESET}")
        sys.exit(1)

    tests = load_test_cases()
    if args.category:
        tests = [t for t in tests if t.get("category") == args.category]

    if not tests:
        print(f"{YELLOW}No test cases found.{RESET}")
        sys.exit(0)

    print(f"\n{BOLD}=== LLM Evaluation Framework ==={RESET}")
    print(f"{DIM}Source:   {TEST_CASES_PATH.relative_to(PROJECT_ROOT)}{RESET}")
    print(f"{DIM}Provider: {provider} ({resolved_model}){RESET}")
    print(f"{DIM}Strategy: {args.strategy}{RESET}")
    print(f"{DIM}Tests:    {len(tests)}{RESET}\n")

    # Run
    results: list[dict] = []
    current_category = None
    for test in tests:
        cat = test.get("category", "unknown")
        if cat != current_category:
            current_category = cat
            print(f"{CYAN}{BOLD}  -- {cat} --{RESET}")
        result = run_test(test, provider=provider, model=args.model, verbose=args.verbose, strategy=args.strategy)
        results.append(result)
        print_result(result, verbose=args.verbose)

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    avg_score = sum(r["score"] for r in results) / total if total > 0 else 0

    print(f"\n{BOLD}=== Summary ==={RESET}")
    print(f"  Total:   {total}")
    print(f"  Passed:  {GREEN}{passed}{RESET}")
    print(f"  Failed:  {RED}{failed}{RESET}" if failed else f"  Failed:  {GREEN}0{RESET}")
    print(f"  Score:   {avg_score:.0%}")

    # Per-category breakdown
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"passed": 0, "total": 0}
        categories[cat]["total"] += 1
        if r["passed"]:
            categories[cat]["passed"] += 1

    print(f"\n{BOLD}  Per-Category:{RESET}")
    for cat, stats in categories.items():
        p, t = stats["passed"], stats["total"]
        color = GREEN if p == t else (YELLOW if p > 0 else RED)
        print(f"    {color}{p}/{t}{RESET}  {cat}")

    # ── Launch preview if requested ──────────────────────────────────────
    if args.launch:
        # Find the first passing result that has output
        launch_candidate = None
        for r in results:
            if r["passed"] and r.get("output"):
                launch_candidate = r
                break

        if launch_candidate is None:
            print(f"\n{YELLOW}--launch: No passing test to launch.{RESET}")
        else:
            # Write the output JSON to a temp pack folder
            pack_name = launch_candidate["name"]
            pack_dir = PROJECT_ROOT / "temp" / f"{pack_name}_pack"
            pack_dir.mkdir(parents=True, exist_ok=True)

            output_data = launch_candidate["output"]
            category = launch_candidate["category"]

            # If the output IS a manifest (scripting_components), write it directly
            if "header" in output_data and "modules" in output_data:
                (pack_dir / "manifest.json").write_text(
                    json.dumps(output_data, indent=2), encoding="utf-8"
                )
            else:
                # For entities/items/blocks/loot, wrap in a minimal manifest
                # and write the spec as the main content file
                _write_pack_with_manifest(pack_dir, pack_name, output_data,
                                         category)

            print(f"\n{BOLD}=== Launching Server Session ==={RESET}")
            try:
                from launch_server_session import launch_server_session
                launch_server_session(str(pack_dir), category=category)
            except FileNotFoundError as exc:
                print(f"{RED}{exc}{RESET}")
                # Fallback to mcworld injection if BDS not available
                print(f"{YELLOW}Falling back to .mcworld injection...{RESET}")
                try:
                    from launch_preview import launch_preview
                    launch_preview(str(pack_dir), pack_name)
                except FileNotFoundError as exc2:
                    print(f"{RED}{exc2}{RESET}")

    print()
    sys.exit(0 if failed == 0 else 1)


def _write_pack_with_manifest(pack_dir: Path, pack_name: str,
                              spec_data: dict, category: str) -> None:
    """Write a minimal Behavior Pack folder with manifest + content file."""
    import uuid as _uuid

    # Create manifest.json
    manifest = {
        "format_version": 2,
        "header": {
            "name": pack_name,
            "description": f"Auto-generated preview pack for {pack_name}",
            "uuid": str(_uuid.uuid4()),
            "version": [1, 0, 0],
            "min_engine_version": [1, 21, 0],
        },
        "modules": [
            {
                "type": "data",
                "uuid": str(_uuid.uuid4()),
                "version": [1, 0, 0],
            }
        ],
    }
    (pack_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # Write the spec into the appropriate subfolder
    _CATEGORY_SUBFOLDERS = {
        "entity_logic_ai": "entities",
        "items_weaponry": "items",
        "blocks_furniture": "blocks",
        "loot_recipes": "loot_tables" if "pools" in spec_data else "recipes",
        "scripting_components": ".",
    }
    subfolder = _CATEGORY_SUBFOLDERS.get(category, "data")
    content_dir = pack_dir / subfolder
    content_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{pack_name}.json"
    (content_dir / filename).write_text(
        json.dumps(spec_data, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
