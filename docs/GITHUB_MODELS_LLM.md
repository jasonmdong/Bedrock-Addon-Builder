# LLM Integration via GitHub Models — Technical Documentation

**Date:** March 3, 2026
**Status:** v1.0 — Working End-to-End

---

## Table of Contents

1. [Overview](#1-overview)
2. [Why GitHub Models?](#2-why-github-models)
3. [Getting Your GitHub Token](#3-getting-your-github-token)
4. [How It Works End-to-End](#4-how-it-works-end-to-end)
5. [Architecture Deep Dive](#5-architecture-deep-dive)
6. [Configuration Reference](#6-configuration-reference)
7. [Available Models](#7-available-models)
8. [Using It in the Web App](#8-using-it-in-the-web-app)
9. [Using It in the Evaluation Script](#9-using-it-in-the-evaluation-script)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Overview

The Bedrock Addon Builder uses LLMs (Large Language Models) to let users describe changes in plain English (e.g., "make the mob do double damage and fly") and have the AI rewrite the mob's JSON spec accordingly.

Instead of paying for the OpenAI API directly, we route all OpenAI-model requests through **GitHub Models** — a free inference API available to all GitHub users, including those on **GitHub Pro for Students** (GitHub Education). This gives us access to GPT-4.1, GPT-4o, and other frontier models at no cost.

### Key Points

- **Free for GitHub users** — No credit card or OpenAI billing required
- **Uses the standard `openai` Python package** — Just pointed at a different URL
- **Same models** — GPT-4.1, GPT-4o-mini, etc. are all available
- **Token-based auth** — Uses your GitHub Personal Access Token (PAT), not an OpenAI API key

---

## 2. Why GitHub Models?

| Feature | OpenAI Direct API | GitHub Models |
|---|---|---|
| **Cost** | Pay-per-token ($$$) | Free (rate-limited) |
| **Auth** | OpenAI API key (requires billing setup) | GitHub PAT (free with any GitHub account) |
| **Models** | GPT-4o, GPT-4.1, etc. | Same models via `openai/gpt-4.1`, etc. |
| **Rate Limits** | Based on billing tier | ~150 requests/day for free tier, more for Pro |
| **Student Access** | Requires payment | Free with GitHub Education / Pro for Students |
| **SDK** | `openai` Python package | Same `openai` package, different `base_url` |

GitHub Pro for Students (via [GitHub Education](https://education.github.com/)) gives you elevated rate limits on GitHub Models, making it practical for development and testing.

---

## 3. Getting Your GitHub Token

### Step 1: Verify GitHub Pro for Students

If you're a student, make sure you've signed up for the GitHub Student Developer Pack:
1. Go to [education.github.com/pack](https://education.github.com/pack)
2. Click **"Sign up for Student Developer Pack"**
3. Verify your student status with your `.edu` email or school ID
4. Once approved, your GitHub account is upgraded to **GitHub Pro**

### Step 2: Create a Personal Access Token (PAT)

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. Click **"Generate new token"** → **"Generate new token (classic)"**
3. Give it a descriptive name (e.g., `bedrock-addon-builder-llm`)
4. Under **Select scopes**, there is no special scope needed for GitHub Models — the default (no scopes) works. However, if you see a `models` scope, check it.
5. Click **"Generate token"**
6. **Copy the token immediately** — it starts with `ghp_` and you won't see it again

### Step 3: Add to Your `.env` File

Open your `.env` file in the project root and add:

```
GITHUB_TOKEN=ghp_your_actual_token_here
```

That's it. The app loads this automatically via `python-dotenv` when the server starts.

### Alternative: Paste Directly in the UI

You can also paste your token into the **"API Key"** field in the LLM Assistant panel in the browser. This is stored in `localStorage` (browser-only, never sent to any third party) and takes priority over the `.env` token.

---

## 4. How It Works End-to-End

Here's the complete flow when you click **"Ask LLM"** in the web app:

```
┌─────────────────────────────────────────────────────────┐
│  BROWSER (frontend)                                     │
│                                                         │
│  1. User types: "make the mob do double damage and fly" │
│  2. User selects Provider: "OpenAI"                     │
│  3. User clicks "Ask LLM"                               │
│                                                         │
│  frontend/js/llm.js → requestLlm()                      │
│    ├─ Reads current mob spec from JSON editor            │
│    ├─ Reads provider ("openai") and API key from form    │
│    ├─ POST /api/spec/llm                                 │
│    │   Body: {                                           │
│    │     "prompt": "make the mob do double damage...",   │
│    │     "provider": "openai",                           │
│    │     "api_key": "ghp_...",  (optional)               │
│    │     "current_spec": { ... mob JSON ... }            │
│    │   }                                                 │
│    └─ Receives updated spec, shows diff, updates editor  │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP POST
                     ▼
┌─────────────────────────────────────────────────────────┐
│  BACKEND (FastAPI / Python)                             │
│                                                         │
│  backend/core/routes.py → llm_spec_editor()             │
│    ├─ Extracts prompt, provider, api_key, current_spec  │
│    ├─ Calls llm_rewrite_spec(prompt, spec, provider,    │
│    │                          api_key)                   │
│    └─ Returns { "spec": { ...updated JSON... } }        │
│                                                         │
│  backend/llm/llm.py → llm_rewrite_spec()                │
│    ├─ Routes to _call_openai() for "openai" provider    │
│    │                                                     │
│    │  _call_openai():                                    │
│    │    1. Builds system prompt with:                    │
│    │       - Bedrock rules & component dependencies     │
│    │       - JSON schema for the spec format             │
│    │       - Vanilla reference data (component examples) │
│    │    2. Creates OpenAI client:                        │
│    │       OpenAI(                                       │
│    │         base_url="https://models.github.ai/         │
│    │                   inference",                        │
│    │         api_key=<GITHUB_TOKEN>                      │
│    │       )                                             │
│    │    3. Calls client.chat.completions.create(         │
│    │         model="openai/gpt-4.1",                    │
│    │         response_format={"type": "json_object"},   │
│    │         messages=[system_prompt, user_prompt]       │
│    │       )                                             │
│    │    4. Parses JSON from response                     │
│    │    5. Validates against mob_spec schema             │
│    │    6. Returns validated spec                        │
│    │                                                     │
│    └─ Returns updated spec to route handler              │
└────────────────────┬────────────────────────────────────┘
                     │ HTTPS POST (OpenAI SDK)
                     ▼
┌─────────────────────────────────────────────────────────┐
│  GITHUB MODELS (external)                               │
│                                                         │
│  URL: https://models.github.ai/inference                │
│  Auth: Authorization: Bearer ghp_...                    │
│                                                         │
│  Receives:                                              │
│    POST /chat/completions                               │
│    {                                                     │
│      "model": "openai/gpt-4.1",                        │
│      "response_format": {"type": "json_object"},        │
│      "messages": [                                       │
│        {"role": "system", "content": "<rules+schema>"}, │
│        {"role": "user", "content": "<spec + prompt>"}   │
│      ]                                                   │
│    }                                                     │
│                                                         │
│  Returns:                                               │
│    { "choices": [{ "message": { "content": "{...}" }}]} │
│                                                         │
│  The content is a complete, valid mob spec JSON that    │
│  incorporates the user's requested changes.             │
└─────────────────────────────────────────────────────────┘
```

### What Makes This Work

The `openai` Python package doesn't hardcode `api.openai.com`. It accepts a `base_url` parameter that redirects all API calls to any OpenAI-compatible endpoint. GitHub Models exposes the same `/chat/completions` REST API that OpenAI does, so the SDK works unchanged — we just point it at a different server and use a different auth token.

```python
# Before (paid OpenAI):
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# After (free GitHub Models):
client = OpenAI(
    base_url="https://models.github.ai/inference",
    api_key=os.environ["GITHUB_TOKEN"],
)
```

Everything else — the chat completions call, JSON mode, streaming, etc. — works identically.

---

## 5. Architecture Deep Dive

### Files Involved

| File | Role |
|---|---|
| `backend/llm/llm.py` | Core LLM logic — builds prompts, calls providers, validates output |
| `backend/core/core.py` | Configuration constants (`LLM_MODEL_NAME`, `DEFAULT_LLM_PROVIDER`) |
| `backend/core/routes.py` | FastAPI endpoint `POST /api/spec/llm` |
| `frontend/js/llm.js` | UI handler — form submission, diff display, history |
| `scripts/evaluate_llm.py` | Standalone evaluation script (also uses GitHub Models) |
| `.env` | `GITHUB_TOKEN` lives here |

### The OpenAI Client Setup

```python
# backend/llm/llm.py

def _get_openai_client(api_key: Optional[str]):
    """Get an OpenAI-compatible client routed through GitHub Models."""
    if OpenAI is None:
        raise RuntimeError("openai package is not installed.")

    # Priority: UI-provided key > .env GITHUB_TOKEN
    key = api_key or os.environ.get("GITHUB_TOKEN")
    if not key:
        raise RuntimeError("Provide GITHUB_TOKEN (either in the form field or as an env var).")

    return OpenAI(
        base_url="https://models.github.ai/inference",
        api_key=key,
    )
```

**Key detail:** The `api_key` parameter comes from the browser's form field. If the user pasted a token in the UI, it's sent in the request body and used here. If not, the server falls back to `GITHUB_TOKEN` from `.env`.

### The Model Name

GitHub Models requires vendor-prefixed model names:

```python
# backend/core/core.py
LLM_MODEL_NAME = os.environ.get("LLM_MODEL", "openai/gpt-4.1")
```

This is different from the OpenAI API which uses bare names like `gpt-4o`. On GitHub Models:
- `openai/gpt-4.1` (not `gpt-4.1`)
- `openai/gpt-4o-mini` (not `gpt-4o-mini`)

### System Prompt Construction

The LLM doesn't just get the user's instruction — it gets a rich system prompt that includes:

1. **Base rules** — "Return ONLY valid JSON", "Preserve existing fields", component dependency rules
2. **JSON Schema** — The full `mob_spec.schema.json` so the model knows the exact structure
3. **Vanilla Reference** — Real component examples from Minecraft's bedrock-samples repository

This context is what makes the LLM produce structurally valid Bedrock JSON rather than hallucinated nonsense.

### Response Validation

After the LLM returns JSON, it goes through `validate_spec()` which checks:
- All required fields present (`identifier`, `display_name`, `short_name`)
- Field types match schema (strings, numbers, arrays)
- Identifier format is correct (`namespace:mob_name`)
- No invalid component combinations

If validation fails, a `SpecValidationError` is raised and the user sees the error in the UI.

---

## 6. Configuration Reference

### Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `GITHUB_TOKEN` | *(none)* | GitHub Personal Access Token for GitHub Models |
| `LLM_MODEL` | `openai/gpt-4.1` | Default model for OpenAI provider |
| `LLM_PROVIDER` | `openai` | Default LLM provider |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Model for DeepSeek provider |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Model for Google Gemini provider |
| `CLAUDE_MODEL` | `claude-3-5-sonnet-20240620` | Model for Anthropic Claude provider |
| `OLLAMA_MODEL` | `llama3.2` | Model for local Ollama provider |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |

### Supported Providers

The app supports multiple LLM providers. The user selects one from the dropdown in the UI:

| Provider | API Key Env Var | Endpoint | Cost |
|---|---|---|---|
| **OpenAI** (via GitHub Models) | `GITHUB_TOKEN` | `models.github.ai/inference` | Free |
| **Claude** | `ANTHROPIC_API_KEY` | `api.anthropic.com` | Paid |
| **DeepSeek** | `DEEPSEEK_API_KEY` | `api.deepseek.com` | Paid |
| **Gemini** | `GEMINI_API_KEY` | Google GenAI SDK | Free tier available |
| **Ollama** | *(none)* | `localhost:11434` | Free (local) |
| **Mock** | *(none)* | Local hardcoded responses | Free (for testing) |

---

## 7. Available Models

GitHub Models hosts many models. For OpenAI models, use the `openai/` prefix:

| Model ID (for GitHub Models) | Description |
|---|---|
| `openai/gpt-4.1` | Latest GPT-4.1 — strong coding + instruction following |
| `openai/gpt-4.1-mini` | Smaller, faster, cheaper variant |
| `openai/gpt-4.1-nano` | Smallest variant, fastest responses |
| `openai/gpt-4o` | GPT-4o multimodal |
| `openai/gpt-4o-mini` | Smaller GPT-4o |
| `openai/o4-mini` | Reasoning model |

To use a different model, set `LLM_MODEL` in your `.env`:
```
LLM_MODEL=openai/gpt-4o-mini
```

Full catalog: [github.com/marketplace/models](https://github.com/marketplace/models)

---

## 8. Using It in the Web App

1. **Start the server:**
   ```bash
   python run.py
   ```

2. **Open the browser** at `http://127.0.0.1:7860`

3. **Select a mob** from the sidebar (or create a new one)

4. **In the LLM Assistant panel:**
   - **Provider:** Select "OpenAI" from the dropdown
   - **API Key:** Paste your `ghp_...` token (or leave blank if it's in `.env`)
   - **Prompt:** Type your instruction (e.g., "make the mob do double damage and fly")
   - Click **"Ask LLM"**

5. **The response:**
   - The JSON editor updates with the modified spec
   - A diff view shows what changed (green = added, red = removed)
   - The change is saved to LLM History for undo/reuse

### Where the API Key Lives

- **In `.env`:** Loaded server-side. You never need to paste it in the UI.
- **In the UI field:** Stored in `localStorage` (browser-only). Sent to the backend in the request body. Takes priority over `.env`.
- **Never sent to third parties:** The key goes from your browser → your local FastAPI server → GitHub Models. That's it.

---

## 9. Using It in the Evaluation Script

The evaluation script (`scripts/evaluate_llm.py`) also uses GitHub Models for the OpenAI provider:

```bash
# Run all tests with GPT-4.1 via GitHub Models
python scripts/evaluate_llm.py --provider openai

# Use a specific model
python scripts/evaluate_llm.py --provider openai --model openai/gpt-4o-mini

# Filter to one category
python scripts/evaluate_llm.py --provider openai -c entity_logic_ai -v
```

The script reads `GITHUB_TOKEN` from `.env` (loaded by the script itself). The same `base_url` and auth logic applies.

---

## 10. Troubleshooting

### "GITHUB_TOKEN environment variable not set"
- Add `GITHUB_TOKEN=ghp_...` to your `.env` file, OR paste the token in the UI's API Key field

### "Unknown model: /gpt-4o" or similar
- GitHub Models requires vendor-prefixed names: `openai/gpt-4.1`, not `gpt-4o`
- Set `LLM_MODEL=openai/gpt-4.1` in your `.env`

### "Incorrect API key provided"
- You're using an OpenAI API key instead of a GitHub token
- GitHub tokens start with `ghp_`
- Generate one at [github.com/settings/tokens](https://github.com/settings/tokens)

### "Rate limit exceeded"
- GitHub Models has rate limits (~150 req/day free, more with Pro)
- Wait a few minutes and try again, or use a different provider (Ollama is unlimited locally)

### "openai package is not installed"
- Run: `pip install openai` (should already be in `requirements.txt`)

### LLM returns bad/invalid JSON
- The system prompt includes schema and rules, but models can still hallucinate
- The validator catches most issues and returns an error
- Try rephrasing your prompt to be more specific
- GPT-4.1 tends to be more reliable than smaller models for structured output
