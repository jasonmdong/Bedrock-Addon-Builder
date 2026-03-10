# ⚒️ Mob Forge — Minecraft Bedrock Mob Creator

Create custom Minecraft Bedrock mobs with AI! Describe any mob in natural language, get a complete entity with behaviors, stats, textures, and a downloadable `.mcaddon` pack.

## Architecture

```
┌─────────────────────────┐     MCP (stdio)     ┌──────────────────┐
│  Mob Forge Web App      │◄──────────────────► │  MCP Server      │
│  (FastAPI + HTML/JS)    │                      │  (FastMCP)       │
│                         │                      │                  │
│  • Create mobs          │                      │  • generate_mob  │
│  • Mob gallery          │                      │  • build_pack    │
│  • Texture studio       │                      │  • gen_texture   │
│  • Download .mcaddon    │                      └──────────────────┘
└─────────────────────────┘                              │
                                                         ▼
                                                   GitHub Models
                                                   (GPT-4o, free)
```

## Quick Start

### 1. Set up your GitHub Token

Get a [GitHub PAT](https://github.com/settings/tokens) with `models:read` permission:

```bash
# Windows PowerShell
$env:GITHUB_TOKEN = "your_github_pat_here"

# Linux/Mac
export GITHUB_TOKEN="your_github_pat_here"
```

### 2. Install dependencies

```bash
pip install fastapi uvicorn "mcp[cli]" openai Pillow
```

### 3. Run the app

```bash
cd MCP
python -m uvicorn mob_forge_app.app:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** in your browser.

## MCP Tools

| Tool | Description |
|---|---|
| `generate_mob` | Describe a mob → get valid Bedrock entity JSON |
| `build_mob_pack` | Select mobs → download `.mcaddon` ZIP |
| `generate_mob_texture` | Generate AI pixel-art textures |

## Features

- **Mob Creator** — Type "a fire-breathing dragon" → AI generates a complete Bedrock entity
- **Mob Gallery** — View all mobs with stats, textures, and actions
- **Texture Studio** — Pick colors, choose body style, generate pixel art
- **Pack Builder** — Select mobs, build & download `.mcaddon` for Minecraft Bedrock

## VS Code / Copilot Integration

The `.vscode/mcp.json` config lets Copilot Agent mode use these tools too.

## Tech Stack

- **MCP Server**: Python + FastMCP (stdio transport)
- **LLM**: GitHub Models (GPT-4o, free tier)
- **Web Backend**: FastAPI (MCP client via `mcp.client.stdio`)
- **Web Frontend**: Vanilla HTML/CSS/JS, dark theme, glassmorphism
