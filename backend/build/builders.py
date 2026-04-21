"""Builders for resource packs and behavior packs."""
import copy
import json
import uuid
from pathlib import Path

from backend.config.settings import DEFAULTS, COLOR_WORDS
from backend.schemas.spec_utils import default_spec, validate_spec


def _write_text(path: Path, content: str):
    """Write text with Unix line endings (LF only). Windows defaults to CRLF
    which can break Minecraft's mcfunction and JSON parsers."""
    path.write_bytes(content.encode("utf-8"))


def _normalize_spec_animation_json(spec: dict) -> None:
    """Ensure spec['animation_json'] is a dict with a real ``animations`` map.

    Specs from the editor sometimes have ``"animations": null`` or omit the key;
    ``setdefault`` alone then leaves a null value and procedural clips never stick.
    """
    anim = spec.get("animation_json")
    if anim is None or not isinstance(anim, dict):
        spec["animation_json"] = {"format_version": "1.8.0", "animations": {}}
        return
    anims = anim.get("animations")
    if not isinstance(anims, dict):
        anim["animations"] = {}
    anim.setdefault("format_version", "1.8.0")


def _sanitize_animations(animation_json: dict) -> None:
    """Fix common LLM animation issues at build time.

    - Removes anim_time_update from walk/run animations (causes jitter
      on custom entities whose pathfinding movement isn't smooth).
    """
    for anim_key, anim_data in animation_json.get("animations", {}).items():
        if not isinstance(anim_data, dict):
            continue
        last_seg = anim_key.rsplit(".", 1)[-1].lower()
        if last_seg in ("walk", "walking", "run", "running"):
            anim_data.pop("anim_time_update", None)


def _collect_geometry_bone_names(geo_data: dict | None) -> set[str]:
    names: set[str] = set()
    if not geo_data or not isinstance(geo_data, dict):
        return names
    for geo_entry in geo_data.get("minecraft:geometry", []):
        for bone in geo_entry.get("bones", []):
            n = bone.get("name")
            if isinstance(n, str) and n:
                names.add(n)
    return names


def _remap_animation_bones_to_geometry(animation_json: dict, geo_data: dict | None) -> None:
    """Retarget animation bone keys to names that exist on the rig.

    LLMs often emit a single ``tail`` bone while the model uses ``tail_base`` /
    ``tail_mid`` / ``tail_tip`` — those keys are ignored in-game and look broken.
    """
    valid = _collect_geometry_bone_names(geo_data)
    if not valid or not animation_json or not isinstance(animation_json, dict):
        return
    anims = animation_json.get("animations")
    if not isinstance(anims, dict) or not anims:
        return

    if "tail" not in valid:
        tail_targets = [b for b in ("tail_base", "tail_mid", "tail_tip") if b in valid]
        if not tail_targets:
            tail_targets = sorted(b for b in valid if b.lower().startswith("tail"))
        tail_to = tail_targets[0] if tail_targets else None
    else:
        tail_to = None

    remapped = False
    for anim_data in anims.values():
        if not isinstance(anim_data, dict):
            continue
        bones = anim_data.get("bones")
        if not isinstance(bones, dict) or "tail" not in bones:
            continue
        if tail_to:
            bones[tail_to] = bones.pop("tail")
            remapped = True
    if remapped and tail_to:
        print(f"[BUILD] Remapped animation bone 'tail' -> '{tail_to}' (geometry mismatch fix)")


def _anim_short_key(anim_key: str, mob_name: str) -> str:
    """Extract short animation key (e.g. 'walk') from a full animation ID.

    Handles mismatches between mob_name and the animation prefix.
    For example, mob_name='my_first_mob' but anim_key='animation.custom_dragon.walk'
    -> returns 'walk' (the last dot-segment).
    """
    # Try exact prefix match first
    prefix = f"animation.{mob_name}."
    if anim_key.startswith(prefix):
        return anim_key[len(prefix):]
    # Fall back to last dot-segment (e.g. animation.custom_dragon.walk -> walk)
    parts = anim_key.split(".")
    if len(parts) >= 3 and parts[0] == "animation":
        return parts[-1]
    return anim_key


def _fix_geometry_uv(geo_data: dict) -> dict:
    """Fix UV overflow in geometry: expand texture_width/texture_height to fit all cubes.

    LLM-generated geometry often has cubes whose box-UV mappings extend beyond
    the declared texture atlas dimensions.  When this happens Minecraft silently
    fails to render those bones, making the mob invisible.  This function
    calculates the minimum atlas size needed and rounds up to a power of two.
    """
    import math
    for geo_entry in geo_data.get("minecraft:geometry", []):
        desc = geo_entry.get("description", {})
        tw = desc.get("texture_width", 64)
        th = desc.get("texture_height", 64)

        max_u = tw
        max_v = th
        for bone in geo_entry.get("bones", []):
            for cube in bone.get("cubes", []):
                uv = cube.get("uv")
                sz = cube.get("size")
                if not uv or not sz or not isinstance(uv, (list, tuple)):
                    continue
                # Per-face UV (dict) doesn't overflow the atlas the same way
                if isinstance(uv, dict):
                    continue
                w, h, d = float(sz[0]), float(sz[1]), float(sz[2])
                u0, v0 = float(uv[0]), float(uv[1])
                # Box UV layout: width = 2*d + 2*w, height = d + h
                needed_u = u0 + 2 * d + 2 * w
                needed_v = v0 + d + h
                max_u = max(max_u, needed_u)
                max_v = max(max_v, needed_v)

        if max_u > tw or max_v > th:
            # Round up to next power of two for clean texture mapping
            new_tw = 1 << math.ceil(math.log2(max(max_u, 1)))
            new_th = 1 << math.ceil(math.log2(max(max_v, 1)))
            new_tw = max(new_tw, 16)
            new_th = max(new_th, 16)
            desc["texture_width"] = new_tw
            desc["texture_height"] = new_th
            print(f"[BUILD] Fixed UV overflow: texture atlas {tw}x{th} -> {new_tw}x{new_th}")
    return geo_data


def _fix_geometry_legs(geo_data: dict) -> dict:
    """Fix LLM-generated geometry where legs overlap with the body or
    extend below Y=0 (underground).

    Common LLM mistakes:
    1. Legs at the same Y as body (invisible inside body)
    2. Legs with negative Y origins (underground in-game)
    In both cases, shift the entire model up so leg bottoms sit at Y=0.
    """
    from backend.llm.texture_gen import _classify_bone

    for geo_entry in geo_data.get("minecraft:geometry", []):
        bones = geo_entry.get("bones", [])
        if not bones:
            continue

        body_bone = None
        body_cube = None
        leg_bones = []

        for bone in bones:
            role = _classify_bone(bone.get("name", ""))
            cubes = bone.get("cubes", [])
            if not cubes:
                continue
            if role == "body" and not body_bone:
                body_bone = bone
                body_cube = cubes[0]
            elif role == "leg":
                leg_bones.append(bone)

        if not leg_bones:
            continue

        leg_origins_y = []
        leg_heights = []
        for lb in leg_bones:
            for cube in lb.get("cubes", []):
                oy = cube.get("origin", [0, 0, 0])[1]
                h = cube.get("size", [0, 0, 0])[1]
                leg_origins_y.append(oy)
                leg_heights.append(h)

        if not leg_origins_y:
            continue

        min_leg_y = min(leg_origins_y)

        # Case 1: Legs go below Y=0 — shift everything up
        if min_leg_y < 0:
            shift = -min_leg_y
            print(f"[BUILD] Fixing underground legs: shifting all bones up by {shift}")
            for bone in bones:
                for cube in bone.get("cubes", []):
                    origin = cube.get("origin", [0, 0, 0])
                    origin[1] += shift
                    cube["origin"] = origin
                pivot = bone.get("pivot", [0, 0, 0])
                pivot[1] += shift
                bone["pivot"] = pivot
            continue

        # Case 2: Legs overlap with body (same Y level)
        if not body_bone or not body_cube:
            continue

        body_origin_y = body_cube.get("origin", [0, 0, 0])[1]
        max_leg_h = max(leg_heights)

        overlap = body_origin_y - min_leg_y
        if overlap >= 0 and overlap < max_leg_h * 0.5:
            shift = max_leg_h - overlap
            if shift <= 0:
                continue

            print(f"[BUILD] Fixing leg overlap: shifting non-leg bones up by {shift}")
            for bone in bones:
                role = _classify_bone(bone.get("name", ""))
                if role == "leg":
                    continue
                for cube in bone.get("cubes", []):
                    origin = cube.get("origin", [0, 0, 0])
                    origin[1] += shift
                    cube["origin"] = origin
                pivot = bone.get("pivot", [0, 0, 0])
                pivot[1] += shift
                bone["pivot"] = pivot

    return geo_data


def _fix_geometry_scale(geo_data: dict) -> dict:
    """Scale up LLM geometry that is too small for Minecraft.

    LLMs sometimes generate geometry in "real-world" scale (e.g., a body
    that is 4x3x2 pixels) instead of Minecraft's expected scale where a
    cow body is about 14x10x8.  This detects when the largest body part
    is unreasonably small and scales the entire model up.
    """
    MIN_BODY_DIMENSION = 6

    for geo_entry in geo_data.get("minecraft:geometry", []):
        bones = geo_entry.get("bones", [])
        if not bones:
            continue

        max_dim = 0
        for bone in bones:
            for cube in bone.get("cubes", []):
                sz = cube.get("size", [0, 0, 0])
                max_dim = max(max_dim, *[abs(s) for s in sz])

        if max_dim < MIN_BODY_DIMENSION and max_dim > 0:
            scale_factor = round(MIN_BODY_DIMENSION / max_dim + 0.5)
            scale_factor = max(2, min(scale_factor, 6))
            print(f"[BUILD] Scaling up undersized geometry by {scale_factor}x "
                  f"(max dimension was {max_dim})")

            for bone in bones:
                for cube in bone.get("cubes", []):
                    origin = cube.get("origin", [0, 0, 0])
                    size = cube.get("size", [0, 0, 0])
                    cube["origin"] = [round(v * scale_factor, 1) for v in origin]
                    cube["size"] = [round(v * scale_factor, 1) for v in size]
                pivot = bone.get("pivot", [0, 0, 0])
                bone["pivot"] = [round(v * scale_factor, 1) for v in pivot]

    return geo_data


def prepare_geometry_for_texture(geo_data: dict) -> dict:
    """Normalize geometry before procedural UV texturing (LLM / viewer path).

    Runs the same scale, leg, and UV-atlas fixes used when building packs so
    ``generate_mob_texture`` aligns with what Minecraft expects.
    """
    if not isinstance(geo_data, dict) or not geo_data.get("minecraft:geometry"):
        return geo_data
    data = copy.deepcopy(geo_data)
    _fix_geometry_scale(data)
    _fix_geometry_legs(data)
    _fix_geometry_uv(data)
    return data


def _has_wing_bones(geo_data: dict | None) -> bool:
    """Check if the geometry contains wing bones."""
    if not geo_data or not isinstance(geo_data, dict):
        return False
    for geo_entry in geo_data.get("minecraft:geometry", []):
        for bone in geo_entry.get("bones", []):
            name = bone.get("name", "").lower()
            if "wing" in name:
                return True
    return False


def _get_wing_bone_names(geo_data: dict) -> list[str]:
    """Return names of wing bones in the geometry."""
    names = []
    for geo_entry in geo_data.get("minecraft:geometry", []):
        for bone in geo_entry.get("bones", []):
            name = bone.get("name", "")
            if "wing" in name.lower():
                names.append(name)
    return names


def _has_fly_components(components: dict | None) -> bool:
    """Check if the entity has fly-related behavior components."""
    if not components:
        return False
    fly_keys = ("minecraft:can_fly", "minecraft:movement.fly",
                "minecraft:navigation.fly", "minecraft:flying_speed")
    return any(k in components for k in fly_keys)


def _ensure_fly_animation(spec: dict) -> None:
    """Auto-generate a fly animation with wing flapping if the mob has wing
    bones but no fly animation.  Modifies spec['animation_json'] in-place."""
    geo = spec.get("geometry_json")
    anim = spec.get("animation_json")

    wing_names = _get_wing_bone_names(geo) if geo else []
    if not wing_names:
        return

    if not anim or not isinstance(anim, dict):
        anim = {"format_version": "1.8.0", "animations": {}}
        spec["animation_json"] = anim

    animations = anim.setdefault("animations", {})

    already_has_fly = any("fly" in k.lower() for k in animations)
    if already_has_fly:
        return

    short_name = spec.get("short_name", "custom_mob")
    fly_key = f"animation.{short_name}.fly"

    bones = {}
    for wname in wing_names:
        wl = wname.lower()
        if "left" in wl:
            bones[wname] = {
                "rotation": {
                    "0.0": [0, 0, -45],
                    "0.5": [0, 0, 15],
                    "1.0": [0, 0, -45],
                }
            }
        elif "right" in wl:
            bones[wname] = {
                "rotation": {
                    "0.0": [0, 0, 45],
                    "0.5": [0, 0, -15],
                    "1.0": [0, 0, 45],
                }
            }
        else:
            bones[wname] = {
                "rotation": {
                    "0.0": [0, 0, -30],
                    "0.5": [0, 0, 30],
                    "1.0": [0, 0, -30],
                }
            }

    bones["body"] = {
        "rotation": {
            "0.0": [2, 0, 0],
            "0.5": [-2, 0, 0],
            "1.0": [2, 0, 0],
        }
    }

    animations[fly_key] = {
        "loop": True,
        "animation_length": 1.0,
        "bones": bones,
    }
    print(f"[BUILD] Auto-generated fly animation '{fly_key}' for wings: {wing_names}")


_LEG_BONE_SUBSTRINGS = (
    "leg", "foreleg", "hindleg", "hind_leg", "fore_leg",
    "limb", "forelimb", "hindlimb", "rearlimb", "backlimb",
    "paw", "foot", "feet", "thigh", "shin", "calf", "hoof", "knee", "ankle",
    "femur", "tibia", "tarsus", "metatars", "digit", "toe", "heel",
    "hind",  # hind_l, hindleg (avoid bare "fore" — matches unrelated names like "forehead")
)
_FIN_BONE_SUBSTRINGS = ("fin", "flipper", "fluke", "paddle")


def _has_leg_bones(geo_data: dict | None) -> bool:
    """True if geometry has leg / paw bones (mob should walk on land)."""
    if not geo_data or not isinstance(geo_data, dict):
        return False
    for geo_entry in geo_data.get("minecraft:geometry", []):
        for bone in geo_entry.get("bones", []):
            name = bone.get("name", "").lower()
            if any(s in name for s in _LEG_BONE_SUBSTRINGS):
                return True
    return False


def _get_leg_bone_names(geo_data: dict | None) -> list[str]:
    names = []
    if not geo_data or not isinstance(geo_data, dict):
        return names
    for geo_entry in geo_data.get("minecraft:geometry", []):
        for bone in geo_entry.get("bones", []):
            n = bone.get("name", "")
            if n and any(s in n.lower() for s in _LEG_BONE_SUBSTRINGS):
                names.append(n)
    return names


def _sort_leg_bones_for_walk(names: list[str]) -> list[str]:
    """Order legs for a diagonal trot: front-left, front-right, back-left, back-right when names allow."""

    def sort_key(nm: str) -> tuple:
        n = nm.lower()
        if any(k in n for k in ("back", "hind", "rear")):
            z = 2
        elif any(k in n for k in ("front", "fore")):
            z = 1
        else:
            z = 0
        if "left" in n:
            x = 1
        elif "right" in n:
            x = 2
        else:
            x = 0
        return (z, x, n)

    return sorted(names, key=sort_key)


def _walk_phase_signs(count: int) -> list[int]:
    """Rotation multipliers per leg index (+/- 1). Standard quadruped diagonal: [1,-1,-1,1]."""
    if count <= 0:
        return []
    if count == 1:
        return [1]
    if count == 2:
        return [1, -1]
    if count == 3:
        return [1, -1, 1]
    if count == 4:
        return [1, -1, -1, 1]
    signs = []
    base = (1, -1, -1, 1)
    for i in range(count):
        signs.append(base[i % 4])
    return signs


def _build_walk_bone_keyframes(leg_names: list[str]) -> dict:
    """Procedural walk: animate every leg bone with diagonal paired phases."""
    sorted_legs = _sort_leg_bones_for_walk(leg_names)
    signs = _walk_phase_signs(len(sorted_legs))
    bones: dict = {}
    for i, lname in enumerate(sorted_legs):
        sgn = signs[i]
        bones[lname] = {
            "rotation": {
                "0.0": [30 * sgn, 0, 0],
                "0.5": [-30 * sgn, 0, 0],
                "1.0": [30 * sgn, 0, 0],
            }
        }
    return bones


def _augment_walk_animation_with_missing_legs(spec: dict) -> None:
    """If a walk/run clip exists but omits hind legs (common LLM output), add them from geometry."""
    geo = spec.get("geometry_json")
    leg_names = _get_leg_bone_names(geo)
    if len(leg_names) < 2:
        return

    anim = spec.get("animation_json")
    if not anim or not isinstance(anim, dict):
        return
    animations = anim.get("animations")
    if not isinstance(animations, dict):
        return

    walk_key = next(
        (
            k
            for k in animations
            if any(x in k.lower() for x in ("walk", "walking", "run", "running"))
        ),
        None,
    )
    if not walk_key:
        return

    wdata = animations.get(walk_key)
    if not isinstance(wdata, dict):
        return
    bones = wdata.setdefault("bones", {})
    if not isinstance(bones, dict):
        return

    sorted_legs = _sort_leg_bones_for_walk(leg_names)
    signs = _walk_phase_signs(len(sorted_legs))
    added = []
    for i, lname in enumerate(sorted_legs):
        if lname in bones:
            continue
        sgn = signs[i]
        bones[lname] = {
            "rotation": {
                "0.0": [30 * sgn, 0, 0],
                "0.5": [-30 * sgn, 0, 0],
                "1.0": [30 * sgn, 0, 0],
            }
        }
        added.append(lname)
    if added:
        print(
            f"[BUILD] Augmented walk clip with missing leg bones for "
            f"{spec.get('short_name', '?')}: {added}"
        )


def _prune_fly_animations_without_wing_bones(spec: dict) -> None:
    """Drop fly/flying clips if geometry has no wing bones (LLM often adds fly for fish)."""
    geo = spec.get("geometry_json")
    if not geo or _has_wing_bones(geo):
        return
    anim = spec.get("animation_json")
    if not anim or not isinstance(anim, dict):
        return
    animations = anim.get("animations")
    if not isinstance(animations, dict):
        return
    to_del = [k for k in animations if "fly" in k.lower() or "flying" in k.lower()]
    for k in to_del:
        del animations[k]
    if to_del:
        print(
            f"[BUILD] Removed wingless fly clip(s) for {spec.get('short_name', '?')}: {to_del}"
        )


def _ensure_walk_animation(spec: dict) -> None:
    """Add a simple walk loop when leg bones exist but animation_json has no walk/run clip."""
    geo = spec.get("geometry_json")
    leg_names = _get_leg_bone_names(geo)
    if not leg_names:
        return

    anim = spec.get("animation_json")
    if not anim or not isinstance(anim, dict):
        anim = {"format_version": "1.8.0", "animations": {}}
        spec["animation_json"] = anim

    animations = anim.setdefault("animations", {})
    if any(
        any(x in k.lower() for x in ("walk", "walking", "run", "running"))
        for k in animations
    ):
        return

    short_name = spec.get("short_name", "custom_mob")
    walk_key = f"animation.{short_name}.walk"
    sorted_legs = _sort_leg_bones_for_walk(leg_names)
    bones = _build_walk_bone_keyframes(sorted_legs)

    animations[walk_key] = {
        "loop": True,
        "animation_length": 1.0,
        "bones": bones,
    }
    print(
        f"[BUILD] Auto-generated walk '{walk_key}' for {len(sorted_legs)} leg(s): "
        f"{sorted_legs[:6]}"
    )


def _ensure_idle_animation(spec: dict) -> None:
    """Add a minimal idle loop when missing — helps client + preview default clip."""
    geo = spec.get("geometry_json")
    anim = spec.get("animation_json")
    if not anim or not isinstance(anim, dict):
        anim = {"format_version": "1.8.0", "animations": {}}
        spec["animation_json"] = anim

    animations = anim.setdefault("animations", {})
    if any("idle" in k.lower() or "stand" in k.lower() for k in animations):
        return

    short_name = spec.get("short_name", "custom_mob")
    idle_key = f"animation.{short_name}.idle"
    bones: dict = {}
    body_b = None
    if geo:
        try:
            first = geo["minecraft:geometry"][0].get("bones", [])
            body_b = next(
                (b.get("name") for b in first if "body" in b.get("name", "").lower()),
                None,
            )
            if not body_b and first:
                body_b = first[0].get("name")
        except (KeyError, IndexError, TypeError):
            pass
    if body_b:
        bones[body_b] = {
            "rotation": {
                "0.0": [0, 0, 0],
                "0.5": [2, 0, 0],
                "1.0": [0, 0, 0],
            }
        }
    if not bones:
        return

    animations[idle_key] = {
        "loop": True,
        "animation_length": 2.0,
        "bones": bones,
    }
    print(f"[BUILD] Auto-generated idle animation '{idle_key}' for preview/bind pose")


def _has_fin_bones(geo_data: dict | None) -> bool:
    """True if geometry looks aquatic (fins / flippers)."""
    if not geo_data or not isinstance(geo_data, dict):
        return False
    for geo_entry in geo_data.get("minecraft:geometry", []):
        for bone in geo_entry.get("bones", []):
            name = bone.get("name", "").lower()
            if any(s in name for s in _FIN_BONE_SUBSTRINGS):
                return True
    return False


def _get_fin_bone_names(geo_data: dict | None) -> list[str]:
    names = []
    if not geo_data or not isinstance(geo_data, dict):
        return names
    for geo_entry in geo_data.get("minecraft:geometry", []):
        for bone in geo_entry.get("bones", []):
            n = bone.get("name", "")
            if n and any(s in n.lower() for s in _FIN_BONE_SUBSTRINGS):
                names.append(n)
    return names


def _ensure_swim_animation(spec: dict) -> None:
    """Add a simple swim loop when fins exist but animation_json has no swim clip."""
    geo = spec.get("geometry_json")
    fin_names = _get_fin_bone_names(geo)
    if not fin_names:
        return

    anim = spec.get("animation_json")
    if not anim or not isinstance(anim, dict):
        anim = {"format_version": "1.8.0", "animations": {}}
        spec["animation_json"] = anim

    animations = anim.setdefault("animations", {})
    if any("swim" in k.lower() for k in animations):
        return

    short_name = spec.get("short_name", "custom_mob")
    swim_key = f"animation.{short_name}.swim"
    bones = {}
    for fname in fin_names:
        bones[fname] = {
            "rotation": {
                "0.0": [0, 0, -20],
                "0.5": [0, 0, 20],
                "1.0": [0, 0, -20],
            }
        }
    if geo:
        try:
            first = geo["minecraft:geometry"][0].get("bones", [])
            body_b = next(
                (b.get("name") for b in first if "body" in b.get("name", "").lower()),
                None,
            )
            if body_b and body_b not in bones:
                bones[body_b] = {
                    "rotation": {
                        "0.0": [2, 0, 0],
                        "0.5": [-2, 0, 0],
                        "1.0": [2, 0, 0],
                    }
                }
        except (KeyError, IndexError, TypeError):
            pass

    animations[swim_key] = {
        "loop": True,
        "animation_length": 1.0,
        "bones": bones,
    }
    print(f"[BUILD] Auto-generated swim animation '{swim_key}' for fins: {fin_names}")


_ANIMATE_ATTACK_KEYS = frozenset({
    "attack", "attacking", "breath", "fire", "fire_breath", "fire_attack",
    "shoot", "bite", "charge", "roar",
})
# Client entity scripts: prefer variable.attack_time / variable.attacking (query.is_attacking is unreliable).
_MOLANG_ATTACK_PLAY = "(variable.attack_time > 0) || (variable.attacking > 0)"

# Microsoft Learn + pig.entity.json: pre_animation runs before scripts.animate. Merging speed signals here
# fixes walk weights when query.modified_move_speed stays ~0 on custom entities (common client issue).
_LOCOMOTION_PRE_ANIM_LINE = (
    "variable.bab_locomotion = math.max(query.modified_move_speed, "
    "math.max(query.is_moving, query.ground_speed));"
)


def _inject_locomotion_pre_animation(scripts: dict) -> None:
    line = _LOCOMOTION_PRE_ANIM_LINE
    pa = scripts.get("pre_animation")
    if isinstance(pa, list):
        rest = [x for x in pa if x != line]
        scripts["pre_animation"] = [line] + rest
    elif pa is None:
        scripts["pre_animation"] = [line]
    else:
        scripts["pre_animation"] = [line, pa]


def _build_scripts_animate_entries(anim_refs: dict, pure_flier: bool = False) -> list:
    """Build ``scripts.animate`` for the client entity.

    Follows `Animations overview` on Microsoft Learn: blend weights are Molang; pig uses
    ``query.modified_move_speed`` for walk. Custom entities often need ``variable.bab_locomotion``
    from ``pre_animation`` (see ``_inject_locomotion_pre_animation``).

    **Winged walkers** (dragon with walk + fly): vanilla-style split uses ``query.is_on_ground`` only.
    Do *not* use a loose ``is_on_ground || low vertical_speed`` mask — that keeps fly weight at 0 while
    hovering (only idle stayed visible). Locomotion is **not** multiplied by ``!attack`` so a stuck
    ``variable.attacking`` cannot silence walk/fly.

    **Pure fliers**: main fly clip as a string; optional clips in the tail loop.
    """

    def _is_ctrl(fid) -> bool:
        return str(fid).startswith("controller.animation.")

    def _walk_short_key() -> str | None:
        for k in ("walk", "walking", "run", "running"):
            if k in anim_refs and not _is_ctrl(anim_refs[k]):
                return k
        return None

    def _fly_short_key() -> str | None:
        for k in ("fly", "flying"):
            if k in anim_refs and not _is_ctrl(anim_refs[k]):
                return k
        return None

    def _has_attack_clip() -> bool:
        return any(
            k in _ANIMATE_ATTACK_KEYS
            for k, v in anim_refs.items() if not _is_ctrl(v)
        )

    walk_k = _walk_short_key()
    fly_k = _fly_short_key()
    has_idle = (
        "idle" in anim_refs
        and not _is_ctrl(anim_refs.get("idle", ""))
    )
    has_fly = fly_k is not None
    winged_walker = has_fly and walk_k is not None and not pure_flier
    atk = _has_attack_clip()
    _NOT_ATK = f"!({_MOLANG_ATTACK_PLAY})"
    # Split locomotion: on-foot vs airborne. Hovering with vertical_speed ~0 still has is_on_ground == 0,
    # so fly must not require vertical motion. Walking uses strict "on ground and calm" so fly + walk
    # do not both go full weight during a hop.
    _ground_locomotion = "(query.is_on_ground && (math.abs(query.vertical_speed) < 0.15))"
    _air_locomotion = "(!query.is_on_ground || (math.abs(query.vertical_speed) >= 0.15))"
    _dry = "(!query.is_in_water)"
    # Walk blend: pig speed + merged client signal (pre_animation).
    _walk_speed = "math.max(query.modified_move_speed, variable.bab_locomotion)"

    animate_list: list = []
    used: set[str] = set()

    # ------------------------------------------------------------------ pure flier (bat, ghast): one main flying clip
    if pure_flier:
        if fly_k:
            animate_list.append(fly_k)
            used.add(fly_k)
        if has_idle:
            used.add("idle")
        if walk_k:
            used.add(walk_k)
        for short_key, full_id in anim_refs.items():
            if _is_ctrl(full_id) or short_key in used:
                continue
            if short_key in ("swim", "swimming"):
                c = "(query.is_in_water)"
                if atk:
                    c = f"({c}) * ({_NOT_ATK})"
                animate_list.append({short_key: c})
            elif short_key in ("slither", "moving"):
                c = f"{_walk_speed} * (!query.is_in_water)"
                if atk:
                    c = f"({c}) * ({_NOT_ATK})"
                animate_list.append({short_key: c})
            elif short_key in _ANIMATE_ATTACK_KEYS:
                animate_list.append({short_key: _MOLANG_ATTACK_PLAY})
            else:
                animate_list.append(short_key)
        return animate_list

    # ------------------------------------------------------------------ winged walker: ground = idle + walk, air = fly (Learn: blend expressions)
    if winged_walker:
        if has_idle:
            animate_list.append({"idle": f"({_ground_locomotion}) * ({_dry})"})
            used.add("idle")
        if walk_k:
            animate_list.append({
                walk_k: f"({_walk_speed}) * ({_ground_locomotion}) * ({_dry})",
            })
            used.add(walk_k)
        if fly_k:
            animate_list.append({
                fly_k: f"({_air_locomotion}) * ({_dry})",
            })
            used.add(fly_k)
    # ------------------------------------------------------------------ flier without walk
    elif has_fly and walk_k is None:
        if has_idle:
            animate_list.append({"idle": f"({_ground_locomotion}) * ({_dry})"})
            used.add("idle")
        if fly_k:
            animate_list.append({fly_k: f"({_air_locomotion}) * ({_dry})"})
            used.add(fly_k)
    # ------------------------------------------------------------------ land-only (pig / cow pattern)
    else:
        if has_idle:
            animate_list.append("idle")
            used.add("idle")
        if walk_k:
            animate_list.append({walk_k: _walk_speed})
            used.add(walk_k)

    for short_key, full_id in anim_refs.items():
        if _is_ctrl(full_id) or short_key in used:
            continue
        if short_key in ("walk", "walking", "run", "running", "fly", "flying", "idle"):
            continue
        if short_key in ("swim", "swimming"):
            c = "(query.is_in_water)"
            if atk:
                c = f"({c}) * ({_NOT_ATK})"
            animate_list.append({short_key: c})
        elif short_key in _ANIMATE_ATTACK_KEYS:
            animate_list.append({short_key: _MOLANG_ATTACK_PLAY})
        else:
            animate_list.append(short_key)

    return animate_list


def _strip_fly_ai_for_winged_walker(comps: dict) -> None:
    """Remove active fly AI so winged walkers (dragons etc.) use walk + gravity.

    We keep minecraft:can_fly so the mob doesn't take fall damage when its
    wings push it briefly airborne, but strip the movement/navigation components
    that would make it hover or path-find through the air.
    """
    comps.pop("minecraft:movement.fly", None)
    comps.pop("minecraft:navigation.fly", None)
    comps.pop("minecraft:flying_speed", None)
    comps.pop("minecraft:behavior.random_fly", None)
    # Retain can_fly so the mob is immune to fall damage (wings + gravity = safe landing)
    comps.setdefault("minecraft:can_fly", {})
    comps.setdefault("minecraft:movement.basic", {})
    comps.setdefault(
        "minecraft:navigation.walk",
        {"can_walk": True, "can_pass_doors": True},
    )
    comps.setdefault("minecraft:behavior.float", {"priority": 0})


# Cache for fetched vanilla geometry (avoids re-downloading during the same process)
_vanilla_geo_cache: dict[str, dict | None] = {}


def _fetch_vanilla_geometry(geometry_ref: str) -> dict | None:
    """Fetch vanilla geometry JSON from Mojang's bedrock-samples repo.

    Given a geometry reference like 'geometry.chicken', extracts 'chicken'
    and downloads the .geo.json from GitHub. Returns the normalized geometry
    dict or None if not found.
    """
    import urllib.request
    import urllib.error

    # Extract mob name from geometry ref: "geometry.chicken" -> "chicken"
    parts = geometry_ref.split(".")
    if len(parts) < 2:
        return None
    mob_name = parts[1].lower()  # e.g. "chicken", "cow", "zombie"

    if mob_name in _vanilla_geo_cache:
        return _vanilla_geo_cache[mob_name]

    base_url = "https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity"
    candidates = [
        f"{mob_name}.geo.json",
        f"{mob_name}_v2.geo.json",
        f"{mob_name}_v1.geo.json",
    ]

    for filename in candidates:
        url = f"{base_url}/{filename}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BedrockAddonBuilder/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # Normalize old-format geometry to modern format
                if "minecraft:geometry" not in data:
                    # Old format: {"geometry.mob": {...}} -> {"minecraft:geometry": [...]}
                    geo_entries = []
                    for key, val in data.items():
                        if key.startswith("geometry.") and isinstance(val, dict):
                            entry = dict(val)
                            desc = entry.setdefault("description", {})
                            desc.setdefault("identifier", key)
                            if "texturewidth" in entry:
                                desc.setdefault("texture_width", entry.pop("texturewidth"))
                            if "textureheight" in entry:
                                desc.setdefault("texture_height", entry.pop("textureheight"))
                            if "visible_bounds_width" in entry:
                                desc.setdefault("visible_bounds_width", entry.pop("visible_bounds_width"))
                            if "visible_bounds_height" in entry:
                                desc.setdefault("visible_bounds_height", entry.pop("visible_bounds_height"))
                            if "visible_bounds_offset" in entry:
                                desc.setdefault("visible_bounds_offset", entry.pop("visible_bounds_offset"))
                            geo_entries.append(entry)
                    if geo_entries:
                        data = {"format_version": "1.12.0", "minecraft:geometry": geo_entries}
                    else:
                        continue

                _vanilla_geo_cache[mob_name] = data
                print(f"[GEOMETRY] Fetched vanilla geometry '{filename}' for '{geometry_ref}'")
                return data
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as e:
            continue

    print(f"[GEOMETRY] Could not fetch vanilla geometry for '{geometry_ref}'")
    _vanilla_geo_cache[mob_name] = None
    return None


def make_uuid() -> str:
    """Generate a UUID string."""
    return str(uuid.uuid4())


def make_png_rgba(width, height, r, g, b, a=255) -> bytes:
    """Generate a simple solid-color PNG image."""
    import struct
    import binascii
    import zlib

    sig = b'\x89PNG\r\n\x1a\n'

    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", binascii.crc32(name + data) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row = bytes([r, g, b, a]) * width
    raw = b''.join([b'\x00' + row for _ in range(height)])
    comp = zlib.compress(raw, level=9)
    return sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', comp) + chunk(b'IEND', b'')


def write_tga(path: Path, width, height, r, g, b, a=255):
    """Write an uncompressed BGRA 32-bit TGA file."""
    import struct
    header = struct.pack("<BBB5sHHHHBB", 0, 0, 2, bytes(5), 0, 0, width, height, 32, 0x28)
    pixel = bytes([b, g, r, a])
    raw = pixel * (width * height)
    path.write_bytes(header + raw)


def safe_json_load(path: Path):
    """Safely load JSON, returning None on error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def ensure_min_engine(manifest: dict, engine_min):
    """Ensure manifest has min_engine_version set."""
    manifest.setdefault("format_version", 2)
    manifest.setdefault("header", {})
    manifest["header"].setdefault("min_engine_version", engine_min)


def _manifest_version(manifest: dict) -> list:
    """Extract version from manifest header."""
    return manifest.get("header", {}).get("version") or [1, 0, 0]


def patch_resource_pack(res_root: Path, specs: list[dict], textures_dir: Path = None):
    """Patch a resource pack with custom mob textures, entities, and manifests."""
    import shutil
    ent_dir = res_root / "entity"
    ent_dir.mkdir(parents=True, exist_ok=True)
    
    geo_dir = res_root / "models" / "entity"
    geo_dir.mkdir(parents=True, exist_ok=True)

    texts_dir = res_root / "texts"
    texts_dir.mkdir(parents=True, exist_ok=True)
    lang_file = texts_dir / "en_US.lang"
    lang_lines = []

    # Explicitly register spawn egg icons for better compatibility
    tex_dir = res_root / "textures"
    tex_dir.mkdir(parents=True, exist_ok=True)
    item_tex_file = tex_dir / "item_texture.json"
    item_texture = {
        "resource_pack_name": "custom_addon",
        "texture_name": "atlas.items",
        "texture_data": {}
    }

    # Use the vanilla built-in controller.render.default — it already maps
    # Geometry.default, Material.default, and Texture.default which is all we need.
    # Writing a custom render controller file was unreliable (pack load order issues).

    first_png = None

    for spec in specs:
        client_file = ent_dir / f"{spec['short_name']}.entity.json"
        
        # Handle custom geometry
        actual_geometry = spec.get("geometry", DEFAULTS["geometry"])
        actual_rc = spec.get("render_controller", DEFAULTS["render_controller"])
        
        custom_geo = spec.get("geometry_json")
        has_custom_geo = (custom_geo and isinstance(custom_geo, dict)
                          and "minecraft:geometry" in custom_geo)

        if has_custom_geo:
            # Deep-copy to avoid mutating the original spec dict
            import copy
            custom_geo = copy.deepcopy(custom_geo)

            # Ensure the geometry has a unique identifier based on the mob name.
            # Keep only the first geometry entry to avoid identifier conflicts
            # (some Mojang files contain multiple versions of the same geometry).
            unique_geo_id = f"geometry.{spec['short_name']}.custom"
            try:
                custom_geo["minecraft:geometry"] = [custom_geo["minecraft:geometry"][0]]
                geo_desc = custom_geo["minecraft:geometry"][0]["description"]
                geo_desc["identifier"] = unique_geo_id
                # Ensure visible bounds exist — without them Minecraft culls
                # the entity and it appears completely invisible in-game.
                cbox = spec.get("collision_box", {})
                cbox_w = float(cbox.get("width", 1))
                cbox_h = float(cbox.get("height", 1))
                scale = float(spec.get("scale", 1.0))
                if "visible_bounds_width" not in geo_desc:
                    geo_desc["visible_bounds_width"] = max(cbox_w * scale + 1, 4)
                if "visible_bounds_height" not in geo_desc:
                    geo_desc["visible_bounds_height"] = max(cbox_h * scale + 1, 4)
                if "visible_bounds_offset" not in geo_desc:
                    geo_desc["visible_bounds_offset"] = [0, cbox_h * scale / 2, 0]
                actual_geometry = unique_geo_id
                actual_rc = "controller.render.default"
            except (KeyError, IndexError):
                pass
                
            custom_geo = _fix_geometry_scale(custom_geo)
            custom_geo = _fix_geometry_uv(custom_geo)
            custom_geo = _fix_geometry_legs(custom_geo)
            geo_file = geo_dir / f"{spec['short_name']}.geo.json"
            _write_text(geo_file, json.dumps(custom_geo, indent=2))

        elif actual_geometry and actual_geometry.startswith("geometry."):
            # No custom geometry_json — fetch the vanilla geometry from Mojang's
            # repo so the .geo.json file is included in the pack.  Without it
            # Minecraft can't resolve the geometry ID and the mob is invisible.
            vanilla_geo = _fetch_vanilla_geometry(actual_geometry)
            if vanilla_geo:
                import copy
                vanilla_geo = copy.deepcopy(vanilla_geo)
                unique_geo_id = f"geometry.{spec['short_name']}.custom"
                try:
                    # Use only the first geometry entry and rename its identifier
                    vanilla_geo["minecraft:geometry"] = [vanilla_geo["minecraft:geometry"][0]]
                    geo_desc = vanilla_geo["minecraft:geometry"][0]["description"]
                    geo_desc["identifier"] = unique_geo_id
                    # Ensure visible bounds
                    if "visible_bounds_width" not in geo_desc:
                        geo_desc["visible_bounds_width"] = 4
                    if "visible_bounds_height" not in geo_desc:
                        geo_desc["visible_bounds_height"] = 4
                    if "visible_bounds_offset" not in geo_desc:
                        geo_desc["visible_bounds_offset"] = [0, 1, 0]
                    actual_geometry = unique_geo_id
                    actual_rc = "controller.render.default"
                except (KeyError, IndexError):
                    pass
                geo_file = geo_dir / f"{spec['short_name']}.geo.json"
                _write_text(geo_file, json.dumps(vanilla_geo, indent=2))
                print(f"[BUILD] Included vanilla geometry for {spec['short_name']}")
        
        mob_textures_dir = res_root / "textures" / "entity"
        mob_textures_dir.mkdir(parents=True, exist_ok=True)

        png_path = mob_textures_dir / f"{spec['short_name']}.png"

        # Try to copy texture from client-provided textures_dir first
        if textures_dir:
            client_texture = textures_dir / f"{spec['short_name']}.png"
            if client_texture.exists():
                shutil.copyfile(client_texture, png_path)
        
        # Fallback: try server-side SPECS_DIR
        if not png_path.exists():
            from backend.config.settings import SPECS_DIR
            persistent_png = SPECS_DIR / f"{spec['short_name']}.png"
            if persistent_png.exists():
                shutil.copyfile(persistent_png, png_path)

        if not png_path.exists():
            # Use the UV-fixed geometry (written to disk) so the texture
            # dimensions match the actual atlas size the game will use.
            geo_for_tex = None
            written_geo = geo_dir / f"{spec['short_name']}.geo.json"
            if written_geo.exists():
                try:
                    geo_for_tex = json.loads(written_geo.read_bytes())
                except Exception:
                    geo_for_tex = None
            if not geo_for_tex:
                geo_for_tex = spec.get("geometry_json")

            procedural_ok = False
            if geo_for_tex and isinstance(geo_for_tex, dict) and geo_for_tex.get("minecraft:geometry"):
                try:
                    from backend.llm.texture_gen import generate_mob_texture
                    import base64 as _b64
                    tex_b64 = generate_mob_texture(
                        geometry_json=geo_for_tex,
                        display_name=spec.get("display_name", ""),
                        color_rgb=spec.get("color_rgb"),
                        texture_hint=spec.get("texture_hint", ""),
                        short_name=spec.get("short_name", "custom_mob"),
                    )
                    if tex_b64 and "," in tex_b64:
                        raw = _b64.b64decode(tex_b64.split(",", 1)[1])
                        png_path.write_bytes(raw)
                        procedural_ok = True
                        print(f"[BUILD] Procedural texture for {spec['short_name']}")
                except Exception as tex_err:
                    print(f"[BUILD] Procedural texture failed: {tex_err}")

            if not procedural_ok:
                col = spec.get("color_rgb", COLOR_WORDS.get("red"))
                tex_w, tex_h = 64, 64
                if geo_for_tex:
                    try:
                        desc = geo_for_tex["minecraft:geometry"][0]["description"]
                        tex_w = int(desc.get("texture_width", 64))
                        tex_h = int(desc.get("texture_height", 64))
                    except (IndexError, KeyError, TypeError, ValueError):
                        pass
                png = make_png_rgba(tex_w, tex_h, *col, 255)
                png_path.write_bytes(png)

        if not first_png:
            first_png = png_path


        scale = float(spec.get("scale", 1.0))
        client_desc = {
            "identifier": spec["identifier"],
            "materials": {"default": "entity_alphatest"},
            "textures": {"default": f"textures/entity/{spec['short_name']}"},
            "geometry": {"default": actual_geometry},
            "render_controllers": [actual_rc],
            "spawn_egg": {
                "base_color": spec.get("egg_base", DEFAULTS["egg_base"]),
                "overlay_color": spec.get("egg_overlay", DEFAULTS["egg_overlay"])
            }
        }
        # Do not set description.min_engine_version here: it must be a *string* (e.g. "1.16.0"),
        # not a manifest-style [major, minor, patch] array. Wrong type or a value higher than
        # the resource pack's engine version causes the client definition to be skipped → invisible mob.

        # Animation fallbacks: prune impossible fly, then ensure clips from bones
        _normalize_spec_animation_json(spec)
        _prune_fly_animations_without_wing_bones(spec)
        _ensure_fly_animation(spec)
        _ensure_swim_animation(spec)
        _ensure_walk_animation(spec)
        _ensure_idle_animation(spec)
        _augment_walk_animation_with_missing_legs(spec)

        # Wire animation.json and animation_controllers.json into client entity
        animation_json = spec.get("animation_json")
        animation_controller_json = spec.get("animation_controller_json")
        short = spec["short_name"]

        has_controller = (
            animation_controller_json
            and isinstance(animation_controller_json, dict)
            and animation_controller_json.get("animation_controllers")
        )

        anim_refs = {}
        _anim_map = (
            animation_json.get("animations")
            if isinstance(animation_json, dict)
            else None
        )
        if animation_json and isinstance(animation_json, dict) and isinstance(_anim_map, dict) and _anim_map:
            import copy
            animation_json = copy.deepcopy(animation_json)
            _remap_animation_bones_to_geometry(animation_json, spec.get("geometry_json"))
            _sanitize_animations(animation_json)
            anim_dir = res_root / "animations"
            anim_dir.mkdir(parents=True, exist_ok=True)
            _write_text(anim_dir / f"{short}.animation.json", json.dumps(animation_json, indent=2))
            print(f"[BUILD] Wrote animation.json for {short}")

            for anim_key in animation_json["animations"]:
                short_key = _anim_short_key(anim_key, short)
                anim_refs[short_key] = anim_key

        if has_controller:
            # Remap controller animation references from full IDs to short names
            if anim_refs:
                import copy
                remapped_ctrl = copy.deepcopy(animation_controller_json)
                reverse = {v: k for k, v in anim_refs.items()}
                for controller in remapped_ctrl.get("animation_controllers", {}).values():
                    for state in controller.get("states", {}).values():
                        anims = state.get("animations")
                        if not isinstance(anims, list):
                            continue
                        state["animations"] = [
                            reverse.get(e, e) if isinstance(e, str)
                            else {reverse.get(k, k): v for k, v in e.items()} if isinstance(e, dict)
                            else e
                            for e in anims
                        ]
                animation_controller_json = remapped_ctrl

            ac_dir = res_root / "animation_controllers"
            ac_dir.mkdir(parents=True, exist_ok=True)
            _write_text(ac_dir / f"{short}.animation_controllers.json", json.dumps(animation_controller_json, indent=2))
            print(f"[BUILD] Wrote animation_controllers.json for {short}")

            # Do NOT add controllers to anim_refs — adding them to entity.json
            # animations dict causes Bedrock to auto-initialize them, which conflicts
            # with direct scripts.animate entries and silences all animations.

        if anim_refs:
            client_desc["animations"] = anim_refs

            # Detect pure flier from geometry + animations — patch_resource_pack runs before
            # patch_behavior_pack so fly components may not be in spec["components"] yet.
            # Use fly animation presence as additional signal (LLM adds fly anim before can_fly).
            _geo = spec.get("geometry_json")
            _comps = spec.get("components", {})
            _anim_json = spec.get("animation_json")
            _has_fly_anim_rp = (
                _anim_json and isinstance(_anim_json, dict)
                and any("fly" in k for k in _anim_json.get("animations", {}))
            )
            _explicit_fly = _has_fly_components(_comps) or bool(_has_fly_anim_rp)
            _has_legs = _has_leg_bones(_geo)
            _has_wings = _has_wing_bones(_geo)
            # Any mob with leg bones is a winged walker, not a pure flier — even if it
            # has a fly animation.  Pure fliers (bats, parrots, ghasts) have no leg bones.
            _is_pure_flier = (_explicit_fly or _has_wings) and not _has_legs
            animate_list = _build_scripts_animate_entries(anim_refs, pure_flier=_is_pure_flier)
            if animate_list:
                scr = client_desc.setdefault("scripts", {})
                scr["animate"] = animate_list
                _inject_locomotion_pre_animation(scr)

        client = {
            # 1.20.0 matches current pack/manifest targets; pig still uses 1.10.0 but both are valid.
            "format_version": "1.20.0",
            "minecraft:client_entity": {
                "description": client_desc
            }
        }
        if abs(scale - 1.0) > 1e-6:
            client["minecraft:client_entity"]["description"].setdefault("scripts", {})["scale"] = str(scale)
        _write_text(client_file, json.dumps(client, indent=2))

        # Add names to lang file
        display_name = spec.get("display_name", spec["short_name"].capitalize())
        lang_lines.append(f"entity.{spec['identifier']}.name={display_name}")
        lang_lines.append(f"item.spawn_egg.entity.{spec['identifier']}.name=Spawn {display_name}")

        # Map the spawn egg texture to the entity icon (optional but good)
        item_texture["texture_data"][f"spawn_egg_{spec['short_name']}"] = {
            "textures": f"textures/entity/{spec['short_name']}"
        }

    if lang_lines:
        _write_text(lang_file, "\n".join(lang_lines) + "\n")

    if item_texture["texture_data"]:
        _write_text(item_tex_file, json.dumps(item_texture, indent=2))

    # Use the first spec for the main manifest info
    main_spec = specs[0] if specs else validate_spec(default_spec())

    man = res_root / "manifest.json"
    if man.exists():
        manifest = safe_json_load(man) or {}
    else:
        manifest = {"format_version": 2, "header": {}, "modules": []}
    manifest["header"]["description"] = f"{main_spec['display_name']} Resources"
    manifest["header"]["name"] = f"{main_spec['display_name']} Resources"
    manifest["header"]["uuid"] = make_uuid()
    manifest["header"]["version"] = [1, 0, 0]
    ensure_min_engine(manifest, [1, 16, 0])
    manifest["modules"] = [{
        "description": "resources",
        "type": "resources",
        "uuid": make_uuid(),
        "version": [1, 0, 0]
    }]
    try:
        if first_png:
            (res_root / "pack_icon.png").write_bytes(first_png.read_bytes())
    except Exception:
        pass
    _write_text(man, json.dumps(manifest, indent=2))
    return manifest


def _generate_loot_table(spec: dict) -> dict:
    """Generate a Bedrock loot table JSON from the mob spec.

    Reads ``loot_drops`` from the spec. Each drop uses MCP-compatible format:
      {"item": "minecraft:diamond", "count_min": 1, "count_max": 3, "chance": 1.0}

    Falls back to bones if no loot_drops are specified.
    """
    # Common shorthand → full Bedrock item ID
    _ITEM_MAP = {
        "diamond": "minecraft:diamond", "diamonds": "minecraft:diamond",
        "gold": "minecraft:gold_ingot", "gold_ingot": "minecraft:gold_ingot",
        "iron": "minecraft:iron_ingot", "iron_ingot": "minecraft:iron_ingot",
        "emerald": "minecraft:emerald", "emeralds": "minecraft:emerald",
        "bone": "minecraft:bone", "bones": "minecraft:bone",
        "leather": "minecraft:leather", "string": "minecraft:string",
        "feather": "minecraft:feather", "gunpowder": "minecraft:gunpowder",
        "blaze_rod": "minecraft:blaze_rod", "ender_pearl": "minecraft:ender_pearl",
        "rotten_flesh": "minecraft:rotten_flesh", "spider_eye": "minecraft:spider_eye",
        "nether_star": "minecraft:nether_star", "coal": "minecraft:coal",
        "redstone": "minecraft:redstone", "arrow": "minecraft:arrow",
        "fire_charge": "minecraft:fire_charge", "magma_cream": "minecraft:magma_cream",
        "ghast_tear": "minecraft:ghast_tear", "egg": "minecraft:egg",
    }

    def _resolve_item(name: str) -> str:
        key = name.lower().strip()
        if key in _ITEM_MAP:
            return _ITEM_MAP[key]
        if ":" in key:
            return key
        return f"minecraft:{key.replace(' ', '_')}"

    loot_drops = spec.get("loot_drops", [])
    if not isinstance(loot_drops, list) or not loot_drops:
        # Default: drop bones
        loot_drops = [{"item": "minecraft:bone", "count_min": 1, "count_max": 2, "chance": 1.0}]

    # Each drop becomes its own pool (matches MCP's _build_loot_table format)
    pools = []
    for drop in loot_drops:
        if isinstance(drop, str):
            drop = {"item": drop, "count_min": 1, "count_max": 3, "chance": 1.0}

        item = _resolve_item(drop.get("item", "minecraft:bone"))
        count_min = int(drop.get("count_min", drop.get("min", 1)))
        count_max = int(drop.get("count_max", drop.get("max", 1)))
        chance = float(drop.get("chance", 1.0))

        entry = {"type": "item", "name": item, "weight": 1}
        if count_max > 1:
            entry["functions"] = [
                {"function": "set_count", "count": {"min": count_min, "max": count_max}}
            ]

        pool = {"rolls": 1, "entries": [entry]}
        if chance < 1.0:
            pool["conditions"] = [
                {"condition": "random_chance", "chance": chance}
            ]
        pools.append(pool)

    return {"pools": pools}


def patch_behavior_pack(beh_root: Path, specs: list[dict]):
    """Patch a behavior pack with custom mob entities and manifests."""
    ent_dir = beh_root / "entities"
    ent_dir.mkdir(parents=True, exist_ok=True)

    texts_dir = beh_root / "texts"
    texts_dir.mkdir(parents=True, exist_ok=True)
    lang_file = texts_dir / "en_US.lang"
    lang_lines = []

    for spec in specs:
        ent_file = ent_dir / f"{spec['short_name']}.json"

        # Add names to lang file for behavior pack too (helps with some registries)
        display_name = spec.get("display_name", spec["short_name"].capitalize())
        lang_lines.append(f"entity.{spec['identifier']}.name={display_name}")

        # --- Hostile, pursuit-oriented mob ---
        entity = {
            "format_version": "1.16.0",
            "minecraft:entity": {
                "description": {
                    "identifier": spec["identifier"],
                    "is_spawnable": True,
                    "is_summonable": True,
                    "is_experimental": False
                },
                "components": {
                    "minecraft:type_family": {"family": [spec["short_name"], "monster"]},
                    "minecraft:health": {"value": int(spec["hp"]), "max": int(spec["hp"])},
                    "minecraft:movement.basic": {},
                    "minecraft:jump.static": {},
                    "minecraft:movement": {"value": float(spec.get("speed", 0.30))},
                    "minecraft:attack": {"damage": int(spec["damage"])},
                    "minecraft:physics": {},
                    "minecraft:collision_box": spec["collision_box"],
                    "minecraft:navigation.walk": {
                        "can_walk": True,
                        "can_pass_doors": True
                    },
                    "minecraft:pushable": {"is_pushable": True, "is_pushable_by_piston": True},
                    "minecraft:behavior.float": {"priority": 0},
                    "minecraft:behavior.hurt_by_target": {"priority": 1},
                    "minecraft:behavior.nearest_attackable_target": {
                        "priority": 2,
                        "entity_types": [
                            {
                                "filters": {
                                    "test": "is_family",
                                    "subject": "other",
                                    "value": "player"
                                },
                                "max_dist": 35
                            }
                        ]
                    },
                    "minecraft:behavior.melee_attack": {
                        "priority": 3,
                        "speed_multiplier": 1.0
                    },
                    "minecraft:behavior.look_at_player": {"priority": 8, "look_distance": 6.0},
                    "minecraft:behavior.random_look_around": {"priority": 9},
                    "minecraft:behavior.random_stroll": {"priority": 6, "speed_multiplier": 1.0}
                }
            }
        }

        # Apply minecraft:scale from spec (elephants should be large, mice small)
        scale = float(spec.get("scale", 1.0))
        if abs(scale - 1.0) > 1e-6:
            entity["minecraft:entity"]["components"]["minecraft:scale"] = {"value": scale}

        # Merge custom components from spec
        custom_components = spec.get("components", {})
        if custom_components:
            for k, v in custom_components.items():
                if v is None:
                    if k in entity["minecraft:entity"]["components"]:
                        del entity["minecraft:entity"]["components"][k]
                else:
                    entity["minecraft:entity"]["components"][k] = v

        comps = entity["minecraft:entity"]["components"]

        # Ensure targeting filter has required "subject" field
        _nat = comps.get("minecraft:behavior.nearest_attackable_target", {})
        for _et in _nat.get("entity_types", []):
            _f = _et.get("filters", {})
            if _f.get("test") == "is_family" and "subject" not in _f:
                _f["subject"] = "other"

        # If mob has ranged attack (shooter), remove melee_attack so it
        # actually fires projectiles instead of always running up to melee.
        if "minecraft:shooter" in comps and "minecraft:behavior.ranged_attack" in comps:
            comps.pop("minecraft:behavior.melee_attack", None)

        # Normalize shooter projectile to minecraft:small_fireball (blaze-style)
        # which works reliably for custom entities. Other fireball types often
        # silently fail to spawn.
        if "minecraft:shooter" in comps:
            shooter = comps["minecraft:shooter"]
            proj = shooter.get("def", "")
            if proj in ("minecraft:fireball", "minecraft:dragon_fireball",
                        "minecraft:large_fireball"):
                shooter["def"] = "minecraft:small_fireball"

        # Strip invalid ranged_attack params the LLM may hallucinate.
        # Only keep Bedrock-valid keys to prevent silent component failure.
        if "minecraft:behavior.ranged_attack" in comps:
            ra = comps["minecraft:behavior.ranged_attack"]
            valid_ra_keys = {
                "priority", "speed_multiplier", "attack_interval_min",
                "attack_interval_max", "attack_radius", "attack_radius_min",
                "burst_shots", "burst_interval", "charge_charged_trigger",
                "charge_shoot_trigger", "x_max_rotation", "y_max_head_rotation",
            }
            bad_keys = [k for k in ra if k not in valid_ra_keys]
            for k in bad_keys:
                del ra[k]
            # Ensure valid defaults
            ra.setdefault("priority", 3)
            ra.setdefault("attack_interval_min", 3.0)
            ra.setdefault("attack_interval_max", 5.0)
            ra.setdefault("attack_radius", 16.0)

        # Fly AI only for legless fliers. Winged walkers (dragons, etc.) keep walk
        # navigation — otherwise every winged mob loses ground movement and client
        # fly clips dominate (query.is_on_ground is often false while hovering).
        _geo = spec.get("geometry_json")
        _anim_json = spec.get("animation_json")
        _has_fly_anim = (
            _anim_json and isinstance(_anim_json, dict)
            and any("fly" in k for k in _anim_json.get("animations", {}))
        )
        _has_legs_geo = _has_leg_bones(_geo)
        # Explicit fly components in the spec mean the user/LLM intentionally
        # made this a flier — don't demote it to winged-walker just because it
        # also has leg bones.
        _explicit_fly = _has_fly_components(comps)
        _winged_walker = _has_wing_bones(_geo) and _has_legs_geo and not _explicit_fly
        _should_fly = (
            (_has_fly_anim or _has_wing_bones(_geo) or _explicit_fly)
            and not _winged_walker
        )
        if _should_fly:
            comps.pop("minecraft:movement.basic", None)
            comps.setdefault("minecraft:movement.fly", {})
            comps.pop("minecraft:navigation.walk", None)
            _nav_fly = comps.setdefault("minecraft:navigation.fly", {})
            _nav_fly.setdefault("can_path_over_water", True)
            _nav_fly.setdefault("can_path_over_lava", True)
            _nav_fly.setdefault("can_path_from_air", True)
            comps.setdefault("minecraft:can_fly", {})
            comps.setdefault("minecraft:flying_speed", {"value": 0.4})
            # Vanilla parrot uses default gravity with movement.fly + random_fly. Forcing
            # has_gravity:false removes downward correction; random_fly then drifts upward
            # (especially with large y_dist). Match vanilla: gravity on, tight vertical range.
            comps["minecraft:physics"] = {"has_collision": True}
            comps.pop("minecraft:behavior.wander", None)
            # Ground-walking makes no sense for a pure flier
            comps.pop("minecraft:behavior.random_stroll", None)
            comps["minecraft:behavior.float"] = {"priority": 1}
            if "minecraft:behavior.random_fly" not in comps:
                comps["minecraft:behavior.random_fly"] = {
                    "priority": 5,
                    "avoid_damage_blocks": True,
                    "can_land_on_trees": False,
                    "xz_dist": 15,
                    # Parrot uses y_dist 1 — large values let random_fly pick big vertical hops.
                    "y_dist": 1,
                    "y_offset": 0,
                    "speed_multiplier": 1.0,
                }
            else:
                _rf = comps.get("minecraft:behavior.random_fly")
                if isinstance(_rf, dict):
                    if _rf.get("y_offset") == 3:
                        _rf["y_offset"] = 0
                    if _rf.get("y_dist") == 7:
                        _rf["y_dist"] = 1
            print(f"[BUILD] Ensured fly components + behaviors for {spec['short_name']}")
        elif _winged_walker:
            _strip_fly_ai_for_winged_walker(comps)
            print(
                f"[BUILD] Winged walker {spec['short_name']}: stripped fly AI, "
                "using walk + wing flap while airborne"
            )

        # Loot table pipeline: ensure minecraft:loot is wired AND the
        # actual loot table JSON file is created when loot_drops exists.
        mob_name = spec["identifier"].split(":")[-1]
        loot_drops = spec.get("loot_drops", [])

        # Auto-wire minecraft:loot if loot_drops exists but component missing
        if loot_drops and "minecraft:loot" not in comps:
            comps["minecraft:loot"] = {
                "table": f"loot_tables/entities/{mob_name}.json"
            }
            print(f"[BUILD] Auto-wired minecraft:loot for {mob_name}")

        # Create loot table file
        loot_comp = comps.get("minecraft:loot")
        if loot_comp and isinstance(loot_comp, dict):
            loot_path = loot_comp.get("table", "")
            if loot_path:
                loot_file = beh_root / loot_path
                loot_file.parent.mkdir(parents=True, exist_ok=True)
                loot_table = _generate_loot_table(spec)
                _write_text(loot_file, json.dumps(loot_table, indent=2))
                print(f"[BUILD] Created loot table: {loot_path} (drops={[d.get('item','?') for d in loot_drops] if loot_drops else 'default'})")

        _write_text(ent_file, json.dumps(entity, indent=2))

    if lang_lines:
        _write_text(lang_file, "\n".join(lang_lines) + "\n")

    # One-shot summon via player tag.
    # tick.json calls startup every tick; startup uses a player tag as a
    # one-shot gate. Uses OLD Bedrock execute syntax which works on ALL
    # versions: execute <selector> <x> <y> <z> <command>
    functions_dir = beh_root / "functions"
    functions_dir.mkdir(parents=True, exist_ok=True)
    startup_lines = []
    for i, spec in enumerate(specs):
        offset_x = 2 + (i * 4)
        startup_lines.append(
            f"execute @a[tag=!mf_spawned] ~ ~ ~ summon {spec['identifier']} ~{offset_x} ~ ~2"
        )
    startup_lines.append(
        'execute @a[tag=!mf_spawned] ~ ~ ~ tellraw @a {"rawtext":[{"text":"§aAddon Builder: §fCustom mobs summoned near you!"}]}'
    )
    startup_lines.append("tag @a add mf_spawned")
    _write_text(functions_dir / "startup.mcfunction", "\n".join(startup_lines) + "\n")
    _write_text(functions_dir / "tick.json", json.dumps({"values": ["startup"]}, indent=2))

    main_spec = specs[0] if specs else validate_spec(default_spec())
    man = beh_root / "manifest.json"
    if man.exists():
        manifest = safe_json_load(man) or {}
    else:
        manifest = {"format_version": 2, "header": {}, "modules": []}
    manifest["header"]["description"] = f"{main_spec['display_name']} Behavior"
    manifest["header"]["name"] = f"{main_spec['display_name']} Behavior"
    manifest["header"]["uuid"] = make_uuid()
    manifest["header"]["version"] = [1, 0, 0]
    ensure_min_engine(manifest, [1, 16, 0])
    manifest["modules"] = [{
        "description": "behavior",
        "type": "data",
        "uuid": make_uuid(),
        "version": [1, 0, 0]
    }]
    _write_text(man, json.dumps(manifest, indent=2))
    return manifest
