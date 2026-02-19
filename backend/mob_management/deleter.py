"""
Delete mobs from the database.

Part of CRUD operations:
- create: save_mob.py (fetch from GitHub and insert)
- read: retriever.py (get mobs from database)
- update: updater.py (modify existing mobs)
- delete: deleter.py (this file - remove mobs)
"""
from typing import Optional
from backend.database import execute_query, fetch_one


def delete_mob_by_id(mob_id: int) -> bool:
    """
    Delete a mob from the database by ID.
    
    Args:
        mob_id: The ID of the mob to delete
    
    Returns:
        True if successful, False otherwise
    """
    sql = "DELETE FROM mob_geometries WHERE id = %s"
    
    try:
        execute_query(sql, (mob_id,))
        return True
    except Exception as e:
        print(f"Error deleting mob {mob_id}: {e}")
        return False


def delete_mob_by_name(mob_name: str) -> bool:
    """
    Delete a mob from the database by name.
    
    Args:
        mob_name: The name of the mob to delete
    
    Returns:
        True if successful, False otherwise
    """
    sql = "DELETE FROM mob_geometries WHERE name = %s"
    
    try:
        execute_query(sql, (mob_name,))
        return True
    except Exception as e:
        print(f"Error deleting mob '{mob_name}': {e}")
        return False


def delete_all_official_mobs() -> bool:
    """
    Delete all official mobs from the database.
    
    WARNING: This is a destructive operation.
    
    Returns:
        True if successful, False otherwise
    """
    sql = "DELETE FROM mob_geometries WHERE is_official = TRUE"
    
    try:
        execute_query(sql)
        return True
    except Exception as e:
        print(f"Error deleting official mobs: {e}")
        return False


def delete_all_custom_mobs() -> bool:
    """
    Delete all custom mobs from the database.
    
    WARNING: This is a destructive operation.
    
    Returns:
        True if successful, False otherwise
    """
    sql = "DELETE FROM mob_geometries WHERE is_official = FALSE"
    
    try:
        execute_query(sql)
        return True
    except Exception as e:
        print(f"Error deleting custom mobs: {e}")
        return False
