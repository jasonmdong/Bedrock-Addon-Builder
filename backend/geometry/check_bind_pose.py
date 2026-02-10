#!/usr/bin/env python3
"""
Check for bind_pose_rotation fields.
"""
import httpx

mobs = ["cow", "chicken", "enderman"]

for mob_name in mobs:
    url = f'https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity/{mob_name}.geo.json'
    response = httpx.get(url)
    geom_data = response.json()
    
    # Find geometry
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
    
    print(f"\n{'='*70}")
    print(f"{mob_name.upper()} - bind_pose_rotation FIELDS")
    print(f"{'='*70}")
    
    bones = geom.get('bones', [])
    for bone in bones:
        if 'bind_pose_rotation' in bone:
            print(f"{bone['name']}: bind_pose_rotation={bone['bind_pose_rotation']}")
    
    if not any('bind_pose_rotation' in bone for bone in bones):
        print("No bind_pose_rotation fields found")
