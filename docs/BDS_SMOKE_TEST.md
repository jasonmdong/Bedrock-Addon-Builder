# BDS Smoke Test

Automatically validates every generated `.mcaddon` by booting a real Bedrock Dedicated Server, loading the pack, and summoning each custom entity — all in ~6 seconds.

## Why it exists

Static validators (JSON schema, regex checks) can confirm that a file is well-formed, but they cannot tell you whether Bedrock itself accepts the pack. A mob with a typo in a component name, a broken animation controller reference, or an invalid geometry identifier will pass static checks but fail silently in-game. The smoke test catches those failures before the user downloads anything.

## How it works

```
POST /api/build
      │
      ▼
builders.py / packaging.py
  generates .mcaddon ZIP
      │
      ▼
bds_runner.run_bds_smoke_sync()
  ┌───────────────────────────────────────────────┐
  │ 1. Extract .mcaddon → resource_pack/          │
  │                      behavior_pack/           │
  │ 2. Copy packs into BDS dirs (run-scoped name) │
  │ 3. Write world_*_packs.json                   │
  │ 4. Write server.properties (flat, offline,    │
  │    peaceful, creative, alt port)              │
  │ 5. Start bedrock_server.exe as subprocess     │
  │ 6. Stream stdout → wait for "Server started." │
  │ 7. Send: tickingarea add 0 0 0 5 5 5          │
  │    Wait 1.5 s (chunk load)                    │
  │ 8. Send: summon <identifier> 0 64 0           │
  │    for each entity in behavior pack           │
  │ 9. Drain stdout for 4 s, collect all lines    │
  │10. Kill BDS                                   │
  │11. Parse log → errors / warnings              │
  │12. Cleanup: remove packs + world              │
  └───────────────────────────────────────────────┘
      │
      ▼
SmokeResult { passed, errors, warnings, session_log }
```

### Step 7 — why `tickingarea`

BDS in headless mode (no players connected) does not keep any chunks loaded. Without loaded chunks, `summon` always fails with "Unable to summon object" even if the entity is registered correctly. `tickingarea add` forces BDS to load and tick a chunk region permanently, so the subsequent `summon` has a valid target area.

### Step 8 — what a failed summon tells you

| BDS output | Meaning |
|---|---|
| `Object successfully summoned` | Entity registered and spawnable |
| `Unable to summon object` | Entity registered but chunk not loaded (should not happen after step 7), or spawn conditions blocked |
| `No entity with type '...' was found` | Entity identifier not registered — behavior pack didn't load correctly |
| `Unknown command` | Command syntax rejected — indicates a code bug in the runner |

## Error patterns checked (`log_parser.py`)

The log parser scans every line of BDS stdout against these rules:

| Rule | Pattern | Severity |
|---|---|---|
| `pack_load_failure` | `[Packs] can't load/parse` | error |
| `invalid_manifest` | `[Packs] invalid manifest` | error |
| `missing_manifest` | `[Packs] missing manifest` | error |
| `pack_not_found` | `[Packs] can't find` | error |
| `content_log_error` | `[ContentLog] [error]` | error |
| `content_log_warning` | `[ContentLog] [warning]` | warning |
| `missing_definition` | `Unable to find definition/component for` | error |
| `entity_load_failure` | `Failed to load/resolve entity` | error |
| `bad_format_version` | `has invalid format_version` | error |
| `invalid_json` | `Invalid JSON in` | error |
| `json_parse_error` | `JSON parsing error` | error |
| `missing_texture` | `Texture ... not found` | error |
| `missing_geometry` | `Geometry ... not found` | error |
| `unknown_geometry` | `Unknown geometry` | error |
| `missing_render_ctrl` | `render controller ... not found` | error |
| `script_error` | `[Script] Error` | error |
| `script_warning` | `[Script] Warning` | warning |
| `entity_not_registered` | `No entity with type ... was found` | error |
| `summon_failed` | `summon.*failed` / `Unable to summon` | error |
| `unknown_command` | `Unknown command` | error |
| `unknown_component` | `Unknown block/item/component` | warning |
| `deprecated_api` | `deprecated` | warning |

**Pass condition:** `bds_ready == True AND len(errors) == 0`

## Why it's fast (~6 seconds)

BDS is not slow — the startup cost is just the binary loading and LevelDB opening. Several things keep it minimal:

- **Flat world** — 4 layers (bedrock + 2 dirt + grass), no terrain generation, no structures, no caves. LevelDB is created fresh each run from scratch in milliseconds.
- **Peaceful + Creative** — no mob spawning, no combat ticks, no hunger calculations. The game loop does almost nothing.
- **`tick-distance=4`, `view-distance=4`** — minimum possible chunk simulation radius.
- **No players** — no network handshake, no inventory, no skin loading, no player data.
- **Offline mode** — no Xbox Live authentication round-trip.
- **Alt port (29132)** — no conflict with a running BDS instance; bind succeeds immediately.
- **No GUI** — BDS is a headless binary, zero rendering overhead.

The breakdown in a typical run:

| Phase | Time |
|---|---|
| BDS binary load + LevelDB create | ~1 s |
| Pack validation + world pack JSON parse | ~0.5 s |
| `Server started.` + 3 s content-log drain | ~3 s |
| `tickingarea` + 1.5 s chunk load | ~1.5 s |
| `summon` + 4 s drain | ~0.5 s |
| **Total** | **~6 s** |

The 3-second sleep after `Server started.` dominates. It exists to let BDS flush any deferred content-log errors (missing textures, bad component names) that are emitted asynchronously after the server reports ready.

## Configuration

Set these environment variables to control the smoke test:

| Variable | Default | Description |
|---|---|---|
| `BDS_PATH` | *(unset)* | Full path to `bedrock_server.exe`. If unset, smoke tests are skipped. |
| `BDS_TIMEOUT` | `60` | Seconds to wait for `Server started.` before giving up. |
| `BDS_SMOKE_PORT` | `29132` | UDP port BDS binds. Change if another process owns 29132. |

## Isolation

Each run gets a unique `run_id` (12-char hex). All run-scoped files use that ID:

```
bedrock-server/
  behavior_packs/smoke_{run_id}_beh/   ← deleted after run
  resource_packs/smoke_{run_id}_res/   ← deleted after run
  worlds/smoke_{run_id}/               ← deleted after run
```

Cleanup runs in a `finally` block, so it happens even if BDS crashes or the smoke test raises an exception. Only one BDS instance runs at a time (threading semaphore), so concurrent builds queue rather than collide.

## Production considerations

The smoke test is designed for local development and CI. Deploying it to production introduces several real tensions.

### The binary problem

BDS is a ~250 MB executable. In a Docker-based deployment (e.g. Hugging Face Spaces) you have two options, both with downsides:

- **Bundle in image** — adds 250 MB to every deploy push; HF Spaces free tier has storage and RAM limits a running BDS instance will pressure.
- **Download at startup** — slow cold starts; adds a hard dependency on Mojang's CDN being available.

### The blocking problem

`/api/build` currently blocks for ~6 seconds while smoke runs. For one user that is fine. For a public deployment it ties up a FastAPI worker for 6 seconds per build. The fix is to return the artifact immediately, run smoke in the background, and expose a `/api/build/{id}/smoke` status endpoint (or push the result over a websocket).

### The concurrency problem

The semaphore serializes all smoke tests globally. Five concurrent builds means the fifth user waits ~30 seconds just for a smoke slot. Fixing this requires either a pool of BDS instances or a proper job queue (Celery, RQ, etc.) in front of the runner.

### Recommended approaches by deployment target

| Scenario | Approach |
|---|---|
| **Local dev** (current) | Full smoke on every build. Works as-is. |
| **HF Spaces / demo** | Set `BDS_PATH` unset — smoke is skipped automatically. Run smoke only in local dev and CI against golden tests. Correct for a demo where mob templates are stable. |
| **Real product with users** | Dedicated smoke service on a small always-on VM. Main app POSTs the `.mcaddon` to the service and polls for a `SmokeResult`. BDS pool lives on the VM. Main app stays lightweight and deployable anywhere. Build endpoint returns immediately; status arrives async. |

### What to do right now

For the current HF Spaces deployment: leave `BDS_PATH` unset in production. The golden test suite in `backend/llm_scoring.py` already covers correctness for known prompt patterns. Per-build smoke is most valuable locally where you are actively changing builder code — in a deployed demo with stable templates it adds latency without much signal.
