# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bedrock Addon Builder is a web application that lets users create custom Minecraft Bedrock Edition mobs using natural language prompts powered by LLMs. Users describe what they want (e.g., "make it fly" or "double the health") and the system generates valid Bedrock add-on JSON specs.

The project includes an **automated LLM evaluation framework** to score and compare how well different LLM providers handle Minecraft Bedrock add-on generation tasks.

## Tech Stack

- **Backend:** Python 3.12 + FastAPI/Uvicorn (`backend/`)
- **Frontend:** Vanilla HTML/CSS/JS single-file app (`frontend/index.html`)
- **LLM Providers:** OpenAI (gpt-4o), DeepSeek, Gemini, Claude, Ollama
- **Deployment:** Docker → Hugging Face Spaces (port 7860)
- **Entry point:** `run.py`

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server (port 7860)
python run.py

# Run with custom port (uses PORT env var, not a CLI flag)
PORT=8000 python run.py

# Docker
docker build -t bedrock-builder .
docker run -p 7860:7860 bedrock-builder
```

## Environment Variables

```bash
PORT=7860                    # Server port
OPENAI_API_KEY=sk-...        # OpenAI
DEEPSEEK_API_KEY=sk-...      # DeepSeek
GEMINI_API_KEY=...           # Gemini
ANTHROPIC_API_KEY=sk-ant-... # Claude
OLLAMA_BASE_URL=...          # Ollama server (default: http://localhost:11435)
OLLAMA_MODEL=llama3.2        # Ollama model name
LLM_MODEL=gpt-4o             # Default OpenAI model
DEEPSEEK_MODEL=deepseek-chat # Default DeepSeek model
LLM_PROVIDER=openai          # Default provider
```

## Backend Architecture (`backend/`)

| Module | Purpose |
|--------|---------|
| `app.py` | FastAPI entry point, CORS config, route registration |
| `routes.py` | All HTTP endpoints (mob CRUD, builds, LLM calls, static files) |
| `core.py` | Constants, defaults, regex validators, `LLM_SYSTEM_PROMPT` |
| `spec_utils.py` | Mob spec validation (`validate_spec()`), read/write/delete, JSON Patch |
| `builders.py` | Generate resource/behavior pack files (textures, manifests, entities) |
| `packaging.py` | Bundle ZIPs, create .mcpack/.mcaddon/.mcworld files |
| `llm.py` | Multi-provider LLM integration |
| `llm_scoring.py` | **Source of truth for test cases.** `GOLDEN_TESTS` list, semantic rules, scoring |
| `llm_logger.py` | Logs LLM requests/responses to `data/llm_logs/` |
| `run_golden_tests.py` | CLI tool to run golden tests against any provider |
| `schemas_loader.py` | Load and cache `schemas/mob_spec.schema.json` |

## Frontend (`frontend/index.html`)

Single 93KB file containing:
- User management (localStorage-based, no database)
- JSON editor for mob specs
- LLM assistant integration
- Pixel Painter for textures
- Three.js 3D geometry viewport
- Light/dark theme toggle

## Key API Endpoints

- `GET /api/mobs` - List all mobs
- `GET/POST/DELETE /api/mobs/{name}` - Mob CRUD
- `POST /api/build` - Build addon (`specs_json`, `build_mode`)
- `POST /api/spec/llm` - AI-assisted spec editing
- `GET /api/geometry/{mob_name}` - Fetch geometry from bedrock-samples
- `GET /download/{name}` - Download built artifact

## Validation Rules (`spec_utils.py`)

- Identifier: `^[a-z0-9_]+:[a-z0-9_]+$`
- HP: 1-2048, Damage: 0-128, Speed: 0-2, Scale: 0.2-5.0
- Collision box: width 0.1-5, height 0.5-5
- Colors: hex format `#RRGGBB`

## Golden Test Case Schema
Test cases live in `backend/llm_scoring.py` as `GoldenTestCase` dataclass instances inside the `GOLDEN_TESTS` list.

```python
GoldenTestCase(
    name="test_name",              # Unique identifier
    description="What this tests", # Human-readable description
    prompt="User instruction",     # The prompt sent to the LLM
    input_spec={                   # Fixed starting mob spec
        "identifier": "custom:test_mob",
        "display_name": "Test Mob",
        "short_name": "test_mob",
        "hp": 20,
        "damage": 5,
        "speed": 0.25,
        "components": {}
    },
    required_components=["minecraft:component_name"],  # Must exist in output
    forbidden_components=["minecraft:bad_component"],   # Must NOT exist in output
    required_fields={                                   # Field value constraints
        "hp": {"equals": 40},
        "speed": {"min": 0.1, "max": 2.0},
        "display_name": {"contains": "Dragon"}
    },
    should_not_change=["hp", "damage", "speed"]        # Fields LLM should leave alone
)
```

## Test Categories

All test cases target `test_cases.json` as the canonical source. Categories in priority order:

### 1. Entity Logic & AI
Focus: `minecraft:behavior.*` components.
Rule: Validate behavioral goals (AI) separately from static stats (hp, speed, damage).
Currently 10 test cases covering stats changes, behavior additions, and component dependencies.

### 2. Items & Weaponry
Focus: `minecraft:damage`, `minecraft:shooter`, `minecraft:digger`.
Rule: Item files must NOT contain entity-only components (`minecraft:behavior.*`).

### 3. Blocks & Furniture
Focus: `minecraft:geometry`, `minecraft:block`.
Rule: Validate namespaces and geometry references for custom models.

### 4. Loot Tables & Recipes
Focus: JSON structure in `loot_tables/` and `recipes/`.
Rule: Check correct `pools`/`rolls` nesting in loot tables and valid `pattern`/`result` syntax in recipes.

### 5. Scripting & Custom Components *(low priority, advanced)*
Focus: Scripting API, `manifest.json`.
Rule: Validate script module versioning and entry point paths.

## Critical Minecraft Bedrock Rules
These rules MUST be enforced in all test cases and LLM outputs:

1. **Behaviors belong to Entities, NOT Items.** `minecraft:behavior.*` components are for mobs only. Items use `minecraft:weapon`, `minecraft:damage`, `minecraft:digger`, etc.
2. **Component dependencies exist.** If `minecraft:behavior.swell` is present, `minecraft:explode` must also be present. If `minecraft:tameable` is present, `minecraft:behavior.beg` must also be present. See `COMPONENT_DEPENDENCIES` in `llm_scoring.py`.
3. **Components that imply field values.** `minecraft:is_baby` implies `scale < 0.9`. `minecraft:can_fly` implies `speed >= 0.1`. See `COMPONENT_FIELD_IMPLICATIONS` in `llm_scoring.py`.
4. **All output must be valid JSON** matching the mob spec schema with ALL required keys.

## Scoring System (3-Tier)
- **Tier 1 - Structural Validity:** Valid JSON, correct types, values in range (`spec_utils.py`)
- **Tier 2 - Semantic Consistency:** Component dependencies, logical coherence (`llm_scoring.py`)
- **Tier 3 - Intent Alignment:** Does the output match what the user asked? (Future: LLM-as-Judge)

## Running Golden Tests

```bash
# Mock provider (10/10 pass, no API needed)
python backend/run_golden_tests.py --provider mock

# Local Ollama
python backend/run_golden_tests.py --provider ollama -v

# Cloud providers
python backend/run_golden_tests.py --provider openai --provider deepseek

# Specific test only
python backend/run_golden_tests.py --provider ollama -t basic_explode -v

# See all available tests
python backend/run_golden_tests.py --dry-run
```

## Build Output Formats

- `bundle` → ZIP with both packs
- `mcworld` → Importable world file
- `mcaddon` → Addon package
- `resources` / `behavior` → Individual .mcpack files

## Client-Side Storage Keys

User data stored in browser localStorage:
- `app_users` - List of usernames
- `current_user` - Active user
- `user_{NAME}_data` - User's mobs and settings
- `builder_llm_provider` / `builder_llm_api_key` - LLM config

## Current Sprint Goals
1. Expand test categories beyond Entity modification (Weaponry, Blocks, Loot Tables)
2. Use test results to identify where models fail and build context injection to improve prompts
3. Compare providers to find the best model for each category
