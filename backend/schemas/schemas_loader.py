"""Schema loading and management."""
import json
from pathlib import Path
from backend.config.settings import SCHEMA_PATH


def load_schema() -> dict:
    """Load the mob spec JSON schema."""
    try:
        with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


# Cache the schema on load
SPEC_SCHEMA = load_schema()
