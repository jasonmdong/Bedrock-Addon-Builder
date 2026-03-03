"""
FastAPI route handlers for mctools MCP integration.

Exposes in-scope MCP tools as REST endpoints:
- POST /api/mctools/validate        → validateContent
- POST /api/mctools/validate-file   → validateFile
- POST /api/mctools/create-project  → createProject
- POST /api/mctools/add-item        → addItem
- POST /api/mctools/create-content  → createMinecraftContent
- POST /api/mctools/content-schema  → getEffectiveContentSchema
- POST /api/mctools/design-model    → designModel
- POST /api/mctools/design-structure → designStructure
- GET  /api/mctools/model-templates → getModelTemplates
- POST /api/mctools/read-image      → readImageFile
- POST /api/mctools/write-image     → writeImageFile
- POST /api/mctools/write-image-svg → writeImageFileFromSvg
- POST /api/mctools/write-image-pixel-art → writeImageFileFromPixelArt
- GET  /api/mctools/health          → health check
"""

import json
import logging
import time
from typing import Any

from fastapi import HTTPException, Body
from fastapi.responses import JSONResponse

from backend.mctools.client import call_tool, is_available, MCTOOLS_ENABLED

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_enabled():
    if not MCTOOLS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Minecraft Creator Tools integration is disabled. Set MCTOOLS_ENABLED=true.",
        )


async def _call(tool_name: str, arguments: dict[str, Any]) -> JSONResponse:
    """Call an MCP tool and return the result as a JSON response."""
    _require_enabled()
    try:
        result = await call_tool(tool_name, arguments)
        if result.get("isError"):
            # Tool executed but reported an error in its content
            text_parts = [
                c.get("text", "") for c in result.get("content", [])
                if c.get("type") == "text"
            ]
            return JSONResponse(
                status_code=422,
                content={"error": True, "detail": "\n".join(text_parts), "content": result["content"]},
            )
        return JSONResponse(content={"ok": True, "content": result["content"]})
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def mctools_health():
    """GET /api/mctools/health — Check if mctools is available."""
    available = await is_available()
    return JSONResponse(content={
        "enabled": MCTOOLS_ENABLED,
        "available": available,
    })


async def mctools_validate(body: dict = Body(...)):
    """POST /api/mctools/validate — Validate Minecraft content (JSON or base64 ZIP)."""
    content = body.get("content")
    if not content:
        raise HTTPException(status_code=400, detail="Missing 'content' field (JSON string or base64 ZIP)")
    return await _call("validateContent", {"jsonContentOrBase64ZipContent": content})


async def mctools_validate_file(body: dict = Body(...)):
    """POST /api/mctools/validate-file — Validate content at a file path."""
    file_path = body.get("filePath")
    if not file_path:
        raise HTTPException(status_code=400, detail="Missing 'filePath' field")
    return await _call("validateFile", {"filePath": file_path})


async def mctools_create_project(body: dict = Body(...)):
    """POST /api/mctools/create-project — Create a new Minecraft project."""
    required = ["folderPathToCreateProjectAt", "title", "newName", "creator", "template"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing required field '{field}'")
    return await _call("createProject", body)


async def mctools_add_item(body: dict = Body(...)):
    """POST /api/mctools/add-item — Add an item to a project."""
    required = ["folderPathToCreateProjectAt", "templateType", "name"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing required field '{field}'")
    return await _call("addItem", body)


async def mctools_create_content(body: dict = Body(...)):
    """POST /api/mctools/create-content — Create Minecraft content from meta-schema."""
    if "definition" not in body or "outputPath" not in body:
        raise HTTPException(status_code=400, detail="Missing 'definition' and/or 'outputPath'")
    return await _call("createMinecraftContent", body)


async def mctools_content_schema(body: dict = Body(...)):
    """POST /api/mctools/content-schema — Get effective content schema for a project."""
    folder_path = body.get("folderPath")
    if not folder_path:
        raise HTTPException(status_code=400, detail="Missing 'folderPath' field")
    args: dict[str, Any] = {"folderPath": folder_path}
    if "options" in body:
        args["options"] = body["options"]
    return await _call("getEffectiveContentSchema", args)


async def mctools_design_model(body: dict = Body(...)):
    """POST /api/mctools/design-model — Design a 3D model."""
    required = ["projectPath", "design", "modelId"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing required field '{field}'")
    args = {k: v for k, v in body.items() if k in ("projectPath", "design", "modelId", "usage", "wireTo")}
    return await _call("designModel", args)


async def mctools_design_structure(body: dict = Body(...)):
    """POST /api/mctools/design-structure — Design a structure."""
    required = ["projectPath", "blockVolume", "structureId"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing required field '{field}'")
    return await _call("designStructure", body)


async def mctools_model_templates(templateType: str = "humanoid"):
    """GET /api/mctools/model-templates?templateType=humanoid — Get model templates."""
    return await _call("getModelTemplates", {"templateType": templateType})


async def mctools_read_image(body: dict = Body(...)):
    """POST /api/mctools/read-image — Read an image file."""
    file_path = body.get("filePath")
    if not file_path:
        raise HTTPException(status_code=400, detail="Missing 'filePath' field")
    return await _call("readImageFile", {"filePath": file_path})


async def mctools_write_image(body: dict = Body(...)):
    """POST /api/mctools/write-image — Write base64 image data to a file."""
    required = ["filePath", "base64Data"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing required field '{field}'")
    args = {k: v for k, v in body.items() if k in ("filePath", "base64Data", "mimeType")}
    return await _call("writeImageFile", args)


async def mctools_write_image_svg(body: dict = Body(...)):
    """POST /api/mctools/write-image-svg — Convert SVG to PNG."""
    required = ["filePath", "svgContent"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing required field '{field}'")
    args = {k: v for k, v in body.items() if k in ("filePath", "svgContent", "width", "height")}
    return await _call("writeImageFileFromSvg", args)


async def mctools_write_image_pixel_art(body: dict = Body(...)):
    """POST /api/mctools/write-image-pixel-art — Create PNG from pixel art."""
    required = ["filePath", "lines", "palette"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing required field '{field}'")
    args = {k: v for k, v in body.items() if k in ("filePath", "lines", "palette", "scale", "backgroundColor")}
    return await _call("writeImageFileFromPixelArt", args)


# ---------------------------------------------------------------------------
# Diagnostic endpoint
# ---------------------------------------------------------------------------

async def mctools_diagnose():
    """GET /api/mctools/diagnose — Test each MCP tool and report what works."""
    from backend.mctools.client import (
        _mcp_post, _ensure_session, _extract_response, _next_id, _session_id,
    )

    results = {"enabled": MCTOOLS_ENABLED, "tests": []}

    if not MCTOOLS_ENABLED:
        results["error"] = "MCTOOLS_ENABLED is false"
        return JSONResponse(content=results)

    # Ensure session
    try:
        session = await _ensure_session()
        results["session_id"] = session
    except Exception as e:
        results["error"] = f"Session init failed: {e}"
        return JSONResponse(content=results)

    sh_id = session

    # Helper to call a tool and record the result
    async def test_tool(name: str, arguments: dict, timeout: float = 15.0):
        entry = {"tool": name, "arguments": arguments}
        start = time.time()
        try:
            result = await call_tool(name, arguments, timeout=timeout)
            entry["elapsed_ms"] = int((time.time() - start) * 1000)
            entry["isError"] = result.get("isError", False)
            content = result.get("content", [])
            entry["content_items"] = len(content)
            entry["content_preview"] = []
            for c in content[:5]:
                txt = (c.get("text") or "")[:500]
                entry["content_preview"].append({"type": c.get("type"), "text": txt})
            entry["status"] = "error" if result.get("isError") else "ok"
        except Exception as e:
            entry["elapsed_ms"] = int((time.time() - start) * 1000)
            entry["status"] = "exception"
            entry["error"] = str(e)
        results["tests"].append(entry)

    # List tools first
    try:
        req_id = _next_id()
        resp = await _mcp_post(
            {"jsonrpc": "2.0", "id": req_id, "method": "tools/list", "params": {}},
            sh_id, timeout=10,
        )
        ct = resp.headers.get("content-type", "")
        data = _extract_response(resp.text, ct, req_id)
        tools = data.get("result", {}).get("tools", [])
        results["available_tools"] = []
        for t in tools:
            tool_info = {"name": t.get("name")}
            schema = t.get("inputSchema", {})
            tool_info["required"] = schema.get("required", [])
            tool_info["properties"] = {
                k: {"type": v.get("type", "?"), "description": (v.get("description") or "")[:150]}
                for k, v in schema.get("properties", {}).items()
            }
            results["available_tools"].append(tool_info)
    except Exception as e:
        results["tools_list_error"] = str(e)

    # Test getModelTemplates (entity-type templates)
    await test_tool("getModelTemplates", {"templateType": "humanoid"})

    # Test validateContent with a real entity
    test_entity = json.dumps({
        "format_version": "1.21.0",
        "minecraft:entity": {
            "description": {"identifier": "custom:test", "is_spawnable": True, "is_summonable": True},
            "components": {"minecraft:health": {"value": 20, "max": 20}},
        }
    })
    await test_tool("validateContent", {"jsonContentOrBase64ZipContent": test_entity})

    # Test getModelTemplates (block template)
    await test_tool("getModelTemplates", {"templateType": "block"})

    return JSONResponse(content=results)
