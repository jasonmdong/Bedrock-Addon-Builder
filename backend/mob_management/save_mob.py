import requests
import json
import re
import os
import time
from typing import Set, Optional
from datetime import datetime
from strands import Agent, tool
from strands.models.openai import OpenAIModel
import API_KEY
import mob_descriptions
import mob_keywords
import get_geometry
import get_bone_data
import neon_db
import mob_complexity
import get_vector_embeddings

# GitHub API configuration
GITHUB_TOKEN = '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'
GITHUB_HEADERS = {
    'Accept': 'application/vnd.github.v3+json',
}
if GITHUB_TOKEN:
    GITHUB_HEADERS['Authorization'] = f'token {GITHUB_TOKEN}'

# Request timeout and retry settings
REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


def make_github_request(url: str, max_retries: int = MAX_RETRIES) -> Optional[requests.Response]:
    """
    Make a GitHub API request with timeout and retry logic.

    Args:
        url: The GitHub API URL to request
        max_retries: Maximum number of retry attempts

    Returns:
        Response object if successful, None otherwise
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(
                url,
                headers=GITHUB_HEADERS,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            return response

        except requests.exceptions.Timeout:
            print(f"⚠ Timeout on attempt {attempt + 1}/{max_retries} for {url}")
            if attempt < max_retries - 1:
                print(f"  Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                print(f"✗ Max retries exceeded for {url}")
                return None

        except requests.exceptions.ConnectionError as e:
            print(f"⚠ Connection error on attempt {attempt + 1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                print(f"  Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                print(f"✗ Max retries exceeded")
                return None

        except requests.exceptions.RequestException as e:
            print(f"✗ Request error: {e}")
            return None

    return None


def get_file_last_updated(file: dict) -> datetime:
    """
    Gets the last updated date of a GitHub file by fetching its commit history.

    Args:
        file: The file object from GitHub API response

    Returns:
        datetime object of when the file was last updated
    """
    try:
        # Extract the file path from the file object
        file_path = file['path']

        # Use the commits API to get the last commit for this specific file
        commits_url = f"https://api.github.com/repos/Mojang/bedrock-samples/commits?path={file_path}&page=1&per_page=1"

        response = make_github_request(commits_url)

        if not response:
            print(f"  ⚠ Could not fetch commit date for {file['name']}, using current time")
            return datetime.now()

        commits_data = response.json()

        # Get the most recent commit date
        if commits_data and len(commits_data) > 0:
            commit = commits_data[0]
            date_str = commit['commit']['committer']['date']
            # Parse ISO 8601 format: "2024-01-15T10:30:45Z"
            file_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            print(f"  Last updated: {file_date.strftime('%Y-%m-%d')}")
            return file_date
        else:
            print(f"  ⚠ No commit history found for {file['name']}, using current time")
            return datetime.now()

    except Exception as e:
        print(f"  ✗ Error getting file date for {file.get('name', 'unknown')}: {e}")
        return datetime.now()



def get_entity_names_from_github(db_connection: neon_db.NeonDatabaseConnection):
    """
    Fetches the list of files from the Bedrock samples repository
    and extracts entity names with .geo.json files.
    Inserts mob data into the Neon PostgreSQL database.
    """
    # GitHub API endpoint for the directory
    api_url = "https://api.github.com/repos/Mojang/bedrock-samples/contents/resource_pack/models/entity"

    try:
        # Fetch the directory contents with timeout and retry
        print(f"Fetching mob list from GitHub...")
        response = make_github_request(api_url)

        if not response:
            print("✗ Failed to fetch mob list from GitHub after retries")
            return set()

        files = response.json()
        print(f"✓ Successfully fetched {len(files)} files from GitHub")

        # Extract entity names from .geo.json files
        entity_names: Set[str] = set()

        for file in files:
            if file['name'].endswith('.geo.json'):
                # Extract entity name from filename
                # Format is typically: entity_name.geo.json
                entity_name = file['name'].replace('.geo.json', '')
                entity_names.add(entity_name)

                print(f"\nProcessing: {entity_name}")

                # mob_name is entity name
                mob_name = entity_name

                # get the description of the mob
                desc = mob_descriptions.makeMobDescription(entity_name)

                # set prompt to blank since these are official mobs
                prompt = ""

                # get the keywords for the mob
                keywords = mob_keywords.makeMobKeywords(entity_name)
                # separate keywords by comma and store as list
                keywords_list = [keyword.strip() for keyword in keywords.split(',')]

                # get the geometry data for the mob
                geometry = get_geometry.get_geometry_json(entity_name)

                # create the embedding vector for each mob
                embeddings = get_vector_embeddings.generate_mob_embedding(entity_name, keywords_list, desc, API_KEY.MY_API_KEY)

                # create the bone metadata for the mob
                bones = get_bone_data.extract_bone_metadata(geometry)

                # create the complexity score for the mob
                complexity = mob_complexity.makeMobComplexity(entity_name)

                # is_official is true
                official = True

                # get the creation/last updated date from GitHub file metadata
                file_commit_date = get_file_last_updated(file)
                creation_date = file_commit_date.isoformat()

                # Insert into database
                if geometry:
                    db_connection.insert_mob(
                        mob_name=mob_name,
                        mob_description=desc,
                        prompt=prompt,
                        mob_keywords=keywords_list,
                        mob_geometry=geometry,
                        mob_embedding=embeddings,
                        bone_metadata=bones,
                        complexity_score=complexity,
                        is_official=official,
                        creation_date=creation_date
                    )
                else:
                    print(f"⚠ Skipping {entity_name} - no geometry data")

        # Sort and print the entity names
        if entity_names:
            print(f"\n{'='*60}")
            print(f"✓ Processed {len(entity_names)} entities with .geo.json files")
            print(f"{'='*60}")
        else:
            print("No .geo.json files found.")

        return entity_names

    except requests.exceptions.RequestException as e:
        print(f"✗ Error fetching data from GitHub: {e}")
        return set()




if __name__ == "__main__":
    # Set up database connection
    connection_string = 'postgresql://neondb_owner:npg_gyK7U5GZOhDS@ep-restless-scene-a876hfcf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require'

    db = neon_db.NeonDatabaseConnection(connection_string)

    # Connect to database
    if db.connect():
        # Create table if it doesn't exist
        db.create_table()

        # Fetch and insert mobs
        get_entity_names_from_github(db)

        # Disconnect
        db.disconnect()
    else:
        print("Failed to connect to database")

