# MCP-Augmented LLM Pipeline — Development Plan

**Date:** March 3, 2026  
**Status:** Implemented (all 6 phases complete)  
**Goal:** Wire MCP tools into the LLM pipeline so every prompt automatically retrieves the most relevant context before generation, and validates the output after.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Phase 1 — MCP Context Retriever Module](#2-phase-1--mcp-context-retriever-module)
3. [Phase 2 — Inject MCP Context into LLM System Prompt](#3-phase-2--inject-mcp-context-into-llm-system-prompt)
4. [Phase 3 — Post-Generation MCP Validation](#4-phase-3--post-generation-mcp-validation)
5. [Phase 4 — Geometry Pipeline (Templates + designModel)](#5-phase-4--geometry-pipeline-templates--designmodel)
6. [Phase 5 — Frontend Status & Transparency](#6-phase-5--frontend-status--transparency)
7. [Phase 6 — Testing & Fallback Safety](#7-phase-6--testing--fallback-safety)

---

## 1. Architecture Overview

### Current Flow (Disconnected)
```
User prompt → static system prompt → LLM → validate_spec() → return
                                              (our own Python check)

MCP tools sit in a separate sidebar, never touched by the LLM pipeline.
```

### Target Flow (MCP-Augmented)
```
User prompt
    │
    ▼
┌──────────────────────────────┐
│  STEP 1: Analyze & Retrieve  │  (new module: mcp_context.py)
│  • detect category from spec │
│  • call MCP tools in parallel│
│    - getEffectiveContentSchema│
│    - getModelTemplates        │
│  • format retrieved context   │
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│  STEP 2: Build Rich Prompt   │  (enhanced _get_full_system_prompt)
│  • base system prompt         │
│  • + category context (existing)
│  • + MCP schema (dynamic)     │  ← NEW
│  • + MCP templates (dynamic)  │  ← NEW
│  • + user prompt + spec       │
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│  STEP 3: LLM Call            │  (existing, unchanged)
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│  STEP 4: Post-Validate       │  (new: MCP validateContent)
│  • run our validate_spec()   │
│  • run MCP validateContent() │  ← NEW
│  • if MCP finds issues:       │
│    → retry LLM with errors   │  ← NEW (1 retry max)
└──────────────────────────────┘
    │
    ▼
Return validated spec + metadata to frontend
```

### Files Touched

| File | Change Type | Description |
|------|-------------|-------------|
| `backend/llm/mcp_context.py` | **NEW** | MCP context retrieval & caching module |
| `backend/llm/llm.py` | MODIFY | Wire MCP context into prompt building & post-validation |
| `backend/llm/category_context.py` | MODIFY | Add MCP schema merging helpers |
| `backend/mctools/client.py` | MODIFY | Add convenience wrappers for retrieval use cases |
| `frontend/js/llm.js` | MODIFY | Show MCP augmentation status in the response |
| `frontend/js/mctools.js` | MODIFY | Expose health state for LLM module to check |

---

## 2. Phase 1 — MCP Context Retriever Module

> **ROLE PROMPT:** You are a senior Python backend engineer specializing in async service integration. You build clean, fault-tolerant retrieval layers. You think in terms of: "What context does the LLM need to do this task well?" and "What happens if the MCP server is down?" Every function you write has a graceful fallback that returns empty context rather than crashing. You use `asyncio.gather` for parallel calls and cache results aggressively since schemas rarely change.

### Goal
Create `backend/llm/mcp_context.py` — a module that retrieves dynamic context from MCP tools based on the user's prompt and current spec category.

### Functions to Implement

#### `async retrieve_context(prompt: str, category: str, current_spec: dict) -> MCPContext`

Main entry point. Analyzes what the prompt needs and fetches relevant MCP context in parallel.

Returns an `MCPContext` dataclass:
```python
@dataclass
class MCPContext:
    schema_text: str        # from getEffectiveContentSchema (formatted for prompt injection)
    template_text: str      # from getModelTemplates (formatted for prompt injection)
    source_tools: list[str] # which MCP tools were called (for transparency/logging)
    retrieval_ms: int       # how long retrieval took
    available: bool         # was MCP reachable at all?
```

#### `async _fetch_schema(category: str) -> str`

Calls `getEffectiveContentSchema` via `call_tool()`. Maps our category to an MCP-compatible folder/content type. Returns formatted schema text or empty string on failure.

**Cache strategy:** Schema results are cached in-memory keyed by category with a 10-minute TTL (schemas don't change at runtime).

#### `async _fetch_templates(prompt: str, category: str) -> str`

Calls `getModelTemplates` when the prompt or category involves geometry/models. Uses keyword detection on the prompt (e.g., "model", "shape", "geometry", "spider", "humanoid") to decide the template type.

Returns formatted template text or empty string if not relevant.

#### `_should_fetch_templates(prompt: str, category: str) -> bool`

Quick heuristic: returns True if the prompt likely involves 3D models or geometry. Checks for keywords and whether the category is entity-related.

#### `_format_for_prompt(tool_name: str, raw_content: list[dict]) -> str`

Takes raw MCP tool response content (the `content` array of `{type, text}` items) and formats it into a clean text block suitable for system prompt injection.

### Caching Layer

```python
_schema_cache: dict[str, tuple[str, float]] = {}  # category → (text, timestamp)
CACHE_TTL = 600  # 10 minutes

async def _fetch_schema_cached(category: str) -> str:
    now = time.time()
    if category in _schema_cache:
        text, ts = _schema_cache[category]
        if now - ts < CACHE_TTL:
            return text
    text = await _fetch_schema(category)
    _schema_cache[category] = (text, now)
    return text
```

### Fallback Behavior

Every retrieval function catches all exceptions and returns empty string. The LLM pipeline continues with whatever static context it already has. MCP augmentation is **additive, never blocking**.

```python
async def _fetch_schema(category: str) -> str:
    try:
        result = await call_tool("getEffectiveContentSchema", {...})
        return _format_for_prompt("getEffectiveContentSchema", result["content"])
    except Exception as e:
        log.warning("[mcp_context] Schema retrieval failed: %s", e)
        return ""
```

---

## 3. Phase 2 — Inject MCP Context into LLM System Prompt

> **ROLE PROMPT:** You are an LLM prompt engineer who has tuned hundreds of production AI systems. You know that prompt structure matters enormously — what goes first, how sections are labeled, how much context is too much. You never dump raw JSON into a prompt without framing it. You always label sections clearly so the LLM knows what's authoritative vs. supplementary. You think about token budgets: MCP schemas can be large, so you truncate intelligently and prioritize the most relevant parts.

### Goal
Modify `_get_full_system_prompt()` in `llm.py` to accept and incorporate MCP-retrieved context.

### Changes to `_get_full_system_prompt()`

Current signature:
```python
def _get_full_system_prompt(category: str = "entity_logic_ai") -> str:
```

New signature:
```python
def _get_full_system_prompt(category: str = "entity_logic_ai", mcp_context: MCPContext | None = None) -> str:
```

### Prompt Assembly Order

The order matters for LLM attention. Most important context goes **first** and **last** (primacy/recency effect):

```
1. Base system prompt (LLM_SYSTEM_PROMPT from core.py)     — WHO you are, CRITICAL RULES
2. MCP authoritative schema (if available)                  — WHAT is valid         ← NEW
3. Category-specific context (existing static examples)     — HOW to structure it
4. MCP model templates (if available, if relevant)          — STARTING POINTS       ← NEW
5. Mob spec schema (existing, for entity category)          — FIELD definitions
```

### Prompt Injection Format

MCP context is injected with clear section headers so the LLM treats it as authoritative:

```python
if mcp_context and mcp_context.schema_text:
    prompt += "\n\n--- AUTHORITATIVE BEDROCK SCHEMA (from Minecraft Creator Tools) ---\n"
    prompt += mcp_context.schema_text
    prompt += "\n--- END SCHEMA ---\n"

if mcp_context and mcp_context.template_text:
    prompt += "\n\n--- MODEL TEMPLATES (from Minecraft Creator Tools) ---\n"
    prompt += "Use these as starting points when creating geometry:\n"
    prompt += mcp_context.template_text
    prompt += "\n--- END TEMPLATES ---\n"
```

### Token Budget Guard

MCP schemas can be verbose. Add a safety truncation:

```python
MAX_MCP_SCHEMA_CHARS = 8000   # ~2000 tokens
MAX_MCP_TEMPLATE_CHARS = 4000 # ~1000 tokens

def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated for token budget]"
```

### Changes to `llm_rewrite_spec()`

The main orchestrator needs to call MCP retrieval before building the prompt. Since MCP calls are async but the LLM provider calls are sync, we need a bridge:

```python
def llm_rewrite_spec(prompt, current, provider, api_key, category="entity_logic_ai") -> dict:
    # NEW: Retrieve MCP context (async → sync bridge)
    mcp_ctx = _get_mcp_context(prompt, category, current)  # uses asyncio.run or event loop
    
    # Existing: route to provider (now passes mcp_ctx)
    if provider_key == "openai":
        output_spec = _call_openai(prompt, current, api_key, category, mcp_context=mcp_ctx)
    # ... etc
```

### Async-Sync Bridge

The LLM functions are sync but MCP client is async. Handle this cleanly:

```python
def _get_mcp_context(prompt: str, category: str, current_spec: dict) -> MCPContext | None:
    """Synchronous wrapper for async MCP context retrieval."""
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context (FastAPI) — use a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, retrieve_context(prompt, category, current_spec)
                ).result(timeout=15)
        else:
            return asyncio.run(retrieve_context(prompt, category, current_spec))
    except Exception as e:
        log.warning("[LLM] MCP context retrieval failed: %s", e)
        return None
```

---

## 4. Phase 3 — Post-Generation MCP Validation

> **ROLE PROMPT:** You are a QA automation engineer who builds validation pipelines. You believe in defense in depth: if one validator misses something, the next one catches it. You design retry loops that are bounded (max 1 retry) and informative (feed specific errors back, not generic "try again"). You never let a validation step crash the pipeline — if MCP validation is unavailable, the existing `validate_spec()` result is good enough.

### Goal
After the LLM generates a spec, validate it against MCP's `validateContent` tool. If validation fails, feed the errors back to the LLM for one retry attempt.

### New Function: `async mcp_validate(spec: dict) -> MCPValidationResult`

```python
@dataclass
class MCPValidationResult:
    valid: bool
    errors: list[str]      # human-readable error messages
    raw_content: list[dict] # raw MCP response content
    available: bool         # was MCP reachable?
```

Calls `validateContent` with the JSON-serialized spec. Parses the response content for error messages.

### Integration Point in `llm_rewrite_spec()`

```python
def llm_rewrite_spec(...) -> dict:
    # ... existing LLM call ...
    output_spec = _call_provider(...)
    
    # Existing: Python validation
    if category == "entity_logic_ai":
        output_spec = validate_spec(output_spec)
    
    # NEW: MCP validation (non-blocking)
    mcp_result = _run_mcp_validation(output_spec)
    
    if mcp_result and not mcp_result.valid and not mcp_result.errors_are_cosmetic:
        # ONE retry: feed errors back to LLM
        retry_prompt = (
            f"Original instruction: {prompt}\n\n"
            f"Your previous output had these validation errors from Minecraft Creator Tools:\n"
            + "\n".join(f"- {e}" for e in mcp_result.errors) +
            "\n\nPlease fix these issues and return the corrected spec."
        )
        output_spec = _call_provider(retry_prompt, output_spec, ...)
    
    return output_spec
```

### What Counts as a Retry-Worthy Error

Not all MCP validation messages are errors. Some are warnings or informational. Only retry on:
- Missing required fields
- Invalid component structures  
- Type mismatches
- Out-of-range values

Skip retry for:
- Warnings about deprecated fields
- Informational messages
- Cosmetic suggestions

```python
def _is_retryable(errors: list[str]) -> bool:
    """Only retry on structural/schema errors, not cosmetic warnings."""
    error_keywords = ["required", "invalid", "must be", "expected", "not allowed", "missing"]
    return any(
        any(kw in e.lower() for kw in error_keywords)
        for e in errors
    )
```

---

## 5. Phase 4 — Geometry Pipeline (Templates + designModel)

> **ROLE PROMPT:** You are a 3D graphics engineer who works with Minecraft Bedrock geometry formats daily. You know that LLMs are terrible at generating precise 3D coordinates from scratch — they hallucinate bone positions, mess up UV mapping, and create geometry that clips through itself. The right approach is: start from a real template, then modify. You treat MCP's `getModelTemplates` and `designModel` as the ground truth for geometry, and the LLM as the creative director who decides what to modify.

### Goal
When `llm_generate_geometry()` is called, use MCP to provide a real template as a starting point instead of making the LLM hallucinate coordinates.

### Enhanced Flow

```
User: "create a spider mob model"
    │
    ▼
1. Detect template type from prompt:
   "spider" → templateType = "spider" or "quadruped"
    │
    ▼
2. Fetch MCP template:
   getModelTemplates(templateType="quadruped") → real geometry JSON
    │
    ▼
3. Give template to LLM as starting point:
   "Here is a base quadruped template from Minecraft Creator Tools.
    Modify it to match the user's request: 'spider mob model'"
    │
    ▼
4. LLM modifies the template (much easier than creating from scratch)
    │
    ▼
5. Return modified geometry
```

### Template Type Detection

```python
TEMPLATE_KEYWORDS = {
    "humanoid": ["humanoid", "human", "zombie", "skeleton", "villager", "biped", "npc"],
    "quadruped": ["quadruped", "cow", "pig", "sheep", "wolf", "horse", "spider", "animal", "four legs"],
    "bird": ["bird", "chicken", "parrot", "flying", "wings"],
    "fish": ["fish", "salmon", "cod", "aquatic", "swim"],
}

def _detect_template_type(prompt: str) -> str | None:
    prompt_lower = prompt.lower()
    for template_type, keywords in TEMPLATE_KEYWORDS.items():
        if any(kw in prompt_lower for kw in keywords):
            return template_type
    return "humanoid"  # safe default for entity geometry
```

### Changes to `llm_generate_geometry()`

```python
def llm_generate_geometry(prompt, current_geometry, provider, api_key) -> dict:
    # NEW: If no current geometry, try to fetch a template from MCP
    if not current_geometry:
        template_type = _detect_template_type(prompt)
        mcp_template = _fetch_mcp_template(template_type)
        if mcp_template:
            current_geometry = mcp_template
            # Adjust the prompt to be a modification task
            prompt = f"Starting from this base template, modify it to: {prompt}"
    
    # ... existing LLM call with current_geometry as context ...
```

### Optional: Use `designModel` for Complex Requests

For prompts that describe entirely new models (not modifications), consider calling `designModel` directly instead of the LLM:

```python
if _is_full_model_design(prompt) and mcp_available:
    try:
        result = await call_tool("designModel", {
            "projectPath": ".",
            "design": prompt,
            "modelId": f"geometry.{mob_name}",
            "usage": "entity",
        })
        # If MCP returns valid geometry, use it directly
        return _parse_design_model_result(result)
    except Exception:
        pass  # fall back to LLM
```

---

## 6. Phase 5 — Frontend Status & Transparency

> **ROLE PROMPT:** You are a UX engineer who believes AI systems should be transparent about their process. When the system uses MCP tools behind the scenes, the user should see a brief, non-intrusive indicator of what happened — not a wall of debug text, but enough to build trust. Think GitHub Copilot's "Searching for context..." spinner. You keep the UI minimal but informative.

### Goal
Show the user when MCP context was used to augment their LLM request, and what the MCP validation result was.

### Response Payload Enhancement

Current LLM response:
```json
{ "spec": {...}, "saved": false }
```

Enhanced response:
```json
{
  "spec": {...},
  "saved": false,
  "mcp_augmented": true,
  "mcp_context_sources": ["getEffectiveContentSchema", "getModelTemplates"],
  "mcp_retrieval_ms": 320,
  "mcp_validation": {
    "ran": true,
    "valid": true,
    "messages": []
  }
}
```

### Frontend Changes (`frontend/js/llm.js`)

After receiving the LLM response, show a small status line:

```javascript
if (data.mcp_augmented) {
    const sources = data.mcp_context_sources?.join(", ") || "schema";
    appendStatus(`MCP-augmented (${sources}, ${data.mcp_retrieval_ms}ms)`);
}
if (data.mcp_validation?.ran) {
    if (data.mcp_validation.valid) {
        appendStatus("MCP validation: passed");
    } else {
        appendStatus("MCP validation: " + data.mcp_validation.messages.join("; "));
    }
}
```

### Visual Treatment

- Small italic gray text below the LLM response area
- Green checkmark icon if MCP validation passed
- Yellow warning icon if MCP found issues (with expandable details)
- No indicator at all if MCP was unavailable (don't confuse the user)

---

## 7. Phase 6 — Testing & Fallback Safety

> **ROLE PROMPT:** You are a reliability engineer who has been burned by external service dependencies. You test every failure mode: MCP server down, MCP server slow (>5s), MCP returns garbage, MCP session expired mid-retrieval, MCP returns a schema so large it blows the token budget. For each failure mode, you verify the system degrades gracefully to the existing behavior (static prompts, Python validation only). You write tests that mock MCP at the HTTP level.

### Goal
Ensure the MCP-augmented pipeline never makes things *worse* than the current static pipeline.

### Failure Modes to Test

| Scenario | Expected Behavior |
|---|---|
| MCP server not running | `retrieve_context()` returns empty MCPContext, LLM uses static prompts |
| MCP server slow (>10s) | Timeout fires, returns empty MCPContext, LLM proceeds |
| MCP returns invalid JSON | `_format_for_prompt()` returns empty string |
| MCP schema is 50KB+ | Truncated to MAX_MCP_SCHEMA_CHARS |
| MCP session expired mid-call | `call_tool` auto-reinitializes (existing behavior) |
| MCP validation disagrees with validate_spec() | Our `validate_spec()` is authoritative; MCP is advisory |
| MCP validation says invalid but retry also fails | Return the original LLM output (don't make it worse) |
| `MCTOOLS_ENABLED=false` | All MCP retrieval returns empty, zero overhead |

### Test File: `tests/test_mcp_context.py`

```python
# Mock call_tool to return known responses
# Verify retrieve_context produces correct MCPContext
# Verify _get_full_system_prompt includes MCP sections when available
# Verify _get_full_system_prompt works identically when MCP unavailable
# Verify post-validation retry happens exactly once
# Verify truncation at token budget limits
```

### Integration Test

Run the existing golden tests with MCP augmentation enabled and verify scores don't regress:

```bash
python backend/run_golden_tests.py --provider mock --mcp-augment
```

---

## Implementation Order

| Step | Phase | Est. Effort | Dependencies |
|------|-------|-------------|--------------|
| 1 | Phase 1: `mcp_context.py` module | Medium | None |
| 2 | Phase 2: Prompt injection | Medium | Phase 1 |
| 3 | Phase 3: Post-validation | Medium | Phase 1 |
| 4 | Phase 4: Geometry templates | Small | Phase 1 |
| 5 | Phase 5: Frontend status | Small | Phases 2-3 |
| 6 | Phase 6: Tests & fallback | Medium | Phases 1-4 |

Phases 2 and 3 can be developed in parallel once Phase 1 is done.
Phase 4 is independent and can be done alongside Phase 2/3.

---

## Success Criteria

1. **When MCP is available:** LLM receives real Bedrock schemas and templates in its prompt. Output is validated by MCP before returning. User sees "MCP-augmented" indicator.
2. **When MCP is unavailable:** Behavior is identical to today. No errors, no slowdowns, no degradation.
3. **Golden test scores:** Equal or better than current scores across all providers.
4. **Latency budget:** MCP retrieval adds <2s to the LLM call (schemas are cached after first call).
