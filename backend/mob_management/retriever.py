"""
Retrieve mobs from the database.

Part of CRUD operations:
- create: save_mob.py (fetch from GitHub and insert)
- read: retriever.py (this file - get mobs from database)
- update: updater.py (modify existing mobs)
- delete: deleter.py (remove mobs from database)
"""
from typing import List, Dict, Any, Optional
from backend.database import fetch_all, fetch_one


def get_template_mob_by_name(mob_name: str) -> Optional[Dict[str, Any]]:
    """
    Get a template mob based on a partial name match.
    
    When user creates a mob from a template, search for mobs where mob_name 
    contains the search term. Returns the most recently created mob.
    If multiple mobs were created on the same day, returns the one with 
    the shortest name.
    
    Args:
        mob_name: The mob name or partial name to search for
    
    Returns:
        The matched mob record, or None if no matches found
        
    Raises:
        ValueError: If no mobs are found matching the search
    """
    # Search for mobs where mob_name contains the search term (case-insensitive)
    sql = """
        SELECT * FROM mob_geometries 
        WHERE LOWER(mob_name) LIKE LOWER(%s)
        ORDER BY 
            creation_date DESC,
            LENGTH(mob_name) ASC
        LIMIT 1
    """
    
    # Add wildcards for partial matching
    search_term = f"%{mob_name}%"
    result = fetch_one(sql, (search_term,))
    
    if not result:
        raise ValueError(
            f"No template mob found matching '{mob_name}'. "
            f"Please check the mob name and try again."
        )
    
    return result


def find_similar_mobs(
    query: str,
    limit: int = 5,
    min_similarity: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Find mobs in the database that are similar to the user's query.
    
    Args:
        query: User's prompt describing desired mob
        limit: Maximum number of results to return
        min_similarity: Minimum similarity score (0-1)
    
    Returns:
        List of similar mob records from database
    """
    # TODO: Implement similarity matching logic
    # This could use:
    # - Semantic search on mob descriptions
    # - Vector embeddings similarity
    # - Keyword matching
    # - Characteristics matching (type, size, etc.)
    
    # Placeholder: return all mobs for now
    sql = "SELECT * FROM mob_geometries LIMIT %s"
    results = fetch_all(sql, (limit,))
    return results or []


def get_mob_by_name(mob_name: str) -> Optional[Dict[str, Any]]:
    """Get a specific mob from the database by exact name match."""
    sql = "SELECT * FROM mob_geometries WHERE mob_name = %s"
    return fetch_one(sql, (mob_name,))


def get_all_mobs() -> List[Dict[str, Any]]:
    """Get all mobs from the database."""
    sql = "SELECT * FROM mob_geometries"
    return fetch_all(sql) or []


def get_all_mob_names() -> List[str]:
    """
    Get all mob names from the database for dropdown selection.
    
    Returns:
        List of mob names sorted alphabetically
    """
    sql = "SELECT mob_name FROM mob_geometries ORDER BY mob_name ASC"
    results = fetch_all(sql)
    if results:
        return [row.get('mob_name') for row in results if row.get('mob_name')]
    return []
