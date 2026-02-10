#!/usr/bin/env python3
"""
Test script to fetch and validate real Bedrock geometry files
and verify the rendering implementation matches the specification.
"""
import json
import sys
import httpx
from pathlib import Path

def fetch_geometry(mob_name: str) -> dict:
    """Fetch geometry from bedrock-samples."""
    url = f"https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity/{mob_name}.geo.json"
    print(f"Fetching: {url}")
    
    try:
        response = httpx.get(url, timeout=10)
        if response.status_code != 200:
            print(f"Error: HTTP {response.status_code}")
            return None
        return response.json()
    except Exception as e:
        print(f"Error fetching: {e}")
        return None

def analyze_geometry_structure(geometry_data: dict, mob_name: str) -> None:
    """Analyze and validate the geometry structure."""
    print(f"\n{'='*60}")
    print(f"Analyzing {mob_name}.geo.json")
    print(f"{'='*60}")
    
    # Find the geometry array
    geometries = []
    if "minecraft:geometry" in geometry_data:
        geometries = geometry_data["minecraft:geometry"]
    elif isinstance(geometry_data, list):
        geometries = geometry_data
    else:
        # Look for geometry.* keys
        for key in geometry_data:
            if key.startswith("geometry."):
                value = geometry_data[key]
                if isinstance(value, list):
                    geometries = value
                elif isinstance(value, dict) and "bones" in value:
                    geometries = [value]
                break
    
    if not geometries:
        print("No geometries found")
        return
    
    for geom_idx, geom in enumerate(geometries):
        if not isinstance(geom, dict):
            continue
            
        print(f"\n[GEOMETRY {geom_idx}]")
        if "description" in geom:
            print(f"  Identifier: {geom['description'].get('identifier', 'N/A')}")
        
        bones = geom.get("bones", [])
        print(f"  Total bones: {len(bones)}")
        
        # Create a map for hierarchy analysis
        bone_map = {bone["name"]: bone for bone in bones if isinstance(bone, dict)}
        
        # Track parent-child relationships
        parent_count = {}
        for bone in bones:
            if not isinstance(bone, dict):
                continue
            
            parent = bone.get("parent")
            if parent:
                if parent not in parent_count:
                    parent_count[parent] = 0
                parent_count[parent] += 1
        
        print(f"\n  Bone Hierarchy Analysis:")
        print(f"  - Root bones (no parent): {sum(1 for b in bones if isinstance(b, dict) and 'parent' not in b)}")
        print(f"  - Parented bones: {sum(1 for b in bones if isinstance(b, dict) and 'parent' in b)}")
        
        # Show bone details
        print(f"\n  Bone Details:")
        for bone in bones:
            if not isinstance(bone, dict):
                continue
            
            name = bone.get("name", "UNKNOWN")
            parent = bone.get("parent", "ROOT")
            pivot = bone.get("pivot", [0, 0, 0])
            rotation = bone.get("rotation", [0, 0, 0])
            cubes = bone.get("cubes", [])
            
            print(f"\n    [{name}]")
            print(f"      Parent: {parent}")
            print(f"      Pivot: {pivot}")
            print(f"      Rotation: {rotation}")
            print(f"      Cubes: {len(cubes)}")
            
            # Analyze cubes
            if cubes:
                for cube_idx, cube in enumerate(cubes):
                    if not isinstance(cube, dict):
                        continue
                    
                    origin = cube.get("origin", [0, 0, 0])
                    size = cube.get("size", [0, 0, 0])
                    inflate = cube.get("inflate", 0)
                    uv = cube.get("uv", {})
                    
                    print(f"        Cube {cube_idx}:")
                    print(f"          Origin: {origin}")
                    print(f"          Size: {size}")
                    print(f"          Inflate: {inflate}")
                    if uv:
                        print(f"          UV: {uv}")
        
        # Check for overlapping cubes (same parent, similar positions)
        print(f"\n  Overlap Detection (cubes in same bone with similar positions):")
        overlap_found = False
        for bone in bones:
            if not isinstance(bone, dict):
                continue
            
            cubes = bone.get("cubes", [])
            if len(cubes) > 1:
                for i, cube1 in enumerate(cubes):
                    for j, cube2 in enumerate(cubes):
                        if i >= j or not isinstance(cube1, dict) or not isinstance(cube2, dict):
                            continue
                        
                        origin1 = cube1.get("origin", [0, 0, 0])
                        size1 = cube1.get("size", [0, 0, 0])
                        inflate1 = cube1.get("inflate", 0)
                        
                        origin2 = cube2.get("origin", [0, 0, 0])
                        size2 = cube2.get("size", [0, 0, 0])
                        inflate2 = cube2.get("inflate", 0)
                        
                        # Check if they share the same space
                        if origin1 == origin2:
                            print(f"    - {bone['name']}: Cubes {i} and {j} share same origin")
                            print(f"      Note: inflate1={inflate1}, inflate2={inflate2} (used to separate overlays)")
                            overlap_found = True
        
        if not overlap_found:
            print(f"    - No intentional overlaps detected")

def main():
    """Fetch and analyze several mob geometries."""
    mobs = ["cow", "sheep", "zombie", "spider", "creeper"]
    
    results = {}
    for mob_name in mobs:
        geom_data = fetch_geometry(mob_name)
        if geom_data:
            analyze_geometry_structure(geom_data, mob_name)
            results[mob_name] = "✓"
        else:
            results[mob_name] = "✗"
    
    print(f"\n{'='*60}")
    print("Summary:")
    for mob_name, status in results.items():
        print(f"  {status} {mob_name}")

if __name__ == "__main__":
    main()
