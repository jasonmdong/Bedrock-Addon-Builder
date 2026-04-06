# MCP Master Pipeline Documentation

## Overview

This document describes how the current Minecraft Creator Tools (MCP) pipeline works in Bedrock Addon Builder.

It covers:
- MCP server architecture
- Backend MCP client and route layer
- LLM augmentation flow
- Geometry generation flow
- `designModel` texture generation flow
- Frontend texture/geometry handling
- Build/export behavior
- Current limitations and important implementation notes

This is the authoritative summary of the current implemented pipeline.

---

## High-Level Architecture

The MCP integration is a layered pipeline:

```text
Browser UI
  ↓
Frontend JS
  ↓
FastAPI routes
  ↓
Python MCP client
  ↓
Node mctools-int MCP server
  ↓
Minecraft Creator Tools logic
```

There are two major MCP use cases in the app:

1. **LLM augmentation**
   - Fetching model templates for better prompting
   - Optionally generating a texture + matching geometry after a mob type change

2. **Direct MCP tool proxying**
   - Health checks
   - Validation
   - Design model / design structure
   - Image reads/writes
   - Model template retrieval

---

## Core Files

### Backend

- `backend/mctools/client.py`
  - Manages MCP subprocess lifecycle
  - Handles session initialization
  - Sends JSON-RPC requests over MCP Streamable HTTP
  - Parses SSE responses

- `backend/mctools/routes.py`
  - FastAPI proxy routes for MCP tools

- `backend/llm/mcp_context.py`
  - MCP-aware context retrieval for LLM calls
  - Template fetching
  - `designModel` integration
  - Geometry-to-design conversion
  - Texture/geometry extraction from generated MCP project files

- `backend/llm/llm.py`
  - Main LLM pipeline
  - Invokes MCP context retrieval
  - Invokes `designModel` for texture generation
  - Attaches generated texture to the response
  - Updates geometry to match MCP-generated UV layout

- `backend/core/routes.py`
  - `/api/spec/llm`
  - `/api/geometry/generate`
  - Extracts `_texture_b64` and returns it to frontend

- `backend/core/builders.py`
  - Build/export pipeline
  - Writes final geometry JSON and texture PNG into the resource pack

### Frontend

- `frontend/js/llm.js`
  - Sends LLM spec edit requests
  - Saves returned `texture_b64` to local storage
  - Re-renders geometry if needed

- `frontend/js/viewer3d.js`
  - Renders geometry in 3D
  - Supports both box UV and per-face UV
  - Applies texture atlas to geometry

- `frontend/js/painter.js`
  - Loads texture atlas into the painter canvas

- `frontend/js/mctools.js`
  - MCP health polling and MCP UI wiring

---

## MCP Server and Transport

### MCP server

The app uses Mojang's `mctools-int` package as a local Node.js MCP server.

Location:
- `McpGettingStarted/mctools-int-0.0.1/package/`

The backend auto-starts it on first use.

### Transport model

The Python backend talks to MCP using:
- JSON-RPC
- Streamable HTTP
- Server-Sent Events (SSE) responses

Important details:
- All tool calls go through `POST /mcp`
- MCP requires a session handshake
- Responses often come back as SSE instead of plain JSON
- The backend parses `data:` lines from the SSE stream

### Session lifecycle

`backend/mctools/client.py` is responsible for:
- starting the Node server if needed
- initializing the MCP session
- reusing the session
- recovering from stale sessions
- killing and restarting the subprocess if necessary

---

## FastAPI MCP Route Layer

`backend/mctools/routes.py` exposes Python HTTP endpoints like:

- `GET /api/mctools/health`
- `POST /api/mctools/validate`
- `POST /api/mctools/design-model`
- `POST /api/mctools/design-structure`
- `GET /api/mctools/model-templates`
- `POST /api/mctools/read-image`
- `POST /api/mctools/write-image`

These routes are thin proxies over `call_tool()` in `backend/mctools/client.py`.

---

## LLM Augmentation Pipeline

### Purpose

Before calling the LLM, the app uses MCP to retrieve useful reference material.

### Flow

When `/api/spec/llm` is called:

1. `backend/core/routes.py::llm_spec_editor()` receives the request
2. It calls `backend/llm/llm.py::llm_rewrite_spec()`
3. `llm_rewrite_spec()` calls `retrieve_context_sync()` from `backend/llm/mcp_context.py`
4. MCP context retrieval may call:
   - `getModelTemplates`
5. Retrieved context is injected into the LLM system prompt
6. The LLM generates the updated spec
7. MCP texture generation may run if the mob identity changed
8. The response returns:
   - updated spec
   - MCP metadata
   - `texture_b64` if generated

### Context retrieval

`retrieve_context()` in `backend/llm/mcp_context.py` is responsible for:
- deciding whether MCP should be used
- fetching model templates
- caching results
- timing retrieval
- graceful fallback if MCP is unavailable

### Template detection

`_detect_template_type(prompt, category)` maps user prompts to an MCP model template type.

Examples:
- rhino / elephant / cow-like prompts → `large_animal`
- humanoid prompts → `humanoid`
- fish prompts → `fish`

This gives the LLM a better geometric reference than pure freeform generation.

---

## Geometry Generation Pipeline

### Route

`POST /api/geometry/generate`

### Flow

1. `backend/core/routes.py::llm_geometry_generate()` receives the request
2. It calls `backend/llm/llm.py::llm_generate_geometry()`
3. The LLM produces geometry JSON
4. If MCP is available, `mcp_design_model_sync()` is called
5. MCP returns:
   - texture atlas PNG
   - generated geometry with per-face UV mapping
6. The backend returns:
   - `geometry`
   - `texture_b64`
   - `mcp_texture: true`
7. Frontend stores texture and renders the geometry

### Important behavior

In the geometry generation path, the MCP-generated geometry is already used as the final geometry if available.

This is important because the geometry and texture atlas must match.

---

## Spec Editing Texture Generation Pipeline

### Route

`POST /api/spec/llm`

### Trigger condition

In `llm_rewrite_spec()`, MCP texture generation only runs when:
- category is `entity_logic_ai`
- old display name and new display name differ
- geometry exists in `geometry_json`

### Flow

1. The LLM updates the current spec
2. The backend compares old and new mob identity
3. If the mob changed, it calls:
   - `mcp_design_model_sync(geometry, safe_id, prompt)`
4. MCP generates:
   - a texture atlas PNG
   - matching geometry with per-face UV layout
5. The backend now updates:
   - `output_spec["geometry_json"] = design_result.geometry`
   - `output_spec["_texture_b64"] = design_result.texture_b64`
6. The route returns `texture_b64` to frontend
7. Frontend stores the texture and re-renders the geometry

### Why geometry must be updated

MCP-generated textures are atlas-based and usually require MCP-generated UVs.

If the app keeps the original LLM geometry but uses the MCP texture atlas, the texture does not line up correctly.

This was one of the major bugs fixed in the current pipeline.

---

## `designModel` Pipeline in Detail

### Entry point

`backend/llm/mcp_context.py::mcp_design_model()`

### What it does

`mcp_design_model()` is the bridge between Bedrock geometry and MCP `designModel`.

It:
1. creates a temp project directory
2. converts Bedrock geometry into MCP design format
3. calls MCP `designModel`
4. reads generated texture PNG from disk
5. reads generated geometry JSON from disk
6. returns both in a `DesignModelResult`

### Geometry conversion

Function:
- `_geometry_to_design(geometry, model_id, prompt)`

This converts Bedrock geometry into MCP's design schema.

It currently:
- preserves bone hierarchy
- preserves bone pivots and rotations
- preserves cube origin/size/inflate
- assigns generated per-face backgrounds for each cube face
- uses prompt-derived colors
- sets `pixelsPerUnit = 4`
- adds deterministic face seeds for consistent noise patterns
- uses lighter/darker colors depending on bone name patterns

### Current texture generation strategy

This is not generating a hand-authored Minecraft skin.

Instead, it generates a procedural texture atlas where each cube face gets a texture generated from MCP face background definitions.

Current face backgrounds are based on:
- `stipple_noise`
- color palette inferred from prompt keywords
- per-bone shade variation
- deterministic seeds

### Output of MCP `designModel`

MCP generates:
- a texture atlas PNG
- geometry JSON with per-face UV mapping
- a preview render image in the MCP response content

Important distinction:
- **texture atlas PNG** = correct file for the mob texture
- **preview render** = only a visual preview, not usable as texture

---

## Texture and Geometry File Extraction

### Previous bug

Originally, `mcp_design_model()` tried to read texture from a fixed path like:

- `project_dir/textures/entity/{model_id}.png`

But MCP actually writes into a nested resource pack folder under the temp project.

Because the expected path was wrong, the old fallback grabbed the wrong PNG — often the preview image — which caused the app to use a literal picture of the mob as a texture.

### Current behavior

Now the backend searches recursively for:
- `{model_id}.png` under a `textures` directory
- `{model_id}.geo.json` anywhere outside `.mct`

This prevents preview images from being mistaken for textures.

---

## Frontend Handling of Generated Texture

### `frontend/js/llm.js`

When `/api/spec/llm` returns `texture_b64`:

1. the texture is saved in local storage under the mob name
2. if the mob was renamed, the texture is migrated with it
3. the painter is refreshed
4. the 3D viewer is refreshed

### `frontend/js/painter.js`

The painter simply displays the texture atlas image.

That means if MCP generated an atlas, the painter shows the atlas layout directly, not a rendered mob preview.

This is expected behavior.

### `frontend/js/viewer3d.js`

The 3D viewer applies the texture to geometry.

It now supports both:
- classic Bedrock box UV: `"uv": [x, y]`
- MCP per-face UV: `"uv": {"north": {"uv": [...], "uv_size": [...]}, ...}`

This was another major fix.

Without per-face UV support, MCP-generated geometry would render with broken or stretched textures.

---

## 3D UV Mapping Support

### Box UV

Used by many LLM-generated or vanilla-style geometries.

Format:

```json
"uv": [0, 0]
```

Handled by:
- `applyBoxUV()` in `frontend/js/viewer3d.js`

### Per-face UV

Used by MCP-generated geometry.

Format:

```json
"uv": {
  "north": {"uv": [0, 0], "uv_size": [16, 16]},
  "south": {"uv": [16, 0], "uv_size": [16, 16]}
}
```

Handled by:
- `applyPerFaceUV()` in `frontend/js/viewer3d.js`

This support is required for MCP-generated geometry to render correctly.

---

## Build / Export Pipeline

### Build entry point

`backend/core/builders.py::patch_resource_pack()`

### Behavior

For each spec:

1. if `geometry_json` exists, it is written to:
   - `models/entity/{short_name}.geo.json`
2. if a texture PNG exists in the client-provided temp texture dir, it is copied into:
   - `textures/entity/{short_name}/{short_name}.png`
3. otherwise it falls back to a saved PNG in `SPECS_DIR`
4. otherwise it creates a solid-color placeholder texture
5. the client entity JSON is written referencing:
   - geometry identifier
   - texture path
   - render controller

### Important compatibility note

Minecraft Bedrock can consume the geometry with per-face UV mapping written by MCP, so the final build path is compatible with the MCP-generated atlas flow.

---

## Current Limitations

### 1. Texture quality is procedural, not artist-authored

The current MCP texture generation does not create a polished vanilla-style skin.

It creates a procedural atlas driven by:
- prompt colors
- noise patterns
- cube face packing

So the output is valid and mapped correctly, but not necessarily aesthetically ideal.

### 2. Texture coverage quality depends on geometry and design conversion

If the generated design is simplistic, the resulting texture atlas may feel sparse or repetitive.

This is especially visible on large mobs like elephants or rhinos.

### 3. MCP validation is effectively disabled for internal spec format

The app's internal entity spec format does not match the format expected by MCP `validateContent`, so MCP validation is not authoritative for the spec editing pipeline right now.

### 4. LLM and MCP geometry styles differ

The LLM tends to produce classic Bedrock geometry with box UV assumptions.
MCP produces atlas-packed per-face UV geometry.

The system currently resolves this by using MCP geometry whenever MCP texture generation succeeds.

---

## Recent Critical Fixes

### Fix 1: Prevent preview image from being used as texture

Problem:
- wrong texture path lookup
- fallback grabbed arbitrary PNG
- preview render got used as actual texture

Fix:
- recursive filename search for the real texture under `textures/`
- no unsafe PNG fallback

### Fix 2: Support per-face UV in 3D viewer

Problem:
- frontend only supported box UV
- MCP geometry rendered incorrectly

Fix:
- added `applyPerFaceUV()`
- detect object-vs-array UV format

### Fix 3: Keep geometry and texture in sync in `llm_rewrite_spec()`

Problem:
- MCP texture was returned
- original LLM geometry stayed unchanged
- geometry UVs and texture atlas did not match

Fix:
- when MCP succeeds, replace `geometry_json` with MCP-generated geometry

### Fix 4: Improve procedural texture quality

Changes:
- `pixelsPerUnit = 4`
- per-bone shade variation
- deterministic seeds
- skip empty bones

---

## End-to-End Example

### Example: user changes mob to “rhino”

1. User sends prompt in `/api/spec/llm`
2. `llm_rewrite_spec()` retrieves MCP template context
3. LLM rewrites the spec to become a rhino-like mob
4. Backend sees mob identity changed
5. Backend calls `mcp_design_model_sync()` with current geometry and prompt
6. `_geometry_to_design()` creates an MCP design
7. MCP `designModel` generates:
   - texture atlas PNG
   - per-face UV geometry
   - preview image
8. Backend extracts only the real texture atlas and geometry
9. Backend sets:
   - `spec.geometry_json = mcp geometry`
   - response `texture_b64 = atlas png`
10. Frontend saves `texture_b64`
11. Frontend painter shows the atlas image
12. Frontend 3D viewer applies the atlas to geometry using per-face UV
13. Build pipeline exports both into the final addon

---

## Recommended Next Improvements

### Short-term

- add better texture style generation than pure stipple noise
- make `_pick_colors_from_prompt()` richer and more species-aware
- add face-specific patterns for eyes, underside, horn/tusk, etc.

### Medium-term

- add optional MCP template-first design generation instead of pure geometry-to-noise conversion
- generate more structured pixel-art-like patterns instead of noise-only backgrounds
- add debugging endpoint to inspect generated MCP geometry and atlas metadata

### Long-term

- support a higher-level texture design language for animals
- create reusable texture presets per creature type
- convert internal spec format into real Bedrock JSON before MCP validation so validation can be re-enabled properly

---

## Quick Reference

### MCP texture pipeline

```text
geometry_json
  → _geometry_to_design()
  → MCP designModel
  → atlas PNG + per-face UV geometry
  → backend extracts both
  → frontend stores texture
  → viewer3d applies UV mapping
  → builders.py exports files
```

### Most important rules

- Never use MCP preview images as textures
- Geometry and texture must come from the same MCP result
- MCP-generated geometry uses per-face UVs
- Painter shows the atlas image directly
- Viewer3D must interpret UVs correctly for texture coverage to work

---

## File Map

- `backend/mctools/client.py`
- `backend/mctools/routes.py`
- `backend/llm/mcp_context.py`
- `backend/llm/llm.py`
- `backend/core/routes.py`
- `backend/core/builders.py`
- `frontend/js/llm.js`
- `frontend/js/viewer3d.js`
- `frontend/js/painter.js`
- `frontend/js/mctools.js`
- `docs/MCP_INTEGRATION.md`
- `docs/MCP_LLM_INTEGRATION_SESSION.md`
