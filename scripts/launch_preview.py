#!/usr/bin/env python3
"""
One-Click Play: Inject a generated Behavior Pack into a template .mcworld
and launch Minecraft Bedrock Edition to test it immediately.

Usage (standalone):
    python scripts/launch_preview.py path/to/pack_folder "MyAddon"

Usage (from evaluate_llm.py):
    Called automatically when --launch is passed after a successful test run.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
TEMPLATE_PATH = ASSETS_DIR / "template.mcworld"
TEMP_DIR = PROJECT_ROOT / "temp"


def _remove_from_zip(zip_path: Path, entry_name: str) -> None:
    """Remove a single entry from a zip file by rewriting without it."""
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(zip_path, "r") as zin, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == entry_name:
                    continue
                zout.writestr(item, zin.read(item.filename))
        shutil.move(tmp_path, zip_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def launch_preview(pack_source_path: str | Path, project_name: str) -> Path:
    """Inject *pack_source_path* into a template .mcworld and launch it.

    Parameters
    ----------
    pack_source_path : str | Path
        Directory containing the generated Behavior Pack files (must include
        a ``manifest.json`` at its root).
    project_name : str
        Human-readable project name used for the output file and the
        ``behavior_packs/<name>/`` folder inside the zip.

    Returns
    -------
    Path
        The path to the generated ``.mcworld`` file.

    Raises
    ------
    FileNotFoundError
        If the template world or the pack's ``manifest.json`` is missing.
    """
    pack_path = Path(pack_source_path).resolve()
    manifest_path = pack_path / "manifest.json"

    # ── 1. Prerequisites ────────────────────────────────────────────────
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Template world not found at {TEMPLATE_PATH}\n"
            "Please export a blank Flat World from Minecraft Bedrock and save "
            "it as assets/template.mcworld.\n"
            "Steps:\n"
            "  1. Open Minecraft Bedrock Edition\n"
            "  2. Create New World → Creative, Flat, Cheats On\n"
            "  3. Edit World → Export World\n"
            "  4. Save as assets/template.mcworld"
        )

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No manifest.json found in {pack_path}. "
            "The pack source folder must contain a valid manifest.json."
        )

    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # ── 2. Clone the template ───────────────────────────────────────────
    safe_name = project_name.replace(" ", "_").lower()
    output_path = TEMP_DIR / f"{safe_name}_preview.mcworld"
    shutil.copy2(TEMPLATE_PATH, output_path)
    print(f"  [preview] Cloned template → {output_path.relative_to(PROJECT_ROOT)}")

    # ── 3. Inject the pack into the zip ─────────────────────────────────
    pack_prefix = f"behavior_packs/{safe_name}"
    files_injected = 0

    # Remove existing world_behavior_packs.json to avoid duplicate entry warning
    _remove_from_zip(output_path, "world_behavior_packs.json")

    with zipfile.ZipFile(output_path, "a", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(pack_path):
            for fname in files:
                abs_file = Path(root) / fname
                rel_file = abs_file.relative_to(pack_path)
                arc_name = f"{pack_prefix}/{rel_file.as_posix()}"
                zf.writestr(arc_name, abs_file.read_bytes())
                files_injected += 1

        # ── 4. Auto-enable the pack ────────────────────────────────────
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        header = manifest.get("header", {})
        pack_id = header.get("uuid", "")
        pack_version = header.get("version", [1, 0, 0])

        if not pack_id:
            print("  [preview] WARNING: manifest.json has no header.uuid — "
                  "pack may not auto-enable in-game.")

        world_bp_json = json.dumps([
            {
                "pack_id": pack_id,
                "version": pack_version,
            }
        ], indent=2)
        zf.writestr("world_behavior_packs.json", world_bp_json)

    print(f"  [preview] Injected {files_injected} files into {pack_prefix}/")
    print(f"  [preview] Auto-enabled pack (uuid={pack_id})")

    # ── 5. Launch ───────────────────────────────────────────────────────
    _launch_file(output_path)
    return output_path


def _launch_file(filepath: Path) -> None:
    """Open a file with the OS default handler (Minecraft for .mcworld)."""
    system = platform.system()
    print(f"  [preview] Launching {filepath.name} ...")
    try:
        if system == "Windows":
            os.startfile(str(filepath))
        elif system == "Darwin":
            subprocess.call(["open", str(filepath)])
        else:
            subprocess.call(["xdg-open", str(filepath)])
    except Exception as exc:
        print(f"  [preview] Could not auto-launch: {exc}")
        print(f"  [preview] Manually open: {filepath}")


# ── Standalone entry point ──────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/launch_preview.py <pack_folder> <project_name>")
        sys.exit(1)
    launch_preview(sys.argv[1], sys.argv[2])
