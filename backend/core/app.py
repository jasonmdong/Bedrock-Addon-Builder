#!/usr/bin/env python3
"""
Bedrock Add-on Builder - FastAPI web server
Main entry point orchestrating all modules.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parents[2] / ".env"
    if _env.exists():
        load_dotenv(_env, override=True)
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import route handlers
from backend.core.routes import (
    upsert_user,
    get_user,
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
    get_llm_categories,
    index,
    styles_css,
    serve_js,
    healthz,
    build_form,
    api_build,
    download,
    get_templates,
    get_template_mob_from_database,
    get_all_template_mob_names,
    generate_mob_from_similar,
    generate_complete_mob,
    fetch_mob_geometry,
    launch_test,
    launch_test_status,
    launch_test_stop,
    publish_mob_to_database,
    check_published_mob,
    llm_animation_generate,
    llm_animation_controller_generate,
    auth_signup,
    auth_login,
    auth_logout,
    auth_me,
    get_user_mobs,
    upsert_user_mob,
    delete_user_mob_db,
    get_mob_versions,
    push_mob_version,
    list_published_mobs,
    market_page,
    get_published_mob,
)
from backend.mctools.routes import (
    mctools_health,
    mctools_diagnose,
    mctools_validate,
    mctools_validate_file,
    mctools_create_project,
    mctools_add_item,
    mctools_create_content,
    mctools_content_schema,
    mctools_design_model,
    mctools_design_structure,
    mctools_model_templates,
    mctools_read_image,
    mctools_write_image,
    mctools_write_image_svg,
    mctools_write_image_pixel_art,
)
from backend.mctools.client import stop_mctools_server


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

# Shutdown hook: stop mctools subprocess when the app exits
@app.on_event("shutdown")
def shutdown_event():
    stop_mctools_server()


@app.on_event("startup")
def startup_event():
    try:
        from backend.database.db import run_migrations
        run_migrations()
    except Exception as e:
        print(f"[Startup] Migration skipped: {e}")

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
app.get("/api/llm/categories")(get_llm_categories)

# Build routes
app.post("/build")(build_form)
app.post("/api/build")(api_build)
app.get("/download/{name}")(download)
app.get("/api/templates")(get_templates)
app.get("/api/template/mobs")(get_all_template_mob_names)
app.get("/api/template/mob/{mob_name}")(get_template_mob_from_database)
app.post("/api/template/generate")(generate_mob_from_similar)
app.post("/api/mob/generate-complete")(generate_complete_mob)
app.get("/api/geometry/{mob_name}")(fetch_mob_geometry)
app.post("/api/geometry/generate")(llm_geometry_generate)
app.post("/api/spec/llm_mock")(llm_spec_mock)

# One-Click Play routes
app.post("/api/launch-test")(launch_test)
app.get("/api/launch-test/status")(launch_test_status)
app.post("/api/launch-test/stop")(launch_test_stop)

# Minecraft Creator Tools (MCP) routes
app.get("/api/mctools/health")(mctools_health)
app.get("/api/mctools/diagnose")(mctools_diagnose)
app.post("/api/mctools/validate")(mctools_validate)
app.post("/api/mctools/validate-file")(mctools_validate_file)
app.post("/api/mctools/create-project")(mctools_create_project)
app.post("/api/mctools/add-item")(mctools_add_item)
app.post("/api/mctools/create-content")(mctools_create_content)
app.post("/api/mctools/content-schema")(mctools_content_schema)
app.post("/api/mctools/design-model")(mctools_design_model)
app.post("/api/mctools/design-structure")(mctools_design_structure)
app.get("/api/mctools/model-templates")(mctools_model_templates)
app.post("/api/mctools/read-image")(mctools_read_image)
app.post("/api/mctools/write-image")(mctools_write_image)
app.post("/api/mctools/write-image-svg")(mctools_write_image_svg)
app.post("/api/mctools/write-image-pixel-art")(mctools_write_image_pixel_art)

# Animation generation routes
app.post("/api/animation/generate")(llm_animation_generate)
app.post("/api/animation/controller/generate")(llm_animation_controller_generate)

# Auth routes
app.post("/api/auth/signup")(auth_signup)
app.post("/api/auth/login")(auth_login)
app.post("/api/auth/logout")(auth_logout)
app.get("/api/auth/me")(auth_me)

# User mob storage routes (per-user mob_creations + mob_versions)
app.get("/api/user/mobs")(get_user_mobs)
app.post("/api/user/mobs/{mob_name}")(upsert_user_mob)
app.delete("/api/user/mobs/{mob_name}")(delete_user_mob_db)
app.get("/api/user/mobs/{mob_name}/versions")(get_mob_versions)
app.post("/api/user/mobs/{mob_name}/versions")(push_mob_version)

# User account routes (demo subscription tier sync)
app.post("/api/users")(upsert_user)
app.get("/api/users/{username}")(get_user)

# Publish routes (save user mobs to database for RAG)
app.post("/api/publish")(publish_mob_to_database)
app.get("/api/publish/check/{mob_name}/{username}")(check_published_mob)
app.get("/api/market")(list_published_mobs)
app.get("/api/market/{mob_name}")(get_published_mob)

# Static routes
app.get("/")(index)
app.get("/market")(market_page)
app.get("/styles.css")(styles_css)
app.get("/js/{filename:path}")(serve_js)
app.get("/healthz")(healthz)

# =========================
# ======= WEB APP ==========
# =========================

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

