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
    """Create a .mcworld file from resource and behavior packs."""
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

    # Enable cheats so tick.json commands (summon) actually work
    _enable_cheats_in_world(world_root)

    # Spawn entities in the world
    _spawn_entities_in_world(world_root, specs)

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


def build_addon(specs: list[dict], out_dir: Path, res_src: Optional[Path], beh_src: Optional[Path], textures_dir: Optional[Path] = None):
    """Build a complete addon bundle with resource and behavior packs."""
    from backend.core.builders import patch_resource_pack, patch_behavior_pack

    work = Path(tempfile.mkdtemp(prefix="addon_"))
    logs = io.StringIO()
    try:
        logs.write(f"Building bundle with {len(specs)} mobs: {[s.get('short_name') for s in specs]}\n")
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

        out_dir.mkdir(parents=True, exist_ok=True)

        main_spec = specs[0] if specs else validate_spec(default_spec())
        res_mcpack = out_dir / f"{main_spec['short_name']}_resources.mcpack"
        beh_mcpack = out_dir / f"{main_spec['short_name']}_behavior.mcpack"
        zip_dir(res_root, res_mcpack)
        logs.write(f"Wrote {res_mcpack}\n")
        zip_dir(beh_root, beh_mcpack)
        logs.write(f"Wrote {beh_mcpack}\n")

        mcaddon = out_dir / f"{main_spec['short_name']}.mcaddon"
        with zipfile.ZipFile(mcaddon, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root_path, name in [(res_root, "resource_pack"), (beh_root, "behavior_pack")]:
                for p in root_path.rglob("*"):
                    if p.is_file():
                        arc = Path(name) / p.relative_to(root_path)
                        zf.write(p, arcname=str(arc))
        logs.write(f"Wrote {mcaddon}\n")

        bundle_zip = out_dir / f"{main_spec['short_name']}_output_bundle.zip"

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


def _enable_cheats_in_world(world_root: Path):
    """Patch level.dat to enable cheats/commands so tick.json summon works.

    Bedrock level.dat format: 8-byte header (4-byte version LE + 4-byte
    payload length LE) followed by little-endian NBT compound.
    """
    level_dat = world_root / "level.dat"
    if not level_dat.exists():
        print("[WORLD] No level.dat found, cannot enable cheats")
        return

    try:
        import nbtlib

        raw = level_dat.read_bytes()
        if len(raw) < 8:
            print("[WORLD] level.dat too small")
            return

        # Parse the 8-byte Bedrock header
        header_version, payload_len = struct.unpack_from("<II", raw, 0)
        nbt_bytes = raw[8:]

        # Write NBT payload to a temp file so nbtlib can load it
        tmp_nbt = level_dat.parent / "_level_nbt.tmp"
        tmp_nbt.write_bytes(nbt_bytes)

        nbt_file = nbtlib.load(tmp_nbt, byteorder="little")
        tmp_nbt.unlink(missing_ok=True)

        # Enable cheats and commands
        root = nbt_file
        if "" in root:
            root = root[""]

        root["commandsEnabled"] = nbtlib.Byte(1)
        root["commandblocksenabled"] = nbtlib.Byte(1)
        root["cheatsEnabled"] = nbtlib.Byte(1)
        root["commandblockoutput"] = nbtlib.Byte(0)

        # Write modified NBT to temp file
        nbt_file.save(tmp_nbt, byteorder="little")
        new_nbt = tmp_nbt.read_bytes()
        tmp_nbt.unlink(missing_ok=True)

        # Rebuild level.dat with Bedrock header
        new_header = struct.pack("<II", header_version, len(new_nbt))
        level_dat.write_bytes(new_header + new_nbt)
        print("[WORLD] Enabled cheats/commands in level.dat")

    except ImportError:
        print("[WORLD] nbtlib not available, cannot enable cheats")
    except Exception as e:
        print(f"[WORLD] Failed to patch level.dat: {e}")


def _spawn_entities_in_world(world_root: Path, specs: list[dict]):
    """Auto-spawn entities by adding tick functions to the behavior pack.

    Uses a 40-tick (2s) delay then summons right on the player (~ ~ ~).
    """
    beh_pack = world_root / "behavior_packs" / "custom_addon_beh"
    if not beh_pack.exists():
        print("[WORLD] No behavior pack found in world, cannot spawn entities")
        return

    functions_dir = beh_pack / "functions"
    functions_dir.mkdir(parents=True, exist_ok=True)

    # --- spawn_mobs.mcfunction ---
    # Delay 40 ticks (2s) then spawn right on the player (~ ~ ~).
    lines = [
        "scoreboard objectives add addon_spawn dummy",
        "scoreboard players add @a[tag=!mob_spawned] addon_spawn 1",
    ]
    for i, spec in enumerate(specs):
        lines.append(
            f'execute as @a[tag=!mob_spawned,scores={{addon_spawn=40..}},c=1] at @s run '
            f'summon {spec["identifier"]} ~ ~ ~'
        )
    lines.append("tag @a[scores={addon_spawn=40..}] add mob_spawned")

    spawn_fn = functions_dir / "spawn_mobs.mcfunction"
    spawn_fn.write_text("\n".join(lines), encoding="utf-8")

    # --- tick.json ---
    tick_json = {"values": ["spawn_mobs"]}
    (functions_dir / "tick.json").write_text(
        json.dumps(tick_json, indent=2), encoding="utf-8"
    )

    for spec in specs:
        print(f"[WORLD] Will auto-spawn {spec['identifier']} near player on world load")
