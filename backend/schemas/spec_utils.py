"""Spec validation, storage, and manipulation utilities."""
import json
import re
from pathlib import Path
from typing import Optional

from backend.config.settings import (
    DEFAULTS, COLOR_WORDS, SPECS_DIR, IDENTIFIER_RE, SHORT_NAME_RE, HEX_COLOR_RE
)


class SpecValidationError(ValueError):
    """Raised when the stored/posted spec fails validation."""
    pass


def default_spec() -> dict:
    """Return a fresh copy of the default spec."""
    return json.loads(json.dumps(DEFAULTS))


def slugify(s: str) -> str:
    """Convert a string to a safe slug (lowercase, alphanumeric + underscore)."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s.strip()).strip("_").lower()
    return s or "mob"


def _hex_to_rgb(value: str) -> Optional[tuple[int, int, int]]:
    """Parse a hex color string to RGB tuple."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
    if len(value) != 6:
        return None
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        return None


def _infer_color_rgb(spec: dict) -> tuple[int, int, int]:
    """Infer RGB color from spec fields or defaults to red."""
    raw = spec.get("color_rgb")
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        try:
            return tuple(int(v) for v in raw)
        except Exception:
            pass
    hint = (spec.get("texture_hint") or "").lower()
    for word, rgb in COLOR_WORDS.items():
        if word in hint:
            return rgb
    for key in ("color_hex", "color", "primary_color"):
        rgb = _hex_to_rgb(spec.get(key))
        if rgb:
            return rgb
    for egg_key in ("egg_base", "egg_overlay"):
        rgb = _hex_to_rgb(spec.get(egg_key))
        if rgb:
            return rgb
    return COLOR_WORDS["red"]


def _coerce_number(value, name: str, *, integer=False, minimum=None, maximum=None):
    """Coerce and validate a numeric value."""
    try:
        if integer:
            if isinstance(value, bool):
                raise TypeError
            num = int(value)
        else:
            num = float(value)
    except (TypeError, ValueError):
        raise SpecValidationError(f"{name} must be a {'whole' if integer else 'numeric'} value.")
    if minimum is not None and num < minimum:
        raise SpecValidationError(f"{name} must be >= {minimum}.")
    if maximum is not None and num > maximum:
        raise SpecValidationError(f"{name} must be <= {maximum}.")
    return num


def _coerce_color(value, name: str) -> str:
    """Validate and normalize a hex color string."""
    if not isinstance(value, str) or not HEX_COLOR_RE.fullmatch(value):
        raise SpecValidationError(f"{name} must be a hex string like #AABBCC.")
    return value.upper()


def sanitize_spec(raw: dict) -> dict:
    """Sanitize a spec by clamping values to valid ranges before validation."""
    if not isinstance(raw, dict):
        return raw
    
    sanitized = json.loads(json.dumps(raw))
    
    # Clamp collision_box values to valid ranges
    if "collision_box" in sanitized and isinstance(sanitized["collision_box"], dict):
        box = sanitized["collision_box"]
        if "width" in box:
            try:
                width = float(box["width"])
                box["width"] = max(0.1, min(5, width))
            except (TypeError, ValueError):
                pass
        if "height" in box:
            try:
                height = float(box["height"])
                box["height"] = max(0.5, min(5, height))
            except (TypeError, ValueError):
                pass
    
    # Clamp HP
    if "hp" in sanitized:
        try:
            hp = int(float(sanitized["hp"]))
            sanitized["hp"] = max(1, min(2048, hp))
        except (TypeError, ValueError):
            pass
    
    # Clamp damage
    if "damage" in sanitized:
        try:
            damage = float(sanitized["damage"])
            sanitized["damage"] = max(0, min(128, damage))
        except (TypeError, ValueError):
            pass
    
    # Clamp speed
    if "speed" in sanitized:
        try:
            speed = float(sanitized["speed"])
            sanitized["speed"] = max(0, min(2, speed))
        except (TypeError, ValueError):
            pass
    
    # Clamp scale
    if "scale" in sanitized:
        try:
            scale = float(sanitized["scale"])
            sanitized["scale"] = max(0.2, min(5.0, scale))
        except (TypeError, ValueError):
            pass
    
    return sanitized


def merge_spec(defaults: dict, *layers: dict) -> dict:
    """Merge spec layers over defaults, filling in missing fields."""
    out = json.loads(json.dumps(defaults))
    for lay in layers:
        for k, v in (lay or {}).items():
            out[k] = v
    if not out.get("short_name"):
        base = out.get("display_name") or out.get("identifier").split(":")[-1]
        out["short_name"] = slugify(base)
    if not out.get("identifier"):
        out["identifier"] = f"custom:{out['short_name']}"
    return out


def validate_spec(raw: dict) -> dict:
    """Validate a spec against constraints and fill defaults."""
    if not isinstance(raw, dict):
        raise SpecValidationError("Spec must be a JSON object.")
    merged = merge_spec(DEFAULTS, raw)

    identifier = merged.get("identifier", "")
    if not IDENTIFIER_RE.fullmatch(identifier):
        raise SpecValidationError("identifier must match namespace:mob_id (lowercase, underscores).")

    short_name = merged.get("short_name", "")
    if not SHORT_NAME_RE.fullmatch(short_name):
        raise SpecValidationError("short_name must be lowercase letters/numbers/underscore.")

    display = merged.get("display_name", "").strip()
    if not display:
        raise SpecValidationError("display_name cannot be empty.")
    merged["display_name"] = display

    engine = merged.get("engine_min")
    if isinstance(engine, str):
        try:
            engine = json.loads(engine)
        except json.JSONDecodeError:
            raise SpecValidationError("engine_min must be an array of 3 integers.")
    if not isinstance(engine, (list, tuple)) or len(engine) != 3:
        raise SpecValidationError("engine_min must be an array of 3 integers.")
    engine = [
        _coerce_number(v, f"engine_min[{idx}]", integer=True, minimum=(0 if idx == 2 else 1), maximum=2000)
        for idx, v in enumerate(engine)
    ]
    merged["engine_min"] = engine

    merged["hp"] = _coerce_number(merged.get("hp"), "hp", integer=True, minimum=1, maximum=2048)
    merged["damage"] = _coerce_number(merged.get("damage"), "damage", minimum=0, maximum=128)
    merged["speed"] = _coerce_number(merged.get("speed"), "speed", minimum=0, maximum=2)

    box = merged.get("collision_box") or {}
    if not isinstance(box, dict):
        raise SpecValidationError("collision_box must be an object with width/height.")
    merged["collision_box"] = {
        "width": _coerce_number(box.get("width"), "collision_box.width", minimum=0.1, maximum=10),
        "height": _coerce_number(box.get("height"), "collision_box.height", minimum=0.5, maximum=10),
    }

    for key in ("geometry", "render_controller", "texture_hint"):
        val = merged.get(key, "")
        if not isinstance(val, str) or not val.strip():
            raise SpecValidationError(f"{key} must be a non-empty string.")
        merged[key] = val.strip()

    merged["egg_base"] = _coerce_color(merged.get("egg_base"), "egg_base")
    merged["egg_overlay"] = _coerce_color(merged.get("egg_overlay"), "egg_overlay")
    merged["scale"] = _coerce_number(merged.get("scale"), "scale", minimum=0.2, maximum=5.0)
    merged["color_rgb"] = list(_infer_color_rgb(merged))

    return merged


def _ensure_spec_storage():
    """Ensure the specs directory exists."""
    SPECS_DIR.mkdir(parents=True, exist_ok=True)


def list_mob_names() -> list[str]:
    """List all stored mob spec names (without .json extension)."""
    _ensure_spec_storage()
    return sorted([p.stem for p in SPECS_DIR.glob("*.json")])


def read_mob_spec(name: str) -> dict:
    """Read and validate a mob spec by name."""
    _ensure_spec_storage()
    path = SPECS_DIR / f"{name}.json"
    if not path.exists():
        if name == "current":
            spec = validate_spec(default_spec())
            write_mob_spec("current", spec)
            return spec
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Mob '{name}' not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate_spec(data)
    except Exception as exc:
        raise SpecValidationError(f"Failed to read mob spec '{name}': {exc}")


def write_mob_spec(name: str, data: dict) -> dict:
    """Write and validate a mob spec to disk."""
    _ensure_spec_storage()
    spec = validate_spec(data)
    # Ensure filename is safe (alphanumeric/underscore)
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    path = SPECS_DIR / f"{safe_name}.json"
    path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return spec


def delete_mob_spec(name: str):
    """Delete a stored mob spec."""
    path = SPECS_DIR / f"{name}.json"
    if path.exists():
        path.unlink()


def read_current_spec() -> dict:
    """Read the first/current spec (convenience for single-mob operations)."""
    mobs = list_mob_names()
    if not mobs:
        return read_mob_spec("current")
    return read_mob_spec(mobs[0])


def write_current_spec(data: dict) -> dict:
    """Write the current spec (convenience for single-mob operations)."""
    spec = validate_spec(data)
    name = spec.get("short_name", "current")
    return write_mob_spec(name, spec)


def _decode_pointer(token: str) -> str:
    """Decode JSON Pointer tokens (RFC 6901)."""
    return token.replace("~1", "/").replace("~0", "~")


def _resolve_parent(doc, tokens):
    """Resolve the parent container and key from a JSON Pointer path."""
    current = doc
    for token in tokens[:-1]:
        if isinstance(current, list):
            try:
                index = int(token)
            except ValueError:
                raise SpecValidationError(f"Invalid array index '{token}'.")
            if index < 0 or index >= len(current):
                raise SpecValidationError(f"Array index {index} out of range.")
            current = current[index]
        elif isinstance(current, dict):
            if token not in current:
                raise SpecValidationError(f"Path segment '{token}' does not exist.")
            current = current[token]
        else:
            raise SpecValidationError("Cannot traverse through non-container types.")
    return current, tokens[-1]


def apply_spec_patch(spec: dict, patch_ops: list[dict]) -> dict:
    """Apply RFC 6902 JSON Patch operations to a spec."""
    if not isinstance(patch_ops, list):
        raise SpecValidationError("Patch payload must be a list of operations.")
    data = json.loads(json.dumps(spec))
    for idx, op in enumerate(patch_ops):
        if not isinstance(op, dict):
            raise SpecValidationError(f"Patch operation at index {idx} is not an object.")
        op_name = op.get("op")
        path = op.get("path")
        if op_name not in {"add", "replace", "remove"}:
            raise SpecValidationError(f"Unsupported op '{op_name}'.")
        if not isinstance(path, str) or not path.startswith("/"):
            raise SpecValidationError("Each patch path must start with '/'.")
        tokens = [_decode_pointer(tok) for tok in path.lstrip("/").split("/") if tok] or []
        if not tokens:
            raise SpecValidationError("Root document replacement is not supported.")
        parent, key = _resolve_parent(data, tokens)
        if isinstance(parent, list):
            if key == "-":
                index = len(parent)
            else:
                try:
                    index = int(key)
                except ValueError:
                    raise SpecValidationError(f"Invalid array index '{key}'.")
            if op_name == "add":
                value = op.get("value")
                if index < 0 or index > len(parent):
                    raise SpecValidationError(f"Array index {index} out of range.")
                parent.insert(index, value)
            elif op_name == "replace":
                if index < 0 or index >= len(parent):
                    raise SpecValidationError(f"Array index {index} out of range.")
                parent[index] = op.get("value")
            elif op_name == "remove":
                if index < 0 or index >= len(parent):
                    raise SpecValidationError(f"Array index {index} out of range.")
                parent.pop(index)
        elif isinstance(parent, dict):
            if op_name == "remove":
                if key not in parent:
                    raise SpecValidationError(f"Path '{path}' does not exist.")
                parent.pop(key)
            elif op_name == "replace":
                if key not in parent:
                    raise SpecValidationError(f"Path '{path}' does not exist.")
                parent[key] = op.get("value")
            elif op_name == "add":
                parent[key] = op.get("value")
        else:
            raise SpecValidationError("Patch path does not point to a container.")
    return data
