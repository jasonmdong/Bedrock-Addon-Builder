"""
Publish a user-created mob to the database.

This module handles the "publish" workflow when a user wants to save
their custom mob to the database for RAG (retrieval-augmented generation).

Workflow:
1. User clicks "Publish" button
2. Mob name is set to {mob_name}_{username}
3. User's creation prompts are stored
4. Description and keywords are generated from prompts
5. Geometry and bone metadata are extracted
6. Vector embedding is created for similarity search
7. Everything is saved to the database

Usage:
    from publish_mob import publish_user_mob
    
    result = publish_user_mob(
        mob_name="fire_dragon",
        username="player123",
        prompts=["make it breathe fire", "give it wings"],
        geometry={...}
    )
"""
import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

# Local imports (same pattern as main.py)
import API_KEY
import neon_db
import get_bone_data
import get_vector_embeddings
import mob_descriptions
import mob_keywords
import mob_complexity


# Default database connection string (same as main.py)
DEFAULT_CONNECTION_STRING = 'postgresql://neondb_owner:npg_gyK7U5GZOhDS@ep-restless-scene-a876hfcf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require'


def publish_user_mob(
    mob_name: str,
    username: str,
    prompts: List[str],
    geometry: Dict[str, Any],
    db_connection: Optional[neon_db.NeonDatabaseConnection] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Publish a user-created mob to the database.
    
    This is the main entry point called when a user clicks "Publish".
    Uses the same workflow as main.py but for user-created mobs.
    
    Args:
        mob_name: Base name of the mob (will be suffixed with username)
        username: The user who created the mob
        prompts: List of prompts the user sent to create the mob
        geometry: The mob's geometry JSON data
        db_connection: Optional existing database connection (creates one if not provided)
        api_key: OpenAI API key (falls back to API_KEY.MY_API_KEY)
        
    Returns:
        Dict with success status and mob details
        
    Example:
        result = publish_user_mob(
            mob_name="fire_dragon",
            username="player123",
            prompts=["make it breathe fire", "give it wings", "make it hostile"],
            geometry={...}
        )
    """
    # Get API key
    api_key = api_key or API_KEY.MY_API_KEY
    
    # Track if we created the connection (so we know to close it)
    created_connection = False
    
    try:
        # 1. Set up database connection if not provided
        if db_connection is None:
            connection_string = os.environ.get('DATABASE_URL', DEFAULT_CONNECTION_STRING)
            db_connection = neon_db.NeonDatabaseConnection(connection_string)
            if not db_connection.connect():
                return {
                    "success": False,
                    "error": "Failed to connect to database"
                }
            created_connection = True
        
        # 2. Generate full mob name with username suffix
        full_mob_name = f"{mob_name}_{username}"
        print(f"\nPublishing mob: {full_mob_name}")
        
        # 3. Generate description from prompts (using mob_descriptions module)
        print("  Generating description from prompts...")
        description = mob_descriptions.makeMobDescriptionFromPrompts(mob_name, prompts)
        print(f"  Description: {description[:80]}...")
        
        # 4. Generate keywords from prompts (using mob_keywords module)
        print("  Generating keywords from prompts...")
        keywords_str = mob_keywords.makeMobKeywordsFromPrompts(mob_name, prompts)
        keywords_list = [kw.strip() for kw in keywords_str.split(',') if kw.strip()]
        print(f"  Keywords: {keywords_list}")
        
        # 5. Extract bone metadata from geometry (using get_bone_data module)
        print("  Extracting bone metadata...")
        bone_metadata = get_bone_data.extract_bone_metadata(geometry)
        bone_count = bone_metadata.get("bone_count", 0) if bone_metadata else 0
        print(f"  Extracted {bone_count} bones")
        
        # 6. Generate vector embedding (using get_vector_embeddings module)
        print("  Generating vector embedding...")
        embedding = get_vector_embeddings.generate_mob_embedding(
            full_mob_name, 
            keywords_list, 
            description, 
            api_key
        )
        
        # 7. Calculate complexity score (using mob_complexity or simple heuristic)
        print("  Calculating complexity score...")
        try:
            complexity_score = mob_complexity.makeMobComplexity(mob_name)
        except Exception:
            # Fallback: simple heuristic based on bone count
            complexity_score = min(100, bone_count * 5)
        print(f"  Complexity: {complexity_score}")
        
        # 8. Store prompts as JSON string
        prompts_json = json.dumps(prompts)
        
        # 9. Insert into database (using neon_db.insert_mob like main.py)
        print("  Inserting into database...")
        success = db_connection.insert_mob(
            mob_name=full_mob_name,
            mob_description=description,
            prompt=prompts_json,           # Store prompts array as JSON string
            mob_keywords=keywords_list,
            mob_geometry=geometry,
            mob_embedding=embedding,
            bone_metadata=bone_metadata,
            complexity_score=complexity_score,
            is_official=False,             # User mobs are not official
            creation_date=datetime.now().isoformat()
        )
        
        if success:
            print(f"✓ Successfully published mob: {full_mob_name}")
            return {
                "success": True,
                "mob_name": full_mob_name,
                "description": description,
                "keywords": keywords_list,
                "bone_count": bone_count,
                "complexity_score": complexity_score
            }
        else:
            return {
                "success": False,
                "error": "Database insert failed"
            }
        
    except Exception as e:
        print(f"✗ Error publishing mob: {e}")
        return {
            "success": False,
            "error": str(e)
        }
    finally:
        # Close connection if we created it
        if created_connection and db_connection:
            db_connection.disconnect()


def check_mob_exists(
    mob_name: str, 
    username: str,
    db_connection: Optional[neon_db.NeonDatabaseConnection] = None
) -> bool:
    """
    Check if a mob with this name already exists for this user.
    
    Args:
        mob_name: Base name of the mob
        username: The username
        db_connection: Optional existing database connection
        
    Returns:
        True if mob already exists
    """
    created_connection = False
    
    try:
        if db_connection is None:
            connection_string = os.environ.get('DATABASE_URL', DEFAULT_CONNECTION_STRING)
            db_connection = neon_db.NeonDatabaseConnection(connection_string)
            if not db_connection.connect():
                return False
            created_connection = True
        
        full_mob_name = f"{mob_name}_{username}"
        result = db_connection.get_mob(full_mob_name)
        return result is not None
        
    except Exception as e:
        print(f"Error checking if mob exists: {e}")
        return False
    finally:
        if created_connection and db_connection:
            db_connection.disconnect()


def update_user_mob(
    mob_name: str,
    username: str,
    prompts: List[str],
    geometry: Dict[str, Any],
    db_connection: Optional[neon_db.NeonDatabaseConnection] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update an existing published mob with new data.
    
    Same workflow as publish_user_mob but updates instead of inserts.
    
    Args:
        mob_name: Base name of the mob
        username: The user who created the mob
        prompts: Updated list of prompts
        geometry: Updated geometry JSON
        db_connection: Optional existing database connection
        api_key: OpenAI API key
        
    Returns:
        Dict with success status and mob details
    """
    api_key = api_key or API_KEY.MY_API_KEY
    created_connection = False
    
    try:
        if db_connection is None:
            connection_string = os.environ.get('DATABASE_URL', DEFAULT_CONNECTION_STRING)
            db_connection = neon_db.NeonDatabaseConnection(connection_string)
            if not db_connection.connect():
                return {"success": False, "error": "Failed to connect to database"}
            created_connection = True
        
        full_mob_name = f"{mob_name}_{username}"
        print(f"\nUpdating mob: {full_mob_name}")
        
        # Regenerate all derived fields
        print("  Regenerating description...")
        description = mob_descriptions.makeMobDescriptionFromPrompts(mob_name, prompts)
        
        print("  Regenerating keywords...")
        keywords_str = mob_keywords.makeMobKeywordsFromPrompts(mob_name, prompts)
        keywords_list = [kw.strip() for kw in keywords_str.split(',') if kw.strip()]
        
        print("  Extracting bone metadata...")
        bone_metadata = get_bone_data.extract_bone_metadata(geometry)
        bone_count = bone_metadata.get("bone_count", 0) if bone_metadata else 0
        
        print("  Regenerating embedding...")
        embedding = get_vector_embeddings.generate_mob_embedding(
            full_mob_name, keywords_list, description, api_key
        )
        
        try:
            complexity_score = mob_complexity.makeMobComplexity(mob_name)
        except Exception:
            complexity_score = min(100, bone_count * 5)
        
        prompts_json = json.dumps(prompts)
        
        # Update in database
        print("  Updating in database...")
        success = db_connection.update_mob(
            mob_name=full_mob_name,
            mob_description=description,
            prompt=prompts_json,
            mob_keywords=keywords_list,
            mob_geometry=geometry,
            mob_embedding=embedding,
            bone_metadata=bone_metadata,
            complexity_score=complexity_score,
            creation_date=datetime.now().isoformat()
        )
        
        if success:
            print(f"✓ Successfully updated mob: {full_mob_name}")
            return {
                "success": True,
                "mob_name": full_mob_name,
                "description": description,
                "keywords": keywords_list,
                "bone_count": bone_count,
                "updated": True
            }
        else:
            return {"success": False, "error": "Database update failed"}
        
    except Exception as e:
        print(f"✗ Error updating mob: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if created_connection and db_connection:
            db_connection.disconnect()


def publish_or_update_mob(
    mob_name: str,
    username: str,
    prompts: List[str],
    geometry: Dict[str, Any],
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Publish a new mob or update if it already exists.
    
    Convenience function that checks existence and calls the appropriate method.
    
    Args:
        mob_name: Base name of the mob
        username: The user who created the mob
        prompts: List of prompts used to create the mob
        geometry: The mob's geometry JSON
        api_key: OpenAI API key
        
    Returns:
        Dict with success status and mob details
    """
    api_key = api_key or API_KEY.MY_API_KEY
    
    # Create a single connection for both operations
    connection_string = os.environ.get('DATABASE_URL', DEFAULT_CONNECTION_STRING)
    db = neon_db.NeonDatabaseConnection(connection_string)
    
    if not db.connect():
        return {"success": False, "error": "Failed to connect to database"}
    
    try:
        if check_mob_exists(mob_name, username, db):
            print(f"Mob {mob_name}_{username} exists, updating...")
            return update_user_mob(mob_name, username, prompts, geometry, db, api_key)
        else:
            print(f"Mob {mob_name}_{username} is new, publishing...")
            return publish_user_mob(mob_name, username, prompts, geometry, db, api_key)
    finally:
        db.disconnect()


# Command-line interface for testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Publish a user mob to the database")
    parser.add_argument("--mob-name", required=True, help="Base name of the mob")
    parser.add_argument("--username", required=True, help="Username of the creator")
    parser.add_argument("--prompts", nargs="+", required=True, help="Creation prompts")
    parser.add_argument("--geometry-file", required=True, help="Path to geometry JSON file")
    
    args = parser.parse_args()
    
    # Load geometry from file
    with open(args.geometry_file, 'r') as f:
        geometry = json.load(f)
    
    # Publish the mob
    result = publish_or_update_mob(
        mob_name=args.mob_name,
        username=args.username,
        prompts=args.prompts,
        geometry=geometry
    )
    
    print("\nResult:")
    print(json.dumps(result, indent=2))
