"""
Tool 1: generate_mob — Takes a natural language description and generates
a complete, valid Minecraft Bedrock entity behavior JSON spec.
Uses GitHub Models (GPT-4o) with rich Bedrock context in the system prompt.
"""

import json
import os
import re
from openai import OpenAI

from .bedrock_reference import (
    GENERATE_MOB_SYSTEM_PROMPT,
    VALID_COMPONENTS,
    STYLE_GEOMETRY_MAP,
    STYLE_COLLISION_BOX,
)


MODEL_NAME = os.environ.get("MOB_FORGE_MOB_MODEL") or os.environ.get("MOB_FORGE_MODEL") or "gpt-4o-mini"


def get_client() -> OpenAI:
    """Create OpenAI client configured for GitHub Models."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError(
            "GITHUB_TOKEN environment variable is required. "
            "Create a GitHub PAT with models:read permission."
        )
    return OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
    )


def validate_mob_json(mob_data: dict) -> dict:
    """Validate and fix mob JSON to ensure Bedrock compatibility."""
    errors = []

    # Check top-level structure
    if "format_version" not in mob_data:
        mob_data["format_version"] = "1.16.0"
        errors.append("Added missing format_version")

    entity = mob_data.get("minecraft:entity", {})
    if not entity:
        raise ValueError("Missing minecraft:entity root object")

    # Check description
    desc = entity.get("description", {})
    if "identifier" not in desc:
        raise ValueError("Missing entity identifier")
    if not desc["identifier"].startswith("custom:"):
        desc["identifier"] = f"custom:{desc['identifier'].split(':')[-1]}"
        errors.append(f"Fixed identifier namespace to {desc['identifier']}")

    # Validate components
    components = entity.get("components", {})
    if not components:
        raise ValueError("Entity has no components")

    # Clamp health
    health = components.get("minecraft:health", {})
    if isinstance(health, dict) and "value" in health:
        health["value"] = max(1, min(2048, health["value"]))
        health["max"] = max(health["value"], health.get("max", health["value"]))

    # Clamp attack
    attack = components.get("minecraft:attack", {})
    if isinstance(attack, dict) and "damage" in attack:
        attack["damage"] = max(1, min(100, attack["damage"]))

    # Clamp movement speed
    movement = components.get("minecraft:movement", {})
    if isinstance(movement, dict) and "value" in movement:
        movement["value"] = max(0.05, min(2.0, movement["value"]))

    # Ensure essential components exist
    if "minecraft:physics" not in components:
        components["minecraft:physics"] = {}
    if "minecraft:collision_box" not in components:
        components["minecraft:collision_box"] = {"width": 0.6, "height": 1.8}
    if "minecraft:nameable" not in components:
        components["minecraft:nameable"] = {}

    return mob_data


def extract_metadata(mob_data: dict, description: str, style_override: str = "") -> dict:
    """
    Extract metadata from the entity JSON itself.
    This is robust — it reads stats directly from the components,
    not from a separate metadata key that the LLM may or may not produce.

    Args:
        mob_data: The validated entity JSON.
        description: Original user description.
        style_override: The style explicitly chosen by the LLM via _mob_forge_style.
    """
    entity = mob_data.get("minecraft:entity", {})
    desc_block = entity.get("description", {})
    components = entity.get("components", {})

    identifier = desc_block.get("identifier", "custom:mob")
    mob_name = identifier.split(":")[-1]

    # Make a nice display name from the identifier
    display_name = mob_name.replace("_", " ").title()

    # Extract stats from components
    health = components.get("minecraft:health", {})
    hp = health.get("value", health.get("max", "?"))

    attack = components.get("minecraft:attack", {})
    atk = attack.get("damage", "?")

    movement = components.get("minecraft:movement", {})
    spd = movement.get("value", "?")

    # Detect abilities from behavior components
    abilities = []
    if "minecraft:can_fly" in components or "minecraft:movement.fly" in components:
        abilities.append("Flight")
    if "minecraft:fire_immune" in components:
        abilities.append("Fire Immune")
    if "minecraft:explode" in components:
        abilities.append("Explosive")
    if "minecraft:shooter" in components:
        abilities.append("Ranged Attack")
    if "minecraft:behavior.ranged_attack" in components:
        abilities.append("Ranged Attack")
    if "minecraft:behavior.melee_attack" in components:
        abilities.append("Melee Attack")
    if "minecraft:behavior.swell" in components:
        abilities.append("Self-Destruct")
    if "minecraft:burns_in_daylight" in components:
        abilities.append("Burns in Sun")
    if "minecraft:behavior.leap_at_target" in components:
        abilities.append("Leap Attack")
    if "minecraft:spell_effects" in components:
        abilities.append("Magic")
    if "minecraft:area_attack" in components:
        abilities.append("Area Attack")
    if "minecraft:can_climb" in components:
        abilities.append("Wall Climb")
    if "minecraft:navigation.fly" in components:
        abilities.append("Flight")
    if "minecraft:navigation.swim" in components:
        abilities.append("Swimmer")

    # Deduplicate
    abilities = list(dict.fromkeys(abilities))

    # Use LLM-chosen style if valid, otherwise fall back to heuristic
    style = style_override if style_override in STYLE_GEOMETRY_MAP else ""
    if not style:
        # Heuristic fallback
        if "minecraft:can_fly" in components or "minecraft:movement.fly" in components:
            style = "phantom"
        elif "minecraft:navigation.swim" in components:
            style = "dolphin"
        else:
            collision = components.get("minecraft:collision_box", {})
            width = collision.get("width", 0.6)
            height = collision.get("height", 1.8)
            if width > 1.5:
                style = "ravager"
            elif width > 1.0 and height < width:
                style = "pig"
            elif width > 0.8 and height < 1.5:
                style = "cow"
            elif height > 2.5:
                style = "enderman"
            elif height < 0.6:
                style = "slime"
            else:
                style = "zombie"

    # Guess colors from the description
    color_hints = {
        # Animals
        "elephant": ["#888888", "#999999", "#666666"],
        "giraffe": ["#DAA520", "#F5DEB3", "#8B6914"],
        "lion": ["#C4A44A", "#E8D28A", "#8B6914"],
        "tiger": ["#FF8C00", "#000000", "#FF6600"],
        "bear": ["#5C4033", "#8B6914", "#3D2B1F"],
        "panda": ["#FFFFFF", "#000000", "#CCCCCC"],
        "horse": ["#8B4513", "#A0522D", "#5C3317"],
        "cow": ["#FFFFFF", "#3D2B1F", "#8B6914"],
        "deer": ["#8B6914", "#C4A44A", "#5C3317"],
        "whale": ["#2C3E50", "#34495E", "#1A252F"],
        "shark": ["#708090", "#A9A9A9", "#4A4A4A"],
        "dolphin": ["#708090", "#A9A9A9", "#5F6F7F"],
        "turtle": ["#2E8B57", "#3CB371", "#1A5B3A"],
        "frog": ["#228B22", "#32CD32", "#006400"],
        "snake": ["#2E8B57", "#3CB371", "#1A3C2B"],
        "bird": ["#4169E1", "#6495ED", "#1E3A6E"],
        "parrot": ["#FF4500", "#FFD700", "#228B22"],
        "eagle": ["#5C3317", "#FFFFFF", "#FFD700"],
        "penguin": ["#000000", "#FFFFFF", "#FFD700"],
        "cat": ["#FF8C00", "#FFFFFF", "#A0522D"],
        "dog": ["#C4A44A", "#8B6914", "#5C3317"],
        "rabbit": ["#CCCCCC", "#FFFFFF", "#AAAAAA"],
        "fox": ["#FF6600", "#FFFFFF", "#CC4400"],
        "monkey": ["#8B4513", "#CD853F", "#5C3317"],
        "gorilla": ["#2F2F2F", "#4A4A4A", "#1A1A1A"],
        "rhino": ["#808080", "#999999", "#555555"],
        "hippo": ["#708090", "#8B7D7B", "#4A4A5A"],
        "croc": ["#556B2F", "#6B8E23", "#3B4F1A"],
        "alligator": ["#556B2F", "#6B8E23", "#3B4F1A"],
        "dinosaur": ["#228B22", "#556B2F", "#1A3C2B"],
        # Elements & themes
        "fire": ["#FF4400", "#FFaa00", "#220000"],
        "ice": ["#88DDFF", "#AAEEFF", "#4488CC"],
        "frost": ["#88DDFF", "#AAEEFF", "#4488CC"],
        "snow": ["#FFFFFF", "#E0E0E0", "#B0C4DE"],
        "dragon": ["#AA2200", "#FF6600", "#331100"],
        "shadow": ["#2A1B3D", "#44318D", "#1A1A2E"],
        "undead": ["#3D5A3D", "#5A7A5A", "#2D3D2D"],
        "mushroom": ["#CC3333", "#FFCC99", "#8B4513"],
        "golem": ["#888888", "#AAAAAA", "#555555"],
        "stone": ["#888888", "#AAAAAA", "#555555"],
        "iron": ["#B8B8B8", "#D4D4D4", "#808080"],
        "slime": ["#44CC44", "#88FF88", "#227722"],
        "spider": ["#2B1B0E", "#4A3728", "#1A0F08"],
        "skeleton": ["#CCCCCC", "#EEEEEE", "#888888"],
        "bone": ["#CCCCCC", "#EEEEEE", "#888888"],
        "wolf": ["#999999", "#CCCCCC", "#666666"],
        "pig": ["#FFAA88", "#FF8866", "#CC6644"],
        "creeper": ["#55AA44", "#77CC66", "#337722"],
        "zombie": ["#3D5A3D", "#5A7A5A", "#2D3D2D"],
        "water": ["#2288CC", "#44AAFF", "#115588"],
        "ocean": ["#2288CC", "#44AAFF", "#115588"],
        "lava": ["#FF4400", "#FF8800", "#CC2200"],
        "magma": ["#FF4400", "#FF8800", "#CC2200"],
        "crystal": ["#AA88FF", "#CC99FF", "#7744CC"],
        "golden": ["#FFD700", "#FFC107", "#B8860B"],
        "gold": ["#FFD700", "#FFC107", "#B8860B"],
        "dark": ["#1A1A2E", "#16213E", "#0F3460"],
        "light": ["#FFFFCC", "#FFFF99", "#FFD700"],
        "sand": ["#EDC9AF", "#F5DEB3", "#C2B280"],
        "desert": ["#EDC9AF", "#F5DEB3", "#C2B280"],
        "jungle": ["#228B22", "#32CD32", "#0B6623"],
        "forest": ["#228B22", "#2E8B57", "#0B6623"],
        "purple": ["#800080", "#9932CC", "#4B0082"],
        "red": ["#CC0000", "#FF2222", "#880000"],
        "blue": ["#0066CC", "#3399FF", "#003366"],
    }

    desc_lower = description.lower()
    suggested_colors = ["#808080", "#606060", "#404040"]  # default grey (not green!)
    for keyword, colors in color_hints.items():
        if keyword in desc_lower:
            suggested_colors = colors
            break

    return {
        "display_name": display_name,
        "description": description,
        "hp": hp,
        "attack": atk,
        "speed": spd,
        "abilities": abilities,
        "suggested_colors": suggested_colors,
        "suggested_style": style,
    }


async def generate_mob(description: str, difficulty: str = "medium") -> str:
    """
    Generate a Minecraft Bedrock entity from a natural language description.

    Args:
        description: Natural language description of the desired mob
                     (e.g., "A fire-breathing dragon that flies and has 100 HP")
        difficulty: Difficulty preset - "easy", "medium", or "hard"
                    Affects stat ranges and abilities.

    Returns:
        JSON string with the complete Bedrock entity spec and metadata.
    """
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "medium"

    client = get_client()

    user_prompt = (
        f"Create a Minecraft Bedrock entity for: {description}\n"
        f"Difficulty: {difficulty}\n"
        f"Remember: output ONLY valid JSON, no markdown fences."
    )

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": GENERATE_MOB_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    raw_text = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines)

    # Try to find JSON in the response (sometimes LLMs add text around it)
    json_match = re.search(r'\{[\s\S]*\}', raw_text)
    if json_match:
        raw_text = json_match.group()

    try:
        mob_data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Failed to parse LLM response as JSON: {str(e)}",
            "raw_response": raw_text[:500],
        })

    # Extract the _mob_forge_style the LLM chose, then remove non-Bedrock keys
    llm_style = mob_data.pop("_mob_forge_style", "")
    llm_loot = mob_data.pop("_mob_forge_loot", [])
    mob_data.pop("mob_metadata", None)

    # Validate the chosen style
    if llm_style and llm_style not in STYLE_GEOMETRY_MAP:
        llm_style = ""  # will fall back to heuristic

    # Ensure minecraft:loot component points to the correct loot table path
    entity = mob_data.get("minecraft:entity", {})
    components = entity.get("components", {})
    identifier = entity.get("description", {}).get("identifier", "custom:mob")
    mob_name_for_loot = identifier.split(":")[-1]
    if llm_loot:
        components["minecraft:loot"] = {
            "table": f"loot_tables/entities/{mob_name_for_loot}.json"
        }

    try:
        mob_data = validate_mob_json(mob_data)
    except ValueError as e:
        return json.dumps({
            "error": f"Validation failed: {str(e)}",
            "raw_data": mob_data,
        })

    # Extract metadata using the LLM-chosen style
    metadata = extract_metadata(mob_data, description, style_override=llm_style)

    # Attach loot data to metadata so build pipeline can generate loot table files
    if llm_loot and isinstance(llm_loot, list):
        metadata["loot_drops"] = llm_loot

    result = {
        "entity": mob_data,
        "metadata": metadata,
        "status": "success",
    }

    return json.dumps(result, indent=2)
