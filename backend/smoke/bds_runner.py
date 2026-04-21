"""BDS subprocess wrapper for smoke-testing generated add-on packs.

How it works
------------
1. Reads the .mcaddon ZIP, extracts resource_pack/ and behavior_pack/ dirs.
2. Installs them into the BDS directory (unique run-scoped names).
3. Creates a run-scoped world folder and writes world_*_packs.json.
4. Writes server.properties (level-name, offline mode, flat world, alt port).
5. Starts BDS as an async subprocess, streams stdout line-by-line.
6. Detects "Server started." → sends tickingarea + summon for each mob.
7. Drains output for a few seconds then kills BDS cleanly.
8. Parses all captured lines and returns a SmokeResult.

Environment variables
---------------------
BDS_PATH         Full path to bedrock_server(.exe). Required — smoke tests
                 are skipped if unset or the file doesn't exist.
BDS_TIMEOUT      Seconds to wait for BDS to emit "Server started." Default 60.
BDS_SMOKE_PORT   UDP port BDS binds. Default 29132 (avoids default 19132 so
                 a live BDS instance on the same host isn't disturbed).
"""
import asyncio
import json
import os
import platform
import shutil
import tempfile
import threading
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from backend.smoke.log_parser import (
    READY_PATTERNS,
    SmokeResult,
    parse_session_log,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BDS_PATH: Optional[str] = os.environ.get("BDS_PATH")
BDS_TIMEOUT: int = int(os.environ.get("BDS_TIMEOUT", "60"))
BDS_SMOKE_PORT: int = int(os.environ.get("BDS_SMOKE_PORT", "29132"))

# Only one BDS instance runs at a time — serialise with a semaphore.
_bds_lock = threading.Semaphore(1)


def is_bds_available() -> bool:
    """Return True when BDS_PATH is set and points to an existing executable."""
    return bool(BDS_PATH) and Path(BDS_PATH).is_file()


# ---------------------------------------------------------------------------
# Pack extraction helpers
# ---------------------------------------------------------------------------

def _read_manifest(pack_dir: Path) -> tuple[str, list[int]]:
    """Return (uuid, version) from a pack's manifest.json."""
    manifest = pack_dir / "manifest.json"
    if not manifest.exists():
        raise FileNotFoundError(f"manifest.json not found in {pack_dir}")
    data = json.loads(manifest.read_bytes())
    header = data.get("header", {})
    pack_uuid: str = header.get("uuid", "")
    version = header.get("version", [1, 0, 0])
    if isinstance(version, list) and len(version) >= 3:
        return pack_uuid, [int(v) for v in version[:3]]
    return pack_uuid, [1, 0, 0]


def _extract_mcaddon(mcaddon_path: Path, dest_dir: Path) -> tuple[Path, Path]:
    """Extract .mcaddon and locate the resource + behavior pack directories.

    .mcaddon is a ZIP whose top-level entries are named resource_pack/ and
    behavior_pack/ by convention (our builder follows this).  Returns
    (res_pack_dir, beh_pack_dir).
    """
    with zipfile.ZipFile(mcaddon_path) as zf:
        zf.extractall(dest_dir)

    res_dir: Optional[Path] = None
    beh_dir: Optional[Path] = None

    for child in sorted(dest_dir.iterdir()):  # sorted for determinism
        if not child.is_dir():
            continue
        name = child.name.lower()
        if "resource" in name and res_dir is None:
            res_dir = child
        elif "behavior" in name and beh_dir is None:
            beh_dir = child

    if res_dir is None or beh_dir is None:
        found = [c.name for c in dest_dir.iterdir() if c.is_dir()]
        raise RuntimeError(
            f"Could not locate resource_pack and behavior_pack inside "
            f".mcaddon (found dirs: {found})"
        )
    return res_dir, beh_dir


def _mob_identifiers_from_beh_pack(beh_pack: Path) -> list[str]:
    """Scan entities/*.json and collect minecraft:entity description identifiers."""
    identifiers: list[str] = []
    entities_dir = beh_pack / "entities"
    if not entities_dir.is_dir():
        return identifiers
    for ent_file in sorted(entities_dir.glob("*.json")):
        try:
            data = json.loads(ent_file.read_bytes())
            ident = (
                data.get("minecraft:entity", {})
                    .get("description", {})
                    .get("identifier", "")
            )
            if ident:
                identifiers.append(ident)
        except Exception:
            pass
    return identifiers


# ---------------------------------------------------------------------------
# BDS workspace helpers
# ---------------------------------------------------------------------------

def _write_server_properties(bds_dir: Path, level_name: str, port: int) -> None:
    content = (
        "server-name=Bedrock Smoke Test\n"
        "gamemode=creative\n"
        "difficulty=peaceful\n"
        "allow-cheats=true\n"
        "max-players=1\n"
        "online-mode=false\n"
        "allow-list=false\n"
        f"level-name={level_name}\n"
        "level-type=FLAT\n"
        f"server-port={port}\n"
        f"server-portv6={port + 1}\n"
        "tick-distance=4\n"
        "view-distance=4\n"
        "player-idle-timeout=0\n"
        "content-log-file-enabled=true\n"
    )
    (bds_dir / "server.properties").write_text(content, encoding="utf-8")


def _write_eula(bds_dir: Path) -> None:
    eula = bds_dir / "eula.txt"
    if not eula.exists() or "eula=true" not in eula.read_text(encoding="utf-8", errors="ignore"):
        eula.write_text("eula=true\n", encoding="utf-8")


def _ensure_permissions(bds_dir: Path) -> None:
    perm = bds_dir / "permissions.json"
    if not perm.exists():
        perm.write_text(
            json.dumps({"allowed": [], "banned": [], "operators": []}),
            encoding="utf-8",
        )


def _write_world_pack_jsons(
    world_dir: Path,
    res_uuid: str, res_ver: list[int],
    beh_uuid: str, beh_ver: list[int],
) -> None:
    world_dir.mkdir(parents=True, exist_ok=True)
    (world_dir / "world_resource_packs.json").write_text(
        json.dumps([{"pack_id": res_uuid, "version": res_ver}], indent=2),
        encoding="utf-8",
    )
    (world_dir / "world_behavior_packs.json").write_text(
        json.dumps([{"pack_id": beh_uuid, "version": beh_ver}], indent=2),
        encoding="utf-8",
    )


def _setup_workspace(
    bds_dir: Path,
    level_name: str,
    run_id: str,
    mcaddon_path: Path,
) -> tuple[Path, Path, list[str]]:
    """Install the addon into BDS for this run.

    Creates:
      bds_dir/behavior_packs/smoke_{run_id}_beh/
      bds_dir/resource_packs/smoke_{run_id}_res/
      bds_dir/worlds/{level_name}/world_*_packs.json

    Returns (res_pack_dest, beh_pack_dest, mob_identifiers).
    """
    extract_dir = bds_dir / f"_smoke_extract_{run_id}"
    extract_dir.mkdir(parents=True)
    try:
        res_src, beh_src = _extract_mcaddon(mcaddon_path, extract_dir)
        res_uuid, res_ver = _read_manifest(res_src)
        beh_uuid, beh_ver = _read_manifest(beh_src)

        res_dest = bds_dir / "resource_packs" / f"smoke_{run_id}_res"
        beh_dest = bds_dir / "behavior_packs" / f"smoke_{run_id}_beh"
        shutil.copytree(str(res_src), str(res_dest))
        shutil.copytree(str(beh_src), str(beh_dest))

        # World dir must match the level-name in server.properties exactly.
        world_dir = bds_dir / "worlds" / level_name
        _write_world_pack_jsons(world_dir, res_uuid, res_ver, beh_uuid, beh_ver)

        print(f"[SMOKE] Behavior pack: {beh_dest.name} uuid={beh_uuid}")
        print(f"[SMOKE] Resource pack: {res_dest.name} uuid={res_uuid}")
        print(f"[SMOKE] World dir: {world_dir}")

        mob_identifiers = _mob_identifiers_from_beh_pack(beh_dest)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    return res_dest, beh_dest, mob_identifiers


def _teardown_workspace(
    bds_dir: Path,
    level_name: str,
    run_id: str,
    res_dest: Optional[Path],
    beh_dest: Optional[Path],
) -> None:
    """Remove all run-specific files from the BDS directory."""
    for path in filter(None, [
        res_dest,
        beh_dest,
        bds_dir / "worlds" / level_name,
        bds_dir / f"_smoke_extract_{run_id}",
    ]):
        shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

async def run_bds_smoke(
    mcaddon_path: Path,
    timeout: int = BDS_TIMEOUT,
) -> SmokeResult:
    """Run a BDS smoke test against *mcaddon_path*.

    Starts BDS, waits for the world to load, issues ``/summon`` for every
    entity identifier found in the behavior pack, collects 4 s of output,
    kills BDS, and returns a :class:`~backend.smoke.log_parser.SmokeResult`.

    If ``BDS_PATH`` is not set or the executable is missing this returns
    immediately with ``passed=False`` and a descriptive ``error_message``.
    """
    if not is_bds_available():
        return SmokeResult(
            passed=False,
            error_message=(
                "BDS not available. Set the BDS_PATH environment variable to "
                "the full path of bedrock_server (Linux) or bedrock_server.exe "
                "(Windows)."
            ),
        )

    bds_exe = Path(BDS_PATH)  # type: ignore[arg-type]
    bds_dir = bds_exe.parent
    run_id = uuid.uuid4().hex[:12]  # no "smoke_" prefix — added in folder names below

    if not _bds_lock.acquire(blocking=False):
        return SmokeResult(
            passed=False,
            error_message="Another BDS smoke test is already running. Try again shortly.",
        )

    level_name = f"smoke_{run_id}"
    res_dest: Optional[Path] = None
    beh_dest: Optional[Path] = None
    process: Optional[asyncio.subprocess.Process] = None

    try:
        # ── Configure BDS ────────────────────────────────────────────────────
        _write_eula(bds_dir)
        _ensure_permissions(bds_dir)
        _write_server_properties(bds_dir, level_name=level_name, port=BDS_SMOKE_PORT)

        # ── Install packs ────────────────────────────────────────────────────
        try:
            res_dest, beh_dest, mob_identifiers = _setup_workspace(
                bds_dir, level_name, run_id, mcaddon_path
            )
        except Exception as exc:
            return SmokeResult(
                passed=False,
                error_message=f"BDS workspace setup failed: {exc}",
            )

        print(f"[SMOKE] Run smoke_{run_id} — entities: {mob_identifiers}")

        # ── Start BDS ────────────────────────────────────────────────────────
        env = os.environ.copy()
        if platform.system() == "Linux":
            # BDS ships its own shared libs next to the binary.
            env["LD_LIBRARY_PATH"] = str(bds_dir)

        process = await asyncio.create_subprocess_exec(
            str(bds_exe),
            cwd=str(bds_dir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )

        # ── Stream output until "Server started." ────────────────────────────
        log_lines: list[str] = []
        bds_ready = False

        async def _read_until_ready() -> None:
            nonlocal bds_ready
            assert process.stdout is not None
            while True:
                try:
                    raw = await asyncio.wait_for(
                        process.stdout.readline(), timeout=2.0
                    )
                except asyncio.TimeoutError:
                    if process.returncode is not None:
                        break   # process exited
                    continue    # still running, keep waiting
                if not raw:
                    break       # EOF
                line = raw.decode("utf-8", errors="replace")
                log_lines.append(line)
                print(f"[BDS] {line}", end="")

                if not bds_ready and any(p.search(line) for p in READY_PATTERNS):
                    bds_ready = True
                    # Give BDS a moment to flush remaining content-log lines.
                    await asyncio.sleep(3.0)
                    break

        try:
            await asyncio.wait_for(_read_until_ready(), timeout=timeout)
        except asyncio.TimeoutError:
            print(f"[SMOKE] Timed out after {timeout}s waiting for 'Server started.'")

        # ── Summon each mob entity then drain responses ───────────────────────
        if bds_ready:
            if mob_identifiers and process.stdin is not None:
                # Force-load the spawn chunk so summon has a valid target area.
                print("[SMOKE] Sending: tickingarea add 0 0 0 5 5 5 smoketest")
                process.stdin.write(b"tickingarea add 0 0 0 5 5 5 smoketest\n")
                try:
                    await process.stdin.drain()
                except Exception:
                    pass
                await asyncio.sleep(1.5)

                for ident in mob_identifiers:
                    cmd = f"summon {ident} 0 64 0\n"
                    print(f"[SMOKE] Sending: {cmd.strip()}")
                    process.stdin.write(cmd.encode())
                try:
                    await process.stdin.drain()
                except Exception:
                    pass

            async def _drain() -> None:
                assert process.stdout is not None
                while True:
                    try:
                        raw = await asyncio.wait_for(
                            process.stdout.readline(), timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        break
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace")
                    log_lines.append(line)
                    print(f"[BDS] {line}", end="")
            try:
                await asyncio.wait_for(_drain(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

        # ── Kill BDS ─────────────────────────────────────────────────────────
        if process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=8.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

        # ── Parse and return ─────────────────────────────────────────────────
        errors, warnings = parse_session_log(log_lines)
        session_log = "".join(log_lines)

        return SmokeResult(
            passed=bds_ready and len(errors) == 0,
            errors=errors,
            warnings=warnings,
            bds_ready=bds_ready,
            mob_identifiers=mob_identifiers,
            session_log=session_log,
            error_message=(
                ""
                if bds_ready
                else f"BDS did not reach 'Server started.' within {timeout}s."
            ),
        )

    except Exception:
        return SmokeResult(
            passed=False,
            error_message=f"BDS smoke test raised an exception:\n{traceback.format_exc()}",
        )

    finally:
        _teardown_workspace(bds_dir, level_name, run_id, res_dest, beh_dest)
        _bds_lock.release()


def run_bds_smoke_sync(
    mcaddon_path: Path,
    timeout: int = BDS_TIMEOUT,
) -> SmokeResult:
    """Synchronous wrapper around :func:`run_bds_smoke` for CLI / test use.

    On Windows, uvicorn uses SelectorEventLoop which cannot create subprocesses.
    We create a ProactorEventLoop explicitly so subprocess works correctly.
    """
    if platform.system() == "Windows":
        loop = asyncio.ProactorEventLoop()
        try:
            return loop.run_until_complete(run_bds_smoke(mcaddon_path, timeout=timeout))
        finally:
            loop.close()
    else:
        return asyncio.run(run_bds_smoke(mcaddon_path, timeout=timeout))
