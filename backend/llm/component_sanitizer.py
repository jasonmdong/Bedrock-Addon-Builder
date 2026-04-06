"""Post-generation component sanitizer.

Strips invalid fields from Bedrock entity components using the
vanilla_reference.json schema as ground truth. This catches LLM
hallucinations like "require_angry" or "shoot_sound_event" that
Bedrock silently ignores, causing broken in-game behavior.

Also enforces component dependency and conflict rules.
"""

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load reference once at module init
# ---------------------------------------------------------------------------

_REF_PATH = Path(__file__).resolve().parent.parent / "data" / "vanilla_reference.json"
_REFERENCE: dict = {}

try:
    _REFERENCE = json.loads(_REF_PATH.read_text(encoding="utf-8"))
except Exception as e:
    log.warning("[sanitizer] Could not load vanilla_reference.json: %s", e)

_COMPONENTS: dict = _REFERENCE.get("components", {})
_DEPENDENCIES: dict = _REFERENCE.get("dependencies", {})
_CONFLICTS: dict = _REFERENCE.get("conflicts", {})


# ---------------------------------------------------------------------------
# Field sanitization
# ---------------------------------------------------------------------------

def sanitize_component(name: str, value: dict) -> dict:
    """Remove invalid fields from a single component.

    Returns the cleaned component dict. If the component is not in
    the reference, returns it unchanged (we don't want to break
    components we don't know about).
    """
    if not isinstance(value, dict):
        return value

    ref = _COMPONENTS.get(name)
    if not ref:
        return value  # unknown component, pass through

    valid_fields = ref.get("valid_fields", {})
    if not valid_fields:
        # Component takes no fields (e.g., minecraft:can_fly)
        # Return empty dict if it should be empty
        return {}

    cleaned = {}
    stripped = []
    for key, val in value.items():
        if key in valid_fields:
            cleaned[key] = val
        else:
            stripped.append(key)

    if stripped:
        log.info("[sanitizer] %s: stripped invalid fields %s", name, stripped)

    return cleaned


def sanitize_components(components: dict) -> dict:
    """Sanitize all components in a spec's components dict.

    Returns a new dict with invalid fields stripped from each component.
    """
    if not isinstance(components, dict):
        return components

    result = {}
    for name, value in components.items():
        if value is None:
            continue  # strip null components
        result[name] = sanitize_component(name, value)

    return result


# ---------------------------------------------------------------------------
# Dependency / conflict enforcement
# ---------------------------------------------------------------------------

def check_dependencies(components: dict) -> list[str]:
    """Return list of warning messages for missing dependencies."""
    warnings = []
    for comp_name in components:
        deps = _DEPENDENCIES.get(comp_name, [])
        for dep in deps:
            if dep not in components:
                warnings.append(
                    f"{comp_name} requires {dep} but it's missing"
                )
    return warnings


def check_conflicts(components: dict) -> list[str]:
    """Return list of warning messages for conflicting components."""
    warnings = []
    seen = set()
    for comp_name in components:
        conflicts = _CONFLICTS.get(comp_name, [])
        for conflict in conflicts:
            if conflict in components:
                pair = tuple(sorted([comp_name, conflict]))
                if pair not in seen:
                    seen.add(pair)
                    warnings.append(
                        f"{pair[0]} conflicts with {pair[1]}"
                    )
    return warnings


def resolve_conflicts(components: dict) -> dict:
    """Auto-resolve known conflicts by removing the less specific component.

    Resolution rules (keep → remove):
      - navigation.fly → remove navigation.walk
      - navigation.swim → remove navigation.walk
      - navigation.climb → remove navigation.walk
      - movement.fly → remove movement.basic
      - movement.sway → remove movement.basic
      - behavior.ranged_attack → remove behavior.swell + explode
      - behavior.swell → remove behavior.ranged_attack + shooter
    """
    result = dict(components)

    # Navigation: specialized wins over walk
    for nav in ("minecraft:navigation.fly", "minecraft:navigation.swim", "minecraft:navigation.climb"):
        if nav in result and "minecraft:navigation.walk" in result:
            log.info("[sanitizer] Conflict: %s wins, removing navigation.walk", nav)
            del result["minecraft:navigation.walk"]

    # Movement: specialized wins over basic
    for mov in ("minecraft:movement.fly", "minecraft:movement.sway"):
        if mov in result and "minecraft:movement.basic" in result:
            log.info("[sanitizer] Conflict: %s wins, removing movement.basic", mov)
            del result["minecraft:movement.basic"]

    # Ranged vs swell: last-added wins is ambiguous, so we pick ranged
    # (ranged is more commonly intended; swell is a niche creeper mechanic)
    if "minecraft:behavior.ranged_attack" in result and "minecraft:behavior.swell" in result:
        log.info("[sanitizer] Conflict: ranged_attack wins, removing swell + explode")
        result.pop("minecraft:behavior.swell", None)
        result.pop("minecraft:explode", None)

    return result


# ---------------------------------------------------------------------------
# Projectile validation
# ---------------------------------------------------------------------------

def validate_shooter(components: dict) -> dict:
    """Ensure minecraft:shooter has a valid projectile def."""
    shooter = components.get("minecraft:shooter")
    if not isinstance(shooter, dict):
        return components

    ref = _COMPONENTS.get("minecraft:shooter", {})
    valid_projectiles = ref.get("valid_projectiles", [])

    projectile = shooter.get("def", "")
    if valid_projectiles and projectile and projectile not in valid_projectiles:
        # Try common corrections
        corrections = {
            "minecraft:fireball": "minecraft:small_fireball",
            "fireball": "minecraft:small_fireball",
            "small_fireball": "minecraft:small_fireball",
            "large_fireball": "minecraft:large_fireball",
            "arrow": "minecraft:arrow",
            "snowball": "minecraft:snowball",
        }
        corrected = corrections.get(projectile)
        if corrected:
            log.info("[sanitizer] Corrected shooter projectile: %s → %s", projectile, corrected)
            components = dict(components)
            components["minecraft:shooter"] = dict(shooter, def_=None)
            components["minecraft:shooter"] = {"def": corrected}
        else:
            log.warning("[sanitizer] Unknown projectile: %s (valid: %s)", projectile, valid_projectiles)

    return components


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def auto_inject_dependencies(components: dict) -> dict:
    """Auto-inject well-known required companion components that LLMs forget.

    Handles:
    - minecraft:can_fly for flying mobs
    - minecraft:behavior.ranged_attack for mobs with minecraft:shooter
    - minecraft:fire_immune for mobs shooting fireballs
    """
    result = dict(components)

    # minecraft:can_fly is required whenever fly navigation or movement is used
    if (
        "minecraft:navigation.fly" in result or "minecraft:movement.fly" in result
    ) and "minecraft:can_fly" not in result:
        result["minecraft:can_fly"] = {}
        log.info("[sanitizer] Auto-injected minecraft:can_fly")

    # minecraft:shooter requires minecraft:behavior.ranged_attack to actually fire
    if "minecraft:shooter" in result and "minecraft:behavior.ranged_attack" not in result:
        result["minecraft:behavior.ranged_attack"] = {
            "priority": 3,
            "attack_interval_min": 2.0,
            "attack_interval_max": 5.0,
            "attack_radius": 16.0,
        }
        log.info("[sanitizer] Auto-injected minecraft:behavior.ranged_attack for shooter")

    # Mobs that shoot fireballs should be fire immune
    shooter = result.get("minecraft:shooter")
    if isinstance(shooter, dict):
        proj = shooter.get("def", "")
        if "fireball" in str(proj).lower() and "minecraft:fire_immune" not in result:
            result["minecraft:fire_immune"] = {}
            log.info("[sanitizer] Auto-injected minecraft:fire_immune for fireball shooter")

    # Ranged attackers need a target selector
    if "minecraft:behavior.ranged_attack" in result and "minecraft:behavior.nearest_attackable_target" not in result:
        result["minecraft:behavior.nearest_attackable_target"] = {
            "priority": 1,
            "entity_types": [
                {"filters": {"test": "is_family", "value": "player"}, "max_dist": 32}
            ],
        }
        log.info("[sanitizer] Auto-injected minecraft:behavior.nearest_attackable_target for ranged attacker")

    return result


def sanitize_spec(spec: dict) -> dict:
    """Run the full sanitization pipeline on a mob spec.

    1. Strip null components
    2. Strip invalid fields from each component
    3. Resolve conflicts (navigation, movement, ranged vs swell)
    4. Auto-inject missing required companion components
    5. Validate shooter projectiles
    6. Log any remaining dependency warnings

    Returns the spec with cleaned components. Non-destructive to
    non-component fields.
    """
    if "components" not in spec or not isinstance(spec["components"], dict):
        return spec

    components = spec["components"]

    # Step 1+2: sanitize fields (also strips nulls)
    components = sanitize_components(components)

    # Step 3: resolve conflicts
    components = resolve_conflicts(components)

    # Step 4: auto-inject missing required companions
    components = auto_inject_dependencies(components)

    # Step 5: validate projectiles
    components = validate_shooter(components)

    # Step 6: log any remaining warnings (informational, don't block)
    dep_warnings = check_dependencies(components)
    conflict_warnings = check_conflicts(components)
    for w in dep_warnings:
        log.warning("[sanitizer] Dependency: %s", w)
    for w in conflict_warnings:
        log.warning("[sanitizer] Conflict: %s", w)

    spec["components"] = components
    return spec
