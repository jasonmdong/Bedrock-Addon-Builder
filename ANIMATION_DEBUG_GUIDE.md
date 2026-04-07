# Animation System Debug Guide

## What You've Already Fixed ✅
1. **Malformed animation JSON** - Detects bones at root level and wraps properly
2. **Animation controllers using wrong IDs** - Now use short names, not full identifiers
3. **Missing entity.json scripts block** - Animations now linked to controller
4. **Animations lost in mcworld export** - Files injected into ZIP after build
5. **JSON extraction from LLM responses** - 4-strategy fallback handles preamble/trailing text
6. **Only 1 animation instead of 3** - System prompt now requires idle/walk/run
7. **Locomotion classification** - Flying/aquatic/bipedal mobs get motion-appropriate states
8. **Validation before storage** - Detects unnamed animations, dangling state references

## How Animations Are Generated (The Flow)
```
1. User creates mob or edits spec
                    ↓
2. LLM calls /api/animation/generate endpoint
                    ↓
3. Extract geometry (bone names, hierarchy)
                    ↓
4. Classify locomotion type (biped/flying/aquatic)
   └─ Asks LLM: "What movement does this mob have?"
   └─ Returns: [idle, walk, run] or [idle, fly] or [idle, swim]
                    ↓
5. Build animation skeletons (pre-populated with bone names)
   └─ All bones set to ["0", "0", "0"] initially
   └─ Placeholders like FILL_IN_X_WALK tell LLM what to fill
                    ↓
6. Call LLM to fill skeleton placeholders with Molang
   └─ LLM writes math expressions for movement
   └─ Strategy: Count limbs, apply cyclical math
                    ↓
7. Validate structure + run MCP validation (with retry loop)
   └─ MCP checks: Valid Molang syntax? No syntax errors?
   └─ If error: feed back to LLM to fix
                    ↓
8. Generate animation controller (state machine)
   └─ Defines idle→walk→run transitions
   └─ Uses query conditions to decide when to play each
                    ↓
9. Write to packs + inject into mcworld
   └─ Files go to resource/behavior packs
   └─ Animations injected last to prevent loss
```

## Common Failure Points (Debug These When Animations Don't Work)

### ❌ Issue: "Animation file never created"
**Check these in order:**
1. Open browser console → look for API errors
2. Check if LLM endpoint is working: `POST /api/animation/generate` returns 200?
3. Check terminal logs: What did LLM return? (paste the raw response)
4. Look at validation errors: `[ANIMATION-GEN]` log lines

**Debug code to add:**
```python
# In backend/llm/animation_generation.py, before LLM call:
print(f"[DEBUG] Request to {provider} with prompt length: {len(prompt)}")
print(f"[DEBUG] Bones: {bones}")
print(f"[DEBUG] Locomotion: {locomotion}")

# After LLM response:
print(f"[DEBUG] Raw LLM response:\n{response_text[:500]}")
```

### ❌ Issue: "Animation created but doesn't play"
**Likely causes (in order of probability):**

1. **Animation controller not linked in entity.json**
   - Check: `entity.json` → `scripts.animate` block exists?
   - Should have: `"animate": ["controller.animation.{mob_name}"]`
   - Location: `resource_packs/{uuid}/entities/` 

2. **State references don't match animation names**
   - Controller references "idle" but animations file has "animation.mob.idle"
   - Should use short names in controller, entity.json maps to full IDs
   - Check: All states in controller.states exist as keys in animation.json

3. **Locomotion type wrong for mob**
   - Flying ghost got walk animation (needs fly)
   - Classification failed, defaulted to biped
   - Look for: `[ANIMATION-GEN] Classified as: ...`

4. **Malformed Molang expressions**
   - Walk has math but leg bones are still "0"
   - LLM generated invalid syntax that MCP didn't catch
   - Check: Animation file → walk/run animations → leg bones have actual math

5. **Geometry bones don't match animation skeleton**
   - Animation references "leg_back_left" but geometry has "back_leg"
   - Skeleton was built from wrong geometry
   - Check: LLM output shows which bones it used

### ❌ Issue: "Only 1 animation plays (stuck in idle)"
**Root cause:** Walk/run states missing or controller transition broken
1. Check controller.json → `states` dict has idle, walk, run keys
2. Check animation.json → has animations for each state
3. Look for logs: `[ANIMATION-GEN] controller_dict states: ...`

### ❌ Issue: "Legs aren't moving in walk/run"
**Most common:** LLM set leg bones to ["0", "0", "0"]
1. Open animation.json → walk animation
2. Find leg bones → check if they have Molang math
3. Should look like: `"leg_back_left": ["query.modified_distance_moved * 38.17", "0", "0"]`
4. If they're "0": LLM didn't follow guidance

**How to fix in prompt:**
System message already has enhanced guidance. But if still failing, consider:
- Force LLM to write specific Molang: `query.modified_distance_moved * 45.0`
- Reduce degrees of freedom: Only motion on X-axis (forward/back)
- Example in system prompt: Show exact walk animation with math

## Current Critical Gaps (Not Yet Addressed)

| Gap | Impact | Effort to Fix |
|-----|--------|---------------|
| **No golden test cases for animations** | Can't measure quality or compare LLM providers | Medium (1-2 hrs) |
| **No Molang syntax validation** | Invalid expressions slip through | Medium (3-4 hrs) |
| **Hardcoded format_version 1.8.0** | Minecraft 1.20+ uses 1.20.0, may cause compat issues | Low (15 min) |
| **Animation sync validation only warns** | Build succeeds with broken animations | Low (30 min) |
| **No integration tests** | Can't verify API endpoints work end-to-end | Medium (2-3 hrs) |

## Files Organized by Purpose

### Animation Generation (Core Logic)
- `backend/llm/animation_generation.py` — Main engine
  - `llm_generate_animation()` — Orchestrates whole flow
  - `_classify_locomotion()` — Asks LLM what type of movement
  - `_get_animation_skeleton()` — Creates template with bones pre-filled
  - `_normalize_animation_json()` — Fixes malformed LLM output
  - `validate_animation_format()` — Checks structure before storing

### Animation Controllers (State Machines)
- `backend/llm/animation_controllers_generation.py` — Controller generation
  - `generate_animation_controller()` — Creates idle→walk→run transitions
  - `_build_controller_states()` — Defines state logic

### File Writing & Packing
- `backend/core/builders.py` — Writes animations to pack files
  - `patch_behavior_pack()` — Writes animation.json, animation_controllers.json to packs
- `backend/core/packaging.py` — Handles mcworld/mcaddon export
  - `create_mcworld()` — Injects animation files into final ZIP

### API Endpoints
- `backend/core/routes.py` 
  - `POST /api/animation/generate` — Main animation generation endpoint
  - `POST /api/animation/controller/generate` — Controller generation

### Testing
- `test_animation_validation.py` — 9 unit tests (all passing)
- `test_json_extraction.py` — JSON parsing tests
- `backend/llm/llm_scoring.py` — Golden test cases (0 animation tests)

## Quick Debugging Checklist

When animations break:
- [ ] Check browser console for API errors
- [ ] Look for `[ANIMATION-GEN]` logs in terminal
- [ ] Verify LLM returned valid JSON (not just text)
- [ ] Check if entity.json has scripts.animate block
- [ ] Verify animation state names match controller references
- [ ] Look for MCP validation errors (scroll terminal up)
- [ ] If legs static: Check walk/run Molang has math, not "0"
- [ ] If stuck in idle: Check if controller.json states has walk/run
- [ ] If geometry mismatch: Re-check which geometry was used

## Next Steps to Improve Robustness

**Priority 1 (Quick wins):**
1. Add golden test cases for animations (5 test cases)
2. Add Molang syntax validation (simple regex patterns)
3. Update format_version to 1.20.0

**Priority 2 (Prevent future issues):**
1. Add integration tests for animation API endpoints
2. Expose sync validation severity in API response
3. Add telemetry: log which step fails most often

**Priority 3 (Advance features):**
1. Support custom animation names (not just idle/walk/run)
2. Add animation blending for complex locomotion
3. Preview animations in web UI before building
