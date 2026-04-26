import psycopg2
from psycopg2.extras import Json
from typing import Optional, List, Dict, Any
import json


class NeonDatabaseConnection:
    """Connection manager for Neon PostgreSQL database."""

    def __init__(self, connection_string: str):
        """
        Initialize connection to Neon PostgreSQL database.

        Args:
            connection_string: PostgreSQL connection string from Neon
        """
        self.connection_string = connection_string
        self.conn = None

    def connect(self) -> bool:
        """
        Establish connection to the database.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.conn = psycopg2.connect(self.connection_string)
            print("✓ Connected to Neon PostgreSQL database")
            return True
        except psycopg2.Error as e:
            print(f"✗ Error connecting to database: {e}")
            return False

    def disconnect(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            print("✓ Disconnected from database")

    def create_table(self) -> bool:
        """
        Create the mob_geometries table if it doesn't exist.

        Returns:
            True if successful, False otherwise
        """
        try:
            cursor = self.conn.cursor()

            create_table_sql = """
            CREATE TABLE IF NOT EXISTS mob_geometries (
                mob_id SERIAL PRIMARY KEY,
                mob_name VARCHAR(255) NOT NULL,
                mob_description TEXT,
                prompt TEXT,
                mob_keywords TEXT[],
                mob_geometry JSONB NOT NULL,
                mob_embedding vector(1536),
                bone_metadata JSONB,
                complexity_score INT,
                is_official BOOLEAN,
                creation_date TIMESTAMP,
                mob_spec JSONB,
                texture_data TEXT
            );
            """

            cursor.execute(create_table_sql)
            self.conn.commit()

            # Add columns if they don't exist (for existing tables)
            alter_sql = [
                "ALTER TABLE mob_geometries ADD COLUMN IF NOT EXISTS mob_spec JSONB",
                "ALTER TABLE mob_geometries ADD COLUMN IF NOT EXISTS texture_data TEXT",
            ]
            for sql in alter_sql:
                try:
                    cursor.execute(sql)
                    self.conn.commit()
                except Exception:
                    self.conn.rollback()

            cursor.close()
            print("✓ Table created or already exists")
            return True
        except psycopg2.Error as e:
            print(f"✗ Error creating table: {e}")
            self.conn.rollback()
            return False

    def insert_mob(self,
                   mob_name: str,
                   mob_description: str,
                   prompt: str,
                   mob_keywords: List[str],
                   mob_geometry: Dict[str, Any],
                   mob_embedding: Optional[List[float]] = None,
                   bone_metadata: Optional[Dict[str, Any]] = None,
                   complexity_score: Optional[int] = None,
                   is_official: bool = True,
                   creation_date: Optional[str] = None,
                   mob_spec: Optional[Dict[str, Any]] = None,
                   texture_data: Optional[str] = None) -> bool:
        """
        Insert a mob record into the database.

        Args:
            mob_name: Name of the mob
            mob_description: Description of the mob
            prompt: Prompt text (can be empty string)
            mob_keywords: List of keywords
            mob_geometry: Complete geometry JSON as dict
            mob_embedding: Optional embedding vector (list of 1536 floats)
            bone_metadata: Optional bone metadata as dict
            complexity_score: Optional complexity score (0-100)
            is_official: Whether mob is official (default True)
            creation_date: Creation date as string (ISO format)

        Returns:
            True if insert successful, False otherwise
        """
        try:
            cursor = self.conn.cursor()

            insert_sql = """
            INSERT INTO mob_geometries 
            (mob_name, mob_description, prompt, mob_keywords, mob_geometry, mob_embedding, bone_metadata, complexity_score, is_official, creation_date, mob_spec, texture_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """

            cursor.execute(insert_sql, (
                mob_name,
                mob_description,
                prompt,
                mob_keywords,
                Json(mob_geometry),  # JSONB field
                mob_embedding,  # vector field
                Json(bone_metadata) if bone_metadata is not None else None,  # JSONB field - None if no bone data
                complexity_score,
                is_official,
                creation_date,
                Json(mob_spec) if mob_spec is not None else None,
                texture_data
            ))

            self.conn.commit()
            cursor.close()
            print(f"✓ Inserted mob: {mob_name}")
            return True
        except psycopg2.Error as e:
            print(f"✗ Error inserting mob {mob_name}: {e}")
            self.conn.rollback()
            return False

    def update_mob(self,
                   mob_name: str,
                   mob_description: str,
                   prompt: str,
                   mob_keywords: List[str],
                   mob_geometry: Dict[str, Any],
                   mob_embedding: Optional[List[float]] = None,
                   bone_metadata: Optional[Dict[str, Any]] = None,
                   complexity_score: Optional[int] = None,
                   creation_date: Optional[str] = None,
                   mob_spec: Optional[Dict[str, Any]] = None,
                   texture_data: Optional[str] = None) -> bool:
        """
        Update an existing mob record in the database.

        Args:
            mob_name: Name of the mob to update (used as identifier)
            mob_description: Updated description
            prompt: Updated prompt text
            mob_keywords: Updated list of keywords
            mob_geometry: Updated geometry JSON
            mob_embedding: Updated embedding vector
            bone_metadata: Updated bone metadata
            complexity_score: Updated complexity score
            creation_date: Updated date (typically set to now)

        Returns:
            True if update successful, False otherwise
        """
        try:
            cursor = self.conn.cursor()

            update_sql = """
            UPDATE mob_geometries 
            SET mob_description = %s,
                prompt = %s,
                mob_keywords = %s,
                mob_geometry = %s,
                mob_embedding = %s,
                bone_metadata = %s,
                complexity_score = %s,
                creation_date = %s,
                mob_spec = %s,
                texture_data = %s
            WHERE mob_name = %s;
            """

            cursor.execute(update_sql, (
                mob_description,
                prompt,
                mob_keywords,
                Json(mob_geometry),
                mob_embedding,
                Json(bone_metadata) if bone_metadata is not None else None,
                complexity_score,
                creation_date,
                Json(mob_spec) if mob_spec is not None else None,
                texture_data,
                mob_name
            ))

            rows_affected = cursor.rowcount
            self.conn.commit()
            cursor.close()

            if rows_affected > 0:
                print(f"✓ Updated mob: {mob_name}")
                return True
            else:
                print(f"⚠ No mob found with name: {mob_name}")
                return False

        except psycopg2.Error as e:
            print(f"✗ Error updating mob {mob_name}: {e}")
            self.conn.rollback()
            return False

    def get_mob(self, mob_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a mob record from the database.

        Args:
            mob_name: Name of the mob to retrieve

        Returns:
            Dictionary with mob data, or None if not found
        """
        try:
            cursor = self.conn.cursor()

            cursor.execute(
                "SELECT mob_id, mob_name, mob_description, prompt, mob_keywords, "
                "mob_geometry, mob_embedding, bone_metadata, complexity_score, "
                "is_official, creation_date, mob_spec, texture_data "
                "FROM mob_geometries WHERE mob_name = %s",
                (mob_name,)
            )
            row = cursor.fetchone()
            cursor.close()

            if row:
                return {
                    'mob_id': row[0],
                    'mob_name': row[1],
                    'mob_description': row[2],
                    'prompt': row[3],
                    'mob_keywords': row[4],
                    'mob_geometry': row[5],
                    'mob_embedding': row[6],
                    'bone_metadata': row[7],
                    'complexity_score': row[8],
                    'is_official': row[9],
                    'creation_date': row[10],
                    'mob_spec': row[11],
                    'texture_data': row[12]
                }
            return None
        except psycopg2.Error as e:
            print(f"✗ Error retrieving mob {mob_name}: {e}")
            return None

    def get_all_mobs(self) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve all mobs from the database.

        Returns:
            List of mob dictionaries, or None if error
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT mob_id, mob_name, mob_description, mob_keywords, "
                "complexity_score, is_official, creation_date "
                "FROM mob_geometries ORDER BY creation_date DESC"
            )
            rows = cursor.fetchall()
            cursor.close()
            return [
                {
                    'mob_id': row[0],
                    'mob_name': row[1],
                    'mob_description': row[2],
                    'mob_keywords': row[3],
                    'complexity_score': row[4],
                    'is_official': row[5],
                    'creation_date': str(row[6]) if row[6] else None,
                }
                for row in rows
            ]
        except psycopg2.Error as e:
            print(f"✗ Error listing mobs: {e}")
            return None


# Helper function to get connection string
def get_neon_connection():
    """
    Get Neon database connection using the connection string.
    Store the connection string in an environment variable for security.

    Usage:
        import os
        os.environ['DATABASE_URL'] = 'postgresql://neondb_owner:npg_gyK7U5GZOhDS@...'
        db = get_neon_connection()
        db.connect()
    """
    import os
    connection_string = os.environ.get('DATABASE_URL')
    if not connection_string:
        print("Error: DATABASE_URL environment variable not set")
        return None
    return NeonDatabaseConnection(connection_string)

