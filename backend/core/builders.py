"""Builders for resource packs and behavior packs."""
import json
import uuid
from pathlib import Path

from backend.core.core import DEFAULTS, COLOR_WORDS
from backend.schemas.spec_utils import default_spec, validate_spec


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

    rc_dir = res_root / "render_controllers"
    rc_dir.mkdir(parents=True, exist_ok=True)

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

    # Create a truly generic render controller for custom geometries
    generic_rc_path = rc_dir / "custom_mob.render_controller.json"
    generic_rc = {
        "format_version": "1.8.0",
        "render_controllers": {
            "controller.render.custom_mob": {
                "geometry": "Geometry.default",
                "materials": [ { "*": "Material.default" } ],
                "textures": [ "Texture.default" ]
            }
        }
    }
    generic_rc_path.write_text(json.dumps(generic_rc, indent=2), encoding="utf-8")

    first_png = None

    for spec in specs:
        client_file = ent_dir / f"{spec['short_name']}.client.entity.json"
        
        # Handle custom geometry
        actual_geometry = spec.get("geometry", DEFAULTS["geometry"])
        actual_rc = spec.get("render_controller", DEFAULTS["render_controller"])
        
        custom_geo = spec.get("geometry_json")
        if custom_geo and isinstance(custom_geo, dict) and "minecraft:geometry" in custom_geo:
            # Deep-copy to avoid mutating the original spec dict
            import copy
            custom_geo = copy.deepcopy(custom_geo)

            # Ensure the geometry has a unique identifier based on the mob name.
            # Keep only the first geometry entry to avoid identifier conflicts
            # (some Mojang files contain multiple versions of the same geometry).
            unique_geo_id = f"geometry.{spec['short_name']}.custom"
            try:
                custom_geo["minecraft:geometry"] = [custom_geo["minecraft:geometry"][0]]
                custom_geo["minecraft:geometry"][0]["description"]["identifier"] = unique_geo_id
                actual_geometry = unique_geo_id
                actual_rc = "controller.render.custom_mob"
            except (KeyError, IndexError):
                pass
                
            geo_file = geo_dir / f"{spec['short_name']}.geo.json"
            geo_file.write_text(json.dumps(custom_geo, indent=2), encoding="utf-8")
        
        mob_textures_dir = res_root / "textures" / "entity" / spec["short_name"]
        mob_textures_dir.mkdir(parents=True, exist_ok=True)

        png_path = mob_textures_dir / f"{spec['short_name']}.png"

        # Try to copy texture from client-provided textures_dir first
        if textures_dir:
            client_texture = textures_dir / f"{spec['short_name']}.png"
            if client_texture.exists():
                shutil.copyfile(client_texture, png_path)
        
        # Fallback: try server-side SPECS_DIR
        if not png_path.exists():
            from backend.core.core import SPECS_DIR
            persistent_png = SPECS_DIR / f"{spec['short_name']}.png"
            if persistent_png.exists():
                shutil.copyfile(persistent_png, png_path)

        if not png_path.exists():
            col = spec.get("color_rgb", COLOR_WORDS.get("red"))
            # Use texture dimensions from geometry if available, else default 64x64
            tex_w, tex_h = 64, 64
            try:
                geo = spec.get("geometry_json", {})
                desc = geo.get("minecraft:geometry", [{}])[0].get("description", {})
                tex_w = int(desc.get("texture_width", 64))
                tex_h = int(desc.get("texture_height", 64))
            except (IndexError, KeyError, TypeError, ValueError):
                pass
            png = make_png_rgba(tex_w, tex_h, *col, 255)
            png_path.write_bytes(png)

        if not first_png:
            first_png = png_path


        scale = float(spec.get("scale", 1.0))
        client = {
            "format_version": "1.10.0",
            "minecraft:client_entity": {
                "description": {
                    "identifier": spec["identifier"],
                    "materials": {"default": "entity_alphatest"},
                    "textures": {"default": f"textures/entity/{spec['short_name']}/{spec['short_name']}"},
                    "geometry": {"default": actual_geometry},
                    "render_controllers": [actual_rc]
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
                    "minecraft:jump.static": {},
                    "minecraft:movement": {"value": float(spec.get("speed", 0.30))},
                    "minecraft:attack": {"damage": float(spec["damage"])},
                    "minecraft:physics": {},
                    "minecraft:collision_box": spec["collision_box"],
                    "minecraft:navigation.walk": {
                        "can_walk": True,
                        "can_pass_doors": True,
                        "avoid_water": True
                    },
                    "minecraft:knockback_resistance": {"value": 0.5},
                    "minecraft:pushable": {"is_pushable": True, "is_pushable_by_piston": True},
                    "minecraft:behavior.hurt_by_target": {"priority": 1},
                    "minecraft:behavior.nearest_attackable_target": {
                        "priority": 2,
                        "within_radius": 25,
                        "reselect_targets": True,
                        "entity_types": [
                            {
                                "filters": {
                                    "any_of": [
                                        {"test": "is_family", "subject": "other", "value": "player"}
                                    ]
                                },
                                "max_dist": 35
                            }
                        ]
                    },
                    "minecraft:behavior.melee_attack": {
                        "priority": 3,
                        "speed_multiplier": 1.0,
                        "track_target": True
                    },
                    "minecraft:behavior.look_at_player": {"priority": 7, "look_distance": 6.0, "probability": 0.02},
                    "minecraft:behavior.random_look_around": {"priority": 8},
                    "minecraft:behavior.random_stroll": {"priority": 6, "speed_multiplier": 1.0}
                }
            }
        }

        # Merge custom components from spec
        custom_components = spec.get("components", {})
        if custom_components:
            for k, v in custom_components.items():
                if v is None:
                    if k in entity["minecraft:entity"]["components"]:
                        del entity["minecraft:entity"]["components"][k]
                else:
                    entity["minecraft:entity"]["components"][k] = v

        ent_file.write_text(json.dumps(entity, indent=2), encoding="utf-8")

    if lang_lines:
        lang_file.write_text("\n".join(lang_lines), encoding="utf-8")

    # Add tick function so entities auto-spawn when pack is used (mcpack, mcaddon, or mcworld).
    # Delay 40 ticks (2s) then spawn right on the player (~ ~ ~).
    functions_dir = beh_root / "functions"
    functions_dir.mkdir(parents=True, exist_ok=True)
    spawn_lines = [
        "scoreboard objectives add addon_spawn dummy",
        "scoreboard players add @a[tag=!mob_spawned] addon_spawn 1",
    ]
    for i, spec in enumerate(specs):
        spawn_lines.append(
            f'execute @a[tag=!mob_spawned,scores={{addon_spawn=40..}},c=1] ~ ~ ~ '
            f'summon {spec["identifier"]} ~ ~ ~'
        )
    spawn_lines.append("tag @a[scores={addon_spawn=40..}] add mob_spawned")
    (functions_dir / "spawn_mobs.mcfunction").write_text("\n".join(spawn_lines), encoding="utf-8")
    (functions_dir / "tick.json").write_text(
        json.dumps({"values": ["spawn_mobs"]}, indent=2), encoding="utf-8"
    )

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
