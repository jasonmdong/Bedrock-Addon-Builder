"""MCP-based geometry generator - replaces LLM geometry generation with MCP tools."""
import json
import time
from typing import Optional
from pathlib import Path

from backend.llm.mcp_client import get_mcp_client


def mcp_generate_geometry(
    prompt: str, 
    current_geometry: Optional[dict] = None,
    working_dir: Optional[str] = None
) -> dict:
    """
    Use MCP to generate or modify Bedrock geometry JSON.
    Replaces the LLM-based llm_generate_geometry function.
    
    Args:
        prompt: User instruction for the geometry (e.g., "create a three-headed dragon")
        current_geometry: Optional existing geometry to modify
        working_dir: Working directory for MCP server
        
    Returns:
        Valid minecraft:geometry JSON object
    """
    start_time = time.time()
    
    # Get or create MCP client
    client = get_mcp_client(working_dir=working_dir)
    if not client:
        raise RuntimeError("Failed to connect to MCP server. Is mct-int installed?")
    
    try:
        # Check which tools are available
        has_design_model = client.is_tool_available("designModel")
        has_create_content = client.is_tool_available("createMinecraftContent")
        
        if not has_design_model and not has_create_content:
            raise RuntimeError("MCP server does not have geometry generation tools")
        
        # Try designModel first (preferred for geometry)
        if has_design_model:
            return _generate_with_design_model(client, prompt, current_geometry)
        
        # Fallback to createMinecraftContent
        return _generate_with_create_content(client, prompt, current_geometry)
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        print(f"[MCP] Geometry generation failed after {duration_ms}ms: {e}")
        raise


def _generate_with_design_model(
    client, 
    prompt: str, 
    current_geometry: Optional[dict] = None
) -> dict:
    """Generate geometry using the designModel tool."""
    
    # Build the request
    tool_args = {
        "description": prompt,
        "saveTo": "temp_geometry.geo.json"  # Temporary file
    }
    
    # If we have existing geometry, include it as reference
    if current_geometry:
        tool_args["referenceGeometry"] = json.dumps(current_geometry, indent=2)
    
    print(f"[MCP] Calling designModel with prompt: {prompt[:50]}...")
    
    result = client.call_tool("designModel", tool_args)
    
    # The result should contain the geometry or a file path
    geometry = _extract_geometry_from_result(result)
    
    if geometry:
        # Validate the geometry structure
        _validate_geometry_structure(geometry)
        
        duration_ms = int((time.time() - start_time) * 1000)
        print(f"[MCP] Geometry generation completed in {duration_ms}ms")
        
        return geometry
    
    raise RuntimeError("MCP designModel did not return valid geometry")


def _generate_with_create_content(
    client, 
    prompt: str, 
    current_geometry: Optional[dict] = None
) -> dict:
    """Generate geometry using the createMinecraftContent tool as fallback."""
    
    # Build a detailed description that includes geometry requirements
    description = f"""Create a Minecraft entity with custom geometry.
    
Geometry requirements: {prompt}

The entity should have a complete geometry definition with bones and cubes."""
    
    tool_args = {
        "type": "entity",
        "description": description,
        "identifier": "custom:generated_entity"
    }
    
    print(f"[MCP] Calling createMinecraftContent for geometry: {prompt[:50]}...")
    
    result = client.call_tool("createMinecraftContent", tool_args)
    
    # Extract geometry from the result
    geometry = _extract_geometry_from_content_result(result)
    
    if geometry:
        _validate_geometry_structure(geometry)
        
        duration_ms = int((time.time() - start_time) * 1000)
        print(f"[MCP] Geometry generation completed in {duration_ms}ms")
        
        return geometry
    
    raise RuntimeError("MCP createMinecraftContent did not return valid geometry")


def _extract_geometry_from_result(result: dict) -> Optional[dict]:
    """Extract geometry JSON from MCP tool result."""
    
    # Check for direct geometry in result
    if "geometry" in result:
        geometry = result["geometry"]
        if isinstance(geometry, dict):
            return _normalize_geometry(geometry)
    
    # Check for files in result
    if "files" in result:
        files = result["files"]
        for filename, content in files.items():
            if filename.endswith(".geo.json") or "geometry" in filename.lower():
                if isinstance(content, str):
                    try:
                        geometry = json.loads(content)
                        return _normalize_geometry(geometry)
                    except json.JSONDecodeError:
                        continue
                elif isinstance(content, dict):
                    return _normalize_geometry(content)
    
    # Check for result text that might contain JSON
    if "result" in result:
        text = result["result"]
        geometry = _extract_json_from_text(text)
        if geometry:
            return _normalize_geometry(geometry)
    
    # Check content array
    if "content" in result:
        for item in result["content"]:
            if item.get("type") == "text":
                text = item.get("text", "")
                geometry = _extract_json_from_text(text)
                if geometry:
                    return _normalize_geometry(geometry)
    
    return None


def _extract_geometry_from_content_result(result: dict) -> Optional[dict]:
    """Extract geometry from createMinecraftContent result."""
    
    # Look for geometry files in the result
    if "files" in result:
        files = result["files"]
        
        # Look for geometry files
        for filename, content in files.items():
            if "models" in filename or filename.endswith(".geo.json"):
                if isinstance(content, str):
                    try:
                        geometry = json.loads(content)
                        return _normalize_geometry(geometry)
                    except json.JSONDecodeError:
                        continue
                elif isinstance(content, dict):
                    return _normalize_geometry(content)
        
        # Look for entity files that might contain geometry reference
        for filename, content in files.items():
            if "entities" in filename and filename.endswith(".json"):
                if isinstance(content, str):
                    try:
                        entity_data = json.loads(content)
                        # Check for geometry component
                        components = entity_data.get("minecraft:entity", {}).get("components", {})
                        geometry_component = components.get("minecraft:geometry", {})
                        if isinstance(geometry_component, dict):
                            identifier = geometry_component.get("identifier", "")
                            # Return a minimal geometry with the identifier
                            return {
                                "format_version": "1.12.0",
                                "minecraft:geometry": [{
                                    "description": {
                                        "identifier": identifier,
                                        "texture_width": 64,
                                        "texture_height": 64,
                                        "visible_bounds_width": 2,
                                        "visible_bounds_height": 2,
                                        "visible_bounds_offset": [0, 1, 0]
                                    },
                                    "bones": []
                                }]
                            }
                    except json.JSONDecodeError:
                        continue
    
    # Try generic extraction
    return _extract_geometry_from_result(result)


def _extract_json_from_text(text: str) -> Optional[dict]:
    """Extract JSON object from text, handling markdown code blocks."""
    
    # Try to find JSON in markdown code blocks
    if "```json" in text:
        parts = text.split("```json")
        for part in parts[1:]:  # Skip first part before ```json
            json_text = part.split("```")[0].strip()
            try:
                return json.loads(json_text)
            except json.JSONDecodeError:
                continue
    
    if "```" in text:
        parts = text.split("```")
        for part in parts[1::2]:  # Take every other part (inside code blocks)
            try:
                return json.loads(part.strip())
            except json.JSONDecodeError:
                continue
    
    # Try to find JSON object directly
    try:
        # Look for text that starts with {
        start = text.find("{")
        if start != -1:
            # Try to find matching }
            brace_count = 0
            end = start
            for i, char in enumerate(text[start:]):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = start + i + 1
                        break
            
            json_text = text[start:end]
            return json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        pass
    
    return None


def _normalize_geometry(geometry: dict) -> dict:
    """
    Normalize geometry to standard minecraft:geometry format.
    
    Args:
        geometry: Input geometry dict in various possible formats
        
    Returns:
        Standardized geometry dict
    """
    # If already in correct format, return as-is
    if "minecraft:geometry" in geometry:
        return geometry
    
    # If it has format_version but no minecraft:geometry wrapper
    if "format_version" in geometry and "minecraft:geometry" not in geometry:
        # Check if it has bones at top level (old format)
        if "bones" in geometry:
            description = geometry.get("description", {})
            return {
                "format_version": geometry.get("format_version", "1.12.0"),
                "minecraft:geometry": [{
                    "description": description,
                    "bones": geometry["bones"]
                }]
            }
    
    # If it's just an array of geometries, wrap it
    if isinstance(geometry, list):
        return {
            "format_version": "1.12.0",
            "minecraft:geometry": geometry
        }
    
    # If it has a single geometry object without the wrapper
    if "description" in geometry or "bones" in geometry:
        return {
            "format_version": "1.12.0",
            "minecraft:geometry": [geometry]
        }
    
    return geometry


def _validate_geometry_structure(geometry: dict):
    """
    Validate that geometry has required fields.
    Raises ValueError if invalid.
    """
    if "minecraft:geometry" not in geometry:
        raise ValueError("Geometry missing 'minecraft:geometry' key")
    
    geo_array = geometry.get("minecraft:geometry", [])
    if not isinstance(geo_array, list) or len(geo_array) == 0:
        raise ValueError("Geometry must contain at least one geometry object")
    
    for geo in geo_array:
        if "description" not in geo:
            raise ValueError("Geometry object missing 'description'")
        
        desc = geo["description"]
        if "identifier" not in desc:
            raise ValueError("Geometry description missing 'identifier'")


def mcp_get_model_templates(working_dir: Optional[str] = None) -> list[dict]:
    """
    Get available model templates from MCP.
    
    Args:
        working_dir: Working directory for MCP server
        
    Returns:
        List of available model templates
    """
    client = get_mcp_client(working_dir=working_dir)
    if not client:
        raise RuntimeError("MCP client not available")
    
    if not client.is_tool_available("getModelTemplates"):
        # Return default templates if tool not available
        return _get_default_templates()
    
    try:
        result = client.call_tool("getModelTemplates", {})
        
        # Extract templates from result
        if "templates" in result:
            return result["templates"]
        
        if "result" in result:
            try:
                parsed = json.loads(result["result"])
                if "templates" in parsed:
                    return parsed["templates"]
            except json.JSONDecodeError:
                pass
        
        return _get_default_templates()
        
    except Exception as e:
        print(f"[MCP] Failed to get model templates: {e}")
        return _get_default_templates()


def _get_default_templates() -> list[dict]:
    """Return default model templates when MCP tool is unavailable."""
    return [
        {"name": "humanoid", "description": "Standard humanoid shape (player-like)"},
        {"name": "small_animal", "description": "Small quadruped (cat, wolf, etc.)"},
        {"name": "large_animal", "description": "Large quadruped (cow, pig, etc.)"},
        {"name": "block", "description": "Simple block shape"},
        {"name": "item", "description": "Flat item shape"},
        {"name": "bird", "description": "Flying creature with wings"},
        {"name": "insect", "description": "Small multi-legged creature"},
        {"name": "fish", "description": "Aquatic creature"},
        {"name": "robot", "description": "Mechanical/robot shape"}
    ]


# Import time at module level for use in functions
import time
