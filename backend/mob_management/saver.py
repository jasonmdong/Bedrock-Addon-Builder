"""
Save custom/generated mob specs to the database.

Note: For fetching and bulk importing Bedrock sample mobs from GitHub,
see backend/mob_management/save_mob.py
"""
from typing import Dict, Any, Optional

# For complex DB operations, use the save_mob.py module
# For simple spec storage to existing tables, use the database module


def save_custom_mob_spec(mob_spec: Dict[str, Any]) -> bool:
    """
    Save a custom-generated mob spec to the application's mob storage.
    
    This integrates with the existing mob spec storage system
    (currently uses local files via spec_utils).
    
    Args:
        mob_spec: Validated mob specification dictionary
    
    Returns:
        True if successful
    """
    from backend.schemas.spec_utils import write_mob_spec
    
    mob_name = mob_spec.get("short_name", "custom_mob")
    try:
        write_mob_spec(mob_name, mob_spec)
        return True
    except Exception as e:
        print(f"Error saving mob spec: {e}")
        return False


def retrieve_custom_mob_spec(mob_name: str) -> Optional[Dict[str, Any]]:
    """Retrieve a custom mob spec from storage."""
    from backend.schemas.spec_utils import read_mob_spec
    
    try:
        return read_mob_spec(mob_name)
    except Exception as e:
        print(f"Error retrieving mob spec: {e}")
        return None
