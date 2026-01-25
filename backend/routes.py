"""FastAPI route handlers for the web API."""
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import File, Form, HTTPException, Body, UploadFile, Response
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, JSONResponse

from spec_utils import (
    read_mob_spec, write_mob_spec, delete_mob_spec, list_mob_names,
    read_current_spec, write_current_spec, apply_spec_patch,
    SpecValidationError
)
from llm import llm_rewrite_spec
from packaging import build_addon
import shutil


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
        from spec_utils import validate_spec
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
    from core import BACKEND_DIR
    import json
    path = BACKEND_DIR / "data" / "vanilla_mobs.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Failed to load templates: {e}")
    return {"mobs": {}}


def get_mob(name: str):
    """Retrieve a specific mob spec."""
    from schemas_loader import SPEC_SCHEMA
    try:
        spec = read_mob_spec(name)
        return {"spec": spec, "schema": SPEC_SCHEMA}
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def get_mob_texture(name: str):
    """Get a mob's texture image."""
    from builders import make_png_rgba
    from core import COLOR_WORDS, SPECS_DIR
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
    from core import SPECS_DIR
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
    from schemas_loader import SPEC_SCHEMA
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
    prompt = data.get("prompt", "")
    if not prompt or not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    provider = data.get("provider")
    api_key = data.get("api_key")
    print(f"[LLM] provider={provider} prompt_len={len(prompt.strip())}")
    
    # Use client-provided spec if available, otherwise fallback to server's 'current'
    current = data.get("current_spec")
    if not current:
        current = read_current_spec()
        
    try:
        updated = llm_rewrite_spec(prompt, current, provider, api_key)
        # We don't necessarily want to write to the server's disk here if using client-side storage,
        # but returning it is enough. We'll return it as a validated spec.
        from spec_utils import validate_spec
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
    from core import FRONTEND_DIR
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text(encoding="utf-8"))

def styles_css():
    """Serve the main stylesheet."""
    from core import FRONTEND_DIR
    path = FRONTEND_DIR / "styles.css"
    if not path.exists():
        # Fallback: minimal inline CSS if file missing
        return PlainTextResponse("/* styles.css not found */", media_type="text/css")
    return FileResponse(path, media_type="text/css")


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
    from spec_utils import validate_spec
    from core import SPECS_DIR
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
