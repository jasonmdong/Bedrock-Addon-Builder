#!/usr/bin/env python3
"""Test script for MCP integration."""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

def test_mcp_imports():
    """Test that MCP modules can be imported."""
    print("Testing MCP module imports...")
    try:
        from backend.llm.mcp_client import MCPClient, get_mcp_client
        print("  ✓ mcp_client imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import mcp_client: {e}")
        return False
    
    try:
        from backend.llm.mcp_spec_editor import mcp_rewrite_spec
        print("  ✓ mcp_spec_editor imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import mcp_spec_editor: {e}")
        return False
    
    try:
        from backend.llm.mcp_geometry import mcp_generate_geometry
        print("  ✓ mcp_geometry imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import mcp_geometry: {e}")
        return False
    
    return True


def test_mcp_in_llm_module():
    """Test that MCP functions are available in llm module."""
    print("\nTesting MCP integration in llm module...")
    try:
        from backend.llm.llm import (
            llm_rewrite_spec_mcp, 
            llm_generate_geometry_mcp,
            get_mcp_status,
            MCP_AVAILABLE,
            USE_MCP
        )
        print(f"  ✓ MCP functions imported successfully")
        print(f"    - MCP_AVAILABLE: {MCP_AVAILABLE}")
        print(f"    - USE_MCP: {USE_MCP}")
        return True
    except ImportError as e:
        print(f"  ✗ Failed to import MCP functions from llm: {e}")
        return False


def test_mcp_status():
    """Test getting MCP status."""
    print("\nTesting MCP status check...")
    try:
        from backend.llm.llm import get_mcp_status
        status = get_mcp_status()
        print(f"  ✓ MCP status retrieved:")
        print(f"    - Available: {status.get('available')}")
        if status.get('available'):
            print(f"    - Initialized: {status.get('initialized')}")
            print(f"    - Tools: {status.get('tool_count', 0)}")
            print(f"    - Tool names: {', '.join(status.get('tools', [])[:5])}...")
        else:
            print(f"    - Error: {status.get('error')}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to get MCP status: {e}")
        return False


def test_core_config():
    """Test that MCP config is in core."""
    print("\nTesting core configuration...")
    try:
        from backend.core.core import USE_MCP, MCP_COMMAND, MCP_WORKING_DIR
        print(f"  ✓ MCP configuration loaded:")
        print(f"    - USE_MCP: {USE_MCP}")
        print(f"    - MCP_COMMAND: {MCP_COMMAND}")
        print(f"    - MCP_WORKING_DIR: {MCP_WORKING_DIR}")
        return True
    except ImportError as e:
        print(f"  ✗ Failed to load MCP config: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("MCP Integration Test Suite")
    print("=" * 60)
    
    results = []
    results.append(("Module Imports", test_mcp_imports()))
    results.append(("LLM Module Integration", test_mcp_in_llm_module()))
    results.append(("Core Configuration", test_core_config()))
    results.append(("MCP Status", test_mcp_status()))
    
    print("\n" + "=" * 60)
    print("Test Results:")
    print("=" * 60)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
    
    all_passed = all(passed for _, passed in results)
    print("=" * 60)
    if all_passed:
        print("All tests passed!")
        return 0
    else:
        print("Some tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
