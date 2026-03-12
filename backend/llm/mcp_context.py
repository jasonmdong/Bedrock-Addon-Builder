"""MCP-augmented context retrieval for the LLM pipeline.

Fetches dynamic context from Minecraft Creator Tools (MCP) to enrich
LLM prompts with authoritative schemas and model templates.

Also provides `mcp_design_model()` to generate geometry + texture PNGs
via the MCP `designModel` tool.

Design principles:
  - Additive only: if MCP is unavailable, returns empty context (never blocks).
  - Circuit breaker: after repeated failures, auto-disables for a cooldown period.
  - Cached: schemas cached with TTL; failures cached with shorter TTL.
  - Parallel: independent MCP calls run concurrently via asyncio.gather.
"""

import asyncio
import base64
import json
import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.llm.prompt_intents import PromptIntentProfile, extract_prompt_intents

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class MCPContext:
    """Context retrieved from MCP tools for prompt injection."""
    schema_text: str = ""
    template_text: str = ""
    source_tools: list[str] = field(default_factory=list)
    retrieval_ms: int = 0
    available: bool = False
    skipped_reason: str = ""

    @property
    def has_content(self) -> bool:
        return bool(self.schema_text or self.template_text)


@dataclass
class MCPValidationResult:
    """Result of post-generation MCP validation."""
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    raw_content: list[dict] = field(default_factory=list)
    available: bool = False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CACHE_TTL = 600  # 10 minutes
NEGATIVE_CACHE_TTL = 120  # 2 min — cache failures so we don't retry every request
MAX_MCP_SCHEMA_CHARS = 8000
MAX_MCP_TEMPLATE_CHARS = 4000
MCP_RETRIEVAL_TIMEOUT = 10  # seconds — hard cap on template retrieval
MCP_TOOL_TIMEOUT = 8.0  # seconds — per-tool httpx timeout (overrides the global 30s)
MCP_VALIDATION_TIMEOUT = 15.0  # seconds — per-validation httpx timeout

# Circuit breaker: after this many consecutive failures, stop trying
CIRCUIT_BREAKER_THRESHOLD = 2
CIRCUIT_BREAKER_COOLDOWN = 300  # 5 minutes

# Maps prompt keywords → MCP getModelTemplates templateType.
# Full valid enum: humanoid, small_animal, large_animal, vehicle, bird, insect,
# flying, fish, slime, wizard, golem, fox, crystal, enchanted_sword,
# tropical_fish, ghost, robot, mushroom_creature, treasure_chest,
# block, stone_brick, wooden_crate, glowing_ore, mossy_stone, crystal_block,
# tech_block, item, potion_bottle, magic_wand, ornate_key, gemstone, apple, pickaxe
TEMPLATE_KEYWORDS: dict[str, list[str]] = {
    "humanoid": [
        "humanoid", "human", "zombie", "skeleton", "villager",
        "biped", "npc", "person", "warrior", "knight",
    ],
    "small_animal": [
        "pig", "sheep", "rabbit", "chicken", "cat", "dog", "fox",
        "small animal", "small mob", "pet",
    ],
    "large_animal": [
        "cow", "horse", "wolf", "bear", "lion", "tiger",
        "large animal", "quadruped", "four legs", "spider",
    ],
    "bird": ["bird", "parrot", "eagle", "owl", "crow", "wings"],
    "flying": ["flying", "bat", "phantom", "dragon", "fly"],
    "fish": ["fish", "salmon", "cod", "aquatic", "swim", "dolphin", "tropical"],
    "insect": ["insect", "bee", "spider", "scorpion", "ant", "bug"],
    "slime": ["slime", "blob", "jelly", "ooze", "cube"],
    "golem": ["golem", "iron golem", "snow golem", "construct", "guardian"],
    "wizard": ["wizard", "mage", "witch", "sorcerer", "enchanter"],
    "ghost": ["ghost", "phantom", "spirit", "wraith", "specter"],
    "robot": ["robot", "mech", "machine", "android", "automaton"],
    "vehicle": ["vehicle", "car", "boat", "minecart", "mount"],
    "fox": ["fox"],
    "crystal": ["crystal", "gem", "prism"],
    "mushroom_creature": ["mushroom", "fungus", "mooshroom", "shroom"],
    "block": ["block", "cube", "brick", "stone", "wood", "crate"],
    "item": ["sword", "weapon", "tool", "wand", "staff", "bow", "axe"],
    "potion_bottle": ["potion", "bottle", "flask", "elixir"],
    "pickaxe": ["pickaxe", "mining", "digger"],
}

# Default template to fetch per app category when no keyword match is found
_CATEGORY_DEFAULT_TEMPLATE: dict[str, str] = {
    "entity_logic_ai": "humanoid",
    "items_weaponry": "item",
    "blocks_furniture": "block",
    "loot_recipes": "humanoid",
    "scripting_components": "humanoid",
}


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

# value is (text_or_None, timestamp) — None means "this tool failed, don't retry soon"
_schema_cache: dict[str, tuple[Optional[str], float]] = {}
_template_cache: dict[str, tuple[Optional[str], float]] = {}


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

_consecutive_retrieval_failures: int = 0
_consecutive_validation_failures: int = 0
_retrieval_tripped_until: float = 0.0
_validation_tripped_until: float = 0.0


def _is_retrieval_tripped() -> bool:
    if _retrieval_tripped_until and time.time() < _retrieval_tripped_until:
        return True
    return False


def _is_validation_tripped() -> bool:
    if _validation_tripped_until and time.time() < _validation_tripped_until:
        return True
    return False


def _record_retrieval_failure() -> None:
    global _consecutive_retrieval_failures, _retrieval_tripped_until
    _consecutive_retrieval_failures += 1
    if _consecutive_retrieval_failures >= CIRCUIT_BREAKER_THRESHOLD:
        _retrieval_tripped_until = time.time() + CIRCUIT_BREAKER_COOLDOWN
        log.warning(
            "[mcp_context] Circuit breaker TRIPPED for retrieval after %d failures "
            "(cooldown %ds)",
            _consecutive_retrieval_failures, CIRCUIT_BREAKER_COOLDOWN,
        )


def _record_retrieval_success() -> None:
    global _consecutive_retrieval_failures, _retrieval_tripped_until
    _consecutive_retrieval_failures = 0
    _retrieval_tripped_until = 0.0


def _record_validation_failure() -> None:
    global _consecutive_validation_failures, _validation_tripped_until
    _consecutive_validation_failures += 1
    if _consecutive_validation_failures >= CIRCUIT_BREAKER_THRESHOLD:
        _validation_tripped_until = time.time() + CIRCUIT_BREAKER_COOLDOWN
        log.warning(
            "[mcp_context] Circuit breaker TRIPPED for validation after %d failures "
            "(cooldown %ds)",
            _consecutive_validation_failures, CIRCUIT_BREAKER_COOLDOWN,
        )


def _record_validation_success() -> None:
    global _consecutive_validation_failures, _validation_tripped_until
    _consecutive_validation_failures = 0
    _validation_tripped_until = 0.0


def clear_cache() -> None:
    """Clear all cached MCP context and reset circuit breakers."""
    global _consecutive_retrieval_failures, _consecutive_validation_failures
    global _retrieval_tripped_until, _validation_tripped_until
    _schema_cache.clear()
    _template_cache.clear()
    _consecutive_retrieval_failures = 0
    _consecutive_validation_failures = 0
    _retrieval_tripped_until = 0.0
    _validation_tripped_until = 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated for token budget]"


def _format_for_prompt(tool_name: str, raw_content: list[dict]) -> str:
    """Extract text from MCP tool response content items."""
    parts = []
    for item in raw_content:
        if item.get("type") == "text":
            text = item.get("text", "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _should_fetch_templates(
    prompt: str,
    category: str,
    intent_profile: Optional[PromptIntentProfile] = None,
) -> bool:
    """Return True when the prompt likely benefits from a geometry template."""
    if category != "entity_logic_ai":
        return False

    profile = intent_profile or extract_prompt_intents(prompt, category)
    if profile.constraints.get("geometry_requested"):
        return True
    if profile.template_hint:
        return True
    return any(signal.name == "geometry_edit" for signal in profile.signals)


def _detect_template_type(
    prompt: str,
    category: str,
    intent_profile: Optional[PromptIntentProfile] = None,
) -> str:
    """Determine the best MCP template type from the user's prompt and category."""
    profile = intent_profile or extract_prompt_intents(prompt, category)
    if profile.template_hint:
        return profile.template_hint

    prompt_lower = prompt.lower()
    for template_type, keywords in TEMPLATE_KEYWORDS.items():
        if any(kw in prompt_lower for kw in keywords):
            return template_type
    return _CATEGORY_DEFAULT_TEMPLATE.get(category, "humanoid")


# ---------------------------------------------------------------------------
# MCP tool callers (async, with fallbacks)
# ---------------------------------------------------------------------------

async def _fetch_schema(category: str) -> Optional[str]:
    """Placeholder for schema retrieval.

    getEffectiveContentSchema requires a populated Minecraft project folder,
    which is impractical to maintain. We rely on local schemas from
    category_context.py instead (already injected via _get_full_system_prompt).
    Returns empty string — schema context comes from the static category_context.
    """
    return ""


async def _fetch_schema_cached(category: str) -> str:
    """Fetch schema with TTL-based in-memory caching (including negative cache)."""
    now = time.time()
    if category in _schema_cache:
        cached_val, ts = _schema_cache[category]
        ttl = CACHE_TTL if cached_val else NEGATIVE_CACHE_TTL
        if now - ts < ttl:
            return cached_val or ""
    result = await _fetch_schema(category)
    # Cache both successes and failures (None → negative cache entry)
    _schema_cache[category] = (result, now)
    return result or ""


async def _fetch_templates(prompt: str, category: str) -> str:
    """Fetch model templates from MCP based on prompt and category."""
    from backend.mctools.client import call_tool, MCTOOLS_ENABLED

    if not MCTOOLS_ENABLED:
        return ""

    profile = extract_prompt_intents(prompt, category)
    if not _should_fetch_templates(prompt, category, profile):
        return ""

    template_type = _detect_template_type(prompt, category, profile)

    cache_key = template_type
    now = time.time()
    if cache_key in _template_cache:
        cached_val, ts = _template_cache[cache_key]
        ttl = CACHE_TTL if cached_val else NEGATIVE_CACHE_TTL
        if now - ts < ttl:
            return cached_val or ""

    try:
        result = await call_tool(
            "getModelTemplates",
            {"templateType": template_type},
            timeout=MCP_TOOL_TIMEOUT,
        )
        if result.get("isError"):
            log.warning("[mcp_context] getModelTemplates returned isError for %s", template_type)
            _template_cache[cache_key] = (None, now)
            return ""
        text = _format_for_prompt("getModelTemplates", result.get("content", []))
        text = _truncate(text, MAX_MCP_TEMPLATE_CHARS)
        _template_cache[cache_key] = (text or None, now)
        return text
    except Exception as e:
        log.warning("[mcp_context] Template retrieval failed for %s: %s", template_type, e)
        _template_cache[cache_key] = (None, now)
        return ""


# ---------------------------------------------------------------------------
# Post-generation validation
# ---------------------------------------------------------------------------

async def mcp_validate(spec: dict) -> MCPValidationResult:
    """Validate a spec against MCP's validateContent tool.
    """
    from backend.mctools.client import call_tool, MCTOOLS_ENABLED

    if not MCTOOLS_ENABLED:
        return MCPValidationResult(valid=True, available=False)

    if _is_validation_tripped():
        return MCPValidationResult(valid=True, available=False)

    try:
        payload = json.dumps(_spec_to_validation_content(spec), indent=2)
        result = await call_tool(
            "validateContent",
            {"jsonContentOrBase64ZipContent": payload},
            timeout=MCP_VALIDATION_TIMEOUT,
        )
        text_parts = [
            item.get("text", "")
            for item in result.get("content", [])
            if item.get("type") == "text"
        ]
        errors = _extract_errors(text_parts)
        valid = not result.get("isError") and not errors
        if valid:
            _record_validation_success()
        else:
            _record_validation_failure()
        return MCPValidationResult(
            valid=valid,
            errors=errors,
            raw_content=result.get("content", []),
            available=True,
        )
    except Exception as e:
        log.warning("[mcp_context] validateContent failed: %s", e)
        _record_validation_failure()
        return MCPValidationResult(valid=True, available=False)


def _spec_to_validation_content(spec: dict) -> dict:
    """Convert an internal app spec into the JSON document expected by validateContent."""
    if "minecraft:entity" in spec or "minecraft:item" in spec or "minecraft:block" in spec:
        return spec
    if "pools" in spec or any(k.startswith("minecraft:recipe") for k in spec):
        return spec
    if "header" in spec and "modules" in spec:
        return spec
    return _spec_to_bedrock_entity(spec)


def _spec_to_bedrock_entity(spec: dict) -> dict:
    """Build a minimal Bedrock entity JSON from the app's simplified mob spec."""
    identifier = spec.get("identifier", "custom:mob")
    short_name = spec.get("short_name", identifier.split(":")[-1])
    hp = int(spec.get("hp", 20))
    damage = int(spec.get("damage", 2))
    speed = float(spec.get("speed", 0.25))
    collision_box = spec.get("collision_box", {"width": 1, "height": 1})

    entity = {
        "format_version": "1.16.0",
        "minecraft:entity": {
            "description": {
                "identifier": identifier,
                "is_spawnable": True,
                "is_summonable": True,
                "is_experimental": False,
            },
            "components": {
                "minecraft:type_family": {"family": [short_name, "monster"]},
                "minecraft:health": {"value": hp, "max": hp},
                "minecraft:movement.basic": {},
                "minecraft:jump.static": {},
                "minecraft:movement": {"value": speed},
                "minecraft:attack": {"damage": damage},
                "minecraft:physics": {},
                "minecraft:collision_box": collision_box,
                "minecraft:navigation.walk": {
                    "can_walk": True,
                    "can_pass_doors": True,
                },
                "minecraft:pushable": {
                    "is_pushable": True,
                    "is_pushable_by_piston": True,
                },
                "minecraft:behavior.float": {"priority": 0},
                "minecraft:behavior.hurt_by_target": {"priority": 1},
                "minecraft:behavior.nearest_attackable_target": {
                    "priority": 2,
                    "entity_types": [
                        {
                            "filters": {
                                "test": "is_family",
                                "subject": "other",
                                "value": "player",
                            },
                            "max_dist": 35,
                        }
                    ],
                },
                "minecraft:behavior.melee_attack": {
                    "priority": 3,
                    "speed_multiplier": 1.0,
                },
                "minecraft:behavior.random_stroll": {
                    "priority": 6,
                    "speed_multiplier": 1.0,
                },
                "minecraft:behavior.look_at_player": {
                    "priority": 8,
                    "look_distance": 6.0,
                },
                "minecraft:behavior.random_look_around": {"priority": 9},
            },
        },
    }

    if abs(float(spec.get("scale", 1.0)) - 1.0) > 1e-6:
        entity["minecraft:entity"]["components"]["minecraft:scale"] = {
            "value": float(spec["scale"])
        }

    for key, value in (spec.get("components") or {}).items():
        if value is None:
            entity["minecraft:entity"]["components"].pop(key, None)
        else:
            entity["minecraft:entity"]["components"][key] = value

    return entity


def _extract_errors(text_parts: list[str]) -> list[str]:
    """Parse MCP validation output for actionable error messages.

    Skips info/stats lines (e.g. "invalidCommandSyntaxCount": 0) that contain
    error-like keywords but are just zero-count counters.
    """
    errors = []
    error_indicators = [
        "error", "invalid", "required", "must be", "expected",
        "not allowed", "missing", "failed",
    ]
    # Lines that are just JSON stats with zero counts, not real errors
    stats_patterns = ["count", "size", "counts"]

    for text in text_parts:
        for line in text.splitlines():
            line_stripped = line.strip().rstrip(",")
            if not line_stripped:
                continue

            # Skip JSON key-value lines where the value is 0 or a small number
            # e.g. "invalidCommandSyntaxCount": 0
            if ": 0" in line_stripped or '": 0' in line_stripped:
                continue
            # Skip lines that are just stats counters
            line_lower = line_stripped.lower()
            if any(sp in line_lower for sp in stats_patterns) and '": ' in line_stripped:
                continue

            if any(ind in line_lower for ind in error_indicators):
                errors.append(line_stripped)
    return errors


def is_retryable(errors: list[str]) -> bool:
    """Only retry on structural/schema errors, not cosmetic warnings."""
    retryable_keywords = [
        "required", "invalid", "must be", "expected",
        "not allowed", "missing", "type mismatch",
    ]
    return any(
        any(kw in e.lower() for kw in retryable_keywords)
        for e in errors
    )


# ---------------------------------------------------------------------------
# designModel — geometry + texture generation
# ---------------------------------------------------------------------------

@dataclass
class DesignModelResult:
    """Result from MCP designModel: geometry JSON + texture PNG."""
    geometry: Optional[dict] = None
    texture_b64: str = ""
    preview_b64: str = ""
    available: bool = False
    error: str = ""


MCP_DESIGN_MODEL_TIMEOUT = 30.0


def _geometry_to_design(
    geometry: dict,
    model_id: str,
    prompt: str,
    color_rgb: Optional[list] = None,
    display_name: str = "",
) -> dict:
    """Convert Bedrock geometry JSON into a designModel-compatible design.

    The LLM produces standard Bedrock geometry (format_version, minecraft:geometry,
    bones with cubes). designModel expects a similar but slightly different schema
    with per-face texture hints. We convert and add default face textures based on
    color_rgb (from LLM spec), prompt keywords, or display_name.
    """
    design: dict = {"identifier": model_id, "bones": [], "pixelsPerUnit": 4}

    geo_list = geometry.get("minecraft:geometry", [])
    if not geo_list:
        return design

    geo_def = geo_list[0]
    desc = geo_def.get("description", {})

    # Set visible bounds large enough so Minecraft doesn't cull the entity
    design["visibleBoundsSize"] = [
        desc.get("visible_bounds_width", 4),
        desc.get("visible_bounds_height", 4),
    ]
    design["visibleBoundsOffset"] = desc.get("visible_bounds_offset", [0, 1, 0])

    # Prefer LLM's color_rgb (it understands "rhino" → gray, "dragon" → purple, etc.)
    if color_rgb and isinstance(color_rgb, (list, tuple)) and len(color_rgb) >= 3:
        base_colors = [_rgb_to_hex(color_rgb)]
    else:
        base_colors = _pick_colors_from_prompt(prompt.lower(), display_name.lower())

    # Create slightly darker/lighter variants for visual variety per bone
    darker_colors = [_darken_hex(c, 0.75) for c in base_colors]
    lighter_colors = [_lighten_hex(c, 0.3) for c in base_colors]

    # Bone name patterns for shade variation
    dark_keywords = ("leg", "foot", "arm", "limb", "tail", "hoof")
    light_keywords = ("head", "ear", "horn", "tusk", "snout", "eye")

    bone_idx = 0
    for bone in geo_def.get("bones", []):
        if not bone.get("cubes"):
            # Still include parent-only bones (like "root") so hierarchy is preserved.
            # Give them a tiny transparent cube so MCP doesn't drop them.
            design_bone: dict = {"name": bone["name"]}
            if "parent" in bone:
                design_bone["parent"] = bone["parent"]
            if "pivot" in bone:
                design_bone["pivot"] = bone["pivot"]
            if "rotation" in bone:
                design_bone["rotation"] = bone["rotation"]
            design_bone["cubes"] = [{
                "origin": [0, 0, 0],
                "size": [0, 0, 0],
                "faces": {
                    face: {"background": {"type": "solid", "colors": ["#00000000"]}}
                    for face in ["north", "south", "east", "west", "up", "down"]
                },
            }]
            design["bones"].append(design_bone)
            continue

        design_bone: dict = {"name": bone["name"]}
        if "parent" in bone:
            design_bone["parent"] = bone["parent"]
        if "pivot" in bone:
            design_bone["pivot"] = bone["pivot"]
        if "rotation" in bone:
            design_bone["rotation"] = bone["rotation"]

        # Pick shade based on bone name
        bone_lower = bone["name"].lower()
        if any(kw in bone_lower for kw in dark_keywords):
            colors = darker_colors
        elif any(kw in bone_lower for kw in light_keywords):
            colors = lighter_colors
        else:
            colors = base_colors

        design_cubes = []
        for cube in bone.get("cubes", []):
            design_cube: dict = {
                "origin": cube.get("origin", [0, 0, 0]),
                "size": cube.get("size", [1, 1, 1]),
            }
            if "inflate" in cube:
                design_cube["inflate"] = cube["inflate"]

            # Use deterministic seed per bone for consistent noise
            design_cube["faces"] = {
                face: {
                    "background": {
                        "type": "stipple_noise",
                        "colors": colors,
                        "seed": bone_idx * 6 + fi,
                    }
                }
                for fi, face in enumerate(
                    ["north", "south", "east", "west", "up", "down"]
                )
            }
            design_cubes.append(design_cube)

        design_bone["cubes"] = design_cubes
        design["bones"].append(design_bone)
        bone_idx += 1

    return design


def _darken_hex(hex_color: str, factor: float) -> str:
    """Darken a hex color by a factor (0-1)."""
    hex_color = hex_color.lstrip("#")
    r = int(int(hex_color[0:2], 16) * factor)
    g = int(int(hex_color[2:4], 16) * factor)
    b = int(int(hex_color[4:6], 16) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def _lighten_hex(hex_color: str, factor: float) -> str:
    """Lighten a hex color by a factor (0-1, blends toward white)."""
    hex_color = hex_color.lstrip("#")
    r = int(int(hex_color[0:2], 16) + (255 - int(hex_color[0:2], 16)) * factor)
    g = int(int(hex_color[2:4], 16) + (255 - int(hex_color[2:4], 16)) * factor)
    b = int(int(hex_color[4:6], 16) + (255 - int(hex_color[4:6], 16)) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb_to_hex(rgb: list | tuple) -> str:
    """Convert [R, G, B] (0-255) to hex."""
    if not rgb or len(rgb) < 3:
        return "#808080"
    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _pick_colors_from_prompt(prompt: str, display_name: str = "") -> list[str]:
    """Pick texture colors based on keywords in the prompt or display_name.

    Checks both prompt and display_name so 'Rhino' in the spec still matches.
    """
    color_map = {
        "zombie": ["#4a7a3a", "#3d6630"],
        "skeleton": ["#c8c8c8", "#a0a0a0"],
        "creeper": ["#4caf50", "#388e3c"],
        "spider": ["#3a2a1a", "#2d1f14"],
        "pig": ["#f0a0a0", "#d88888"],
        "cow": ["#6b4226", "#f0f0f0"],
        "sheep": ["#e8e8e8", "#d0d0d0"],
        "chicken": ["#ffffff", "#e8e0d0"],
        "wolf": ["#b0b0b0", "#909090"],
        "dragon": ["#2a0a30", "#4a1a50"],
        "golem": ["#b0b0b0", "#8a8a8a", "#d0ccc0"],
        "robot": ["#707890", "#505868", "#a0b0c0"],
        "ghost": ["#e0e8f0", "#c0c8e0"],
        "slime": ["#7ec850", "#5ca030"],
        "fire": ["#ff6600", "#ff3300", "#ffaa00"],
        "ice": ["#a0d8ef", "#80c0e0", "#c0e8ff"],
        "crystal": ["#b060d0", "#9040b0", "#d090f0"],
        "mushroom": ["#c83030", "#f0f0e0"],
        "stone": ["#808080", "#707070", "#909090"],
        "wood": ["#8b6914", "#a07828"],
        "gold": ["#ffd700", "#daa520"],
        "diamond": ["#4aedd9", "#2cc5b8"],
        "iron": ["#d0d0d0", "#b8b8b8"],
        # Large animals
        "rhino": ["#808080", "#696969", "#a0a0a0"],
        "elephant": ["#8b7355", "#6b5344", "#a08060"],
        "hippo": ["#a08060", "#8b7355", "#6b5344"],
        "bear": ["#5c4033", "#3d2b1f", "#7a5540"],
        "lion": ["#d4a84b", "#c49440", "#e8c080"],
        "tiger": ["#ff8c42", "#e67e30", "#d4a574"],
        # Other creatures
        "unicorn": ["#ffffff", "#e8e0f0", "#d0c8e0"],
        "phoenix": ["#ff6600", "#ff3300", "#ffaa00"],
        "blaze": ["#ffcc00", "#ff9900", "#ff6600"],
        "ghast": ["#f0f0f0", "#e0e0e0", "#ffffff"],
    }
    combined = f"{prompt} {display_name}".lower()
    for keyword, colors in color_map.items():
        if keyword in combined:
            return colors
    return ["#808080", "#707070"]


async def mcp_design_model(
    geometry: dict,
    model_id: str,
    prompt: str,
    usage: str = "entity",
    color_rgb: Optional[list] = None,
    display_name: str = "",
) -> DesignModelResult:
    """Call MCP designModel to generate geometry + texture from a design.

    Takes LLM-generated geometry and a prompt, converts to a designModel-
    compatible design with face textures, and returns the generated PNG.

    color_rgb: Optional [R,G,B] from the LLM spec — used when available for
        accurate colors (LLM understands "rhino" → gray, etc.).
    display_name: Mob display name — used for keyword fallback when color_rgb
        is not provided.
    """
    from backend.mctools.client import call_tool, MCTOOLS_ENABLED

    if not MCTOOLS_ENABLED:
        return DesignModelResult(available=False)

    project_dir = None
    try:
        project_dir = Path(tempfile.mkdtemp(prefix="mcp_design_"))
        design = _geometry_to_design(
            geometry, model_id, prompt,
            color_rgb=color_rgb,
            display_name=display_name,
        )

        log.info("[mcp_context] Calling designModel for %s (project=%s)", model_id, project_dir)
        start = time.time()

        result = await call_tool(
            "designModel",
            {
                "projectPath": str(project_dir),
                "design": design,
                "modelId": model_id,
                "usage": usage,
                "wireTo": False,
            },
            timeout=MCP_DESIGN_MODEL_TIMEOUT,
        )

        elapsed_ms = int((time.time() - start) * 1000)
        log.info("[mcp_context] designModel completed in %dms", elapsed_ms)

        # Extract preview image from the response
        preview_b64 = ""
        for item in result.get("content", []):
            if item.get("type") == "image":
                preview_b64 = item.get("data", "")
                break

        # Read the generated texture PNG from disk.
        # MCP creates a nested resource pack folder inside projectPath,
        # so the texture may be at e.g. projectPath/rp/textures/entity/rhino.png
        # instead of projectPath/textures/entity/rhino.png.  Search by filename.
        texture_b64 = ""
        tex_filename = f"{model_id}.png"
        tex_match = None
        for candidate in project_dir.rglob(tex_filename):
            # Must be under a textures/ directory (not .mct/previews/ etc.)
            if "textures" in candidate.parts and ".mct" not in str(candidate):
                tex_match = candidate
                break
        if tex_match:
            raw = tex_match.read_bytes()
            texture_b64 = f"data:image/png;base64,{base64.b64encode(raw).decode()}"
            log.info("[mcp_context] Read texture from %s (%d bytes)", tex_match, len(raw))
        else:
            log.warning("[mcp_context] Texture %s not found under %s", tex_filename, project_dir)

        # Read geometry JSON from disk (MCP may have modified it).
        # Same nested-folder issue: search by filename.
        out_geometry = geometry
        geo_filename = f"{model_id}.geo.json"
        geo_match = None
        for candidate in project_dir.rglob(geo_filename):
            if ".mct" not in str(candidate):
                geo_match = candidate
                break
        if geo_match:
            try:
                out_geometry = json.loads(geo_match.read_text(encoding="utf-8"))
                log.info("[mcp_context] Read geometry from %s", geo_match)
                # Ensure visible bounds are large enough so Minecraft renders the entity.
                # MCP may default to tiny bounds (1x1) which causes invisible mobs.
                for geo_entry in out_geometry.get("minecraft:geometry", []):
                    d = geo_entry.get("description", {})
                    if d.get("visible_bounds_width", 0) < 4:
                        d["visible_bounds_width"] = 4
                    if d.get("visible_bounds_height", 0) < 4:
                        d["visible_bounds_height"] = 4
                    if "visible_bounds_offset" not in d:
                        d["visible_bounds_offset"] = [0, 1, 0]
            except Exception:
                pass

        return DesignModelResult(
            geometry=out_geometry,
            texture_b64=texture_b64,
            preview_b64=preview_b64,
            available=True,
        )

    except Exception as e:
        log.warning("[mcp_context] designModel failed: %s", e)
        return DesignModelResult(available=False, error=str(e))
    finally:
        if project_dir and project_dir.exists():
            import shutil
            try:
                shutil.rmtree(project_dir, ignore_errors=True)
            except Exception:
                pass


def mcp_design_model_sync(
    geometry: dict,
    model_id: str,
    prompt: str,
    usage: str = "entity",
    color_rgb: Optional[list] = None,
    display_name: str = "",
) -> DesignModelResult:
    """Synchronous wrapper for mcp_design_model."""
    from backend.mctools.client import MCTOOLS_ENABLED
    if not MCTOOLS_ENABLED:
        return DesignModelResult(available=False)
    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                mcp_design_model(
                    geometry, model_id, prompt, usage,
                    color_rgb=color_rgb,
                    display_name=display_name,
                ),
            )
            return future.result(timeout=MCP_DESIGN_MODEL_TIMEOUT + 5)
    except Exception as e:
        log.warning("[mcp_context] Sync designModel failed: %s", e)
        return DesignModelResult(available=False, error=str(e))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def retrieve_context(
    prompt: str,
    category: str,
    current_spec: dict,
) -> MCPContext:
    """Retrieve dynamic MCP context for LLM prompt augmentation.

    Runs schema and template fetches in parallel with a timeout.
    Returns MCPContext with whatever was successfully retrieved.
    Circuit breaker: skips entirely if recent calls have been failing.
    """
    from backend.mctools.client import MCTOOLS_ENABLED

    if not MCTOOLS_ENABLED:
        return MCPContext(available=False)

    if _is_retrieval_tripped():
        remaining = int(_retrieval_tripped_until - time.time())
        log.debug("[mcp_context] Retrieval circuit breaker active (%ds remaining)", remaining)
        return MCPContext(available=False, skipped_reason=f"circuit breaker ({remaining}s)")

    start = time.time()
    source_tools: list[str] = []
    schema_text = ""
    template_text = ""
    failed = False

    try:
        tasks = [
            _fetch_schema_cached(category),
            _fetch_templates(prompt, category),
        ]
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=MCP_RETRIEVAL_TIMEOUT,
        )

        if isinstance(results[0], str) and results[0]:
            schema_text = results[0]
            source_tools.append("getEffectiveContentSchema")
        elif isinstance(results[0], Exception):
            log.warning("[mcp_context] Schema task failed: %s", results[0])

        if isinstance(results[1], str) and results[1]:
            template_text = results[1]
            source_tools.append("getModelTemplates")
        elif isinstance(results[1], Exception):
            log.warning("[mcp_context] Template task failed: %s", results[1])

    except asyncio.TimeoutError:
        log.warning("[mcp_context] Retrieval timed out after %ds", MCP_RETRIEVAL_TIMEOUT)
        failed = True
    except Exception as e:
        log.warning("[mcp_context] Retrieval failed: %s", e)
        failed = True

    elapsed_ms = int((time.time() - start) * 1000)

    if source_tools:
        _record_retrieval_success()
    elif failed:
        _record_retrieval_failure()

    ctx = MCPContext(
        schema_text=schema_text,
        template_text=template_text,
        source_tools=source_tools,
        retrieval_ms=elapsed_ms,
        available=bool(source_tools),
    )

    if source_tools:
        print(f"[mcp_context] Retrieved context in {elapsed_ms}ms "
              f"(sources={source_tools}, schema={len(schema_text)} chars)")
    elif failed:
        print(f"[mcp_context] Retrieval failed in {elapsed_ms}ms (will skip after "
              f"{CIRCUIT_BREAKER_THRESHOLD - _consecutive_retrieval_failures} more failures)")

    return ctx


# ---------------------------------------------------------------------------
# Sync wrapper (for use in sync LLM functions called from async FastAPI)
# ---------------------------------------------------------------------------

def retrieve_context_sync(
    prompt: str,
    category: str,
    current_spec: dict,
) -> Optional[MCPContext]:
    """Synchronous wrapper for async MCP context retrieval.

    Handles the async-sync bridge safely whether called from an async
    context (FastAPI route) or a sync context (tests, CLI).
    """
    from backend.mctools.client import MCTOOLS_ENABLED
    if not MCTOOLS_ENABLED:
        return MCPContext(available=False)
    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                retrieve_context(prompt, category, current_spec),
            )
            return future.result(timeout=MCP_RETRIEVAL_TIMEOUT + 3)
    except Exception as e:
        log.warning("[mcp_context] Sync retrieval failed: %s", e)
        return None


def mcp_validate_sync(spec: dict) -> Optional[MCPValidationResult]:
    """Synchronous wrapper for async MCP validation.

    Currently a no-op passthrough — see mcp_validate() docstring.
    """
    return MCPValidationResult(valid=True, available=False)


def mcp_validate_sync_v2(spec: dict) -> Optional[MCPValidationResult]:
    """Synchronous wrapper for async MCP validation."""
    from backend.mctools.client import MCTOOLS_ENABLED
    if not MCTOOLS_ENABLED:
        return MCPValidationResult(valid=True, available=False)
    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, mcp_validate(spec))
            return future.result(timeout=MCP_VALIDATION_TIMEOUT + 3)
    except Exception as e:
        log.warning("[mcp_context] Sync validation failed: %s", e)
        return MCPValidationResult(valid=True, available=False)


mcp_validate_sync = mcp_validate_sync_v2
