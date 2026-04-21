# Textures, Geometry, Web Preview, and In-Game Mobs

This document explains **how textures are produced**, **how animations are driven** in the app versus in Minecraft, and **how the “geometry editor” / 3D preview relates** to what ends up in a built pack and in-game.

For the full **Bedrock animation generation, controllers, Molang, and packaging** story, see [ANIMATION_PIPELINE.md](./ANIMATION_PIPELINE.md).

---

## Table of contents

1. [How textures are created](#how-textures-are-created)
2. [How animations work (overview)](#how-animations-work-overview)
3. [Web preview vs in-game](#web-preview-vs-in-game)
4. [Key files (quick reference)](#key-files-quick-reference)

---

## How textures are created

### Decision order (backend)

When the LLM produces or updates an **entity** spec (`entity_logic_ai`), the server tries to attach a PNG in this order:

1. **Procedural, geometry-aware texture (default)**  
   - **Module:** `backend/llm/texture_gen.py` → `generate_mob_texture()`  
   - **Input:** `geometry_json` after `prepare_geometry_for_texture()` (see below).  
   - **Also uses:** `display_name`, `color_rgb`, `texture_hint`, `texture_instructions`, `short_name`.

2. **MCP `designModel` fallback**  
   - If procedural generation fails or returns empty, `backend/llm/llm.py` can call `mcp_design_model_sync()` to obtain texture (and optionally revised geometry) from Minecraft Creator Tools.

**Important:** Before texturing, the spec’s geometry is passed through `prepare_geometry_for_texture()` (`backend/build/builders.py`), which applies:

- `_fix_geometry_scale` — scales up unrealistically tiny cubes so Bedrock box-UV math matches visible models.
- `_fix_geometry_uv` — grows `texture_width` / `texture_height` when cube UVs would overflow the declared atlas.

That way the **same UV layout** the procedural painter assumes is the one Minecraft will use after build.

### What the procedural generator actually does

The procedural path does **not** ask an image model for a full skin. It **paints the texture atlas in pixel space** using the geometry’s UV layout:

1. Fill the atlas with a noisy base color (from `color_rgb` or a guess from `display_name` / `texture_hint`).
2. Walk every bone → cube → face, compute each face’s UV rectangle (Bedrock **box UV** uses cardinal names in code: `north`, `south`, `east`, `west`, `up`, `down`; `north` is −Z when the model follows project conventions).
3. Shade each region by **bone role** (head, body, leg, wing, tail, etc.) via `backend/llm/texture_gen.py` (`_classify_bone`, palette, per-face shading).
4. Apply optional **patterns** (spots, stripes, …) from detected style / `texture_instructions`.
5. Paint **eyes and simple facial features** on the **largest `north` face** among cubes on **head** bones only, **clipped to that face’s UV rectangle** so features do not bleed into adjacent islands (e.g. the head’s bottom face).

Output is a **PNG as a base64 data URL**, returned on the API as `texture_b64` and stored in the web app per mob (see below).

### Frontend storage (preview / painter)

- **Where the browser keeps the skin:** `frontend/js/core/user.js` — `saveUserMobTexture` / `getUserMobTexture` (per user, per mob `short_name`, in `localStorage`).
- **2D painter:** `frontend/js/viewer/painter.js` — edits the same logical texture; exports at the size implied by `geometry_json` description (`texture_width` × `texture_height`).
- **When the LLM returns a new texture:** `frontend/js/build/llm.js` saves it with `saveUserMobTexture(currentMobName, payload.texture_b64)`.

---

## How animations work (overview)

### In Minecraft (authoritative)

Bedrock uses:

- **`animation_json`** — clip definitions (bone keyframes over time).
- **`animation_controller_json`** — states, transitions, and **Molang** conditions (idle vs walk vs attack vs fly, etc.).
- **Entity client definition** — links geometry, texture, materials, `animations`, and `scripts` so the runtime loads the right clips.

Generation, sanitization, fly auto-animations, and build-time fixes are documented in **[ANIMATION_PIPELINE.md](./ANIMATION_PIPELINE.md)** (`backend/llm/animation_generation.py`, `animation_controllers_generation.py`, `builders.py`, MCP `build_mcworld.py`, etc.).

### In the web app (preview only)

The **3D Model Preview** does **not** run Minecraft’s engine. It uses **Three.js** (`frontend/js/viewer/viewer3d.js`):

1. **Geometry** — `render3DGeometry()` parses `minecraft:geometry`, builds box meshes, applies **Bedrock-style UVs** (`applyBoxUV` / `applyPerFaceUV`) and Blockbench-like **X inversion** on positions.
2. **Texture** — loads the mob’s saved PNG (data URL) via `THREE.TextureLoader` after `getUserMobTexture(mobName)`, then builds meshes so sampling matches the atlas.
3. **Animation playback** — `loadAnimation()` reads `animation_json` clips from the current mob spec, parses keyframes with `parseKeyframes()` (including fixes for common LLM shapes such as an array of `{"0.0": [...]}` objects), and each frame calls `applyAnimationFrame()`:
   - Resolves bone names with `resolveViewerBone()` (case / spacing tolerant).
   - Applies rotation / position / scale to the matching **THREE bone groups** (degrees → radians, with the same sign conventions used when the rig was built).

The **timeline UI** clip dropdown lists only animations present in `spec.animation_json.animations`. Changing the dropdown reloads that clip into the viewer. This is a **best-effort preview**; if bone names in JSON do not match geometry bone names, clips may look static until names align.

---

## Web preview vs in-game

| Aspect | Web app (builder) | Minecraft (built pack / .mcworld) |
|--------|-------------------|-------------------------------------|
| **Geometry source** | `spec.geometry_json` in memory + `localStorage`; optional fetch of vanilla geo for templates | `models/entity/<mob>.geo.json` in the **resource pack** (written at build from the same spec after extra fixes). |
| **Geometry fixes** | LLM path uses `prepare_geometry_for_texture()` before texturing. Full build also runs `_fix_geometry_legs` etc. (`builders.py`). | Pack on disk includes **post-fix** geometry; must match the texture atlas size and UVs. |
| **Texture source** | `localStorage` texture + painter canvas; LLM returns `texture_b64` on save. | `textures/entity/<short_name>.png` produced when the pack is built (procedural regen from written `.geo.json` if no PNG supplied). |
| **“Geometry editor” JSON panel** | Shows **raw `geometry_json`** (cubes, pivots, UVs). It does **not** embed PNG pixels — eyes are **texture**, not extra cubes. | Same JSON conceptually; game reads from pack files. |
| **Animations** | Three.js preview + simplified keyframe parsing. | Real Bedrock runtime + animation controllers + Molang. |
| **Materials / render controllers** | Lambert + alphatest-style defaults in Three.js. | Whatever the entity JSON and render controllers specify. |

**Practical takeaway:** If the **preview** and **game** disagree, check (1) **atlas size** in geometry `description` vs actual PNG dimensions, (2) **UV** coordinates vs box layout, (3) whether the **browser** has an **old** `localStorage` texture after geometry changed, and (4) **rebuild** the pack so the world uses the same assets as the latest spec.

---

## Key files (quick reference)

| Concern | Location |
|--------|----------|
| Procedural texture algorithm | `backend/llm/texture_gen.py` |
| Texture orchestration (LLM step) | `backend/llm/llm.py` |
| Geometry scale/UV prep before texture | `backend/build/builders.py` → `prepare_geometry_for_texture`, `_fix_geometry_uv`, `_fix_geometry_scale` |
| Pack build + geo on disk | `backend/build/builders.py` |
| Structured prompt hints (e.g. Clifford / quadruped) | `backend/llm/prompt_intents.py` |
| 3D preview + UV + animation playback | `frontend/js/viewer/viewer3d.js` |
| 2D texture painter | `frontend/js/viewer/painter.js` |
| Per-user mob + texture storage | `frontend/js/core/user.js` |
| LLM response → spec + texture in browser | `frontend/js/build/llm.js` |
| Full animation/controller pipeline | [ANIMATION_PIPELINE.md](./ANIMATION_PIPELINE.md) |

---

## Related docs

- [ANIMATION_PIPELINE.md](./ANIMATION_PIPELINE.md) — animation generation, controllers, Molang, fly behavior, build sync with MCP.
- [MCWORLD_AUTO_SPAWN.md](./features/MCWORLD_AUTO_SPAWN.md) — how test worlds embed packs and spawn mobs.
