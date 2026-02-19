import requests
import json
import time
from typing import Dict, Any, Optional

# Request settings
REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


def get_geometry_json(entity_name: str) -> Optional[Dict[str, Any]]:
    """
    Fetches the complete JSON geometry data for a mob from GitHub.

    Args:
        entity_name: The name of the mob entity (e.g., 'creeper')

    Returns:
        The full JSON data as a dictionary, or None if the request fails
    """
    url = f"https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity/{entity_name}.geo.json"

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            # Parse and return the JSON
            geometry_json = response.json()
            return geometry_json

        except requests.exceptions.Timeout:
            print(f"  ⚠ Timeout fetching {entity_name} geometry (attempt {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                print(f"  ✗ Max retries exceeded for {entity_name}")
                return None

        except requests.exceptions.ConnectionError as e:
            print(f"  ⚠ Connection error for {entity_name} (attempt {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                print(f"  ✗ Failed to fetch {entity_name} geometry after {MAX_RETRIES} attempts")
                return None

        except requests.exceptions.RequestException as e:
            print(f"  ✗ Error fetching geometry for {entity_name}: {e}")
            return None

        except json.JSONDecodeError as e:
            print(f"  ✗ Error parsing JSON for {entity_name}: {e}")
            return None

    return None

