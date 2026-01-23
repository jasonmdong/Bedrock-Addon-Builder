#!/usr/bin/env python3
# app.py — Tiny HTTP endpoint to build a Bedrock Behavior+Resource pack + .mcaddon
# FastAPI + the builder logic in one file (stdlib for build; FastAPI for HTTP).
# Python 3.10+

import os, re, json, zipfile, shutil, uuid, tempfile, struct, binascii, zlib, io
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body, Response
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
SPECS_DIR = BASE_DIR / "specs"
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
    SPECS_DIR.mkdir(parents=True, exist_ok=True)

def list_mob_names() -> list[str]:
    _ensure_spec_storage()
    return sorted([p.stem for p in SPECS_DIR.glob("*.json")])

def read_mob_spec(name: str) -> dict:
    _ensure_spec_storage()
    path = SPECS_DIR / f"{name}.json"
    if not path.exists():
        if name == "current":
            spec = validate_spec(default_spec())
            write_mob_spec("current", spec)
            return spec
        raise HTTPException(status_code=404, detail=f"Mob '{name}' not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate_spec(data)
    except Exception as exc:
        raise SpecValidationError(f"Failed to read mob spec '{name}': {exc}")

def write_mob_spec(name: str, data: dict) -> dict:
    _ensure_spec_storage()
    spec = validate_spec(data)
    # Ensure filename is safe (alphanumeric/underscore)
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    path = SPECS_DIR / f"{safe_name}.json"
    path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return spec

def delete_mob_spec(name: str):
    path = SPECS_DIR / f"{name}.json"
    if path.exists():
        path.unlink()

def read_current_spec() -> dict:
    # Legacy support / convenience for single-mob operations
    mobs = list_mob_names()
    if not mobs:
        return read_mob_spec("current")
    return read_mob_spec(mobs[0])

def write_current_spec(data: dict) -> dict:
    # Legacy support
    spec = validate_spec(data)
    name = spec.get("short_name", "current")
    return write_mob_spec(name, spec)


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
    
    print("[LLM] calling DeepSeek via OpenAI client")
    try:
        # DeepSeek is OpenAI-compatible
        client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
        schema_text = json.dumps(SPEC_SCHEMA or {}, indent=2)
        
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": f"{LLM_SYSTEM_PROMPT}\nSchema:\n{schema_text}"
                },
                {
                    "role": "user",
                    "content": f"Current spec:\n{json.dumps(current, indent=2)}\n\nInstruction:\n{prompt.strip()}"
                }
            ],
            stream=False,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        candidate = json.loads(content)
        return validate_spec(candidate)
    except Exception as exc:
        print(f"[LLM] DeepSeek request failed: {exc}")
        raise RuntimeError(f"DeepSeek request failed: {exc}") from exc


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

def patch_resource_pack(res_root: Path, specs: list[dict]):
    ent_dir = res_root/"entity"
    ent_dir.mkdir(parents=True, exist_ok=True)
    
    texts_dir = res_root/"texts"
    texts_dir.mkdir(parents=True, exist_ok=True)
    lang_file = texts_dir/"en_US.lang"
    lang_lines = []

    # Explicitly register spawn egg icons for better compatibility
    tex_dir = res_root/"textures"
    tex_dir.mkdir(parents=True, exist_ok=True)
    item_tex_file = tex_dir/"item_texture.json"
    item_texture = {
        "resource_pack_name": "custom_addon",
        "texture_name": "atlas.items",
        "texture_data": {}
    }

    first_png = None
    
    for spec in specs:
        client_file = ent_dir/f"{spec['short_name']}.client.entity.json"
        textures_dir = res_root/"textures"/"entity"/spec["short_name"]
        textures_dir.mkdir(parents=True, exist_ok=True)

        png_path = textures_dir/f"{spec['short_name']}.png"
        mers_tga = textures_dir/f"{spec['short_name']}_mers.tga"
        texset = textures_dir/f"{spec['short_name']}.texture_set.json"

        # Try to copy persistent texture if it exists
        persistent_png = Path("specs") / f"{spec['short_name']}.png"
        if persistent_png.exists():
            shutil.copyfile(persistent_png, png_path)
        
        if not png_path.exists():
            col = spec.get("color_rgb", COLOR_WORDS.get("red"))
            png = make_png_rgba(64,64,*col,255)
            png_path.write_bytes(png)
        
        if not first_png:
            first_png = png_path

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
        
        # Add names to lang file
        display_name = spec.get("display_name", spec["short_name"].capitalize())
        lang_lines.append(f"entity.{spec['identifier']}.name={display_name}")
        lang_lines.append(f"item.spawn_egg.entity.{spec['identifier']}.name=Spawn {display_name}")

        # Map the spawn egg texture to the entity icon (optional but good)
        item_texture["texture_data"][f"spawn_egg_{spec['short_name']}"] = {
            "textures": f"textures/entity/{spec['short_name']}/{spec['short_name']}"
        }

    if lang_lines:
        lang_file.write_text("\n".join(lang_lines), encoding="utf-8")
    
    if item_texture["texture_data"]:
        item_tex_file.write_text(json.dumps(item_texture, indent=2), encoding="utf-8")

    # Use the first spec for the main manifest info
    main_spec = specs[0] if specs else validate_spec(default_spec())
    
    man = res_root/"manifest.json"
    if man.exists():
        manifest = safe_json_load(man) or {}
    else:
        manifest = {"format_version":2,"header":{},"modules":[]}
    manifest["header"]["description"] = f"{main_spec['display_name']} Resources"
    manifest["header"]["name"] = f"{main_spec['display_name']} Resources"
    manifest["header"]["uuid"] = make_uuid()
    manifest["header"]["version"] = [1,0,0]
    ensure_min_engine(manifest, main_spec["engine_min"])
    manifest["modules"] = [{
        "description":"resources",
        "type":"resources",
        "uuid": make_uuid(),
        "version":[1,0,0]
    }]
    try:
        if first_png:
            (res_root/"pack_icon.png").write_bytes(first_png.read_bytes())
    except Exception:
        pass
    man.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest

def patch_behavior_pack(beh_root: Path, specs: list[dict]):
    ent_dir = beh_root/"entities"
    ent_dir.mkdir(parents=True, exist_ok=True)
    
    texts_dir = beh_root/"texts"
    texts_dir.mkdir(parents=True, exist_ok=True)
    lang_file = texts_dir/"en_US.lang"
    lang_lines = []

    for spec in specs:
        ent_file = ent_dir/f"{spec['short_name']}.entity.json"
        
        # Add names to lang file for behavior pack too (helps with some registries)
        display_name = spec.get("display_name", spec["short_name"].capitalize())
        lang_lines.append(f"entity.{spec['identifier']}.name={display_name}")

        # --- Hostile, pursuit-oriented mob ---
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
                    "minecraft:type_family": { "family": [spec["short_name"], "monster"] },
                    "minecraft:health": { "value": int(spec["hp"]), "max": int(spec["hp"]) },
                    "minecraft:movement.basic": {},
                    "minecraft:movement": { "value": float(spec.get("speed", 0.30)) },
                    "minecraft:attack": { "damage": float(spec["damage"]) },
                    "minecraft:physics": { "has_gravity": True, "has_collision": True },
                    "minecraft:collision_box": spec["collision_box"],
                    "minecraft:navigation.walk": { "can_pass_doors": True, "avoid_water": True },
                    "minecraft:follow_range": { "value": 40.0 },
                    "minecraft:knockback_resistance": { "value": 0.5 },
                    "minecraft:pushable": { "is_pushable": True },
                    "minecraft:despawn": { "despawn_time": 6000 },
                    "minecraft:behavior.hurt_by_target": { "priority": 0 },
                    "minecraft:behavior.target_nearby_player": {
                        "priority": 1,
                        "within_radius": 32,
                        "must_see": False,
                        "sprint_speed_multiplier": 1.2
                    },
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
                    "minecraft:behavior.move_towards_target": {
                        "priority": 3,
                        "speed_multiplier": 1.15,
                        "within_radius": 1.8
                    },
                    "minecraft:behavior.melee_attack": {
                        "priority": 4,
                        "speed_multiplier": 1.0,
                        "track_target": True
                    },
                    "minecraft:behavior.look_at_player": { "priority": 5, "look_distance": 8.0 },
                    "minecraft:behavior.random_stroll": { "priority": 6, "speed_multiplier": 1.0 }
                }
            }
        }
        ent_file.write_text(json.dumps(entity, indent=2), encoding="utf-8")

    if lang_lines:
        lang_file.write_text("\n".join(lang_lines), encoding="utf-8")

    main_spec = specs[0] if specs else validate_spec(default_spec())
    man = beh_root/"manifest.json"
    if man.exists():
        manifest = safe_json_load(man) or {}
    else:
        manifest = {"format_version":2,"header":{},"modules":[]}
    manifest["header"]["description"] = f"{main_spec['display_name']} Behavior"
    manifest["header"]["name"] = f"{main_spec['display_name']} Behavior"
    manifest["header"]["uuid"] = make_uuid()
    manifest["header"]["version"] = [1,0,0]
    ensure_min_engine(manifest, main_spec["engine_min"])
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
                   specs: list[dict]) -> Path:
    main_spec = specs[0] if specs else validate_spec(default_spec())
    world_root = out_dir / f"{main_spec['short_name']}_world"
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

    # Copy our combined packs into the world
    shutil.copytree(beh_root, world_root / "behavior_packs" / "custom_addon_beh", dirs_exist_ok=True)
    shutil.copytree(res_root, world_root / "resource_packs" / "custom_addon_res", dirs_exist_ok=True)

    (world_root / "levelname.txt").write_text(f"Add-on: {main_spec['display_name']}", encoding="utf-8")
    
    # Write link files.
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
        shutil.copyfile(icon_src, world_root / "world_icon.png")

    mcworld = out_dir / f"{main_spec['short_name']}.mcworld"
    with zipfile.ZipFile(mcworld, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        all_files = []
        for p in world_root.rglob("*"):
            if p.is_file():
                all_files.append(p)
        
        all_files.sort(key=lambda x: (x.name != "level.dat", x.name != "levelname.txt", x.name))
        for p in all_files:
            arc = p.relative_to(world_root).as_posix()
            zf.write(p, arcname=arc)
            
    shutil.rmtree(world_root, ignore_errors=True)
    return mcworld


def build_addon(specs: list[dict], out_dir: Path, res_src: Optional[Path], beh_src: Optional[Path]):
    work = Path(tempfile.mkdtemp(prefix="addon_"))
    logs = io.StringIO()
    try:
        logs.write(f"Building bundle with {len(specs)} mobs: {[s.get('short_name') for s in specs]}\n")
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

        res_manifest = patch_resource_pack(res_root, specs)
        beh_manifest = patch_behavior_pack(beh_root, specs)

        out_dir.mkdir(parents=True, exist_ok=True)
        
        main_spec = specs[0] if specs else validate_spec(default_spec())
        res_mcpack = out_dir/f"{main_spec['short_name']}_resources.mcpack"
        beh_mcpack = out_dir/f"{main_spec['short_name']}_behavior.mcpack"
        zip_dir(res_root, res_mcpack); logs.write(f"Wrote {res_mcpack}\n")
        zip_dir(beh_root, beh_mcpack); logs.write(f"Wrote {beh_mcpack}\n")

        mcaddon = out_dir/f"{main_spec['short_name']}.mcaddon"
        with zipfile.ZipFile(mcaddon, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root_path, name in [(res_root, "resource_pack"), (beh_root, "behavior_pack")]:
                for p in root_path.rglob("*"):
                    if p.is_file():
                        arc = Path(name)/p.relative_to(root_path)
                        zf.write(p, arcname=str(arc))
        logs.write(f"Wrote {mcaddon}\n")

        bundle_zip = out_dir/f"{main_spec['short_name']}_output_bundle.zip"
        
        mcworld = None
        try:
            mcworld = create_mcworld(out_dir, res_root, res_manifest, beh_root, beh_manifest, specs)
        except Exception as exc:
            print(f"[WARN] Failed to create .mcworld: {exc}")
            logs.write(f"Warning: .mcworld could not be created because no base world template was found.\n")

        spec_json_path = out_dir / "specs.json"
        spec_json_path.write_text(json.dumps(specs, indent=2), encoding="utf-8")

        with zipfile.ZipFile(bundle_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(res_mcpack, arcname=res_mcpack.name)
            zf.write(beh_mcpack, arcname=beh_mcpack.name)
            zf.write(mcaddon, arcname=mcaddon.name)
            if mcworld:
                zf.write(mcworld, arcname=mcworld.name)
            zf.write(spec_json_path, arcname="specs.json")
            zf.writestr("BUILD_LOG.txt", logs.getvalue())

        return {
            "res_mcpack": str(res_mcpack),
            "beh_mcpack": str(beh_mcpack),
            "mcaddon": str(mcaddon),
            "mcworld": str(mcworld) if mcworld else "",
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

@app.get("/api/mobs", response_class=JSONResponse)
def get_mobs():
    return {"mobs": list_mob_names()}

@app.get("/api/mobs/{name}", response_class=JSONResponse)
def get_mob(name: str):
    try:
        spec = read_mob_spec(name)
        return {"spec": spec, "schema": SPEC_SCHEMA}
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.get("/api/mobs/{name}/texture")
def get_mob_texture(name: str):
    path = Path("specs") / f"{name}.png"
    if path.exists():
        return FileResponse(path, media_type="image/png")
    # Fallback to a generated one based on the spec
    spec = read_mob_spec(name)
    col = spec.get("color_rgb", COLOR_WORDS.get("red"))
    png = make_png_rgba(64, 64, *col, 255)
    return Response(content=png, media_type="image/png")

@app.post("/api/mobs/{name}/texture")
async def save_mob_texture(name: str, file: UploadFile = File(...)):
    path = Path("specs") / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"status": "ok"}

@app.post("/api/mobs/{name}", response_class=JSONResponse)
async def save_mob(name: str, payload: dict = Body(...)):
    try:
        spec = write_mob_spec(name, payload)
        return {"spec": spec}
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.delete("/api/mobs/{name}", response_class=JSONResponse)
def delete_mob(name: str):
    delete_mob_spec(name)
    return {"status": "ok"}

@app.post("/api/mobs/{name}/duplicate", response_class=JSONResponse)
def duplicate_mob(name: str):
    spec = read_mob_spec(name)
    new_name = f"{name}_copy"
    # Ensure uniqueness
    existing = list_mob_names()
    while new_name in existing:
        new_name = f"{new_name}_copy"
    spec["short_name"] = new_name
    spec["display_name"] = f"{spec['display_name']} Copy"
    spec["identifier"] = f"{spec['identifier']}_copy"
    new_spec = write_mob_spec(new_name, spec)
    return {"name": new_name, "spec": new_spec}

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

@app.get("/", response_class=HTMLResponse)
def index():
    return Path("index.html").read_text(encoding="utf-8")

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
        path_str = artifacts.get("mcworld")
        if not path_str:
            raise HTTPException(status_code=400, detail="Could not create .mcworld: No base world template found on server. "
                                                        "Please ensure a 'base_world' folder or 'base_world.mcworld' exists in the 'templates' directory "
                                                        "and is not gitignored.")
        return "mcworld", Path(path_str)
    elif mode == "mcaddon":
        return "mcaddon", Path(artifacts["mcaddon"])
    elif mode == "resources":
        return "resources", Path(artifacts["res_mcpack"])
    elif mode == "behavior":
        return "behavior", Path(artifacts["beh_mcpack"])
    return "bundle", Path(artifacts["bundle_zip"])


def _build_and_bundle(res_path: Optional[Path],
                      beh_path: Optional[Path],
                      specs_override: Optional[list[dict]] = None,
                      build_mode: str = "bundle") -> tuple[str, Path, dict]:
    if specs_override:
        specs = [validate_spec(s) for s in specs_override]
        print(f"[BUILD] Overriding specs with: {[s.get('short_name') for s in specs]}")
    else:
        names = list_mob_names()
        if not names:
            specs = [read_mob_spec("current")]
        else:
            specs = [read_mob_spec(n) for n in names]
        print(f"[BUILD] Using all discovered mobs: {[s.get('short_name') for s in specs]}")

    out_dir = Path(tempfile.mkdtemp(prefix="out_"))
    artifacts = build_addon(specs, out_dir, res_path, beh_path)
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
                    build_mode: str = Form("bundle"),
                    target_mobs: Optional[str] = Form(None),
                    specs_json: Optional[str] = Form(None)):
    tmp = Path(tempfile.mkdtemp(prefix="http_"))
    try:
        specs_override = None
        # Prefer specs_json from client (localStorage) over server-side target_mobs
        if specs_json:
            try:
                raw_specs = json.loads(specs_json)
                specs_override = [validate_spec(s) for s in raw_specs]
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid specs_json: {e}")
        elif target_mobs:
            # Fallback: target_mobs is a comma-separated list of mob names from server
            names = [n.strip() for n in target_mobs.split(",") if n.strip()]
            if names:
                specs_override = [read_mob_spec(n) for n in names]
        
        res_path = _save_upload(tmp, resource)
        beh_path = _save_upload(tmp, behavior)
        kind, artifact, artifacts = _build_and_bundle(res_path, beh_path, specs_override=specs_override, build_mode=build_mode)
        
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
    import os
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
