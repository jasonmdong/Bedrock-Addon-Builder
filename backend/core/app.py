#!/usr/bin/env python3
"""
Bedrock Add-on Builder - FastAPI web server
Main entry point orchestrating all modules.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import route handlers
from backend.core.routes import (
    get_mobs,
    get_mob,
    get_mob_texture,
    save_mob_texture,
    save_mob,
    delete_mob,
    duplicate_mob,
    get_spec,
    replace_spec,
    patch_spec,
    llm_spec_editor,
    validate_spec_endpoint,
    llm_spec_mock,
    llm_geometry_generate,
    index,
    styles_css,
    serve_js,
    healthz,
    mcp_status,
    build_form,
    api_build,
    download,
    get_templates,
    get_template_mob_from_database,
    get_all_template_mob_names,
    fetch_mob_geometry,
    launch_test,
    launch_test_status,
    launch_test_stop,
)


# Create FastAPI app
app = FastAPI(title="Bedrock Add-on Builder", version="0.1.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# ====== API ROUTES =======
# =========================

# Mob management routes
app.get("/api/mobs")(get_mobs)
app.get("/api/mobs/{name}")(get_mob)
app.get("/api/mobs/{name}/texture")(get_mob_texture)
app.post("/api/mobs/{name}/texture")(save_mob_texture)
app.post("/api/mobs/{name}")(save_mob)
app.delete("/api/mobs/{name}")(delete_mob)
app.post("/api/mobs/{name}/duplicate")(duplicate_mob)

# Spec routes
app.get("/api/spec")(get_spec)
app.put("/api/spec")(replace_spec)
app.post("/api/spec/patch")(patch_spec)
app.post("/api/spec/llm")(llm_spec_editor)
app.post("/api/spec/validate")(validate_spec_endpoint)

# Build routes
app.post("/build")(build_form)
app.post("/api/build")(api_build)
app.get("/download/{name}")(download)
app.get("/api/templates")(get_templates)
app.get("/api/template/mobs")(get_all_template_mob_names)
app.get("/api/template/mob/{mob_name}")(get_template_mob_from_database)
app.get("/api/geometry/{mob_name}")(fetch_mob_geometry)
app.post("/api/geometry/generate")(llm_geometry_generate)
app.post("/api/spec/llm_mock")(llm_spec_mock)

# One-Click Play routes
app.post("/api/launch-test")(launch_test)
app.get("/api/launch-test/status")(launch_test_status)
app.post("/api/launch-test/stop")(launch_test_stop)

# Static routes
app.get("/")(index)
app.get("/styles.css")(styles_css)
app.get("/js/{filename}")(serve_js)
app.get("/healthz")(healthz)
app.get("/api/mcp/status")(mcp_status)

# =========================
# ======= WEB APP ==========
# =========================

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

