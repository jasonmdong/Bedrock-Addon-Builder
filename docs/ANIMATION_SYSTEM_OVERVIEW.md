# Bedrock Addon Builder - Animation System Overview

## 1. ANIMATION CODE LOCATIONS

### Core Animation Modules
| File | Lines | Purpose |
|------|-------|---------|
| [backend/llm/animation_generation.py](backend/llm/animation_generation.py) | ~2150 | Main animation generation engine via LLM |
| [backend/llm/animation_controllers_generation.py](backend/llm/animation_controllers_generation.py) | ~600+ | Animation controller (state machine) generation |
| [backend/core/routes.py](backend/core/routes.py) | ~1350+ | FastAPI route handlers for animation endpoints |
| [backend/core/app.py](backend/core/app.py) | ~130+ | FastAPI app setup and route registration |
| [backend/core/builders.py](backend/core/builders.py) | ~1000+ | Pack building, animation file writing |
| [backend/core/packaging.py](backend/core/packaging.py) | ~350+ | ZIP packing, animation file injection |
| [test_animation_validation.py](test_animation_validation.py) | ~100+ | Animation validation tests |

### LLM Integration Files
| File | Purpose |
|------|---------|
| [backend/llm/mcp_context.py](backend/llm/mcp_context.py) | MCP validation of animation JSON structure |
| [backend/llm/llm.py](backend/llm/llm.py) | Multi-provider LLM configuration & routing |
| [backend/core/core.py](backend/core/core.py) | Constants, defaults, system prompts |

### Geometry Module (Used by Animation)
| File | Purpose |
|------|---------|
| [backend/geometry/](backend/geometry/) | Geometry validation, bone extraction, positioning |

---

## 2. ANIMATION GENERATION FLOW

### High-Level Pipeline

```
User Input (mob description)
    ↓
llm_generate_animation() [animation_generation.py]
    ├─ Extract bone names from geometry_json
    ├─ Classify locomotion type (biped/flying/aquatic/etc)
    ├─ Build animation skeletons (pre-structured JSON for LLM to fill)
    ├─ Call LLM provider (OpenAI/DeepSeek/Gemini/Claude/Ollama)
    ├─ Extract JSON from LLM response
    ├─ Normalize animation structure (if malformed)
    ├─ Validate via MCP with retry loop
    └─ Return animation.json dict

    ↓
llm_generate_animation_controller() [animation_controllers_generation.py]
    ├─ Extract animation names from animation.json
    ├─ Build state machine system prompt
    ├─ Call LLM to generate controller (state transitions)
    ├─ Extract JSON from response
    ├─ Fix short-name references
    ├─ Validate via MCP with retry loop
    └─ Return animation_controllers.json dict

    ↓
Store in spec.animation_json & spec.animation_controller_json

    ↓
During build: patch_resource_pack() [builders.py]
    └─ Write animation.json & animation_controllers.json to RP

    ↓
During build: patch_behavior_pack() [builders.py]
    └─ Update entity.json with animation references

    ↓
During packaging: create_mcworld() [packaging.py]
    └─ Inject animation files into mcworld ZIP
```

### Detailed Generation Steps

#### Step 1: Extract Bone Names
**Function:** `_extract_bones_from_geometry(geometry_json)`
- Parses `minecraft:geometry[].bones[].name`
- Returns list of bone names (excluding "root")
- Used to build context for LLM

#### Step 2: Classify Locomotion Type
**Function:** `_classify_locomotion(mob_name, bones, provider, api_key)`
- LLM classifies the mob's movement type
- Returns: `{type, states[], reasoning}`
- Types: biped, quadruped, flying, aquatic, slithering, stationary, etc.
- Determines which animation states are needed (not hardcoded idle/walk/run)
- **Fallback:** If classification fails, defaults to `["idle", "walk", "run"]`

#### Step 3: Build Animation Skeletons
**Function:** `_get_animation_skeleton(mob_name, anim_type, bones)`
- Creates pre-structured JSON skeletons with ALL bones already defined
- Leaves FILL_IN_X, FILL_IN_Y, FILL_IN_Z placeholders for LLM to fill
- Purpose: Eliminate LLM hallucination of invented bone names
- Prevents malformed structures by providing valid template

#### Step 4: Build System Prompt
**Function:** `_get_animation_system_prompt(bone_names, mob_name, geometry_id)`
- Provides detailed Molang expression guidance
- Includes magnitude reference table (57.3 * multiplier = degrees)
- CRITICAL: Emphasizes bone animation requirements
  - For WALK/RUN: Leg bones MUST have motion math
  - For IDLE: Legs should be "0", only breathing/idle motion
  - For FLY: Wings MUST flap, legs can be "0"
  - For SWIM: Body/tail MUST wave, legs can be "0"

#### Step 5: Call LLM Provider
**Function:** `_call_animation_provider(prompt, system_prompt, provider, api_key)`
- Routes to provider-specific function (_call_animation_openai, _call_animation_deepseek, etc.)
- Supported providers:
  - OpenAI (gpt-4o) via OPENAI_API_KEY
  - DeepSeek (deepseek-chat) via DEEPSEEK_API_KEY
  - Gemini (gemini-pro) via GEMINI_API_KEY
  - Claude (claude-3-5-sonnet) via ANTHROPIC_API_KEY
  - Ollama (local) via OLLAMA_BASE_URL
- Temperature: 0.7, Max tokens: 2000

#### Step 6: Extract JSON from Response
**Function:** `_extract_json_from_response(content)`
- **Strategy 1:** Direct JSON parsing
- **Strategy 2:** Find JSON by looking for "animations"/"states" key with bracket matching
- **Strategy 3:** Find largest balanced brace block (top-level object)
- **Strategy 4:** Greedy regex fallback (last resort)
- Returns parsed dict or None

#### Step 7: Normalize Malformed Structure
**Function:** `_normalize_animation_json(animation_json, mob_name, bone_names)`
- **Problem:** LLM sometimes returns bones at root level instead of wrapped in "animations" object
- **Detection:** Looks for bones at root or "rotation" as bone name
- **Fix:** Wraps bones in proper "animations" object, creates idle/walk/run animations
- **Example:**
  ```python
  # Malformed: {"body": {...}, "head": {...}}
  # Fixed:     {"format_version": "1.8.0", "animations": {"animation.mob.idle": {...}}}
  ```

#### Step 8: MCP Validation with Retry
**Function:** `_validate_animation_with_retry(animation_dict, mob_name, bones, provider, api_key, max_retries=3)`
- Calls `mcp_validate_sync(content, schema_type="animation")`
- **On failure:** Feeds validation errors back to LLM with fix prompt
- **Retry loop:** Up to 3 attempts (configurable)
- **Result:** Either validated_animation, None, or error messages

#### Step 9: Generate Animation Controller
Same flow as animation but:
- **Input:** animation.json (extracts animation names)
- **LLM Task:** Generate state machine with `idle → walk → run` transitions
- **Queries:** Uses `query.is_moving`, `query.is_sprinting`, `query.ground_speed`, etc.
- **Critical Fix:** Converts long animation IDs to short names
  - e.g., `["animation.mob.idle"]` → `["idle"]` (entity.json provides mapping)

#### Step 10: Integrate into Spec
**Location:** [backend/core/routes.py](backend/core/routes.py) line ~973-1017
- Called via `llm_spec_editor()` endpoint
- Stores in `spec.animation_json`
- Stores in `spec.animation_controller_json`
- Sets `spec.animation_controller = f"controller.animation.{mob_name}"`
- **Auto-generation:**
  - If only animation_json exists → auto-generates controller
  - If only controller exists → auto-generates animation (from stated animation names)
  - Uses `ensure_animations_and_controller()` to maintain both

#### Step 11: Write to Packs
**Location:** [backend/core/builders.py](backend/core/builders.py)
- `patch_resource_pack()`: Writes animation files
  - `animations/{mob_name}.animation.json`
  - `animation_controllers/{mob_name}.animation_controllers.json`
- `patch_behavior_pack()`: Updates entity.json
  - Adds `minecraft:animation.controller` component
  - References controller ID

#### Step 12: Inject into MCWorld
**Location:** [backend/core/packaging.py](backend/core/packaging.py) lines ~296-336
- After MCP builds mcworld, animation files are injected into ZIP
- Finds pack prefixes dynamically (`behavior_packs/{name}_BP/`, `resource_packs/{name}_RP/`)
- Writes animation files to correct locations in ZIP

---

## 3. KEY ANIMATION FILES & FUNCTIONS

### animation_generation.py

**Main Entry Point:**
```python
def llm_generate_animation(
    prompt: str,
    geometry_json: dict,
    mob_name: str,
    current_animation: Optional[dict] = None,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict
```
- **Args:** User prompt, geometry, mob name, LLM config
- **Returns:** `{animation, mcp_verified, bone_count, provider, elapsed_ms, error}`
- **Lines:** ~1350-1680

**Helper Functions:**
| Function | Lines | Purpose |
|----------|-------|---------|
| `_extract_bones_from_geometry()` | ~680-695 | Parse bone names from geometry |
| `_classify_locomotion()` | ~1200-1260 | Ask LLM to classify movement type |
| `_get_animation_skeleton()` | ~700-760 | Build pre-structured JSON skeleton |
| `_get_animation_system_prompt()` | ~810-900 | Build detailed system prompt with Molang guidance |
| `_extract_json_from_response()` | ~152-247 | Robustly extract JSON from LLM response |
| `_normalize_animation_json()` | ~248-340 | Fix malformed structures |
| `validate_animation_format()` | ~341-391 | Validate animation.json structure |
| `validate_animation_controller_format()` | ~393-462 | Validate animation_controllers.json |
| `ensure_animations_and_controller()` | ~464-579 | Auto-generate missing files |
| `_validate_animation_with_retry()` | ~761-808 | MCP validation with LLM retry |
| `validate_physics_animation_sync()` | ~1807-2000+ | Check animation-physics sync |
| `batch_generate_animations()` | ~2050+ | Generate for multiple mobs |
| `_fetch_mojang_animation_sample()` | ~612-642 | Download real Minecraft examples |
| `_fetch_mojang_animation_controller_sample()` | ~644-680 | Download real controller examples |

**Provider-Specific Functions:**
- `_call_animation_openai()` - OpenAI API
- `_call_animation_deepseek()` - DeepSeek API
- `_call_animation_gemini()` - Gemini API
- `_call_animation_claude()` - Claude API (with model selection)
- `_call_animation_ollama()` - Local Ollama
- `_call_animation_provider()` - Router that selects provider

**Hardcoded Data:**
- `ANIMATION_FORMAT_VERSION = "1.8.0"` (line 39)
- Molang expression guidance in system prompt (detailed magnitude table)
- Default animation states: `["idle", "walk", "run"]` (fallback only)

### animation_controllers_generation.py

**Main Entry Point:**
```python
def llm_generate_animation_controller(
    animation_json: dict,
    mob_name: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict
```
- **Args:** animation.json dict, mob name, LLM config
- **Returns:** `{animation_controller, mcp_verified, provider, elapsed_ms, error}`
- **Lines:** ~400-600

**Helper Functions:**
| Function | Purpose |
|----------|---------|
| `_fetch_mojang_animation_controller_sample()` | Download real controller examples |
| `_extract_json_from_response()` | Extract JSON from LLM response |
| `_get_ac_system_prompt()` | Build state machine system prompt |
| `_build_controller_states()` | Fix short-name references in states |
| `_build_entity_animations_block()` | Build entity.json animations block (deterministic) |
| `_validate_animation_controller_with_retry()` | MCP validation with LLM retry |
| Provider-specific functions (OpenAI, DeepSeek, Gemini, Claude, Ollama) |

**Hardcoded Data:**
- `AC_FORMAT_VERSION = "1.8.0"` (line 37)
- Default query conditions: `query.is_moving`, `query.is_sprinting`, `query.ground_speed`
- Query condition guidance (list of available queries)

### builders.py

**Animation-Related Functions:**
| Function | Lines | Purpose |
|----------|-------|---------|
| `patch_resource_pack()` | ~500-600 | Write animation.json and controllers to RP |
| `patch_behavior_pack()` | ~200-400 | Update entity with animation references |
| `_fix_geometry_uv()` | ~50-80 | (Geometry fix, used with animations) |

**Key Code Section - Behavior Pack Entity Update:**
```python
# Adds minecraft:animation.controller component to behavior entity
entity_data["minecraft:animation.controller"] = {
    "controllers": [
        f"controller.animation.{mob_name}"
    ]
}
```

### packaging.py

**Animation Injection Code:**
- Lines ~296-336: `create_mcworld()` function
- Injects animation files into mcworld ZIP after MCP build
- Finds pack prefixes dynamically
- Writes both:
  - `behavior_packs/{pack}/animations/*.json`
  - `resource_packs/{pack}/animation_controllers/*.json`
- Logs each injected file

---

## 4. ISSUES & GAPS IDENTIFIED

### ✅ FIXED (from memory notes)

1. **Malformed Animation JSON Structure** ✅ FIXED
   - **Issue:** LLM returned bones at root level instead of wrapped in "animations" object
   - **Symptom:** `[ANIMATION-GEN] animation_dict keys: ['body', 'head', 'trunk', ...]` (no "animations" key)
   - **Fix:** `_normalize_animation_json()` detects and repairs
   - **Status:** Implemented, fallback in place

2. **Animation Controller Using Long Identifiers** ✅ FIXED
   - **Issue:** Controller referenced full IDs like `["animation.elephant.idle"]` instead of short names
   - **Symptom:** Minecraft couldn't find animations in entity.json
   - **Fix:** `_build_controller_states()` converts to short names like `["idle"]`
   - **Status:** Implemented, validated

3. **Redundant anim_time_update in Idle** ✅ FIXED
   - **Issue:** Idle animations had `"anim_time_update": "query.anim_time"` (redundant/risky)
   - **Fix:** Only add `anim_time_update` for non-idle animations
   - **Status:** Implemented in `_get_animation_skeleton()`

4. **Animation Files Lost in MCWorld** ✅ FIXED
   - **Issue:** Animation files written to temp dirs, lost when MCP builds mcworld
   - **Fix:** Added post-build zip injection in `create_mcworld()`
   - **Status:** Implemented, all files re-injected

5. **Missing Entity Scripts Block** ✅ FIXED
   - **Issue:** Entity.json had no `scripts` or `animations` block
   - **Fix:** Builders now write scripts block linking to controller
   - **Status:** Implemented in `patch_resource_pack()`

6. **Static Leg Bones in Movement Animations** ✅ ENHANCED
   - **Issue:** LLM setting all leg bones to ["0", "0", "0"] in walk/run
   - **Fix:** Added CRITICAL warnings and bone category guidance
   - **Status:** System prompt now explicit about which bones MUST have motion

### ⚠️ POTENTIAL ISSUES (Not Yet Confirmed)

1. **Test Coverage for Animations**
   - `test_animation_validation.py` tests validation logic only
   - **No golden test cases** for animation generation in `llm_scoring.py`
   - **No integration tests** for animation + controller generation
   - **Risk:** LLM output issues might not be caught until user builds

2. **Molang Expression Validation**
   - Skeletons provide templates, but LLM could still write invalid Molang
   - Example: `"math.sin(query.anim_time * foo)"` (undefined 'foo')
   - **Current validation:** Only checks JSON structure, not Molang validity
   - **Gap:** No semantic validation of Molang expressions (would require Molang parser)

3. **Bone Name Mismatches**
   - Skeletons pre-populate bone names to prevent hallucination
   - But if geometry changes after skeleton generation, bones could be wrong
   - **Risk:** Low (geometry is extracted immediately before skeleton)
   - **Mitigation:** System prompt warns: "DO NOT add or remove bones"

4. **Animation State Mismatch**
   - `_classify_locomotion()` determines states (idle, walk, run, fly, swim, etc.)
   - If classification output is malformed, could revert to default biped
   - **Current behavior:** Validates classification response, has fallback
   - **Gap:** No validation that returned states match any actual animation names

5. **Missing Transitions**
   - Animation controller could have states without transitions back to idle
   - Mob would get "stuck" in walk/run state
   - **Current validation:** `validate_physics_animation_sync()` checks this
   - **Gap:** Validation runs but doesn't fail the build (only warnings)

6. **Query Condition Syntax**
   - Transitions use query conditions like `query.is_moving && !query.is_sprinting`
   - LLM could write invalid syntax
   - **Current validation:** Checks for "query" in condition string
   - **Gap:** No syntax validation for Molang conditions

### 🔴 CRITICAL GAPS

1. **No Animation Golden Tests**
   - `llm_scoring.py` (the source of truth per CLAUDE.md) has NO animation test cases
   - Cannot measure LLM performance on animation generation
   - **Impact:** Can't compare providers, track quality, or validate improvements
   - **Recommendation:** Create 5-10 animation test cases:
     ```
     - test_basic_idle_animation (validates structure)
     - test_walk_leg_motion (validates leg bones have motion)
     - test_controller_state_transitions (validates all states have returns to idle)
     - test_flying_mob_animations (validates wings animate)
     - test_aquatic_animations (validates body wave motion)
     ```

2. **Hardcoded vs Classified Animation States**
   - System uses locomotion classification to determine animation states
   - But if classification fails or returns unexpected states, no graceful handling
   - Example: Classification returns `["idle", "hover", "dash"]` (non-standard)
   - **Risk:** Skeleton generation might fail for uncommon states
   - **Gap:** `_get_animation_skeleton()` expects specific state types (idle, walk, run, fly, swim, slither)
   - **Mitigation:** Needed: support for arbitrary state names or standardize classification output

3. **Format Version Compatibility**
   - `ANIMATION_FORMAT_VERSION = "1.8.0"` is hardcoded
   - Minecraft Bedrock now supports up to 1.21.0+
   - Older version might not support all modern features
   - **Gap:** No way to specify format version per mob type
   - **Recommendation:** Consider format_version 1.12.0 or 1.20.0 for better compatibility

4. **No Support for Custom Query Conditions**
   - Only uses standard queries: `query.is_moving`, `query.is_sprinting`, `query.ground_speed`
   - Cannot use custom queries defined in behavior components
   - **Gap:** Limited animation controller complexity
   - **Recommendation:** Allow custom query list in system prompt

5. **MCP Validation Disabled Scenarios**
   - If MCP is unavailable, animations are generated but not validated
   - Could produce invalid JSON that only fails at game load time
   - **Current behavior:** Validation runs with retry, but doesn't block generation
   - **Gap:** No hard failure if MCP unavailable
   - **Recommendation:** Document MCP requirement, add fallback JSON schema validation

6. **Animation-Physics Desync Not Enforced**
   - `validate_physics_animation_sync()` detects issues but only logs warnings
   - Doesn't prevent build or alert user to critical issues
   - **Example:** Walk animation has no leg motion but controller switches to walk state → "gliding" effect
   - **Current:** Only generates warning, not error
   - **Gap:** User could accidentally build broken animation without knowing
   - **Recommendation:** Expose sync validation results in API response, fail build on logic_failure_risk

### 📋 UNFINISHED/DEPRECATED

1. **`_fetch_animation_template_sync()` is DEPRECATED** (line ~1010)
   - Used to fetch MCP keyframe templates
   - Now uses GitHub Mojang samples instead (Molang format)
   - **Reason:** Format confusion (keyframes vs Molang expressions)
   - **Status:** Kept for backward compatibility, returns None

2. **MCP Animation Template Fetch** (in llm_generate_animation)
   - Code still fetches Mojang samples from GitHub
   - Shows examples in system prompt
   - **Gap:** Could be optimized (tests for existence before using)

---

## 5. TESTING STATUS

### Test Files

#### test_animation_validation.py (~100 lines)
**Purpose:** Validate animation JSON structure validation functions
**Tests:** 9 test cases
```
✓ Test 1: Valid animation.json → Pass
✓ Test 2: Invalid animation key (no "animation." prefix) → Detected
✓ Test 3: Non-dict animation value → Detected
✓ Test 4: Valid animation_controller.json → Pass
✓ Test 5: Controller with bad state reference → Detected
✓ Test 6: Missing format_version → Detected
✓ Test 7: Missing animations key → Detected
✓ Test 8: Empty animations dict → Detected
✓ Test 9: None animation → Detected
```
**Status:** All tests pass ✅

#### Golden Test Cases in llm_scoring.py
**Current:** NO animation test cases
**Recommendation:** Add these test cases:
```python
# Entity Logic & AI category
GoldenTestCase(
    name="animation_idle_walk_transitions",
    description="Animation controller should transition between idle and walk",
    prompt="Generate animations for walking and idle states",
    input_spec={...},
    required_components=["minecraft:animation.controller"],
    forbidden_components=[],
    required_fields={
        "animation_json": {"key_exists": "animations"},
        "animation_controller_json": {"key_exists": "animation_controllers"}
    },
)

# More test cases for:
# - Flying mobs (wings animate)
# - Aquatic mobs (body waves)
# - Leg motion in walk/run
# - Controller transitions
# - Molang expression validity
```

### No Integration Tests
- No API endpoint tests for `/api/animation/generate`
- No API endpoint tests for `/api/animation/controller/generate`
- **Gap:** Can't verify end-to-end animation generation works

---

## 6. DATA FLOW SUMMARY

### Spec Fields Added
```python
{
    "animation_json": {
        "format_version": "1.8.0",
        "animations": {
            "animation.mob.idle": {...},
            "animation.mob.walk": {...},
            "animation.mob.run": {...}
        }
    },
    "animation_controller_json": {
        "format_version": "1.8.0",
        "animation_controllers": {
            "controller.animation.mob": {
                "initial_state": "idle",
                "states": {...}
            }
        }
    },
    "animation_controller": "controller.animation.mob"
}
```

### File Output Locations

**Resource Pack:**
- `/resource_packs/{name}_RP/animations/{name}.animation.json`
- `/resource_packs/{name}_RP/animation_controllers/{name}.animation_controllers.json`

**Behavior Pack:**
- Entity.json updated with `minecraft:animation.controller` component

**MCWorld:**
- Same structure as packed files, but injected after ZIP creation

---

## 7. LLM PROVIDER SUPPORT

| Provider | Status | Config | Default Model | Notes |
|----------|--------|--------|----------------|----|
| OpenAI | ✅ Full | OPENAI_API_KEY | gpt-4o | Timeout: 30s |
| DeepSeek | ✅ Full | DEEPSEEK_API_KEY | deepseek-chat | Timeout: 30s |
| Gemini | ✅ Full | GEMINI_API_KEY | gemini-pro | Timeout: 30s |
| Claude | ✅ Full | ANTHROPIC_API_KEY | claude-sonnet-4-20250514 | Supports -opus variant |
| Ollama | ✅ Full | OLLAMA_BASE_URL | llama3.2 (default) | Local, timeout: 60s |

---

## 8. SYSTEM PROMPT CONTENT

### Animation Generation System Prompt

Provides:
1. Task description (fill in FILL_IN_X/Y/Z in skeleton)
2. Molang single-expression format (no keyframes)
3. Molang basics (math.sin, 57.3 conversion, queries)
4. Animation-specific guidance:
   - **IDLE:** Slow gentle oscillation (frequency 1-3, amplitude 0.05-0.15)
   - **WALK:** ±30-40° leg swings at 38.17 frequency, opposite leg negated
   - **RUN:** ±45-60° leg swings at 76.35 frequency (2x walk)
   - **FLY:** Wing flapping (4+ Hz), gentle banking
   - **SWIM:** Serpentine body motion, tail swish
   - **SLITHER:** Lateral undulation with phase offset
5. Rotation magnitude reference table (57.3 * 0.05 = ±2.9°, etc.)
6. Critical rules:
   - DO NOT add/remove bones
   - DO NOT change keys/structure
   - DO NOT use keyframe objects
   - ONLY replace FILL_IN_X/Y/Z
7. Examples for various bone motions

### Animation Controller System Prompt

Provides:
1. Task description (generate state machine)
2. Required format (controller.animation.mob structure)
3. Critical rules:
   - format_version "1.8.0"
   - Controller ID format
   - State names must match animation names
   - Minimum 2 states (idle, moving)
   - All animations must exist
4. Available query conditions
5. Example controller structure with transitions

---

## 9. CRITICAL READING POINTS

For detailed implementation:
- [animation_generation.py](backend/llm/animation_generation.py) lines 1350-1680 (main entry point)
- [animation_controllers_generation.py](backend/llm/animation_controllers_generation.py) lines 400-600 (controller generation)
- [animation_generation.py](backend/llm/animation_generation.py) lines 340-463 (validation functions)
- [routes.py](backend/core/routes.py) lines 1252-1330 (API endpoints)
- [builders.py](backend/core/builders.py) lines 500-600 (file writing)
- [packaging.py](backend/core/packaging.py) lines 296-336 (ZIP injection)

---

## 10. RECOMMENDATIONS FOR IMPROVEMENT

1. **Add Golden Test Cases** (HIGHEST PRIORITY)
   - Create 5-10 animation test cases in `llm_scoring.py`
   - Test locomotion classification, bone animation, controller transitions
   - Enable provider comparison

2. **Create Integration Tests**
   - Test `/api/animation/generate` endpoint
   - Test `/api/animation/controller/generate` endpoint
   - Test animation + controller together

3. **Add Molang Validation**
   - Could use regex patterns to validate common Molang expressions
   - Or parse Molang expressions (more complex)
   - At minimum: warn on undefined variable usage

4. **Expose Sync Validation in API**
   - Return `logic_failure_risk` and `visual_failure_risk` in response
   - Fail build if `logic_failure_risk` is true
   - Show warnings to user before build

5. **Support Format Versions**
   - Allow per-mob animation format version
   - Consider upgrading default to 1.20.0 (better compatibility)
   - Document version feature support

6. **Standardize Classified States**
   - Restrict `_classify_locomotion()` to known state sets
   - Or dynamically build guidance for arbitrary states
   - Ensure all returned states have animation guidance

7. **Add Animation Debugging Output**
   - Log animation skeleton before/after LLM
   - Log extracted JSON before/after normalization
   - Add debug endpoint to inspect intermediate steps

8. **Cache Mojang Samples**
   - Cache downloaded animation/controller samples locally
   - Reduce GitHub API calls during generation
   - Fallback gracefully on network error

9. **Support Custom Bone Animations**
   - Allow users to provide pre-existing bone motion patterns
   - Build custom Molang expressions from patterns
   - Example: "leg swings 30 degrees" → math.sin(...) * 57.3 * 0.5

10. **Animation Preview**
    - Export animation JSON with test rig
    - Allow user to preview animation before build
    - Requires Bedrock preview infrastructure

