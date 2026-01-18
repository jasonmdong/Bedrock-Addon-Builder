#!/usr/bin/env python3
# app.py — Tiny HTTP endpoint to build a Bedrock Behavior+Resource pack + .mcaddon
# FastAPI + the builder logic in one file (stdlib for build; FastAPI for HTTP).
# Python 3.10+

import os, re, json, zipfile, shutil, uuid, tempfile, struct, binascii, zlib, io
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# =========================
# ====== BUILD CORE =======
# =========================

DEFAULTS = {
    "identifier": "cont_stoo:stoopidcow",
    "display_name": "Stoopid Cow",
    "short_name": "stoopidcow",
    "engine_min": [1,21,110],
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


def default_spec() -> dict:
    return json.loads(json.dumps(DEFAULTS))

COLOR_WORDS = {
    "red":   (255, 0, 0),
    "blue":  (40, 120, 255),
    "green": (0, 180, 80),
    "yellow":(240, 200, 0),
    "purple":(160, 60, 220),
    "white": (255,255,255),
    "black": (10,10,10),
    "orange":(255,140,0),
    "pink":  (255,105,180),
    "cyan":  (0,200,200),
}

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "schemas" / "mob_spec.schema.json"
SPEC_PATH = BASE_DIR / "specs" / "current.json"
IDENTIFIER_RE = re.compile(r"^[a-z0-9_]+:[a-z0-9_]+$")
SHORT_NAME_RE = re.compile(r"^[a-z0-9_]+$")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LLM_MODEL_NAME = os.environ.get("LLM_MODEL", "gpt-5")
DEEPSEEK_MODEL_NAME = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEFAULT_LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
WORLD_TEMPLATE_BASES = [
    BASE_DIR / "templates" / "base_world",
    BASE_DIR / "templates" / "base_world.mcworld",
    BASE_DIR / "templates" / "base_world.zip",
    BASE_DIR / "base_world",
    BASE_DIR / "base_world.mcworld",
    BASE_DIR / "base_world.zip",
]
LLM_SYSTEM_PROMPT = """You edit Bedrock mob specs.
Respond with a single JSON object matching the provided schema.
Respect the existing namespace and only change fields the user mentions.
Always include every required key (identifier, display_name, short_name, engine_min, hp, damage, speed,
collision_box, geometry, render_controller, texture_hint, egg_base, egg_overlay, scale)."""


class SpecValidationError(ValueError):
    """Raised when the stored/posted spec fails validation."""


def _load_schema() -> dict:
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


try:
    SPEC_SCHEMA = _load_schema()
except FileNotFoundError:
    SPEC_SCHEMA = {}

def slugify(s: str) -> str:
    import re as _re
    s = _re.sub(r"[^a-zA-Z0-9]+", "_", s.strip()).strip("_").lower()
    return s or "mob"

def make_uuid() -> str:
    return str(uuid.uuid4())

def make_png_rgba(width, height, r, g, b, a=255) -> bytes:
    sig = b'\x89PNG\r\n\x1a\n'
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", binascii.crc32(name + data) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row = bytes([r,g,b,a]) * width
    raw = b''.join([b'\x00' + row for _ in range(height)])
    comp = zlib.compress(raw, level=9)
    return sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', comp) + chunk(b'IEND', b'')

def write_tga(path: Path, width, height, r, g, b, a=255):
    # Uncompressed BGRA 32-bit
    header = struct.pack("<BBB5sHHHHBB", 0, 0, 2, bytes(5), 0, 0, width, height, 32, 0x28)
    pixel = bytes([b, g, r, a])
    raw = pixel * (width * height)
    path.write_bytes(header + raw)

def merge_spec(defaults: dict, *layers: dict) -> dict:
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

def _coerce_number(value, name: str, *, integer=False, minimum=None, maximum=None):
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
    if not isinstance(value, str) or not HEX_COLOR_RE.fullmatch(value):
        raise SpecValidationError(f"{name} must be a hex string like #AABBCC.")
    return value.upper()


def _hex_to_rgb(value: str) -> Optional[tuple[int,int,int]]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
    if len(value) != 6:
        return None
    try:
        return (int(value[0:2],16), int(value[2:4],16), int(value[4:6],16))
    except ValueError:
        return None


def _infer_color_rgb(spec: dict) -> tuple[int,int,int]:
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


def validate_spec(raw: dict) -> dict:
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
        _coerce_number(v, f"engine_min[{idx}]", integer=True, minimum=1, maximum=2000)
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
        "width": _coerce_number(box.get("width"), "collision_box.width", minimum=0.1, maximum=5),
        "height": _coerce_number(box.get("height"), "collision_box.height", minimum=0.5, maximum=5),
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
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)


def read_current_spec() -> dict:
    _ensure_spec_storage()
    if not SPEC_PATH.exists():
        spec = validate_spec(default_spec())
        SPEC_PATH.write_text(json.dumps(spec, indent=2))
        return spec
    data = json.loads(SPEC_PATH.read_text())
    return validate_spec(data)


def write_current_spec(data: dict) -> dict:
    _ensure_spec_storage()
    spec = validate_spec(data)
    SPEC_PATH.write_text(json.dumps(spec, indent=2))
    return spec


def _decode_pointer(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _resolve_parent(doc, tokens):
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


def _get_openai_client(api_key: Optional[str]):
    if OpenAI is None:
        raise RuntimeError("openai package is not installed. Install the 'openai' package.")
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Provide OPENAI_API_KEY (either in the form field or as an environment variable).")
    return OpenAI(api_key=key)


def _call_openai(prompt: str, current: dict, api_key: Optional[str]) -> dict:
    print("[LLM] calling OpenAI model", LLM_MODEL_NAME)
    client = _get_openai_client(api_key)
    schema_text = json.dumps(SPEC_SCHEMA or {}, indent=2)
    messages = [
        {
            "role": "system",
            "content": f"{LLM_SYSTEM_PROMPT}\nSchema:\n{schema_text}"
        },
        {
            "role": "user",
            "content": f"Current spec:\n{json.dumps(current, indent=2)}\n\nInstruction:\n{prompt.strip()}"
        }
    ]
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL_NAME,
            response_format={"type": "json_object"},
            messages=messages
        )
        content = resp.choices[0].message.content
    except Exception as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc
    try:
        candidate = json.loads(content)
    except Exception as exc:
        raise RuntimeError(f"LLM returned invalid JSON: {exc}") from exc
    return validate_spec(candidate)


def _call_deepseek(prompt: str, current: dict, api_key: Optional[str]) -> dict:
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("Provide DEEPSEEK_API_KEY (either in the form field or as an environment variable).")
    print("[LLM] calling DeepSeek model", DEEPSEEK_MODEL_NAME)
    schema_text = json.dumps(SPEC_SCHEMA or {}, indent=2)
    messages = [
        {
            "role": "system",
            "content": f"{LLM_SYSTEM_PROMPT}\nSchema:\n{schema_text}"
        },
        {
            "role": "user",
            "content": f"Current spec:\n{json.dumps(current, indent=2)}\n\nInstruction:\n{prompt.strip()}"
        }
    ]
    payload = json.dumps({
        "model": DEEPSEEK_MODEL_NAME,
        "messages": messages,
        "stream": False,
        "response_format": {"type": "json_object"}
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read().decode("utf-8")
            parsed = json.loads(data)
            content = parsed["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"DeepSeek request failed: {exc}") from exc
    try:
        candidate = json.loads(content)
    except Exception as exc:
        raise RuntimeError(f"LLM returned invalid JSON: {exc}") from exc
    return validate_spec(candidate)


def llm_rewrite_spec(prompt: str, current: dict, provider: str, api_key: Optional[str]) -> dict:
    provider_key = (provider or DEFAULT_LLM_PROVIDER or "openai").lower()
    if provider_key == "deepseek":
        return _call_deepseek(prompt, current, api_key)
    return _call_openai(prompt, current, api_key)

def ensure_min_engine(manifest: dict, engine_min):
    manifest.setdefault("format_version", 2)
    manifest.setdefault("header", {})
    manifest["header"].setdefault("min_engine_version", engine_min)

def zip_dir(src_dir: Path, out_zip: Path):
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in src_dir.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(src_dir))

def safe_json_load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def unpack_if_given(path: Optional[Path], dest: Path):
    if not path: return None
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "r") as zf:
        zf.extractall(dest)
    # Flatten if manifest not at root
    man = dest/"manifest.json"
    if not man.exists():
        for sub in dest.iterdir():
            if sub.is_dir() and (sub/"manifest.json").exists():
                for child in sub.iterdir():
                    shutil.move(str(child), dest)
                shutil.rmtree(sub, ignore_errors=True)
                break
    return dest


def copy_world_template(dest: Path):
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    for cand in _world_template_candidates():
        if cand.is_dir():
            shutil.copytree(cand, dest, dirs_exist_ok=True)
            _flatten_world_root(dest)
            return
        if cand.is_file():
            tmp = Path(tempfile.mkdtemp(prefix="world_tpl_"))
            try:
                with zipfile.ZipFile(cand, "r") as zf:
                    zf.extractall(tmp)
                # Just copy everything from the extract root.
                # _flatten_world_root will handle un-nesting if needed.
                shutil.copytree(tmp, dest, dirs_exist_ok=True)
                _flatten_world_root(dest)
                return
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    raise RuntimeError(
        "World template not found. Place a base world directory or .mcworld/.zip under templates/base_world*."
    )


def _world_template_candidates():
    seen = set()
    for base in WORLD_TEMPLATE_BASES:
        if base not in seen:
            seen.add(base)
            yield base
    for pattern in ("*.mcworld", "*.zip"):
        for path in BASE_DIR.glob(pattern):
            if path not in seen:
                seen.add(path)
                yield path


def _flatten_world_root(world_root: Path):
    if (world_root / "level.dat").exists():
        return
    subdirs = [p for p in world_root.iterdir() if p.is_dir()]
    if len(subdirs) == 1 and (subdirs[0] / "level.dat").exists():
        nested = subdirs[0]
        for child in nested.iterdir():
            shutil.move(str(child), world_root)
        shutil.rmtree(nested, ignore_errors=True)

def patch_resource_pack(res_root: Path, spec: dict):
    ent_dir = res_root/"entity"
    ent_dir.mkdir(parents=True, exist_ok=True)
    client_file = ent_dir/f"{spec['short_name']}.client.entity.json"
    textures_dir = res_root/"textures"/"entity"/spec["short_name"]
    textures_dir.mkdir(parents=True, exist_ok=True)

    png_path = textures_dir/f"{spec['short_name']}.png"
    mers_tga = textures_dir/f"{spec['short_name']}_mers.tga"
    texset = textures_dir/f"{spec['short_name']}.texture_set.json"

    if not png_path.exists():
        col = spec.get("color_rgb", COLOR_WORDS.get("red"))
        png = make_png_rgba(128,128,*col,255)
        png_path.write_bytes(png)
    if not mers_tga.exists():
        col = spec.get("color_rgb", COLOR_WORDS.get("red"))
        write_tga(mers_tga, 128,128,*col,255)
    if not texset.exists():
        texset.write_text(json.dumps({
            "format_version":"1.21.30",
            "minecraft:texture_set":{
                "color": spec["short_name"],
                "metalness_emissive_roughness_subsurface": f"{spec['short_name']}_mers"
            }
        }, indent=2), encoding="utf-8")

    scale = float(spec.get("scale", 1.0))
    client = {
        "format_version":"1.21.0",
        "minecraft:client_entity":{
            "description":{
                "identifier": spec["identifier"],
                "min_engine_version":"1.8.0",
                "materials":{"default":"entity_alphatest"},
                "textures":{"default": f"textures/entity/{spec['short_name']}/{spec['short_name']}"},
                "geometry":{"default": spec.get("geometry", DEFAULTS["geometry"])},
                "render_controllers":[ spec.get("render_controller", DEFAULTS["render_controller"]) ]
            }
        }
    }
    if abs(scale - 1.0) > 1e-6:
        client["minecraft:client_entity"]["description"]["scale"] = scale
    client_file.write_text(json.dumps(client, indent=2), encoding="utf-8")

    man = res_root/"manifest.json"
    if man.exists():
        manifest = safe_json_load(man) or {}
    else:
        manifest = {"format_version":2,"header":{},"modules":[]}
    manifest["header"]["description"] = f"{spec['display_name']} Resources"
    manifest["header"]["name"] = f"{spec['display_name']} Resources"
    manifest["header"]["uuid"] = make_uuid()
    manifest["header"]["version"] = [1,0,0]
    ensure_min_engine(manifest, spec["engine_min"])
    manifest["modules"] = [{
        "description":"resources",
        "type":"resources",
        "uuid": make_uuid(),
        "version":[1,0,0]
    }]
    try:
        (res_root/"pack_icon.png").write_bytes(png_path.read_bytes())
    except Exception:
        pass
    man.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest

def patch_behavior_pack(beh_root: Path, spec: dict):
    ent_dir = beh_root/"entities"
    ent_dir.mkdir(parents=True, exist_ok=True)
    ent_file = ent_dir/f"{spec['short_name']}.entity.json"

    # --- Hostile, pursuit-oriented cow ---
    entity = {
        "format_version": "1.21.10",
        "minecraft:entity": {
            "description": {
                "identifier": spec["identifier"],
                "is_spawnable": True,
                "is_summonable": True,
                "is_experimental": False,
                "spawn_egg": { "base_color": spec.get("egg_base", DEFAULTS["egg_base"]), "overlay_color": spec.get("egg_overlay", DEFAULTS["egg_overlay"]) }
            },
            "components": {
                # Core stats
                "minecraft:type_family": { "family": [spec["short_name"], "monster"] },
                "minecraft:health": { "value": int(spec["hp"]), "max": int(spec["hp"]) },
                # Use 'movement.basic' (more consistent pathing)
                "minecraft:movement.basic": {},
                # Keep a speed scalar via 'minecraft:movement' for engines that honor it
                "minecraft:movement": { "value": float(spec.get("speed", 0.30)) },
                "minecraft:attack": { "damage": float(spec["damage"]) },

                # Physics + pathing
                "minecraft:physics": { "has_gravity": True, "has_collision": True },
                "minecraft:collision_box": spec["collision_box"],
                "minecraft:navigation.walk": { "can_pass_doors": True, "avoid_water": True },
                "minecraft:follow_range": { "value": 40.0 },  # farther acquisition
                "minecraft:knockback_resistance": { "value": 0.5 },
                "minecraft:pushable": { "is_pushable": True },
                "minecraft:despawn": { "despawn_time": 6000 },

                # ---------- AI stack (lower = higher priority) ----------
                # 0) Retaliate if hurt
                "minecraft:behavior.hurt_by_target": { "priority": 0 },

                # 1) Actively target & pursue nearby players (works well across versions)
                "minecraft:behavior.target_nearby_player": {
                    "priority": 1,
                    "within_radius": 32,
                    "must_see": False,
                    "sprint_speed_multiplier": 1.2
                },

                # 2) Backup selector for engines that prefer explicit entity_types targeting
                "minecraft:behavior.nearest_attackable_target": {
                    "priority": 2,
                    "reselect_targets": True,
                    "entity_types": [
                        {
                            "filters": { "test": "is_family", "subject": "other", "value": "player" },
                            "max_dist": 40,
                            "must_see": False
                        }
                    ]
                },

                # 3) Close distance to target (keeps moving between swings)
                "minecraft:behavior.move_towards_target": {
                    "priority": 3,
                    "speed_multiplier": 1.15,
                    "within_radius": 1.8
                },

                # 4) Melee attack when close; keep tracking
                "minecraft:behavior.melee_attack": {
                    "priority": 4,
                    "speed_multiplier": 1.0,
                    "track_target": True
                },

                # 5/6) Idle behaviors (low prio so they don't override pursuit)
                "minecraft:behavior.look_at_player": { "priority": 5, "look_distance": 8.0 },
                "minecraft:behavior.random_stroll": { "priority": 6, "speed_multiplier": 1.0 }
            }
        }
    }
    ent_file.write_text(json.dumps(entity, indent=2), encoding="utf-8")

    # manifest (unchanged)
    man = beh_root/"manifest.json"
    if man.exists():
        manifest = safe_json_load(man) or {}
    else:
        manifest = {"format_version":2,"header":{},"modules":[]}
    manifest["header"]["description"] = f"{spec['display_name']} Behavior"
    manifest["header"]["name"] = f"{spec['display_name']} Behavior"
    manifest["header"]["uuid"] = make_uuid()
    manifest["header"]["version"] = [1,0,0]
    ensure_min_engine(manifest, spec["engine_min"])
    manifest["modules"] = [{
        "description": "behavior",
        "type": "data",
        "uuid": make_uuid(),
        "version": [1,0,0]
    }]
    man.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _manifest_version(manifest: dict) -> list:
    return manifest.get("header", {}).get("version") or [1, 0, 0]


def create_mcworld(out_dir: Path,
                   res_root: Path,
                   res_manifest: dict,
                   beh_root: Path,
                   beh_manifest: dict,
                   spec: dict) -> Path:
    world_root = out_dir / f"{spec['short_name']}_world"
    copy_world_template(world_root)
    
    # Remove any existing pack folders and link files from the template
    # to ensure a clean link to our new packs.
    for folder in ["behavior_packs", "resource_packs"]:
        p = world_root / folder
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
        p.mkdir(parents=True, exist_ok=True)

    # Remove existing icons to avoid confusion
    for icon in ["world_icon.png", "world_icon.jpeg", "world_icon.jpg"]:
        (world_root / icon).unlink(missing_ok=True)

    shutil.copytree(beh_root, world_root / "behavior_packs" / spec["short_name"], dirs_exist_ok=True)
    shutil.copytree(res_root, world_root / "resource_packs" / spec["short_name"], dirs_exist_ok=True)

    (world_root / "levelname.txt").write_text(spec["display_name"], encoding="utf-8")
    
    # Write link files. Note: Minecraft often prefers these to be flat (no indent) 
    # and in some cases, picky about the exact format.
    beh_links = [{
        "pack_id": beh_manifest["header"]["uuid"],
        "version": _manifest_version(beh_manifest)
    }]
    res_links = [{
        "pack_id": res_manifest["header"]["uuid"],
        "version": _manifest_version(res_manifest)
    }]
    
    (world_root / "world_behavior_packs.json").write_text(json.dumps(beh_links), encoding="utf-8")
    (world_root / "world_resource_packs.json").write_text(json.dumps(res_links), encoding="utf-8")

    icon_src = res_root / "pack_icon.png"
    if icon_src.exists():
        # Standard world icon name
        shutil.copyfile(icon_src, world_root / "world_icon.png")

    mcworld = out_dir / f"{spec['short_name']}.mcworld"
    with zipfile.ZipFile(mcworld, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Sort files to ensure level.dat is early in the archive (some parsers like this)
        all_files = []
        for p in world_root.rglob("*"):
            if p.is_file():
                all_files.append(p)
        
        # Put level.dat and levelname.txt first
        all_files.sort(key=lambda x: (x.name != "level.dat", x.name != "levelname.txt", x.name))
        
        for p in all_files:
            arc = p.relative_to(world_root).as_posix()
            zf.write(p, arcname=arc)
            
    shutil.rmtree(world_root, ignore_errors=True)
    return mcworld


def build_addon(spec: dict, out_dir: Path, res_src: Optional[Path], beh_src: Optional[Path]):
    work = Path(tempfile.mkdtemp(prefix="addon_"))
    logs = io.StringIO()
    try:
        res_root = work/"res"
        beh_root = work/"beh"
        if res_src and res_src.exists():
            logs.write(f"Reusing resource pack: {res_src}\n")
            unpack_if_given(res_src, res_root)
        else:
            res_root.mkdir(parents=True, exist_ok=True)
        if beh_src and beh_src.exists():
            logs.write(f"Reusing behavior pack: {beh_src}\n")
            unpack_if_given(beh_src, beh_root)
        else:
            beh_root.mkdir(parents=True, exist_ok=True)

        res_manifest = patch_resource_pack(res_root, spec)
        beh_manifest = patch_behavior_pack(beh_root, spec)

        out_dir.mkdir(parents=True, exist_ok=True)
        res_mcpack = out_dir/f"{spec['short_name']}_resources.mcpack"
        beh_mcpack = out_dir/f"{spec['short_name']}_behavior.mcpack"
        zip_dir(res_root, res_mcpack); logs.write(f"Wrote {res_mcpack}\n")
        zip_dir(beh_root, beh_mcpack); logs.write(f"Wrote {beh_mcpack}\n")

        mcaddon = out_dir/f"{spec['short_name']}.mcaddon"
        with zipfile.ZipFile(mcaddon, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root_path, name in [(res_root, "resource_pack"), (beh_root, "behavior_pack")]:
                for p in root_path.rglob("*"):
                    if p.is_file():
                        arc = Path(name)/p.relative_to(root_path)
                        zf.write(p, arcname=str(arc))
        logs.write(f"Wrote {mcaddon}\n")

        bundle_zip = out_dir/f"{spec['short_name']}_output_bundle.zip"
        mcworld = create_mcworld(out_dir, res_root, res_manifest, beh_root, beh_manifest, spec)

        # Also save the spec.json used for this build into the bundle for debugging/reference
        spec_json_path = out_dir / "spec.json"
        spec_json_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        print(f"[DEBUG] Wrote build spec to {spec_json_path}")

        with zipfile.ZipFile(bundle_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(res_mcpack, arcname=res_mcpack.name)
            zf.write(beh_mcpack, arcname=beh_mcpack.name)
            zf.write(mcaddon, arcname=mcaddon.name)
            zf.write(spec_json_path, arcname="spec.json")
            zf.writestr("BUILD_LOG.txt", logs.getvalue())
        print(f"[DEBUG] Created bundle_zip at {bundle_zip}")

        return {
            "res_mcpack": str(res_mcpack),
            "beh_mcpack": str(beh_mcpack),
            "mcaddon": str(mcaddon),
            "mcworld": str(mcworld),
            "bundle_zip": str(bundle_zip),
            "log": logs.getvalue()
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)

# =========================
# ======= WEB APP =========
# =========================

app = FastAPI(title="Bedrock Add-on Builder", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.get("/api/spec", response_class=JSONResponse)
def get_spec():
    return {
        "spec": read_current_spec(),
        "schema": SPEC_SCHEMA
    }


@app.put("/api/spec", response_class=JSONResponse)
async def replace_spec(payload: dict = Body(...)):
    try:
        spec = write_current_spec(payload)
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"spec": spec}


@app.post("/api/spec/patch", response_class=JSONResponse)
async def patch_spec(operations: list[dict] = Body(...)):
    current = read_current_spec()
    try:
        patched = apply_spec_patch(current, operations)
        spec = write_current_spec(patched)
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"spec": spec}


@app.post("/api/spec/llm", response_class=JSONResponse)
def llm_spec_editor(payload: dict = Body(...)):
    data = payload or {}
    prompt = data.get("prompt", "")
    if not prompt or not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    provider = data.get("provider") or DEFAULT_LLM_PROVIDER
    api_key = data.get("api_key")
    print(f"[LLM] provider={provider} prompt_len={len(prompt.strip())}")
    current = read_current_spec()
    try:
        updated = llm_rewrite_spec(prompt, current, provider, api_key)
        spec = write_current_spec(updated)
        print("[LLM] update complete; short_name=", spec.get("short_name"))
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        print(f"[LLM] error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    return {"spec": spec}

INDEX_HTML = """
<!doctype html>
<meta charset="utf-8">
<title>Bedrock Add-on Builder</title>
<style>
  :root {
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
    --bg: #f8fafc;
    --text: #0f172a;
    --card-bg: #ffffff;
    --border: #e2e8f0;
    --muted: #94a3b8;
    --hint: #475569;
    --editor-bg: #0f172a;
    --editor-text: #e2e8f0;
    --status-bg: #0f172a;
    --status-text: #94a3b8;
    --primary: #2563eb;
    --secondary-bg: #e2e8f0;
    --secondary-text: #0f172a;
    --danger: #dc2626;
    --ghost-bg: rgba(148,163,184,0.18);
    --ghost-text: #0f172a;
  }
  body.theme-dark {
    --bg: #05060b;
    --text: #f8fafc;
    --card-bg: #0f172a;
    --border: #1f2937;
    --muted: #cbd5f5;
    --hint: #cbd5f5;
    --editor-bg: #020617;
    --editor-text: #e2e8f0;
    --status-bg: #020617;
    --status-text: #cbd5f5;
    --primary: #38bdf8;
    --secondary-bg: #1e293b;
    --secondary-text: #f8fafc;
    --danger: #f87171;
    --ghost-bg: rgba(148,163,184,0.35);
    --ghost-text: #f8fafc;
  }
  body {
    margin: 2rem;
    color: var(--text);
    background: var(--bg);
    transition: background .3s ease, color .3s ease;
  }
  main {
    max-width: 960px;
    margin: 0 auto;
    background: var(--card-bg);
    border-radius: 16px;
    padding: 2rem;
    box-shadow: 0 18px 35px rgba(15,23,42,.08);
  }
  h1 { margin-top: 0; }
  textarea {
    width:100%;
    min-height: 380px;
    font: 14px/1.4 ui-monospace, SFMono-Regular, Consolas, Menlo, monospace;
    padding: 1rem;
    border-radius: 12px;
    border:1px solid var(--border);
    background: var(--editor-bg);
    color: var(--editor-text);
  }
  textarea:focus { outline: 2px solid var(--primary); }
  .actions { display:flex; gap: 1rem; margin-top: 1rem; flex-wrap: wrap; }
  button { padding: .75rem 1.4rem; border-radius: 999px; border: none; font-weight: 600; cursor: pointer; transition: transform .2s ease; }
  button:active { transform: scale(0.97); }
  button.primary { background: var(--primary); color:#fff; }
  button.secondary { background: var(--secondary-bg); color: var(--secondary-text); }
  button.danger { background: var(--danger); color:#fff; }
  button.ghost { background: var(--ghost-bg); color: var(--ghost-text); }
  label { font-weight: 600; display:block; margin-bottom: .35rem; }
  input[type=file] { width:100%; padding:.35rem 0; color: var(--text); }
  input[type=password], select {
    width: 100%;
    padding: .6rem .75rem;
    border-radius: 10px;
    border:1px solid var(--border);
    background: var(--card-bg);
    color: var(--text);
    font: inherit;
  }
  .row { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-top: 1rem; }
  .llm-card { margin-top: 1.5rem; padding: 1.2rem 1.4rem; border-radius: 16px; border:1px solid var(--border); background: rgba(148,163,184,0.12); display:flex; flex-direction:column; gap:1rem; }
  .llm-controls { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:1rem; align-items:end; }
  .llm-controls .field { min-width:0; }
  .llm-controls .field label { font-size:.9rem; color: var(--hint); margin-bottom:.35rem; }
  .llm-card select,
  .llm-card input[type=password] {
    height: 46px;
    border-radius: 12px;
    border:1px solid var(--border);
    background: var(--card-bg);
    color: var(--text);
    padding: 0 .9rem;
    font: inherit;
  }
  #llm-prompt {
    min-height: 140px;
    background: var(--card-bg);
    color: var(--text);
    border-radius: 12px;
    border:1px solid var(--border);
    resize: vertical;
  }
  .llm-footnote { color: var(--hint); font-size:.85rem; }
  #status {
    background: var(--status-bg);
    color: var(--status-text);
    padding: 1rem;
    border-radius: 12px;
    margin-top:1rem;
    min-height:3rem;
    white-space:pre-wrap;
  }
  .hint { color: var(--hint); font-size:.95rem; margin-bottom:1rem; }
  .build-options { margin-top:1.25rem; display:flex; align-items:center; gap:1rem; flex-wrap:wrap; }
  .build-options label { margin:0; font-size:.95rem; }
  .build-options select { width:auto; min-width:220px; }
  details { margin-top:1rem; }
  code { font-family: ui-monospace, SFMono-Regular, Consolas, Menlo, monospace; }
  .toolbar { display:flex; justify-content:flex-end; margin-bottom:1rem; }
</style>
<main>
  <div class="toolbar">
    <button type="button" class="ghost" id="theme-toggle">🌙 Dark Mode</button>
  </div>
  <h1>Bedrock Add-on Builder</h1>
  <p class="hint">
    Edit the JSON spec, save it, then build packs. Optional resource/behavior packs are merged in before bundling.
  </p>
  <div class="row">
    <div>
      <label>Resource Pack (.zip/.mcpack)</label>
      <input type="file" id="resource">
    </div>
    <div>
      <label>Behavior Pack (.zip/.mcpack)</label>
      <input type="file" id="behavior">
    </div>
  </div>
  <div class="llm-card">
    <div>
      <label style="font-size:1rem;">LLM Assistant Prompt</label>
      <p class="hint" style="margin:.2rem 0 0;">Describe the change you want and let an LLM update the spec.</p>
    </div>
    <div class="llm-controls">
      <div class="field">
        <label>Provider</label>
        <select id="llm-provider">
          <option value="openai">OpenAI</option>
          <option value="deepseek">DeepSeek</option>
        </select>
      </div>
      <div class="field">
        <label>API Key</label>
        <input type="password" id="llm-key" placeholder="sk-..." autocomplete="off">
      </div>
    </div>
    <textarea id="llm-prompt" placeholder="Describe how the mob should change (damage, hp, colors, geometry...)."></textarea>
    <div class="actions">
      <button type="button" class="primary" id="llm-run">Ask LLM</button>
      <span class="llm-footnote">Paste an API key here or configure OPENAI_API_KEY / DEEPSEEK_API_KEY on the server.</span>
    </div>
  </div>
  <pre id="status">Loading spec...</pre>
  <div class="build-options">
    <label for="build-mode">Download Type</label>
    <select id="build-mode">
      <option value="bundle">Bundle (.zip with mcaddon)</option>
      <option value="mcworld">World (.mcworld)</option>
    </select>
  </div>
  <label style="margin-top:1rem;">Mob Spec JSON</label>
  <textarea id="spec-editor" spellcheck="false" autocomplete="off"></textarea>
  <div class="actions">
    <button type="button" class="secondary" id="reset">Reset</button>
    <button type="button" class="danger" id="save">Save Spec</button>
    <button type="button" class="primary" id="build">Build Bundle</button>
  </div>
  <details>
    <summary>View schema (for LLM prompts)</summary>
    <pre id="schema-view" style="background:var(--status-bg);color:var(--status-text);padding:1rem;border-radius:12px;overflow:auto;max-height:240px;"></pre>
  </details>
</main>
<script>
const THEME_KEY = "builder_theme_preference";
const LLM_PROVIDER_KEY = "builder_llm_provider";
const LLM_API_KEY_STORAGE = "builder_llm_api_key";
const BUILD_MODE_KEY = "builder_build_mode";
const editor = document.getElementById("spec-editor");
const statusEl = document.getElementById("status");
const schemaView = document.getElementById("schema-view");
const resourceInput = document.getElementById("resource");
const behaviorInput = document.getElementById("behavior");
const llmPrompt = document.getElementById("llm-prompt");
const llmButton = document.getElementById("llm-run");
const llmProvider = document.getElementById("llm-provider");
const llmKey = document.getElementById("llm-key");
const themeToggle = document.getElementById("theme-toggle");
const buildModeSelect = document.getElementById("build-mode");

function applyTheme(theme) {
  document.body.classList.toggle("theme-dark", theme === "dark");
  if (themeToggle) {
    themeToggle.textContent = theme === "dark" ? "☀ Light Mode" : "🌙 Dark Mode";
  }
}

function initTheme() {
  const stored = localStorage.getItem(THEME_KEY);
  const theme = stored === "dark" ? "dark" : "light";
  applyTheme(theme);
}

function loadLlmPrefs() {
  const storedProvider = localStorage.getItem(LLM_PROVIDER_KEY);
  const storedKey = localStorage.getItem(LLM_API_KEY_STORAGE);
  if (storedProvider && llmProvider) {
    llmProvider.value = storedProvider;
  }
  if (storedKey && llmKey) {
    llmKey.value = storedKey;
  }
}

function loadBuildMode() {
  const storedMode = localStorage.getItem(BUILD_MODE_KEY);
  if (storedMode && buildModeSelect) {
    buildModeSelect.value = storedMode;
  }
}

function setStatus(message, isError=false) {
  statusEl.textContent = message;
  statusEl.style.color = isError ? "#fecdd3" : "#94a3b8";
}

async function loadSpec() {
  setStatus("Fetching spec...");
  const res = await fetch("/api/spec");
  if (!res.ok) {
    setStatus("Failed to load spec: " + res.statusText, true);
    return;
  }
  const data = await res.json();
  editor.value = JSON.stringify(data.spec, null, 2);
  schemaView.textContent = JSON.stringify(data.schema || {}, null, 2);
  setStatus("Loaded spec at " + new Date().toLocaleTimeString());
}

async function saveSpec() {
  let body;
  try {
    body = JSON.stringify(JSON.parse(editor.value), null, 2);
  } catch (err) {
    setStatus("JSON parse error: " + err.message, true);
    return null;
  }
  const res = await fetch("/api/spec", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = payload.detail || JSON.stringify(payload);
    setStatus("Save failed: " + detail, true);
    return null;
  }
  editor.value = JSON.stringify(payload.spec, null, 2);
  setStatus("Saved spec.");
  return payload.spec;
}

async function buildArtifact() {
  const choice = buildModeSelect ? buildModeSelect.value : "bundle";
  setStatus(`Building ${choice}...`);
  const formData = new FormData();
  if (resourceInput.files[0]) formData.append("resource", resourceInput.files[0]);
  if (behaviorInput.files[0]) formData.append("behavior", behaviorInput.files[0]);
  formData.append("build_mode", choice);
  const res = await fetch("/api/build", { method: "POST", body: formData });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = payload.detail || payload.error || res.statusText;
    setStatus("Build failed: " + detail, true);
    return;
  }
  const link = document.createElement("a");
  link.href = payload.artifact || payload.bundle_zip;
  link.textContent = payload.kind === "mcworld" ? "Download .mcworld" : "Download bundle";
  link.target = "_blank";
  link.rel = "noopener";
  statusEl.innerHTML = `${payload.kind === "mcworld" ? "World" : "Bundle"} ready. `;
  statusEl.appendChild(link);
}

async function requestLlm() {
  if (!llmPrompt) return;
  const instruction = llmPrompt.value.trim();
  if (!instruction) {
    setStatus("Enter instructions for the LLM assistant.", true);
    return;
  }
  const provider = llmProvider ? llmProvider.value : "openai";
  setStatus(`Contacting ${provider}...`);
  const apiKey = llmKey ? llmKey.value.trim() : "";
  const requestBody = { prompt: instruction, provider };
  if (apiKey) {
    requestBody.api_key = apiKey;
  }
  let res;
  try {
    res = await fetch("/api/spec/llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody)
    });
  } catch (err) {
    console.error("LLM fetch failed", err);
    setStatus("LLM request failed (network): " + err.message, true);
    return;
  }
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = payload.detail || payload.error || res.statusText;
    setStatus("LLM request failed: " + detail, true);
    return;
  }
  console.log("LLM response", payload);
  editor.value = JSON.stringify(payload.spec, null, 2);
  setStatus(`${provider} updated and saved the spec at ${new Date().toLocaleTimeString()}.`);
}

document.getElementById("reset").addEventListener("click", (e) => {
  e.preventDefault();
  loadSpec();
});
document.getElementById("save").addEventListener("click", (e) => {
  e.preventDefault();
  saveSpec();
});
document.getElementById("build").addEventListener("click", async (e) => {
  e.preventDefault();
  const saved = await saveSpec();
  if (saved) {
    await buildArtifact();
  }
});
llmButton?.addEventListener("click", async (e) => {
  e.preventDefault();
  await requestLlm();
});
themeToggle?.addEventListener("click", () => {
  const next = document.body.classList.contains("theme-dark") ? "light" : "dark";
  applyTheme(next);
  localStorage.setItem(THEME_KEY, next);
});
llmProvider?.addEventListener("change", () => {
  localStorage.setItem(LLM_PROVIDER_KEY, llmProvider.value);
});
llmKey?.addEventListener("input", () => {
  localStorage.setItem(LLM_API_KEY_STORAGE, llmKey.value.trim());
});
buildModeSelect?.addEventListener("change", () => {
  localStorage.setItem(BUILD_MODE_KEY, buildModeSelect.value);
});

initTheme();
loadLlmPrefs();
loadBuildMode();
loadSpec();
</script>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML

@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"

def _save_upload(tmpdir: Path, uf: Optional[UploadFile]) -> Optional[Path]:
    if not uf: return None
    if not uf.filename: return None
    suffix = "".join(Path(uf.filename).suffixes) or ".zip"
    dest = tmpdir / f"upload_{uuid.uuid4().hex}{suffix}"
    with dest.open("wb") as f:
        shutil.copyfileobj(uf.file, f)
    return dest

def _select_artifact(artifacts: dict, build_mode: str) -> tuple[str, Path]:
    mode = (build_mode or "bundle").lower()
    if mode == "mcworld":
        return "mcworld", Path(artifacts["mcworld"])
    elif mode == "mcaddon":
        return "mcaddon", Path(artifacts["mcaddon"])
    elif mode == "resources":
        return "resources", Path(artifacts["res_mcpack"])
    elif mode == "behavior":
        return "behavior", Path(artifacts["beh_mcpack"])
    return "bundle", Path(artifacts["bundle_zip"])


def _build_and_bundle(res_path: Optional[Path],
                      beh_path: Optional[Path],
                      spec_override: Optional[dict] = None,
                      build_mode: str = "bundle") -> tuple[str, Path, dict]:
    spec = validate_spec(spec_override or read_current_spec())
    out_dir = Path(tempfile.mkdtemp(prefix="out_"))
    artifacts = build_addon(spec, out_dir, res_path, beh_path)
    kind, artifact_path = _select_artifact(artifacts, build_mode)
    return kind, artifact_path, artifacts

@app.post("/build")
def build_form(resource: Optional[UploadFile] = File(None),
               behavior: Optional[UploadFile] = File(None),
               build_mode: str = Form("bundle")):
    tmp = Path(tempfile.mkdtemp(prefix="http_"))
    try:
        res_path = _save_upload(tmp, resource)
        beh_path = _save_upload(tmp, behavior)
        kind, artifact, _ = _build_and_bundle(res_path, beh_path, build_mode=build_mode)
        media_type = "application/zip" if kind != "mcworld" else "application/octet-stream"
        return FileResponse(artifact, filename=artifact.name, media_type=media_type)
    finally:
        pass

@app.post("/api/build")
async def api_build(resource: Optional[UploadFile] = File(None),
                    behavior: Optional[UploadFile] = File(None),
                    build_mode: str = Form("bundle")):
    tmp = Path(tempfile.mkdtemp(prefix="http_"))
    try:
        # Load the current spec from disk to ensure we use the latest saved version
        current_spec = read_current_spec()
        res_path = _save_upload(tmp, resource)
        beh_path = _save_upload(tmp, behavior)
        kind, artifact, artifacts = _build_and_bundle(res_path, beh_path, spec_override=current_spec, build_mode=build_mode)
        downloads = {
            "bundle": f"/download/{Path(artifacts['bundle_zip']).name}",
            "mcworld": f"/download/{Path(artifacts['mcworld']).name}",
            "mcaddon": f"/download/{Path(artifacts['mcaddon']).name}",
            "res_mcpack": f"/download/{Path(artifacts['res_mcpack']).name}",
            "beh_mcpack": f"/download/{Path(artifacts['beh_mcpack']).name}",
        }
        return JSONResponse({
            "artifact": f"/download/{artifact.name}",
            "kind": kind,
            "downloads": downloads,
            "note": "Fetch artifacts at /download/<name>; choose mcworld to import directly into Minecraft."
        })
    finally:
        pass

@app.get("/download/{name}")
def download(name: str):
    root = Path(tempfile.gettempdir())
    print(f"[DEBUG] Searching for {name} in {root}")
    # Sort by mtime to find the newest one if multiple exist
    candidates = []
    for p in root.rglob(name):
        if p.is_file():
            candidates.append(p)
    
    if candidates:
        newest = max(candidates, key=lambda x: x.stat().st_mtime)
        print(f"[DEBUG] Found newest: {newest}")
        return FileResponse(newest, filename=newest.name, media_type="application/zip")
    
    print(f"[DEBUG] {name} not found")
    return PlainTextResponse("Not found", status_code=404)

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
