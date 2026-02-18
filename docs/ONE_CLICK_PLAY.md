# One-Click Play: Complete Implementation Guide

> Master technical document covering the full implementation of the Minecraft Bedrock auto-launch, auto-summon, and in-browser testing system.

**Last updated:** February 17, 2026

---

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Prerequisites & Setup](#prerequisites--setup)
4. [Quick Start](#quick-start)
5. [Implementation Details](#implementation-details)
   - [Phase 1: Server Setup](#phase-1-server-setup-setup_server)
   - [Phase 2: BDS Process Management](#phase-2-bds-process-management)
   - [Phase 3: Client Launch & Auto-Connect](#phase-3-client-launch--auto-connect)
   - [Phase 4: The "Magic" — Auto Summon/Give](#phase-4-the-magic--auto-summongive)
   - [Phase 5: Frontend Integration](#phase-5-frontend-integration)
   - [Phase 6: API Endpoints](#phase-6-api-endpoints)
6. [Complete Code Reference](#complete-code-reference)
7. [Server Configuration](#server-configuration)
8. [Threading Model](#threading-model)
9. [Windows-Specific Technical Details](#windows-specific-technical-details)
10. [Bugs Fixed During Development](#bugs-fixed-during-development)
11. [Known Limitations](#known-limitations)
12. [Troubleshooting](#troubleshooting)

---

## Overview

The One-Click Play system bridges the gap between **generating** a Minecraft Bedrock add-on in the web UI and **seeing it in-game**. Instead of manually copying packs, configuring servers, and typing commands, the entire lifecycle is automated.

There are **two entry points**:

1. **Web UI** — Click the **🎮 Test in Game** button on `localhost:7860`. The FastAPI backend builds the addon, starts BDS, launches Minecraft, and summons the entity.
2. **CLI** — Run `python scripts/evaluate_llm.py -c entity_logic_ai --launch`. The evaluation framework runs LLM tests, takes the first passing result, and launches it.

Both paths converge on the same core script: `scripts/launch_server_session.py`.

---

## System Architecture

```
 ┌──────────────────────────────────────────────────────────────────┐
 │                    ENTRY POINT 1: Web UI                        │
 │                                                                  │
 │  Browser (localhost:7860)                                        │
 │    └─ Click "🎮 Test in Game"                                    │
 │         └─ POST /api/launch-test  { specs: [...], category }    │
 │                                                                  │
 │  FastAPI Backend (backend/app.py → backend/routes.py)           │
 │    ├─ validate_spec() on each mob spec                          │
 │    ├─ build_addon(specs, out_dir, None, None)                   │
 │    ├─ Extract beh_mcpack.zip → bds_bp/ folder                  │
 │    ├─ Extract res_mcpack.zip → bds_rp/ folder                  │
 │    └─ Start background thread → _run_server_session_thread()    │
 │                                                                  │
 │  Frontend polls GET /api/launch-test/status every 1.5s          │
 │  Frontend can POST /api/launch-test/stop to kill the server     │
 └──────────────────────────────────────────────────────────────────┘

 ┌──────────────────────────────────────────────────────────────────┐
 │                    ENTRY POINT 2: CLI                            │
 │                                                                  │
 │  python scripts/evaluate_llm.py -c entity_logic_ai --launch    │
 │    ├─ Load test cases from data/test_cases.json                 │
 │    ├─ Run through LLM provider (mock/ollama/openai/anthropic)   │
 │    ├─ Validate output (schema + semantic checks)                │
 │    ├─ Write first passing result to temp/<name>_pack/           │
 │    └─ Call launch_server_session(pack_path, category)           │
 └──────────────────────────────────────────────────────────────────┘

 ┌──────────────────────────────────────────────────────────────────┐
 │              CORE: launch_server_session.py                      │
 │                                                                  │
 │  setup_server(bp_path, rp_path)                                 │
 │    ├─ Pre-flight checks (BDS exists, vanilla packs present)     │
 │    ├─ Clean non-vanilla packs from behavior_packs/ & resource_packs/
 │    ├─ Deploy BP → bedrock_server/behavior_packs/<name>/         │
 │    ├─ Deploy RP → bedrock_server/resource_packs/<name>/         │
 │    ├─ Delete old world folder (fresh world every time)          │
 │    ├─ Write world_behavior_packs.json (auto-enable BP)          │
 │    ├─ Write world_resource_packs.json (auto-enable RP)          │
 │    └─ Write server.properties (creative/flat/peaceful)          │
 │                                                                  │
 │  _kill_minecraft_client()                                        │
 │    └─ taskkill /F /IM Minecraft.Windows.exe /T                  │
 │                                                                  │
 │  Start bedrock_server.exe via subprocess.Popen                  │
 │    ├─ Background thread reads stdout, sets threading.Events     │
 │    ├─ Main thread waits for "Server started" (bail on fatal)    │
 │    ├─ Kill stale Minecraft → wait 3s → launch minecraft:// URI  │
 │    ├─ Wait for "Player Spawned" → wait 2s → send /summon       │
 │    ├─ If "No targets matched" → retry once after 3s             │
 │    └─ Keep alive until Ctrl+C or API stop                       │
 └──────────────────────────────────────────────────────────────────┘

 ┌──────────────────────┐     ┌──────────────────────────┐
 │  bedrock_server/     │     │  Minecraft Client        │
 │                      │◄────│  (launched via URI)      │
 │  bedrock_server.exe  │     │                          │
 │  behavior_packs/     │     │  Player spawns →         │
 │  resource_packs/     │     │  Entity summoned with    │
 │  worlds/             │     │  full textures & model   │
 │  server.properties   │     │                          │
 └──────────────────────┘     └──────────────────────────┘
```

### Files Modified/Created

| File | What Was Done |
|------|---------------|
| `scripts/launch_server_session.py` | **Created.** Core BDS lifecycle: setup, launch, log monitoring, auto-summon, cleanup |
| `scripts/launch_preview.py` | **Modified.** Fixed duplicate `world_behavior_packs.json` zip warning |
| `scripts/evaluate_llm.py` | **Modified.** Added `--launch` flag integration, BDS primary with `.mcworld` fallback |
| `backend/routes.py` | **Modified.** Added 3 API endpoints + background thread for server session |
| `backend/app.py` | **Modified.** Registered 3 new routes |
| `frontend/index.html` | **Modified.** Added Test in Game button, status bar, log viewer, stop button, JS polling |

---

## Prerequisites & Setup

### 1. Bedrock Dedicated Server (BDS)

Download and extract into `bedrock_server/` at the project root:

```powershell
# Download from:
# https://www.minecraft.net/en-us/download/server/bedrock

# Extract EVERYTHING (not just top-level files):
Expand-Archive -Path bedrock-server-*.zip -DestinationPath bedrock_server/
```

**Verify these exist:**
```
bedrock_server/
├── bedrock_server.exe          ← the server binary
├── behavior_packs/
│   └── vanilla/                ← MUST exist
├── resource_packs/
│   └── vanilla/
│       └── manifest.json       ← MUST exist (BDS won't start without it)
└── ...
```

### 2. Windows Loopback Exemption (one-time, as Administrator)

Minecraft is a UWP (Windows Store) app. By default, UWP apps **cannot connect to localhost**. This is a Windows security restriction. You must run this command **once, ever**, in an elevated terminal:

```powershell
# Official Microsoft SID-based command (from BDS documentation):
CheckNetIsolation.exe LoopbackExempt -a -p=S-1-15-2-1958404141-86561845-1752920682-3514627264-368642714-62675701-733520436
```

**Why this specific SID?** It's the security identifier for the Minecraft UWP package. The older `-n="Microsoft.MinecraftUWP_8wekyb3d8bbwe"` approach is less reliable. This SID-based command comes directly from Microsoft's BDS documentation.

### 3. Minecraft Bedrock Edition

Must be installed from the Microsoft Store. The script launches it via the `minecraft://` protocol handler.

### 4. Python Environment

```powershell
# Activate the venv (has FastAPI, uvicorn, etc.)
venv\Scripts\activate

# Start the web server
python run.py
# → http://localhost:7860
```

---

## Quick Start

### From the Web UI (recommended)

1. Start the server: `python run.py` (from venv)
2. Open `http://localhost:7860`
3. Create or select a mob in the sidebar (click on it so it's the **active** mob)
4. Click **🎮 Test in Game** — only the active mob is sent
5. Watch the status bar — when it says "Server ready!", Minecraft launches
6. In Minecraft: **Play → Friends → LAN Games → "Bedrock Addon Test"**
7. Your entity is summoned automatically when you spawn

### From the CLI

```powershell
# Mock provider (no API key needed)
python scripts/evaluate_llm.py -c entity_logic_ai --launch

# With a real LLM
python scripts/evaluate_llm.py -c entity_logic_ai -p ollama -m qwen2.5-coder:7b --launch
python scripts/evaluate_llm.py -c items_weaponry -p openai -m gpt-4o --launch

# Standalone (skip evaluation, just launch a pack folder)
python scripts/launch_server_session.py temp/my_pack_folder entity_logic_ai
```

---

## Implementation Details

### Phase 1: Server Setup (`setup_server()`)

**File:** `scripts/launch_server_session.py` lines 61–167

This function prepares BDS to run with the generated addon.

#### Pre-flight Checks

```python
# 1. BDS directory exists
if not BDS_DIR.exists():
    raise FileNotFoundError("Bedrock Dedicated Server not found...")

# 2. bedrock_server.exe exists
if not BDS_EXE.exists():
    raise FileNotFoundError("bedrock_server.exe not found...")

# 3. Pack has manifest.json
if not (pack_path / "manifest.json").exists():
    raise FileNotFoundError("No manifest.json in pack...")

# 4. Vanilla resource pack exists (BDS CANNOT start without it)
_has_vanilla_rp = any(
    (rp_dir / d / "manifest.json").exists()
    for d in ("vanilla", "vanilla_base")
    if (rp_dir / d).exists()
)
```

#### Pack Cleaning (preserve vanilla)

Only non-vanilla packs are removed. Vanilla packs are identified by prefix:

```python
_VANILLA_PREFIXES = ("vanilla", "chemistry", "experimental")
for child in d.iterdir():
    if child.is_dir() and not child.name.startswith(_VANILLA_PREFIXES):
        shutil.rmtree(child)
```

#### Pack Deployment

Both behavior pack AND resource pack are deployed:

```python
# Behavior pack → bedrock_server/behavior_packs/<name>/
shutil.copytree(pack_path, bp_dir / pack_name)

# Resource pack → bedrock_server/resource_packs/<name>/  (if provided)
if resource_pack_path and resource_pack_path.exists():
    shutil.copytree(resource_pack_path, rp_dir / rp_name)
```

#### Fresh World Every Time

The old world is **deleted** before each run:

```python
world_dir = BDS_DIR / "worlds" / "Bedrock-Addon-Test"
if world_dir.exists():
    shutil.rmtree(world_dir)  # Delete old world
world_dir.mkdir(parents=True, exist_ok=True)
```

#### Auto-Enable Packs

Two JSON files tell BDS to load the packs in the world:

```python
# world_behavior_packs.json
[{"pack_id": "<uuid-from-manifest>", "version": [1, 0, 0]}]

# world_resource_packs.json (only if RP was deployed)
[{"pack_id": "<uuid-from-rp-manifest>", "version": [1, 0, 0]}]
```

#### Server Properties

Written to `bedrock_server/server.properties`:

```properties
server-name=Bedrock Addon Test
gamemode=creative
difficulty=peaceful
allow-cheats=true
level-name=Bedrock-Addon-Test
level-type=flat
online-mode=false
server-port=19132
server-portv6=19133
max-players=1
view-distance=10
tick-distance=4
player-idle-timeout=0
default-player-permission-level=operator
texturepack-required=false
content-log-file-enabled=true
```

**Key choices:**
- **`gamemode=creative`** — so commands work and you can fly
- **`level-type=flat`** — fast world generation, clean testing surface
- **`difficulty=peaceful`** — no hostile mobs interfering
- **`online-mode=false`** — no Xbox Live authentication required
- **`default-player-permission-level=operator`** — full command access immediately
- **`allow-cheats=true`** — required for `/summon` and `/give`

---

### Phase 2: BDS Process Management

**File:** `scripts/launch_server_session.py` lines 174–201, 352–444

#### Starting the Process

```python
proc = subprocess.Popen(
    [str(BDS_EXE)],
    cwd=str(BDS_DIR),       # CRITICAL: BDS resolves paths relative to cwd
    stdin=subprocess.PIPE,   # So we can send commands later
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,               # String mode (not bytes)
    bufsize=1,               # Line-buffered
)
```

**Why `text=True`?** BDS outputs UTF-8 text. Using text mode with `bufsize=1` gives us line-buffered reading, which is essential for real-time log monitoring.

**Why `cwd=str(BDS_DIR)`?** BDS resolves all relative paths (packs, worlds, properties) from its working directory. Without this, it can't find anything.

#### Log Monitoring Thread

A daemon thread reads BDS stdout and sets `threading.Event` objects:

```python
def _read_server_output(proc, event_server_ready, event_player_spawned,
                        event_fatal_error, event_no_targets, log_lines):
    for line in iter(proc.stdout.readline, ""):
        line = line.rstrip()
        log_lines.append(line)

        if "Server started" in line:           event_server_ready.set()
        if "Player Spawned" in line:           event_player_spawned.set()
        if "Failed to load Vanilla" in line:   event_fatal_error.set()
        if "No targets matched" in line:       event_no_targets.set()
```

| Event | BDS Log Trigger | What Happens |
|-------|----------------|--------------|
| `event_server_ready` | `[INFO] Server started.` | Proceed to launch Minecraft |
| `event_player_spawned` | `[INFO] Player Spawned: <name>` | Proceed to auto-summon |
| `event_fatal_error` | `Failed to load Vanilla Resource Pack` | Kill server, print fix instructions |
| `event_no_targets` | `No targets matched selector` | Retry the summon command |

#### Wait Loop (bail early on fatal)

Instead of blocking for 120 seconds, the main thread polls every second:

```python
while not event_server_ready.is_set():
    if event_fatal_error.wait(timeout=1):
        proc.kill()
        return  # bail immediately
    if event_server_ready.wait(timeout=1):
        break
    if proc.poll() is not None:
        return  # process died
```

---

### Phase 3: Client Launch & Auto-Connect

**File:** `scripts/launch_server_session.py` lines 204–235

#### Force-Kill Stale Minecraft

Windows UWP apps often stay "suspended" in memory even after closing the window. If Minecraft is already running, the `minecraft://Connect` URI just brings the window to the front **without triggering the connection**.

```python
def _kill_minecraft_client():
    subprocess.run(
        ["taskkill", "/F", "/IM", "Minecraft.Windows.exe", "/T"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
```

**Flags:**
- `/F` — Force kill (don't ask nicely)
- `/IM Minecraft.Windows.exe` — Match by image name
- `/T` — Kill child processes too

This runs **twice**: once before BDS starts (clean slate), and once right before launching the URI (kill anything that respawned).

#### 3-Second Delay

After killing Minecraft, we wait 3 seconds for Windows to fully release the process handle:

```python
_kill_minecraft_client()
time.sleep(3)  # let Windows fully release the process
_launch_client()
```

#### Protocol Handler URI

```python
uri = "minecraft://Connect?ip=127.0.0.1&port=19132"
os.startfile(uri)  # Windows
```

**Known limitation:** The `minecraft://Connect` URI is **unreliable on Windows UWP**. It works ~50% of the time. When it fails, the player lands on the Main Menu instead of auto-joining. The fallback is:

> **Play → Friends → LAN Games → "Bedrock Addon Test"**

The BDS server broadcasts on LAN automatically, so it always appears in the Friends tab.

---

### Phase 4: The "Magic" — Auto Summon/Give

**File:** `scripts/launch_server_session.py` lines 242–295

#### Identifier Detection

The script parses the generated pack's JSON files to find **all** content that was created:

```python
def _detect_identifiers(pack_path, category) -> list[str]:
    search_map = {
        "entity_logic_ai": ("entities", "minecraft:entity"),
        "items_weaponry":  ("items",    "minecraft:item"),
        "blocks_furniture": ("blocks",  "minecraft:block"),
    }
    # Returns ALL identifiers found, e.g. ["custom:cow", "custom:blaze"]
```

#### Command Building

```python
def _build_command(identifier, category):
    if category == "entity_logic_ai":
        return f"execute at @a run summon {identifier} ~ ~ ~"
    elif category == "blocks_furniture":
        return f"give @a {identifier} 64"
    else:
        return f"give @a {identifier}"
```

**Why `execute at @a run summon`?** The `execute at @a` targets the nearest player's position, then `summon` spawns the entity at `~ ~ ~` (the player's exact coordinates).

**Bedrock limitation:** No NBT data in commands. `{NoAI:1b}` syntax is Java Edition only. Bedrock commands only accept basic parameters.

#### Timing

```
BDS log: "Player Spawned: Doomyu7 xuid: ..."
    → wait 2 seconds (world fully loaded)
    → send: /execute at @a run summon custom:blaze ~ ~ ~
    → watch for "No targets matched selector" for 3s
        → if detected: wait 3s, retry once
    → done
```

**Why "Player Spawned" not "Player connected"?** The `connected` event fires when the network handshake completes, but the player entity doesn't exist yet. `@a` returns no targets. The `Spawned` event fires when the player is fully loaded into the world.

---

### Phase 5: Frontend Integration

**File:** `frontend/index.html`

#### Button HTML (sidebar footer)

```html
<button type="button" id="test-in-game"
  style="background: linear-gradient(135deg, #10b981, #059669); color: #fff;">
  🎮 Test in Game
</button>

<div id="test-session-bar">
  <span id="test-session-status">Idle</span>
  <button id="test-stop-btn" class="danger">Stop</button>
  <div id="test-session-log"></div>  <!-- monospace log viewer -->
</div>
```

#### Click Handler Flow

```javascript
testInGameBtn.addEventListener("click", async (e) => {
  // 1. Auto-save current spec (no need to manually save first)
  if (currentMobName) {
    const saved = await saveSpec();
    if (saved === null) return;  // validation failed
  }

  // 2. Use only the currently active mob (the one being edited)
  const activeMobSpec = getUserMob(currentMobName);
  const selectedSpecs = [activeMobSpec];

  // 3. POST to backend
  const res = await fetch("/api/launch-test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ specs: selectedSpecs, category: "entity_logic_ai" }),
  });

  // 4. Start polling for status updates
  _startTestPolling();
});
```

#### Status Polling (every 1.5 seconds)

```javascript
setInterval(async () => {
  const res = await fetch("/api/launch-test/status");
  const data = await res.json();
  // data = { running, status, error, log_count, recent_logs }

  // Color-coded status:
  //   starting → amber (#f59e0b)
  //   ready    → green (#10b981)
  //   error    → red (var(--danger))
  //   stopped  → gray (var(--hint))

  // Auto-scrolling log viewer shows last 20 BDS log lines
  testSessionLog.textContent = data.recent_logs.join("\n");
}, 1500);
```

#### Stop Button

```javascript
testStopBtn.addEventListener("click", async () => {
  await fetch("/api/launch-test/stop", { method: "POST" });
  // Sends "stop\n" to BDS stdin → graceful shutdown
});
```

---

### Phase 6: API Endpoints

**File:** `backend/routes.py` lines 466–694, `backend/app.py` lines 80–83

#### Route Registration

```python
# backend/app.py
app.post("/api/launch-test")(launch_test)
app.get("/api/launch-test/status")(launch_test_status)
app.post("/api/launch-test/stop")(launch_test_stop)
```

#### `POST /api/launch-test`

**Request:**
```json
{
  "specs": [{ "identifier": "custom:blaze", "short_name": "blaze", ... }],
  "category": "entity_logic_ai"
}
```

**What it does:**
1. Validates specs via `validate_spec()`
2. Calls `build_addon(specs, out_dir, None, None)` → produces `.mcpack` zips
3. Extracts `beh_mcpack` → `bds_bp/` folder
4. Extracts `res_mcpack` → `bds_rp/` folder (textures, models, client entity definitions)
5. Starts `_run_server_session_thread(bp_dir, rp_dir, category)` in a daemon thread

**Response:**
```json
{ "status": "starting", "message": "Test session is launching..." }
```

**Error (409):** If a session is already running:
```json
{ "detail": "A test session is already running. Stop it first." }
```

#### `GET /api/launch-test/status`

**Response:**
```json
{
  "running": true,
  "status": "ready",           // idle | starting | ready | error | stopped
  "error": null,
  "log_count": 42,
  "recent_logs": [
    "[api] Setting up server...",
    "[api] Server configured.",
    "[2026-02-17 14:59:27:009 INFO] Server started.",
    "[api] Server is READY on port 19132",
    "[api] Minecraft client launched.",
    "[api] Sent: /execute at @a run summon custom:blaze ~ ~ ~",
    "[2026-02-17 14:59:27:069 INFO] Object successfully summoned",
    "[api] Magic complete!"
  ]
}
```

#### `POST /api/launch-test/stop`

Sends `stop\n` to BDS stdin for graceful shutdown. Falls back to `proc.kill()` after 10 seconds.

**Response:**
```json
{ "status": "stopped", "message": "Server stopped." }
```

#### Global Session State

Only one test session can run at a time. State is managed via a module-level dict protected by a threading lock:

```python
_server_session_lock = threading.Lock()
_server_session = {
    "running": False,
    "thread": None,
    "proc": None,           # subprocess.Popen instance
    "status": "idle",       # idle | starting | ready | error | stopped
    "logs": [],             # all BDS log lines
    "error": None,          # error message string
}
```

---

## Complete Code Reference

### Files and Functions

#### `scripts/launch_server_session.py` (454 lines)

| Function | Lines | Description |
|----------|-------|-------------|
| `setup_server(pack_path, resource_pack_path)` | 61–167 | Pre-flight checks, clean packs, deploy BP+RP, delete old world, write pack lists, write server.properties |
| `_read_server_output(proc, events..., log_lines)` | 174–201 | Daemon thread: read BDS stdout, set threading events |
| `_kill_minecraft_client()` | 204–217 | `taskkill /F /IM Minecraft.Windows.exe /T` |
| `_launch_client()` | 220–235 | `os.startfile("minecraft://Connect?ip=127.0.0.1&port=19132")` |
| `_detect_identifiers(pack_path, category)` | 242–285 | Scan pack JSON for **all** entity/item/block identifiers |
| `_build_command(identifier, category)` | 287–295 | Build `/summon` or `/give` command string |
| `launch_server_session(pack_path, category, resource_pack_path)` | 302–444 | Main orchestrator: setup → launch BDS → connect client → magic → cleanup |

#### `backend/routes.py` (new section, lines 466–694)

| Function | Lines | Description |
|----------|-------|-------------|
| `_run_server_session_thread(pack_dir, rp_dir, category)` | 486–594 | Background thread: full BDS lifecycle via imported functions |
| `launch_test(payload)` | 597–663 | `POST /api/launch-test` — build addon, extract packs, start thread |
| `launch_test_status()` | 666–674 | `GET /api/launch-test/status` — return session state + logs |
| `launch_test_stop()` | 677–694 | `POST /api/launch-test/stop` — send "stop" to BDS, kill if needed |

#### `frontend/index.html` (new section, lines 537–548, 2745–2859)

| Element | Description |
|---------|-------------|
| `#test-in-game` button | Green gradient button in sidebar footer |
| `#test-session-bar` | Status bar with status text, stop button, log viewer |
| `#test-session-status` | Color-coded status label |
| `#test-session-log` | Monospace scrollable log (last 20 lines from BDS) |
| `#test-stop-btn` | Red stop button |
| `_startTestPolling()` | `setInterval` polling `/api/launch-test/status` every 1.5s |
| `_stopTestPolling()` | `clearInterval` |

---

## Threading Model

```
Main Thread (FastAPI/uvicorn)
  │
  ├─ POST /api/launch-test
  │    └─ Spawns daemon thread: _run_server_session_thread()
  │
  ├─ GET /api/launch-test/status
  │    └─ Reads _server_session dict (no lock needed for reads)
  │
  └─ POST /api/launch-test/stop
       └─ Writes to proc.stdin + kills process

_run_server_session_thread (daemon)
  │
  ├─ setup_server()          ← runs on this thread
  ├─ subprocess.Popen()      ← starts BDS process
  │    └─ Spawns daemon thread: _read_server_output()
  │         └─ Reads BDS stdout line-by-line
  │         └─ Sets threading.Events
  │         └─ Appends to session["logs"]
  ├─ Waits on events (server ready, player spawned)
  ├─ _kill_minecraft_client() + _launch_client()
  ├─ Writes commands to proc.stdin
  └─ proc.wait()             ← blocks until BDS exits or is killed
```

**Thread safety:** The `_server_session` dict is protected by `_server_session_lock` for write operations (starting a new session). Read operations (status polling) don't need the lock because Python's GIL ensures atomic dict reads.

---

## Windows-Specific Technical Details

### UWP Loopback Restriction

Windows Store (UWP) apps run in an **AppContainer sandbox** that blocks connections to `localhost` / `127.0.0.1`. This is a Windows security feature, not a Minecraft bug.

**The fix** (run once as Administrator):
```powershell
CheckNetIsolation.exe LoopbackExempt -a -p=S-1-15-2-1958404141-86561845-1752920682-3514627264-368642714-62675701-733520436
```

The SID `S-1-15-2-1958404141-...` is the security identifier for the Minecraft UWP package. This is the **official command from Microsoft's BDS documentation** and is more reliable than the older `-n="Microsoft.MinecraftUWP_8wekyb3d8bbwe"` approach.

### `taskkill` Command

```
taskkill /F /IM Minecraft.Windows.exe /T
```

| Flag | Meaning |
|------|---------|
| `/F` | Forcefully terminate (don't send WM_CLOSE) |
| `/IM Minecraft.Windows.exe` | Match by image name (process executable) |
| `/T` | Kill the process tree (all child processes) |

### `minecraft://` Protocol Handler

```
minecraft://Connect?ip=127.0.0.1&port=19132
```

This is an **undocumented** URI scheme registered by the Minecraft UWP app. It's supposed to launch Minecraft and auto-connect to the specified server. In practice, it's unreliable:

- **If Minecraft is not running:** Works ~50% of the time. Sometimes the app's splash screen swallows the URI parameters.
- **If Minecraft is already running:** Just brings the window to the front without connecting.

**Workaround:** The server broadcasts on LAN, so it always appears in **Play → Friends → LAN Games**.

### BDS Process on Windows

BDS (`bedrock_server.exe`) is a native Win32 console application (not UWP). It:
- Needs a real console (no `CREATE_NO_WINDOW`)
- Reads commands from stdin (one per line)
- Writes logs to stdout with timestamps like `[2026-02-17 14:59:27:009 INFO]`
- Responds to `stop` command for graceful shutdown

---

## Bugs Fixed During Development

### 1. "Failed to load Vanilla Resource Pack"

**Root cause:** BDS zip was partially extracted — `resource_packs/vanilla/` was missing.

**Fix:** Added pre-flight check in `setup_server()` that verifies vanilla packs exist before starting BDS. Added `event_fatal_error` to bail immediately instead of waiting 120 seconds.

### 2. Summon fired too early ("No targets matched selector")

**Root cause:** The original trigger was `"Player connected"`, which fires during the network handshake. The player entity doesn't exist yet, so `@a` returns nothing.

**Fix:** Changed trigger to `"Player Spawned"` + 2-second delay + automatic retry logic.

### 3. NBT syntax error (`Unexpected '{'`)

**Root cause:** Initial summon command used `{NoAI:1b}` — this is Java Edition NBT syntax. Bedrock Edition does not support NBT in commands.

**Fix:** Removed all NBT data from summon commands. Bedrock commands only accept basic parameters.

### 4. Entity invisible in-game

**Root cause:** Only the behavior pack was deployed to BDS. The resource pack (containing textures, models, and client entity definitions) was never copied.

**Fix:** Updated `setup_server()` to accept and deploy an optional `resource_pack_path`. Updated the API endpoint to extract both `beh_mcpack` and `res_mcpack` from build artifacts.

### 5. `build_addon()` missing positional arguments

**Root cause:** The API endpoint called `build_addon(specs, out_dir)` but the function signature requires `build_addon(specs, out_dir, res_src, beh_src, textures_dir=None)`.

**Fix:** Changed to `build_addon(specs, out_dir, None, None)`.

### 6. Same world persisting between tests

**Root cause:** The world folder was never deleted. BDS reused the existing world data, including old packs and terrain.

**Fix:** Added `shutil.rmtree(world_dir)` before creating the new world folder. Every test now starts with a fresh flat world.

### 7. BDS stdin writes failing (bytes vs strings)

**Root cause:** `subprocess.Popen` was opened with `text=True` but commands were being written as bytes (`cmd.encode("utf-8")`).

**Fix:** Changed all `proc.stdin.write()` calls to write strings directly.

### 8. Vanilla packs deleted during cleanup

**Root cause:** The pack cleaning loop unconditionally deleted all directories in `behavior_packs/` and `resource_packs/`, including vanilla packs.

**Fix:** Added `_VANILLA_PREFIXES = ("vanilla", "chemistry", "experimental")` filter. Only non-vanilla packs are removed.

### 9. Duplicate `world_behavior_packs.json` in `.mcworld` zip

**Root cause:** The `.mcworld` template already contained a `world_behavior_packs.json`. Appending a new one created a duplicate entry warning.

**Fix:** Added `_remove_from_zip()` helper that rewrites the zip without the old entry before appending the new one.

### 10. "Test in Game" launched all checked mobs instead of the active one

**Root cause:** The frontend click handler gathered all mobs with checked checkboxes in the sidebar and sent them all to the API. If two mobs were checked, both were built and summoned — but the user only wanted to test the one they were editing.

**Fix:** Changed the click handler to use only `currentMobName` (the mob currently selected/being edited in the JSON editor) instead of scanning all checkboxes. Now only the active mob is sent.

### 11. Only first entity summoned when pack contained multiple

**Root cause:** `_detect_identifier()` returned only the first entity JSON it found (alphabetically). In a multi-mob pack, only one entity was summoned.

**Fix:** Replaced with `_detect_identifiers()` (plural) that returns **all** identifiers. Both `launch_server_session.py` and `routes.py` now loop over all identifiers, sending a summon/give command for each with retry logic.

---

## Known Limitations

1. **Auto-connect is unreliable.** The `minecraft://Connect` URI works ~50% of the time on Windows UWP. When it fails, the player must manually join via **Play → Friends → LAN Games → "Bedrock Addon Test"**.

2. **Single session only.** Only one BDS test session can run at a time. Starting a new one requires stopping the current one first.

3. **Windows only for full experience.** The `taskkill` and `os.startfile()` calls are Windows-specific. macOS/Linux have fallbacks (`pkill`, `open`/`xdg-open`) but are less tested.

4. **No hot-reload.** Changing the addon requires stopping the server and starting a new session. BDS doesn't support live pack reloading.

5. **Custom entities may be invisible** if only a behavior pack is generated (no resource pack with model/textures). The build system generates both, but LLM-generated packs from `evaluate_llm.py` may only produce behavior packs.

---

## Troubleshooting

### "Failed to load Vanilla Resource Pack"

**Cause:** Incomplete BDS extraction.

**Fix:**
```powershell
# Re-extract everything
Remove-Item -Recurse bedrock_server
Expand-Archive -Path bedrock-server-*.zip -DestinationPath bedrock_server/
# Verify: bedrock_server/resource_packs/vanilla/manifest.json must exist
```

### Minecraft won't connect to localhost

**Cause:** UWP loopback restriction.

**Fix (run once as Admin):**
```powershell
CheckNetIsolation.exe LoopbackExempt -a -p=S-1-15-2-1958404141-86561845-1752920682-3514627264-368642714-62675701-733520436
```

### Minecraft opens but doesn't auto-join

**Cause:** Known UWP protocol handler limitation.

**Workaround:** In Minecraft: **Play → Friends → LAN Games → "Bedrock Addon Test"**

### Port 19132 already in use

**Cause:** A previous BDS instance is still running.

**Fix:**
```powershell
Get-Process bedrock_server -ErrorAction SilentlyContinue | Stop-Process -Force
```

### Entity is invisible

**Cause:** Resource pack not deployed (no textures/models on the server).

**Fix:** Ensure the build produces both `res_mcpack` and `beh_mcpack`. The API endpoint extracts both. If using CLI, pass the resource pack path as well.

### "No targets matched selector"

**Cause:** Summon command fired before player entity fully loaded.

**Fix:** Already handled — the script waits for `"Player Spawned"`, adds a 2-second delay, and retries once. If it still fails, increase the delay in `launch_server_session.py` line 411.

### Build error: "missing 2 required positional arguments: 'res_src' and 'beh_src'"

**Cause:** `build_addon()` called without all required args.

**Fix:** Call as `build_addon(specs, out_dir, None, None)`.
