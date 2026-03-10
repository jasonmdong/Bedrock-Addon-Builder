"""Dynamic MCP context injection based on user prompt analysis.

Analyzes the user's prompt to detect behavioral intents (fire breathing,
flying, exploding, tameable, etc.) and selects relevant Bedrock component
documentation, vanilla mob examples, and behavior patterns to inject into
the LLM system prompt.

This is purely local — no external API calls. Context is pulled from
MCP/mcp_server/tools/bedrock_reference.py and backend/data/*.json.

Design principles:
  - Prompt-driven: only injects context relevant to what the user asked for
  - Additive: never removes existing static context, only augments
  - Budget-aware: caps total injected context to stay within token limits
  - Deterministic: same prompt always produces same context selection
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Context budget
# ---------------------------------------------------------------------------

MAX_DYNAMIC_CONTEXT_CHARS = 6000  # ~1500 tokens — leaves room for other layers

# ---------------------------------------------------------------------------
# Behavior intents — keyword → intent mapping
# ---------------------------------------------------------------------------

@dataclass
class BehaviorIntent:
    """A detected behavioral intent from the user's prompt."""
    name: str
    confidence: float  # 0.0–1.0
    keywords_matched: list[str] = field(default_factory=list)


# Each intent maps to: (keywords, priority, context_builder_fn_name)
# Priority determines injection order when budget is tight (lower = higher priority)
INTENT_KEYWORDS: dict[str, dict] = {
    "ranged_attack": {
        "keywords": [
            "fire breath", "fire-breath", "fireball", "shoot", "shooting",
            "ranged", "projectile", "spit", "throw", "hurl", "blast",
            "fireball", "fire ball", "flame", "flames",
            "ice bolt", "lightning bolt", "arrow", "arrows",
            "sniper", "cannon", "laser", "beam",
        ],
        "priority": 1,
    },
    "flying": {
        "keywords": [
            "fly", "flying", "flight", "airborne", "soar", "soaring",
            "hover", "hovering", "float", "floating", "wings", "winged",
            "dragon", "phoenix", "wyvern", "pterodactyl", "bat-like",
            "aerial", "sky",
        ],
        "priority": 2,
    },
    "exploding": {
        "keywords": [
            "explod", "explosion", "bomb", "detonate", "self-destruct",
            "boom", "blast", "tnt", "volatile", "unstable",
            "creeper-like", "suicide bomb", "kamikaze",
        ],
        "priority": 3,
    },
    "passive": {
        "keywords": [
            "passive", "peaceful", "friendly", "docile", "tame",
            "pet", "companion", "farm", "livestock", "grazing",
            "non-hostile", "non hostile", "harmless", "gentle",
            "wander", "calm",
        ],
        "priority": 4,
    },
    "tameable": {
        "keywords": [
            "tame", "tameable", "tamable", "pet", "domesticate",
            "rideable", "ridable", "ride", "mount", "mountable",
            "saddle", "leash",
        ],
        "priority": 5,
    },
    "aquatic": {
        "keywords": [
            "aquatic", "water", "swim", "swimming", "underwater",
            "ocean", "sea", "fish", "shark", "whale", "dolphin",
            "squid", "octopus", "jellyfish", "amphibian",
        ],
        "priority": 6,
    },
    "boss": {
        "keywords": [
            "boss", "boss mob", "mini-boss", "miniboss", "elite",
            "powerful", "legendary", "mythical", "titan",
            "massive damage", "very strong", "ultra",
        ],
        "priority": 7,
    },
    "area_attack": {
        "keywords": [
            "area attack", "stomp", "ground pound", "shockwave",
            "aoe", "area of effect", "slam", "quake",
            "splash damage", "cleave",
        ],
        "priority": 8,
    },
    "teleport": {
        "keywords": [
            "teleport", "blink", "phase", "warp", "flash step",
            "enderman", "ender", "dimensional",
        ],
        "priority": 9,
    },
    "climbing": {
        "keywords": [
            "climb", "climbing", "wall climb", "spider-like",
            "scale walls", "crawl", "cling",
        ],
        "priority": 10,
    },
    "breeding": {
        "keywords": [
            "breed", "breeding", "breedable", "baby", "offspring",
            "mate", "reproduce",
        ],
        "priority": 11,
    },
}

# ---------------------------------------------------------------------------
# Context snippets for each intent
# ---------------------------------------------------------------------------

INTENT_CONTEXT: dict[str, str] = {
    "ranged_attack": """## RANGED ATTACK (fire breathing, shooting projectiles)
To make a mob shoot projectiles, you need BOTH of these components:
- "minecraft:shooter": {"def": "minecraft:small_fireball"} — defines the projectile type
- "minecraft:behavior.ranged_attack": {"priority": 3, "attack_interval_min": 2.0, "attack_interval_max": 5.0, "attack_radius": 15.0}

IMPORTANT: Do NOT include "minecraft:behavior.melee_attack" alongside ranged attack — the mob will ignore ranged and always melee instead.

Valid projectile types for "def":
- "minecraft:small_fireball" — blaze-style fireball (RECOMMENDED, most reliable)
- "minecraft:arrow" — skeleton-style arrow
- "minecraft:snowball" — snowball

For fire-breathing mobs, also add:
- "minecraft:fire_immune": {}

VALID ranged_attack keys (do NOT add others — invalid keys cause silent failure):
- priority, speed_multiplier, attack_interval_min, attack_interval_max
- attack_radius, attack_radius_min, burst_shots, burst_interval
- x_max_rotation, y_max_head_rotation

Example — Fire Dragon (ranged attacker):
```json
"minecraft:shooter": {"def": "minecraft:small_fireball"},
"minecraft:behavior.ranged_attack": {"priority": 3, "attack_interval_min": 2.0, "attack_interval_max": 4.0, "attack_radius": 16.0},
"minecraft:fire_immune": {},
"minecraft:behavior.nearest_attackable_target": {"priority": 1, "entity_types": [{"filters": {"test": "is_family", "value": "player"}, "max_dist": 32}]},
"minecraft:behavior.hurt_by_target": {"priority": 1}
```
""",

    "flying": """## FLYING MOBS
To make a mob fly, you MUST replace walk/basic movement with fly variants:
- "minecraft:movement.fly": {} — (replaces minecraft:movement.basic)
- "minecraft:navigation.fly": {"can_path_over_water": true, "can_path_over_lava": true} — (replaces minecraft:navigation.walk)
- "minecraft:can_fly": {}

IMPORTANT: Do NOT include both minecraft:movement.basic AND minecraft:movement.fly — they conflict and the mob gets stuck.
Do NOT include both minecraft:navigation.walk AND minecraft:navigation.fly — same issue.

Example — Flying Dragon:
```json
"minecraft:movement.fly": {},
"minecraft:navigation.fly": {"can_path_over_water": true, "can_path_over_lava": true},
"minecraft:can_fly": {},
"minecraft:flying_speed": {"value": 0.4}
```
""",

    "exploding": """## EXPLODING MOBS (creeper-like)
To make a mob explode on approach:
- "minecraft:behavior.swell": {"priority": 2, "start_distance": 2.5, "stop_distance": 6.0} — triggers the fuse
- "minecraft:explode": {"fuse_length": 1.5, "fuse_lit": true, "power": 3, "causes_fire": false, "destroy_affected_by_griefing": true}

IMPORTANT: Do NOT include "minecraft:behavior.melee_attack" — the mob should swell and explode, not punch.
Set "minecraft:behavior.melee_attack": null to explicitly remove it.

Example — Vanilla Creeper components:
```json
"minecraft:behavior.swell": {"priority": 2, "start_distance": 2.5, "stop_distance": 6.0},
"minecraft:explode": {"fuse_length": 1.5, "fuse_lit": true, "power": 3, "causes_fire": false, "destroy_affected_by_griefing": true},
"minecraft:behavior.melee_attack": null
```
""",

    "passive": """## PASSIVE / PEACEFUL MOBS
Passive mobs flee when attacked and wander peacefully:
- "minecraft:behavior.panic": {"priority": 1, "speed_multiplier": 1.5} — flee when hurt
- "minecraft:behavior.tempt": {"priority": 3, "speed_multiplier": 1.2, "items": ["wheat"]} — follow players holding items
- "minecraft:behavior.random_stroll": {"priority": 5, "speed_multiplier": 0.8}
- "minecraft:behavior.look_at_player": {"priority": 6, "look_distance": 6.0}

Do NOT include "minecraft:behavior.nearest_attackable_target" or "minecraft:behavior.melee_attack" for passive mobs.
Do NOT include "minecraft:attack" — passive mobs deal no damage.

Example — Passive Farm Animal:
```json
"minecraft:behavior.panic": {"priority": 1, "speed_multiplier": 1.5},
"minecraft:behavior.tempt": {"priority": 3, "speed_multiplier": 1.2, "items": ["wheat"]},
"minecraft:behavior.random_stroll": {"priority": 5, "speed_multiplier": 0.8},
"minecraft:behavior.look_at_player": {"priority": 6, "look_distance": 6.0},
"minecraft:behavior.random_look_around": {"priority": 7}
```
""",

    "tameable": """## TAMEABLE / RIDEABLE MOBS
To make a mob tameable:
- "minecraft:tameable": {"probability": 0.33, "tame_items": ["minecraft:bone"]}
- "minecraft:behavior.beg": {"priority": 9, "look_distance": 8, "items": ["minecraft:bone"]}

To make a mob rideable (after taming or always):
- "minecraft:rideable": {"seat_count": 1, "family_types": ["player"], "seats": [{"position": [0.0, 1.2, 0.0]}]}
- "minecraft:input_ground_controlled": {} — lets the player steer
- "minecraft:behavior.mount_pathing": {"priority": 1, "speed_multiplier": 1.25, "target_dist": 0}

Example — Tameable Rideable Wolf:
```json
"minecraft:tameable": {"probability": 0.33, "tame_items": ["minecraft:bone"]},
"minecraft:rideable": {"seat_count": 1, "family_types": ["player"], "seats": [{"position": [0.0, 1.2, 0.0]}]},
"minecraft:input_ground_controlled": {},
"minecraft:behavior.beg": {"priority": 9, "look_distance": 8, "items": ["minecraft:bone"]}
```
""",

    "aquatic": """## AQUATIC / WATER MOBS
For mobs that live in water:
- "minecraft:navigation.swim": {} — (replaces minecraft:navigation.walk)
- "minecraft:breathable": {"breathes_water": true, "breathes_air": false}
- "minecraft:movement.sway": {} — (replaces minecraft:movement.basic)
- "minecraft:behavior.swim_idle": {"priority": 5}
- "minecraft:behavior.swim_wander": {"priority": 4, "speed_multiplier": 1.0}

Do NOT include minecraft:navigation.walk or minecraft:movement.basic for aquatic mobs.

Example — Shark:
```json
"minecraft:navigation.swim": {},
"minecraft:breathable": {"breathes_water": true, "breathes_air": false},
"minecraft:movement.sway": {},
"minecraft:behavior.swim_wander": {"priority": 4, "speed_multiplier": 1.0},
"minecraft:behavior.swim_idle": {"priority": 5}
```
""",

    "boss": """## BOSS MOBS
Boss mobs should have:
- High HP: 100–2048 (use "minecraft:health": {"value": 200, "max": 200})
- High damage: 15–50+
- Knockback resistance: "minecraft:knockback_resistance": {"value": 0.8} to {"value": 1.0}
- Multiple attack types: combine melee + ranged, or melee + area
- Large scale: "minecraft:scale": {"value": 2.0} to {"value": 4.0}
- Large collision box to match scale

Consider adding multiple abilities:
- Ranged + melee (use component_groups for phase switching)
- Area attack: "minecraft:area_attack": {"damage_range": 0.2, "damage_per_tick": 4, "cause": "entity_attack"}
- High follow range for aggressive targeting
""",

    "area_attack": """## AREA ATTACK (stomp, ground pound, shockwave)
For area-of-effect damage around the mob:
- "minecraft:area_attack": {"damage_range": 0.2, "damage_per_tick": 4, "cause": "entity_attack"}

This deals damage to all nearby entities every tick within range. Good for:
- Large mobs that stomp
- Electric/poison aura mobs
- Ground pound attacks

Can be combined with melee attack for mobs that both swing and have an AoE aura.
""",

    "teleport": """## TELEPORTING MOBS (Enderman-like)
To make a mob teleport:
- "minecraft:teleport": {"random_teleports": true, "min_teleport_time": 5, "max_teleport_time": 30, "random_teleport_cube": [32, 16, 32]}

This makes the mob randomly teleport within the specified cube dimensions.
Combine with high damage and melee for an Enderman-like experience.
""",

    "climbing": """## CLIMBING MOBS (Spider-like)
To make a mob climb walls:
- "minecraft:can_climb": {}
- "minecraft:navigation.climb": {"can_path_over_water": false} — (replaces minecraft:navigation.walk)

Combine with:
- "minecraft:behavior.leap_at_target": {"priority": 4, "yd": 0.4, "must_be_on_ground": true}
- "minecraft:behavior.stalk_and_pounce_on_target": {"priority": 4}
""",

    "breeding": """## BREEDABLE MOBS
To make a mob breedable:
- "minecraft:breedable": {"require_tame": false, "breed_items": ["wheat"], "breeds_with": [{"mate_type": "custom:your_mob", "baby_type": "custom:your_mob"}]}
- "minecraft:behavior.breed": {"priority": 3, "speed_multiplier": 1.0}
- "minecraft:behavior.tempt": {"priority": 4, "speed_multiplier": 1.2, "items": ["wheat"]}
- "minecraft:is_baby": {} — (for baby variant, usually in a component_group)

Breedable mobs should typically be passive.
""",
}

# ---------------------------------------------------------------------------
# Vanilla mob examples keyed by relevance to intents
# ---------------------------------------------------------------------------

# Maps intent → list of vanilla mob names whose components are good examples
INTENT_EXAMPLE_MOBS: dict[str, list[str]] = {
    "ranged_attack": ["blaze"],
    "flying": ["blaze"],
    "exploding": ["creeper"],
    "passive": ["cow", "pig", "sheep", "chicken"],
    "tameable": ["cow"],  # simplified
    "aquatic": [],
    "boss": ["iron_golem"],
    "area_attack": ["iron_golem"],
    "teleport": ["enderman"],
    "climbing": ["spider"],
    "breeding": ["cow", "sheep"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class DynamicContext:
    """Result of prompt-based dynamic context selection."""
    intents: list[BehaviorIntent] = field(default_factory=list)
    context_text: str = ""
    example_mobs_used: list[str] = field(default_factory=list)
    total_chars: int = 0

    @property
    def has_content(self) -> bool:
        return bool(self.context_text)


def detect_intents(prompt: str) -> list[BehaviorIntent]:
    """Analyze a prompt to detect behavioral intents, sorted by confidence then priority."""
    prompt_lower = prompt.lower()
    intents: list[BehaviorIntent] = []

    for intent_name, config in INTENT_KEYWORDS.items():
        matched = []
        for kw in config["keywords"]:
            # Use word boundary-ish matching for short keywords
            if len(kw) <= 3:
                if re.search(rf'\b{re.escape(kw)}\b', prompt_lower):
                    matched.append(kw)
            else:
                if kw in prompt_lower:
                    matched.append(kw)

        if matched:
            # Confidence based on how many keywords matched
            confidence = min(1.0, len(matched) * 0.4)
            intents.append(BehaviorIntent(
                name=intent_name,
                confidence=confidence,
                keywords_matched=matched,
            ))

    # Sort by confidence (desc), then priority (asc)
    intents.sort(key=lambda i: (-i.confidence, INTENT_KEYWORDS[i.name]["priority"]))
    return intents


def build_dynamic_context(
    prompt: str,
    category: str = "entity_logic_ai",
    vanilla_mobs: Optional[dict] = None,
) -> DynamicContext:
    """Build dynamic context based on the user's prompt.

    Detects behavioral intents, selects relevant component documentation
    and vanilla mob examples, and assembles a context string for injection
    into the LLM system prompt.

    Args:
        prompt: The user's natural language prompt
        category: Content category (only entity_logic_ai uses dynamic context)
        vanilla_mobs: Optional dict of vanilla mob specs (from vanilla_mobs.json)

    Returns:
        DynamicContext with the assembled context text
    """
    if category != "entity_logic_ai":
        return DynamicContext()

    intents = detect_intents(prompt)
    if not intents:
        return DynamicContext()

    # Load vanilla mobs if not provided
    if vanilla_mobs is None:
        vanilla_mobs = _load_vanilla_mobs()

    parts: list[str] = []
    example_mobs_used: list[str] = []
    budget = MAX_DYNAMIC_CONTEXT_CHARS

    # Header
    header = "--- DYNAMIC CONTEXT (selected based on your prompt) ---\n"
    parts.append(header)
    budget -= len(header)

    # Add context snippets for each detected intent (budget-aware)
    for intent in intents:
        snippet = INTENT_CONTEXT.get(intent.name, "")
        if not snippet:
            continue
        if len(snippet) > budget:
            continue  # Skip if it would exceed budget
        parts.append(snippet)
        budget -= len(snippet)

        # Add vanilla mob examples for this intent
        example_names = INTENT_EXAMPLE_MOBS.get(intent.name, [])
        for mob_name in example_names:
            if mob_name in example_mobs_used:
                continue  # Don't repeat the same example
            mob_data = vanilla_mobs.get(mob_name)
            if not mob_data:
                continue
            example_text = _format_mob_example(mob_name, mob_data)
            if len(example_text) > budget:
                continue
            parts.append(example_text)
            budget -= len(example_text)
            example_mobs_used.append(mob_name)

    # Footer
    footer = "\n--- END DYNAMIC CONTEXT ---"
    parts.append(footer)

    context_text = "\n".join(parts)

    return DynamicContext(
        intents=intents,
        context_text=context_text,
        example_mobs_used=example_mobs_used,
        total_chars=len(context_text),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_vanilla_mobs_cache: Optional[dict] = None


def _load_vanilla_mobs() -> dict:
    """Load vanilla mobs from backend/data/vanilla_mobs.json (cached)."""
    global _vanilla_mobs_cache
    if _vanilla_mobs_cache is not None:
        return _vanilla_mobs_cache

    data_path = Path(__file__).resolve().parent.parent / "data" / "vanilla_mobs.json"
    if data_path.exists():
        try:
            raw = json.loads(data_path.read_text(encoding="utf-8"))
            _vanilla_mobs_cache = raw.get("mobs", {})
        except Exception:
            _vanilla_mobs_cache = {}
    else:
        _vanilla_mobs_cache = {}
    return _vanilla_mobs_cache


def _format_mob_example(mob_name: str, mob_data: dict) -> str:
    """Format a vanilla mob as a compact example for context injection."""
    display = mob_data.get("display_name", mob_name.title())
    hp = mob_data.get("hp", "?")
    damage = mob_data.get("damage", "?")
    speed = mob_data.get("speed", "?")
    components = mob_data.get("components", {})

    if not components:
        return ""

    lines = [
        f"### Vanilla Reference: {display}",
        f"HP={hp}, Damage={damage}, Speed={speed}",
        f"Special components: {json.dumps(components, indent=2)}",
        "",
    ]
    return "\n".join(lines)
