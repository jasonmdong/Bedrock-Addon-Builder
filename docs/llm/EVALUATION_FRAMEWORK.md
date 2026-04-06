# LLM Evaluation Framework — Design Document

**Date:** February 9, 2026
**Author:** Development Session Log
**Status:** v1.0 — Initial Implementation Complete

---

## Table of Contents

1. [Motivation](#1-motivation)
2. [Architecture Overview](#2-architecture-overview)
3. [Test Suite (`data/test_cases.json`)](#3-test-suite)
4. [Evaluation Script (`scripts/evaluate_llm.py`)](#4-evaluation-script)
5. [Provider System](#5-provider-system)
6. [Context Injection (Few-Shot Prompting)](#6-context-injection)
7. [Validation Pipeline](#7-validation-pipeline)
8. [CLI Reference](#8-cli-reference)
9. [Results & Analysis](#9-results--analysis)
10. [Known Issues & Next Steps](#10-known-issues--next-steps)

---

## 1. Motivation

The Bedrock Addon Builder uses LLMs to generate Minecraft Bedrock Edition JSON files — entities, items, blocks, loot tables, recipes, and manifests. These JSON outputs must conform to strict structural rules:

- **Entity components** need specific AI behavior hierarchies (e.g., `melee_attack` requires `attack` and `nearest_attackable_target`).
- **Item components** must never include entity-only fields like `minecraft:health`.
- **Block geometry** references must start with `"geometry."`.
- **Loot table pools** must always have `rolls` and `entries`.
- **Manifest UUIDs** must be valid v4 format.

Before this framework, there was no automated way to measure how well an LLM performs across these categories. The backend had scoring logic (`backend/llm_scoring.py`) and golden tests (`backend/run_golden_tests.py`), but no standalone, provider-agnostic evaluation harness that could compare models head-to-head.

### Goals

1. **Quantify LLM accuracy** — Get a concrete pass/fail rate per category and overall.
2. **Compare providers** — Run the same 50 tests against mock, Ollama (local), Anthropic (Claude), and OpenAI (GPT) to find the best model for each task.
3. **Catch regressions** — If a prompt change or model update degrades output quality, the test suite catches it immediately.
4. **Guide prompt engineering** — The per-category breakdown reveals which areas need better few-shot examples or system prompt rules.

---

## 2. Architecture Overview

```
data/test_cases.json          50 golden test cases (10 per category)
        │
        ▼
scripts/evaluate_llm.py       Main evaluation harness
        │
        ├── load_test_cases()         Parse JSON, filter dividers
        ├── _build_system_prompt()    Inject schema + few-shot examples
        ├── query_llm()               Route to provider (mock/anthropic/openai/ollama)
        ├── check_strict_requirements()   Validate components, fields, forbidden items
        ├── check_semantic_consistency()  UUID validation, cross-field logic
        └── main()                    CLI, run loop, summary output
```

### Data Flow

```
Test Case ──► System Prompt + User Prompt ──► LLM Provider ──► JSON Output
                                                                    │
                                                                    ▼
                                                          Strict Validation
                                                          Semantic Validation
                                                                    │
                                                                    ▼
                                                            PASS / FAIL
```

---

## 3. Test Suite

**File:** `data/test_cases.json`
**Version:** 2.0.0
**Total Tests:** 50 (10 per category)

### Categories

| Category | Description | Example Tests |
|---|---|---|
| `entity_logic_ai` | AI behaviors, targeting, breeding, taming, riding, explosions | `wolf_hunts_creepers`, `tameable_pet`, `creeper_exploder`, `multi_behavior_boss` |
| `items_weaponry` | Weapons, tools, food, armor, throwables, cooldowns | `diamond_greatsword`, `food_item`, `armor_chestplate`, `multi_component_tool` |
| `blocks_furniture` | Custom geometry, lighting, materials, destructibility, crafting stations | `wooden_chair`, `glowing_lamp`, `destructible_block`, `crafting_station_block` |
| `loot_recipes` | Loot tables, shaped/shapeless/furnace recipes, conditions, functions | `zombie_loot_table`, `simple_shapeless_recipe`, `furnace_recipe`, `enchanted_loot_functions` |
| `scripting_components` | Manifest.json files — script/data/resource/world_template modules | `script_manifest_basic`, `simple_data_module`, `world_template_manifest`, `full_addon_manifest` |

### Difficulty Distribution

Each category contains tests ranging from **simple** to **complex**:

- **Simple** (3-4 per category): Basic single-component tasks. E.g., "Create a passive mob that wanders."
- **Medium** (3-4 per category): Multi-component tasks with field constraints. E.g., "Create a wolf that hunts creepers."
- **Complex** (2-3 per category): Multi-component tasks with events, conditions, or cross-cutting concerns. E.g., "Create a boss mob with 100 HP, melee attack, knockback resistance, and player targeting at 32 blocks."

### Test Case Structure

Each test case contains:

```json
{
  "name": "diamond_greatsword",
  "category": "items_weaponry",
  "difficulty": "medium",
  "description": "Sword with high damage and durability",
  "prompt": "Create a diamond greatsword with 12 damage and 500 durability...",
  "input_spec": { ... },
  "required_components": ["minecraft:damage", "minecraft:durability", "minecraft:hand_equipped"],
  "required_fields": {
    "minecraft:item.components.minecraft:damage": { "equals": 12 },
    "minecraft:item.components.minecraft:durability.max_durability": { "equals": 500 }
  },
  "forbidden_components": ["minecraft:health", "minecraft:behavior.melee_attack", ...],
  "should_not_change": ["minecraft:item.description.identifier"]
}
```

- **`input_spec`** — The starting JSON given to the LLM as context.
- **`required_components`** — Keys that MUST exist in the output's components.
- **`required_fields`** — Dot-path fields with value constraints (`equals`, `type`, `pattern`, `min`, `max`, `min_length`, `contains`, etc.).
- **`forbidden_components`** — Keys that MUST NOT appear (catches cross-category hallucination).
- **`should_not_change`** — Fields whose values must remain identical to the input.

---

## 4. Evaluation Script

**File:** `scripts/evaluate_llm.py`
**Lines:** ~1,488

The script is organized into numbered steps:

| Step | Function | Purpose |
|---|---|---|
| 1 | `load_test_cases()` | Parse `test_cases.json`, filter `__divider__` entries |
| 2 | `query_llm()`, `mock_response()`, `_call_anthropic()`, `_call_openai()`, `_call_ollama()` | Send prompt to LLM, extract JSON from response |
| 3 | `check_strict_requirements()` | Validate required/forbidden components, required fields, unchanged fields |
| 4 | `check_semantic_consistency()` | UUID v4 validation, structural cross-checks |
| 5 | `run_test()`, `print_result()`, `main()` | Orchestration, CLI parsing, colored output, summary |

### Path Resolution Engine

A critical subsystem is the **dot-path resolver** (`_get_nested_value`, `_tokenize_path`, `_resolve_tokens`) which handles:

- **Simple paths:** `minecraft:item.components.minecraft:damage`
- **Wildcard arrays:** `pools[*].entries[*].type` — expands to all matching values
- **Indexed arrays:** `pools[0].rolls`
- **Wildcard objects:** `minecraft:block.components.minecraft:material_instances.*`
- **Compound Bedrock keys:** `minecraft:behavior.panic` (a single key containing a dot)

The tokenizer was specifically enhanced to handle Bedrock's naming convention where component keys like `minecraft:behavior.panic`, `minecraft:navigation.walk`, and `minecraft:movement.basic` contain dots that are NOT path separators. It uses a greedy re-join strategy: when a `minecraft:`-prefixed token is followed by a non-structural, non-namespaced token, they are merged back into a single compound key.

---

## 5. Provider System

The framework supports four LLM providers with graceful fallback:

### Mock Provider (default)

- Returns hardcoded JSON responses for all 50 test cases.
- `wolf_hunts_creepers` is **intentionally flawed** (missing `minecraft:attack`) to demonstrate failure detection.
- Used for development and CI — no network calls, instant results.
- Expected result: **49/50 pass** (1 intentional failure).

### Anthropic (Claude)

- Uses the `anthropic` Python package.
- Requires `ANTHROPIC_API_KEY` environment variable.
- Default model: `claude-sonnet-4-20250514`.
- Falls back to mock if package missing or key unset.

### OpenAI (GPT)

- Uses the `openai` Python package.
- Requires `OPENAI_API_KEY` environment variable.
- Default model: `gpt-4o`.
- Falls back to mock if package missing or key unset.

### Ollama (Local)

- Uses HTTP requests to `http://localhost:11435/api/chat` (with `/api/generate` fallback).
- No API key needed — runs against a local Ollama instance.
- Default model: `llama3.2`.
- Falls back to mock if Ollama is unreachable.
- 120-second timeout per request.

All real providers receive the full system prompt (see Section 6) and extract JSON from the response using regex-based extraction (`_extract_json`), which finds the first `{...}` block in the LLM's output.

---

## 6. Context Injection

### Motivation

Small local models (e.g., Llama 3 8B) struggle with Bedrock JSON without guidance. The context injection system mirrors the backend's `_get_full_system_prompt()` approach from `backend/llm.py`, providing:

1. **Base system prompt** — Universal rules (JSON-only output, preserve existing fields, no hallucinated components, component dependency rules).

2. **Category-specific context** (`CATEGORY_CONTEXT` dict) — Structural examples and key rules tailored to each of the 5 categories:

   - **entity_logic_ai:** Entity structure, attack triple (attack + melee_attack + nearest_attackable_target), breeding, taming, riding, explosions, panic, knockback resistance. Plus vanilla component reference from `backend/data/vanilla_reference.json`.
   - **items_weaponry:** Item structure, sword/crossbow/pickaxe examples, food, armor, wearable, cooldown, repairable, projectile, max_stack_size rules.
   - **blocks_furniture:** Block structure, chair/lamp/glass table examples, destructible_by_mining, destructible_by_explosion, crafting_table, rotation traits, per-face material_instances.
   - **loot_recipes:** Loot table, shaped recipe, shapeless recipe, furnace recipe structures. Pool/entry rules, conditions, functions.
   - **scripting_components:** Manifest structure, script/data/resource/world_template module examples. UUID v4 rules, version arrays, dependencies.

3. **Schema reference** — A formal JSON Schema is appended for every category:
   - `entity_logic_ai` → `mob_spec.schema.json`
   - `items_weaponry` → `item_spec.schema.json`
   - `blocks_furniture` → `block_spec.schema.json`
   - `loot_recipes` → `loot_spec.schema.json`
   - `scripting_components` → `manifest_spec.schema.json`

### Impact

Context injection was the single biggest improvement for real LLM performance. In early testing, `items_weaponry` went from ~30% to **100% pass rate** with Llama 3 on Ollama after adding category-specific examples.

---

## 7. Validation Pipeline

Each test case goes through two validation stages:

### Stage 1: Strict Requirement Checks

| Check Type | What It Validates |
|---|---|
| `required_component` | Component key exists in the output's components dict |
| `forbidden_component` | Component key does NOT exist (catches hallucination) |
| `required_field` | Dot-path field exists and satisfies constraints: `equals`, `type`, `pattern`, `min`, `max`, `min_length`, `max_length`, `exact_length`, `items_type`, `type_any`, `contains` |
| `unchanged_field` | Field value matches the original `input_spec` exactly |

### Stage 2: Semantic Consistency Checks

| Check Type | What It Validates |
|---|---|
| `semantic_uuid` | All UUID-like strings in the output are valid UUID v4 format (`xxxxxxxx-xxxx-4xxx-[89ab]xxx-xxxxxxxxxxxx`) |

### Scoring

- A test **passes** only if ALL checks pass (strict AND semantic).
- The **score** is `passed_checks / total_checks` (e.g., 5/7 = 71%).
- The **summary** shows pass count, fail count, average score, and per-category breakdown.

---

## 8. How to Run

### Prerequisites

- **Python 3.10+** (uses `dict[str, dict]` type hints)
- No additional packages needed for mock provider
- For real providers, install the relevant package:

```bash
pip install anthropic          # For Claude
pip install openai             # For GPT-4o
pip install requests           # For Ollama (usually already installed)
```

### Environment Variables (Real Providers Only)

```bash
# Anthropic (Claude)
set ANTHROPIC_API_KEY=sk-ant-...       # Windows
export ANTHROPIC_API_KEY=sk-ant-...    # Linux/Mac

# OpenAI (GPT-4o)
set OPENAI_API_KEY=sk-...              # Windows
export OPENAI_API_KEY=sk-...           # Linux/Mac

# Ollama — no API key needed, just needs to be running
# Default URL: http://localhost:11435
```

### Ollama Setup

If using Ollama on a **local machine**:
```bash
ollama serve                           # Start the Ollama server
ollama pull llama3                     # Download the model (first time only)
```

If using Ollama on a **remote GPU server**, you need to either:
1. SSH tunnel: `ssh -L 11435:localhost:11434 user@remote-server`
2. Or change `OLLAMA_BASE_URL` in `scripts/evaluate_llm.py` to `http://<remote-ip>:11434`

> **Important:** If Ollama is not reachable, the script silently falls back to the mock provider.
> Check the first line of output — if it says `"Falling back to mock provider"`, your LLM is not being used.

---

### Quick Start Commands

```bash
# 1. Verify everything works with mock (no setup needed)
python scripts/evaluate_llm.py --all

# 2. Run a single category with mock
python scripts/evaluate_llm.py -c items_weaponry

# 3. Run with verbose output to see every check
python scripts/evaluate_llm.py --all -v
```

### Running Against Real LLMs

```bash
# Ollama (local or remote)
python scripts/evaluate_llm.py --all -p ollama                    # default model (llama3.2)
python scripts/evaluate_llm.py --all -p ollama -m llama3          # specific model
python scripts/evaluate_llm.py --all -p ollama -m mistral         # different model
python scripts/evaluate_llm.py --all -p ollama -m llama3 -v       # verbose

# Anthropic (Claude) — requires ANTHROPIC_API_KEY
python scripts/evaluate_llm.py --all -p anthropic                 # default (claude-sonnet)
python scripts/evaluate_llm.py --all -p anthropic -m claude-sonnet-4-20250514

# OpenAI (GPT) — requires OPENAI_API_KEY
python scripts/evaluate_llm.py --all -p openai                    # default (gpt-4o)
python scripts/evaluate_llm.py --all -p openai -m gpt-4o-mini     # cheaper model
```

### Single Category Testing

Use `-c` to test one category at a time (useful for debugging or prompt tuning):

```bash
python scripts/evaluate_llm.py -c entity_logic_ai -p ollama -m llama3 -v
python scripts/evaluate_llm.py -c items_weaponry -p ollama -m llama3 -v
python scripts/evaluate_llm.py -c blocks_furniture -p ollama -m llama3 -v
python scripts/evaluate_llm.py -c loot_recipes -p ollama -m llama3 -v
python scripts/evaluate_llm.py -c scripting_components -p ollama -m llama3 -v
```

### Comparing Models

Run the same tests against different models to compare:

```bash
python scripts/evaluate_llm.py --all -p ollama -m llama3          # Llama 3 8B
python scripts/evaluate_llm.py --all -p ollama -m llama3.1        # Llama 3.1
python scripts/evaluate_llm.py --all -p ollama -m mistral         # Mistral 7B
python scripts/evaluate_llm.py --all -p ollama -m deepseek-r1     # DeepSeek R1
python scripts/evaluate_llm.py --all -p anthropic                 # Claude Sonnet
python scripts/evaluate_llm.py --all -p openai                    # GPT-4o
```

### Reading the Output

```
=== LLM Evaluation Framework ===
Source:   data\test_cases.json
Provider: ollama (llama3)          ← Confirm this says your provider, NOT "mock"
Tests:    50

  -- entity_logic_ai --
  FAIL    75%  wolf_hunts_creepers   [entity_logic_ai]    ← 75% of checks passed
  PASS   100%  breedable_farm_animal [entity_logic_ai]    ← All checks passed

=== Summary ===
  Total:   50
  Passed:  49
  Failed:  1
  Score:   100%

  Per-Category:
    9/10  entity_logic_ai          ← 9 out of 10 tests passed
    10/10 items_weaponry
```

- **PASS** = all checks passed for that test case
- **FAIL** = at least one check failed; the percentage shows how many checks passed
- **Provider line** = verify this shows your actual provider, not `mock`
- Add `-v` to see exactly which checks passed/failed

### Flags Reference

| Flag | Short | Description |
|---|---|---|
| `--all` | `-a` | Run all 50 tests across all 5 categories |
| `--category` | `-c` | Run only one category: `entity_logic_ai`, `items_weaponry`, `blocks_furniture`, `loot_recipes`, `scripting_components` |
| `--provider` | `-p` | LLM provider: `mock` (default), `anthropic`, `openai`, `ollama` |
| `--model` | `-m` | Override default model name (e.g. `llama3`, `gpt-4o-mini`) |
| `--verbose` | `-v` | Print individual check results for every test |

### Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `Falling back to mock provider` | Ollama not running or wrong URL | Start Ollama with `ollama serve`, or fix `OLLAMA_BASE_URL` in the script |
| `Provider: mock (llama3)` | Ollama unreachable, fell back to mock | Same as above — the `(llama3)` is the requested model, but mock is being used |
| `ANTHROPIC_API_KEY not set` | Missing env variable | Set the environment variable (see above) |
| `OPENAI_API_KEY not set` | Missing env variable | Set the environment variable (see above) |
| All scripting tests fail on UUID | LLM generates invalid UUID v4 | This is a known limitation of small models — they can't reliably produce valid UUIDs |
| Exit code 1 | At least one test failed | This is expected; exit code 0 = all tests passed |

---

## 9. Results & Analysis

### Mock Provider (Baseline)

```
  Per-Category:
    9/10  entity_logic_ai       (1 intentional failure: wolf_hunts_creepers)
    10/10 items_weaponry
    10/10 blocks_furniture
    10/10 loot_recipes
    10/10 scripting_components
  Total: 49/50 (98%)
```

### Ollama — Llama 3 (8B, Local GPU)

```
  Per-Category:
    3/10  entity_logic_ai
    7/10  items_weaponry
    10/10 blocks_furniture
    10/10 loot_recipes
    1/10  scripting_components
  Total: 31/50 (62%)
```

### Analysis

| Category | Llama 3 Score | Primary Failure Mode |
|---|---|---|
| **blocks_furniture** | 10/10 | None — block JSON is structurally simple |
| **loot_recipes** | 10/10 | None — loot/recipe structures are well-defined |
| **items_weaponry** | 7/10 | Occasional missing components or wrong field types |
| **entity_logic_ai** | 3/10 | Missing component dependencies (e.g., attack triple), wrong filter structures |
| **scripting_components** | 1/10 | **UUID generation is the dominant failure.** Llama 3 cannot reliably produce valid UUID v4 strings. Also changes `header.name` values. |

### Key Insights

1. **Blocks and loot are solved** — The few-shot examples are sufficient for Llama 3 to produce perfect output in these categories.

2. **UUID generation is the #1 bottleneck** — Nearly every `scripting_components` failure is due to invalid UUIDs. Llama 3 generates strings that look like UUIDs but fail the v4 regex (`4` in position 13, `[89ab]` in position 18). This is a fundamental limitation of small language models with hex/format constraints.

3. **Entity logic needs richer examples** — The attack triple (attack + melee_attack + nearest_attackable_target) is a non-obvious dependency that small models miss. More few-shot examples showing the complete pattern would help.

4. **Context injection works** — Categories with detailed structural examples (blocks, loot) achieve 100%. Categories where the model must infer dependencies (entities) or generate constrained random strings (UUIDs) still struggle.

---

## 10. Known Issues & Next Steps

### Known Issues

- **Compound key tokenizer** — The path tokenizer uses a heuristic to detect Bedrock keys with dots (e.g., `minecraft:behavior.panic`). It works for all current test cases but may need refinement for deeply nested or unusual key patterns.
- **UUID generation** — Small models cannot reliably generate UUID v4 strings. A post-processing step that replaces invalid UUIDs with generated ones would dramatically improve `scripting_components` scores.
- **`header.name` mutation** — Llama 3 sometimes changes the pack name despite the system prompt saying to preserve existing fields. Stronger prompt wording or a post-processing fix could address this.

### Potential Next Steps

1. **Post-processing pipeline** — Auto-fix invalid UUIDs and restore mutated `should_not_change` fields before scoring. This would separate "can the model get the structure right?" from "can the model generate valid random strings?"
2. **Larger model benchmarks** — Run the suite against Claude Sonnet, GPT-4o, and larger Ollama models (Llama 3 70B, Mixtral) to establish a performance ladder.
3. **Prompt iteration** — Use the per-category scores to guide targeted prompt improvements. Entity logic needs more dependency examples; scripting needs explicit UUID format examples.
4. **CI integration** — Run `python scripts/evaluate_llm.py --all` in CI with the mock provider to catch test case or validation regressions.
5. **Score history tracking** — Log results to a JSON file over time to track improvement trends across prompt and model changes.

---

## Files Modified/Created

| File | Action | Description |
|---|---|---|
| `scripts/evaluate_llm.py` | Created | Full evaluation harness (~1,500 lines) |
| `data/test_cases.json` | Expanded | 15 → 50 test cases (v1.0 → v2.0) |
| `backend/schemas/item_spec.schema.json` | Created | JSON Schema for items & weaponry |
| `backend/schemas/block_spec.schema.json` | Created | JSON Schema for blocks & furniture |
| `backend/schemas/loot_spec.schema.json` | Created | JSON Schema for loot tables & recipes |
| `backend/schemas/manifest_spec.schema.json` | Created | JSON Schema for manifest.json files |
| `CLAUDE.md` | Created | Project context file for Claude Code CLI |
| `docs/EVALUATION_FRAMEWORK.md` | Created | This document |
