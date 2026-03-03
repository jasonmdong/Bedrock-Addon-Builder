# Dynamic Category Context Injection — Technical Documentation

**Date:** March 3, 2026
**Status:** v1.0 — Implemented

---

## Table of Contents

1. [Overview](#1-overview)
2. [The Problem: Static Prompts](#2-the-problem-static-prompts)
3. [The Solution: Dynamic Category Context](#3-the-solution-dynamic-category-context)
4. [Architecture](#4-architecture)
5. [How It Works End-to-End](#5-how-it-works-end-to-end)
6. [Category Reference](#6-category-reference)
7. [Hybrid Detection](#7-hybrid-detection)
8. [Files Changed](#8-files-changed)
9. [Adding a New Category](#9-adding-a-new-category)
10. [Configuration & Storage](#10-configuration--storage)

---

## 1. Overview

The LLM pipeline now **dynamically selects which context, examples, and schema** to inject into the system prompt based on the content category the user is working on. Instead of always sending entity/mob-specific context, the system sends category-appropriate reference material — items get item examples, blocks get block examples, loot tables get loot table structure, etc.

This replaces the previous static approach where every LLM call received the same entity-focused system prompt regardless of what the user was building.

### Key Points

- **5 content categories** — Entity/Mob, Items & Weaponry, Blocks & Furniture, Loot Tables & Recipes, Scripting & Manifests
- **Hybrid detection** — User selects category via dropdown, auto-detection serves as fallback
- **Shared context data** — Both the production LLM pipeline and the evaluation framework use the same source of truth
- **Backward compatible** — Defaults to `entity_logic_ai` if no category is specified

---

## 2. The Problem: Static Prompts

Previously, `_get_full_system_prompt()` in `backend/llm/llm.py` built the same system prompt every time:

```
LLM_SYSTEM_PROMPT (entity-focused rules)
  + mob_spec.schema.json (entity schema)
  + vanilla_reference.json (entity components)
```

This worked when the app only supported entities. But the evaluation framework (`scripts/evaluate_llm.py`) already supported 5 categories, each with its own rich context — examples, structural templates, and validation rules. That category-specific context was duplicated in the eval script and never available to the production pipeline.

**Result:** When a user asked the LLM to create an item or a loot table, it received entity-specific instructions and would often produce invalid output.

---

## 3. The Solution: Dynamic Category Context

The system prompt is now assembled in layers based on the selected category:

```
Layer 1: LLM_SYSTEM_PROMPT        (shared base rules — always included)
Layer 2: CATEGORY_CONTEXT[cat]     (category-specific examples, structure, rules)
Layer 3: CATEGORY_SCHEMAS[cat]     (category-specific JSON schema, if it exists)
```

For the `entity_logic_ai` category, the vanilla component reference is embedded inside the category context block, and the mob spec schema is appended. Other categories get their own examples and rules without entity-specific baggage.

---

## 4. Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│  BROWSER                                                    │
│                                                             │
│  1. User selects Category: "Items & Weaponry"               │
│  2. User selects Provider: "OpenAI"                         │
│  3. User types: "create a diamond sword with 12 damage"     │
│  4. User clicks "Ask LLM"                                   │
│                                                             │
│  frontend/js/llm.js → requestLlm()                          │
│    ├─ Reads category ("items_weaponry") from dropdown        │
│    ├─ Reads current spec from JSON editor                    │
│    ├─ Runs detectCategoryFromSpec() for hybrid warning       │
│    └─ POST /api/spec/llm                                    │
│        Body: {                                              │
│          "prompt": "create a diamond sword...",             │
│          "provider": "openai",                              │
│          "category": "items_weaponry",                      │
│          "current_spec": { ... },                           │
│          "api_key": "ghp_..."                               │
│        }                                                    │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  BACKEND                                                    │
│                                                             │
│  routes.py → llm_spec_editor()                              │
│    ├─ Extracts category from payload ("items_weaponry")     │
│    └─ Calls llm_rewrite_spec(prompt, spec, provider,        │
│                               api_key, category)            │
│                                                             │
│  llm.py → llm_rewrite_spec()                                │
│    ├─ If category is empty → detect_category(spec)          │
│    ├─ Routes to _call_openai(..., category)                 │
│    └─ _call_openai() builds messages:                       │
│         system: _get_full_system_prompt("items_weaponry")   │
│         user:   "Current spec: {...}\nInstruction: ..."     │
│                                                             │
│  llm.py → _get_full_system_prompt("items_weaponry")         │
│    ├─ Layer 1: LLM_SYSTEM_PROMPT (base rules)               │
│    ├─ Layer 2: CATEGORY_CONTEXT["items_weaponry"]            │
│    │    └─ Item structure, 3 examples, item-specific rules   │
│    └─ Layer 3: CATEGORY_SCHEMAS["items_weaponry"]            │
│         └─ (only if item_spec.schema.json exists on disk)    │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  LLM PROVIDER (OpenAI / DeepSeek / Gemini / Claude / Ollama)│
│                                                             │
│  Receives a system prompt with item-specific context:       │
│  - Item JSON structure template                             │
│  - 3 worked examples (sword, crossbow, pickaxe)             │
│  - Item-specific rules (what components are valid)           │
│  - Explicit warnings (NO entity components on items)         │
│                                                             │
│  Returns valid item JSON                                    │
└─────────────────────────────────────────────────────────────┘
```

### Shared Module

All category data lives in a single shared module:

```
backend/llm/category_context.py
├── CATEGORIES           — list of valid category IDs
├── CATEGORY_LABELS      — human-readable labels (for UI)
├── CATEGORY_CONTEXT     — per-category prompt context (examples, rules)
├── CATEGORY_SCHEMAS     — per-category JSON schemas (loaded from disk)
├── VANILLA_REF          — vanilla entity component reference
└── detect_category()    — auto-detection from spec structure
```

This module is imported by:
- `backend/llm/llm.py` — production LLM pipeline
- `scripts/evaluate_llm.py` — evaluation framework

---

## 5. How It Works End-to-End

### Step 1: User selects a category

The LLM Assistant panel has a **Category** dropdown with 5 options. The selection is persisted in `localStorage` under the key `builder_llm_category`.

### Step 2: Frontend sends category in the request

`requestLlm()` in `frontend/js/llm.js` reads the dropdown value and includes it in the POST body:

```js
const requestBody = {
    prompt: instruction,
    provider: provider,
    category: category,        // e.g. "items_weaponry"
    current_spec: currentSpec
};
```

Before sending, the frontend also runs `detectCategoryFromSpec(currentSpec)` and logs a warning to the console if the detected category doesn't match the dropdown. This is informational only — the dropdown value always wins.

### Step 3: Backend extracts category and builds the prompt

`llm_spec_editor()` in `routes.py` pulls `category` from the payload (defaulting to `"entity_logic_ai"`) and passes it through to `llm_rewrite_spec()`.

`llm_rewrite_spec()` applies hybrid logic: if `category` is falsy, it falls back to `detect_category(current_spec)` which inspects the spec's top-level keys.

### Step 4: Dynamic system prompt assembly

`_get_full_system_prompt(category)` builds the prompt:

| Category | Context Included | Schema Included |
|---|---|---|
| `entity_logic_ai` | Entity structure, AI rules, component reference | `mob_spec.schema.json` |
| `items_weaponry` | Item structure, 3 examples, item rules | `item_spec.schema.json` (if exists) |
| `blocks_furniture` | Block structure, 3 examples, block rules | `block_spec.schema.json` (if exists) |
| `loot_recipes` | Loot + recipe structures, 5 examples, rules | `loot_spec.schema.json` (if exists) |
| `scripting_components` | Manifest structure, 4 examples, UUID rules | `manifest_spec.schema.json` (if exists) |

### Step 5: Conditional validation

After the LLM responds, the output is only validated against `validate_spec()` (the mob spec validator) when the category is `entity_logic_ai`. Other categories return the raw JSON from the LLM, since they have different structures that `validate_spec()` would reject.

---

## 6. Category Reference

### `entity_logic_ai` — Entity / Mob

The original and most mature category. Focused on `minecraft:entity` JSON with AI behavior components.

**Context includes:**
- Entity JSON structure with `minecraft:entity > components`
- Rules for AI goals (`minecraft:behavior.*` with priorities)
- Component dependencies (e.g., `melee_attack` requires `attack` + `nearest_attackable_target`)
- Full vanilla component reference from `vanilla_reference.json`

**Validated by:** `validate_spec()` (mob spec schema)

### `items_weaponry` — Items & Weaponry

For `minecraft:item` definitions — swords, tools, food, armor, projectiles.

**Context includes:**
- Item JSON structure with `minecraft:item > components`
- 3 worked examples: sword, crossbow, pickaxe
- Rules for all item components (damage, durability, shooter, digger, food, armor, wearable, cooldown, repairable, projectile, max_stack_size)
- Cross-domain warning: entity components are forbidden

### `blocks_furniture` — Blocks & Furniture

For `minecraft:block` definitions — custom geometry blocks, furniture, decorative items.

**Context includes:**
- Block JSON structure with `minecraft:block > components`
- 3 worked examples: chair, lamp, transparent glass table
- Rules for geometry references, collision/selection boxes, light emission, material instances, destructibility, rotation traits
- Cross-domain warning: entity components are forbidden

### `loot_recipes` — Loot Tables & Recipes

For loot table pools and crafting/furnace recipes.

**Context includes:**
- Loot table structure with `pools > rolls + entries`
- 2 loot table examples (basic drops, set_count functions)
- 3 recipe structures: shaped, shapeless, furnace
- Rules for pool structure, conditions, functions, recipe key format

### `scripting_components` — Scripting & Manifests

For `manifest.json` files with script modules, dependencies, and UUIDs.

**Context includes:**
- Manifest structure with header, modules, dependencies
- 4 examples: script pack, data module, resource pack, world template
- Rules for UUID v4 format, module types, entry points, versioning

---

## 7. Hybrid Detection

The system uses a **"user picks, system verifies"** approach:

### Frontend (client-side)

`detectCategoryFromSpec(spec)` checks for distinctive top-level keys:

| Key Present | Detected Category |
|---|---|
| `minecraft:item` | `items_weaponry` |
| `minecraft:block` | `blocks_furniture` |
| `pools` or `minecraft:recipe*` | `loot_recipes` |
| `header` + `modules` | `scripting_components` |
| `minecraft:entity` | `entity_logic_ai` |
| `hp`, `components`, or anything else | `entity_logic_ai` (default) |

If the detection disagrees with the dropdown, a warning is logged to the browser console. The dropdown value is always sent to the server.

### Backend (server-side)

`detect_category(spec)` in `category_context.py` uses the same logic. It's called as a **fallback** in `llm_rewrite_spec()` only when no category is provided in the request (e.g., from older clients or direct API calls).

---

## 8. Files Changed

| File | Change |
|---|---|
| `backend/llm/category_context.py` | **New.** Single source of truth for all category data |
| `backend/llm/llm.py` | `_get_full_system_prompt()` now accepts `category`. All `_call_*` functions thread it through. Validation is conditional on category |
| `backend/core/routes.py` | `llm_spec_editor()` extracts `category` from payload. New `get_llm_categories()` endpoint |
| `backend/core/app.py` | Registered `GET /api/llm/categories` route |
| `frontend/index.html` | Added Category dropdown to LLM controls |
| `frontend/js/llm.js` | Reads category dropdown, sends in request body, persists in localStorage, auto-detect helper |
| `scripts/evaluate_llm.py` | Imports `CATEGORY_CONTEXT` and `CATEGORY_SCHEMAS` from shared module instead of duplicating ~400 lines |

### API Changes

| Endpoint | Change |
|---|---|
| `POST /api/spec/llm` | Now accepts optional `category` field in body (default: `"entity_logic_ai"`) |
| `GET /api/llm/categories` | **New.** Returns list of `{id, label}` objects for all available categories |

---

## 9. Adding a New Category

To add a new content category (e.g., `animations`):

### 1. Add to `backend/llm/category_context.py`

```python
# In CATEGORIES list:
CATEGORIES = [
    "entity_logic_ai",
    "items_weaponry",
    "blocks_furniture",
    "loot_recipes",
    "scripting_components",
    "animations",              # NEW
]

# In CATEGORY_LABELS:
CATEGORY_LABELS = {
    ...
    "animations": "Animations",
}

# In CATEGORY_CONTEXT:
CATEGORY_CONTEXT = {
    ...
    "animations": """
CATEGORY: Animations (animations/*.json)

STRUCTURE:
{
  "format_version": "1.10.0",
  "animations": {
    "animation.custom.walk": {
      "loop": true,
      "animation_length": 1.0,
      "bones": { ... }
    }
  }
}

KEY RULES:
- Animation identifiers must start with "animation."
- ...
""",
}

# In detect_category():
def detect_category(spec: dict) -> str:
    if "animations" in spec:
        return "animations"
    ...
```

### 2. (Optional) Add a schema file

Create `backend/schemas/animation_spec.schema.json`. It will be automatically loaded by the `CATEGORY_SCHEMAS` loader in `category_context.py`.

### 3. Add to the frontend dropdown

In `frontend/index.html`:

```html
<select id="llm-category">
    ...
    <option value="animations">Animations</option>
</select>
```

### 4. Update auto-detection (frontend)

In `frontend/js/llm.js`, update `detectCategoryFromSpec()`:

```js
if ("animations" in spec) return "animations";
```

That's it. The rest of the pipeline (routes, LLM calls, system prompt assembly) handles it automatically.

---

## 10. Configuration & Storage

### Environment Variables

No new environment variables. Category selection is a client-side preference.

### localStorage Keys

| Key | Value | Purpose |
|---|---|---|
| `builder_llm_category` | Category ID string (e.g. `"items_weaponry"`) | Persists the user's last selected category across sessions |

### Server-Side Defaults

If no `category` is provided in the API request, the server defaults to `"entity_logic_ai"` and falls back to `detect_category()` for auto-detection from the spec structure.
