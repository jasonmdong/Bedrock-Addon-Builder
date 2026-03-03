"""MCP (Model Context Protocol) client for communicating with mctools-int server."""
import json
import subprocess
import threading
import time
import os
from pathlib import Path
from typing import Optional, Dict, Any, Callable


class MCPClient:
    """
    Client for communicating with the Minecraft Creator Tools MCP server.
    Uses stdio-based JSON-RPC communication.
    """
    
    def __init__(self, working_dir: Optional[str] = None, mcp_command: str = "mct-int"):
        """
        Initialize the MCP client.
        
        Args:
            working_dir: Directory to use as the MCP server working folder
            mcp_command: Command to launch the MCP server (default: "mct-int")
        """
        self.working_dir = working_dir or os.getcwd()
        self.mcp_command = mcp_command
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._initialized = False
        self._available_tools: list[dict] = []
        
    def start(self) -> bool:
        """
        Start the MCP server process and initialize the connection.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure npm global bin is in PATH
            env = os.environ.copy()
            npm_bin = os.path.expanduser("~\\AppData\\Roaming\\npm")
            if os.path.exists(npm_bin) and npm_bin not in env.get("PATH", ""):
                env["PATH"] = npm_bin + os.pathsep + env.get("PATH", "")
            
            # On Windows, use the .cmd file directly
            if os.name == 'nt':
                cmd_path = os.path.join(npm_bin, f"{self.mcp_command}.cmd")
                if os.path.exists(cmd_path):
                    cmd = [cmd_path, "mcp", "-i", self.working_dir]
                else:
                    cmd = [self.mcp_command, "mcp", "-i", self.working_dir]
            else:
                cmd = [self.mcp_command, "mcp", "-i", self.working_dir]
            
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                encoding='utf-8',
                env=env
            )
            
            # Wait a moment for server to start
            time.sleep(0.5)
            
            if self.process.poll() is not None:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                print(f"[MCP] Server failed to start: {stderr}")
                return False
            
            # Initialize the connection
            if self._initialize():
                self._initialized = True
                print(f"[MCP] Connected to server, {len(self._available_tools)} tools available")
                return True
            else:
                return False
                
        except FileNotFoundError:
            print(f"[MCP] Command '{self.mcp_command}' not found. Is mctools-int installed?")
            return False
        except Exception as e:
            print(f"[MCP] Failed to start server: {e}")
            return False
    
    def stop(self):
        """Stop the MCP server process."""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            print("[MCP] Server stopped")
        self._initialized = False
    
    def _initialize(self) -> bool:
        """
        Send initialize request and get available tools.
        
        Returns:
            True if initialization successful
        """
        # Send initialize request
        init_request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "bedrock-addon-builder",
                    "version": "0.1.0"
                }
            },
            "id": 1
        }
        
        response = self._send_request(init_request)
        if not response or "error" in response:
            print(f"[MCP] Initialization failed: {response.get('error') if response else 'No response'}")
            return False
        
        # Send initialized notification
        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        self._send_notification(initialized_notification)
        
        # Get available tools
        tools = self._list_tools()
        if tools:
            self._available_tools = tools
            return True
        return False
    
    def _send_request(self, request: dict) -> Optional[dict]:
        """Send a JSON-RPC request and wait for response."""
        with self._lock:
            if not self.process or self.process.poll() is not None:
                return None
            
            try:
                json_line = json.dumps(request) + "\n"
                self.process.stdin.write(json_line)
                self.process.stdin.flush()
                
                # Read response with timeout - may need to skip non-JSON lines
                max_attempts = 5
                for _ in range(max_attempts):
                    response_line = self.process.stdout.readline()
                    if not response_line:
                        return None
                    # Skip lines that don't start with '{' (log messages)
                    if response_line.strip().startswith('{'):
                        return json.loads(response_line)
                return None
            except Exception as e:
                print(f"[MCP] Request failed: {e}")
                return None
    
    def _send_notification(self, notification: dict):
        """Send a JSON-RPC notification (no response expected)."""
        with self._lock:
            if self.process and self.process.poll() is None:
                try:
                    json_line = json.dumps(notification) + "\n"
                    self.process.stdin.write(json_line)
                    self.process.stdin.flush()
                except Exception as e:
                    print(f"[MCP] Notification failed: {e}")
    
    def _list_tools(self) -> list[dict]:
        """Get list of available tools from the MCP server."""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": self._request_id
        }
        
        response = self._send_request(request)
        if response and "result" in response:
            return response["result"].get("tools", [])
        return []
    
    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Call an MCP tool with the given arguments.
        
        Args:
            tool_name: Name of the tool to call (e.g., "createMinecraftContent")
            arguments: Dictionary of arguments for the tool
            
        Returns:
            Tool result as dictionary
        """
        if not self._initialized:
            raise RuntimeError("MCP client not initialized. Call start() first.")
        
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            },
            "id": self._request_id
        }
        
        response = self._send_request(request)
        if not response:
            raise RuntimeError("No response from MCP server")
        
        if "error" in response:
            error = response["error"]
            raise RuntimeError(f"MCP tool error: {error.get('message', 'Unknown error')}")
        
        # Parse the result content
        result = response.get("result", {})
        content = result.get("content", [])
        
        # Extract text content from the result
        text_content = []
        for item in content:
            if item.get("type") == "text":
                text_content.append(item.get("text", ""))
        
        full_text = "".join(text_content)
        
        # Try to parse as JSON if it looks like JSON
        try:
            if full_text.strip().startswith("{") or full_text.strip().startswith("["):
                return json.loads(full_text)
        except json.JSONDecodeError:
            pass
        
        return {"result": full_text, "content": content}
    
    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a specific tool is available."""
        return any(t.get("name") == tool_name for t in self._available_tools)
    
    def get_available_tools(self) -> list[dict]:
        """Get list of all available tools with their schemas."""
        return self._available_tools


# Global client instance for reuse
_mcp_client: Optional[MCPClient] = None


def get_mcp_client(working_dir: Optional[str] = None, force_new: bool = False) -> Optional[MCPClient]:
    """
    Get or create the global MCP client instance.
    
    Args:
        working_dir: Directory to use as MCP working folder
        force_new: If True, create a new client even if one exists
        
    Returns:
        MCPClient instance or None if failed
    """
    global _mcp_client
    
    if _mcp_client is not None and not force_new:
        if _mcp_client._initialized:
            return _mcp_client
        else:
            # Clean up failed client
            _mcp_client.stop()
            _mcp_client = None
    
    client = MCPClient(working_dir=working_dir)
    if client.start():
        _mcp_client = client
        return client
    return None


def close_mcp_client():
    """Close the global MCP client if it exists."""
    global _mcp_client
    if _mcp_client:
        _mcp_client.stop()
        _mcp_client = None
