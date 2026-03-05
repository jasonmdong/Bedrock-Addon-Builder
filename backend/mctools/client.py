"""
MCP client for Minecraft Creator Tools (mctools-int).

Manages an MCP session over Streamable HTTP transport:
- Lazy initialization on first tool call
- Session ID tracking and re-init on expiry
- Subprocess management for the mctools HTTP server
- SSE (Server-Sent Events) response parsing
"""

import os
import json
import asyncio
import subprocess
import logging
from pathlib import Path
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCTOOLS_MCP_URL = os.environ.get("MCTOOLS_MCP_URL", "http://localhost:6126/mcp")
MCTOOLS_ENABLED = os.environ.get("MCTOOLS_ENABLED", "true").lower() in ("1", "true", "yes")
MCTOOLS_TIMEOUT = int(os.environ.get("MCTOOLS_TIMEOUT_MS", "30000")) / 1000  # seconds
MCTOOLS_ADMIN_PASSCODE = os.environ.get("MCTOOLS_ADMIN_PASSCODE", "mctadm01")

# The mctools MCP transport has DNS rebinding protection that only allows
# Host: 127.0.0.1, but the server binds to "localhost" (which may resolve
# to ::1 on Windows).  We override the Host header on MCP requests.
_MCP_HOST_HEADER = "127.0.0.1:6126"

# Resolve the mctools package directory
_MCTOOLS_PACKAGE_DIR = (
    Path(__file__).resolve().parents[2]
    / "McpGettingStarted" / "mctools-int-0.0.1" / "package"
)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_session_id: Optional[str] = None
_mctools_process: Optional[subprocess.Popen] = None
_request_id_counter: int = 0
_session_lock: Optional[asyncio.Lock] = None


def _get_session_lock() -> asyncio.Lock:
    """Get or create the session lock (must be created inside an event loop)."""
    global _session_lock
    if _session_lock is None:
        _session_lock = asyncio.Lock()
    return _session_lock


def _next_id() -> int:
    global _request_id_counter
    _request_id_counter += 1
    return _request_id_counter


# ---------------------------------------------------------------------------
# SSE response parsing
# ---------------------------------------------------------------------------

def _parse_sse(text: str) -> list[dict]:
    """
    Parse an SSE response body into a list of JSON-RPC messages.
    
    The MCP SDK sends responses as:
        event: message
        id: <optional>
        data: {"jsonrpc":"2.0","id":1,"result":{...}}
        
        event: message
        data: {"jsonrpc":"2.0","method":"notifications/..."}
        
    We collect all `data:` lines and parse each as JSON.
    """
    messages = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            try:
                messages.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                log.warning("[mctools] SSE data line not valid JSON: %s", line[:200])
    return messages


def _extract_response(text: str, content_type: str, request_id: int) -> dict:
    """
    Parse an MCP HTTP response, handling both JSON and SSE formats.
    
    Returns the JSON-RPC response dict matching request_id.
    Raises RuntimeError if no matching response found.
    """
    if "text/event-stream" in content_type:
        messages = _parse_sse(text)
        # Find the response matching our request ID
        for msg in messages:
            if msg.get("id") == request_id:
                return msg
        # If only one response-like message, use it
        responses = [m for m in messages if "id" in m]
        if len(responses) == 1:
            return responses[0]
        if messages:
            log.warning("[mctools] SSE had %d messages but none matched id=%s", len(messages), request_id)
            return messages[-1]  # last message as fallback
        raise RuntimeError(f"SSE response contained no parseable messages")
    else:
        # Plain JSON response
        return json.loads(text)


# ---------------------------------------------------------------------------
# Subprocess management
# ---------------------------------------------------------------------------

async def _start_mctools_server() -> None:
    """Start the mctools HTTP server as a subprocess if not already running."""
    global _mctools_process

    if _mctools_process is not None and _mctools_process.poll() is None:
        return  # already running

    if not _MCTOOLS_PACKAGE_DIR.exists():
        raise RuntimeError(
            f"mctools package not found at {_MCTOOLS_PACKAGE_DIR}. "
            "Run npm install in that directory first."
        )

    node_modules = _MCTOOLS_PACKAGE_DIR / "node_modules"
    if not node_modules.exists():
        raise RuntimeError(
            f"mctools node_modules not found. Run: npm install "
            f"in {_MCTOOLS_PACKAGE_DIR}"
        )

    cli_entry = _MCTOOLS_PACKAGE_DIR / "cli" / "index.mjs"
    cmd = [
        "node", str(cli_entry),
        "serve",
        "--adminpc", MCTOOLS_ADMIN_PASSCODE,
        "--port", "6126",
    ]

    log.info("[mctools] Starting HTTP server: %s", " ".join(cmd))
    _mctools_process = subprocess.Popen(
        cmd,
        cwd=str(_MCTOOLS_PACKAGE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Wait for the server to become reachable (up to 30s)
    base_url = MCTOOLS_MCP_URL.rsplit("/mcp", 1)[0]
    async with httpx.AsyncClient() as client:
        for attempt in range(60):
            await asyncio.sleep(0.5)
            if _mctools_process.poll() is not None:
                out = _mctools_process.stdout.read() if _mctools_process.stdout else ""
                raise RuntimeError(
                    f"mctools server exited during startup (code {_mctools_process.returncode}):\n{out[:2000]}"
                )
            try:
                resp = await client.get(f"{base_url}/", timeout=3)
                if resp.status_code < 500:
                    log.info("[mctools] Server ready after %.1fs", (attempt + 1) * 0.5)
                    return
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException):
                pass

    raise RuntimeError("mctools server did not become ready within 30 seconds")


def stop_mctools_server() -> None:
    """Stop the mctools subprocess if running."""
    global _mctools_process
    if _mctools_process is not None:
        log.info("[mctools] Stopping HTTP server (pid %s)", _mctools_process.pid)
        _mctools_process.terminate()
        try:
            _mctools_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _mctools_process.kill()
        _mctools_process = None


# ---------------------------------------------------------------------------
# Low-level MCP POST helper
# ---------------------------------------------------------------------------

_MCP_HEADERS_BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Host": _MCP_HOST_HEADER,
}


async def _mcp_post(
    payload: dict,
    session_id: Optional[str] = None,
    timeout: Optional[float] = None,
) -> httpx.Response:
    """POST a JSON-RPC payload to the MCP endpoint."""
    headers = dict(_MCP_HEADERS_BASE)
    if session_id:
        headers["mcp-session-id"] = session_id
    effective_timeout = timeout if timeout is not None else MCTOOLS_TIMEOUT
    async with httpx.AsyncClient(timeout=effective_timeout) as client:
        return await client.post(MCTOOLS_MCP_URL, json=payload, headers=headers)


# ---------------------------------------------------------------------------
# MCP session management
# ---------------------------------------------------------------------------

async def _ensure_session() -> str:
    """Initialize an MCP session if we don't have one. Returns session ID.

    Uses a lock so only one caller does the init/recycle at a time.
    Concurrent callers wait and then reuse the established session.
    """
    global _session_id

    if _session_id:
        return _session_id

    async with _get_session_lock():
        # Re-check after acquiring the lock — another caller may have finished
        if _session_id:
            return _session_id

        # Make sure a server is reachable
        if not await _is_server_reachable():
            await _start_mctools_server()

        # Initialize a session (handles stale-session recovery internally)
        _session_id = await _do_initialize()
        return _session_id


async def _is_server_reachable() -> bool:
    """Quick probe: is something listening on the mctools port?"""
    try:
        base_url = MCTOOLS_MCP_URL.rsplit("/mcp", 1)[0]
        async with httpx.AsyncClient(timeout=3) as probe:
            resp = await probe.get(f"{base_url}/", timeout=3)
            return resp.status_code < 500
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException):
        return False


async def _do_initialize() -> str:
    """Send MCP initialize handshake.

    If the server has a stale session from a previous app instance, kills the
    orphaned Node process, waits for the port to be free, starts a fresh
    server, and retries.
    """
    req_id = _next_id()
    init_payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {
                "name": "bedrock-addon-builder",
                "version": "0.1.0",
            },
        },
    }

    resp = await _mcp_post(init_payload)

    if resp.status_code == 400 and "already initialized" in resp.text.lower():
        log.warning("[mctools] Stale session — killing orphaned server and restarting")
        await _kill_port_holder()
        await _wait_port_free()
        await _start_mctools_server()

        req_id = _next_id()
        init_payload["id"] = req_id
        resp = await _mcp_post(init_payload)

    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"MCP initialize failed ({resp.status_code}): {resp.text[:500]}"
        )

    session_id = resp.headers.get("mcp-session-id")
    if not session_id:
        raise RuntimeError("MCP server did not return mcp-session-id header")

    ct = resp.headers.get("content-type", "")
    data = _extract_response(resp.text, ct, req_id)
    log.info("[mctools] MCP session initialized: %s (server: %s)",
             session_id,
             data.get("result", {}).get("serverInfo", {}).get("name", "unknown"))

    notif_payload = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }
    await _mcp_post(notif_payload, session_id)
    return session_id


def _find_pid_on_port(port: str) -> list[int]:
    """Return PIDs of processes listening on the given port."""
    import platform
    pids: list[int] = []
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    pid = parts[-1]
                    if pid.isdigit() and int(pid) > 0:
                        pids.append(int(pid))
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5,
            )
            for tok in result.stdout.strip().split():
                if tok.isdigit():
                    pids.append(int(tok))
    except Exception as e:
        log.debug("[mctools] _find_pid_on_port failed: %s", e)
    return pids


async def _kill_port_holder() -> None:
    """Kill whatever process is holding the mctools port."""
    global _mctools_process
    import platform

    port = MCTOOLS_MCP_URL.rsplit(":", 1)[-1].split("/")[0]

    # Kill our tracked subprocess first
    if _mctools_process is not None:
        try:
            _mctools_process.kill()
            _mctools_process.wait(timeout=5)
        except Exception:
            pass
        _mctools_process = None

    # Find and force-kill the actual port holder
    pids = _find_pid_on_port(port)
    for pid in pids:
        log.info("[mctools] Killing PID %d holding port %s", pid, port)
        try:
            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                               capture_output=True, timeout=10)
            else:
                subprocess.run(["kill", "-9", str(pid)],
                               capture_output=True, timeout=5)
        except Exception as e:
            log.warning("[mctools] Failed to kill PID %d: %s", pid, e)


async def _wait_port_free(max_wait: float = 10.0) -> None:
    """Block until the mctools port is free, or raise after max_wait seconds."""
    import time
    port = MCTOOLS_MCP_URL.rsplit(":", 1)[-1].split("/")[0]
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if not _find_pid_on_port(port):
            log.info("[mctools] Port %s is free", port)
            return
        await asyncio.sleep(0.5)
    log.warning("[mctools] Port %s still occupied after %.0fs, proceeding anyway", port, max_wait)


async def _invalidate_session() -> None:
    """Clear the session so the next call re-initializes."""
    global _session_id
    _session_id = None


# ---------------------------------------------------------------------------
# Tool invocation
# ---------------------------------------------------------------------------

async def call_tool(
    tool_name: str,
    arguments: dict[str, Any],
    timeout: Optional[float] = None,
) -> dict:
    """
    Call an MCP tool and return the parsed result.

    Args:
        tool_name: MCP tool name to invoke.
        arguments: Tool arguments dict.
        timeout: Optional per-call timeout in seconds (overrides MCTOOLS_TIMEOUT).

    Returns dict with keys:
      - "content": list of content items from the tool result
      - "isError": bool if tool reported an error
    
    Raises RuntimeError on transport/protocol failures.
    """
    if not MCTOOLS_ENABLED:
        raise RuntimeError("mctools integration is disabled (MCTOOLS_ENABLED=false)")

    effective_timeout = timeout if timeout is not None else MCTOOLS_TIMEOUT
    session_id = await _ensure_session()

    req_id = _next_id()
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }

    try:
        resp = await _mcp_post(payload, session_id, timeout=effective_timeout)
    except httpx.TimeoutException:
        await _invalidate_session()
        raise RuntimeError(f"MCP tool call '{tool_name}' timed out after {effective_timeout}s")

    if resp.status_code == 400 and "session" in resp.text.lower():
        await _invalidate_session()
        session_id = await _ensure_session()
        resp = await _mcp_post(payload, session_id, timeout=effective_timeout)

    if resp.status_code != 200:
        raise RuntimeError(
            f"MCP tool call '{tool_name}' failed ({resp.status_code}): {resp.text[:500]}"
        )

    ct = resp.headers.get("content-type", "")
    try:
        data = _extract_response(resp.text, ct, req_id)
    except (RuntimeError, json.JSONDecodeError) as e:
        raise RuntimeError(
            f"MCP tool '{tool_name}' returned unparseable response: {e}\n"
            f"Content-Type: {ct}\nBody (first 500): {resp.text[:500]}"
        )

    # JSON-RPC error
    if "error" in data:
        err = data["error"]
        raise RuntimeError(
            f"MCP tool '{tool_name}' returned error {err.get('code')}: {err.get('message', '')}"
        )

    result = data.get("result", {})
    return {
        "content": result.get("content", []),
        "isError": result.get("isError", False),
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def is_available() -> bool:
    """Check if mctools MCP is reachable and has an active session."""
    if not MCTOOLS_ENABLED:
        return False
    try:
        await _ensure_session()
        return True
    except Exception:
        return False
