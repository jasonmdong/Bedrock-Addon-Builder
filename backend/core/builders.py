"""Builders for resource packs and behavior packs."""
import json
import uuid
from pathlib import Path

from backend.core.core import DEFAULTS, COLOR_WORDS
from backend.schemas.spec_utils import default_spec, validate_spec


def _write_text(path: Path, content: str):
    """Write text with Unix line endings (LF only). Windows defaults to CRLF
    which can break Minecraft's mcfunction and JSON parsers."""
    path.write_bytes(content.encode("utf-8"))


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
                
            custom_geo = _fix_geometry_uv(custom_geo)
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
            from backend.core.core import SPECS_DIR
            persistent_png = SPECS_DIR / f"{spec['short_name']}.png"
            if persistent_png.exists():
                shutil.copyfile(persistent_png, png_path)

        if not png_path.exists():
            # Try procedural UV-mapped texture first (body-part colors,
            # eyes, patterns) then fall back to solid-color placeholder.
            geo_for_tex = spec.get("geometry_json")
            if not geo_for_tex:
                written_geo = geo_dir / f"{spec['short_name']}.geo.json"
                if written_geo.exists():
                    try:
                        geo_for_tex = json.loads(written_geo.read_bytes())
                    except Exception:
                        geo_for_tex = None

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
        client = {
            "format_version": "1.10.0",
            "minecraft:client_entity": {
                "description": {
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
            }
        }
        if abs(scale - 1.0) > 1e-6:
            client["minecraft:client_entity"]["description"]["scale"] = scale
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

        # If mob has ranged attack (shooter), remove melee_attack so it
        # actually fires projectiles instead of always running up to melee.
        if "minecraft:shooter" in comps and "minecraft:behavior.ranged_attack" in comps:
            comps.pop("minecraft:behavior.melee_attack", None)

        # Normalize shooter projectile: minecraft:fireball (ghast) is unreliable
        # for custom entities. Use minecraft:small_fireball (blaze) which always works.
        if "minecraft:shooter" in comps:
            shooter = comps["minecraft:shooter"]
            proj = shooter.get("def", "")
            if proj in ("minecraft:fireball", "minecraft:dragon_fireball"):
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

        # If mob uses fly movement, remove conflicting walk components
        if "minecraft:movement.fly" in comps:
            comps.pop("minecraft:movement.basic", None)
        if "minecraft:navigation.fly" in comps:
            comps.pop("minecraft:navigation.walk", None)

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
