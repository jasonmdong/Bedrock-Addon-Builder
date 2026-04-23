"""World creation and addon bundling utilities."""
import io
import json
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from backend.core.core import WORLD_TEMPLATE_BASES, BASE_DIR
from backend.core.builders import make_uuid, safe_json_load, _manifest_version, make_png_rgba
from backend.schemas.spec_utils import validate_spec, default_spec


def zip_dir(src_dir: Path, out_zip: Path):
    """Compress a directory into a ZIP file."""
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in src_dir.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(src_dir))


def unpack_if_given(path: Optional[Path], dest: Path):
    """Extract a ZIP file and flatten its structure if needed."""
    if not path:
        return None
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "r") as zf:
        zf.extractall(dest)
    # Flatten if manifest not at root
    man = dest / "manifest.json"
    if not man.exists():
        for sub in dest.iterdir():
            if sub.is_dir() and (sub / "manifest.json").exists():
                for child in sub.iterdir():
                    shutil.move(str(child), dest)
                shutil.rmtree(sub, ignore_errors=True)
                break
    return dest


def _world_template_candidates():
    """Yield candidate paths for a world template."""
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
    """Flatten nested world structure if level.dat is in a subdirectory."""
    if (world_root / "level.dat").exists():
        return
    subdirs = [p for p in world_root.iterdir() if p.is_dir()]
    if len(subdirs) == 1 and (subdirs[0] / "level.dat").exists():
        nested = subdirs[0]
        for child in nested.iterdir():
            shutil.move(str(child), world_root)
        shutil.rmtree(nested, ignore_errors=True)


def copy_world_template(dest: Path):
    """Copy a world template to the destination, handling both directories and ZIP files."""
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


def create_mcworld(out_dir: Path,
                   res_root: Path,
                   res_manifest: dict,
                   beh_root: Path,
                   beh_manifest: dict,
                   specs: list[dict]) -> Path:
    """Create a .mcworld file by delegating to MCP's proven build_mcworld.

    Translates our spec format to MCP's mob format, then calls its
    build_mcworld function which is known to produce visible mobs.
    """
    import asyncio
    import base64
    import copy
    import sys

    # Ensure MCP tools are importable
    mcp_root = Path(__file__).resolve().parents[2] / "MCP" / "mcp_server"
    if str(mcp_root) not in sys.path:
        sys.path.insert(0, str(mcp_root))

    from tools.build_mcworld import build_mcworld as _mcp_build
    from backend.core.builders import _fix_geometry_uv

    main_spec = specs[0] if specs else validate_spec(default_spec())
    safe_name = main_spec["short_name"]

    # Translate our specs to MCP mob format
    mcp_mobs = []
    for spec in specs:
        identifier = spec["identifier"]
        mob_name = identifier.split(":")[-1]

        # Read the actual behavior entity JSON from beh_root (written by
        # patch_behavior_pack with all LLM-generated components like
        # minecraft:shooter, minecraft:behavior.ranged_attack, etc.)
        beh_entity_file = beh_root / "entities" / f"{mob_name}.json"
        if beh_entity_file.exists():
            entity_data = json.loads(beh_entity_file.read_bytes())
            print(f"[WORLD] Using LLM-generated behavior entity from {beh_entity_file.name}")
            # Ensure minecraft:loot is wired if loot_drops exist
            loot_drops = spec.get("loot_drops", [])
            if loot_drops:
                ent_comps = entity_data.get("minecraft:entity", {}).get("components", {})
                if "minecraft:loot" not in ent_comps:
                    ent_comps["minecraft:loot"] = {
                        "table": f"loot_tables/entities/{mob_name}.json"
                    }
                    print(f"[WORLD] Auto-wired minecraft:loot for {mob_name}")
        else:
            # Fallback: build a minimal entity
            entity_data = {
                "format_version": "1.16.0",
                "minecraft:entity": {
                    "description": {
                        "identifier": identifier,
                        "is_spawnable": True,
                        "is_summonable": True,
                        "is_experimental": False
                    },
                    "components": {
                        "minecraft:type_family": {"family": [mob_name, "monster"]},
                        "minecraft:health": {"value": int(spec.get("hp", 20)), "max": int(spec.get("hp", 20))},
                        "minecraft:movement.basic": {},
                        "minecraft:jump.static": {},
                        "minecraft:movement": {"value": float(spec.get("speed", 0.30))},
                        "minecraft:attack": {"damage": int(spec.get("damage", 3))},
                        "minecraft:physics": {},
                        "minecraft:collision_box": spec.get("collision_box", {"width": 1, "height": 1}),
                        "minecraft:navigation.walk": {"can_walk": True, "can_pass_doors": True},
                        "minecraft:pushable": {"is_pushable": True, "is_pushable_by_piston": True},
                        "minecraft:behavior.float": {"priority": 0},
                        "minecraft:behavior.hurt_by_target": {"priority": 1},
                        "minecraft:behavior.nearest_attackable_target": {
                            "priority": 2,
                            "entity_types": [{
                                "filters": {"test": "is_family", "subject": "other", "value": "player"},
                                "max_dist": 35
                            }]
                        },
                        "minecraft:behavior.melee_attack": {"priority": 3, "speed_multiplier": 1.0},
                        "minecraft:behavior.random_stroll": {"priority": 6, "speed_multiplier": 1.0},
                        "minecraft:behavior.look_at_player": {"priority": 8, "look_distance": 6.0},
                        "minecraft:behavior.random_look_around": {"priority": 9},
                    }
                }
            }
            print(f"[WORLD] No behavior entity file found, using fallback")

        # Geometry: fix UV overflow, then pass to MCP build
        geometry_data = None
        geo_json = spec.get("geometry_json")
        if geo_json and isinstance(geo_json, dict) and geo_json.get("minecraft:geometry"):
            geometry_data = _fix_geometry_uv(copy.deepcopy(geo_json))

        # Texture: read from res_root if available, else None
        texture_b64 = None
        tex_path = res_root / "textures" / "entity" / f"{mob_name}.png"
        if tex_path.exists():
            texture_b64 = base64.b64encode(tex_path.read_bytes()).decode("utf-8")

        # Egg colors
        egg_base = spec.get("egg_base", "#4A7023")
        egg_overlay = spec.get("egg_overlay", "#2E4F1E")

        # Scale
        scale = float(spec.get("scale", 1.0))

        # Build metadata for MCP pipeline
        mcp_metadata = {
            "display_name": spec.get("display_name", mob_name.replace("_", " ").title()),
            "suggested_style": "zombie",
            "suggested_colors": [egg_base, egg_overlay],
            "scale": scale,
        }

        # Pass loot_drops to MCP so _build_loot_table creates proper drops
        loot_drops = spec.get("loot_drops", [])
        if loot_drops and isinstance(loot_drops, list):
            mcp_metadata["loot_drops"] = loot_drops

        mcp_mobs.append({
            "entity": entity_data,
            "metadata": mcp_metadata,
            "texture_base64": texture_b64,
            "geometry_data": geometry_data,
        })

    # Call MCP's build_mcworld (async def but contains no await calls).
    # Run in a new thread to avoid conflicts with FastAPI's event loop.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result_json = pool.submit(
            asyncio.run, _mcp_build(mcp_mobs, safe_name)
        ).result()

    result = json.loads(result_json)
    mcworld_bytes = base64.b64decode(result["file_base64"])

    # ── Single-pass ZIP rebuild: replace MCP entity/geo files AND inject animations ──
    # MCP generates entity files without the scripts block for animation wiring.
    # We rebuild the ZIP once, replacing MCP entity/geometry with our pre-built files
    # and injecting all animation files in the same pass (avoids a costly second rebuild).
    with zipfile.ZipFile(io.BytesIO(mcworld_bytes), "r") as src_zf:
        # Discover pack prefixes in one pass over namelist
        beh_pack_prefix = None
        res_pack_prefix = None
        for item in src_zf.namelist():
            if beh_pack_prefix is None and "behavior_packs/" in item and "/manifest.json" in item:
                beh_pack_prefix = item.split("/manifest.json")[0]
            if res_pack_prefix is None and "resource_packs/" in item and "/manifest.json" in item:
                res_pack_prefix = item.split("/manifest.json")[0]
            if beh_pack_prefix and res_pack_prefix:
                break

        # Determine which MCP-generated entries to drop (entity + geometry — we replace these)
        entries_to_remove = set()
        if res_pack_prefix:
            entries_to_remove = {
                entry for entry in src_zf.namelist()
                if f"{res_pack_prefix}/entity/" in entry
                or f"{res_pack_prefix}/models/entity/" in entry
            }
            if entries_to_remove:
                print(f"[WORLD] Removing {len(entries_to_remove)} MCP-generated entity/geometry files from ZIP")

        temp_buffer = io.BytesIO()
        with zipfile.ZipFile(temp_buffer, "w", zipfile.ZIP_DEFLATED) as dst_zf:
            # Copy all surviving MCP entries in one pass
            for entry in src_zf.namelist():
                if entry not in entries_to_remove:
                    dst_zf.writestr(entry, src_zf.read(entry))

            # ── Inject our RP replacements and animation files ──────────────
            if res_pack_prefix:
                # Entity files (correct geometry references + scripts block)
                ent_dir = res_root / "entity"
                if ent_dir.exists():
                    for ent_file in sorted(ent_dir.glob("*.entity.json")):
                        content = ent_file.read_text()
                        dst_zf.writestr(f"{res_pack_prefix}/entity/{ent_file.name}", content)
                        if '"scripts"' in content:
                            print(f"[WORLD] ✓ Using {ent_file.name} with scripts block")
                        else:
                            print(f"[WORLD] ✗ WARNING: {ent_file.name} missing scripts block")

                # Geometry files (correctly renamed identifiers matching entity.json)
                geo_dir = res_root / "models" / "entity"
                if geo_dir.exists():
                    for geo_file in sorted(geo_dir.glob("*.geo.json")):
                        dst_zf.writestr(f"{res_pack_prefix}/models/entity/{geo_file.name}", geo_file.read_text())
                        print(f"[WORLD] ✓ Injected geometry {geo_file.name}")

                # RP animation files
                anim_dir = res_root / "animations"
                if anim_dir.exists():
                    for anim_file in anim_dir.glob("*.animation.json"):
                        dst_zf.writestr(f"{res_pack_prefix}/animations/{anim_file.name}", anim_file.read_text())
                        print(f"[WORLD] Injected {anim_file.name} into resource pack")

                # RP animation controller files
                ac_dir = res_root / "animation_controllers"
                if ac_dir.exists():
                    for ac_file in ac_dir.glob("*.animation_controllers.json"):
                        dst_zf.writestr(f"{res_pack_prefix}/animation_controllers/{ac_file.name}", ac_file.read_text())
                        print(f"[WORLD] Injected {ac_file.name} into resource pack")

            # ── Inject BP animation files ───────────────────────────────────
            if beh_pack_prefix:
                anim_dir = beh_root / "animations"
                if anim_dir.exists():
                    for anim_file in anim_dir.glob("*.json"):
                        dst_zf.writestr(f"{beh_pack_prefix}/animations/{anim_file.name}", anim_file.read_text())
                        print(f"[WORLD] Injected {anim_file.name} into behavior pack")

                ac_dir = beh_root / "animation_controllers"
                if ac_dir.exists():
                    for ac_file in ac_dir.glob("*.json"):
                        dst_zf.writestr(f"{beh_pack_prefix}/animation_controllers/{ac_file.name}", ac_file.read_text())
                        print(f"[WORLD] Injected {ac_file.name} into behavior pack")

    mcworld_bytes = temp_buffer.getvalue()

    mcworld_path = out_dir / f"{safe_name}.mcworld"
    mcworld_path.write_bytes(mcworld_bytes)

    for ident in result.get("mob_identifiers", []):
        print(f"[WORLD] Will auto-spawn {ident} near player on world load")
    print(f"[WORLD] Generated .mcworld via MCP pipeline with injected animations")

    return mcworld_path


def build_addon(specs: list[dict], out_dir: Path, res_src: Optional[Path], beh_src: Optional[Path], textures_dir: Optional[Path] = None, build_mode: str = "bundle"):
    """Build a complete addon bundle with resource and behavior packs.
    
    build_mode controls which artifacts are produced:
      "bundle"   → everything (res, beh, mcaddon, mcworld, bundle zip)
      "mcworld"  → only mcworld (skips mcpack/mcaddon/bundle zip)
      "mcaddon"  → only mcaddon (skips mcworld and bundle zip)
      "resources"/"behavior" → only the respective mcpack
    """
    from backend.core.builders import patch_resource_pack, patch_behavior_pack

    mode = (build_mode or "bundle").lower()
    need_mcworld = mode in ("bundle", "mcworld")
    need_mcpacks = mode in ("bundle", "resources", "behavior")
    need_mcaddon = mode in ("bundle", "mcaddon")
    need_bundle  = mode == "bundle"

    work = Path(tempfile.mkdtemp(prefix="addon_"))
    logs = io.StringIO()
    try:
        logs.write(f"Building {mode} with {len(specs)} mobs: {[s.get('short_name') for s in specs]}\n")
        print(f"[BUILD] Overriding specs with: {[s.get('short_name') for s in specs]}")
        res_root = work / "res"
        beh_root = work / "beh"
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

        res_manifest = patch_resource_pack(res_root, specs, textures_dir=textures_dir)
        beh_manifest = patch_behavior_pack(beh_root, specs)

        # Cross-link manifests: behavior pack depends on resource pack and vice versa.
        # Without this, Minecraft treats them as unrelated packs and the client
        # entity definition (geometry, textures, render controller) never applies
        # to the server entity — making the mob invisible in-game.
        res_uuid = res_manifest.get("header", {}).get("uuid", "")
        res_ver = res_manifest.get("header", {}).get("version", [1, 0, 0])
        beh_uuid = beh_manifest.get("header", {}).get("uuid", "")
        beh_ver = beh_manifest.get("header", {}).get("version", [1, 0, 0])

        if res_uuid and beh_uuid:
            beh_manifest.setdefault("dependencies", [])
            beh_manifest["dependencies"].append({"uuid": res_uuid, "version": res_ver})
            (beh_root / "manifest.json").write_bytes(
                json.dumps(beh_manifest, indent=2).encode("utf-8")
            )

            res_manifest.setdefault("dependencies", [])
            res_manifest["dependencies"].append({"uuid": beh_uuid, "version": beh_ver})
            (res_root / "manifest.json").write_bytes(
                json.dumps(res_manifest, indent=2).encode("utf-8")
            )
            logs.write("Linked resource ↔ behavior pack dependencies\n")

        out_dir.mkdir(parents=True, exist_ok=True)

        main_spec = specs[0] if specs else validate_spec(default_spec())
        res_mcpack = out_dir / f"{main_spec['short_name']}_resources.mcpack"
        beh_mcpack = out_dir / f"{main_spec['short_name']}_behavior.mcpack"

        if need_mcpacks or need_mcaddon:
            zip_dir(res_root, res_mcpack)
            logs.write(f"Wrote {res_mcpack}\n")
            zip_dir(beh_root, beh_mcpack)
            logs.write(f"Wrote {beh_mcpack}\n")

        mcaddon = out_dir / f"{main_spec['short_name']}.mcaddon"
        if need_mcaddon:
            with zipfile.ZipFile(mcaddon, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for root_path, name in [(res_root, "resource_pack"), (beh_root, "behavior_pack")]:
                    for p in root_path.rglob("*"):
                        if p.is_file():
                            arc = Path(name) / p.relative_to(root_path)
                            zf.write(p, arcname=str(arc))
            logs.write(f"Wrote {mcaddon}\n")

        bundle_zip = out_dir / f"{main_spec['short_name']}_output_bundle.zip"

        mcworld = None
        if need_mcworld:
            try:
                mcworld = create_mcworld(out_dir, res_root, res_manifest, beh_root, beh_manifest, specs)
            except Exception as exc:
                import traceback; traceback.print_exc()
                print(f"[WARN] Failed to create .mcworld: {exc}")
                logs.write(f"Warning: .mcworld could not be created.\n")

        spec_json_path = out_dir / "specs.json"
        spec_json_path.write_bytes(json.dumps(specs, indent=2).encode("utf-8"))

        if need_bundle:
            # Use ZIP_STORED for mcpack/mcaddon/mcworld entries — they are already
            # ZIP-compressed internally, so DEFLATE gains nothing and just wastes CPU.
            with zipfile.ZipFile(bundle_zip, "w") as zf:
                zf.write(res_mcpack, arcname=res_mcpack.name, compress_type=zipfile.ZIP_STORED)
                zf.write(beh_mcpack, arcname=beh_mcpack.name, compress_type=zipfile.ZIP_STORED)
                zf.write(mcaddon, arcname=mcaddon.name, compress_type=zipfile.ZIP_STORED)
                if mcworld:
                    zf.write(mcworld, arcname=mcworld.name, compress_type=zipfile.ZIP_STORED)
                zf.write(spec_json_path, arcname="specs.json")
                zf.writestr("BUILD_LOG.txt", logs.getvalue())

        return {
            "res_mcpack": str(res_mcpack) if res_mcpack.exists() else "",
            "beh_mcpack": str(beh_mcpack) if beh_mcpack.exists() else "",
            "mcaddon": str(mcaddon) if mcaddon.exists() else "",
            "mcworld": str(mcworld) if mcworld else "",
            "bundle_zip": str(bundle_zip) if bundle_zip.exists() else "",
            "log": logs.getvalue()
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ─── Bedrock Little-Endian NBT Writer (ported from MCP) ──────────────────────

_TAG_END = 0
_TAG_BYTE = 1
_TAG_SHORT = 2
_TAG_INT = 3
_TAG_LONG = 4
_TAG_FLOAT = 5
_TAG_STRING = 8
_TAG_LIST = 9
_TAG_COMPOUND = 10


def _nbt_write_tag_name(buf: io.BytesIO, tag_type: int, name: str):
    """Write tag type byte + name (little-endian short length + utf-8)."""
    buf.write(struct.pack("<B", tag_type))
    encoded = name.encode("utf-8")
    buf.write(struct.pack("<H", len(encoded)))
    buf.write(encoded)


def _nbt_write_string(buf: io.BytesIO, value: str):
    encoded = value.encode("utf-8")
    buf.write(struct.pack("<H", len(encoded)))
    buf.write(encoded)


def _nbt_write_compound(buf: io.BytesIO, data: dict):
    """Recursively write a compound tag in Bedrock little-endian NBT."""
    for key, value in data.items():
        if isinstance(value, dict):
            if "_type" in value:
                t = value["_type"]
                v = value["_value"]
                if t == "byte":
                    _nbt_write_tag_name(buf, _TAG_BYTE, key)
                    buf.write(struct.pack("<b", v))
                elif t == "short":
                    _nbt_write_tag_name(buf, _TAG_SHORT, key)
                    buf.write(struct.pack("<h", v))
                elif t == "int":
                    _nbt_write_tag_name(buf, _TAG_INT, key)
                    buf.write(struct.pack("<i", v))
                elif t == "long":
                    _nbt_write_tag_name(buf, _TAG_LONG, key)
                    buf.write(struct.pack("<q", v))
                elif t == "float":
                    _nbt_write_tag_name(buf, _TAG_FLOAT, key)
                    buf.write(struct.pack("<f", v))
                elif t == "string":
                    _nbt_write_tag_name(buf, _TAG_STRING, key)
                    _nbt_write_string(buf, v)
                elif t == "int_list":
                    _nbt_write_tag_name(buf, _TAG_LIST, key)
                    buf.write(struct.pack("<B", _TAG_INT))
                    buf.write(struct.pack("<i", len(v)))
                    for item in v:
                        buf.write(struct.pack("<i", item))
            else:
                _nbt_write_tag_name(buf, _TAG_COMPOUND, key)
                _nbt_write_compound(buf, value)
        elif isinstance(value, str):
            _nbt_write_tag_name(buf, _TAG_STRING, key)
            _nbt_write_string(buf, value)
        elif isinstance(value, bool):
            _nbt_write_tag_name(buf, _TAG_BYTE, key)
            buf.write(struct.pack("<b", 1 if value else 0))
        elif isinstance(value, int):
            _nbt_write_tag_name(buf, _TAG_INT, key)
            buf.write(struct.pack("<i", value))
        elif isinstance(value, float):
            _nbt_write_tag_name(buf, _TAG_FLOAT, key)
            buf.write(struct.pack("<f", value))
        elif isinstance(value, list):
            _nbt_write_tag_name(buf, _TAG_LIST, key)
            if len(value) > 0 and isinstance(value[0], int):
                buf.write(struct.pack("<B", _TAG_INT))
                buf.write(struct.pack("<i", len(value)))
                for item in value:
                    buf.write(struct.pack("<i", item))
            else:
                buf.write(struct.pack("<B", _TAG_END))
                buf.write(struct.pack("<i", 0))
    buf.write(struct.pack("<B", _TAG_END))


def _build_level_dat(world_name: str) -> bytes:
    """Build a minimal Bedrock level.dat binary from scratch.

    8-byte header (version=10, payload_length) + little-endian NBT compound.
    Ported from MCP's build_mcworld tool.
    """
    import time as _time

    flat_layers = json.dumps({
        "biome_id": 1,
        "block_layers": [
            {"block_name": "minecraft:bedrock", "count": 1},
            {"block_name": "minecraft:dirt", "count": 2},
            {"block_name": "minecraft:grass_block", "count": 1}
        ],
        "encoding_version": 6,
        "structure_options": None,
        "world_version": "version.post_1_18"
    })

    nbt_data = {
        "abilities": {
            "attackmobs": {"_type": "byte", "_value": 1},
            "attackplayers": {"_type": "byte", "_value": 1},
            "build": {"_type": "byte", "_value": 1},
            "doorsandswitches": {"_type": "byte", "_value": 1},
            "flying": {"_type": "byte", "_value": 0},
            "flySpeed": {"_type": "float", "_value": 0.05},
            "instabuild": {"_type": "byte", "_value": 0},
            "invulnerable": {"_type": "byte", "_value": 0},
            "lightning": {"_type": "byte", "_value": 0},
            "mayfly": {"_type": "byte", "_value": 1},
            "mine": {"_type": "byte", "_value": 1},
            "op": {"_type": "byte", "_value": 1},
            "opencontainers": {"_type": "byte", "_value": 1},
            "teleport": {"_type": "byte", "_value": 1},
            "walkSpeed": {"_type": "float", "_value": 0.1},
        },
        "baseGameVersion": "*",
        "cheatsEnabled": {"_type": "byte", "_value": 1},
        "commandblockoutput": {"_type": "byte", "_value": 1},
        "commandblocksenabled": {"_type": "byte", "_value": 1},
        "commandsEnabled": {"_type": "byte", "_value": 1},
        "currentTick": {"_type": "long", "_value": 1},
        "Difficulty": 1,
        "dodaylightcycle": {"_type": "byte", "_value": 1},
        "doentitydrops": {"_type": "byte", "_value": 1},
        "dofiretick": {"_type": "byte", "_value": 1},
        "doimmediaterespawn": {"_type": "byte", "_value": 0},
        "doinsomnia": {"_type": "byte", "_value": 1},
        "domobloot": {"_type": "byte", "_value": 1},
        "domobspawning": {"_type": "byte", "_value": 1},
        "dotiledrops": {"_type": "byte", "_value": 1},
        "doweathercycle": {"_type": "byte", "_value": 1},
        "drowningdamage": {"_type": "byte", "_value": 1},
        "falldamage": {"_type": "byte", "_value": 1},
        "firedamage": {"_type": "byte", "_value": 1},
        "FlatWorldLayers": flat_layers,
        "ForceGameType": {"_type": "byte", "_value": 0},
        "functioncommandlimit": 10000,
        "GameType": 1,  # Creative
        "Generator": 2,  # Flat
        "hasBeenLoadedInCreative": {"_type": "byte", "_value": 1},
        "immutableWorld": {"_type": "byte", "_value": 0},
        "InventoryVersion": "1.20.0",
        "keepinventory": {"_type": "byte", "_value": 1},
        "LANBroadcast": {"_type": "byte", "_value": 1},
        "LANBroadcastIntent": {"_type": "byte", "_value": 1},
        "lastOpenedWithVersion": [1, 20, 0, 0, 0],
        "LastPlayed": {"_type": "long", "_value": int(_time.time())},
        "LevelName": world_name,
        "lightningLevel": {"_type": "float", "_value": 0.0},
        "lightningTime": 0,
        "LimitedWorldOriginX": 0,
        "LimitedWorldOriginY": 32767,
        "LimitedWorldOriginZ": 0,
        "maxcommandchainlength": 65535,
        "MinimumCompatibleClientVersion": [1, 20, 0, 0, 0],
        "mobgriefing": {"_type": "byte", "_value": 1},
        "MultiplayerGame": {"_type": "byte", "_value": 1},
        "MultiplayerGameIntent": {"_type": "byte", "_value": 1},
        "naturalregeneration": {"_type": "byte", "_value": 1},
        "NetherScale": 8,
        "NetworkVersion": 594,
        "permissionsLevel": 1,
        "Platform": 2,
        "PlatformBroadcastIntent": 3,
        "pvp": {"_type": "byte", "_value": 1},
        "rainLevel": {"_type": "float", "_value": 0.0},
        "rainTime": 0,
        "RandomSeed": {"_type": "long", "_value": 12345},
        "randomtickspeed": 1,
        "sendcommandfeedback": {"_type": "byte", "_value": 1},
        "serverChunkTickRange": 4,
        "showcoordinates": {"_type": "byte", "_value": 1},
        "showdeathmessages": {"_type": "byte", "_value": 1},
        "spawnMobs": {"_type": "byte", "_value": 1},
        "spawnradius": 5,
        "SpawnX": 0,
        "SpawnY": 4,
        "SpawnZ": 0,
        "startWithMapEnabled": {"_type": "byte", "_value": 0},
        "StorageVersion": 10,
        "texturePacksRequired": {"_type": "byte", "_value": 0},
        "Time": {"_type": "long", "_value": 0},
        "tntexplodes": {"_type": "byte", "_value": 1},
        "useMsaGamertagsOnly": {"_type": "byte", "_value": 0},
        "WorldVersion": 1,
        "XBLBroadcastIntent": 3,
        "experiments": {
            "experiments_ever_used": {"_type": "byte", "_value": 0},
            "saved_with_toggled_experiments": {"_type": "byte", "_value": 0},
        },
    }

    payload = io.BytesIO()
    _nbt_write_tag_name(payload, _TAG_COMPOUND, "")
    _nbt_write_compound(payload, nbt_data)
    nbt_bytes = payload.getvalue()

    header = struct.pack("<II", 10, len(nbt_bytes))
    return header + nbt_bytes
