# Database Insertion Module

This module handles inserting mob data into the Neon PostgreSQL database for use in RAG (Retrieval-Augmented Generation) workflows.

## Overview

The database stores mob information including geometry, descriptions, keywords, and vector embeddings. This data enables AI models to find similar existing mobs when users create new ones.

## Two Workflows

### 1. Official Mob Import (`main.py`)

Scrapes official Minecraft Bedrock mobs from GitHub and populates the database.

```
GitHub API → Geometry JSON → Generate metadata → Insert to DB
```

**When to use:** One-time bulk import of vanilla Minecraft mobs.

```bash
cd data/database_insertion
python main.py
```

### 2. User Mob Publishing (`publish_mob.py`)

Saves user-created custom mobs to the database when they click "Publish".

```
User Input → Generate metadata from prompts → Insert to DB
```

**When to use:** Called via `/api/publish` endpoint when users publish mobs.

```python
from publish_mob import publish_or_update_mob

result = publish_or_update_mob(
    mob_name="fire_dragon",
    username="player123",
    prompts=["make it breathe fire", "give it wings"],
    geometry={...}
)
```

## File Reference

| File | Purpose |
|------|---------|
| `main.py` | Scrapes official mobs from GitHub |
| `publish_mob.py` | Publishes user-created mobs |
| `neon_db.py` | Database connection and CRUD operations |
| `get_geometry.py` | Fetches geometry JSON from GitHub |
| `get_bone_data.py` | Extracts bone hierarchy from geometry |
| `get_vector_embeddings.py` | Generates OpenAI embeddings for similarity search |
| `mob_descriptions.py` | LLM-generated mob descriptions |
| `mob_keywords.py` | LLM-generated keywords (hostile, flying, etc.) |
| `mob_complexity.py` | Calculates complexity score |
| `API_KEY.py` | Stores OpenAI API key |

## Database Schema

```sql
CREATE TABLE mob_geometries (
    mob_id SERIAL PRIMARY KEY,
    mob_name VARCHAR(255) NOT NULL,      -- "creeper" or "fire_dragon_player123"
    mob_description TEXT,                 -- "A monster that explodes near players"
    prompt TEXT,                          -- JSON array of user prompts (empty for official)
    mob_keywords TEXT[],                  -- ["hostile", "explodes", "green"]
    mob_geometry JSONB NOT NULL,          -- Full geometry JSON
    mob_embedding vector(1536),           -- OpenAI text-embedding-3-small
    bone_metadata JSONB,                  -- Bone hierarchy and pivots
    complexity_score INT,                 -- 0-100
    is_official BOOLEAN,                  -- true for vanilla mobs
    creation_date TIMESTAMP
);
```

## Data Flow Comparison

| Step | Official (`main.py`) | User (`publish_mob.py`) |
|------|---------------------|------------------------|
| **Source** | GitHub API | Frontend input |
| **Name** | `entity_name` | `{mob_name}_{username}` |
| **Geometry** | `get_geometry.get_geometry_json()` | Passed from frontend |
| **Description** | `mob_descriptions.makeMobDescription()` | `mob_descriptions.makeMobDescriptionFromPrompts()` |
| **Keywords** | `mob_keywords.makeMobKeywords()` | `mob_keywords.makeMobKeywordsFromPrompts()` |
| **Prompts** | Empty `""` | JSON array of user prompts |
| **is_official** | `True` | `False` |

## Vector Embeddings

Embeddings are generated using OpenAI's `text-embedding-3-small` model (1536 dimensions).

**Input format:**
```
Mob: {name} | Keywords: {keywords} | Description: {description}
```

**Example:**
```
Mob: fire_dragon_player123 | Keywords: hostile, flying, fire, dragon | Description: A flying creature that breathes fire and is immune to lava.
```

These embeddings enable similarity search via pgvector's cosine distance operator (`<=>`).

## API Integration

The publish workflow is exposed via FastAPI:

```
POST /api/publish
{
    "mob_name": "fire_dragon",
    "username": "player123",
    "prompts": ["make it breathe fire", "give it wings"],
    "geometry": { ... }
}
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (falls back to hardcoded default) |
| `OPENAI_API_KEY` | For embeddings and LLM calls (or use `API_KEY.py`) |

## Bone Metadata Format

Extracted from geometry JSON:

```json
{
    "bone_count": 12,
    "bones": [
        {"name": "body", "parent": null, "pivot": [0, 24, 0]},
        {"name": "head", "parent": "body", "pivot": [0, 24, 0]},
        {"name": "leg0", "parent": "body", "pivot": [-2, 12, 4]}
    ]
}
```

## Supported Geometry Formats

1. **Standard:** `{"minecraft:geometry": [{"bones": [...]}]}`
2. **Alternative:** `{"geometry.entity_name": {"bones": [...]}}`

Both formats are automatically detected by `get_bone_data.extract_bone_metadata()`.
