# Bedrock Addon Builder — Full Pipeline Documentation

This document traces every step of the pipeline, from the moment a user types a prompt to the final `.mcworld` file that opens in Minecraft Bedrock Edition.

---

## Table of Contents

1. [Overview](#1-overview)
2. [User Input (Frontend)](#2-user-input-frontend)
3. [LLM Spec Generation](#3-llm-spec-generation)
4. [Context Injection](#4-context-injection)
5. [Geometry Generation](#5-geometry-generation)
6. [Build Pipeline](#6-build-pipeline)
7. [Resource Pack Patching](#7-resource-pack-patching)
8. [Behavior Pack Patching](#8-behavior-pack-patching)
9. [Post-Merge Fixups](#9-post-merge-fixups)
10. [MCP World Builder](#10-mcp-world-builder)
11. [Auto-Spawn Mechanism](#11-auto-spawn-mechanism)
12. [Output Artifacts](#12-output-artifacts)
13. [MCP Context Sources (mctools)](#13-mcp-context-sources-mctools)
14. [Environment Variables](#14-environment-variables)
15. [File Map](#15-file-map)

---

## 1. Overview

```
User Prompt
    │
    ▼
┌─────────────────────────────────────────┐
│  Frontend (editor.js / builder.js)      │
│  Sends prompt + current spec to backend │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  Backend Route: POST /api/llm           │
│  (backend/core/routes.py)               │
└──────────────────┬──────────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
┌───────────────┐   ┌─────────────────────┐
│ MCP Context   │   │ Static Context      │
│ (mctools)     │   │ (category_context)  │
│ Templates,    │   │ Entity rules,       │
│ Schemas       │   │ Vanilla reference,  │
│ (OPTIONAL)    │   │ JSON schemas        │
└───────┬───────┘   └────────┬────────────┘
        │                    │
        └────────┬───────────┘
                 ▼
┌─────────────────────────────────────────┐
│  LLM Call (OpenAI / DeepSeek / Gemini / │
│  Claude / Ollama)                       │
│  (backend/llm/llm.py)                   │
│  System prompt = base + MCP context     │
│                + static context         │
│                + schema                 │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  Spec Validation + Storage              │
│  (backend/schemas/spec_utils.py)        │
└──────────────────┬──────────────────────┘
                   │
          User clicks "Build"
                   │
                   ▼
┌─────────────────────────────────────────┐
│  Build Pipeline                         │
│  (backend/core/packaging.py)            │
│                                         │
│  1. patch_resource_pack (builders.py)   │
│  2. patch_behavior_pack (builders.py)   │
│  3. Cross-link manifests                │
│  4. create_mcworld (→ MCP builder)      │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  MCP World Builder                      │
│  (MCP/mcp_server/tools/build_mcworld.py)│
│                                         │
│  Assembles the final .mcworld ZIP:      │
│  - level.dat (NBT)                      │
│  - Embedded BP + RP                     │
│  - Auto-spawn functions                 │
│  - Pack linking                         │
└──────────────────┬──────────────────────┘
                   │
                   ▼
            .mcworld file
         (opens in Minecraft)
```

---

## 2. User Input (Frontend)

**Files:** `frontend/js/editor.js`, `frontend/js/builder.js`

The user interacts with the app in two ways:

### Prompt-based generation
- User types a prompt like "fire breathing dragon" in the chat input
- Frontend sends `POST /api/llm` with:
  - `prompt`: the user's text
  - `current`: the current mob spec JSON
  - `provider`: which LLM to use (openai, deepseek, gemini, claude, ollama)
  - `api_key`: the user's API key
  - `category`: content type (default: `entity_logic_ai`)

### Build trigger
- User clicks **Build** or **Play World**
- Frontend calls `POST /api/build` with:
  - `build_mode`: "mcworld", "mcaddon", "bundle", etc.
  - `specs_json`: array of mob specs to build
  - `textures_json`: base64 textures keyed by mob name

---

## 3. LLM Spec Generation

**File:** `backend/llm/llm.py`

**Function:** `llm_rewrite_spec(prompt, current, provider, api_key, category)`

This is the main generation entry point. It runs a 5-step pipeline:

### Step 1 — MCP Context Retrieval
```python
mcp_ctx = retrieve_context_sync(effective_prompt, category, current)
```
Calls `backend/llm/mcp_context.py` → `retrieve_context()` which fetches:
- **Schema**: from MCP `getEffectiveContentSchema` (currently returns empty — static schemas used instead)
- **Templates**: from MCP `getModelTemplates` (fetches geometry templates matching the prompt)

This is **non-blocking and additive** — if mctools is unavailable, it returns empty context and generation continues without it. A **circuit breaker** disables retrieval after 2 consecutive failures for 5 minutes.

### Step 2 — LLM Call
```python
output_spec = _call_provider(prompt, current, provider_key, api_key, category, mcp_ctx)
```
Routes to the appropriate provider (OpenAI, DeepSeek, Gemini, Claude, or Ollama). Each provider receives:
- **System prompt**: built by `_get_full_system_prompt()` (see Context Injection below)
- **User message**: `"Current spec:\n{spec_json}\n\nInstruction:\n{prompt}"`

The LLM returns a complete JSON spec which is parsed and validated.

### Step 3 — MCP Post-Validation
```python
mcp_validation = mcp_validate_sync(output_spec)
```
Currently a **no-op** — `mcp_validate()` returns `valid=True` immediately. The reason: our app uses an internal spec format (`hp`, `damage`, `speed`, `components` dict), but MCP's `validateContent` expects real Bedrock entity JSON. Sending our spec would waste 15+ seconds on a guaranteed parse failure.

### Step 4 — Retry on Validation Errors
If MCP validation finds retryable errors (structural/schema issues), the LLM is called again with error feedback injected into the prompt. Currently inactive since validation is a no-op.

### Step 5 — MCP Texture Generation
If the mob type changed (display_name differs from previous), calls `mcp_design_model_sync()` to generate a matching texture via mctools `designModel` tool.

### Return Value
The output spec includes `_mcp_meta` metadata:
```json
{
  "_mcp_meta": {
    "augmented": true,
    "context_sources": ["getModelTemplates"],
    "retrieval_ms": 450,
    "validation": { "ran": false, "valid": true, "messages": [] }
  },
  "_texture_b64": "data:image/png;base64,..."
}
```

---

## 4. Context Injection

**Files:** `backend/llm/llm.py` (`_get_full_system_prompt`), `backend/llm/category_context.py`, `backend/llm/mcp_context.py`

The system prompt is assembled in layers, ordered for LLM attention (most important first and last):

### Layer 1 — Base System Prompt
From `backend/core/core.py` → `LLM_SYSTEM_PROMPT`. Contains general rules about JSON output format, spec structure, and Bedrock conventions.

### Layer 2 — MCP Authoritative Schema (dynamic, optional)
```
--- AUTHORITATIVE BEDROCK SCHEMA (from Minecraft Creator Tools) ---
Use this schema as the ground truth for valid fields, types, and value ranges:
{schema_text}
--- END SCHEMA ---
```
Source: `mcp_context.py` → `_fetch_schema()`. Currently returns empty (placeholder). When active, would fetch from mctools `getEffectiveContentSchema`.

### Layer 3 — Category-Specific Context (static)
From `category_context.py` → `CATEGORY_CONTEXT[category]`. Contains:
- **Structure examples**: valid entity/item/block JSON templates
- **Key rules**: which components go together, what's required for hostile mobs, ranged attacks, breeding, etc.
- **Component reference**: vanilla component data from `backend/data/vanilla_reference.json` (if it exists)

For `entity_logic_ai`, this includes rules like:
- "To make a mob attack, you need ALL THREE: `minecraft:attack`, `minecraft:behavior.melee_attack`, and `minecraft:behavior.nearest_attackable_target`"
- "For ranged attacks: `minecraft:shooter` (with def string) + `minecraft:behavior.ranged_attack`"

### Layer 4 — MCP Model Templates (dynamic, optional)
```
--- MODEL TEMPLATES (from Minecraft Creator Tools) ---
Use these as starting points when creating or modifying geometry:
{template_text}
--- END TEMPLATES ---
```
Source: `mcp_context.py` → `_fetch_templates()`. Calls mctools `getModelTemplates` with a `templateType` inferred from prompt keywords:
- "dragon" / "fly" → `flying`
- "zombie" / "skeleton" → `humanoid`
- "pig" / "sheep" → `small_animal`
- "cow" / "horse" → `large_animal`
- etc. (see `TEMPLATE_KEYWORDS` in `mcp_context.py`)

These templates give the LLM **starting geometry and structure** to work from instead of inventing from scratch.

### Layer 5 — JSON Schema
From `backend/schemas/mob_spec.schema.json`. Defines valid fields, types, required properties, and value ranges for the mob spec format.

### Layer 6 — Dynamic Context (prompt-analyzed, always active)
```
--- DYNAMIC CONTEXT (selected based on your prompt) ---
{behavior docs, component examples, vanilla mob references}
--- END DYNAMIC CONTEXT ---
```
Source: `backend/llm/dynamic_context.py` → `build_dynamic_context()`. This is placed **last** in the system prompt for recency effect (LLMs attend more to the end).

**How it works:**
1. The user's prompt is scanned for behavioral intent keywords
2. Matching intents are detected (e.g. "fire breathing dragon" → `ranged_attack` + `flying`)
3. For each intent, relevant Bedrock component documentation is selected
4. Matching vanilla mob examples are pulled from `backend/data/vanilla_mobs.json`
5. Everything is assembled into a targeted context block (capped at 6000 chars)

**Supported intents:**

| Intent | Example keywords | Context injected |
|--------|-----------------|------------------|
| `ranged_attack` | fire breath, fireball, shoot, projectile | `minecraft:shooter` + `ranged_attack` docs, valid projectile types, blaze example |
| `flying` | fly, dragon, wings, hover, airborne | `movement.fly` + `navigation.fly` docs, conflict warnings |
| `exploding` | explode, bomb, creeper-like | `behavior.swell` + `explode` docs, creeper example |
| `passive` | peaceful, friendly, farm, pet | `behavior.panic` + `tempt` docs, cow/pig/sheep examples |
| `tameable` | tame, ride, mount, saddle | `tameable` + `rideable` + `input_ground_controlled` docs |
| `aquatic` | water, swim, shark, ocean | `navigation.swim` + `breathable` + `movement.sway` docs |
| `boss` | boss, elite, legendary, titan | High HP/damage guidelines, knockback resistance, area attack |
| `area_attack` | stomp, ground pound, AoE | `area_attack` component docs |
| `teleport` | teleport, blink, enderman | `teleport` component docs, enderman example |
| `climbing` | climb, wall climb, spider-like | `can_climb` + `navigation.climb` docs, spider example |
| `breeding` | breed, baby, offspring | `breedable` + `behavior.breed` docs |

**Key design properties:**
- **No external API calls** — all context is local data
- **Budget-aware** — capped at 6000 chars (~1500 tokens)
- **Additive** — never removes existing static context
- **Deterministic** — same prompt always produces same context
- **Multiple intents** — "flying fire-breathing boss dragon" gets ranged + flying + boss context simultaneously

### Total prompt budget
System prompt is capped at **25,000 characters** (~6K tokens). If it exceeds this, it's truncated with a warning.

---

## 5. Geometry Generation

**File:** `backend/llm/llm.py` (`llm_generate_geometry`)

Separate from spec generation. Called when the user requests geometry changes.

### Pipeline:
1. **Fetch MCP template** — `_fetch_geometry_template_sync(prompt)` retrieves a matching geometry template from mctools
2. **Build system prompt** — `GEOMETRY_SYSTEM_PROMPT` + MCP template text (if available)
3. **LLM call** — generates `minecraft:geometry` JSON with bones, cubes, UVs
4. **MCP texture generation** — calls `mcp_design_model_sync()` to create a texture that matches the geometry

### MCP designModel
`mcp_context.py` → `mcp_design_model()`:
- Converts Bedrock geometry into designModel-compatible format via `_geometry_to_design()`
- Adds per-face texture hints using `color_rgb` from the spec (or keyword-based color lookup)
- Applies shade variations per bone (darker for legs/tail, lighter for head/horn)
- Calls mctools `designModel` tool which generates a PNG texture and optionally modified geometry
- Reads texture and geometry back from disk

---

## 6. Build Pipeline

**File:** `backend/core/packaging.py` → `build_addon()`

Triggered by `POST /api/build`. Orchestrates the full build:

```python
def build_addon(specs, out_dir, res_src, beh_src, textures_dir=None):
    # 1. Prepare working directories
    work = tempdir()
    res_root = work / "res"
    beh_root = work / "beh"

    # 2. Patch resource pack (client entities, geometry, textures, lang)
    res_manifest = patch_resource_pack(res_root, specs, textures_dir)

    # 3. Patch behavior pack (server entities, AI, auto-spawn)
    beh_manifest = patch_behavior_pack(beh_root, specs)

    # 4. Cross-link manifests (BP ↔ RP UUID dependencies)
    #    Without this, Minecraft treats them as unrelated packs
    #    and the mob is invisible.

    # 5. Package outputs
    #    - .mcpack (resource)
    #    - .mcpack (behavior)
    #    - .mcaddon (both packs)
    #    - .mcworld (playable world via MCP builder)
    #    - .zip (bundle of everything)
```

---

## 7. Resource Pack Patching

**File:** `backend/core/builders.py` → `patch_resource_pack()`

Writes all client-side files for each mob:

### Client Entity (`entity/{mob}.entity.json`)
- Maps server entity identifier to client rendering
- References geometry, texture, render controller
- Includes spawn egg definition with custom colors
- Scale applied via `"scripts": {"scale": "2.2"}`

### Geometry (`models/entity/{mob}.geo.json`)
- Writes geometry JSON from spec
- **UV overflow fix** (`_fix_geometry_uv()`): if any cube's UV coordinates exceed the declared texture atlas size, the atlas is expanded to the next power-of-two
- **Vanilla geometry fetch** (`_fetch_vanilla_geometry()`): if geometry ID references a vanilla model (e.g. `geometry.chicken`), downloads it from Mojang's GitHub repo

### Texture (`textures/entity/{mob}.png`)
- If a custom texture exists (from painter or MCP designModel), writes it
- Otherwise generates a **placeholder PNG** using the spec's `color_rgb` value
- Texture dimensions are read from the `.geo.json` atlas size to ensure they match

### Language (`texts/en_US.lang`)
- `entity.custom:my_mob.name=Fire Breathing Dragon`
- `item.spawn_egg.entity.custom:my_mob.name=Spawn Fire Breathing Dragon`

### Manifest
- `min_engine_version: [1, 16, 0]` (compatible with all modern Bedrock versions)
- Type: `resources`

---

## 8. Behavior Pack Patching

**File:** `backend/core/builders.py` → `patch_behavior_pack()`

Writes all server-side files for each mob:

### Base Entity Template
Every mob starts with a **hostile pursuit-oriented** base:
```json
{
  "format_version": "1.16.0",
  "minecraft:entity": {
    "description": {
      "identifier": "custom:my_mob",
      "is_spawnable": true,
      "is_summonable": true
    },
    "components": {
      "minecraft:health": { "value": 60, "max": 60 },
      "minecraft:movement.basic": {},
      "minecraft:navigation.walk": { "can_walk": true, "can_pass_doors": true },
      "minecraft:attack": { "damage": 10 },
      "minecraft:behavior.float": { "priority": 0 },
      "minecraft:behavior.hurt_by_target": { "priority": 1 },
      "minecraft:behavior.nearest_attackable_target": {
        "priority": 2,
        "entity_types": [{ "filters": { "test": "is_family", "value": "player" }, "max_dist": 35 }]
      },
      "minecraft:behavior.melee_attack": { "priority": 3 },
      "minecraft:behavior.random_stroll": { "priority": 6 },
      "minecraft:behavior.look_at_player": { "priority": 8 },
      "minecraft:behavior.random_look_around": { "priority": 9 }
    }
  }
}
```

### LLM Component Merge
The LLM-generated `components` from the spec are merged on top of the base:
```python
for k, v in spec["components"].items():
    if v is None:
        del entity["components"][k]  # Remove component
    else:
        entity["components"][k] = v  # Override/add component
```

This is where the LLM's fire-breathing, flying, knockback resistance, etc. get applied.

---

## 9. Post-Merge Fixups

**File:** `backend/core/builders.py` (lines 471–509)

After merging LLM components, several automated fixups run to prevent silent failures in Bedrock:

### Ranged vs Melee Conflict
If the entity has both `minecraft:shooter` and `minecraft:behavior.ranged_attack`, remove `minecraft:behavior.melee_attack`. Otherwise the mob always runs up to melee range instead of shooting.

### Projectile Normalization
If `minecraft:shooter.def` is `"minecraft:fireball"` (ghast) or `"minecraft:dragon_fireball"`, it's replaced with `"minecraft:small_fireball"` (blaze fireball). The ghast fireball is unreliable for custom entities; the blaze fireball always works.

### Invalid Ranged Attack Parameters
LLMs sometimes hallucinate keys like `requires_target`, `burst_shot_delay`, `burst_shot_count` which are not valid Bedrock parameters. Invalid keys are stripped, and valid defaults are ensured:
- `attack_interval_min: 3.0`
- `attack_interval_max: 5.0`
- `attack_radius: 16.0`

### Movement Conflicts
- If `minecraft:movement.fly` is present → remove `minecraft:movement.basic`
- If `minecraft:navigation.fly` is present → remove `minecraft:navigation.walk`

These conflicts cause the mob to get stuck if both walk and fly variants coexist.

---

## 10. MCP World Builder

**File:** `MCP/mcp_server/tools/build_mcworld.py` → `build_mcworld()`

This is the **single source of truth** for `.mcworld` creation. Called by `packaging.py` → `create_mcworld()`.

### Translation Layer
`create_mcworld()` in `packaging.py` translates the app's format into MCP's input format:
```python
mcp_mobs.append({
    "entity": entity_data,       # Full behavior entity JSON (from beh_root)
    "metadata": {
        "display_name": "Fire Breathing Dragon",
        "suggested_style": "zombie",
        "suggested_colors": ["#225022", "#D82920"],
        "scale": 2.2
    },
    "texture_base64": "iVBOR...",  # PNG bytes as base64
    "geometry_data": { ... }       # Geometry JSON (UV-fixed)
})
```

**Important:** `entity_data` is read from the **already-patched behavior entity** file (`beh_root/entities/{mob}.json`), not regenerated. This preserves all LLM-generated components and the post-merge fixups.

### What the MCP builder writes into the .mcworld ZIP:

```
my_mob.mcworld (ZIP)
├── level.dat                           # Bedrock NBT (creative, flat, cheats on)
├── level.dat_old                       # Copy of level.dat
├── levelname.txt                       # World display name
├── world_behavior_packs.json           # Links BP by UUID
├── world_resource_packs.json           # Links RP by UUID
├── behavior_packs/
│   └── my_mob_BP/
│       ├── manifest.json               # BP manifest (min_engine_version 1.16.0)
│       ├── pack_icon.png
│       ├── entities/my_mob.json        # Full behavior entity
│       ├── loot_tables/entities/my_mob.json
│       └── functions/
│           ├── startup.mcfunction      # Auto-spawn commands
│           └── tick.json               # Calls startup every tick
├── resource_packs/
│   └── my_mob_RP/
│       ├── manifest.json               # RP manifest (min_engine_version 1.16.0)
│       ├── pack_icon.png
│       ├── entity/my_mob.entity.json   # Client entity
│       ├── models/entity/my_mob.geo.json
│       ├── textures/entity/my_mob.png
│       └── texts/en_US.lang
└── db/                                 # Empty LevelDB (Minecraft regenerates)
```

### level.dat
Built from scratch using a custom little-endian NBT writer. Key settings:
- `GameType: 1` (Creative)
- `Generator: 2` (Flat)
- `cheatsEnabled: 1`
- `commandsEnabled: 1`
- `commandblocksenabled: 1`
- `functioncommandlimit: 10000`

---

## 11. Auto-Spawn Mechanism

**Files:** `backend/core/builders.py`, `MCP/mcp_server/tools/build_mcworld.py`

Both files write the same auto-spawn logic (builders.py for mcpack/mcaddon, MCP for mcworld):

### tick.json
```json
{ "values": ["startup"] }
```
Calls `startup.mcfunction` every game tick.

### startup.mcfunction
```
execute @a[tag=!mf_spawned] ~ ~ ~ summon custom:my_mob ~2 ~ ~2
execute @a[tag=!mf_spawned] ~ ~ ~ tellraw @a {"rawtext":[{"text":"§aAddon Builder: §fCustom mobs summoned near you!"}]}
tag @a add mf_spawned
```

### How it works:
1. Every tick, Bedrock runs `startup`
2. If any player does NOT have the `mf_spawned` tag, the commands execute
3. The mob is summoned near that player
4. A chat message confirms the spawn
5. All players get tagged `mf_spawned`
6. On all subsequent ticks, the selector `@a[tag=!mf_spawned]` matches nobody, so nothing happens

### Why OLD execute syntax:
Uses `execute @a[tag=!mf_spawned] ~ ~ ~ summon ...` (old Bedrock syntax) instead of `execute as @a at @s run summon ...` (new syntax). The new syntax requires `min_engine_version [1, 19, 70]` in the manifest. Since we use `[1, 16, 0]` for maximum compatibility, the old syntax is required. The new syntax silently fails on older engine versions.

---

## 12. Output Artifacts

`build_addon()` produces:

| Artifact | Description |
|----------|-------------|
| `{mob}_resources.mcpack` | Resource pack only (client entities, textures, geometry) |
| `{mob}_behavior.mcpack` | Behavior pack only (server entities, AI, auto-spawn) |
| `{mob}.mcaddon` | Both packs combined (install into existing world) |
| `{mob}.mcworld` | Complete playable world with packs embedded |
| `{mob}_output_bundle.zip` | All of the above + specs.json + BUILD_LOG.txt |

---

## 13. MCP Context Sources (mctools)

**Files:** `backend/llm/mcp_context.py`, `backend/mctools/client.py`

The mctools integration provides **optional** context enrichment. It connects to a local Minecraft Creator Tools MCP server (Node.js process on port 6126).

### Currently Active Context Sources:

| Source | Tool | What it provides | Used where |
|--------|------|------------------|------------|
| **Model Templates** | `getModelTemplates` | Starting geometry structures for mob types (humanoid, flying, quadruped, etc.) | LLM system prompt (Layer 4), geometry generation |
| **Design Model** | `designModel` | Generates texture PNGs from geometry + color hints | After spec generation (if mob type changed), after geometry generation |

### Currently Inactive (implemented but disabled):

| Source | Tool | Why inactive |
|--------|------|--------------|
| **Content Schema** | `getEffectiveContentSchema` | Requires a populated Minecraft project folder on disk |
| **Validation** | `validateContent` | Our spec format differs from Bedrock entity JSON; would always fail |

### Availability
- mctools is **optional** — if `MCTOOLS_ENABLED=false` or the server is down, generation proceeds with static context only
- Circuit breaker trips after 2 failures, cooldown 5 minutes
- Results cached for 10 minutes (failures cached for 2 minutes)
- Per-tool timeout: 8 seconds; total retrieval timeout: 10 seconds

### Template Type Detection
`mcp_context.py` maps prompt keywords to mctools template types:
```
"dragon" / "fly" / "bat"     → flying
"zombie" / "skeleton"         → humanoid
"pig" / "sheep" / "rabbit"   → small_animal
"cow" / "horse" / "bear"     → large_animal
"spider" / "bee" / "ant"     → insect
"slime" / "blob" / "jelly"   → slime
"ghost" / "phantom"           → ghost
"robot" / "mech"              → robot
... (30+ template types total)
```

---

## 14. Environment Variables

### Main App (`/.env`)
| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes (for OpenAI) | GitHub PAT with `models:read` permission, used for GitHub Models API |
| `DEEPSEEK_API_KEY` | For DeepSeek | DeepSeek API key |
| `GEMINI_API_KEY` | For Gemini | Google Gemini API key |
| `ANTHROPIC_API_KEY` | For Claude | Anthropic API key |

### mctools (`MCTOOLS_*` env vars)
| Variable | Default | Description |
|----------|---------|-------------|
| `MCTOOLS_ENABLED` | `true` | Enable/disable mctools integration |
| `MCTOOLS_MCP_URL` | `http://localhost:6126/mcp` | mctools MCP endpoint |
| `MCTOOLS_TIMEOUT_MS` | `30000` | Tool call timeout in ms |
| `MCTOOLS_ADMIN_PASSCODE` | `mctadm01` | Admin passcode for mctools server |

### MCP Server (`/MCP/.env`)
| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Only if using MCP's own generation tools | GitHub PAT |
| `MOB_FORGE_MODEL` | No | Override model for all MCP tools |
| `MOB_FORGE_MOB_MODEL` | No | Override model for mob generation |
| `MOB_FORGE_GEOMETRY_MODEL` | No | Override model for geometry |
| `MOB_FORGE_TEXTURE_MODEL` | No | Override model for textures |

**Note:** The `MCP/.env` variables are only needed if you use MCP's own LLM-based generation tools directly. The current pipeline does **not** use them — it only imports `build_mcworld` from MCP, which is local packaging logic with no API calls.

---

## 15. File Map

### Backend — LLM & Context
| File | Role |
|------|------|
| `backend/llm/llm.py` | Main LLM entry points: `llm_rewrite_spec`, `llm_generate_geometry` |
| `backend/llm/mcp_context.py` | MCP context retrieval, template fetching, designModel, validation |
| `backend/llm/category_context.py` | Static per-category context: entity rules, item rules, block rules, loot rules |
| `backend/core/core.py` | Base system prompt, defaults, paths, color palette |

### Backend — Build & Packaging
| File | Role |
|------|------|
| `backend/core/routes.py` | FastAPI route handlers, `_build_and_bundle()` |
| `backend/core/packaging.py` | `build_addon()`, `create_mcworld()`, NBT writer, `_build_level_dat()` |
| `backend/core/builders.py` | `patch_resource_pack()`, `patch_behavior_pack()`, UV fix, geometry fetch |
| `backend/schemas/spec_utils.py` | Spec validation, defaults |

### Backend — mctools Integration
| File | Role |
|------|------|
| `backend/mctools/client.py` | MCP client over Streamable HTTP, subprocess management, SSE parsing |
| `backend/mctools/routes.py` | FastAPI routes for mctools UI features |

### MCP — World Builder
| File | Role |
|------|------|
| `MCP/mcp_server/tools/build_mcworld.py` | Authoritative .mcworld builder, NBT writer, pack embedding |
| `MCP/mcp_server/tools/bedrock_reference.py` | Valid component lists, manifest generators, client entity generators |

### Frontend
| File | Role |
|------|------|
| `frontend/js/editor.js` | Spec editing, mob list management |
| `frontend/js/builder.js` | Build trigger, artifact download, Play World |
| `frontend/js/mctools.js` | mctools UI integration |

---

## Summary

The pipeline has **three context sources** that feed the LLM:

1. **Static context** (always active): category rules, entity structure examples, vanilla component reference, JSON schema
2. **MCP templates** (active when mctools is running): geometry starting points matched by prompt keywords
3. **MCP designModel** (active when mctools is running): texture generation from geometry + color hints

And **two build paths** that produce the final output:

1. **builders.py**: Prepares resource pack (rendering) + behavior pack (AI, auto-spawn) with post-merge fixups
2. **MCP build_mcworld.py**: Takes the prepared packs and assembles a complete `.mcworld` with level.dat, pack linking, and embedded content
