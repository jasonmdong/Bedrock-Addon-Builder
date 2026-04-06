# MCP-Augmented LLM Pipeline — Implementation Session Report

**Date:** March 3, 2026  
**Duration:** Full session (~4+ hours)  
**Outcome:** MCP context retrieval working end-to-end; validation deferred  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [What Was Built](#3-what-was-built)
4. [Architecture — Before vs After](#4-architecture--before-vs-after)
5. [New Files Created](#5-new-files-created)
6. [Files Modified](#6-files-modified)
7. [Technical Deep-Dive: MCP Context Retrieval](#7-technical-deep-dive-mcp-context-retrieval)
8. [Technical Deep-Dive: Session Management & Reliability](#8-technical-deep-dive-session-management--reliability)
9. [Technical Deep-Dive: Post-Generation Validation](#9-technical-deep-dive-post-generation-validation)
10. [Issues Encountered & Resolutions](#10-issues-encountered--resolutions)
11. [What Was Dropped & Why](#11-what-was-dropped--why)
12. [Current State & Performance](#12-current-state--performance)
13. [Remaining Work](#13-remaining-work)

---

## 1. Executive Summary

Before this session, the Bedrock Addon Builder had two fully separate systems: an **LLM pipeline** (OpenAI/DeepSeek/Gemini/Claude/Ollama) that generated Minecraft Bedrock specs from natural language, and an **MCP integration** (Mojang's Minecraft Creator Tools) that sat in a sidebar UI but was never touched by the LLM. The LLM worked entirely from static prompts — it had no access to Mojang's authoritative schemas or model templates.

After this session, every LLM request now:
1. **Retrieves dynamic context** from MCP tools (`getModelTemplates`) based on the user's prompt
2. **Injects that context** into the LLM system prompt as authoritative reference material
3. **Reports MCP augmentation status** to the frontend (sources used, retrieval time)
4. **Degrades gracefully** if MCP is unavailable — falls back silently to static prompts

The result: LLM responses are now grounded in real Bedrock geometry templates from Mojang's tools, retrieved in ~500ms with caching, rather than hallucinating structures from training data alone.

---

## 2. Problem Statement

### What was wrong

The MCP integration existed purely as a UI sidebar feature — users could manually click "Validate" or "Load Template" buttons, but the LLM pipeline was completely unaware of MCP. When a user typed "make a spider mob," the LLM had to invent geometry coordinates from scratch, with no reference to Mojang's actual model structures.

### What we wanted

A **Retrieval-Augmented Generation (RAG)** pattern where:
- The user's prompt is analyzed to determine what MCP context would be helpful
- Relevant schemas and templates are fetched from MCP in parallel
- That context is injected into the LLM's system prompt as authoritative reference
- After generation, MCP validates the output and feeds errors back for a retry if needed
- All of this happens transparently — the user just types a prompt and gets a better result

---

## 3. What Was Built

### New Module: `backend/llm/mcp_context.py` (472 lines)

The core retrieval and validation layer. Contains:

| Component | Purpose |
|-----------|---------|
| `MCPContext` dataclass | Holds retrieved schema text, template text, source tools, timing, availability |
| `MCPValidationResult` dataclass | Holds validation results (valid/errors/raw content/availability) |
| `retrieve_context()` | Async entry point — runs schema + template fetches in parallel via `asyncio.gather` |
| `retrieve_context_sync()` | Sync wrapper using `ThreadPoolExecutor` + `asyncio.run` for the sync LLM functions |
| `mcp_validate()` / `mcp_validate_sync()` | Post-generation validation (currently disabled — see section 9) |
| `_fetch_schema_cached()` | Schema retrieval with TTL-based caching (10min positive, 2min negative) |
| `_fetch_templates()` | Template retrieval from `getModelTemplates` with keyword-based type detection |
| `_detect_template_type()` | Maps prompt keywords to one of 32 valid MCP template types |
| Circuit breaker | Auto-disables MCP after 2 consecutive failures, 5-minute cooldown |
| `TEMPLATE_KEYWORDS` | Mapping of 19 template types to ~80+ keywords for prompt matching |
| `_CATEGORY_DEFAULT_TEMPLATE` | Fallback template type per app category when no keyword matches |

### Modified: `backend/llm/llm.py`

Wired MCP into the existing LLM pipeline:

| Change | Location | Description |
|--------|----------|-------------|
| Import `mcp_context` | Top of file | Imports `MCPContext`, `MCPValidationResult`, `retrieve_context_sync`, `mcp_validate_sync`, `is_retryable` |
| `_get_full_system_prompt()` | Lines 32–79 | Now accepts optional `mcp_context` parameter; injects MCP schema and template text into the system prompt with labeled sections |
| All `_call_*()` functions | Throughout | Every provider function now accepts and passes through `mcp_context` |
| `llm_rewrite_spec()` | Lines 324–428 | New 4-step pipeline: (1) MCP context retrieval, (2) LLM call with enriched prompt, (3) MCP post-validation, (4) retry on errors. Attaches `_mcp_meta` to output spec. |
| `_get_geometry_system_prompt()` | Lines 482–490 | Accepts MCP template text and injects it into the geometry system prompt |
| `_fetch_geometry_template_sync()` | Lines 493–511 | Fetches MCP template for geometry generation using the same `_detect_template_type` logic |
| `llm_generate_geometry()` | Lines 514–557 | Uses MCP templates as starting points when no current geometry exists |

### Modified: `backend/mctools/client.py`

Major reliability improvements to session management:

| Change | Description |
|--------|-------------|
| `timeout` parameter on `_mcp_post()` and `call_tool()` | Per-call timeout override (was hardcoded to global 30s) |
| `_session_lock` + `_get_session_lock()` | `asyncio.Lock` to serialize session initialization, preventing race conditions |
| `_ensure_session()` rewrite | Acquires lock, double-checks `_session_id`, probes server reachability, delegates to `_do_initialize()` |
| `_is_server_reachable()` | Quick HTTP probe to check if something is listening on port 6126 |
| `_do_initialize()` | Full MCP handshake with stale-session recovery: detects "already initialized" errors, kills orphaned processes, waits for port release, restarts server |
| `_find_pid_on_port()` | Cross-platform (Windows `netstat -ano` / Linux `lsof`) PID lookup for port 6126 |
| `_kill_port_holder()` | Kills tracked subprocess + any orphaned processes holding the port (Windows: `taskkill /F /T`) |
| `_wait_port_free()` | Polls up to 10s for port 6126 to be released after a process kill |

### Modified: `backend/core/routes.py`

- Extracts `_mcp_meta` from LLM output spec before saving
- Passes MCP metadata to the frontend response under the `mcp` key

### Modified: `backend/core/app.py`

- Moved `load_dotenv()` to the very top of the file (before any imports) with `override=True`
- Registered new routes: `mctools_diagnose`
- Added shutdown hook for `stop_mctools_server()`

### New Module: `backend/llm/category_context.py` (458 lines)

Category-specific static context for LLM prompts. Contains:
- 5 categories with full structural examples and rules: `entity_logic_ai`, `items_weaponry`, `blocks_furniture`, `loot_recipes`, `scripting_components`
- `CATEGORY_SCHEMAS` — JSON schemas loaded from disk per category
- `VANILLA_REF` — vanilla entity component reference data
- `detect_category()` — auto-detects content type from spec structure

### Modified: Frontend (`frontend/js/llm.js`)

- `_buildProgressSteps()` — shows "Retrieving MCP context..." step during LLM requests when MCP is available
- `_formatMcpStatus()` — formats MCP augmentation info (sources, timing, validation status) for the status bar
- `_renderMcpBadge()` — renders an italic detail badge below the status area showing MCP context sources, retrieval time, and validation results

### Modified: Frontend (`frontend/js/mctools.js`)

- `mctoolsAvailable` global variable exposed for the LLM module to check
- Health check runs on load and every 30 seconds

---

## 4. Architecture — Before vs After

### Before (Disconnected)

```
User prompt → static system prompt → LLM → validate_spec() → return
                                             (Python-only checks)

MCP tools: separate sidebar UI, never touched by LLM pipeline
```

### After (MCP-Augmented)

```
User prompt
    │
    ├─ detect category from spec
    │
    ▼
┌─────────────────────────────────────┐
│ Step 1: MCP Context Retrieval       │
│  ├─ _fetch_schema_cached(category)  │  (placeholder — uses static schemas)
│  └─ _fetch_templates(prompt, cat)   │  (calls getModelTemplates via MCP)
│  Both run in parallel via gather    │
│  10s hard timeout, circuit breaker  │
│  TTL cache: 10min success, 2min fail│
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ Step 2: Build Enriched Prompt       │
│  1. Base LLM_SYSTEM_PROMPT          │
│  2. MCP authoritative schema (if any)│
│  3. Category context (static)       │
│  4. MCP model templates (dynamic)   │
│  5. Mob spec schema                 │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ Step 3: LLM Call                    │
│  (OpenAI / DeepSeek / Gemini / etc.)│
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ Step 4: Post-Validation (advisory)  │
│  • validate_spec() (Python)         │
│  • mcp_validate() — DISABLED for now│
│    (spec format mismatch — see §9)  │
└─────────────────────────────────────┘
    │
    ▼
Return spec + _mcp_meta → frontend shows augmentation badge
```

---

## 5. New Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `backend/llm/mcp_context.py` | 472 | MCP context retrieval, caching, circuit breaker, validation |
| `backend/llm/category_context.py` | 458 | Category-specific static context, schemas, vanilla references |
| `backend/mctools/__init__.py` | 0 | Package init (empty) |
| `backend/mctools/client.py` | 490 | MCP client with session management (existed before, heavily modified) |
| `backend/mctools/routes.py` | 280 | 14+ FastAPI route handlers for MCP tools |
| `frontend/js/mctools.js` | 201 | Frontend MCP health, validation, template UI |
| `docs/MCP_AUGMENTED_LLM_PLAN.md` | 545 | Original MDD plan document (6 phases) |
| `docs/MCP_INTEGRATION.md` | 301 | MCP protocol and integration technical docs |

---

## 6. Files Modified

| File | Nature of Changes |
|------|-------------------|
| `backend/llm/llm.py` | Wired MCP context into all 6 provider functions, system prompt builder, geometry pipeline; added `_mcp_meta` metadata attachment |
| `backend/core/app.py` | Moved `load_dotenv` to top with `override=True`, registered MCP routes and diagnose endpoint, added shutdown hook |
| `backend/core/routes.py` | Extract `_mcp_meta` from LLM output, pass to frontend response |
| `frontend/js/llm.js` | Progress steps show MCP status, MCP badge rendering, status formatting |
| `frontend/index.html` | Added MCP section UI, script tag for `mctools.js` |
| `run.py` | Fixed stray `+` syntax error |
| `.env.example` | Added MCP-related environment variables |
| `.gitignore` | Added MCP-related ignores |

---

## 7. Technical Deep-Dive: MCP Context Retrieval

### How `getModelTemplates` is used

When a user sends a prompt like "make a spider mob," the system:

1. **Detects the template type** via `_detect_template_type()`:
   - Scans the prompt against `TEMPLATE_KEYWORDS` — a mapping of 19 template types to ~80+ keywords
   - "spider" matches `large_animal` (via keyword list: cow, horse, wolf, bear, lion, tiger, spider)
   - If no keyword matches, falls back to `_CATEGORY_DEFAULT_TEMPLATE[category]` (e.g., `humanoid` for entities)

2. **Checks the cache** in `_template_cache`:
   - Keyed by template type string (e.g., `"large_animal"`)
   - Positive cache TTL: 600 seconds (10 minutes)
   - Negative cache TTL: 120 seconds (2 minutes) — failures are cached to avoid hammering MCP

3. **Calls MCP** via `call_tool("getModelTemplates", {"templateType": "large_animal"}, timeout=8.0)`:
   - 8-second per-tool timeout (vs the global 30s default)
   - Returns geometry JSON for a large quadruped animal model

4. **Truncates** to 4000 chars max (`MAX_MCP_TEMPLATE_CHARS`) to protect the LLM token budget

5. **Returns** as part of `MCPContext.template_text`

### The 32 valid template types

MCP's `getModelTemplates` accepts these types (discovered through testing):

```
humanoid, small_animal, large_animal, vehicle, bird, insect, flying, fish,
slime, wizard, golem, fox, crystal, enchanted_sword, tropical_fish, ghost,
robot, mushroom_creature, treasure_chest, block, stone_brick, wooden_crate,
glowing_ore, mossy_stone, crystal_block, tech_block, item, potion_bottle,
magic_wand, ornate_key, gemstone, apple, pickaxe
```

We map 19 of these via `TEMPLATE_KEYWORDS` and have per-category defaults for the rest.

### Prompt injection placement

The retrieved template is injected into the system prompt in a specific order designed for LLM attention (primacy/recency effect):

```
1. Base LLM_SYSTEM_PROMPT      — identity and critical rules (primacy)
2. MCP authoritative schema     — what's valid (high attention)
3. Category context             — examples and structure (middle)
4. MCP model templates          — starting geometry (recency boost)
5. Mob spec JSON schema         — field definitions (recency)
```

Each MCP section is wrapped with clear labels:

```
--- MODEL TEMPLATES (from Minecraft Creator Tools) ---
Use these as starting points when creating or modifying geometry:
<template JSON here>
--- END TEMPLATES ---
```

### The async-sync bridge problem

The LLM provider functions (`_call_openai`, `_call_deepseek`, etc.) are all **synchronous**, but MCP calls are **async** (using `httpx.AsyncClient`). This is a classic problem in FastAPI where route handlers are async but some business logic is sync.

Solution in `retrieve_context_sync()`:
```python
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    future = pool.submit(asyncio.run, retrieve_context(prompt, category, current_spec))
    return future.result(timeout=MCP_RETRIEVAL_TIMEOUT + 3)
```

This spawns a new thread with its own event loop to run the async MCP calls, then blocks the calling thread for at most `timeout` seconds. The `+3` buffer accounts for thread startup overhead.

---

## 8. Technical Deep-Dive: Session Management & Reliability

### The single-session problem

The `mctools-int` MCP server only supports **one active session** at a time. If the FastAPI app restarts (common during development with `--reload`), the Node.js subprocess may still be running with a stale session. The next `initialize` request gets:

```json
{"jsonrpc":"2.0","error":{"code":-32600,"message":"Invalid Request: Server already initialized"},"id":null}
```

### The race condition

Multiple concurrent callers (health check, template fetch, validation) would all see `_session_id is None` and simultaneously try to initialize. This caused:
- Multiple processes trying to kill port 6126
- Multiple processes trying to start new servers
- `EADDRINUSE` errors from port conflicts

### The solution: `asyncio.Lock` + aggressive process recycling

```python
_session_lock: Optional[asyncio.Lock] = None

async def _ensure_session() -> str:
    global _session_id
    if _session_id:
        return _session_id

    async with _get_session_lock():
        if _session_id:      # double-check after acquiring lock
            return _session_id

        if not await _is_server_reachable():
            await _start_mctools_server()

        _session_id = await _do_initialize()
        return _session_id
```

The lock serializes all session initialization. Only one caller does the expensive work; others wait and then reuse the result.

### `_do_initialize()` — the full recovery sequence

When the server has a stale session:

1. Send `initialize` handshake
2. Get `400 "Server already initialized"` response
3. Call `_kill_port_holder()`:
   - Kill our tracked subprocess via `_mctools_process.kill()`
   - Find any process on port 6126 via `netstat -ano` (Windows) or `lsof` (Linux)
   - Force-kill with `taskkill /PID <pid> /F /T` (the `/T` flag kills child processes too)
4. Call `_wait_port_free()`:
   - Poll every 500ms for up to 10 seconds
   - Verify port 6126 has no LISTENING processes
5. Call `_start_mctools_server()`:
   - Spawn new Node.js subprocess
   - Wait up to 30s for it to become reachable
6. Retry the `initialize` handshake on the fresh server

### Why `/T` matters on Windows

Without `/T`, `taskkill` only kills the parent process. The Node.js mctools server spawns child worker processes that can hold the port even after the parent is killed. The `/T` flag terminates the entire process tree.

---

## 9. Technical Deep-Dive: Post-Generation Validation

### What was planned

After the LLM generates a spec, send it to MCP's `validateContent` tool. If validation finds structural errors (missing required fields, type mismatches), feed those errors back to the LLM for one retry attempt.

### What actually happened

The `validateContent` tool was timing out at 15 seconds on every call. Investigation revealed a fundamental **format mismatch**:

| What we send | What `validateContent` expects |
|---|---|
| Our internal app spec format: `{ "identifier": "custom:mob", "hp": 20, "damage": 5, "speed": 0.25, "components": {...} }` | Real Bedrock entity JSON: `{ "format_version": "1.21.0", "minecraft:entity": { "description": {...}, "components": {...} } }` |

Our app uses a simplified internal spec format that gets converted to real Bedrock JSON only during the build step (in `builders.py`). The LLM pipeline operates entirely on this internal format. Sending it to `validateContent` was asking the tool to parse something completely different from what it expects, causing it to churn for 15+ seconds and then time out.

### Resolution

Validation was disabled (both `mcp_validate()` and `mcp_validate_sync()` now return `MCPValidationResult(valid=True, available=False)` immediately). This is the correct decision because:

1. **It was purely advisory** — even when it timed out, the spec was still returned to the user
2. **It was adding 15+ seconds of latency** to every LLM request for zero benefit
3. **The circuit breaker was triggering** after 2 failures, which disabled MCP validation for 5 minutes anyway
4. **To enable it properly**, we'd need to run the spec through `builders.py` to produce real Bedrock entity JSON first, then validate that — a significant refactor

The `_extract_errors()` and `is_retryable()` functions are preserved for when validation is re-enabled.

### Validation false positives (earlier issue)

Even when `validateContent` did return results (in testing with properly formatted Bedrock JSON), the error parser had false positives. Lines like `"invalidCommandSyntaxCount": 0` were flagged as errors because they contained the word "invalid." Fixed by adding filters:

```python
if ": 0" in line_stripped or '": 0' in line_stripped:
    continue  # skip zero-count stat lines
```

---

## 10. Issues Encountered & Resolutions

### Issue 1: `MCTOOLS_ENABLED` reading as `false` despite `.env` setting

**Symptom:** Server logs showed `MCTOOLS_ENABLED: False` even with `MCTOOLS_ENABLED=true` in `.env`.

**Root cause:** `load_dotenv()` was called in the middle of imports, and by default uses `override=False`. When Uvicorn's `--reload` mode spawns a child process, the parent's environment may contain stale values. The child process inherits the parent's env, and `load_dotenv(override=False)` refuses to overwrite it.

**Fix:** Moved `load_dotenv()` to the absolute first line of `backend/core/app.py` (before any imports that read env vars) and set `override=True`:

```python
try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parents[2] / ".env"
    if _env.exists():
        load_dotenv(_env, override=True)
except ImportError:
    pass
```

### Issue 2: `SyntaxError: invalid syntax` in `run.py`

**Symptom:** File watcher restart failed with a syntax error.

**Root cause:** A stray `+` character on line 30 of `run.py` (likely from a copy-paste error).

**Fix:** Removed the `+`.

### Issue 3: Port 6126 `EADDRINUSE` / `WinError 10048`

**Symptom:** After killing the mctools server, the new server couldn't bind to port 6126.

**Root cause:** Windows doesn't release TCP ports instantly after a process is killed. The OS holds them in `TIME_WAIT` state. Also, child processes of the Node.js server could still be holding the port.

**Fix:** Implemented `_wait_port_free()` that polls every 500ms for up to 10 seconds, plus `_kill_port_holder()` with `/T` flag to kill the entire process tree.

### Issue 4: Concurrent session initialization race condition

**Symptom:** Multiple "Server already initialized" errors in rapid succession. Multiple concurrent callers all trying to kill and restart the server simultaneously.

**Root cause:** Three concurrent async callers (health check polling, template fetch, and validation) all saw `_session_id is None` at the same time and raced to initialize.

**Fix:** Added `asyncio.Lock` to `_ensure_session()`. Only one caller performs the initialization; others wait for the lock and then reuse the established session.

### Issue 5: `getEffectiveContentSchema` returning empty results

**Symptom:** The `getEffectiveContentSchema` MCP tool reported success but returned empty or useless data.

**Root cause:** This tool requires a populated Minecraft project folder with actual content files to analyze. The `createProject` MCP tool, despite reporting success, didn't actually write files to disk. So schema analysis always got an empty directory.

**Fix:** Abandoned `getEffectiveContentSchema` integration entirely. The system relies on:
- Static schemas loaded from `backend/schemas/` (local files)
- `getModelTemplates` for dynamic geometry context (works perfectly, no project needed)

### Issue 6: `validateContent` 15-second timeouts

**Symptom:** `[mcp_context] MCP validation failed: MCP tool call 'validateContent' timed out after 15.0s` on every LLM request.

**Root cause:** Sending our internal app spec format to a tool that expects real Bedrock entity JSON. The tool spent 15 seconds trying to parse an unrecognized format before giving up.

**Fix:** Disabled validation entirely (see section 9). The spec format mismatch is fundamental — can't be fixed with a timeout increase.

### Issue 7: `UnicodeEncodeError` in PowerShell

**Symptom:** `UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'` when running Python scripts.

**Root cause:** PowerShell's default encoding doesn't support Unicode arrows used in log messages.

**Fix:** Set `$env:PYTHONUTF8='1'` in the shell before running Python.

### Issue 8: `ModuleNotFoundError: No module named 'backend'`

**Symptom:** Running test scripts directly with `python scripts/test_mcp_context.py` failed.

**Fix:** Run as module: `python -m backend.tests.test_mcp_context`.

---

## 11. What Was Dropped & Why

| Feature | Reason |
|---------|--------|
| `getEffectiveContentSchema` integration | Tool requires a populated project directory; `createProject` doesn't actually write files. Impractical without a pre-built reference project. Static local schemas are sufficient. |
| MCP post-generation validation | Our internal spec format doesn't match what `validateContent` expects. Would need to run specs through `builders.py` first — significant refactor. |
| `designModel` direct integration | Planned in Phase 4 of the MDD plan but deferred. `getModelTemplates` provides sufficient starting points. `designModel` is complex (requires `projectPath`, `design` JSON, `modelId`) and harder to integrate transparently. |
| Reference project management | Scripts to create/maintain a fake Minecraft project for `getEffectiveContentSchema` — abandoned with that tool. |
| Several diagnostic scripts | `scripts/diagnose_mcp.py`, `scripts/test_mcp_enums.py`, `scripts/test_mcp_tools.py`, `scripts/test_mcp_meta.py`, `scripts/test_llm_with_mcp.py` — all deleted after debugging was complete. |

---

## 12. Current State & Performance

### What's working

| Feature | Status | Typical Latency |
|---------|--------|-----------------|
| MCP server auto-start | Working | ~5-10s first time |
| Session initialization | Working (with lock) | ~1-2s first time |
| `getModelTemplates` context retrieval | Working | ~500ms (573ms, 477ms observed) |
| Template caching (10min TTL) | Working | <1ms on cache hit |
| Negative caching (2min TTL) | Working | <1ms on cache hit |
| Circuit breaker (2 failures → 5min cooldown) | Working | N/A |
| Prompt injection with MCP templates | Working | No additional latency |
| Frontend MCP status badge | Working | Real-time |
| Frontend progress steps | Working | Shows "Retrieving MCP context..." |
| Graceful degradation when MCP unavailable | Working | No latency impact |
| Health check endpoint | Working | Polls every 30s |
| Diagnostic endpoint (`/api/mctools/diagnose`) | Working | Tests all tools |

### Server log output for a typical LLM request

```
[LLM] provider=openai category=entity_logic_ai prompt_len=25
[LLM] category=entity_logic_ai
[mcp_context] Retrieved context in 477ms (sources=['getModelTemplates'], schema=0 chars)
[LLM] MCP context retrieved in 477ms (sources=['getModelTemplates'])
[LLM] calling OpenAI model openai/gpt-4.1
[LLM] System prompt built for category=entity_logic_ai (context=yes, schema=yes, mcp_sources=['getModelTemplates'])
```

### Frontend response metadata

```json
{
  "spec": { ... },
  "mcp": {
    "augmented": true,
    "context_sources": ["getModelTemplates"],
    "retrieval_ms": 477,
    "validation": {
      "ran": false,
      "valid": true,
      "messages": []
    }
  }
}
```

---

## 13. Remaining Work

### High priority

| Task | Description | Effort |
|------|-------------|--------|
| Enable real validation | Run specs through `builders.py` to produce Bedrock JSON, then send to `validateContent` | Medium |
| Test with all providers | Verify MCP augmentation works with DeepSeek, Gemini, Claude, Ollama (only OpenAI tested) | Small |

### Medium priority

| Task | Description | Effort |
|------|-------------|--------|
| `designModel` integration | For geometry requests, try MCP's `designModel` before falling back to LLM | Medium |
| Schema retrieval | Find a way to get useful schema data from MCP (possibly via `getEffectiveContentSchema` with a pre-built reference project) | Medium |
| Golden test comparison | Run golden tests with/without MCP augmentation to measure score improvement | Small |

### Low priority

| Task | Description | Effort |
|------|-------------|--------|
| Expand template keyword coverage | Add more keywords to `TEMPLATE_KEYWORDS` for better template type detection | Small |
| MCP context for non-entity categories | Investigate which MCP tools are useful for items, blocks, loot tables, scripting | Medium |
| Automated MCP health recovery | If MCP server crashes mid-session, auto-restart without requiring next request to fail first | Small |
