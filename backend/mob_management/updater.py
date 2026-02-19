"""
Update existing mob specifications in the database.

Part of CRUD operations:
- create: save_mob.py (fetch from GitHub and insert)
- read: retriever.py (get mobs from database)
- update: updater.py (this file - modify existing mobs)
- delete: deleter.py (remove mobs from database)
"""
from typing import Dict, Any, Optional
from backend.database import fetch_one, execute_query


def update_mob_in_db(mob_id: int, updates: Dict[str, Any]) -> bool:
    """
    Update specific fields of a mob in the database.
    
    Args:
        mob_id: The ID of the mob to update
        updates: Dictionary of field names and new values to update
    
    Returns:
        True if successful, False otherwise
    """
    if not updates:
        return False
    
    # Build the SET clause dynamically
    set_parts = []
    values = []
    for key, value in updates.items():
        set_parts.append(f"{key} = %s")
        values.append(value)
    
    # Add mob_id as the WHERE condition
    values.append(mob_id)
    
    set_clause = ", ".join(set_parts)
    sql = f"UPDATE mob_geometries SET {set_clause} WHERE id = %s"
    
    try:
        execute_query(sql, tuple(values))
        return True
    except Exception as e:
        print(f"Error updating mob {mob_id}: {e}")
        return False


def update_mob_description(mob_id: int, new_description: str) -> bool:
    """Update just the description of a mob."""
    return update_mob_in_db(mob_id, {"mob_description": new_description})


def update_mob_keywords(mob_id: int, new_keywords: list) -> bool:
    """Update just the keywords of a mob."""
    import json
    return update_mob_in_db(mob_id, {"mob_keywords": json.dumps(new_keywords)})


def update_mob_complexity(mob_id: int, new_complexity: float) -> bool:
    """Update just the complexity score of a mob."""
    return update_mob_in_db(mob_id, {"complexity_score": new_complexity})


def update_mob_embedding(mob_id: int, new_embedding: list) -> bool:
    """Update just the embedding vector of a mob."""
    import json
    return update_mob_in_db(mob_id, {"mob_embedding": json.dumps(new_embedding)})


def update_mob_geometry(mob_id: int, new_geometry: Dict) -> bool:
    """Update just the geometry of a mob."""
    import json
    return update_mob_in_db(mob_id, {"mob_geometry": json.dumps(new_geometry)})
