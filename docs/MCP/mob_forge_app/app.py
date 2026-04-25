"""
Mob Forge Web App — FastAPI backend that acts as an MCP client.
Spawns the MCP server as a subprocess and exposes REST endpoints.
"""

import os
import sys
import json
import uuid
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load .env from project root (parent of mob_forge_app/)
load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ─── In-Memory Gallery ─────────────────────────────────────────────────────────

gallery: dict[str, dict] = {}

# ─── MCP Client Session ────────────────────────────────────────────────────────

mcp_session: ClientSession | None = None
_mcp_context = None
_mcp_read = None
_mcp_write = None


async def connect_mcp():
    """Connect to the MCP server as a subprocess."""
    global mcp_session, _mcp_context, _mcp_read, _mcp_write

    server_path = str(Path(__file__).parent.parent / "mcp_server" / "server.py")
    server_dir = str(Path(__file__).parent.parent / "mcp_server")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_path],
        env={**os.environ},
        cwd=server_dir,
    )

    _mcp_context = stdio_client(server_params)
    _mcp_read, _mcp_write = await _mcp_context.__aenter__()

    mcp_session = ClientSession(_mcp_read, _mcp_write)
    await mcp_session.__aenter__()
    await mcp_session.initialize()

    # List available tools to verify connection
    tools = await mcp_session.list_tools()
    tool_names = [t.name for t in tools.tools]
    print(f"[MobForge] Connected to MCP server. Tools: {tool_names}")


async def disconnect_mcp():
    """Disconnect from the MCP server."""
    global mcp_session, _mcp_context
    if mcp_session:
        await mcp_session.__aexit__(None, None, None)
    if _mcp_context:
        await _mcp_context.__aexit__(None, None, None)


async def call_tool(tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool and return the parsed result."""
    if not mcp_session:
        raise HTTPException(status_code=503, detail="MCP server not connected")

    try:
        result = await mcp_session.call_tool(tool_name, arguments)
    except Exception as e:
        print(f"[MobForge ERROR] MCP call_tool exception: {e}")
        raise HTTPException(status_code=500, detail=f"MCP tool call failed: {str(e)}")

    print(f"[MobForge DEBUG] Tool '{tool_name}' isError={result.isError}, "
          f"content_blocks={len(result.content) if result.content else 0}")

    # Check for MCP tool errors
    if result.isError:
        error_text = "Unknown error"
        if result.content and len(result.content) > 0:
            error_text = getattr(result.content[0], "text", str(result.content[0]))
        print(f"[MobForge ERROR] MCP tool '{tool_name}' returned error: {error_text}")
        raise HTTPException(status_code=500, detail=f"MCP tool error: {error_text}")

    # MCP returns content as a list of content blocks
    if not result.content or len(result.content) == 0:
        print(f"[MobForge WARNING] Empty response from tool '{tool_name}'")
        return {"error": "Empty response from MCP server"}

    text = getattr(result.content[0], "text", None)
    if text is None:
        print(f"[MobForge WARNING] No text in content block from tool '{tool_name}'")
        return {"error": "No text content from MCP server"}

    print(f"[MobForge DEBUG] Tool '{tool_name}' response length: {len(text)} chars")
    print(f"[MobForge DEBUG] First 300 chars: {text[:300]}")

    try:
        parsed = json.loads(text)
        print(f"[MobForge DEBUG] Parsed keys: {list(parsed.keys())}")
        if "entity" in parsed:
            ent = parsed["entity"]
            print(f"[MobForge DEBUG] entity has {len(ent)} keys: {list(ent.keys())[:5]}")
        if "error" in parsed:
            print(f"[MobForge ERROR] Tool returned error in JSON: {parsed['error']}")
        return parsed
    except json.JSONDecodeError as e:
        print(f"[MobForge ERROR] JSON parse failed: {e}")
        print(f"[MobForge ERROR] Raw text: {text[:500]}")
        return {"error": f"JSON parse failed: {str(e)}", "raw": text}


# ─── App Lifecycle ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop MCP server with the app."""
    await connect_mcp()
    yield
    await disconnect_mcp()


app = FastAPI(title="Mob Forge", lifespan=lifespan)

# ─── Request/Response Models ───────────────────────────────────────────────────

class GenerateMobRequest(BaseModel):
    description: str = Field(..., description="Natural language mob description")
    difficulty: str = Field("medium", description="easy, medium, or hard")


class GenerateTextureRequest(BaseModel):
    mob_name: str
    description: str = ""
    style: str = "biped"
    colors: list[str] = Field(default=["#4A7023", "#2E4F1E", "#1A2E0F"])
    size: int = 16


class BuildPackRequest(BaseModel):
    mob_ids: list[str] = Field(..., description="Gallery mob IDs to include")
    pack_name: str = "custom_mobs"


# ─── API Endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/generate-mob")
async def api_generate_mob(req: GenerateMobRequest):
    """Generate a new mob and add it to the gallery."""
    result = await call_tool("generate_mob", {
        "description": req.description,
        "difficulty": req.difficulty,
    })

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Debug: log what we got back
    print(f"[MobForge DEBUG] generate_mob result keys: {list(result.keys())}")
    entity = result.get("entity", {})
    metadata = result.get("metadata", {})
    print(f"[MobForge DEBUG] entity keys: {list(entity.keys()) if entity else 'EMPTY'}")
    print(f"[MobForge DEBUG] metadata: {metadata}")

    # Store in gallery
    mob_id = str(uuid.uuid4())
    gallery[mob_id] = {
        "id": mob_id,
        "entity": entity,
        "metadata": metadata,
        "texture_base64": None,
        "geometry_data": None,
        "prompt": req.description,
        "difficulty": req.difficulty,
    }

    # Auto-generate custom geometry for this mob
    mc_entity = entity.get("minecraft:entity", {})
    identifier = mc_entity.get("description", {}).get("identifier", "custom:mob")
    mob_name = identifier.split(":")[-1]
    cbox = mc_entity.get("components", {}).get("minecraft:collision_box", {})
    try:
        geo_result = await call_tool("generate_mob_geometry", {
            "mob_name": mob_name,
            "description": req.description,
            "collision_width": cbox.get("width", 0.9),
            "collision_height": cbox.get("height", 1.4),
        })
        if "error" not in geo_result and "geometry" in geo_result:
            gallery[mob_id]["geometry_data"] = geo_result["geometry"]
            gallery[mob_id]["geometry_id"] = geo_result.get("geometry_id", f"geometry.{mob_name}")
            print(f"[MobForge] Generated custom geometry: {geo_result.get('geometry_id')} ({geo_result.get('bone_count')} bones)")
        else:
            print(f"[MobForge WARNING] Geometry generation failed: {geo_result.get('error', 'unknown')}")
    except Exception as e:
        print(f"[MobForge WARNING] Geometry generation exception: {e}")

    # Auto-generate texture for this mob
    try:
        tex_result = await call_tool("generate_mob_texture", {
            "mob_name": metadata.get("display_name", mob_name),
            "description": req.description,
            "style": metadata.get("suggested_style", "zombie"),
            "colors": metadata.get("suggested_colors", ["#808080", "#606060", "#404040"]),
            "size": 16,
        })
        if "error" not in tex_result and tex_result.get("texture_base64"):
            gallery[mob_id]["texture_base64"] = tex_result["texture_base64"]
            print(f"[MobForge] Generated texture for {mob_name}")
        else:
            print(f"[MobForge WARNING] Texture generation failed: {tex_result.get('error', 'unknown')}")
    except Exception as e:
        print(f"[MobForge WARNING] Texture generation exception: {e}")

    return {"id": mob_id, **gallery[mob_id]}


@app.post("/api/generate-texture")
async def api_generate_texture(req: GenerateTextureRequest):
    """Generate a texture for a mob."""
    result = await call_tool("generate_mob_texture", {
        "mob_name": req.mob_name,
        "description": req.description,
        "style": req.style,
        "colors": req.colors,
        "size": req.size,
    })

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/api/generate-texture/{mob_id}")
async def api_generate_texture_for_mob(mob_id: str):
    """Generate a texture for a gallery mob using its metadata."""
    if mob_id not in gallery:
        raise HTTPException(status_code=404, detail="Mob not found")

    mob = gallery[mob_id]
    metadata = mob.get("metadata", {})

    result = await call_tool("generate_mob_texture", {
        "mob_name": metadata.get("display_name", "mob"),
        "description": metadata.get("description", mob.get("prompt", "")),
        "style": metadata.get("suggested_style", "biped"),
        "colors": metadata.get("suggested_colors", ["#4A7023", "#2E4F1E", "#1A2E0F"]),
        "size": 16,
    })

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Store texture in gallery
    gallery[mob_id]["texture_base64"] = result.get("texture_base64")
    return result


@app.post("/api/build-pack")
async def api_build_pack(req: BuildPackRequest):
    """Build .mcpack files from selected gallery mobs."""
    mobs_data = []
    for mob_id in req.mob_ids:
        if mob_id not in gallery:
            raise HTTPException(status_code=404, detail=f"Mob {mob_id} not found")
        mob = gallery[mob_id]
        mobs_data.append({
            "entity": mob["entity"],
            "metadata": mob.get("metadata", {}),
            "texture_base64": mob.get("texture_base64"),
        })

    result = await call_tool("build_mob_pack", {
        "mobs": mobs_data,
        "pack_name": req.pack_name,
    })

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/api/download-mob/{mob_id}")
async def api_download_single_mob(mob_id: str):
    """Build and download .mcpack for a single mob."""
    if mob_id not in gallery:
        raise HTTPException(status_code=404, detail="Mob not found")

    mob = gallery[mob_id]
    identifier = mob["entity"].get("minecraft:entity", {}).get("description", {}).get("identifier", "custom:mob")
    mob_name = identifier.split(":")[-1]

    result = await call_tool("build_mob_pack", {
        "mobs": [{
            "entity": mob["entity"],
            "metadata": mob.get("metadata", {}),
            "texture_base64": mob.get("texture_base64"),
            "geometry_data": mob.get("geometry_data"),
        }],
        "pack_name": mob_name,
    })

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/api/download-world/{mob_id}")
async def api_download_world(mob_id: str):
    """Build and download a .mcworld with a single mob pre-summoned."""
    if mob_id not in gallery:
        raise HTTPException(status_code=404, detail="Mob not found")

    mob = gallery[mob_id]
    metadata = mob.get("metadata", {})
    identifier = mob["entity"].get("minecraft:entity", {}).get("description", {}).get("identifier", "custom:mob")
    mob_name = identifier.split(":")[-1]

    result = await call_tool("build_mcworld", {
        "mobs": [{
            "entity": mob["entity"],
            "metadata": metadata,
            "texture_base64": mob.get("texture_base64"),
            "geometry_data": mob.get("geometry_data"),
        }],
        "pack_name": mob_name,
    })

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.get("/api/gallery")
async def api_gallery():
    """Get all mobs in the gallery."""
    return {"mobs": list(gallery.values())}


@app.delete("/api/gallery/{mob_id}")
async def api_delete_mob(mob_id: str):
    """Remove a mob from the gallery."""
    if mob_id not in gallery:
        raise HTTPException(status_code=404, detail="Mob not found")
    del gallery[mob_id]
    return {"status": "deleted", "id": mob_id}


# ─── Static Files & SPA Fallback ───────────────────────────────────────────────

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_index():
    """Serve the main page."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Mob Forge API — frontend not found. Place index.html in static/"}


# ─── Run ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
