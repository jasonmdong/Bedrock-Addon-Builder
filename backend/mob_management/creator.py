"""Create new mob specifications based on user requests."""
from typing import Dict, Any, Optional
from backend.core.core import DEFAULTS
from backend.schemas.spec_utils import validate_spec


def create_mob_spec(
    base_mob: Optional[Dict[str, Any]] = None,
    user_prompt: str = "",
    customizations: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a new mob specification.
    
    Args:
        base_mob: Existing mob to use as template, or None for defaults
        user_prompt: User's description of desired mob
        customizations: Dict of custom properties to override
    
    Returns:
        Validated mob spec dictionary
    """
    # Start with base mob or defaults
    if base_mob:
        spec = dict(base_mob)
    else:
        spec = dict(DEFAULTS)
    
    # TODO: Apply customizations from user_prompt
    # This could involve:
    # - Parsing the prompt for desired traits
    # - Adjusting size, speed, damage, colors, etc.
    # - Generating texture descriptions
    # - Setting appropriate geometry
    
    # Apply any explicit customizations
    if customizations:
        spec.update(customizations)
    
    # Validate the spec before returning
    return validate_spec(spec)


def apply_lllm_changes(
    current_spec: Dict[str, Any],
    llm_changes: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Apply changes from LLM output to an existing spec.
    
    Args:
        current_spec: The current mob specification
        llm_changes: Changes from LLM (usually a new spec)
    
    Returns:
        Updated mob specification
    """
    updated = dict(current_spec)
    updated.update(llm_changes)
    return validate_spec(updated)
