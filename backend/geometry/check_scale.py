#!/usr/bin/env python3
"""
Check for scale fields in geometry data.
"""
import httpx
import json

mobs = ["cow", "chicken", "enderman"]

for mob_name in mobs:
    url = f'https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity/{mob_name}.geo.json'
    response = httpx.get(url)
    geom_data = response.json()
    
    print(f"\n{'='*70}")
    print(f"{mob_name.upper()} - FULL GEOMETRY STRUCTURE")
    print(f"{'='*70}")
    
    # Check for scale at geometry level
    if 'minecraft:geometry' in geom_data:
        geom = geom_data['minecraft:geometry'][0]
    else:
        for key in geom_data:
            if key.startswith('geometry.'):
                value = geom_data[key]
                if isinstance(value, list):
                    geom = value[0]
                elif isinstance(value, dict) and "bones" in value:
                    geom = value
                break
    
    # Print geometry-level keys
    print(f"\nGeometry keys: {list(geom.keys())}")
    
    # Check for scale
    if 'scale' in geom:
        print(f"Geometry scale: {geom['scale']}")
    
    # Check description
    if 'description' in geom:
        print(f"Description: {geom['description']}")
    
    # Check for scale in bones
    print(f"\nBone scales:")
    bones = geom.get('bones', [])
    for bone in bones:
        if 'scale' in bone:
            print(f"  {bone['name']}: scale={bone['scale']}")
        else:
            # Check if all bones have scale
            pass
    
    # Print first bone completely to see all fields
    if bones:
        print(f"\nFirst bone (complete structure):")
        first_bone = bones[0]
        for key, value in first_bone.items():
            if key not in ['cubes']:  # Skip cubes for brevity
                print(f"  {key}: {value}")
