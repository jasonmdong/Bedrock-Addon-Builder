"""Category-specific context for LLM prompts.

Shared between the production LLM pipeline (backend/llm/llm.py) and
the evaluation framework (scripts/evaluate_llm.py).
"""
import json
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Valid categories
# ---------------------------------------------------------------------------

CATEGORIES = [
    "entity_logic_ai",
    "items_weaponry",
    "blocks_furniture",
    "loot_recipes",
    "scripting_components",
]

CATEGORY_LABELS = {
    "entity_logic_ai": "Entity / Mob",
    "items_weaponry": "Items & Weaponry",
    "blocks_furniture": "Blocks & Furniture",
    "loot_recipes": "Loot Tables & Recipes",
    "scripting_components": "Scripting & Manifests",
}

# ---------------------------------------------------------------------------
# Per-category JSON schemas (loaded from disk if they exist)
# ---------------------------------------------------------------------------

_CATEGORY_SCHEMA_FILES = {
    "entity_logic_ai": "mob_spec.schema.json",
    "items_weaponry": "item_spec.schema.json",
    "blocks_furniture": "block_spec.schema.json",
    "loot_recipes": "loot_spec.schema.json",
    "scripting_components": "manifest_spec.schema.json",
}

SCHEMAS_DIR = BACKEND_DIR / "schemas"

CATEGORY_SCHEMAS: dict[str, dict] = {}
for _cat, _fname in _CATEGORY_SCHEMA_FILES.items():
    _spath = SCHEMAS_DIR / _fname
    if _spath.exists():
        try:
            CATEGORY_SCHEMAS[_cat] = json.loads(_spath.read_text(encoding="utf-8"))
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Vanilla reference (entity components)
# ---------------------------------------------------------------------------

VANILLA_REF: dict = {}
_ref_path = BACKEND_DIR / "data" / "vanilla_reference.json"
if _ref_path.exists():
    try:
        VANILLA_REF = json.loads(_ref_path.read_text(encoding="utf-8"))
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Category-specific context blocks (examples, rules, structure)
# ---------------------------------------------------------------------------

_vanilla_ref_json = json.dumps(VANILLA_REF, indent=2) if VANILLA_REF else ""

# The vanilla reference can be extremely large. Keep it as a separate block so
# the prompt builder can include it only when needed.
ENTITY_COMPONENT_REFERENCE_TEXT = (
    f"\nCOMPONENT REFERENCE:\n{_vanilla_ref_json}" if _vanilla_ref_json else ""
)

CATEGORY_CONTEXT: dict[str, str] = {
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
""",

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


def detect_category(spec: dict) -> str:
    """Auto-detect the category from a spec's structure.

    Checks for distinctive top-level keys that identify each Bedrock content type.
    Falls back to entity_logic_ai for the app's simplified mob spec format.
    """
    if "minecraft:item" in spec:
        return "items_weaponry"
    if "minecraft:block" in spec:
        return "blocks_furniture"
    if "pools" in spec or any(k.startswith("minecraft:recipe") for k in spec):
        return "loot_recipes"
    if "header" in spec and "modules" in spec:
        return "scripting_components"
    if "minecraft:entity" in spec:
        return "entity_logic_ai"
    # Simplified mob spec (hp, damage, components, etc.)
    return "entity_logic_ai"
