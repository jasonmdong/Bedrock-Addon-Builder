"""Builders for resource packs and behavior packs."""
import json
import uuid
from pathlib import Path

from core import DEFAULTS, COLOR_WORDS
from spec_utils import default_spec, validate_spec


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


def patch_resource_pack(res_root: Path, specs: list[dict]):
    """Patch a resource pack with custom mob textures, entities, and manifests."""
    ent_dir = res_root / "entity"
    ent_dir.mkdir(parents=True, exist_ok=True)

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

    first_png = None

    for spec in specs:
        client_file = ent_dir / f"{spec['short_name']}.client.entity.json"
        textures_dir = res_root / "textures" / "entity" / spec["short_name"]
        textures_dir.mkdir(parents=True, exist_ok=True)

        png_path = textures_dir / f"{spec['short_name']}.png"
        mers_tga = textures_dir / f"{spec['short_name']}_mers.tga"
        texset = textures_dir / f"{spec['short_name']}.texture_set.json"

        # Try to copy persistent texture if it exists
        persistent_png = Path("specs") / f"{spec['short_name']}.png"
        if persistent_png.exists():
            import shutil
            shutil.copyfile(persistent_png, png_path)

        if not png_path.exists():
            col = spec.get("color_rgb", COLOR_WORDS.get("red"))
            png = make_png_rgba(64, 64, *col, 255)
            png_path.write_bytes(png)

        if not first_png:
            first_png = png_path

        if not mers_tga.exists():
            col = spec.get("color_rgb", COLOR_WORDS.get("red"))
            write_tga(mers_tga, 128, 128, *col, 255)

        if not texset.exists():
            texset.write_text(json.dumps({
                "format_version": "1.21.30",
                "minecraft:texture_set": {
                    "color": spec["short_name"],
                    "metalness_emissive_roughness_subsurface": f"{spec['short_name']}_mers"
                }
            }, indent=2), encoding="utf-8")

        scale = float(spec.get("scale", 1.0))
        client = {
            "format_version": "1.21.0",
            "minecraft:client_entity": {
                "description": {
                    "identifier": spec["identifier"],
                    "min_engine_version": "1.8.0",
                    "materials": {"default": "entity_alphatest"},
                    "textures": {"default": f"textures/entity/{spec['short_name']}/{spec['short_name']}"},
                    "geometry": {"default": spec.get("geometry", DEFAULTS["geometry"])},
                    "render_controllers": [spec.get("render_controller", DEFAULTS["render_controller"])]
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

    man = res_root / "manifest.json"
    if man.exists():
        manifest = safe_json_load(man) or {}
    else:
        manifest = {"format_version": 2, "header": {}, "modules": []}
    manifest["header"]["description"] = f"{main_spec['display_name']} Resources"
    manifest["header"]["name"] = f"{main_spec['display_name']} Resources"
    manifest["header"]["uuid"] = make_uuid()
    manifest["header"]["version"] = [1, 0, 0]
    ensure_min_engine(manifest, main_spec["engine_min"])
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
    man.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def patch_behavior_pack(beh_root: Path, specs: list[dict]):
    """Patch a behavior pack with custom mob entities and manifests."""
    ent_dir = beh_root / "entities"
    ent_dir.mkdir(parents=True, exist_ok=True)

    texts_dir = beh_root / "texts"
    texts_dir.mkdir(parents=True, exist_ok=True)
    lang_file = texts_dir / "en_US.lang"
    lang_lines = []

    for spec in specs:
        ent_file = ent_dir / f"{spec['short_name']}.entity.json"

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
                    "spawn_egg": {
                        "base_color": spec.get("egg_base", DEFAULTS["egg_base"]),
                        "overlay_color": spec.get("egg_overlay", DEFAULTS["egg_overlay"])
                    }
                },
                "components": {
                    "minecraft:type_family": {"family": [spec["short_name"], "monster"]},
                    "minecraft:health": {"value": int(spec["hp"]), "max": int(spec["hp"])},
                    "minecraft:movement.basic": {},
                    "minecraft:movement": {"value": float(spec.get("speed", 0.30))},
                    "minecraft:attack": {"damage": float(spec["damage"])},
                    "minecraft:physics": {"has_gravity": True, "has_collision": True},
                    "minecraft:collision_box": spec["collision_box"],
                    "minecraft:navigation.walk": {"can_pass_doors": True, "avoid_water": True},
                    "minecraft:follow_range": {"value": 40.0},
                    "minecraft:knockback_resistance": {"value": 0.5},
                    "minecraft:pushable": {"is_pushable": True},
                    "minecraft:despawn": {"despawn_time": 6000},
                    "minecraft:behavior.hurt_by_target": {"priority": 0},
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
                                "filters": {"test": "is_family", "subject": "other", "value": "player"},
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
                    "minecraft:behavior.look_at_player": {"priority": 5, "look_distance": 8.0},
                    "minecraft:behavior.random_stroll": {"priority": 6, "speed_multiplier": 1.0}
                }
            }
        }
        ent_file.write_text(json.dumps(entity, indent=2), encoding="utf-8")

    if lang_lines:
        lang_file.write_text("\n".join(lang_lines), encoding="utf-8")

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
    ensure_min_engine(manifest, main_spec["engine_min"])
    manifest["modules"] = [{
        "description": "behavior",
        "type": "data",
        "uuid": make_uuid(),
        "version": [1, 0, 0]
    }]
    man.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
