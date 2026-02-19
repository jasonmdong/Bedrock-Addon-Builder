"""
Mob management module for CRUD operations on mobs.

- CREATE: save_mob.py (fetch from GitHub and insert new mobs)
- READ: retriever.py (get mobs from database)
- UPDATE: updater.py (modify existing mobs)
- DELETE: deleter.py (remove mobs from database)
"""

# Lazy imports to avoid loading psycopg2 until needed
def __getattr__(name):
    """Lazy load modules on demand."""
    if name == 'find_similar_mobs':
        from .retriever import find_similar_mobs
        return find_similar_mobs
    elif name == 'get_mob_by_name':
        from .retriever import get_mob_by_name
        return get_mob_by_name
    elif name == 'get_all_mobs':
        from .retriever import get_all_mobs
        return get_all_mobs
    elif name == 'get_template_mob_by_name':
        from .retriever import get_template_mob_by_name
        return get_template_mob_by_name
    elif name == 'update_mob_in_db':
        from .updater import update_mob_in_db
        return update_mob_in_db
    elif name == 'update_mob_description':
        from .updater import update_mob_description
        return update_mob_description
    elif name == 'update_mob_keywords':
        from .updater import update_mob_keywords
        return update_mob_keywords
    elif name == 'update_mob_complexity':
        from .updater import update_mob_complexity
        return update_mob_complexity
    elif name == 'update_mob_embedding':
        from .updater import update_mob_embedding
        return update_mob_embedding
    elif name == 'update_mob_geometry':
        from .updater import update_mob_geometry
        return update_mob_geometry
    elif name == 'delete_mob_by_id':
        from .deleter import delete_mob_by_id
        return delete_mob_by_id
    elif name == 'delete_mob_by_name':
        from .deleter import delete_mob_by_name
        return delete_mob_by_name
    elif name == 'delete_all_official_mobs':
        from .deleter import delete_all_official_mobs
        return delete_all_official_mobs
    elif name == 'delete_all_custom_mobs':
        from .deleter import delete_all_custom_mobs
        return delete_all_custom_mobs
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # READ operations
    "find_similar_mobs",
    "get_mob_by_name",
    "get_all_mobs",
    "get_template_mob_by_name",
    # UPDATE operations
    "update_mob_in_db",
    "update_mob_description",
    "update_mob_keywords",
    "update_mob_complexity",
    "update_mob_embedding",
    "update_mob_geometry",
    # DELETE operations
    "delete_mob_by_id",
    "delete_mob_by_name",
    "delete_all_official_mobs",
    "delete_all_custom_mobs",
]
