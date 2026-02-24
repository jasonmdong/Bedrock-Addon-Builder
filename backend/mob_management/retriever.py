"""
Retrieve mobs from the database.

Part of CRUD operations:
- create: save_mob.py (fetch from GitHub and insert)
- read: retriever.py (this file - get mobs from database)
- update: updater.py (modify existing mobs)
- delete: deleter.py (remove mobs from database)
"""
import os
from typing import List, Dict, Any, Optional
from backend.database import fetch_all, fetch_one


def _generate_query_embedding(query: str) -> List[float]:
    """
    Generate an embedding vector for a user's query text.
    
    Args:
        query: The user's natural language query
        
    Returns:
        List of 1536 floats representing the embedding vector
        
    Raises:
        RuntimeError: If OPENAI_API_KEY is not set
    """
    import openai
    
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable not set")
    
    client = openai.OpenAI(api_key=api_key)
    response = client.embeddings.create(
        input=query,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding


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
    Find mobs in the database that are similar to the user's query
    using vector similarity search (pgvector cosine distance).
    
    Args:
        query: User's prompt describing desired mob (e.g., "a flying fire creature")
        limit: Maximum number of results to return
        min_similarity: Minimum similarity score (0-1), where 1 is identical
    
    Returns:
        List of similar mob records from database, ordered by similarity (highest first).
        Each record includes a 'similarity' field with the cosine similarity score.
    """
    # Generate embedding for the user's query
    try:
        query_embedding = _generate_query_embedding(query)
    except RuntimeError as e:
        print(f"Warning: Could not generate query embedding: {e}")
        # Fallback to returning recent mobs if embeddings unavailable
        sql = "SELECT * FROM mob_geometries ORDER BY creation_date DESC LIMIT %s"
        return fetch_all(sql, (limit,)) or []
    
    # Convert embedding to string format for pgvector
    embedding_str = "[" + ",".join(str(f) for f in query_embedding) + "]"
    
    # Query using pgvector cosine distance operator (<=>)
    # Cosine distance = 1 - cosine similarity, so we compute similarity as (1 - distance)
    sql = """
        SELECT 
            mob_id,
            mob_name,
            mob_description,
            prompt,
            mob_keywords,
            mob_geometry,
            bone_metadata,
            complexity_score,
            is_official,
            creation_date,
            1 - (mob_embedding <=> %s::vector) as similarity
        FROM mob_geometries
        WHERE mob_embedding IS NOT NULL
          AND 1 - (mob_embedding <=> %s::vector) >= %s
        ORDER BY mob_embedding <=> %s::vector ASC
        LIMIT %s
    """
    
    results = fetch_all(sql, (embedding_str, embedding_str, min_similarity, embedding_str, limit))
    return results or []


def find_similar_mobs_by_embedding(
    embedding: List[float],
    limit: int = 5,
    min_similarity: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Find similar mobs using a pre-computed embedding vector.
    
    Useful when you already have an embedding (e.g., from an existing mob)
    and want to find similar ones without re-computing.
    
    Args:
        embedding: Pre-computed embedding vector (1536 floats)
        limit: Maximum number of results to return
        min_similarity: Minimum similarity score (0-1)
    
    Returns:
        List of similar mob records ordered by similarity
    """
    embedding_str = "[" + ",".join(str(f) for f in embedding) + "]"
    
    sql = """
        SELECT 
            mob_id,
            mob_name,
            mob_description,
            prompt,
            mob_keywords,
            mob_geometry,
            bone_metadata,
            complexity_score,
            is_official,
            creation_date,
            1 - (mob_embedding <=> %s::vector) as similarity
        FROM mob_geometries
        WHERE mob_embedding IS NOT NULL
          AND 1 - (mob_embedding <=> %s::vector) >= %s
        ORDER BY mob_embedding <=> %s::vector ASC
        LIMIT %s
    """
    
    results = fetch_all(sql, (embedding_str, embedding_str, min_similarity, embedding_str, limit))
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
