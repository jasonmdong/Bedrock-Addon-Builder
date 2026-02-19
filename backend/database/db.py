"""Database connection utilities for PostgreSQL (Neon)."""
import os
from typing import Optional, Any, List, Dict


def get_db_url() -> Optional[str]:
    """Get the database connection URL from environment variables."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL environment variable not set. "
            "Set it to: postgresql://user:password@host/dbname?sslmode=require&channel_binding=require"
        )
    return db_url


def get_connection():
    """Create and return a psycopg2 connection to the database."""
    import psycopg2
    
    db_url = get_db_url()
    try:
        conn = psycopg2.connect(db_url)
        return conn
    except psycopg2.OperationalError as e:
        raise RuntimeError(f"Failed to connect to database: {e}")


def execute_query(sql: str, params: Optional[tuple] = None, fetch: bool = False) -> Any:
    """
    Execute a SQL query (INSERT, UPDATE, DELETE, etc.) and optionally fetch results.
    
    Args:
        sql: SQL query string
        params: Optional parameters for the query
        fetch: If True, returns all results; if False, returns None (for INSERT/UPDATE/DELETE)
    
    Returns:
        Query results if fetch=True and query is SELECT, otherwise None
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        
        if fetch:
            results = cur.fetchall()
            conn.commit()
            return results
        else:
            conn.commit()
            return None
    except psycopg2.Error as e:
        conn.rollback()
        raise RuntimeError(f"Database error: {e}")
    finally:
        cur.close()
        conn.close()


def fetch_all(sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
    """Fetch all rows from a SELECT query."""
    return execute_query(sql, params, fetch=True) or []


def fetch_one(sql: str, params: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
    """Fetch a single row from a SELECT query."""
    results = execute_query(sql, params, fetch=True)
    return results[0] if results else None


class Database:
    """Helper class for database operations."""
    
    @staticmethod
    def insert(table: str, data: Dict[str, Any]) -> None:
        """Insert a row into a table."""
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        values = tuple(data.values())
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        execute_query(sql, values)
    
    @staticmethod
    def update(table: str, data: Dict[str, Any], where: Dict[str, Any]) -> None:
        """Update rows in a table."""
        set_clause = ", ".join([f"{k} = %s" for k in data.keys()])
        where_clause = " AND ".join([f"{k} = %s" for k in where.keys()])
        values = tuple(list(data.values()) + list(where.values()))
        sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
        execute_query(sql, values)
    
    @staticmethod
    def delete(table: str, where: Dict[str, Any]) -> None:
        """Delete rows from a table."""
        where_clause = " AND ".join([f"{k} = %s" for k in where.keys()])
        values = tuple(where.values())
        sql = f"DELETE FROM {table} WHERE {where_clause}"
        execute_query(sql, values)
    
    @staticmethod
    def select(table: str, where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Select rows from a table."""
        if where:
            where_clause = " AND ".join([f"{k} = %s" for k in where.keys()])
            values = tuple(where.values())
            sql = f"SELECT * FROM {table} WHERE {where_clause}"
            return fetch_all(sql, values)
        else:
            sql = f"SELECT * FROM {table}"
            return fetch_all(sql)
