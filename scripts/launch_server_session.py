#!/usr/bin/env python3
"""
Instant Play & Spawn: Launch a Bedrock Dedicated Server with the generated
pack pre-installed, auto-connect the client, and give/summon the item or
entity as soon as the player joins.

Usage (standalone):
    python scripts/launch_server_session.py path/to/pack_folder "my:custom_sword" entity_logic_ai

Usage (from evaluate_llm.py):
    Called automatically when --launch is passed after a successful test run.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BDS_DIR = PROJECT_ROOT / "bedrock_server"
BDS_EXE = BDS_DIR / "bedrock_server.exe"

# Default server.properties for a fast-loading test environment
_SERVER_PROPERTIES = textwrap.dedent("""\
    server-name=Bedrock Addon Test
    gamemode=creative
    difficulty=peaceful
    allow-cheats=true
    level-name=Bedrock-Addon-Test
    level-type=flat
    online-mode=false
    server-port=19132
    server-portv6=19133
    max-players=1
    view-distance=10
    tick-distance=4
    player-idle-timeout=0
    default-player-permission-level=operator
    texturepack-required=false
    content-log-file-enabled=true
""")

# Loopback exemption command (Windows UWP apps can't connect to localhost
# without this). Only needs to be run once, ever.
_LOOPBACK_CMD = (
    'CheckNetIsolation.exe LoopbackExempt -a '
    '-p=S-1-15-2-1958404141-86561845-1752920682-3514627264-368642714-62675701-733520436'
)


# ---------------------------------------------------------------------------
# 1. Server Setup
# ---------------------------------------------------------------------------

def setup_server(pack_path: str | Path, resource_pack_path: str | Path | None = None) -> None:
    """Clean old packs, deploy the new one, and write server.properties."""
    pack_path = Path(pack_path).resolve()
    resource_pack_path = Path(resource_pack_path).resolve() if resource_pack_path else None

    if not BDS_DIR.exists():
        raise FileNotFoundError(
            f"Bedrock Dedicated Server not found at {BDS_DIR}\n"
            "Download it from https://www.minecraft.net/en-us/download/server/bedrock\n"
            "and extract it into the bedrock_server/ folder."
        )
    if not BDS_EXE.exists():
        raise FileNotFoundError(
            f"bedrock_server.exe not found in {BDS_DIR}\n"
            "Make sure you extracted the full BDS zip into bedrock_server/."
        )
    if not (pack_path / "manifest.json").exists():
        raise FileNotFoundError(
            f"No manifest.json in {pack_path}. Cannot deploy pack."
        )

    # ── Verify vanilla packs exist (BDS won't start without them) ───────
    rp_dir = BDS_DIR / "resource_packs"
    bp_dir = BDS_DIR / "behavior_packs"
    _has_vanilla_rp = any(
        (rp_dir / d / "manifest.json").exists()
        for d in ("vanilla", "vanilla_base")
        if (rp_dir / d).exists()
    ) if rp_dir.exists() else False

    if not _has_vanilla_rp:
        raise FileNotFoundError(
            "BDS is missing the vanilla resource pack!\n"
            "The server CANNOT start without it.\n\n"
            "Fix: Re-extract the BDS zip completely into bedrock_server/.\n"
            "The zip should contain resource_packs/vanilla/ and other folders.\n"
            "Make sure to extract ALL contents, not just the top-level files.\n\n"
            "Download: https://www.minecraft.net/en-us/download/server/bedrock"
        )

    # ── Clean only non-vanilla packs ────────────────────────────────────
    _VANILLA_PREFIXES = ("vanilla", "chemistry", "experimental")
    for d in (bp_dir, rp_dir):
        if d.exists():
            for child in d.iterdir():
                if child.is_dir() and not child.name.startswith(_VANILLA_PREFIXES):
                    shutil.rmtree(child)
                elif child.is_file() and child.name != "manifest.json":
                    child.unlink()
        else:
            d.mkdir(parents=True)

    # ── Deploy the behavior pack ─────────────────────────────────────────
    pack_name = pack_path.name
    dest = bp_dir / pack_name
    shutil.copytree(pack_path, dest)
    print(f"  [server] Deployed BP → behavior_packs/{pack_name}/")

    # ── Deploy the resource pack (if provided) ────────────────────────
    rp_id = ""
    rp_version = [1, 0, 0]
    if resource_pack_path and resource_pack_path.exists():
        rp_name = resource_pack_path.name
        rp_dest = rp_dir / rp_name
        shutil.copytree(resource_pack_path, rp_dest)
        print(f"  [server] Deployed RP → resource_packs/{rp_name}/")
        rp_manifest_path = resource_pack_path / "manifest.json"
        if rp_manifest_path.exists():
            rp_manifest = json.loads(rp_manifest_path.read_text(encoding="utf-8"))
            rp_header = rp_manifest.get("header", {})
            rp_id = rp_header.get("uuid", "")
            rp_version = rp_header.get("version", [1, 0, 0])

    # ── Write world pack lists so the world auto-loads them ───────────
    manifest = json.loads((pack_path / "manifest.json").read_text(encoding="utf-8"))
    header = manifest.get("header", {})
    pack_id = header.get("uuid", "")
    pack_version = header.get("version", [1, 0, 0])

    # ── Delete old world so every test starts fresh ────────────────────
    world_dir = BDS_DIR / "worlds" / "Bedrock-Addon-Test"
    if world_dir.exists():
        shutil.rmtree(world_dir)
        print("  [server] Deleted old world (fresh start)")
    world_dir.mkdir(parents=True, exist_ok=True)

    world_bp = [{"pack_id": pack_id, "version": pack_version}]
    (world_dir / "world_behavior_packs.json").write_text(
        json.dumps(world_bp, indent=2), encoding="utf-8"
    )
    print(f"  [server] Auto-enabled BP (uuid={pack_id})")

    if rp_id:
        world_rp = [{"pack_id": rp_id, "version": rp_version}]
        (world_dir / "world_resource_packs.json").write_text(
            json.dumps(world_rp, indent=2), encoding="utf-8"
        )
        print(f"  [server] Auto-enabled RP (uuid={rp_id})")
    else:
        # Remove stale RP list from previous runs
        rp_list_path = world_dir / "world_resource_packs.json"
        if rp_list_path.exists():
            rp_list_path.unlink()

    # ── Write server.properties ─────────────────────────────────────────
    (BDS_DIR / "server.properties").write_text(_SERVER_PROPERTIES, encoding="utf-8")
    print("  [server] Wrote server.properties (creative/flat/peaceful)")


# ---------------------------------------------------------------------------
# 2 & 3. Launch Server + Client
# ---------------------------------------------------------------------------

def _read_server_output(proc: subprocess.Popen, event_server_ready: threading.Event,
                        event_player_spawned: threading.Event,
                        event_fatal_error: threading.Event,
                        event_no_targets: threading.Event,
                        log_lines: list[str]) -> None:
    """Background thread: read BDS stdout line-by-line."""
    try:
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()
            if not line:
                continue
            log_lines.append(line)
            print(f"  [BDS] {line}", flush=True)

            # BDS prints: [... INFO] Server started.
            if "Server started" in line:
                event_server_ready.set()
            # Trigger on full spawn, not just connection
            if "Player Spawned" in line:
                event_player_spawned.set()
            # Fatal: BDS can't proceed without vanilla packs
            if "Failed to load Vanilla Resource Pack" in line:
                event_fatal_error.set()
            # Command retry trigger
            if "No targets matched selector" in line:
                event_no_targets.set()
    except Exception:
        pass  # process killed


def _kill_minecraft_client() -> None:
    """Force-close any suspended Minecraft instances so the URI cold-boots."""
    print("  [client] Ensuring fresh game instance...")
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/IM", "Minecraft.Windows.exe", "/T"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif system == "Darwin":
            subprocess.run(["pkill", "-9", "Minecraft"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass  # fine if it wasn't running


def _launch_client() -> None:
    """Open Minecraft and attempt to auto-connect to localhost:19132."""
    system = platform.system()
    uri = "minecraft://Connect?ip=127.0.0.1&port=19132"

    if system == "Windows":
        print("  [client] Launching Minecraft...")
        # Try the protocol handler first (works ~50% of the time on UWP)
        os.startfile(uri)
        print("  [client] If you land on the Main Menu instead of auto-joining:")
        print("           Play → Friends → LAN Games → 'Bedrock Addon Test'")
        print(f"  [client] First time? Run once as Admin: {_LOOPBACK_CMD}")
    elif system == "Darwin":
        subprocess.Popen(["open", uri])
    else:
        subprocess.Popen(["xdg-open", uri])


# ---------------------------------------------------------------------------
# 4. The "Magic" — Auto Give / Summon
# ---------------------------------------------------------------------------

def _detect_identifiers(pack_path: Path, category: str) -> list[str]:
    """Walk the pack folder and find ALL content identifiers from the spec JSONs.

    For entities: look in entities/ for "minecraft:entity" -> "description" -> "identifier"
    For items:    look in items/    for "minecraft:item"   -> "description" -> "identifier"
    For blocks:   look in blocks/   for "minecraft:block"  -> "description" -> "identifier"
    """
    identifiers: list[str] = []
    search_map = {
        "entity_logic_ai": ("entities", "minecraft:entity"),
        "items_weaponry":  ("items",    "minecraft:item"),
        "blocks_furniture": ("blocks",  "minecraft:block"),
    }

    if category in search_map:
        subfolder, root_key = search_map[category]
        search_dir = pack_path / subfolder
        if search_dir.exists():
            for f in search_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    desc = data.get(root_key, {}).get("description", {})
                    ident = desc.get("identifier")
                    if ident and ident not in identifiers:
                        identifiers.append(ident)
                except (json.JSONDecodeError, AttributeError):
                    continue

    # Fallback: scan all JSON files if nothing found yet
    if not identifiers:
        for f in pack_path.rglob("*.json"):
            if f.name == "manifest.json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                for root_key in ("minecraft:entity", "minecraft:item", "minecraft:block"):
                    desc = data.get(root_key, {}).get("description", {})
                    ident = desc.get("identifier")
                    if ident and ident not in identifiers:
                        identifiers.append(ident)
            except (json.JSONDecodeError, AttributeError):
                continue

    return identifiers


# Keep backward-compat alias
def _detect_identifier(pack_path: Path, category: str) -> str | None:
    """Return the first detected identifier (legacy helper)."""
    ids = _detect_identifiers(pack_path, category)
    return ids[0] if ids else None


def _build_command(identifier: str, category: str) -> str:
    """Build the server command to give/summon based on category."""
    if category == "entity_logic_ai":
        return f"execute at @a run summon {identifier} ~ ~ ~"
    elif category == "blocks_furniture":
        return f"give @a {identifier} 64"
    else:
        # items, loot, recipes, etc.
        return f"give @a {identifier}"


# ---------------------------------------------------------------------------
# 5. Main Orchestrator
# ---------------------------------------------------------------------------

def launch_server_session(pack_path: str | Path, category: str = "items_weaponry",
                          resource_pack_path: str | Path | None = None) -> None:
    """Full lifecycle: setup → launch server → connect client → magic → cleanup.

    Parameters
    ----------
    pack_path : str | Path
        Directory containing the generated Behavior Pack (with manifest.json).
    category : str
        The test category, used to decide give vs summon.
    resource_pack_path : str | Path | None
        Optional directory containing the Resource Pack (textures, models).
    """
    pack_path = Path(pack_path).resolve()

    # ── Setup ───────────────────────────────────────────────────────────
    print("\n=== Server Session: Setup ===")
    setup_server(pack_path, resource_pack_path=resource_pack_path)

    # ── Detect identifiers ──────────────────────────────────────────────
    identifiers = _detect_identifiers(pack_path, category)
    commands: list[str] = []
    if identifiers:
        for ident in identifiers:
            cmd = _build_command(ident, category)
            commands.append(cmd)
            print(f"  [magic] Detected: {ident}  →  /{cmd}")
    else:
        print("  [magic] WARNING: Could not detect any identifiers. "
              "Auto-give/summon will be skipped.")

    # ── Invisible entity warning ─────────────────────────────────────────
    if category == "entity_logic_ai" and identifiers:
        has_rp = False
        for rp_candidate in (pack_path.parent, pack_path.parent.parent):
            for rp_dir_check in rp_candidate.glob("**/resource_pack*"):
                if rp_dir_check.is_dir():
                    for ej in rp_dir_check.rglob("*.entity.json"):
                        has_rp = True
                        break
                if has_rp:
                    break
            if has_rp:
                break
        if not has_rp:
            print("  [magic] WARNING: No matching Resource Pack found. "
                  "The entity may be invisible in-game.")

    # ── Kill any suspended Minecraft before starting ────────────────────
    _kill_minecraft_client()

    # ── Launch server ───────────────────────────────────────────────────
    print("\n=== Server Session: Starting BDS ===")
    event_server_ready = threading.Event()
    event_player_spawned = threading.Event()
    event_fatal_error = threading.Event()
    event_no_targets = threading.Event()
    log_lines: list[str] = []

    proc = subprocess.Popen(
        [str(BDS_EXE)],
        cwd=str(BDS_DIR),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    reader_thread = threading.Thread(
        target=_read_server_output,
        args=(proc, event_server_ready, event_player_spawned,
              event_fatal_error, event_no_targets, log_lines),
        daemon=True,
    )
    reader_thread.start()

    try:
        # ── Wait for server ready (bail early on fatal error) ──────────
        print("  [server] Waiting for server to start...")
        while not event_server_ready.is_set():
            if event_fatal_error.wait(timeout=1):
                print("\n  [server] FATAL: BDS cannot start — vanilla resource pack missing.")
                print("  [server] Re-extract the BDS zip fully into bedrock_server/.")
                print("  [server] The zip must include resource_packs/vanilla/ and related folders.")
                proc.kill()
                return
            if event_server_ready.wait(timeout=1):
                break
            # Check if process died
            if proc.poll() is not None:
                print("  [server] ERROR: BDS exited unexpectedly.")
                print("  [server] Last log lines:")
                for line in log_lines[-10:]:
                    print(f"    {line}")
                return

        print("  [server] Server is READY on port 19132")

        # ── Launch client (kill stale instances first) ────────────────
        print("\n=== Server Session: Connecting Client ===")
        _kill_minecraft_client()
        time.sleep(3)  # let Windows fully release the process
        _launch_client()

        # ── Wait for player spawn + magic ─────────────────────────────
        if commands:
            print("  [magic] Waiting for player to spawn...")
            if event_player_spawned.wait(timeout=120):
                print("  [magic] Player spawned! Waiting 2s before commands...")
                time.sleep(2)
                for cmd in commands:
                    event_no_targets.clear()
                    proc.stdin.write(cmd + "\n")
                    proc.stdin.flush()
                    print(f"  [magic] Sent: /{cmd}")
                    # Retry once if no targets matched
                    if event_no_targets.wait(timeout=3):
                        print("  [magic] No targets matched — retrying in 3s...")
                        time.sleep(3)
                        event_no_targets.clear()
                        proc.stdin.write(cmd + "\n")
                        proc.stdin.flush()
                        print(f"  [magic] Retry sent: /{cmd}")
                    time.sleep(1)  # small gap between multiple summons
                print(f"  [magic] Done! All {len(commands)} command(s) sent.")
            else:
                print("  [magic] No player spawned within 120s. Skipping auto-give.")

        # ── Keep server alive until Ctrl+C ─────────────────────────────
        print("\n=== Server Running ===")
        print("  Press Ctrl+C to stop the server and clean up.\n")
        proc.wait()

    except KeyboardInterrupt:
        print("\n  [server] Shutting down...")
        try:
            proc.stdin.write("stop\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        print("  [server] Server stopped.")
    finally:
        if proc.poll() is None:
            proc.kill()


# ── Standalone entry point ──────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/launch_server_session.py <pack_folder> [category]")
        sys.exit(1)
    cat = sys.argv[2] if len(sys.argv) > 2 else "items_weaponry"
    launch_server_session(sys.argv[1], category=cat)
