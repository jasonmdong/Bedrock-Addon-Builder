# Animation Pipeline — Internal Documentation

This document describes how the Bedrock Addon Builder generates, validates,
processes, and packages Minecraft Bedrock Edition animations for custom entities.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Pipeline Stages](#pipeline-stages)
   - [Stage 1: Intent Detection](#stage-1-intent-detection)
   - [Stage 2: LLM Spec Generation](#stage-2-llm-spec-generation)
   - [Stage 3: Animation Generation](#stage-3-animation-generation)
   - [Stage 4: Animation Controller Generation](#stage-4-animation-controller-generation)
   - [Stage 5: Component Sanitization](#stage-5-component-sanitization)
   - [Stage 6: Build-Time Processing](#stage-6-build-time-processing)
   - [Stage 7: Packaging into .mcworld](#stage-7-packaging-into-mcworld)
3. [Auto-Generated Fly Animations](#auto-generated-fly-animations)
4. [Animation Condition Logic (Molang)](#animation-condition-logic-molang)
5. [Geometry Post-Processors](#geometry-post-processors)
6. [Key Functions Reference](#key-functions-reference)
7. [Data Flow Diagram](#data-flow-diagram)
8. [Dual Pipeline Architecture](#dual-pipeline-architecture)
9. [Common LLM Mistakes & Build-Time Fixes](#common-llm-mistakes--build-time-fixes)

---

## Architecture Overview

The animation pipeline spans multiple modules:

```
User Prompt
    │
    ▼
┌──────────────────────┐
│  Intent Detection    │  backend/llm/prompt_intents.py
│  (flying, ranged)    │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  LLM Spec Rewrite    │  backend/llm/llm.py
│  (preserves anims)   │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  Animation Gen       │  backend/llm/animation_generation.py
│  (geometry → clips)  │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  Controller Gen      │  backend/llm/animation_controllers_generation.py
│  (clips → states)    │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  Component Sanitizer │  backend/llm/component_sanitizer.py
│  (fly deps, shooter) │
└──────────┬───────────┘
           ▼
┌──────────────────────┐     ┌──────────────────────┐
│  Build (builders.py) │────▶│  Package (packaging)  │
│  .mcaddon / .mcpack  │     │  .mcworld via MCP     │
└──────────────────────┘     └──────────────────────┘
```

Two parallel build pipelines exist:
- **`builders.py`** — writes resource/behavior packs to disk (`.mcaddon`/`.mcpack`)
- **`build_mcworld.py`** — writes a self-contained `.mcworld` ZIP via MCP

Both implement the same animation processing logic and must be kept in sync.

---

## Pipeline Stages

### Stage 1: Intent Detection

**File:** `backend/llm/prompt_intents.py`

The system scans the user's prompt for keywords that indicate animation-relevant
intents. This happens before any LLM call.

**Flying intent** triggers on: `fly`, `flying`, `hover`, `hovering`, `winged`,
`wings`, `airborne`.

**Ranged attack intent** triggers on: `ranged`, `projectile`, `shoot`,
`fireball`, `fire breath`, `arrow`, `beam`, etc.

The resulting `PromptIntentProfile` is appended to the LLM system prompt,
nudging the model to generate appropriate components (e.g., `minecraft:can_fly`,
`minecraft:shooter`) and bone structures (e.g., wings).

Template hints like `"bird"`, `"large_animal"` are also derived from keywords
like `dragon`, `phoenix`, `bat`, `wyvern`.

### Stage 2: LLM Spec Generation

**File:** `backend/llm/llm.py`

The main LLM call generates or rewrites a mob spec. Animations are handled
specially to avoid token bloat:

1. **`_prepare_spec_for_llm(spec)`** — Strips the full `animation_json` and
   `animation_controller_json` from the spec before sending to the LLM.
   Replaces them with summary strings like
   `"(ANIMATIONS PRESENT — DO NOT REMOVE) clips=[walk, fly, idle]"` so the
   LLM doesn't echo back huge JSON or corrupt it.

2. **`_sanitize_animation_fields(candidate)`** — After LLM response is parsed,
   this cleans up broken animation data. If `animation_json` is a string (the
   LLM echoed the placeholder) or a dict without `"animations"`, it's reset
   to `{}`. Same for `animation_controller_json` without
   `"animation_controllers"`.

3. **`_preserve_animations(output_spec, input_spec)`** — If the LLM output
   lost valid animations that existed in the input (common when the LLM was
   asked to change behavior only), the original `animation_json` and
   `animation_controller_json` are copied back from the input spec.

4. **`_auto_fetch_geometry(output_spec)`** — When the spec needs custom
   geometry (non-vanilla mob) but has none, this generates geometry via LLM,
   then chains into animation generation and controller generation:
   ```
   geometry → llm_generate_animation(geometry) → llm_generate_animation_controller(animations)
   ```

### Stage 3: Animation Generation

**File:** `backend/llm/animation_generation.py`

Generates a Bedrock `animation.json` from entity geometry.

**Entry point:** `llm_generate_animation(prompt, mob_name, geometry_json, ...)`

**Process:**

1. **Extract bones** — `_extract_bones_from_geometry()` collects bone names
   from `minecraft:geometry`, skipping `root`.

2. **Build system prompt** — `_get_animation_system_prompt()` creates a
   detailed prompt including:
   - The bone list
   - Walk/fly/idle animation hints derived from bone names (e.g., bones
     containing `"wing"` trigger fly animation examples)
   - Embedded JSON examples using `animation.{mob_name}.*` naming

3. **Fetch templates** (optional) — `_fetch_animation_template_sync()` retrieves
   walk/idle templates from MCP for enrichment.

4. **LLM call** — Routes to the configured provider (OpenAI, Gemini, Anthropic,
   DeepSeek, Ollama) with `response_format=json_object` and `temperature=0.5`.

5. **Post-processing:**
   - `_fix_keyframe_format()` — Normalizes LLM mistakes: converts
     array-of-dicts to single dicts, stringifies time keys, strips invalid
     fields like `bone_position`.
   - Validates structure with `validate_animation_format()`
   - Optional MCP validation
   - Enforces `format_version: "1.8.0"` if missing

**Output:** A dict with `animation_json`, `mcp_verified`, `bone_count`,
`provider`, `error`, and `elapsed_ms`.

**Constants:**
- `ANIMATION_FORMAT_VERSION = "1.8.0"`

### Stage 4: Animation Controller Generation

**File:** `backend/llm/animation_controllers_generation.py`

Generates a Bedrock `animation_controllers.json` state machine from an
existing `animation.json`.

**Entry point:** `llm_generate_animation_controller(animation_json, mob_name, ...)`

**Process:**

1. **Build system prompt** — `_get_ac_system_prompt()` maps full animation IDs
   to short names and constructs state machine rules:
   - If any animation name contains `"fly"`, a `flying` state is added with
     `!query.is_on_ground` transition
   - Similar logic for swim/walk states
   - Instructs LLM to use **short names** in `animations` arrays (Bedrock
     resolves them via the client entity's `animations` map)

2. **LLM call** — Same provider routing as animations, max_tokens 2000.

3. **Post-processing:** MCP validation, enforce `format_version: "1.10.0"`.

**Helper:** `ensure_animations_and_controller()` — If a spec has animations
but no controller (or vice versa), generates the missing piece.

**Constants:**
- `AC_FORMAT_VERSION = "1.10.0"`

### Stage 5: Component Sanitization

**File:** `backend/llm/component_sanitizer.py`

Runs after spec generation but before building. Handles dependency injection
for fly-related components:

- If `minecraft:navigation.fly` or `minecraft:movement.fly` is present but
  `minecraft:can_fly` is missing → auto-inject `minecraft:can_fly: {}`
- If `minecraft:shooter` exists → ensure `behavior.ranged_attack` is present
- If projectile is fireball-like → inject `minecraft:fire_immune`
- If ranged attack → ensure `nearest_attackable_target` with proper filters

**Conflict resolution:** `resolve_conflicts()` ensures `movement.fly` wins
over `movement.basic` when both are present.

Note: The sanitizer does **not** read `animation_json`. Fly behavior injection
based on wing bones or fly animations happens at build time (Stage 6).

### Stage 6: Build-Time Processing

**File:** `backend/build/builders.py`

This is where animations are processed for the `.mcaddon`/`.mcpack` output.
Two functions handle the two packs:

#### `patch_resource_pack` — Client Entity Wiring

1. **Auto-generate fly animation** — `_ensure_fly_animation(spec)` checks if
   the geometry has wing bones but no fly animation exists. If so, it generates
   a basic wing-flapping animation with:
   - Left wing: Z-rotation oscillating -45° → 15° → -45°
   - Right wing: Z-rotation oscillating 45° → -15° → 45°
   - Body: subtle X-rotation bob (2° → -2° → 2°)

2. **Sanitize animations** — `_sanitize_animations()` removes
   `anim_time_update` from walk/run animations (causes jitter on custom
   entities).

3. **Write animation files** — `animations/{short_name}.animation.json`

4. **Build `anim_refs` map** — Maps short keys (e.g., `"walk"`) to full
   animation IDs (e.g., `"animation.fire_giraffe.walk"`) using
   `_anim_short_key()`.

5. **Remap controller references** — Animation controllers from the LLM may
   reference full animation IDs; these are remapped to short names so Bedrock
   can resolve them via the client entity's `animations` map.

6. **Write controller files** — `animation_controllers/{short_name}.controllers.json`

7. **Build `scripts.animate` list** — Creates Molang-conditional animation
   playback entries (see [Animation Condition Logic](#animation-condition-logic-molang)).

8. **Set `client_desc["animations"]`** — The full `anim_refs` map becomes the
   client entity's animation reference table.

#### `patch_behavior_pack` — Fly Behavior Injection

After component processing, the builder checks if the mob should fly using
three signals:

```python
_should_fly = (
    _has_fly_anim           # "fly" in animation key names
    or _has_wing_bones(geo) # wing bones in geometry
    or _has_fly_components  # can_fly, movement.fly, etc. in components
)
```

If any signal is true, it injects:
- `minecraft:movement.fly` (replaces `movement.basic`)
- `minecraft:navigation.fly` (replaces `navigation.walk`)
- `minecraft:can_fly`
- `minecraft:flying_speed: {"value": 0.4}`
- `minecraft:behavior.float: {"priority": 0}`
- `minecraft:behavior.random_fly: {"priority": 5, ...}`
- `minecraft:behavior.random_stroll: {"priority": 7, ...}` (for ground movement)
- Removes `minecraft:behavior.wander` (conflicts with flight)

### Stage 7: Packaging into .mcworld

**File:** `backend/build/packaging.py` → `MCP/mcp_server/tools/build_mcworld.py`

`packaging.py` builds an `mcp_mobs` list from specs, passing `animation_json`
and `animation_controller_json` as fields, then calls MCP's `build_mcworld`.

`build_mcworld.py` repeats the same animation processing as `builders.py`
inside the ZIP:

1. Auto-generate fly animation for wing bones
2. Sanitize animations (remove `anim_time_update`)
3. Build short-key map
4. Remap controller references
5. Write animation/controller JSON into ZIP
6. Build `_build_client_entity` with `scripts.animate`
7. Inject fly behaviors into behavior entity

---

## Auto-Generated Fly Animations

When the geometry contains bones with `"wing"` in the name but no animation
key contains `"fly"`, the build pipeline auto-generates a fly animation.

**Detection helpers:**

| Function | File | Returns |
|----------|------|---------|
| `_has_wing_bones(geo)` | builders.py | `bool` |
| `_get_wing_bone_names(geo)` | builders.py, build_mcworld.py | `list[str]` |
| `_has_fly_components(comps)` | builders.py | `bool` |
| `_ensure_fly_animation(spec)` | builders.py | `None` (mutates spec) |

**Generated animation structure:**

```json
{
  "animation.{short_name}.fly": {
    "loop": true,
    "animation_length": 1.0,
    "bones": {
      "wing_left": {
        "rotation": {
          "0.0": [0, 0, -45],
          "0.5": [0, 0, 15],
          "1.0": [0, 0, -45]
        }
      },
      "wing_right": {
        "rotation": {
          "0.0": [0, 0, 45],
          "0.5": [0, 0, -15],
          "1.0": [0, 0, 45]
        }
      },
      "body": {
        "rotation": {
          "0.0": [2, 0, 0],
          "0.5": [-2, 0, 0],
          "1.0": [2, 0, 0]
        }
      }
    }
  }
}
```

---

## Animation Condition Logic (Molang)

The `scripts.animate` list on the client entity controls when each animation
plays. Conditions are **mutually exclusive** to prevent jitter from competing
animations.

### Condition Matrix

| Short Key | Has Walk? | Has Fly? | Molang Condition |
|-----------|-----------|----------|------------------|
| `idle` | No | No | `"1.0"` (always) |
| `idle` | Yes | No | `"!query.is_moving"` |
| `idle` | No | Yes | `"query.is_on_ground"` |
| `idle` | Yes | Yes | `"query.is_on_ground && !query.is_moving"` |
| `walk` | — | No | `"query.is_moving"` |
| `walk` | — | Yes | `"query.is_on_ground && query.is_moving"` |
| `fly` | — | — | `"!query.is_on_ground"` |
| `attack`* | — | — | `"variable.attacking"` |

\* Attack-like keys: `attack`, `attacking`, `breath`, `fire`, `fire_breath`,
`fire_attack`, `shoot`, `bite`, `charge`

### Resulting `scripts.animate` Example

```json
{
  "scripts": {
    "animate": [
      {"idle": "query.is_on_ground && !query.is_moving"},
      {"walk": "query.is_on_ground && query.is_moving"},
      {"fly": "!query.is_on_ground"},
      {"fire_breath": "variable.attacking"}
    ]
  }
}
```

---

## Geometry Post-Processors

Three geometry fixers run at build time (before animation processing):

### `_fix_geometry_scale`
Detects when the largest cube dimension is under 6 pixels (LLM generated
"real-world" scale instead of Minecraft pixel scale). Scales the entire model
up by 2–6x.

### `_fix_geometry_uv`
Detects UV coordinates that exceed the declared `texture_width`/`texture_height`
and expands the atlas to the next power of two.

### `_fix_geometry_legs`
Handles two cases:
1. **Legs below Y=0** (underground) — shifts the entire model up so the
   lowest leg cube sits at Y=0
2. **Legs overlap with body** (same Y level) — shifts non-leg bones up so
   legs are visible below the body

**Execution order:** `_fix_geometry_scale` → `_fix_geometry_uv` → `_fix_geometry_legs`

---

## Key Functions Reference

### animation_generation.py

| Function | Purpose |
|----------|---------|
| `llm_generate_animation` | Main entry: geometry → LLM → animation.json |
| `_extract_bones_from_geometry` | Collects bone names from geometry |
| `_get_animation_system_prompt` | Builds LLM prompt with bone hints |
| `_fix_keyframe_format` | Normalizes malformed keyframes |
| `validate_animation_format` | Structural validation |
| `ensure_animations_and_controller` | Generates missing half of anim+controller pair |

### animation_controllers_generation.py

| Function | Purpose |
|----------|---------|
| `llm_generate_animation_controller` | Main entry: animations → LLM → controllers |
| `_get_ac_system_prompt` | Builds state machine prompt with fly/walk hints |
| `validate_animation_controller_format` | Structural validation |

### llm.py

| Function | Purpose |
|----------|---------|
| `_prepare_spec_for_llm` | Strips animation JSON, replaces with summary |
| `_sanitize_animation_fields` | Cleans broken LLM animation output |
| `_preserve_animations` | Restores animations lost during LLM rewrite |
| `_has_valid_animations` | Checks for non-empty `animations` dict |
| `_auto_fetch_geometry` | Chains geometry → animation → controller generation |

### builders.py

| Function | Purpose |
|----------|---------|
| `_sanitize_animations` | Removes `anim_time_update` from walk/run |
| `_anim_short_key` | Extracts short key from full animation ID |
| `_ensure_fly_animation` | Auto-generates fly animation for wing bones |
| `_has_wing_bones` | Detects wing bones in geometry |
| `_get_wing_bone_names` | Returns wing bone names |
| `_has_fly_components` | Checks for fly-related entity components |
| `_fix_geometry_scale` | Scales up undersized geometry |
| `_fix_geometry_uv` | Fixes UV overflow |
| `_fix_geometry_legs` | Fixes underground or overlapping legs |

### build_mcworld.py

| Function | Purpose |
|----------|---------|
| `_sanitize_animations` | Same as builders (walk/run jitter fix) |
| `_anim_short_key` | Same as builders |
| `_get_wing_bone_names` | Same as builders |
| `_fix_geometry_scale` | Same as builders (mutates in-place) |
| `_fix_geometry_legs` | Same as builders (mutates in-place) |
| `_remap_controller_to_short_names` | Converts full IDs in controllers |
| `_build_client_entity` | Builds client entity with animation wiring |

### prompt_intents.py

| Function | Purpose |
|----------|---------|
| `extract_prompt_intents` | Keyword-based intent detection |

### component_sanitizer.py

| Function | Purpose |
|----------|---------|
| `auto_inject_dependencies` | Injects `can_fly` when fly nav/movement present |
| `resolve_conflicts` | `movement.fly` wins over `movement.basic` |
| `sanitize_spec` | Full sanitization pipeline |

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User Prompt                                  │
│                    "Create a fire giraffe"                          │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │   extract_prompt_intents │
              │   signals: [flying]      │
              └────────────┬────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │   llm_rewrite_spec      │
              │   _prepare_spec_for_llm │  ◄── strips animation_json
              │   LLM call (gpt-4.1)   │
              │   _sanitize_anim_fields │  ◄── cleans broken output
              │   _preserve_animations  │  ◄── restores from input
              └────────────┬────────────┘
                           │
              ┌────────────┴────────────┐
              │  _auto_fetch_geometry   │  (if geometry missing)
              │    ┌────────────────┐   │
              │    │ llm_generate_  │   │
              │    │ animation()    │   │
              │    └───────┬────────┘   │
              │            ▼            │
              │    ┌────────────────┐   │
              │    │ llm_generate_  │   │
              │    │ anim_controller│   │
              │    └────────────────┘   │
              └────────────┬────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │   sanitize_spec         │
              │   auto_inject_deps      │  ◄── can_fly, fire_immune
              │   resolve_conflicts     │  ◄── fly > basic movement
              └────────────┬────────────┘
                           │
            ┌──────────────┴──────────────┐
            ▼                             ▼
┌───────────────────────┐   ┌──────────────────────────┐
│ patch_resource_pack   │   │ create_mcworld           │
│ ┌───────────────────┐ │   │ ┌──────────────────────┐ │
│ │_ensure_fly_anim   │ │   │ │ auto-gen fly anim    │ │
│ │_sanitize_animations│ │   │ │ _sanitize_animations │ │
│ │write anim JSON    │ │   │ │ write to ZIP         │ │
│ │build anim_refs    │ │   │ │ build anim_refs      │ │
│ │remap controller   │ │   │ │ remap controller     │ │
│ │build animate_list │ │   │ │ build animate_list   │ │
│ │ (Molang conditions)│ │   │ │ (Molang conditions)  │ │
│ └───────────────────┘ │   │ └──────────────────────┘ │
│                       │   │                          │
│ patch_behavior_pack   │   │ BP fly injection         │
│ ┌───────────────────┐ │   │ ┌──────────────────────┐ │
│ │detect fly signals │ │   │ │detect fly signals    │ │
│ │inject fly AI      │ │   │ │inject fly AI         │ │
│ │inject random_fly  │ │   │ │inject random_fly     │ │
│ │normalize shooter  │ │   │ │normalize shooter     │ │
│ └───────────────────┘ │   │ └──────────────────────┘ │
└───────────────────────┘   └──────────────────────────┘
         │                             │
         ▼                             ▼
   .mcaddon/.mcpack              .mcworld ZIP
```

---

## Dual Pipeline Architecture

The animation processing is duplicated across two pipelines:

| Concern | `builders.py` | `build_mcworld.py` |
|---------|---------------|-------------------|
| Output format | Files on disk → `.mcaddon` | In-memory ZIP → `.mcworld` |
| Fly animation auto-gen | `_ensure_fly_animation()` | Inline wing detection |
| Animation sanitize | `_sanitize_animations()` | `_sanitize_animations()` |
| Short key extraction | `_anim_short_key()` | `_anim_short_key()` |
| Controller remap | Inline loop | `_remap_controller_to_short_names()` |
| Animate list | Inline with Molang | Same Molang logic |
| Fly behavior injection | In `patch_behavior_pack` | In main `build_mcworld` |
| Geometry fixes | scale → uv → legs | scale → legs (no uv fix) |

**Important:** When modifying animation logic, both files must be updated
to keep behavior consistent across `.mcaddon` and `.mcworld` outputs.

---

## Common LLM Mistakes & Build-Time Fixes

| LLM Mistake | Fix | Location |
|-------------|-----|----------|
| `anim_time_update: "query.modified_distance_moved"` on walk | Strip at build time | `_sanitize_animations()` |
| Animation IDs in controller instead of short names | Remap to short names | Controller remap logic |
| No fly animation despite wing bones | Auto-generate fly clip | `_ensure_fly_animation()` |
| Tiny geometry (fractional cube sizes) | Scale up to block scale | `_fix_geometry_scale()` |
| Legs at negative Y (underground) | Shift entire model up | `_fix_geometry_legs()` |
| Legs overlap with body (same Y) | Shift body up | `_fix_geometry_legs()` |
| UV coordinates exceed atlas size | Expand atlas to next power of 2 | `_fix_geometry_uv()` |
| `large_fireball` projectile (unreliable) | Normalize to `small_fireball` | Shooter normalization |
| Missing `can_fly` with fly navigation | Auto-inject dependency | `auto_inject_dependencies()` |
| `animate` placed in `description` instead of `scripts` | Move to `scripts.animate` | Client entity builder |
| Animation controller uses old format version | Enforce `"1.10.0"` | `AC_FORMAT_VERSION` |
| `animation_json` echoed as placeholder string | Reset to `{}`, restore from input | `_sanitize_animation_fields()` |
| Missing `subject: "other"` in attack filters | Auto-inject | Filter normalization |
| `melee_attack` + `ranged_attack` (mob melees instead of shooting) | Remove melee | Builder conflict resolution |
