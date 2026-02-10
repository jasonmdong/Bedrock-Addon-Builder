#!/usr/bin/env python3
"""
Debug script to check bone rotations in different mobs.
"""
import httpx
import json

mobs = ["cow", "chicken", "enderman"]

for mob_name in mobs:
    url = f'https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity/{mob_name}.geo.json'
    response = httpx.get(url)
    geom_data = response.json()
    
    # Find geometry
    geom = None
    if 'minecraft:geometry' in geom_data:
        geometries = geom_data.get('minecraft:geometry', [])
        if geometries:
            geom = geometries[0]
    else:
        for key in geom_data:
            if key.startswith('geometry.'):
                value = geom_data[key]
                if isinstance(value, list):
                    geom = value[0]
                elif isinstance(value, dict) and "bones" in value:
                    geom = value
                break
    
    if not geom:
        print(f"Could not find geometry for {mob_name}")
        continue
    
    print(f"\n{'='*70}")
    print(f"{mob_name.upper()} - BONE ROTATIONS AND SIZES")
    print(f"{'='*70}")
    
    bones = geom.get('bones', [])
    for bone in bones:
        rotation = bone.get('rotation', [0, 0, 0])
        parent = bone.get('parent', 'ROOT')
        
        # Check if rotation is non-zero
        has_rotation = any(r != 0 for r in rotation)
        
        print(f"\n{bone['name']}:")
        print(f"  Parent: {parent}")
        print(f"  Rotation: {rotation} {f'(NON-ZERO!)' if has_rotation else '(default)'}")
        
        # Show cube sizes
        if bone.get('cubes'):
            print(f"  Cubes: {len(bone['cubes'])}")
            for i, cube in enumerate(bone['cubes']):
                origin = cube.get('origin', [0, 0, 0])
                size = cube.get('size', [0, 0, 0])
                inflate = cube.get('inflate', 0)
                print(f"    Cube {i}: origin={origin}, size={size}, inflate={inflate}")
