"""MCP-based spec editor - replaces LLM API calls with MCP tools."""
import glob
import json
import os
import time
from typing import Optional
from pathlib import Path

from backend.schemas.spec_utils import validate_spec, SpecValidationError
from backend.llm.mcp_client import get_mcp_client, close_mcp_client
from backend.core.core import BACKEND_DIR

# Load vanilla reference if available
VANILLA_REF = {}
ref_path = BACKEND_DIR / "data" / "vanilla_reference.json"
if ref_path.exists():
    try:
        VANILLA_REF = json.loads(ref_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Failed to load vanilla reference: {e}")


def _build_meta_schema(current_spec: dict, instruction: str) -> dict:
    """
    Build a meta-schema representation of the spec for MCP.
    This converts our internal spec format to the AI-friendly meta-schema.
    """
    # Extract key properties for the meta-schema
    meta_schema = {
        "type": "entity",
        "identifier": current_spec.get("identifier", "custom:entity"),
        "components": {}
    }
    
    # Map behavior components
    components = current_spec.get("components", {})
    if components:
        # Convert component format for MCP
        for key, value in components.items():
            if value is not None:
                # Remove minecraft: prefix for cleaner schema
                clean_key = key.replace("minecraft:", "") if isinstance(key, str) else key
                meta_schema["components"][clean_key] = value
    
    # Add basic properties
    meta_schema["properties"] = {
        "display_name": current_spec.get("display_name", "Custom Entity"),
        "hp": current_spec.get("hp", 10),
        "damage": current_spec.get("damage", 2),
        "speed": current_spec.get("speed", 0.25),
    }
    
    # Add geometry info
    if current_spec.get("geometry_json"):
        meta_schema["geometry"] = {
            "type": "custom",
            "identifier": current_spec.get("identifier", "custom:entity").replace(":", ".")
        }
    elif current_spec.get("geometry"):
        meta_schema["geometry"] = {
            "type": "vanilla",
            "identifier": current_spec.get("geometry")
        }
    
    # Add visual properties
    meta_schema["visuals"] = {
        "color_rgb": current_spec.get("color_rgb", [128, 128, 128]),
        "texture_hint": current_spec.get("texture_hint", ""),
        "texture_instructions": current_spec.get("texture_instructions", []),
        "scale": current_spec.get("scale", 1.0)
    }
    
    # Add spawn egg colors
    meta_schema["spawn_egg"] = {
        "base_color": current_spec.get("egg_base", "#FFFFFF"),
        "overlay_color": current_spec.get("egg_overlay", "#000000")
    }
    
    return meta_schema


def _meta_schema_to_spec(meta_schema: dict, original_spec: dict) -> dict:
    """
    Convert MCP meta-schema back to our internal spec format.
    Preserves fields from original_spec that aren't modified.
    """
    spec = dict(original_spec)
    
    # Update identifier if changed
    if "identifier" in meta_schema:
        spec["identifier"] = meta_schema["identifier"]
    
    # Update components
    if "components" in meta_schema:
        components = {}
        for key, value in meta_schema["components"].items():
            # Add minecraft: prefix back
            full_key = f"minecraft:{key}" if not key.startswith("minecraft:") else key
            components[full_key] = value
        spec["components"] = components
    
    # Update properties
    if "properties" in meta_schema:
        props = meta_schema["properties"]
        if "display_name" in props:
            spec["display_name"] = props["display_name"]
        if "hp" in props:
            spec["hp"] = props["hp"]
        if "damage" in props:
            spec["damage"] = props["damage"]
        if "speed" in props:
            spec["speed"] = props["speed"]
    
    # Update geometry
    if "geometry" in meta_schema:
        geo = meta_schema["geometry"]
        if geo.get("type") == "vanilla":
            spec["geometry"] = geo.get("identifier", "geometry.cow")
        elif geo.get("type") == "custom":
            # Keep existing geometry_json or clear it
            if "geometry_json" not in spec:
                spec["geometry_json"] = {}
    
    # Update visuals
    if "visuals" in meta_schema:
        visuals = meta_schema["visuals"]
        if "color_rgb" in visuals:
            spec["color_rgb"] = visuals["color_rgb"]
        if "texture_hint" in visuals:
            spec["texture_hint"] = visuals["texture_hint"]
        if "texture_instructions" in visuals:
            spec["texture_instructions"] = visuals["texture_instructions"]
        if "scale" in visuals:
            spec["scale"] = visuals["scale"]
    
    # Update spawn egg
    if "spawn_egg" in meta_schema:
        egg = meta_schema["spawn_egg"]
        if "base_color" in egg:
            spec["egg_base"] = egg["base_color"]
        if "overlay_color" in egg:
            spec["egg_overlay"] = egg["overlay_color"]
    
    return spec


def mcp_validate_spec(spec: dict, working_dir: Optional[str] = None) -> dict:
    """
    Use MCP to validate a mob spec.
    
    Args:
        spec: The spec to validate
        working_dir: Working directory for MCP server
        
    Returns:
        Validation result with 'valid' boolean and optional 'errors' list
    """
    client = get_mcp_client(working_dir=working_dir)
    if not client:
        raise RuntimeError("Failed to connect to MCP server")
    
    if not client.is_tool_available("validateContent"):
        raise RuntimeError("MCP server does not support validateContent tool")
    
    # Convert spec to entity JSON format for validation
    entity_json = {
        "format_version": "1.20.0",
        "minecraft:entity": {
            "description": {
                "identifier": spec.get("identifier", "custom:entity"),
                "is_spawnable": True,
                "is_summonable": True
            },
            "components": spec.get("components", {})
        }
    }
    
    tool_args = {
        "content": json.dumps(entity_json),
        "type": "entity"
    }
    
    result = client.call_tool("validateContent", tool_args)
    return result


def mcp_rewrite_spec(prompt: str, current: dict, working_dir: Optional[str] = None) -> dict:
    """
    MCP is not used for spec rewriting - LLMs are better suited for this.
    This function raises an error directing users to use LLM providers.
    """
    raise RuntimeError(
        "MCP is not used for spec editing. Please use OpenAI, DeepSeek, Gemini, "
        "or Claude for modifying specs. MCP is available for geometry generation "
        "and content validation."
    )


def get_mcp_context_for_llm(working_dir: Optional[str] = None) -> str:
    """
    Gather MCP context to enhance LLM prompts.
    Fetches model templates and effective content schema.
    
    Args:
        working_dir: Working directory for MCP server
        
    Returns:
        Context string to add to LLM system prompt
    """
    client = get_mcp_client(working_dir=working_dir)
    if not client:
        return ""
    
    context_parts = []
    
    # Get model templates
    try:
        if client.is_tool_available("getModelTemplates"):
            # Default to a common template type so the tool
            # still works when the caller does not specify one.
            default_template_type = "humanoid"
            print(f"[MCP] Calling getModelTemplates with templateType='{default_template_type}'")
            result = client.call_tool("getModelTemplates", {"templateType": default_template_type})
            if "templates" in result:
                templates = result["templates"]
                context_parts.append("Available Model Templates:")
                for template in templates[:10]:  # Limit to first 10
                    name = template.get("name", "unknown")
                    desc = template.get("description", "")
                    context_parts.append(f"  - {name}: {desc}")
    except Exception as e:
        print(f"[MCP] Failed to get model templates: {e}")
    
    # Get effective content schema if available
    try:
        if client.is_tool_available("getEffectiveContentSchema"):
            # Use the working directory (or current directory) as the
            # default folderPath so the MCP schema requirement is satisfied.
            folder_path = working_dir or os.getcwd()
            print(f"[MCP] Calling getEffectiveContentSchema with folderPath='{folder_path}'")
            result = client.call_tool("getEffectiveContentSchema", {"folderPath": folder_path})
            if "schema" in result:
                schema = result["schema"]
                context_parts.append("\nMinecraft Content Schema:")
                context_parts.append(json.dumps(schema, indent=2)[:1000])  # Limit size
    except Exception as e:
        print(f"[MCP] Failed to get content schema: {e}")
    
    return "\n".join(context_parts) if context_parts else ""


def _entity_json_to_spec(entity_data: dict, original_spec: dict) -> dict:
    """
    Convert Minecraft entity JSON format to our internal spec format.
    
    Args:
        entity_data: Entity JSON from MCP (format_version + minecraft:entity)
        original_spec: Original spec to preserve unmodified fields
        
    Returns:
        Spec dictionary in our internal format
    """
    spec = dict(original_spec)
    
    # Handle different input formats
    if "minecraft:entity" in entity_data:
        entity = entity_data["minecraft:entity"]
    elif "entity" in entity_data:
        entity = entity_data["entity"]
    else:
        entity = entity_data
    
    # Extract description
    description = entity.get("description", {})
    if "identifier" in description:
        spec["identifier"] = description["identifier"]
        # Update short_name based on identifier
        identifier = description["identifier"]
        if ":" in identifier:
            spec["short_name"] = identifier.split(":")[1]
    
    # Extract components
    component_groups = entity.get("component_groups", {})
    components = entity.get("components", {})
    
    # Merge components (prioritize base components)
    all_components = {}
    
    # Add components from default component group if exists
    if "default" in component_groups:
        for key, value in component_groups["default"].items():
            all_components[key] = value
    
    # Add/override with base components
    for key, value in components.items():
        all_components[key] = value
    
    # Extract specific properties from components
    if "minecraft:health" in all_components:
        health = all_components["minecraft:health"]
        if isinstance(health, dict):
            spec["hp"] = health.get("value", health.get("max", 10))
        else:
            spec["hp"] = health
    
    if "minecraft:attack" in all_components:
        attack = all_components["minecraft:attack"]
        if isinstance(attack, dict):
            spec["damage"] = attack.get("damage", 2)
        else:
            spec["damage"] = attack
    
    if "minecraft:movement" in all_components:
        movement = all_components["minecraft:movement"]
        if isinstance(movement, dict):
            spec["speed"] = movement.get("value", 0.25)
        else:
            spec["speed"] = movement
    
    if "minecraft:collision_box" in all_components:
        collision = all_components["minecraft:collision_box"]
        if isinstance(collision, dict):
            spec["collision_box"] = {
                "width": collision.get("width", 1.0),
                "height": collision.get("height", 1.0)
            }
    
    if "minecraft:scale" in all_components:
        scale = all_components["minecraft:scale"]
        if isinstance(scale, dict):
            spec["scale"] = scale.get("value", 1.0)
        else:
            spec["scale"] = scale
    
    # Store all components in spec
    spec["components"] = all_components
    
    return spec


def mcp_validate_content(content: dict or str, content_type: str = "entity") -> dict:
    """
    Use MCP to validate Minecraft content.
    
    Args:
        content: Content to validate (dict or JSON string)
        content_type: Type of content (entity, block, item, etc.)
        
    Returns:
        Validation result with 'valid' boolean and optional 'errors' list
    """
    client = get_mcp_client()
    if not client:
        raise RuntimeError("MCP client not available")
    
    if not client.is_tool_available("validateContent"):
        raise RuntimeError("MCP server does not support validateContent tool")
    
    # Convert dict to JSON string if needed
    if isinstance(content, dict):
        content = json.dumps(content, indent=2)
    
    tool_args = {
        "content": content,
        "type": content_type
    }
    
    result = client.call_tool("validateContent", tool_args)
    return result
