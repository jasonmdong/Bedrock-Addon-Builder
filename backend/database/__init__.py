"""Database module for Bedrock Addon Builder."""

def __getattr__(name):
    """Lazy load database functions on demand."""
    if name == 'get_connection':
        from .db import get_connection
        return get_connection
    elif name == 'get_db_url':
        from .db import get_db_url
        return get_db_url
    elif name == 'execute_query':
        from .db import execute_query
        return execute_query
    elif name == 'fetch_all':
        from .db import fetch_all
        return fetch_all
    elif name == 'fetch_one':
        from .db import fetch_one
        return fetch_one
    elif name == 'Database':
        from .db import Database
        return Database
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["get_connection", "get_db_url", "execute_query", "fetch_all", "fetch_one", "Database"]
