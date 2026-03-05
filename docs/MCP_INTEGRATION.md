# Minecraft Creator Tools (MCP) Integration — Technical Documentation

**Date:** March 3, 2026
**Status:** v1.0 — Working End-to-End

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [MCP Protocol Details](#mcp-protocol-details)
4. [Backend Implementation](#backend-implementation)
5. [Frontend Implementation](#frontend-implementation)
6. [Available Tools](#available-tools)
7. [Configuration](#configuration)
8. [Setup & Installation](#setup--installation)
9. [Troubleshooting](#troubleshooting)

---

## Overview

The Bedrock Addon Builder integrates with **Minecraft Creator Tools (mctools-int)**, a Node.js MCP server that exposes Mojang's official content validation, model design, and project scaffolding tools over the **Model Context Protocol (MCP)**.

The integration follows a proxy architecture:

```
Frontend (browser)
    ↓  REST API calls
Backend (FastAPI / Python)
    ↓  JSON-RPC over HTTP (MCP Streamable HTTP transport)
mctools-int (Node.js MCP server, port 6126)
    ↓  Minecraft Creator Tools engine
Validation results, model templates, project scaffolding, etc.
```

The backend auto-starts the mctools Node.js server as a subprocess on the first tool call (lazy initialization). No manual server management is required.

---

## Architecture

### Components

| Component | Language | Location | Role |
|-----------|----------|----------|------|
| MCP Client | Python | `backend/mctools/client.py` | Session management, SSE parsing, subprocess lifecycle |
| API Routes | Python | `backend/mctools/routes.py` | 14 FastAPI endpoints proxying to MCP tools |
| Route Registration | Python | `backend/core/app.py` | Mounts `/api/mctools/*` routes |
| Frontend Module | JavaScript | `frontend/js/mctools.js` | Health polling, UI event handlers |
| Frontend UI | HTML | `frontend/index.html` | "Minecraft Creator Tools" card section |
| mctools Server | Node.js | `McpGettingStarted/mctools-int-0.0.1/package/` | MCP server (Mojang's tools) |

### Data Flow (Tool Call)

```
1. User clicks "Validate" button in browser
2. frontend/js/mctools.js → POST /api/mctools/validate { content: "..." }
3. backend/mctools/routes.py → mctools_validate() → call_tool("validateContent", {...})
4. backend/mctools/client.py:
   a. _ensure_session() — starts mctools subprocess if needed, initializes MCP session
   b. Sends JSON-RPC POST to http://localhost:6126/mcp
   c. Receives SSE response (text/event-stream)
   d. _parse_sse() → extracts JSON-RPC result from "data:" lines
   e. Returns { "content": [...], "isError": false }
5. Route handler returns JSON to frontend
6. Frontend displays result in output panel
```

---

## MCP Protocol Details

### Transport: Streamable HTTP

The MCP SDK uses **Streamable HTTP** transport, not plain REST. Key differences:

- **Single endpoint:** All requests go to `POST /mcp`
- **Session-based:** First request initializes a session; subsequent requests include `mcp-session-id` header
- **SSE responses:** The server returns `Content-Type: text/event-stream`, not `application/json`
- **Accept header required:** Client MUST send `Accept: application/json, text/event-stream`

### Session Lifecycle

```
1. POST /mcp (no session header)
   Body: { "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {...} }
   Response headers: mcp-session-id: <uuid>
   Response body (SSE): event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{...}}\n\n

2. POST /mcp (with session header)
   Body: { "jsonrpc": "2.0", "method": "notifications/initialized" }
   (notification, no response expected)

3. POST /mcp (with session header)
   Body: { "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "validateContent", "arguments": {...}} }
   Response body (SSE): event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"content":[...],"isError":false}}\n\n
```

### SSE Response Format

The MCP SDK wraps all responses in Server-Sent Events:

```
event: message
data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26","capabilities":{...},"serverInfo":{"name":"minecraft-creator-tools","version":"0.0.1"}}}

```

Our client parses this by scanning for `data: ` prefixed lines and JSON-decoding them.

### DNS Rebinding Protection

The MCP transport has DNS rebinding protection with `allowedHosts: ["127.0.0.1"]`. However, the mctools HTTP server binds to `localhost` (which resolves to `::1` on Windows IPv6). We work around this by overriding the `Host` header to `127.0.0.1:6126` on all MCP requests while connecting via `localhost`.

---

## Backend Implementation

### `backend/mctools/client.py`

The core MCP client module. Key functions:

#### `_parse_sse(text: str) -> list[dict]`
Parses SSE response body into JSON-RPC message dicts by extracting `data:` lines.

#### `_extract_response(text: str, content_type: str, request_id: int) -> dict`
Handles both JSON and SSE response formats. Matches response to request ID.

#### `_start_mctools_server() -> None`
Starts the mctools Node.js server as a subprocess:
- Checks that `node_modules` exists (requires prior `npm install`)
- Runs `node cli/index.mjs serve --adminpc mctadm01 --port 6126`
- Polls `GET http://localhost:6126/` until the server responds (up to 30s)

#### `stop_mctools_server() -> None`
Terminates the mctools subprocess. Called automatically on FastAPI shutdown via `@app.on_event("shutdown")`.

#### `_ensure_session() -> str`
Lazy session initialization:
1. If session exists, returns it
2. Starts mctools server if not running
3. Sends `initialize` JSON-RPC request
4. Extracts `mcp-session-id` from response headers
5. Sends `notifications/initialized` notification
6. Returns session ID

#### `call_tool(tool_name: str, arguments: dict) -> dict`
Main entry point for tool invocation:
1. Ensures session is active
2. Sends `tools/call` JSON-RPC request
3. Parses SSE response
4. Handles session expiry (auto-reinitializes on 400 response)
5. Returns `{"content": [...], "isError": bool}`

#### `is_available() -> bool`
Non-throwing health check. Returns True if session can be established.

### `backend/mctools/routes.py`

14 FastAPI route handlers, each:
1. Validates required fields from request body
2. Calls `call_tool()` with the appropriate MCP tool name and arguments
3. Returns JSON response with `{"ok": true, "content": [...]}` or error

### Route Registration (`backend/core/app.py`)

Routes are registered as:
```python
app.get("/api/mctools/health")(mctools_health)
app.post("/api/mctools/validate")(mctools_validate)
# ... 12 more routes
```

Shutdown hook:
```python
@app.on_event("shutdown")
def shutdown_event():
    stop_mctools_server()
```

---

## Frontend Implementation

### `frontend/js/mctools.js`

- **`checkMctoolsHealth()`** — Polls `GET /api/mctools/health` every 30s, updates status badge
- **`mctoolsValidateCurrentMob()`** — Sends current mob spec to `/api/mctools/validate`
- **`mctoolsLoadModelTemplates()`** — Fetches template from `/api/mctools/model-templates`
- **`mctoolsDesignModel()`** — Sends design JSON to `/api/mctools/design-model`
- **`initMctools()`** — Wires up button listeners, starts health polling

### `frontend/index.html`

Added "Minecraft Creator Tools" section with:
- Status badge (Connected / Starting / Disabled)
- Content Validation panel with "Validate with Creator Tools" button
- Model Templates panel with type selector dropdown
- Design Model panel with JSON textarea
- Output `<pre>` element for results

Script loaded as `<script src="js/mctools.js?v=1"></script>` before `app.js`.
Initialized via `safe("initMctools", ...)` in `app.js` `initApp()`.

---

## Available Tools

### In-Scope (No Bedrock Dedicated Server Required)

| API Endpoint | MCP Tool | Description |
|---|---|---|
| `POST /api/mctools/validate` | `validateContent` | Validate JSON or base64 ZIP content against Bedrock schemas |
| `POST /api/mctools/validate-file` | `validateFile` | Validate content at a file path |
| `POST /api/mctools/create-project` | `createProject` | Scaffold a new Minecraft addon project |
| `POST /api/mctools/add-item` | `addItem` | Add an item to an existing project |
| `POST /api/mctools/create-content` | `createMinecraftContent` | Create content from meta-schema definition |
| `POST /api/mctools/content-schema` | `getEffectiveContentSchema` | Get the effective content schema for a project |
| `POST /api/mctools/design-model` | `designModel` | Design a 3D entity model (geometry + texture) |
| `POST /api/mctools/design-structure` | `designStructure` | Design a block structure |
| `GET /api/mctools/model-templates` | `getModelTemplates` | Get starter geometry templates by type |
| `POST /api/mctools/read-image` | `readImageFile` | Read an image file as base64 |
| `POST /api/mctools/write-image` | `writeImageFile` | Write base64 image data to file |
| `POST /api/mctools/write-image-svg` | `writeImageFileFromSvg` | Convert SVG to PNG |
| `POST /api/mctools/write-image-pixel-art` | `writeImageFileFromPixelArt` | Create PNG from pixel art palette |
| `GET /api/mctools/health` | (internal) | Check if mctools is enabled and reachable |

### Out-of-Scope (Require BDS — Not Implemented)

These tools require a running Bedrock Dedicated Server and are not exposed:
- `runMinecraftCommand`, `runGameTest`, `getBlockAtPosition`, `getEntityAtPosition`, etc.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MCTOOLS_ENABLED` | `true` | Enable/disable the integration |
| `MCTOOLS_MCP_URL` | `http://localhost:6126/mcp` | MCP endpoint URL |
| `MCTOOLS_TIMEOUT_MS` | `30000` | Timeout for MCP requests (milliseconds) |
| `MCTOOLS_ADMIN_PASSCODE` | `mctadm01` | Admin passcode for mctools server (must be exactly 8 lowercase alphanumeric characters) |

Set these in a `.env` file at the project root (see `.env.example`).

---

## Setup & Installation

### Prerequisites
- **Node.js v20+** (for mctools server)
- **Python 3.12+** (for FastAPI backend)
- **mctools-int package** at `McpGettingStarted/mctools-int-0.0.1/package/`

### Steps

1. **Install mctools dependencies** (one-time):
   ```bash
   cd McpGettingStarted/mctools-int-0.0.1/package
   npm install
   ```
   > `node_modules/` is gitignored — this stays local only.

2. **Start the web app** (mctools auto-starts on first use):
   ```bash
   python -m uvicorn backend.core.app:app --host 127.0.0.1 --port 7860 --reload
   ```

3. **Verify** — open `http://127.0.0.1:7860` and scroll to the "Minecraft Creator Tools" section. The status badge should show "Connected" (may take a few seconds on first load as mctools starts).

---

## Troubleshooting

### "mctools not available" / Badge shows "Starting..."
- The mctools server takes ~5–10 seconds to start on first request
- Check that `npm install` was run in the package directory
- Check that Node.js v20+ is installed: `node -v`

### "Improperly formatted admin passcode"
- The passcode must be **exactly 8 lowercase alphanumeric characters**
- Default: `mctadm01`. No hyphens, no uppercase.

### Session expired / 400 errors
- The client auto-reinitializes on session expiry
- If persistent, restart the FastAPI server (which kills the mctools subprocess)

### DNS rebinding / connection refused
- On Windows, `localhost` may resolve to `::1` (IPv6) while MCP expects `127.0.0.1`
- The client works around this by overriding the `Host` header
- If issues persist, try setting `MCTOOLS_MCP_URL=http://127.0.0.1:6126/mcp`

### mctools server won't start
- Check logs: the subprocess stdout is captured and included in error messages
- Ensure port 6126 is not already in use: `netstat -ano | findstr 6126`
- Kill stale processes: `Get-Process -Name node | Stop-Process -Force`
