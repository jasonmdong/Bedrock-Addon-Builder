"""FastAPI route handlers for the web API."""
import tempfile
import uuid
import threading
import sys
import os
from pathlib import Path
from typing import Optional
import json
import httpx

from fastapi import File, Form, HTTPException, Body, UploadFile, Response
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, JSONResponse
import shutil

from backend.schemas.spec_utils import (
    read_mob_spec, write_mob_spec, delete_mob_spec, list_mob_names,
    read_current_spec, write_current_spec, apply_spec_patch,
    validate_spec, SpecValidationError
)
from backend.llm.llm import llm_rewrite_spec, llm_generate_geometry
from backend.llm.category_context import CATEGORIES, CATEGORY_LABELS
from backend.core.packaging import build_addon
from backend.core.builders import make_png_rgba

from backend.core.core import BACKEND_DIR, COLOR_WORDS, SPECS_DIR, FRONTEND_DIR, LOCAL_LLM_DEV

# In-memory cache for geometry fetched from GitHub (avoids burning rate limit)
_geometry_cache: dict[str, dict] = {}
_github_file_list_cache: list[dict] | None = None


def _save_upload(tmpdir: Path, uf: Optional[UploadFile]) -> Optional[Path]:
    """Save an uploaded file to a temporary directory."""
    if not uf:
        return None
    if not uf.filename:
        return None
    suffix = "".join(Path(uf.filename).suffixes) or ".zip"
    dest = tmpdir / f"upload_{uuid.uuid4().hex}{suffix}"
    with dest.open("wb") as f:
        shutil.copyfileobj(uf.file, f)
    return dest


def _select_artifact(artifacts: dict, build_mode: str) -> tuple[str, Path]:
    """Select the appropriate artifact based on build mode."""
    mode = (build_mode or "bundle").lower()
    if mode == "mcworld":
        path_str = artifacts.get("mcworld")
        if not path_str:
            raise HTTPException(
                status_code=400,
                detail="Could not create .mcworld: No base world template found on server. "
                       "Please ensure a 'base_world' folder or 'base_world.mcworld' exists in the 'templates' directory "
                       "and is not gitignored."
            )
        return "mcworld", Path(path_str)
    elif mode == "mcaddon":
        return "mcaddon", Path(artifacts["mcaddon"])
    elif mode == "resources":
        return "resources", Path(artifacts["res_mcpack"])
    elif mode == "behavior":
        return "behavior", Path(artifacts["beh_mcpack"])
    return "bundle", Path(artifacts["bundle_zip"])


def _build_and_bundle(res_path: Optional[Path],
                      beh_path: Optional[Path],
                      specs_override: Optional[list[dict]] = None,
                      build_mode: str = "bundle",
                      textures_dir: Optional[Path] = None) -> tuple[str, Path, dict]:
    """Build and bundle addon, selecting appropriate specs."""
    if specs_override:
        specs = [validate_spec(s) for s in specs_override]
        print(f"[BUILD] Overriding specs with: {[s.get('short_name') for s in specs]}")
    else:
        names = list_mob_names()
        if not names:
            specs = [read_mob_spec("current")]
        else:
            specs = [read_mob_spec(n) for n in names]
        print(f"[BUILD] Using all discovered mobs: {[s.get('short_name') for s in specs]}")

    out_dir = Path(tempfile.mkdtemp(prefix="out_"))
    artifacts = build_addon(specs, out_dir, res_path, beh_path, textures_dir=textures_dir)
    kind, artifact_path = _select_artifact(artifacts, build_mode)
    return kind, artifact_path, artifacts


# Route handlers

def get_mobs():
    """List all mob names."""
    return {"mobs": list_mob_names()}


def get_templates():
    """Get vanilla mob templates."""
    import json
    path = BACKEND_DIR / "data" / "vanilla_mobs.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Failed to load templates: {e}")
    return {"mobs": {}}


async def get_template_mob_from_database(mob_name: str):
    """Load a template mob from the database.
    
    Searches for mobs in the database where the name contains the search term.
    Returns the most recently updated mob; if multiple were updated the same day,
    returns the one with the shortest name.
    
    This is used when users create a mob from a database template instead of GitHub.
    """
    if not mob_name:
        raise HTTPException(status_code=400, detail="mob_name is required")
    
    try:
        from backend.mob_management import get_template_mob_by_name
        
        template_mob = get_template_mob_by_name(mob_name)
        
        return {
            "mob": template_mob,
            "source": "database"
        }
    except ValueError as e:
        # No mob found - return 404 with error message
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"[ERROR] Failed to load template mob from database: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load template: {str(e)}")


async def get_all_template_mob_names():
    """Get all available mob names from the database for dropdown selection."""
    try:
        from backend.mob_management import get_all_mob_names
        
        mob_names = get_all_mob_names()
        return {
            "mobs": mob_names,
            "source": "database",
            "count": len(mob_names)
        }
    except Exception as e:
        print(f"[ERROR] Failed to fetch template mob names: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch mobs: {str(e)}")


def _normalize_geometry(geometry_data: dict) -> dict:
    """Convert old-format Bedrock geometry (geometry.X: {...}) to the modern
    minecraft:geometry array format so all downstream code can use a single check.
    Old format example:  {"format_version": "1.8.0", "geometry.bat": { ... }}
    New format example:  {"format_version": "1.21.0", "minecraft:geometry": [{"description": {"identifier": "geometry.bat", ...}, "bones": [...]}]}
    """
    if "minecraft:geometry" in geometry_data:
        return geometry_data  # already new format

    converted_entries = []
    for key, value in geometry_data.items():
        if key == "format_version":
            continue
        if not key.startswith("geometry.") or not isinstance(value, dict):
            continue
        # Build a new-format entry from the old-format block
        desc = {"identifier": key}
        # Carry over description-level fields
        for field in ("texturewidth", "texture_width"):
            if field in value:
                desc["texture_width"] = value[field]
        for field in ("textureheight", "texture_height"):
            if field in value:
                desc["texture_height"] = value[field]
        for field in ("visible_bounds_width", "visible_bounds_height", "visible_bounds_offset"):
            if field in value:
                desc[field] = value[field]
        # Ensure texture dimensions are present (required for proper UV mapping)
        if "texture_width" not in desc:
            desc["texture_width"] = 64
        if "texture_height" not in desc:
            desc["texture_height"] = 64
        entry = {"description": desc}
        if "bones" in value:
            entry["bones"] = value["bones"]
        converted_entries.append(entry)

    if not converted_entries:
        return geometry_data  # nothing to convert

    print(f"[GEOMETRY] Converted old-format geometry keys: {[e['description']['identifier'] for e in converted_entries]}")
    return {
        "format_version": geometry_data.get("format_version", "1.12.0"),
        "minecraft:geometry": converted_entries
    }


async def generate_mob_from_similar(payload: dict = Body(...)):
    """Generate a new mob spec using AI based on similar mobs in the database.
    
    This is the RAG-powered mob generation endpoint. It:
    1. Searches for similar mobs using vector similarity
    2. Uses those mobs as training examples for the LLM
    3. Generates a new mob spec based on the user's description
    
    Request body:
        query: str - Description of the desired mob (e.g., "a flying fire dragon")
        custom_name: str - The name for the new mob
        provider: str (optional) - LLM provider to use
        api_key: str (optional) - API key for the provider
    
    Returns:
        mob: dict - The generated mob spec
        similar_mobs: list - Names of mobs used as examples
        source: str - "ai_generated"
    """
    data = payload or {}
    query = data.get("query", "").strip()
    custom_name = data.get("custom_name", "").strip()
    provider = data.get("provider")
    api_key = data.get("api_key")
    
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    if not custom_name:
        raise HTTPException(status_code=400, detail="custom_name is required")
    
    try:
        from backend.mob_management import find_similar_mobs
        from backend.core.core import DEFAULTS
        
        # Find similar mobs for RAG context
        similar_mobs = find_similar_mobs(query, limit=5, min_similarity=0.3)
        
        if not similar_mobs:
            print(f"[AI-GEN] No similar mobs found for: {query}")
            similar_mobs = []
        
        # Build context from similar mobs
        examples_context = []
        similar_names = []
        for mob in similar_mobs:
            mob_name = mob.get("mob_name", "unknown")
            similar_names.append(mob_name)
            examples_context.append({
                "name": mob_name,
                "description": mob.get("mob_description", ""),
                "keywords": mob.get("mob_keywords", []),
                "geometry": mob.get("mob_geometry", {}).get("description", {}).get("identifier", ""),
                "complexity": mob.get("complexity_score", 0)
            })
        
        print(f"[AI-GEN] Found {len(similar_mobs)} similar mobs: {similar_names}")
        
        # Build the LLM prompt
        safe_name = custom_name.lower().replace(" ", "_").replace("-", "_")
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
        
        # Use the most similar mob as the template base for geometry
        template_base = None
        template_geometry = "geometry.cow"  # fallback
        if similar_mobs:
            best_match = similar_mobs[0]  # highest similarity first
            template_base = best_match.get("mob_name")
            # Try to get geometry identifier from the similar mob
            mob_geo = best_match.get("mob_geometry", {})
            if isinstance(mob_geo, dict):
                # Try minecraft:geometry format first
                mc_geo = mob_geo.get("minecraft:geometry", [])
                if mc_geo and len(mc_geo) > 0:
                    geo_id = mc_geo[0].get("description", {}).get("identifier")
                    if geo_id:
                        template_geometry = geo_id
                # Fallback to description.identifier
                elif mob_geo.get("description", {}).get("identifier"):
                    template_geometry = mob_geo["description"]["identifier"]
            # If still no geometry, use geometry.{mob_name}
            if template_geometry == "geometry.cow" and template_base:
                template_geometry = f"geometry.{template_base}"
            print(f"[AI-GEN] Using template base: {template_base}, geometry: {template_geometry}")
        
        system_prompt = """You are a Minecraft Bedrock mob generator. Generate a valid mob specification JSON based on the user's description and the example mobs provided.

The output must be a valid JSON object with these required fields:
- identifier: string in format "custom:{short_name}"
- display_name: string (human-readable name)
- short_name: string (lowercase, alphanumeric + underscore only)
- hp: number (1-2048)
- damage: number (0-128)
- speed: number (0-2)
- collision_box: object with width (0.1-5) and height (0.5-5)
- geometry: string (geometry identifier - DO NOT change this, use the provided value)
- scale: number (0.2-5.0)
- components: object (Bedrock behavior components)

Use the example mobs as inspiration for appropriate stats and components. Match the complexity and style of similar creatures.
IMPORTANT: Keep the geometry field exactly as provided - do not invent new geometry identifiers."""

        user_prompt = f"""Create a mob matching this description: "{query}"

The mob should be named "{custom_name}" (short_name: "{safe_name}")
The geometry is already set to: "{template_geometry}" - do not change this.

Example similar mobs for reference:
{json.dumps(examples_context, indent=2)}

Generate a complete mob specification JSON. Only output the JSON, no explanation."""

        # Call the LLM
        base_spec = dict(DEFAULTS)
        base_spec["identifier"] = f"custom:{safe_name}"
        base_spec["display_name"] = custom_name.title()
        base_spec["short_name"] = safe_name
        base_spec["geometry"] = template_geometry
        if template_base:
            base_spec["_template_base"] = template_base
        
        try:
            generated_spec = llm_rewrite_spec(
                prompt=user_prompt,
                current=base_spec,
                provider=provider,
                api_key=api_key
            )
        except Exception as llm_err:
            print(f"[AI-GEN] LLM generation failed: {llm_err}")
            generated_spec = base_spec
        
        # Ensure the spec has the correct naming and template base
        generated_spec["identifier"] = f"custom:{safe_name}"
        generated_spec["display_name"] = custom_name.title()
        generated_spec["short_name"] = safe_name
        generated_spec["geometry"] = template_geometry  # Keep the matched geometry
        if template_base:
            generated_spec["_template_base"] = template_base  # For frontend geometry fetch
        
        return {
            "mob": generated_spec,
            "similar_mobs": similar_names,
            "source": "ai_generated"
        }
        
    except Exception as e:
        print(f"[ERROR] AI mob generation failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate mob: {str(e)}")


async def generate_complete_mob(payload: dict = Body(...)):
    """Generate a complete mob with AI-powered spec AND geometry generation.
    
    This is the comprehensive AI mob creation endpoint that:
    1. Searches for similar mobs using vector similarity (RAG)
    2. AI "thinks through" what features the mob should have based on its name
    3. Generates the mob behavior spec (stats, components)
    4. Generates custom geometry JSON
    5. Returns everything needed for a complete mob
    
    Request body:
        mob_name: str - The name/description of the mob (e.g., "fire_dragon", "ice golem")
        provider: str (optional) - LLM provider to use (openai, deepseek, etc.)
        api_key: str (optional) - API key for the provider
    
    Returns:
        mob: dict - The generated mob spec
        geometry: dict - The generated geometry JSON
        reasoning: str - AI's reasoning about the mob's features
        similar_mobs: list - Names of mobs used as RAG context
        source: str - "ai_generated_complete"
    """
    data = payload or {}
    mob_name = data.get("mob_name", "").strip()
    provider = data.get("provider")
    api_key = data.get("api_key")
    
    if not mob_name:
        raise HTTPException(status_code=400, detail="mob_name is required")
    
    try:
        from backend.mob_management import find_similar_mobs
        from backend.core.core import DEFAULTS
        
        # Create safe name from input
        safe_name = mob_name.lower().replace(" ", "_").replace("-", "_")
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
        display_name = mob_name.replace("_", " ").title()
        
        print(f"[AI-COMPLETE] Generating complete mob: {mob_name} -> {safe_name}")
        
        # Step 1: Find similar mobs for RAG context
        similar_mobs = find_similar_mobs(mob_name, limit=5, min_similarity=0.25)
        
        # Build examples context with geometry data
        examples_context = []
        geometry_examples = []
        similar_names = []
        
        for mob in similar_mobs:
            mob_db_name = mob.get("mob_name", "unknown")
            similar_names.append(mob_db_name)
            
            # Extract spec-relevant info
            examples_context.append({
                "name": mob_db_name,
                "description": mob.get("mob_description", ""),
                "keywords": mob.get("mob_keywords", []),
                "complexity": mob.get("complexity_score", 0)
            })
            
            # Extract geometry structure for geometry generation
            geo = mob.get("mob_geometry", {})
            if geo and "minecraft:geometry" in geo:
                geo_data = geo["minecraft:geometry"]
                if isinstance(geo_data, list) and len(geo_data) > 0:
                    bones_summary = []
                    for bone in geo_data[0].get("bones", [])[:10]:  # Limit bones
                        bone_info = {"name": bone.get("name", ""), "parent": bone.get("parent")}
                        if bone.get("cubes"):
                            bone_info["cube_count"] = len(bone["cubes"])
                        bones_summary.append(bone_info)
                    geometry_examples.append({
                        "mob_name": mob_db_name,
                        "identifier": geo_data[0].get("description", {}).get("identifier", ""),
                        "bones": bones_summary
                    })
        
        print(f"[AI-COMPLETE] Found {len(similar_mobs)} similar mobs: {similar_names}")
        
        # Step 2: AI "Thinking" - Analyze what features this mob should have based on real-world characteristics
        thinking_prompt = f"""Analyze the mob name "{mob_name}" and determine what REAL-WORLD physical features it should have.

Think about what this creature would look like in real life or fantasy:

1. BODY STRUCTURE:
   - What type of creature is this? (humanoid, quadruped, biped, flying, aquatic, insect, serpentine, etc.)
   - How many legs does it have? (0, 2, 4, 6, 8, or more?)
   - Does it have arms/front limbs separate from legs?
   - What is its general body shape? (bulky, slender, round, elongated?)

2. DISTINCTIVE FEATURES - What makes this creature UNIQUE and recognizable?
   - Examples: elephants have long trunks and big ears, rhinos have horns, birds have beaks and wings
   - Does it have a tail? What kind? (long thin tail, bushy tail, armored tail, etc.)
   - Does it have horns, antlers, tusks, or spikes?
   - Does it have wings, fins, or special appendages?
   - Does it have a distinctive head shape? (long snout, beak, mandibles, multiple eyes?)
   - Any special body parts? (shell, armor plates, tentacles, stinger, claws?)

3. PROPORTIONS:
   - Is the head large or small relative to body?
   - Are the limbs long or short, thick or thin?
   - What's the rough scale compared to a human? (tiny insect, cat-sized, human-sized, elephant-sized?)

4. STATS & BEHAVIOR:
   - HP (1-2048): Based on size and toughness
   - Damage (0-128): Based on natural weapons
   - Speed (0-2): Based on how fast it would move
   - What Bedrock behavior components fit? (can_fly, shooter, explode, tameable, etc.)

Similar mobs from database for reference:
{json.dumps(examples_context, indent=2)}

Output a JSON object with DETAILED body part list:
{{
  "creature_type": "detailed description (e.g., 'large quadruped mammal with trunk')",
  "body_parts": ["DETAILED list - include ALL distinct parts like: body, head, trunk, left_ear, right_ear, leg_front_left, leg_front_right, leg_back_left, leg_back_right, tail, tusk_left, tusk_right"],
  "distinctive_features": {{
    "has_trunk": false,
    "has_tail": true,
    "tail_type": "thin/bushy/armored",
    "has_wings": false,
    "has_horns": false,
    "horn_count": 0,
    "leg_count": 4,
    "has_ears": true,
    "ear_type": "normal/large/pointed",
    "has_beak": false,
    "has_shell": false,
    "extra_features": ["any other unique parts"]
  }},
  "proportions": {{
    "head_size": "small/medium/large relative to body",
    "body_shape": "bulky/slender/round",
    "limb_thickness": "thin/medium/thick",
    "overall_scale": 1.0
  }},
  "suggested_stats": {{"hp": number, "damage": number, "speed": number, "scale": number}},
  "behavior_components": ["list", "of", "minecraft:behavior", "components"],
  "reasoning": "explanation of why you chose these features based on real-world or fantasy inspiration"
}}"""

        analysis = None
        reasoning = "Could not analyze mob features"
        
        try:
            analysis = llm_rewrite_spec(
                prompt=thinking_prompt,
                current={"thinking": True},
                provider=provider,
                api_key=api_key
            )
            reasoning = analysis.get("reasoning", "AI analysis complete")
            print(f"[AI-COMPLETE] Analysis: {analysis.get('creature_type', 'unknown')}, parts: {analysis.get('body_parts', [])}")
        except Exception as e:
            print(f"[AI-COMPLETE] Analysis step failed: {e}, using defaults")
            analysis = {
                "creature_type": "generic quadruped creature",
                "body_parts": ["root", "body", "head", "leg_front_left", "leg_front_right", "leg_back_left", "leg_back_right", "tail"],
                "distinctive_features": {
                    "has_trunk": False,
                    "has_tail": True,
                    "tail_type": "thin",
                    "has_wings": False,
                    "has_horns": False,
                    "horn_count": 0,
                    "leg_count": 4,
                    "has_ears": True,
                    "ear_type": "normal",
                    "has_beak": False,
                    "has_shell": False,
                    "extra_features": []
                },
                "proportions": {
                    "head_size": "medium",
                    "body_shape": "medium",
                    "limb_thickness": "medium",
                    "overall_scale": 1.0
                },
                "suggested_stats": {"hp": 20, "damage": 4, "speed": 0.3, "scale": 1.0},
                "behavior_components": [],
                "reasoning": "Using default quadruped structure"
            }
            reasoning = analysis["reasoning"]
        
        # Step 3: Generate mob spec using analysis
        spec_system_prompt = """You are a Minecraft Bedrock mob generator. Generate a valid mob specification JSON.

Required fields:
- identifier: "custom:{short_name}"
- display_name: string
- short_name: lowercase with underscores only
- hp: 1-2048
- damage: 0-128
- speed: 0-2
- collision_box: {width: 0.1-5, height: 0.5-5}
- geometry: "geometry.{short_name}"
- scale: 0.2-5.0
- components: object with Bedrock behavior components

Output ONLY valid JSON."""

        spec_prompt = f"""Create a mob spec for "{display_name}" (short_name: "{safe_name}")

Based on analysis:
- Creature type: {analysis.get('creature_type', 'unknown')}
- Body parts: {analysis.get('body_parts', [])}
- Special features: {analysis.get('special_features', [])}
- Suggested stats: {analysis.get('suggested_stats', {})}
- Recommended behaviors: {analysis.get('behavior_components', [])}

Generate a complete mob specification JSON with appropriate components for this creature type."""

        base_spec = dict(DEFAULTS)
        base_spec["identifier"] = f"custom:{safe_name}"
        base_spec["display_name"] = display_name
        base_spec["short_name"] = safe_name
        base_spec["geometry"] = f"geometry.{safe_name}"
        
        # Apply suggested stats from analysis
        if analysis and analysis.get("suggested_stats"):
            stats = analysis["suggested_stats"]
            base_spec["hp"] = max(1, min(2048, stats.get("hp", 20)))
            base_spec["damage"] = max(0, min(128, stats.get("damage", 4)))
            base_spec["speed"] = max(0, min(2, stats.get("speed", 0.3)))
            base_spec["scale"] = max(0.2, min(5.0, stats.get("scale", 1.0)))
        
        try:
            generated_spec = llm_rewrite_spec(
                prompt=spec_prompt,
                current=base_spec,
                provider=provider,
                api_key=api_key
            )
        except Exception as e:
            print(f"[AI-COMPLETE] Spec generation failed: {e}, using base spec")
            generated_spec = base_spec
        
        # Ensure correct naming
        generated_spec["identifier"] = f"custom:{safe_name}"
        generated_spec["display_name"] = display_name
        generated_spec["short_name"] = safe_name
        generated_spec["geometry"] = f"geometry.{safe_name}"
        
        # Step 4: Generate geometry JSON with detailed body parts
        body_parts = analysis.get("body_parts", ["body", "head"]) if analysis else ["body", "head"]
        creature_type = analysis.get("creature_type", "quadruped") if analysis else "quadruped"
        distinctive_features = analysis.get("distinctive_features", {}) if analysis else {}
        proportions = analysis.get("proportions", {}) if analysis else {}
        
        geometry_prompt = f"""Generate detailed Minecraft Bedrock geometry JSON for a "{display_name}" mob.

=== CREATURE ANALYSIS ===
Type: {creature_type}
Body parts to create: {body_parts}
Scale: {generated_spec.get('scale', 1.0)}

=== DISTINCTIVE FEATURES ===
{json.dumps(distinctive_features, indent=2)}

=== PROPORTIONS ===
{json.dumps(proportions, indent=2)}

=== GEOMETRY REQUIREMENTS ===
The geometry identifier MUST be "geometry.{safe_name}".

Create a bone for EACH body part listed above. Examples:
- For an elephant: body, head, trunk (multiple segments), left_ear, right_ear, 4 legs, tail, tusks
- For a spider: body, head, 8 legs, fangs, abdomen
- For a dragon: body, head, neck, 4 legs, 2 wings (with wing segments), tail (multiple segments), horns

=== BONE HIERARCHY RULES ===
1. Start with a "root" bone at pivot [0, 0, 0]
2. "body" is a child of "root" - this is the main torso
3. "head" is a child of "body" (or "neck" if it has one)
4. Legs are children of "body" - name them: leg_front_left, leg_front_right, leg_back_left, leg_back_right (or leg0, leg1, etc.)
5. Arms/wings attach to "body" near the top
6. Tail attaches to "body" at the back
7. Special features (horns, ears, trunk) attach to their parent part

=== CUBE SIZING GUIDELINES ===
- Body: largest cube, typically 8-16 units wide
- Head: 4-8 units, proportional to body
- Legs: 2-4 units wide, length based on creature height
- Tail: starts thick (2-3 units), tapers to thin (1 unit)
- Trunk/tentacles: multiple segments, each smaller than the last
- Wings: flat and wide, 1-2 units thick but 8-16 units span
- Ears: thin (1-2 units thick), size based on ear_type

=== SIMILAR MOB BONE STRUCTURES FOR REFERENCE ===
{json.dumps(geometry_examples[:3], indent=2)}

Output ONLY valid minecraft:geometry JSON with:
- format_version: "1.12.0"
- texture_width/height: 64 or 128 (larger for complex mobs)
- A bone with cubes for EVERY body part listed
- Proper pivot points so parts rotate naturally
- UV coordinates that don't overlap (spread across the texture)"""

        try:
            generated_geometry = llm_generate_geometry(
                prompt=geometry_prompt,
                current_geometry=None,
                provider=provider,
                api_key=api_key
            )
            
            # Ensure geometry has correct identifier
            if "minecraft:geometry" in generated_geometry:
                geo_list = generated_geometry["minecraft:geometry"]
                if isinstance(geo_list, list) and len(geo_list) > 0:
                    if "description" not in geo_list[0]:
                        geo_list[0]["description"] = {}
                    geo_list[0]["description"]["identifier"] = f"geometry.{safe_name}"
            
            print(f"[AI-COMPLETE] Geometry generated successfully")
        except Exception as e:
            print(f"[AI-COMPLETE] Geometry generation failed: {e}, using fallback")
            # Fallback to a proper quadruped geometry with 4 legs and tail
            generated_geometry = {
                "format_version": "1.12.0",
                "minecraft:geometry": [{
                    "description": {
                        "identifier": f"geometry.{safe_name}",
                        "texture_width": 64,
                        "texture_height": 64,
                        "visible_bounds_width": 3,
                        "visible_bounds_height": 2.5,
                        "visible_bounds_offset": [0, 1, 0]
                    },
                    "bones": [
                        {"name": "root", "pivot": [0, 0, 0]},
                        {"name": "body", "parent": "root", "pivot": [0, 13, 0], 
                         "cubes": [{"origin": [-5, 10, -7], "size": [10, 8, 14], "uv": [0, 0]}]},
                        {"name": "head", "parent": "body", "pivot": [0, 18, -7],
                         "cubes": [{"origin": [-4, 14, -13], "size": [8, 8, 8], "uv": [0, 22]}]},
                        {"name": "leg_front_left", "parent": "body", "pivot": [-3, 10, -5],
                         "cubes": [{"origin": [-5, 0, -6], "size": [4, 10, 4], "uv": [40, 0]}]},
                        {"name": "leg_front_right", "parent": "body", "pivot": [3, 10, -5],
                         "cubes": [{"origin": [1, 0, -6], "size": [4, 10, 4], "uv": [40, 14]}]},
                        {"name": "leg_back_left", "parent": "body", "pivot": [-3, 10, 5],
                         "cubes": [{"origin": [-5, 0, 4], "size": [4, 10, 4], "uv": [0, 38]}]},
                        {"name": "leg_back_right", "parent": "body", "pivot": [3, 10, 5],
                         "cubes": [{"origin": [1, 0, 4], "size": [4, 10, 4], "uv": [16, 38]}]},
                        {"name": "tail", "parent": "body", "pivot": [0, 14, 7],
                         "cubes": [{"origin": [-1, 12, 7], "size": [2, 2, 6], "uv": [32, 38]}]}
                    ]
                }]
            }
        
        # Store geometry in spec for convenience
        generated_spec["geometry_json"] = generated_geometry
        
        return {
            "mob": generated_spec,
            "geometry": generated_geometry,
            "reasoning": reasoning,
            "similar_mobs": similar_names,
            "analysis": analysis,
            "source": "ai_generated_complete"
        }
        
    except Exception as e:
        print(f"[ERROR] Complete AI mob generation failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate mob: {str(e)}")


async def fetch_mob_geometry(mob_name: str):
    """Fetch mob geometry JSON from Mojang's bedrock-samples repository.
    
    Searches for all .geo.json files containing the mob_name (with version numbers/descriptors),
    and fetches the most recently updated one. Results are cached locally to avoid
    burning through the GitHub API rate limit (60 req/hr unauthenticated).
    Old-format geometry files are automatically normalized to the modern
    minecraft:geometry array format.
    """
    if not mob_name:
        raise HTTPException(status_code=400, detail="mob_name is required")
    
    # Sanitize mob_name to prevent directory traversal
    safe_name = mob_name.strip().replace("..", "").replace("/", "")
    safe_name_lower = safe_name.lower()

    # Check in-memory cache first
    if safe_name_lower in _geometry_cache:
        print(f"[GEOMETRY] Cache hit for '{mob_name}'")
        return _geometry_cache[safe_name_lower]
    
    # Use raw.githubusercontent.com directly ΓÇö NO API rate limit!
    # Try common filename patterns for Bedrock geometry files
    base_url = "https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity"
    candidates = [
        f"{safe_name_lower}.geo.json",
        f"{safe_name_lower}_v2.geo.json",
        f"{safe_name_lower}_v1.geo.json",
    ]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for filename in candidates:
                raw_url = f"{base_url}/{filename}"
                response = await client.get(raw_url)
                if response.status_code == 200:
                    try:
                        geometry_data = response.json()
                    except (json.JSONDecodeError, ValueError):
                        continue

                    geometry_data = _normalize_geometry(geometry_data)
                    result = {
                        "geometry": geometry_data,
                        "url": raw_url,
                        "filename": filename,
                        "matches_found": 1
                    }
                    _geometry_cache[safe_name_lower] = result
                    print(f"[GEOMETRY] Fetched and cached '{filename}' for '{mob_name}'")
                    return result

            # None of the direct URLs worked ΓÇö fall back to GitHub API for directory listing
            # (only costs 1 API call, and the listing is cached for future lookups)
            global _github_file_list_cache
            if _github_file_list_cache is not None:
                files = _github_file_list_cache
            else:
                api_url = "https://api.github.com/repos/Mojang/bedrock-samples/contents/resource_pack/models/entity"
                api_response = await client.get(api_url)
                if api_response.status_code != 200:
                    raise HTTPException(
                        status_code=api_response.status_code,
                        detail=f"Failed to query GitHub API (status {api_response.status_code})"
                    )
                files = api_response.json()
                if isinstance(files, list):
                    _github_file_list_cache = files

            matching = [
                f.get("name", "") for f in files
                if safe_name_lower in f.get("name", "").lower() and f.get("name", "").endswith(".geo.json")
            ]
            if not matching:
                raise HTTPException(status_code=404, detail=f"No geometry files found for '{mob_name}'")

            matching.sort(key=len)
            chosen = matching[0]
            raw_url = f"{base_url}/{chosen}"
            response = await client.get(raw_url)
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Failed to fetch geometry file")

            geometry_data = _normalize_geometry(response.json())
            result = {
                "geometry": geometry_data,
                "url": raw_url,
                "filename": chosen,
                "matches_found": len(matching)
            }
            _geometry_cache[safe_name_lower] = result
            print(f"[GEOMETRY] Fetched and cached '{chosen}' for '{mob_name}' (via API fallback)")
            return result

    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch geometry from GitHub: {str(e)}"
        )



def get_mob(name: str):
    """Retrieve a specific mob spec."""
    from backend.schemas.schemas_loader import SPEC_SCHEMA
    try:
        spec = read_mob_spec(name)
        return {"spec": spec, "schema": SPEC_SCHEMA}
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def get_mob_texture(name: str):
    """Get a mob's texture image."""
    from backend.core.builders import make_png_rgba
    from backend.core.core import COLOR_WORDS, SPECS_DIR
    path = SPECS_DIR / f"{name}.png"
    if path.exists():
        return FileResponse(path, media_type="image/png")
    # Fallback to a generated one based on the spec
    spec = read_mob_spec(name)
    col = spec.get("color_rgb", COLOR_WORDS.get("red"))
    png = make_png_rgba(64, 64, *col, 255)
    return Response(content=png, media_type="image/png")


async def save_mob_texture(name: str, file: UploadFile = File(...)):
    """Save a custom texture for a mob."""
    from backend.core.core import SPECS_DIR
    path = SPECS_DIR / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"status": "ok"}


async def save_mob(name: str, payload: dict = Body(...)):
    """Create or update a mob spec."""
    try:
        spec = write_mob_spec(name, payload)
        return {"spec": spec}
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def delete_mob(name: str):
    """Delete a mob spec."""
    delete_mob_spec(name)
    return {"status": "ok"}


def duplicate_mob(name: str):
    """Create a copy of a mob spec."""
    spec = read_mob_spec(name)
    new_name = f"{name}_copy"
    # Ensure uniqueness
    existing = list_mob_names()
    while new_name in existing:
        new_name = f"{new_name}_copy"
    spec["short_name"] = new_name
    spec["display_name"] = f"{spec['display_name']} Copy"
    spec["identifier"] = f"{spec['identifier']}_copy"
    new_spec = write_mob_spec(new_name, spec)
    return {"name": new_name, "spec": new_spec}


def get_spec():
    """Get the current/active spec."""
    from backend.schemas.schemas_loader import SPEC_SCHEMA
    return {
        "spec": read_current_spec(),
        "schema": SPEC_SCHEMA
    }


def get_default_spec():
    """Return a clean blank spec using the built-in DEFAULTS."""
    from backend.core.core import DEFAULTS
    import copy
    return copy.deepcopy(DEFAULTS)


async def replace_spec(payload: dict = Body(...)):
    """Replace the current spec."""
    try:
        spec = write_current_spec(payload)
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"spec": spec}


async def patch_spec(operations: list[dict] = Body(...)):
    """Apply JSON Patch operations to the current spec."""
    current = read_current_spec()
    try:
        patched = apply_spec_patch(current, operations)
        spec = write_current_spec(patched)
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"spec": spec}


def llm_spec_editor(payload: dict = Body(...)):
    """Use LLM to rewrite a spec."""
    data = payload or {}
    prompt = data.get("prompt") or data.get("instruction") or ""
    if not prompt or not str(prompt).strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    provider = data.get("provider")
    api_key = data.get("api_key")
    category = data.get("category", "entity_logic_ai")
    use_plan = bool(data.get("use_plan", False))
    current = data.get("current_spec") or data.get("spec")
    if not current:
        current = read_current_spec()

    print(f"[LLM] provider={provider} category={category} prompt_len={len(str(prompt).strip())} use_plan={use_plan}")

    # if server running in local dev mode prefer mock to avoid external calls
    if LOCAL_LLM_DEV and not provider:
        return llm_spec_mock(payload)

    try:
        updated = llm_rewrite_spec(prompt, current, provider, api_key, category=category, use_plan=use_plan)
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        print(f"[LLM] error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    # Extract internal metadata before saving (don't persist it)
    mcp_meta = updated.pop("_mcp_meta", None) if updated else None
    texture_b64 = updated.pop("_texture_b64", "") if updated else ""
    orchestrator_meta = updated.pop("_orchestrator_meta", None) if updated else None
    pipeline_meta = updated.pop("_pipeline_meta", None) if updated else None
    
    # Auto-generate animations for the spec
    mob_name = updated.get("short_name", "custom_mob") if updated else "custom_mob"
    geometry_json = updated.get("geometry_json", {}) if updated else {}
    
    # Normalize geometry to modern format if needed (converts geometry.X keys to minecraft:geometry array)
    if geometry_json and isinstance(geometry_json, dict):
        geometry_json = _normalize_geometry(geometry_json)
        updated["geometry_json"] = geometry_json  # Update with normalized version
        print(f"[LLM-SPEC-EDITOR] Normalized geometry, keys now: {list(geometry_json.keys())}")
    
    # Check if geometry has actual content (minecraft:geometry key exists)
    has_geometry = geometry_json and isinstance(geometry_json, dict) and "minecraft:geometry" in geometry_json
    
    if has_geometry:
        print(f"[LLM-SPEC-EDITOR] Auto-generating animations for {mob_name}")
        from backend.llm.animation_generation import llm_generate_animation, ensure_animations_and_controller
        from backend.llm.animation_controllers_generation import llm_generate_animation_controller
        
        try:
            anim_result = llm_generate_animation(
                prompt=f"Create animations for: {prompt}",
                geometry_json=geometry_json,
                mob_name=mob_name,
                provider=provider,
                api_key=api_key,
            )
            animation_json = anim_result.get("animation")
            animation_controller_json = None
            
            if animation_json:
                # Auto-generate animation controller
                print(f"[LLM-SPEC-EDITOR] Auto-generating animation controller for {mob_name}")
                try:
                    ac_result = llm_generate_animation_controller(
                        animation_json=animation_json,
                        mob_name=mob_name,
                        provider=provider,
                        api_key=api_key,
                    )
                    animation_controller_json = ac_result.get("animation_controller")
                except Exception as ac_err:
                    print(f"[LLM-SPEC-EDITOR] Warning: failed to generate controller: {ac_err}")
            
            # Validate both and auto-generate any missing ones
            animation_json, animation_controller_json, val_messages = ensure_animations_and_controller(
                animation_json=animation_json,
                animation_controller_json=animation_controller_json,
                mob_name=mob_name,
                geometry_json=geometry_json,
                provider=provider,
                api_key=api_key,
            )
            
            for msg in val_messages:
                print(msg)
            
            if animation_json:
                updated["animation_json"] = animation_json
                print(f"[LLM-SPEC-EDITOR] Generated animations with {anim_result.get('bone_count', 0)} bones")
            
            if animation_controller_json:
                updated["animation_controller_json"] = animation_controller_json
                # Explicitly set the animation_controller ID so builders.py uses it
                updated["animation_controller"] = f"controller.animation.{mob_name}"
                print(f"[LLM-SPEC-EDITOR] Generated animation controller: {updated['animation_controller']}")
            
            if not animation_json and not animation_controller_json:
                print(f"[LLM-SPEC-EDITOR] Warning: animation generation returned None")
        except Exception as anim_err:
            print(f"[LLM-SPEC-EDITOR] Warning: animation generation failed: {anim_err}")
    
    # Log animation fields
    print(f"[LLM-SPEC-EDITOR] Updated spec keys: {list(updated.keys())}")
    print(f"[LLM-SPEC-EDITOR] animation_json present: {bool(updated.get('animation_json'))}")
    print(f"[LLM-SPEC-EDITOR] animation_controller_json present: {bool(updated.get('animation_controller_json'))}")
    print(f"[LLM-SPEC-EDITOR] animation_controller present: {bool(updated.get('animation_controller'))}")
    if updated.get('animation_json'):
        print(f"[LLM-SPEC-EDITOR] animation_json type: {type(updated['animation_json'])}")
        print(f"[LLM-SPEC-EDITOR] animation_json keys: {list(updated['animation_json'].keys()) if isinstance(updated['animation_json'], dict) else 'N/A'}")
    if updated.get('animation_controller_json'):
        print(f"[LLM-SPEC-EDITOR] animation_controller_json type: {type(updated['animation_controller_json'])}")
        print(f"[LLM-SPEC-EDITOR] animation_controller_json keys: {list(updated['animation_controller_json'].keys()) if isinstance(updated['animation_controller_json'], dict) else 'N/A'}")

    # --- Validation: Retry if both animation files failed to generate ---
    has_animation_json = bool(updated.get('animation_json'))
    has_animation_controller_json = bool(updated.get('animation_controller_json'))
    
    if not has_animation_json and not has_animation_controller_json:
        # Both missing ΓÇö check if we have geometry to work from
        geometry_json = updated.get("geometry_json", {})
        has_geometry = geometry_json and isinstance(geometry_json, dict) and "minecraft:geometry" in geometry_json
        
        if has_geometry:
            print(f"[LLM-SPEC-EDITOR] VALIDATION: Both animation files missing, retrying generation...")
            mob_name = updated.get("short_name", "custom_mob")
            from backend.llm.animation_generation import llm_generate_animation, ensure_animations_and_controller
            from backend.llm.animation_controllers_generation import llm_generate_animation_controller
            
            try:
                # Retry animation generation
                anim_result = llm_generate_animation(
                    prompt=f"Create animations for: {prompt}",
                    geometry_json=geometry_json,
                    mob_name=mob_name,
                    provider=provider,
                    api_key=api_key,
                )
                animation_json = anim_result.get("animation") if anim_result else None
                animation_controller_json = None
                
                if animation_json:
                    # Generate animation controller
                    print(f"[LLM-SPEC-EDITOR] RETRY: Auto-generating animation controller")
                    try:
                        ac_result = llm_generate_animation_controller(
                            animation_json=animation_json,
                            mob_name=mob_name,
                            provider=provider,
                            api_key=api_key,
                        )
                        animation_controller_json = ac_result.get("animation_controller") if ac_result else None
                    except Exception as ac_err:
                        print(f"[LLM-SPEC-EDITOR] RETRY: Warning: failed to generate controller: {ac_err}")
                
                # Validate and auto-generate any missing pieces
                animation_json, animation_controller_json, val_messages = ensure_animations_and_controller(
                    animation_json=animation_json,
                    animation_controller_json=animation_controller_json,
                    mob_name=mob_name,
                    geometry_json=geometry_json,
                    provider=provider,
                    api_key=api_key,
                )
                
                for msg in val_messages:
                    print(f"[LLM-SPEC-EDITOR] RETRY: {msg}")
                
                # Update spec with regenerated files
                if animation_json:
                    updated["animation_json"] = animation_json
                    print(f"[LLM-SPEC-EDITOR] RETRY: Animation regenerated and added to spec")
                
                if animation_controller_json:
                    updated["animation_controller_json"] = animation_controller_json
                    # Explicitly set the animation_controller ID
                    updated["animation_controller"] = f"controller.animation.{mob_name}"
                    print(f"[LLM-SPEC-EDITOR] RETRY: Animation controller regenerated: {updated['animation_controller']}")
                
                if not animation_json and not animation_controller_json:
                    print(f"[LLM-SPEC-EDITOR] RETRY: Warning: retry also failed to generate animations")
            except Exception as retry_err:
                err_msg = str(retry_err).replace("{", "{{").replace("}", "}}")
                print(f"[LLM-SPEC-EDITOR] RETRY: Warning: animation retry failed: {err_msg}")
        else:
            print(f"[LLM-SPEC-EDITOR] VALIDATION: Both animation files missing but no geometry to generate from")

    if data.get("save"):
        try:
            name = updated.get("short_name") or "current"
            saved = write_mob_spec(name, updated)
            result = {"spec": saved, "saved": True}
            if mcp_meta:
                result["mcp"] = mcp_meta
            if texture_b64:
                result["texture_b64"] = texture_b64
            if orchestrator_meta:
                result["orchestrator"] = orchestrator_meta
            if pipeline_meta:
                result["pipeline"] = pipeline_meta
            return result
        except SpecValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    result = {"spec": updated, "saved": False}
    if mcp_meta:
        result["mcp"] = mcp_meta
    if texture_b64:
        result["texture_b64"] = texture_b64
    if orchestrator_meta:
        result["orchestrator"] = orchestrator_meta
    if pipeline_meta:
        result["pipeline"] = pipeline_meta
    return result


def llm_geometry_generate(payload: dict = Body(...)):
    """Use LLM to generate or modify Bedrock geometry JSON.
    
    Also auto-generates animations and animation controllers.
    Returns geometry + animations + animation_controller all together.
    """
    from backend.llm.animation_generation import llm_generate_animation
    from backend.llm.animation_controllers_generation import llm_generate_animation_controller
    
    data = payload or {}
    prompt = data.get("prompt") or ""
    if not prompt or not str(prompt).strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    provider = data.get("provider")
    api_key = data.get("api_key")
    current_geometry = data.get("current_geometry")
    mob_name = data.get("mob_name", "custom_mob")

    print(f"[LLM-GEOMETRY] provider={provider} prompt_len={len(str(prompt).strip())} mob={mob_name}")

    try:
        geometry = llm_generate_geometry(prompt, current_geometry, provider, api_key, mob_name=mob_name)
    except RuntimeError as exc:
        print(f"[LLM-GEOMETRY] error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        print(f"[LLM-GEOMETRY] unexpected error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    if not geometry:
        raise HTTPException(status_code=500, detail="Geometry generation returned empty result")

    texture_b64 = geometry.pop("_texture_b64", "") if geometry else ""
    mcp_design = geometry.pop("_mcp_design", False) if geometry else False

    result = {"geometry": geometry}
    if texture_b64:
        result["texture_b64"] = texture_b64
        result["mcp_texture"] = True
    
    # Auto-generate animations for the geometry
    print(f"[LLM-ANIMATION] Auto-generating animations for {mob_name}")
    try:
        anim_result = llm_generate_animation(
            prompt=f"Create animations for: {prompt}",
            geometry_json=geometry,
            mob_name=mob_name,
            provider=provider,
            api_key=api_key,
        )
        animation = anim_result.get("animation")
        if animation:
            result["animation"] = animation
            result["animation_mcp_verified"] = anim_result.get("mcp_verified", False)
            result["animation_bone_count"] = anim_result.get("bone_count", 0)
            print(f"[LLM-ANIMATION] Generated animations with {result['animation_bone_count']} bones")
            
            # Auto-generate animation controller
            print(f"[LLM-ANIMATION-CONTROLLER] Auto-generating animation controller for {mob_name}")
            try:
                ac_result = llm_generate_animation_controller(
                    animation_json=animation,
                    mob_name=mob_name,
                    provider=provider,
                    api_key=api_key,
                )
                animation_controller = ac_result.get("animation_controller")
                if animation_controller:
                    result["animation_controller"] = animation_controller
                    result["animation_controller_mcp_verified"] = ac_result.get("mcp_verified", False)
                    result["animation_controller_id"] = f"controller.animation.{mob_name}"
                    print(f"[LLM-ANIMATION-CONTROLLER] Generated animation controller")
            except Exception as ac_err:
                print(f"[LLM-ANIMATION-CONTROLLER] Warning: failed to generate controller: {ac_err}")
        else:
            print(f"[LLM-ANIMATION] Warning: animation generation returned None")
    except Exception as anim_err:
        print(f"[LLM-ANIMATION] Warning: animation generation failed: {anim_err}")
    
    return result


def llm_animation_generate(payload: dict = Body(...)):
    """Use LLM to generate Bedrock animation.json."""
    from backend.llm.animation_generation import llm_generate_animation
    
    data = payload or {}
    prompt = data.get("prompt") or ""
    if not prompt or not str(prompt).strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    provider = data.get("provider")
    api_key = data.get("api_key")
    geometry_json = data.get("geometry_json")
    mob_name = data.get("mob_name", "custom_mob")

    print(f"[LLM-ANIMATION] provider={provider} prompt_len={len(str(prompt).strip())} mob={mob_name}")

    try:
        result = llm_generate_animation(
            prompt=prompt,
            geometry_json=geometry_json or {},
            mob_name=mob_name,
            provider=provider,
            api_key=api_key,
        )
    except Exception as exc:
        print(f"[LLM-ANIMATION] error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    animation = result.pop("animation", None)
    if not animation:
        raise HTTPException(status_code=500, detail=result.get("error", "Animation generation failed"))

    return {
        "animation": animation,
        "mcp_verified": result.get("mcp_verified", False),
        "bone_count": result.get("bone_count", 0),
        "provider": result.get("provider"),
        "elapsed_ms": result.get("elapsed_ms", 0),
    }


def llm_animation_controller_generate(payload: dict = Body(...)):
    """Use LLM to generate Bedrock animation_controllers.json."""
    from backend.llm.animation_controllers_generation import llm_generate_animation_controller
    
    data = payload or {}
    animation_json = data.get("animation_json")
    if not animation_json:
        raise HTTPException(status_code=400, detail="animation_json is required")

    provider = data.get("provider")
    api_key = data.get("api_key")
    mob_name = data.get("mob_name", "custom_mob")

    print(f"[LLM-ANIMATION-CONTROLLER] provider={provider} mob={mob_name}")

    try:
        result = llm_generate_animation_controller(
            animation_json=animation_json,
            mob_name=mob_name,
            provider=provider,
            api_key=api_key,
        )
    except Exception as exc:
        print(f"[LLM-ANIMATION-CONTROLLER] error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    controller = result.pop("animation_controller", None)
    if not controller:
        raise HTTPException(status_code=500, detail=result.get("error", "Animation controller generation failed"))

    return {
        "animation_controller": controller,
        "mcp_verified": result.get("mcp_verified", False),
        "provider": result.get("provider"),
        "elapsed_ms": result.get("elapsed_ms", 0),
    }

def llm_spec_mock(payload: dict = Body(...)):
    data = payload or {}
    prompt = (data.get("prompt") or data.get("instruction") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    current = data.get("current_spec") or data.get("spec")
    if not current:
        current = read_current_spec()
    spec = dict(current)
    try:
        if "increase hp by" in prompt.lower():
            import re
            m = re.search(r"increase hp by\s*(\d+)", prompt.lower())
            if m:
                delta = int(m.group(1))
            else:
                delta = 1
            spec["hp"] = int(spec.get("hp", 1)) + delta
        if "double damage" in prompt.lower() or "double the damage" in prompt.lower():
            spec["damage"] = float(spec.get("damage", 1)) * 2
        ti = list(spec.get("texture_instructions") or [])
        ti.append(f"[mock applied] {prompt}")
        spec["texture_instructions"] = ti
        validated = validate_spec(spec)
        return {"spec": validated}
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def validate_spec_endpoint(payload: dict = Body(...)):
    """Validate a spec without saving it."""
    from backend.schemas.spec_utils import validate_spec
    try:
        validated = validate_spec(payload)
        return {"valid": True, "spec": validated}
    except SpecValidationError as exc:
        # Return structured error with path information
        error_msg = str(exc)
        # Try to extract field name from error message
        field = None
        for key in ["identifier", "short_name", "display_name", "hp", "damage", "speed", 
                    "collision_box", "egg_base", "egg_overlay", "scale", "engine_min"]:
            if key in error_msg.lower():
                field = key
                break
        return {"valid": False, "error": error_msg, "field": field}
    
    # Use client-provided spec if available, otherwise fallback to server's 'current'
    current = data.get("current_spec")
    if not current:
        current = read_current_spec()
        
    try:
        spec = validate_spec(updated)
        print("[LLM] update complete; short_name=", spec.get("short_name"))
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        print(f"[LLM] error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    return {"spec": spec}


def index():
    """Serve the main HTML page."""
    from backend.core.core import FRONTEND_DIR
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text(encoding="utf-8"))

def styles_css():
    """Serve the main stylesheet."""
    from backend.core.core import FRONTEND_DIR
    path = FRONTEND_DIR / "styles.css"
    if not path.exists():
        # Fallback: minimal inline CSS if file missing
        return PlainTextResponse("/* styles.css not found */", media_type="text/css")
    return FileResponse(path, media_type="text/css")

def serve_js(filename: str):
    """Serve JavaScript files from frontend/js directory."""
    from backend.core.core import FRONTEND_DIR
    js_root = (FRONTEND_DIR / "js").resolve()
    # Resolve the requested path and ensure it stays within js_root
    try:
        path = (js_root / filename).resolve()
        path.relative_to(js_root)  # raises ValueError if outside js_root
    except (ValueError, Exception):
        raise HTTPException(status_code=404, detail=f"JS file not found: {filename}")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"JS file not found: {filename}")
    return FileResponse(path, media_type="application/javascript")


def healthz():
    """Health check endpoint."""
    return PlainTextResponse("ok")


def get_llm_categories():
    """Return available LLM content categories for the frontend dropdown."""
    return {"categories": [
        {"id": cat, "label": CATEGORY_LABELS.get(cat, cat)}
        for cat in CATEGORIES
    ]}


def build_form(resource: Optional[UploadFile] = File(None),
               behavior: Optional[UploadFile] = File(None),
               build_mode: str = Form("bundle")):
    """Build endpoint for form submissions."""
    tmp = Path(tempfile.mkdtemp(prefix="http_"))
    try:
        res_path = _save_upload(tmp, resource)
        beh_path = _save_upload(tmp, behavior)
        kind, artifact, _ = _build_and_bundle(res_path, beh_path, build_mode=build_mode)
        media_type = "application/zip" if kind != "mcworld" else "application/octet-stream"
        return FileResponse(artifact, filename=artifact.name, media_type=media_type)
    finally:
        pass


async def api_build(resource: Optional[UploadFile] = File(None),
                    behavior: Optional[UploadFile] = File(None),
                    build_mode: str = Form("bundle"),
                    target_mobs: Optional[str] = Form(None),
                    specs_json: Optional[str] = Form(None),
                    textures_json: Optional[str] = Form(None)):
    """Build endpoint for JSON API."""
    import json
    import base64
    from backend.schemas.spec_utils import validate_spec
    from backend.core.core import SPECS_DIR
    tmp = Path(tempfile.mkdtemp(prefix="http_"))
    try:
        specs_override = None
        # Prefer specs_json from client (localStorage) over server-side target_mobs
        if specs_json:
            try:
                raw_specs = json.loads(specs_json)
                specs_override = [validate_spec(s) for s in raw_specs]
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid specs_json: {e}")
        elif target_mobs:
            # Fallback: target_mobs is a comma-separated list of mob names from server
            names = [n.strip() for n in target_mobs.split(",") if n.strip()]
            if names:
                specs_override = [read_mob_spec(n) for n in names]

        # Save textures from localStorage to temp directory for build process
        textures_dir = tmp / "textures"
        textures_dir.mkdir(parents=True, exist_ok=True)
        if textures_json:
            try:
                textures = json.loads(textures_json)
                for mob_name, base64_data in textures.items():
                    # base64_data is like "data:image/png;base64,iVBORw0..."
                    if "," in base64_data:
                        base64_data = base64_data.split(",", 1)[1]
                    png_bytes = base64.b64decode(base64_data)
                    tex_path = textures_dir / f"{mob_name}.png"
                    tex_path.write_bytes(png_bytes)
            except Exception as e:
                print(f"[BUILD] Warning: Failed to process textures: {e}")

        res_path = _save_upload(tmp, resource)
        beh_path = _save_upload(tmp, behavior)
        kind, artifact, artifacts = _build_and_bundle(res_path, beh_path, specs_override=specs_override, build_mode=build_mode, textures_dir=textures_dir)

        downloads = {
            "bundle": f"/download/{Path(artifacts['bundle_zip']).name}",
            "mcworld": f"/download/{Path(artifacts['mcworld']).name}" if artifacts.get('mcworld') else "",
            "mcaddon": f"/download/{Path(artifacts['mcaddon']).name}",
            "res_mcpack": f"/download/{Path(artifacts['res_mcpack']).name}",
            "beh_mcpack": f"/download/{Path(artifacts['beh_mcpack']).name}",
        }
        return JSONResponse({
            "artifact": f"/download/{artifact.name}",
            "kind": kind,
            "downloads": downloads,
            "note": "Fetch artifacts at /download/<name>; choose mcworld to import directly into Minecraft."
        })
    finally:
        pass


def download(name: str):
    """Download a previously built artifact."""
    root = Path(tempfile.gettempdir())
    print(f"[DEBUG] Searching for {name} in {root}")
    # Sort by mtime to find the newest one if multiple exist
    candidates = []
    for p in root.rglob(name):
        if p.is_file():
            candidates.append(p)

    if candidates:
        newest = max(candidates, key=lambda x: x.stat().st_mtime)
        print(f"[DEBUG] Found newest: {newest}")
        return FileResponse(newest, filename=newest.name, media_type="application/zip")

    print(f"[DEBUG] {name} not found")
    return PlainTextResponse("Not found", status_code=404)


# ---------------------------------------------------------------------------
# Server Test Session (One-Click Play)
# ---------------------------------------------------------------------------

# Add scripts/ to sys.path for launch_server_session imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts"))

# Global state for the running server session
_server_session_lock = threading.Lock()
_server_session = {
    "running": False,
    "thread": None,
    "proc": None,
    "status": "idle",       # idle | starting | ready | error | stopped
    "logs": [],
    "error": None,
}


def _run_server_session_thread(pack_dir: str, resource_pack_dir: str | None, category: str):
    """Background thread that runs the full BDS lifecycle."""
    import sys
    from pathlib import Path
    
    # Add scripts directory to path for launch_server_session import
    scripts_dir = Path(__file__).parent.parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    
    from launch_server_session import (  # type: ignore
        setup_server, _read_server_output, _launch_client,
        _kill_minecraft_client,
        _detect_identifiers, _build_command, BDS_EXE, BDS_DIR,
    )
    import subprocess
    import time

    session = _server_session
    session["logs"] = []
    session["error"] = None

    try:
        # Setup
        session["status"] = "starting"
        session["logs"].append("[api] Setting up server...")
        setup_server(pack_dir, resource_pack_path=resource_pack_dir)
        session["logs"].append("[api] Server configured.")

        # Detect all identifiers
        pack_path = Path(pack_dir).resolve()
        identifiers = _detect_identifiers(pack_path, category)
        commands: list[str] = []
        if identifiers:
            for ident in identifiers:
                cmd = _build_command(ident, category)
                commands.append(cmd)
                session["logs"].append(f"[api] Will run: /{cmd}")
        else:
            session["logs"].append("[api] No identifiers detected, skipping auto-give.")

        # Launch BDS
        event_server_ready = threading.Event()
        event_player_spawned = threading.Event()
        event_fatal_error = threading.Event()
        event_no_targets = threading.Event()

        proc = subprocess.Popen(
            [str(BDS_EXE)],
            cwd=str(BDS_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        session["proc"] = proc

        reader = threading.Thread(
            target=_read_server_output,
            args=(proc, event_server_ready, event_player_spawned,
                  event_fatal_error, event_no_targets, session["logs"]),
            daemon=True,
        )
        reader.start()

        # Wait for server ready (bail on fatal error)
        while not event_server_ready.is_set():
            if event_fatal_error.wait(timeout=1):
                session["status"] = "error"
                session["error"] = "BDS fatal: vanilla resource pack missing. Re-extract BDS zip."
                proc.kill()
                return
            if event_server_ready.wait(timeout=1):
                break
            if proc.poll() is not None:
                session["status"] = "error"
                session["error"] = "BDS exited unexpectedly."
                return

        session["status"] = "ready"
        session["logs"].append("[api] Server is READY on port 19132")

        # Launch client (kill stale instances first)
        _kill_minecraft_client()
        time.sleep(3)
        _launch_client()
        session["logs"].append("[api] Minecraft client launched.")

        # Wait for player spawn + magic
        if commands:
            session["logs"].append("[api] Waiting for player to spawn...")
            if event_player_spawned.wait(timeout=120):
                time.sleep(2)
                for cmd in commands:
                    event_no_targets.clear()
                    proc.stdin.write(cmd + "\n")
                    proc.stdin.flush()
                    session["logs"].append(f"[api] Sent: /{cmd}")
                    # Retry once if no targets
                    if event_no_targets.wait(timeout=3):
                        time.sleep(3)
                        event_no_targets.clear()
                        proc.stdin.write(cmd + "\n")
                        proc.stdin.flush()
                        session["logs"].append(f"[api] Retry sent: /{cmd}")
                    time.sleep(1)  # small gap between multiple summons
                session["logs"].append(f"[api] Magic complete! ({len(commands)} command(s))")

        # Keep alive until stopped externally
        proc.wait()

    except Exception as exc:
        session["status"] = "error"
        session["error"] = str(exc)
    finally:
        session["running"] = False
        if session["status"] not in ("error",):
            session["status"] = "stopped"
        if session.get("proc") and session["proc"].poll() is None:
            session["proc"].kill()


async def launch_test(payload: dict = Body(...)):
    """POST /api/launch-test \u2014 Build the addon and start a BDS test session."""
    with _server_session_lock:
        if _server_session["running"]:
            raise HTTPException(status_code=409, detail="A test session is already running. Stop it first.")

    # Get specs from payload
    specs_json = payload.get("specs", [])
    category = payload.get("category", "entity_logic_ai")

    if not specs_json:
        raise HTTPException(status_code=400, detail="No specs provided.")

    try:
        specs = [validate_spec(s) for s in specs_json]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid spec: {exc}")

    # Save textures from payload to temp directory for build process
    import base64
    textures_dir = None
    textures_json = payload.get("textures", {})
    if textures_json and isinstance(textures_json, dict):
        tex_tmp = Path(tempfile.mkdtemp(prefix="test_tex_"))
        textures_dir = tex_tmp
        for mob_name, base64_data in textures_json.items():
            try:
                if isinstance(base64_data, str) and base64_data:
                    if "," in base64_data:
                        base64_data = base64_data.split(",", 1)[1]
                    png_bytes = base64.b64decode(base64_data)
                    tex_path = textures_dir / f"{mob_name}.png"
                    tex_path.write_bytes(png_bytes)
            except Exception as e:
                print(f"[TEST] Warning: Failed to process texture for {mob_name}: {e}")

    # Build addon to get the behavior pack folder
    out_dir = Path(tempfile.mkdtemp(prefix="test_session_"))
    try:
        artifacts = build_addon(specs, out_dir, None, None, textures_dir=textures_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Build failed: {exc}")

    # Find the behavior pack folder
    beh_mcpack = artifacts.get("beh_mcpack")
    if not beh_mcpack or not Path(beh_mcpack).exists():
        raise HTTPException(status_code=500, detail="Build produced no behavior pack.")

    # Extract the mcpack (it's a zip) to a folder for BDS
    import zipfile
    pack_dir = out_dir / "bds_bp"
    pack_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(beh_mcpack, "r") as zf:
        zf.extractall(pack_dir)

    # Extract the resource pack too (textures, models, etc.)
    res_mcpack = artifacts.get("res_mcpack")
    rp_dir = None
    if res_mcpack and Path(res_mcpack).exists():
        rp_dir = out_dir / "bds_rp"
        rp_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(res_mcpack, "r") as zf:
            zf.extractall(rp_dir)

    # Start the server session in a background thread
    with _server_session_lock:
        _server_session["running"] = True
        _server_session["status"] = "starting"
        _server_session["logs"] = []
        _server_session["error"] = None
        _server_session["proc"] = None

        t = threading.Thread(
            target=_run_server_session_thread,
            args=(str(pack_dir), str(rp_dir) if rp_dir else None, category),
            daemon=True,
        )
        _server_session["thread"] = t
        t.start()

    return {"status": "starting", "message": "Test session is launching..."}


def launch_test_status():
    """GET /api/launch-test/status \u2014 Poll the current test session state."""
    return {
        "running": _server_session["running"],
        "status": _server_session["status"],
        "error": _server_session["error"],
        "log_count": len(_server_session["logs"]),
        "recent_logs": _server_session["logs"][-20:],
    }


async def launch_test_stop():
    """POST /api/launch-test/stop \u2014 Stop the running test session."""
    proc = _server_session.get("proc")
    if proc and proc.poll() is None:
        try:
            proc.stdin.write("stop\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        _server_session["status"] = "stopped"
        _server_session["running"] = False
        return {"status": "stopped", "message": "Server stopped."}
    else:
        _server_session["status"] = "idle"
        _server_session["running"] = False
        return {"status": "idle", "message": "No server was running."}

# =========================
# ====== PUBLISH ROUTES ===
# =========================

async def publish_mob_to_database(payload: dict = Body(...)):
    """
    POST /api/publish ΓÇö Publish a user-created mob to the database.
    
    Request body:
    {
        "mob_name": "fire_dragon",
        "username": "player123",
        "prompts": ["make it breathe fire", "give it wings"],
        "geometry": { ... geometry JSON ... },
        "api_key": "sk-..." (optional, falls back to env var)
    }
    
    Returns:
    {
        "success": true,
        "mob_name": "fire_dragon_player123",
        "description": "A flying creature that breathes fire.",
        "keywords": ["hostile", "flying", "fire"]
    }
    """
    # Import from data/database_insertion module
    import sys
    from pathlib import Path
    
    # Add database_insertion to path if not already there
    db_insertion_path = Path(__file__).parent.parent.parent / "data" / "database_insertion"
    if str(db_insertion_path) not in sys.path:
        sys.path.insert(0, str(db_insertion_path))
    
    from publish_mob import publish_or_update_mob  # type: ignore
    
    mob_name = payload.get("mob_name")
    username = payload.get("username")
    prompts = payload.get("prompts", [])
    geometry = payload.get("geometry", {})
    api_key = payload.get("api_key")
    
    # Validate required fields
    if not mob_name:
        raise HTTPException(status_code=400, detail="mob_name is required")
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    if not prompts:
        raise HTTPException(status_code=400, detail="prompts array is required")
    if not geometry:
        raise HTTPException(status_code=400, detail="geometry is required")
    
    # Use the combined publish_or_update function
    result = publish_or_update_mob(mob_name, username, prompts, geometry, api_key)
    
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
    
    return result


async def check_published_mob(mob_name: str, username: str):
    """
    GET /api/publish/check/{mob_name}/{username} ΓÇö Check if a mob is already published.
    
    Returns:
    {
        "exists": true/false,
        "full_name": "fire_dragon_player123"
    }
    """
    # Import from data/database_insertion module
    import sys
    from pathlib import Path
    
    db_insertion_path = Path(__file__).parent.parent.parent / "data" / "database_insertion"
    if str(db_insertion_path) not in sys.path:
        sys.path.insert(0, str(db_insertion_path))
    
    from publish_mob import check_mob_exists  # type: ignore
    
    exists = check_mob_exists(mob_name, username)
    return {
        "exists": exists,
        "full_name": f"{mob_name}_{username}"
    }


VALID_TIERS = {"free", "creator", "pro"}


def upsert_user(payload: dict = Body(...)):
    """POST /api/users ΓÇö Create or update a user with their subscription tier."""
    from backend.database.db import execute_query, fetch_one
    username = (payload.get("username") or "").strip()
    tier = payload.get("subscription_tier", "free")
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    if tier not in VALID_TIERS:
        tier = "free"
    execute_query(
        """
        INSERT INTO users (username, subscription_tier)
        VALUES (%s, %s)
        ON CONFLICT (username) DO UPDATE SET subscription_tier = EXCLUDED.subscription_tier
        """,
        (username, tier),
    )
    row = fetch_one("SELECT username, subscription_tier FROM users WHERE username = %s", (username,))
    return {"username": row["username"], "subscription_tier": row["subscription_tier"]}


def get_user(username: str):
    """GET /api/users/{username} ΓÇö Fetch a user's subscription tier."""
    from backend.database.db import fetch_one
    row = fetch_one("SELECT username, subscription_tier FROM users WHERE username = %s", (username,))
    if not row:
        return {"username": username, "subscription_tier": "free"}
    return {"username": row["username"], "subscription_tier": row["subscription_tier"]}
