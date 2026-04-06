# Bedrock Addon Builder — Complete Codebase Guide

> **Audience:** New team members joining the project.
> **Last updated:** March 2026 (post-refactor).

This document is the single source of truth for how the entire application works — from the moment a user types a prompt to the final `.mcworld` file that opens in Minecraft Bedrock Edition. It covers the architecture, every pipeline stage, the LLM context system, the build system, the MCP integration, and every hard-won fix for Bedrock's many quirks.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Project Structure](#2-project-structure)
3. [Getting Started](#3-getting-started)
4. [The Mob Spec — Our Core Data Model](#4-the-mob-spec--our-core-data-model)
5. [End-to-End Pipeline Overview](#5-end-to-end-pipeline-overview)
6. [LLM Pipeline (Prompt → Spec)](#6-llm-pipeline-prompt--spec)
7. [Context Injection — How the LLM Gets Smart](#7-context-injection--how-the-llm-gets-smart)
8. [Geometry Preservation on Iterative Edits](#8-geometry-preservation-on-iterative-edits)
9. [Texture Generation Pipeline](#9-texture-generation-pipeline)
10. [Build Pipeline (Spec → Addon)](#10-build-pipeline-spec--addon)
11. [Resource Pack Patching](#11-resource-pack-patching)
12. [Behavior Pack Patching](#12-behavior-pack-patching)
13. [Post-Merge Fixups (Critical)](#13-post-merge-fixups-critical)
14. [Loot Table Pipeline](#14-loot-table-pipeline)
15. [MCP World Builder (.mcworld)](#15-mcp-world-builder-mcworld)
16. [Auto-Spawn Mechanism](#16-auto-spawn-mechanism)
17. [MCP Integration (Minecraft Creator Tools)](#17-mcp-integration-minecraft-creator-tools)
18. [Database & RAG (Mob Templates)](#18-database--rag-mob-templates)
19. [Frontend Architecture](#19-frontend-architecture)
20. [Challenges & Hard-Won Fixes](#20-challenges--hard-won-fixes)
21. [Environment Variables](#21-environment-variables)
22. [File Map (Quick Reference)](#22-file-map-quick-reference)

---

## 1. Project Overview

**Bedrock Addon Builder** is a web app that lets users create custom Minecraft Bedrock Edition mobs using natural language prompts. Users type something like *"fire breathing dragon that drops diamonds on death"* and the app:

1. Sends the prompt to an LLM (GPT-4.1 via GitHub Models, DeepSeek, Gemini, Claude, or Ollama)
2. The LLM generates a structured mob specification (JSON)
3. The app builds a complete Minecraft addon from that spec
4. The user downloads a `.mcworld` file that opens directly in Minecraft

The app supports iterative editing — users can keep prompting to refine their mob's behavior, appearance, and abilities without losing previous work.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Vanilla HTML/CSS/JS, Three.js (3D preview) |
| **Backend** | Python, FastAPI, Uvicorn |
| **LLM** | OpenAI (via GitHub Models), DeepSeek, Gemini, Claude, Ollama |
| **Database** | PostgreSQL (Neon) for mob templates/RAG |
| **MCP** | Minecraft Creator Tools (Node.js, optional) |
| **Output** | Minecraft Bedrock `.mcworld`, `.mcaddon`, `.mcpack` |

---

## 2. Project Structure

```
Bedrock-Addon-Builder/
├── run.py                          # Entry point — starts FastAPI server on :7860
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Container deployment (HuggingFace Spaces)
├── .env                            # Environment variables (API keys, DB URL)
├── .env.example                    # Template for .env
├── CLAUDE.md                       # AI assistant context file
├── README.md                       # Project README
│
├── backend/                        # Python backend
│   ├── __init__.py
│   ├── api/                        # FastAPI app + all route handlers
│   │   ├── app.py                  #   App creation, middleware, route registration
│   │   └── routes.py               #   All API endpoints (63KB, ~1500 lines)
│   ├── build/                      # Addon building + packaging
│   │   ├── builders.py             #   Resource/behavior pack generation
│   │   └── packaging.py            #   .mcworld/.mcaddon assembly, MCP delegation
│   ├── config/                     # Constants, defaults, LLM system prompt
│   │   └── settings.py             #   DEFAULTS, paths, LLM config, LLM_SYSTEM_PROMPT
│   ├── database/                   # PostgreSQL (Neon) connection
│   │   ├── __init__.py             #   Lazy-loaded exports
│   │   └── db.py                   #   Connection pool, fetch_all/fetch_one/execute_query
│   ├── llm/                        # LLM integration + texture generation
│   │   ├── llm.py                  #   Main LLM pipeline: llm_rewrite_spec()
│   │   ├── texture_gen.py          #   Procedural UV-aware texture generator
│   │   ├── category_context.py     #   Static per-category context (entity/item/block rules)
│   │   ├── dynamic_context.py      #   Prompt-analyzed dynamic context injection
│   │   ├── mcp_context.py          #   MCP context retrieval (templates, schemas, designModel)
│   │   ├── llm_logger.py           #   JSON logging of all LLM calls
│   │   └── llm_scoring.py          #   Semantic consistency scoring
│   ├── mctools/                    # Minecraft Creator Tools integration
│   │   ├── client.py               #   MCP client over Streamable HTTP, subprocess mgmt
│   │   └── routes.py               #   FastAPI routes for mctools UI features
│   ├── mob_management/             # Database CRUD for mob templates
│   │   ├── __init__.py             #   Lazy-loaded exports (find_similar_mobs, etc.)
│   │   ├── retriever.py            #   Read operations (similarity search, get by name)
│   │   ├── updater.py              #   Update operations
│   │   └── deleter.py              #   Delete operations
│   ├── schemas/                    # Mob spec schema + validation
│   │   ├── mob_spec.schema.json    #   JSON Schema defining valid spec fields
│   │   ├── schemas_loader.py       #   Schema loading
│   │   └── spec_utils.py           #   validate_spec(), read/write mob specs, defaults
│   └── data/                       # Reference data
│       ├── vanilla_mobs.json       #   Vanilla mob examples (for dynamic context)
│       └── vanilla_reference.json  #   Vanilla component reference data
│
├── frontend/                       # Browser UI
│   ├── index.html                  #   Single-page app HTML
│   ├── styles.css                  #   All CSS styling
│   └── js/                         #   JavaScript modules (loaded via <script> tags)
│       ├── core/                   #   App initialization + user session
│       │   ├── app.js              #     Main init, tab switching, event wiring
│       │   └── user.js             #     User authentication, session management
│       ├── editor/                 #   Spec editing
│       │   ├── editor.js           #     JSON spec editor, mob list, save/load
│       │   └── form-editor.js      #     Visual form-based spec editing
│       ├── viewer/                 #   3D preview + texture painting
│       │   ├── viewer3d.js         #     Three.js 3D mob preview (48KB)
│       │   └── painter.js          #     Canvas-based texture painter
│       ├── build/                  #   Building + LLM interaction
│       │   ├── builder.js          #     Build trigger, download, Play World
│       │   ├── llm.js              #     LLM prompt UI, provider selection
│       │   └── mctools.js          #     MCP tools UI integration
│       └── ui/                     #   Modals + shared UI
│           └── modals.js           #     Template picker, mob creation modals
│
├── MCP/                            # Minecraft Creator Tools (separate module)
│   └── mcp_server/
│       └── tools/
│           ├── build_mcworld.py    #   Authoritative .mcworld builder
│           └── bedrock_reference.py#   Manifest generators, client entity builders
│
├── McpGettingStarted/              # MCP tutorial/reference (DO NOT MODIFY)
│
├── data/                           # Runtime data
│   ├── specs/                      #   Saved mob specs (JSON) + textures (PNG)
│   ├── templates/                  #   base_world.mcworld, vanilla_mobs.json
│   ├── database_insertion/         #   Scripts to populate the Neon DB
│   │   └── publish_mob.py          #     Publish user mobs to database
│   └── test_cases.json             #   Golden test cases for LLM evaluation
│
├── tests/                          #   All test files
│   ├── backend/                    #     Backend tests (golden tests, MCP context tests)
│   └── integration/                #     Integration tests (mcworld inspection, DB, bakeoff)
│
├── scripts/                        # Developer tools
│   ├── evaluate_llm.py             #   LLM quality evaluation framework
│   ├── launch_server_session.py    #   One-Click Play (BDS integration)
│   ├── launch_preview.py           #   Preview launcher
│   └── clean_llm_logs.py           #   Log cleanup utility
│
└── docs/                           # Documentation
    ├── CODEBASE_GUIDE.md           #   THIS FILE — the master guide
    ├── architecture/               #   Pipeline, MCP integration, MCP master pipeline
    ├── features/                   #   One-Click Play, auto-spawn, geometry
    ├── llm/                        #   LLM scoring, dynamic context, evaluation
    └── development/                #   Implementation checklists, session notes
```

---

## 3. Getting Started

### Prerequisites
- Python 3.11+
- A GitHub Personal Access Token with `models:read` scope (for GitHub Models / OpenAI)
- PostgreSQL database URL (Neon) for mob templates (optional)

### Setup
```bash
# Clone the repo
git clone <repo-url>
cd Bedrock-Addon-Builder

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env: set GITHUB_TOKEN, DATABASE_URL, etc.

# Start the server
python run.py
# Server runs at http://127.0.0.1:7860
```

### Key URLs
| URL | Purpose |
|-----|---------|
| `http://127.0.0.1:7860` | Main web UI |
| `http://127.0.0.1:7860/healthz` | Health check |
| `http://127.0.0.1:7860/api/mobs` | List all saved mobs |

---

## 4. The Mob Spec — Our Core Data Model

Every mob is represented by a **Mob Spec** — a JSON object that flows through the entire pipeline. The spec is the single source of truth for what a mob looks like, how it behaves, and what it drops.

### Schema (defined in `backend/schemas/mob_spec.schema.json`)

| Field | Type | Description |
|-------|------|-------------|
| `identifier` | string | Bedrock entity ID, e.g. `"custom:fire_dragon"` |
| `display_name` | string | Human-readable name, e.g. `"Fire Dragon"` |
| `short_name` | string | Safe filename slug, e.g. `"fire_dragon"` |
| `engine_min` | array | Min engine version `[1, 21, 110]` |
| `hp` | integer | Health points |
| `damage` | integer | Attack damage |
| `speed` | number | Movement speed (0.0–1.0) |
| `collision_box` | object | `{width, height}` hitbox dimensions |
| `geometry` | string | Geometry reference ID, e.g. `"geometry.custom_fire_dragon"` |
| `geometry_json` | object | Full Bedrock geometry JSON (empty `{}` for vanilla mobs) |
| `render_controller` | string | Always `"controller.render.default"` |
| `texture_hint` | string | Color/style hint for texture generation |
| `texture_instructions` | array | Detailed texture style descriptors |
| `color_rgb` | array | Base color `[R, G, B]` for texture generation |
| `egg_base` | string | Spawn egg primary color (hex) |
| `egg_overlay` | string | Spawn egg secondary color (hex) |
| `scale` | number | Entity visual scale multiplier |
| `components` | object | Minecraft behavior components (AI goals, attacks, etc.) |
| `loot_drops` | array | Items dropped on death (see Loot Table Pipeline) |

### Internal (transient) fields
These are attached to the spec during processing but NOT persisted:

| Field | Purpose |
|-------|---------|
| `_mcp_meta` | MCP context metadata (sources, timing, validation results) |
| `_texture_b64` | Generated texture as base64 data URL |
| `_template_base` | Vanilla mob this spec is based on (for texture fetching) |

### Validation
`backend/schemas/spec_utils.py` → `validate_spec()` performs manual validation:
- Enforces correct types, patterns (`identifier` must match `namespace:name`)
- Merges missing fields from `DEFAULTS` (defined in `backend/config/settings.py`)
- Does NOT use strict JSON Schema validation — it's a forgiving merge-and-fix approach

---

## 5. End-to-End Pipeline Overview

```
User types: "fire breathing dragon that drops diamonds"
    │
    ▼
┌─────────────────────────────────────────────────┐
│  Frontend (js/build/llm.js)                     │
│  POST /api/spec/llm                             │
│  Body: {prompt, current_spec, provider, api_key}│
└──────────────────────┬──────────────────────────┘
                       │
            ┌──────────┴──────────┐
            ▼                     ▼
┌─────────────────┐   ┌────────────────────────┐
│ MCP Context     │   │ Dynamic Context        │
│ (optional)      │   │ (always active)        │
│ - Templates     │   │ - Prompt intent scan   │
│ - Schemas       │   │ - Behavior docs        │
│ via mctools     │   │ - Vanilla examples     │
└────────┬────────┘   └───────────┬────────────┘
         │                        │
         └────────┬───────────────┘
                  ▼
┌─────────────────────────────────────────────────┐
│  LLM Call (OpenAI via GitHub Models)            │
│  System prompt = base rules                     │
│                + MCP schema/templates           │
│                + category context               │
│                + mob spec JSON schema           │
│                + dynamic context (last=recency) │
│                                                 │
│  User message = current spec + user instruction │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│  Post-LLM Processing                            │
│  1. _sanitize_geometry_json (fix placeholder)   │
│  2. validate_spec (merge defaults)              │
│  3. _preserve_geometry (restore custom geo)     │
│  4. Procedural texture generation               │
│  5. Attach _mcp_meta + _texture_b64             │
└──────────────────────┬──────────────────────────┘
                       │
              User clicks "Build"
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│  Build Pipeline (backend/build/)                │
│  1. patch_resource_pack (client rendering)      │
│  2. patch_behavior_pack (server AI + loot)      │
│  3. Post-merge fixups (ranged/fly conflicts)    │
│  4. Auto-wire loot tables                       │
│  5. Cross-link BP ↔ RP manifests                │
│  6. create_mcworld (→ MCP builder)              │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│  MCP World Builder (build_mcworld.py)           │
│  Assembles final .mcworld ZIP:                  │
│  - level.dat (NBT, creative flat world)         │
│  - Embedded BP + RP with pack linking           │
│  - Loot tables from metadata.loot_drops         │
│  - Auto-spawn mcfunction                        │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
                 .mcworld file
              (opens in Minecraft)
```

---

## 6. LLM Pipeline (Prompt → Spec)

**File:** `backend/llm/llm.py` → `llm_rewrite_spec()`

This is the heart of the application. It takes a user's natural language prompt and the current mob spec, then returns an updated spec.

### Step-by-step:

#### Step 1 — Category Detection
```python
detected_category = detect_category(current)
```
Auto-detects whether the spec is an entity, item, or block. If the user selected a different category, a conversion prompt is prepended.

#### Step 2 — MCP Context Retrieval (optional, non-blocking)
```python
mcp_ctx = retrieve_context_sync(prompt, category, current)
```
Fetches geometry templates from Minecraft Creator Tools if available. Uses a **circuit breaker** that disables MCP after 2 consecutive failures for 5 minutes. If mctools is down, generation continues with static context only.

#### Step 3 — Dynamic Context Analysis (always active)
```python
dyn_ctx = build_dynamic_context(prompt, category)
```
Scans the prompt for behavioral keywords and injects targeted Bedrock documentation. See [Context Injection](#7-context-injection--how-the-llm-gets-smart) for details.

#### Step 4 — LLM Call
Routes to the configured provider (`_call_openai`, `_call_deepseek`, `_call_gemini`, `_call_claude`, `_call_ollama`). Each provider:
1. Builds the system prompt via `_get_full_system_prompt()`
2. Serializes the current spec via `_prepare_spec_for_llm()` (strips bulky fields like `geometry_json`)
3. Sends to the LLM with `response_format={"type": "json_object"}` (OpenAI)
4. Parses the JSON response
5. Calls `_sanitize_geometry_json()` to handle placeholder strings
6. Validates via `validate_spec()`

**OpenAI specifics:** Uses GitHub Models API (`https://models.github.ai/inference`) authenticated with `GITHUB_TOKEN`. Default model: `openai/gpt-4.1`.

#### Step 5 — Geometry Preservation
```python
output_spec = _preserve_geometry(output_spec, current)
```
If the input had custom geometry and the LLM dropped it (which happens because we strip `geometry_json` for token budget), the original geometry is restored. See [Geometry Preservation](#8-geometry-preservation-on-iterative-edits).

#### Step 6 — Texture Generation
Two attempts, in priority order:
1. **MCP designModel** — calls mctools to generate a texture from geometry + color hints
2. **Procedural generator** — `backend/llm/texture_gen.py` creates a UV-aware texture using body-part coloring, shading, patterns, and eyes

#### Step 7 — Metadata Attachment
The output spec gets `_mcp_meta` (context sources, timing, validation) and `_texture_b64` (generated texture) attached before returning to the frontend.

---

## 7. Context Injection — How the LLM Gets Smart

The LLM's system prompt is assembled in **6 layers**, ordered strategically for attention:

### Layer 1 — Base System Prompt (always)
**Source:** `backend/config/settings.py` → `LLM_SYSTEM_PROMPT`

Contains:
- Field overview (behavior, geometry, visuals)
- Geometry rules (when to use vanilla vs. custom)
- Loot drop format (`loot_drops` array with `item`, `count_min`, `count_max`, `chance`)
- 8 critical rules (JSON format, required keys, bone naming, geometry preservation, etc.)

### Layer 2 — MCP Authoritative Schema (optional)
**Source:** `backend/llm/mcp_context.py` → `_fetch_schema()`

Currently **inactive** — MCP's `getEffectiveContentSchema` requires a populated Minecraft project folder. When active, provides ground-truth Bedrock schema.

### Layer 3 — Category-Specific Context (always)
**Source:** `backend/llm/category_context.py` → `CATEGORY_CONTEXT`

Static context per category. For `entity_logic_ai`, includes:
- Complete entity JSON structure examples
- Component combination rules (e.g., "ranged attacks need `minecraft:shooter` + `behavior.ranged_attack`")
- Vanilla component reference from `backend/data/vanilla_reference.json`

### Layer 4 — MCP Model Templates (optional)
**Source:** `backend/llm/mcp_context.py` → `_fetch_templates()`

Fetches geometry templates from mctools `getModelTemplates`. Maps prompt keywords to template types:
- "dragon" / "fly" → `flying`
- "zombie" / "skeleton" → `humanoid`
- "pig" / "sheep" → `small_animal`
- "spider" / "bee" → `insect`
- 30+ template type mappings

### Layer 5 — JSON Schema (always for entities)
**Source:** `backend/schemas/mob_spec.schema.json`

The complete mob spec schema so the LLM knows exact field types and constraints.

### Layer 6 — Dynamic Context (always, placed LAST for recency effect)
**Source:** `backend/llm/dynamic_context.py` → `build_dynamic_context()`

This is the most sophisticated context layer. It:
1. Scans the user's prompt for behavioral intent keywords
2. Detects intents like `ranged_attack`, `flying`, `exploding`, `passive`, `boss`, etc.
3. For each intent, injects relevant Bedrock component documentation
4. Pulls matching vanilla mob examples from `backend/data/vanilla_mobs.json`
5. Caps total injection at 6000 chars (~1500 tokens)

**Supported intents:**

| Intent | Example Triggers | What Gets Injected |
|--------|-----------------|-------------------|
| `ranged_attack` | "fire breath", "shoot", "fireball" | `minecraft:shooter` + `ranged_attack` docs, valid projectile types |
| `flying` | "fly", "dragon", "wings" | `movement.fly` + `navigation.fly` docs, conflict warnings |
| `exploding` | "explode", "creeper-like" | `behavior.swell` + `explode` docs |
| `passive` | "friendly", "pet", "farm" | `behavior.panic` + `tempt` docs |
| `tameable` | "tame", "ride", "mount" | `tameable` + `rideable` docs |
| `aquatic` | "swim", "shark", "ocean" | `navigation.swim` + `breathable` docs |
| `boss` | "boss", "titan", "legendary" | High HP guidelines, knockback resistance |
| `teleport` | "teleport", "enderman" | `teleport` component docs |
| `breeding` | "breed", "baby" | `breedable` + `behavior.breed` docs |

**Key design:** Multiple intents fire simultaneously — "flying fire-breathing boss dragon" gets ranged + flying + boss context all at once.

### Prompt Budget
Total system prompt is capped at **25,000 characters** (~6K tokens). If exceeded, it's truncated with a warning.

---

## 8. Geometry Preservation on Iterative Edits

**Problem:** When a user prompts "make it drop diamonds" on a dragon with custom geometry, the LLM was replacing the dragon geometry with a chicken model because:
1. `_prepare_spec_for_llm()` strips `geometry_json` to save tokens
2. Without seeing the full geometry, the LLM defaults to a vanilla model
3. The user's custom dragon body was lost

**Solution (3 mechanisms working together):**

### 1. Geometry Summary in LLM Input
`_prepare_spec_for_llm()` replaces `geometry_json` with a text summary:
```
(CUSTOM GEOMETRY PRESENT — DO NOT REPLACE)
id=geometry.custom_fire_dragon, atlas=64x64,
bones=[root(0 cubes), body(1 cubes), head(2 cubes), leg0(1 cubes), ...]
```
This tells the LLM the custom geometry exists without sending the full JSON.

### 2. System Prompt Rule
Rule 8 in `LLM_SYSTEM_PROMPT`:
> "If the current spec has geometry_json marked as '(CUSTOM GEOMETRY PRESENT — DO NOT REPLACE)', keep geometry and geometry_json EXACTLY as they are. Only change geometry if the user explicitly asks to change the mob's shape/model/body."

### 3. Post-LLM Restoration
`_preserve_geometry()` runs after every LLM call:
- If input had custom geometry AND output has empty/placeholder geometry → restore from input
- If LLM changed the geometry reference ID from `geometry.custom_*` to a vanilla ID → restore original ID
- If LLM generated NEW custom geometry → keep it (user explicitly asked for shape change)

### 4. Sanitization Guard
`_sanitize_geometry_json()` runs before `validate_spec()` in every provider function:
- If LLM echoed back the placeholder string as `geometry_json`, replaces it with `{}`
- Prevents validation failure on string-type geometry_json

---

## 9. Texture Generation Pipeline

**File:** `backend/llm/texture_gen.py` → `generate_mob_texture()`

Generates textures procedurally by reading the actual geometry UV map. No external dependencies (pure Python PNG encoding).

### Pipeline:
1. **Fill atlas** with opaque base color (no transparent gaps)
2. **Walk geometry:** bone → cube → compute all 6 face UV rects
3. **Role-based coloring:** each bone gets a color based on its role:
   - Head → lighter, warm tones
   - Body → base color
   - Legs → darker shade
   - Tail/wings → accent color
4. **Per-face shading:** front faces are brighter, bottom faces are darker
5. **Pattern overlay:** spots, stripes, scales, patches on painted UV regions
6. **Eye painting:** detects the head bone's front face and paints eyes there
7. **Encode to PNG** → base64 data URL

### UV Mapping (Box UV format)
Bedrock uses **box UV** where a single `[u, v]` coordinate maps to a 6-face cross layout:
```
          [top]
[right] [front] [left] [back]
          [bottom]
```

The face layout for a cube with `size: [w, h, d]` starting at UV `[u, v]`:
- **Right:** `(u, v+d)` → size `d×h`
- **Front:** `(u+d, v+d)` → size `w×h`
- **Left:** `(u+d+w, v+d)` → size `d×h`
- **Back:** `(u+d+w+d, v+d)` → size `w×h`
- **Top:** `(u+d, v)` → size `w×d`
- **Bottom:** `(u+d+w, v)` → size `w×d`

**Important Bedrock quirk:** The "right" and "left" labels in Bedrock's UV layout are swapped compared to what you'd expect from the player's perspective. This was a source of misaligned textures until fixed.

---

## 10. Build Pipeline (Spec → Addon)

**File:** `backend/build/packaging.py` → `build_addon()`

Triggered by `POST /api/build`. Orchestrates the full build:

```python
def build_addon(specs, out_dir, res_src, beh_src, textures_dir=None):
    # 1. Create temp working directories
    res_root = work / "res"
    beh_root = work / "beh"

    # 2. Patch resource pack (client rendering)
    res_manifest = patch_resource_pack(res_root, specs, textures_dir)

    # 3. Patch behavior pack (server AI, loot tables, auto-spawn)
    beh_manifest = patch_behavior_pack(beh_root, specs)

    # 4. Cross-link manifests (BP ↔ RP UUID dependencies)
    #    Without this, Minecraft treats them as unrelated and mob is INVISIBLE

    # 5. Package outputs: .mcpack, .mcaddon, .mcworld, .zip bundle
```

### Output Artifacts

| Artifact | Description |
|----------|-------------|
| `{mob}_resources.mcpack` | Resource pack (client entities, textures, geometry) |
| `{mob}_behavior.mcpack` | Behavior pack (server entities, AI, loot tables, auto-spawn) |
| `{mob}.mcaddon` | Both packs combined (install into existing world) |
| `{mob}.mcworld` | Complete playable world with packs embedded |
| `{mob}_output_bundle.zip` | All of the above + specs.json + BUILD_LOG.txt |

---

## 11. Resource Pack Patching

**File:** `backend/build/builders.py` → `patch_resource_pack()`

### Client Entity (`entity/{mob}.entity.json`)
- Maps server entity identifier to client rendering
- References geometry, texture path, render controller
- Includes spawn egg definition with custom colors
- Scale applied via `"scripts": {"scale": "2.2"}`

### Geometry (`models/entity/{mob}.geo.json`)
- Writes geometry JSON from spec
- **UV overflow fix** (`_fix_geometry_uv()`): if any cube's UV + size exceeds the declared atlas, the atlas dimensions are expanded to the next power-of-two. This is critical because LLM-generated geometry frequently has cubes too large for the declared 64×64 atlas.
- **Vanilla geometry fetch** (`_fetch_vanilla_geometry()`): if the geometry ID references a vanilla model (e.g. `geometry.chicken`), the real geometry is downloaded from Mojang's Bedrock samples GitHub repo. Vanilla geometry IDs don't resolve in custom addon packs — you must ship the actual `.geo.json` file.

### Texture (`textures/entity/{mob}.png`)
Priority order:
1. Custom texture from painter or MCP designModel
2. Procedurally generated texture (UV-aware, see Texture Generation Pipeline)
3. Solid-color placeholder PNG matching atlas dimensions from `.geo.json`

### Language (`texts/en_US.lang`)
```
entity.custom:fire_dragon.name=Fire Dragon
item.spawn_egg.entity.custom:fire_dragon.name=Spawn Fire Dragon
```

### Manifest
- `min_engine_version: [1, 16, 0]` — maximum compatibility
- `format_version: 2`

---

## 12. Behavior Pack Patching

**File:** `backend/build/builders.py` → `patch_behavior_pack()`

### Base Entity Template
Every mob starts with a **hostile pursuit-oriented** base:
```json
{
  "format_version": "1.16.0",
  "minecraft:entity": {
    "description": { "identifier": "custom:fire_dragon", "is_spawnable": true, "is_summonable": true },
    "components": {
      "minecraft:health": { "value": 60, "max": 60 },
      "minecraft:attack": { "damage": 10 },
      "minecraft:movement.basic": {},
      "minecraft:navigation.walk": { "can_walk": true, "can_pass_doors": true },
      "minecraft:behavior.float": { "priority": 0 },
      "minecraft:behavior.hurt_by_target": { "priority": 1 },
      "minecraft:behavior.nearest_attackable_target": { "priority": 2 },
      "minecraft:behavior.melee_attack": { "priority": 3 },
      "minecraft:behavior.random_stroll": { "priority": 6 },
      "minecraft:behavior.look_at_player": { "priority": 8 },
      "minecraft:behavior.random_look_around": { "priority": 9 }
    }
  }
}
```

### LLM Component Merge
The LLM's `components` dict is merged on top:
```python
for k, v in spec["components"].items():
    if v is None:
        del entity["components"][k]  # null = delete component
    else:
        entity["components"][k] = v  # override or add
```

---

## 13. Post-Merge Fixups (Critical)

**File:** `backend/build/builders.py` (after component merge)

These automated fixups prevent silent failures in Minecraft. They were all discovered through painful trial-and-error.

### Ranged vs. Melee Conflict
If the entity has `minecraft:shooter` + `behavior.ranged_attack`, **remove** `behavior.melee_attack`. Without this fix, the mob always runs to melee range instead of shooting projectiles.

### Projectile Normalization
Replace `minecraft:fireball` (ghast) or `minecraft:dragon_fireball` with `minecraft:small_fireball` (blaze). The ghast fireball is unreliable for custom entities; the blaze fireball always works.

### Invalid Ranged Attack Params
LLMs hallucinate keys like `requires_target`, `burst_shot_delay` which don't exist in Bedrock. All invalid keys are stripped. Valid defaults are ensured:
- `attack_interval_min: 3.0`, `attack_interval_max: 5.0`, `attack_radius: 16.0`

### Movement Conflicts
- `minecraft:movement.fly` present → remove `minecraft:movement.basic`
- `minecraft:navigation.fly` present → remove `minecraft:navigation.walk`

Both walk and fly variants coexisting causes the mob to get stuck.

---

## 14. Loot Table Pipeline

**Problem history:** Mobs were dropping bones instead of user-specified items (e.g. diamonds). This was fixed across the entire pipeline.

### How it works end-to-end:

#### 1. LLM generates `loot_drops`
The system prompt instructs the LLM to output:
```json
{
  "loot_drops": [
    {"item": "minecraft:diamond", "count_min": 1, "count_max": 3, "chance": 1.0}
  ],
  "components": {
    "minecraft:loot": {"table": "loot_tables/entities/fire_dragon.json"}
  }
}
```

#### 2. Schema preserves it
`loot_drops` is defined in `mob_spec.schema.json` as an optional array, and in `DEFAULTS` as `[]`, so it survives validation and merging.

#### 3. Builder auto-wires `minecraft:loot`
In `patch_behavior_pack()`, if `loot_drops` exists but `minecraft:loot` component is missing, it's auto-added:
```python
if loot_drops and "minecraft:loot" not in comps:
    comps["minecraft:loot"] = {"table": f"loot_tables/entities/{mob_name}.json"}
```

#### 4. Builder creates loot table JSON
`_generate_loot_table()` converts the `loot_drops` array into Bedrock loot table format. Each drop becomes its own pool:
```json
{
  "pools": [
    {
      "rolls": 1,
      "entries": [{"type": "item", "name": "minecraft:diamond", "weight": 1, "functions": [{"function": "set_count", "count": {"min": 1, "max": 3}}]}]
    }
  ]
}
```

#### 5. MCP builder also creates loot table
In `packaging.py`, `loot_drops` is passed into `mcp_metadata["loot_drops"]`. The MCP's `build_mcworld.py` → `_build_loot_table()` reads this and creates the loot table file in the `.mcworld` ZIP.

**Key insight:** There are TWO build paths (mcpack via `builders.py` and mcworld via MCP `build_mcworld.py`). Both must receive `loot_drops` — a bug where only the mcpack path was fixed caused mobs to still drop bones in `.mcworld` files.

---

## 15. MCP World Builder (.mcworld)

**File:** `MCP/mcp_server/tools/build_mcworld.py`

This is the **authoritative** `.mcworld` builder. Called by `packaging.py` → `create_mcworld()`.

### Translation Layer
`create_mcworld()` translates app format to MCP input:
```python
mcp_mobs.append({
    "entity": entity_data,        # Full behavior JSON from beh_root (post-fixup)
    "metadata": {
        "display_name": "Fire Dragon",
        "suggested_style": "zombie",
        "suggested_colors": ["#225022", "#D82920"],
        "scale": 2.2,
        "loot_drops": [...]       # Passed through for loot table generation
    },
    "texture_base64": "iVBOR...",
    "geometry_data": { ... }      # UV-fixed geometry
})
```

**Critical:** `entity_data` is read from the already-patched behavior entity file (`beh_root/entities/{mob}.json`). This preserves all LLM components and post-merge fixups. It is NOT regenerated.

### .mcworld ZIP Structure
```
fire_dragon.mcworld (ZIP)
├── level.dat                              # Bedrock NBT (creative, flat, cheats on)
├── level.dat_old                          # Copy of level.dat
├── levelname.txt                          # World display name
├── world_behavior_packs.json              # Links BP by UUID
├── world_resource_packs.json              # Links RP by UUID
├── behavior_packs/{mob}_BP/
│   ├── manifest.json
│   ├── pack_icon.png
│   ├── entities/{mob}.json                # Full behavior entity
│   ├── loot_tables/entities/{mob}.json    # Loot table (from metadata.loot_drops)
│   └── functions/
│       ├── startup.mcfunction             # Auto-spawn commands
│       └── tick.json                      # Runs startup every tick
├── resource_packs/{mob}_RP/
│   ├── manifest.json
│   ├── pack_icon.png
│   ├── entity/{mob}.entity.json           # Client entity
│   ├── models/entity/{mob}.geo.json
│   ├── textures/entity/{mob}.png
│   └── texts/en_US.lang
└── db/                                    # Empty LevelDB (Minecraft regenerates)
```

### level.dat
Custom little-endian NBT writer. Key settings:
- `GameType: 1` (Creative), `Generator: 2` (Flat)
- `cheatsEnabled: 1`, `commandsEnabled: 1`, `commandblocksenabled: 1`
- `functioncommandlimit: 10000`

---

## 16. Auto-Spawn Mechanism

Both build paths (mcpack and mcworld) use the same player-tag-gated one-shot mechanism:

### tick.json
```json
{ "values": ["startup"] }
```

### startup.mcfunction
```
execute @a[tag=!mf_spawned] ~ ~ ~ summon custom:fire_dragon ~2 ~ ~2
execute @a[tag=!mf_spawned] ~ ~ ~ tellraw @a {"rawtext":[{"text":"§aAddon Builder: §fCustom mobs summoned near you!"}]}
tag @a add mf_spawned
```

### How it works:
1. Every tick, `startup` runs
2. `@a[tag=!mf_spawned]` matches any player without the tag
3. Mob is summoned, confirmation message shown
4. All players get `mf_spawned` tag
5. On subsequent ticks, selector matches nobody → effectively disabled

### Why OLD execute syntax
Uses `execute @a[tag=!mf_spawned] ~ ~ ~ summon ...` instead of the newer `execute as @a at @s run ...`. The new syntax requires `min_engine_version [1, 19, 70]` but we use `[1, 16, 0]` for maximum compatibility. The new syntax **silently fails** on older versions.

---

## 17. MCP Integration (Minecraft Creator Tools)

**Files:** `backend/llm/mcp_context.py`, `backend/mctools/client.py`, `backend/mctools/routes.py`

mctools is an **optional** local Node.js server (port 6126) that provides Bedrock-specific tooling.

### Active Features

| Feature | MCP Tool | What It Does |
|---------|----------|-------------|
| **Model Templates** | `getModelTemplates` | Returns geometry templates for mob types (humanoid, flying, etc.) |
| **Design Model** | `designModel` | Generates texture PNGs from geometry + color hints |

### Inactive Features (implemented but disabled)

| Feature | MCP Tool | Why Inactive |
|---------|----------|-------------|
| **Content Schema** | `getEffectiveContentSchema` | Needs a populated Minecraft project folder |
| **Validation** | `validateContent` | Our spec format differs from Bedrock entity JSON |

### Availability & Resilience
- **Optional**: if `MCTOOLS_ENABLED=false` or server is down, generation uses static context only
- **Circuit breaker**: trips after 2 consecutive failures, 5-minute cooldown
- **Caching**: results cached 10 min, failures cached 2 min
- **Timeouts**: per-tool 8s, total retrieval 10s

### Template Type Detection
`mcp_context.py` maps prompt keywords to template types:
```
"dragon" / "fly" / "bat"     → flying
"zombie" / "skeleton"         → humanoid
"pig" / "sheep" / "rabbit"   → small_animal
"cow" / "horse" / "bear"     → large_animal
"spider" / "bee" / "ant"     → insect
"slime" / "blob"             → slime
... (30+ template types)
```

---

## 18. Database & RAG (Mob Templates)

**Files:** `backend/database/`, `backend/mob_management/`, `data/database_insertion/`

The app connects to a PostgreSQL (Neon) database containing pre-built mob templates.

### How RAG Works
1. User clicks "Generate from Template" or the system finds similar mobs
2. `mob_management/retriever.py` → `find_similar_mobs()` does text similarity search
3. Matching mobs provide RAG context to the LLM
4. LLM uses these examples to generate better specs

### Publishing User Mobs
Users can publish their mobs to the database via `POST /api/publish`. This calls `data/database_insertion/publish_mob.py` → `publish_or_update_mob()`.

### Lazy Loading
Both `database/__init__.py` and `mob_management/__init__.py` use `__getattr__` for lazy imports. This prevents `psycopg2` from being loaded until actually needed, avoiding startup failures if the DB is unavailable.

---

## 19. Frontend Architecture

The frontend is a single-page app using vanilla HTML/CSS/JS (no framework). Scripts are loaded as individual `<script>` tags sharing a global scope.

### Module Organization

| Folder | Files | Responsibility |
|--------|-------|---------------|
| `js/core/` | `app.js`, `user.js` | App initialization, tab switching, user auth |
| `js/editor/` | `editor.js`, `form-editor.js` | JSON spec editing, visual form editing |
| `js/viewer/` | `viewer3d.js`, `painter.js` | Three.js 3D preview, canvas texture painter |
| `js/build/` | `builder.js`, `llm.js`, `mctools.js` | Build triggers, LLM prompt UI, MCP tools UI |
| `js/ui/` | `modals.js` | Template picker, mob creation modals |

### 3D Viewer (`viewer3d.js`)
- Uses Three.js r128 for real-time 3D mob preview
- Reads Bedrock geometry JSON and builds Three.js meshes
- Applies UV mapping using Bedrock's box UV format
- Supports orbit controls for rotation/zoom

### Key Frontend → Backend API calls:

| Action | Endpoint | JS File |
|--------|----------|---------|
| Generate mob | `POST /api/spec/llm` | `llm.js` |
| Save spec | `POST /api/mobs/{name}` | `editor.js` |
| Build addon | `POST /api/build` | `builder.js` |
| Get templates | `GET /api/template/mobs` | `modals.js` |
| Fetch geometry | `GET /api/geometry/{mob}` | `builder.js` |

---

## 20. Challenges & Hard-Won Fixes

This section documents every major bug and its root cause. These are the things that will bite you if you change the wrong code.

### Invisible Mobs (The Big One)
**Symptoms:** Mob spawns but is completely invisible in Minecraft.
**Root causes (all had to be fixed together):**

1. **Custom render controllers fail** → Must use `controller.render.default`
2. **Wrong min_engine_version** → Must be `[1, 16, 0]` (not higher)
3. **Behavior format_version too high** → Must be `"1.16.0"`
4. **Nested texture paths** → Must be flat: `textures/entity/{mob}.png` (not `textures/entity/{mob}/{mob}.png`)
5. **Missing BP↔RP cross-linking** → Manifests must reference each other's UUIDs
6. **Missing spawn_egg in client entity** → Spawn egg must be in `minecraft:client_entity`, NOT in behavior `description`
7. **Wrong filter format** → Must use flat `{test, subject, value}` (not `any_of` wrapper)
8. **Missing behavior.float** → Without this, entity immediately sinks into the ground

### UV Overflow (The Real Root Cause of Invisible Mobs)
**The actual #1 cause:** LLM-generated geometry has cubes whose UV coordinates exceed the declared texture atlas size. Minecraft silently fails to render the entire entity.

**Fix:** `_fix_geometry_uv()` calculates the minimum atlas size needed for all cubes and rounds up to the next power-of-two. Every geometry goes through this before being written.

### Vanilla Geometry Not Found
**Problem:** Using `geometry.chicken` in a custom pack doesn't work — Minecraft only resolves it for the actual chicken entity.

**Fix:** `_fetch_vanilla_geometry()` downloads the real geometry JSON from Mojang's GitHub Bedrock samples repo and ships it in the pack.

### Old vs. New Geometry Format
**Problem:** Many vanilla mobs use old format `{"geometry.bat": {...}}` instead of new `{"minecraft:geometry": [...]}`.

**Fix:** `_normalize_geometry()` in `routes.py` converts old → new format when fetching from GitHub.

### Fire-Breathing Mobs Don't Shoot
**Problem:** Dragon with `minecraft:shooter` + `behavior.ranged_attack` still runs up and melee attacks.

**Fix:** Post-merge fixup removes `behavior.melee_attack` when ranged attack components are present.

### Execute Syntax Silently Fails
**Problem:** Auto-spawn commands using new `execute as @a at @s run` syntax don't work.

**Fix:** Switched to old Bedrock syntax `execute @a[tag=!mf_spawned] ~ ~ ~ summon`. The new syntax requires `min_engine_version [1, 19, 70]`.

### CRLF Line Endings Break mcfunction
**Problem:** Windows `\r\n` line endings cause Minecraft to fail parsing `.mcfunction` and JSON files.

**Fix:** `_write_text()` uses `write_bytes()` with explicit UTF-8 encoding to ensure LF-only output.

### LLM Loses Custom Geometry on Re-prompt
**Problem:** Re-prompting a dragon to "drop diamonds" causes LLM to replace dragon geometry with chicken.

**Fix:** Three-layer defense: geometry summary in LLM input, system prompt rule, and `_preserve_geometry()` post-LLM restoration. See [Geometry Preservation](#8-geometry-preservation-on-iterative-edits).

### Mobs Drop Bones Instead of Specified Items
**Problem:** User asks "drop diamonds" but mob drops bones in `.mcworld`.

**Root cause:** The `.mcworld` build path (MCP) has its own loot table generation that defaults to bones when `metadata["loot_drops"]` is empty. The fix in `builders.py` only fixed the `.mcpack` path.

**Fix (4 breakpoints):**
1. Added `loot_drops` to schema so it persists
2. Updated LLM prompt to use MCP-compatible format (`item`/`count_min`/`count_max`/`chance`)
3. `packaging.py` now passes `loot_drops` into MCP metadata
4. `builders.py` auto-wires `minecraft:loot` component when `loot_drops` exists

### Texture Misalignment
**Problem:** Eyes painted on texture don't appear on the head in-game.

**Fix:** Corrected `_box_uv_faces()` face labeling — "right" and "left" were swapped in the UV layout calculation.

---

## 21. Environment Variables

### Main App (`.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_TOKEN` | Yes (for OpenAI) | — | GitHub PAT with `models:read` scope |
| `DATABASE_URL` | For templates | — | PostgreSQL (Neon) connection string |
| `DEEPSEEK_API_KEY` | For DeepSeek | — | DeepSeek API key |
| `GEMINI_API_KEY` | For Gemini | — | Google Gemini API key |
| `ANTHROPIC_API_KEY` | For Claude | — | Anthropic API key |
| `LLM_MODEL` | No | `openai/gpt-4.1` | Override default model |
| `LLM_PROVIDER` | No | `openai` | Default LLM provider |
| `PORT` | No | `7860` | Server port |

### mctools (`MCTOOLS_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `MCTOOLS_ENABLED` | `true` | Enable/disable mctools |
| `MCTOOLS_MCP_URL` | `http://localhost:6126/mcp` | mctools endpoint |
| `MCTOOLS_TIMEOUT_MS` | `30000` | Tool call timeout |
| `MCTOOLS_ADMIN_PASSCODE` | `mctadm01` | Admin passcode |

### MCP Server (`MCP/.env`)

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | Only needed if using MCP's own LLM tools directly |
| `MOB_FORGE_MODEL` | Override model for all MCP tools |

**Note:** The `MCP/.env` variables are only needed for MCP's standalone LLM tools. The main pipeline only imports `build_mcworld` from MCP, which is pure local packaging logic — no API calls.

---

## 22. File Map (Quick Reference)

### Backend — API
| File | Role |
|------|------|
| `backend/api/app.py` | FastAPI app, middleware, route registration |
| `backend/api/routes.py` | All API endpoints (~1500 lines) |

### Backend — Build
| File | Role |
|------|------|
| `backend/build/builders.py` | Resource/behavior pack generation, UV fix, geometry fetch |
| `backend/build/packaging.py` | .mcworld/.mcaddon assembly, MCP delegation, NBT writer |

### Backend — Config
| File | Role |
|------|------|
| `backend/config/settings.py` | DEFAULTS, paths, LLM config, LLM_SYSTEM_PROMPT |

### Backend — LLM
| File | Role |
|------|------|
| `backend/llm/llm.py` | Main LLM pipeline: `llm_rewrite_spec()`, `llm_generate_geometry()` |
| `backend/llm/texture_gen.py` | Procedural UV-aware texture generator |
| `backend/llm/category_context.py` | Static per-category context (entity/item/block rules) |
| `backend/llm/dynamic_context.py` | Prompt-analyzed dynamic context injection |
| `backend/llm/mcp_context.py` | MCP context retrieval, template fetching, designModel |
| `backend/llm/llm_logger.py` | JSON logging of all LLM calls |
| `backend/llm/llm_scoring.py` | Semantic consistency scoring |

### Backend — Data
| File | Role |
|------|------|
| `backend/schemas/mob_spec.schema.json` | JSON Schema for mob spec validation |
| `backend/schemas/spec_utils.py` | validate_spec(), read/write specs, defaults |
| `backend/database/db.py` | PostgreSQL connection pool |
| `backend/mob_management/retriever.py` | Mob similarity search, template retrieval |
| `backend/data/vanilla_mobs.json` | Vanilla mob examples (for dynamic context) |

### Backend — mctools
| File | Role |
|------|------|
| `backend/mctools/client.py` | MCP client, subprocess management, SSE parsing |
| `backend/mctools/routes.py` | FastAPI routes for mctools UI |

### MCP
| File | Role |
|------|------|
| `MCP/mcp_server/tools/build_mcworld.py` | Authoritative .mcworld builder |
| `MCP/mcp_server/tools/bedrock_reference.py` | Manifest generators, client entity builders |

### Frontend
| File | Role |
|------|------|
| `frontend/index.html` | Single-page app HTML |
| `frontend/styles.css` | All CSS |
| `frontend/js/core/app.js` | Main init, tab switching |
| `frontend/js/core/user.js` | User auth, session |
| `frontend/js/editor/editor.js` | JSON spec editor, mob list |
| `frontend/js/editor/form-editor.js` | Visual form editor |
| `frontend/js/viewer/viewer3d.js` | Three.js 3D mob preview |
| `frontend/js/viewer/painter.js` | Canvas texture painter |
| `frontend/js/build/builder.js` | Build trigger, download, Play World |
| `frontend/js/build/llm.js` | LLM prompt UI, provider selection |
| `frontend/js/build/mctools.js` | MCP tools UI |
| `frontend/js/ui/modals.js` | Template picker, creation modals |
