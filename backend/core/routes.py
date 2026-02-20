"""FastAPI route handlers for the web API."""
import tempfile
import uuid
import threading
import sys
import os
from pathlib import Path
from typing import Optional
import json
import httpx

from fastapi import File, Form, HTTPException, Body, UploadFile, Response
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, JSONResponse
import shutil

from backend.schemas.spec_utils import (
    read_mob_spec, write_mob_spec, delete_mob_spec, list_mob_names,
    read_current_spec, write_current_spec, apply_spec_patch,
    validate_spec, SpecValidationError
)
from backend.llm.llm import llm_rewrite_spec, llm_generate_geometry
from backend.core.packaging import build_addon
from backend.core.builders import make_png_rgba

from backend.core.core import BACKEND_DIR, COLOR_WORDS, SPECS_DIR, FRONTEND_DIR, LOCAL_LLM_DEV

# In-memory cache for geometry fetched from GitHub (avoids burning rate limit)
_geometry_cache: dict[str, dict] = {}
_github_file_list_cache: list[dict] | None = None


def _save_upload(tmpdir: Path, uf: Optional[UploadFile]) -> Optional[Path]:
    """Save an uploaded file to a temporary directory."""
    if not uf:
        return None
    if not uf.filename:
        return None
    suffix = "".join(Path(uf.filename).suffixes) or ".zip"
    dest = tmpdir / f"upload_{uuid.uuid4().hex}{suffix}"
    with dest.open("wb") as f:
        shutil.copyfileobj(uf.file, f)
    return dest


def _select_artifact(artifacts: dict, build_mode: str) -> tuple[str, Path]:
    """Select the appropriate artifact based on build mode."""
    mode = (build_mode or "bundle").lower()
    if mode == "mcworld":
        path_str = artifacts.get("mcworld")
        if not path_str:
            raise HTTPException(
                status_code=400,
                detail="Could not create .mcworld: No base world template found on server. "
                       "Please ensure a 'base_world' folder or 'base_world.mcworld' exists in the 'templates' directory "
                       "and is not gitignored."
            )
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
                      build_mode: str = "bundle",
                      textures_dir: Optional[Path] = None) -> tuple[str, Path, dict]:
    """Build and bundle addon, selecting appropriate specs."""
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
    artifacts = build_addon(specs, out_dir, res_path, beh_path, textures_dir=textures_dir)
    kind, artifact_path = _select_artifact(artifacts, build_mode)
    return kind, artifact_path, artifacts


# Route handlers

def get_mobs():
    """List all mob names."""
    return {"mobs": list_mob_names()}


def get_templates():
    """Get vanilla mob templates."""
    import json
    path = BACKEND_DIR / "data" / "vanilla_mobs.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Failed to load templates: {e}")
    return {"mobs": {}}


async def get_template_mob_from_database(mob_name: str):
    """Load a template mob from the database.
    
    Searches for mobs in the database where the name contains the search term.
    Returns the most recently updated mob; if multiple were updated the same day,
    returns the one with the shortest name.
    
    This is used when users create a mob from a database template instead of GitHub.
    """
    if not mob_name:
        raise HTTPException(status_code=400, detail="mob_name is required")
    
    try:
        from backend.mob_management import get_template_mob_by_name
        
        template_mob = get_template_mob_by_name(mob_name)
        
        return {
            "mob": template_mob,
            "source": "database"
        }
    except ValueError as e:
        # No mob found - return 404 with error message
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"[ERROR] Failed to load template mob from database: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load template: {str(e)}")


async def get_all_template_mob_names():
    """Get all available mob names from the database for dropdown selection."""
    try:
        from backend.mob_management import get_all_mob_names
        
        mob_names = get_all_mob_names()
        return {
            "mobs": mob_names,
            "source": "database",
            "count": len(mob_names)
        }
    except Exception as e:
        print(f"[ERROR] Failed to fetch template mob names: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch mobs: {str(e)}")


async def fetch_mob_geometry(mob_name: str):
    """Fetch mob geometry JSON from Mojang's bedrock-samples repository.
    
    Searches for all .geo.json files containing the mob_name (with version numbers/descriptors),
    and fetches the most recently updated one. Results are cached locally to avoid
    burning through the GitHub API rate limit (60 req/hr unauthenticated).
    """
    if not mob_name:
        raise HTTPException(status_code=400, detail="mob_name is required")
    
    # Sanitize mob_name to prevent directory traversal
    safe_name = mob_name.strip().replace("..", "").replace("/", "")
    safe_name_lower = safe_name.lower()

    # Check in-memory cache first
    if safe_name_lower in _geometry_cache:
        print(f"[GEOMETRY] Cache hit for '{mob_name}'")
        return _geometry_cache[safe_name_lower]
    
    # Use raw.githubusercontent.com directly — NO API rate limit!
    # Try common filename patterns for Bedrock geometry files
    base_url = "https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity"
    candidates = [
        f"{safe_name_lower}.geo.json",
        f"{safe_name_lower}_v2.geo.json",
        f"{safe_name_lower}_v1.geo.json",
    ]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for filename in candidates:
                raw_url = f"{base_url}/{filename}"
                response = await client.get(raw_url)
                if response.status_code == 200:
                    try:
                        geometry_data = response.json()
                    except (json.JSONDecodeError, ValueError):
                        continue

                    result = {
                        "geometry": geometry_data,
                        "url": raw_url,
                        "filename": filename,
                        "matches_found": 1
                    }
                    _geometry_cache[safe_name_lower] = result
                    print(f"[GEOMETRY] Fetched and cached '{filename}' for '{mob_name}'")
                    return result

            # None of the direct URLs worked — fall back to GitHub API for directory listing
            # (only costs 1 API call, and the listing is cached for future lookups)
            global _github_file_list_cache
            if _github_file_list_cache is not None:
                files = _github_file_list_cache
            else:
                api_url = "https://api.github.com/repos/Mojang/bedrock-samples/contents/resource_pack/models/entity"
                api_response = await client.get(api_url)
                if api_response.status_code != 200:
                    raise HTTPException(
                        status_code=api_response.status_code,
                        detail=f"Failed to query GitHub API (status {api_response.status_code})"
                    )
                files = api_response.json()
                if isinstance(files, list):
                    _github_file_list_cache = files

            matching = [
                f.get("name", "") for f in files
                if safe_name_lower in f.get("name", "").lower() and f.get("name", "").endswith(".geo.json")
            ]
            if not matching:
                raise HTTPException(status_code=404, detail=f"No geometry files found for '{mob_name}'")

            matching.sort(key=len)
            chosen = matching[0]
            raw_url = f"{base_url}/{chosen}"
            response = await client.get(raw_url)
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Failed to fetch geometry file")

            geometry_data = response.json()
            result = {
                "geometry": geometry_data,
                "url": raw_url,
                "filename": chosen,
                "matches_found": len(matching)
            }
            _geometry_cache[safe_name_lower] = result
            print(f"[GEOMETRY] Fetched and cached '{chosen}' for '{mob_name}' (via API fallback)")
            return result

    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch geometry from GitHub: {str(e)}"
        )



def get_mob(name: str):
    """Retrieve a specific mob spec."""
    from backend.schemas.schemas_loader import SPEC_SCHEMA
    try:
        spec = read_mob_spec(name)
        return {"spec": spec, "schema": SPEC_SCHEMA}
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def get_mob_texture(name: str):
    """Get a mob's texture image."""
    from backend.core.builders import make_png_rgba
    from backend.core.core import COLOR_WORDS, SPECS_DIR
    path = SPECS_DIR / f"{name}.png"
    if path.exists():
        return FileResponse(path, media_type="image/png")
    # Fallback to a generated one based on the spec
    spec = read_mob_spec(name)
    col = spec.get("color_rgb", COLOR_WORDS.get("red"))
    png = make_png_rgba(64, 64, *col, 255)
    return Response(content=png, media_type="image/png")


async def save_mob_texture(name: str, file: UploadFile = File(...)):
    """Save a custom texture for a mob."""
    from backend.core.core import SPECS_DIR
    path = SPECS_DIR / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"status": "ok"}


async def save_mob(name: str, payload: dict = Body(...)):
    """Create or update a mob spec."""
    try:
        spec = write_mob_spec(name, payload)
        return {"spec": spec}
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def delete_mob(name: str):
    """Delete a mob spec."""
    delete_mob_spec(name)
    return {"status": "ok"}


def duplicate_mob(name: str):
    """Create a copy of a mob spec."""
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


def get_spec():
    """Get the current/active spec."""
    from backend.schemas.schemas_loader import SPEC_SCHEMA
    return {
        "spec": read_current_spec(),
        "schema": SPEC_SCHEMA
    }


async def replace_spec(payload: dict = Body(...)):
    """Replace the current spec."""
    try:
        spec = write_current_spec(payload)
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"spec": spec}


async def patch_spec(operations: list[dict] = Body(...)):
    """Apply JSON Patch operations to the current spec."""
    current = read_current_spec()
    try:
        patched = apply_spec_patch(current, operations)
        spec = write_current_spec(patched)
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"spec": spec}


def llm_spec_editor(payload: dict = Body(...)):
    """Use LLM to rewrite a spec."""
    data = payload or {}
    prompt = data.get("prompt") or data.get("instruction") or ""
    if not prompt or not str(prompt).strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    provider = data.get("provider")
    api_key = data.get("api_key")
    current = data.get("current_spec") or data.get("spec")
    if not current:
        current = read_current_spec()

    print(f"[LLM] provider={provider} prompt_len={len(str(prompt).strip())}")

    # if server running in local dev mode prefer mock to avoid external calls
    if LOCAL_LLM_DEV and not provider:
        return llm_spec_mock(payload)

    try:
        updated = llm_rewrite_spec(prompt, current, provider, api_key)
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        print(f"[LLM] error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    if data.get("save"):
        try:
            name = updated.get("short_name") or "current"
            saved = write_mob_spec(name, updated)
            return {"spec": saved, "saved": True}
        except SpecValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    return {"spec": updated, "saved": False}


def llm_geometry_generate(payload: dict = Body(...)):
    """Use LLM to generate or modify Bedrock geometry JSON."""
    data = payload or {}
    prompt = data.get("prompt") or ""
    if not prompt or not str(prompt).strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    
    provider = data.get("provider")
    api_key = data.get("api_key")
    current_geometry = data.get("current_geometry")
    
    print(f"[LLM-GEOMETRY] provider={provider} prompt_len={len(str(prompt).strip())}")
    
    try:
        geometry = llm_generate_geometry(prompt, current_geometry, provider, api_key)
    except RuntimeError as exc:
        print(f"[LLM-GEOMETRY] error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        print(f"[LLM-GEOMETRY] unexpected error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    
    return {"geometry": geometry}

def llm_spec_mock(payload: dict = Body(...)):
    data = payload or {}
    prompt = (data.get("prompt") or data.get("instruction") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    current = data.get("current_spec") or data.get("spec")
    if not current:
        current = read_current_spec()
    spec = dict(current)
    try:
        if "increase hp by" in prompt.lower():
            import re
            m = re.search(r"increase hp by\s*(\d+)", prompt.lower())
            if m:
                delta = int(m.group(1))
            else:
                delta = 1
            spec["hp"] = int(spec.get("hp", 1)) + delta
        if "double damage" in prompt.lower() or "double the damage" in prompt.lower():
            spec["damage"] = float(spec.get("damage", 1)) * 2
        ti = list(spec.get("texture_instructions") or [])
        ti.append(f"[mock applied] {prompt}")
        spec["texture_instructions"] = ti
        validated = validate_spec(spec)
        return {"spec": validated}
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def validate_spec_endpoint(payload: dict = Body(...)):
    """Validate a spec without saving it."""
    from backend.schemas.spec_utils import validate_spec
    try:
        validated = validate_spec(payload)
        return {"valid": True, "spec": validated}
    except SpecValidationError as exc:
        # Return structured error with path information
        error_msg = str(exc)
        # Try to extract field name from error message
        field = None
        for key in ["identifier", "short_name", "display_name", "hp", "damage", "speed", 
                    "collision_box", "egg_base", "egg_overlay", "scale", "engine_min"]:
            if key in error_msg.lower():
                field = key
                break
        return {"valid": False, "error": error_msg, "field": field}
    
    # Use client-provided spec if available, otherwise fallback to server's 'current'
    current = data.get("current_spec")
    if not current:
        current = read_current_spec()
        
    try:
        spec = validate_spec(updated)
        print("[LLM] update complete; short_name=", spec.get("short_name"))
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        print(f"[LLM] error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    return {"spec": spec}


def index():
    """Serve the main HTML page."""
    from backend.core.core import FRONTEND_DIR
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text(encoding="utf-8"))

def styles_css():
    """Serve the main stylesheet."""
    from backend.core.core import FRONTEND_DIR
    path = FRONTEND_DIR / "styles.css"
    if not path.exists():
        # Fallback: minimal inline CSS if file missing
        return PlainTextResponse("/* styles.css not found */", media_type="text/css")
    return FileResponse(path, media_type="text/css")

def serve_js(filename: str):
    """Serve JavaScript files from frontend/js directory."""
    from backend.core.core import FRONTEND_DIR
    # Sanitize filename to prevent directory traversal
    safe_filename = filename.replace("..", "").replace("/", "").replace("\\", "")
    path = FRONTEND_DIR / "js" / safe_filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"JS file not found: {safe_filename}")
    return FileResponse(path, media_type="application/javascript")


def healthz():
    """Health check endpoint."""
    return PlainTextResponse("ok")


def build_form(resource: Optional[UploadFile] = File(None),
               behavior: Optional[UploadFile] = File(None),
               build_mode: str = Form("bundle")):
    """Build endpoint for form submissions."""
    tmp = Path(tempfile.mkdtemp(prefix="http_"))
    try:
        res_path = _save_upload(tmp, resource)
        beh_path = _save_upload(tmp, behavior)
        kind, artifact, _ = _build_and_bundle(res_path, beh_path, build_mode=build_mode)
        media_type = "application/zip" if kind != "mcworld" else "application/octet-stream"
        return FileResponse(artifact, filename=artifact.name, media_type=media_type)
    finally:
        pass


async def api_build(resource: Optional[UploadFile] = File(None),
                    behavior: Optional[UploadFile] = File(None),
                    build_mode: str = Form("bundle"),
                    target_mobs: Optional[str] = Form(None),
                    specs_json: Optional[str] = Form(None),
                    textures_json: Optional[str] = Form(None)):
    """Build endpoint for JSON API."""
    import json
    import base64
    from backend.schemas.spec_utils import validate_spec
    from backend.core.core import SPECS_DIR
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

        # Save textures from localStorage to temp directory for build process
        textures_dir = tmp / "textures"
        textures_dir.mkdir(parents=True, exist_ok=True)
        if textures_json:
            try:
                textures = json.loads(textures_json)
                for mob_name, base64_data in textures.items():
                    # base64_data is like "data:image/png;base64,iVBORw0..."
                    if "," in base64_data:
                        base64_data = base64_data.split(",", 1)[1]
                    png_bytes = base64.b64decode(base64_data)
                    tex_path = textures_dir / f"{mob_name}.png"
                    tex_path.write_bytes(png_bytes)
            except Exception as e:
                print(f"[BUILD] Warning: Failed to process textures: {e}")

        res_path = _save_upload(tmp, resource)
        beh_path = _save_upload(tmp, behavior)
        kind, artifact, artifacts = _build_and_bundle(res_path, beh_path, specs_override=specs_override, build_mode=build_mode, textures_dir=textures_dir)

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


def download(name: str):
    """Download a previously built artifact."""
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


# ---------------------------------------------------------------------------
# Server Test Session (One-Click Play)
# ---------------------------------------------------------------------------

# Add scripts/ to sys.path for launch_server_session imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts"))

# Global state for the running server session
_server_session_lock = threading.Lock()
_server_session = {
    "running": False,
    "thread": None,
    "proc": None,
    "status": "idle",       # idle | starting | ready | error | stopped
    "logs": [],
    "error": None,
}


def _run_server_session_thread(pack_dir: str, resource_pack_dir: str | None, category: str):
    """Background thread that runs the full BDS lifecycle."""
    from launch_server_session import (
        setup_server, _read_server_output, _launch_client,
        _kill_minecraft_client,
        _detect_identifiers, _build_command, BDS_EXE, BDS_DIR,
    )
    import subprocess
    import time

    session = _server_session
    session["logs"] = []
    session["error"] = None

    try:
        # Setup
        session["status"] = "starting"
        session["logs"].append("[api] Setting up server...")
        setup_server(pack_dir, resource_pack_path=resource_pack_dir)
        session["logs"].append("[api] Server configured.")

        # Detect all identifiers
        pack_path = Path(pack_dir).resolve()
        identifiers = _detect_identifiers(pack_path, category)
        commands: list[str] = []
        if identifiers:
            for ident in identifiers:
                cmd = _build_command(ident, category)
                commands.append(cmd)
                session["logs"].append(f"[api] Will run: /{cmd}")
        else:
            session["logs"].append("[api] No identifiers detected, skipping auto-give.")

        # Launch BDS
        event_server_ready = threading.Event()
        event_player_spawned = threading.Event()
        event_fatal_error = threading.Event()
        event_no_targets = threading.Event()

        proc = subprocess.Popen(
            [str(BDS_EXE)],
            cwd=str(BDS_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        session["proc"] = proc

        reader = threading.Thread(
            target=_read_server_output,
            args=(proc, event_server_ready, event_player_spawned,
                  event_fatal_error, event_no_targets, session["logs"]),
            daemon=True,
        )
        reader.start()

        # Wait for server ready (bail on fatal error)
        while not event_server_ready.is_set():
            if event_fatal_error.wait(timeout=1):
                session["status"] = "error"
                session["error"] = "BDS fatal: vanilla resource pack missing. Re-extract BDS zip."
                proc.kill()
                return
            if event_server_ready.wait(timeout=1):
                break
            if proc.poll() is not None:
                session["status"] = "error"
                session["error"] = "BDS exited unexpectedly."
                return

        session["status"] = "ready"
        session["logs"].append("[api] Server is READY on port 19132")

        # Launch client (kill stale instances first)
        _kill_minecraft_client()
        time.sleep(3)
        _launch_client()
        session["logs"].append("[api] Minecraft client launched.")

        # Wait for player spawn + magic
        if commands:
            session["logs"].append("[api] Waiting for player to spawn...")
            if event_player_spawned.wait(timeout=120):
                time.sleep(2)
                for cmd in commands:
                    event_no_targets.clear()
                    proc.stdin.write(cmd + "\n")
                    proc.stdin.flush()
                    session["logs"].append(f"[api] Sent: /{cmd}")
                    # Retry once if no targets
                    if event_no_targets.wait(timeout=3):
                        time.sleep(3)
                        event_no_targets.clear()
                        proc.stdin.write(cmd + "\n")
                        proc.stdin.flush()
                        session["logs"].append(f"[api] Retry sent: /{cmd}")
                    time.sleep(1)  # small gap between multiple summons
                session["logs"].append(f"[api] Magic complete! ({len(commands)} command(s))")

        # Keep alive until stopped externally
        proc.wait()

    except Exception as exc:
        session["status"] = "error"
        session["error"] = str(exc)
    finally:
        session["running"] = False
        if session["status"] not in ("error",):
            session["status"] = "stopped"
        if session.get("proc") and session["proc"].poll() is None:
            session["proc"].kill()


async def launch_test(payload: dict = Body(...)):
    """POST /api/launch-test \u2014 Build the addon and start a BDS test session."""
    with _server_session_lock:
        if _server_session["running"]:
            raise HTTPException(status_code=409, detail="A test session is already running. Stop it first.")

    # Get specs from payload
    specs_json = payload.get("specs", [])
    category = payload.get("category", "entity_logic_ai")

    if not specs_json:
        raise HTTPException(status_code=400, detail="No specs provided.")

    try:
        specs = [validate_spec(s) for s in specs_json]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid spec: {exc}")

    # Save textures from payload to temp directory for build process
    import base64
    textures_dir = None
    textures_json = payload.get("textures", {})
    if textures_json and isinstance(textures_json, dict):
        tex_tmp = Path(tempfile.mkdtemp(prefix="test_tex_"))
        textures_dir = tex_tmp
        for mob_name, base64_data in textures_json.items():
            try:
                if isinstance(base64_data, str) and base64_data:
                    if "," in base64_data:
                        base64_data = base64_data.split(",", 1)[1]
                    png_bytes = base64.b64decode(base64_data)
                    tex_path = textures_dir / f"{mob_name}.png"
                    tex_path.write_bytes(png_bytes)
            except Exception as e:
                print(f"[TEST] Warning: Failed to process texture for {mob_name}: {e}")

    # Build addon to get the behavior pack folder
    out_dir = Path(tempfile.mkdtemp(prefix="test_session_"))
    try:
        artifacts = build_addon(specs, out_dir, None, None, textures_dir=textures_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Build failed: {exc}")

    # Find the behavior pack folder
    beh_mcpack = artifacts.get("beh_mcpack")
    if not beh_mcpack or not Path(beh_mcpack).exists():
        raise HTTPException(status_code=500, detail="Build produced no behavior pack.")

    # Extract the mcpack (it's a zip) to a folder for BDS
    import zipfile
    pack_dir = out_dir / "bds_bp"
    pack_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(beh_mcpack, "r") as zf:
        zf.extractall(pack_dir)

    # Extract the resource pack too (textures, models, etc.)
    res_mcpack = artifacts.get("res_mcpack")
    rp_dir = None
    if res_mcpack and Path(res_mcpack).exists():
        rp_dir = out_dir / "bds_rp"
        rp_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(res_mcpack, "r") as zf:
            zf.extractall(rp_dir)

    # Start the server session in a background thread
    with _server_session_lock:
        _server_session["running"] = True
        _server_session["status"] = "starting"
        _server_session["logs"] = []
        _server_session["error"] = None
        _server_session["proc"] = None

        t = threading.Thread(
            target=_run_server_session_thread,
            args=(str(pack_dir), str(rp_dir) if rp_dir else None, category),
            daemon=True,
        )
        _server_session["thread"] = t
        t.start()

    return {"status": "starting", "message": "Test session is launching..."}


def launch_test_status():
    """GET /api/launch-test/status \u2014 Poll the current test session state."""
    return {
        "running": _server_session["running"],
        "status": _server_session["status"],
        "error": _server_session["error"],
        "log_count": len(_server_session["logs"]),
        "recent_logs": _server_session["logs"][-20:],
    }


async def launch_test_stop():
    """POST /api/launch-test/stop \u2014 Stop the running test session."""
    proc = _server_session.get("proc")
    if proc and proc.poll() is None:
        try:
            proc.stdin.write("stop\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        _server_session["status"] = "stopped"
        _server_session["running"] = False
        return {"status": "stopped", "message": "Server stopped."}
    else:
        _server_session["status"] = "idle"
        _server_session["running"] = False
        return {"status": "idle", "message": "No server was running."}
