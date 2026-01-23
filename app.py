#!/usr/bin/env python3
"""
Bedrock Add-on Builder - FastAPI web server
Main entry point orchestrating all modules.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import route handlers
from routes import (
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
    index,
    styles_css,
    healthz,
    build_form,
    api_build,
    download,
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

# Build routes
app.post("/build")(build_form)
app.post("/api/build")(api_build)
app.get("/download/{name}")(download)

# Static routes
app.get("/")(index)
app.get("/styles.css")(styles_css)
app.get("/healthz")(healthz)

# =========================
# ======= WEB APP ==========
# =========================

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

