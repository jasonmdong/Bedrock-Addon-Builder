#!/usr/bin/env python3
import json
import httpx

url = 'https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity/cow.geo.json'
response = httpx.get(url)
geom_data = response.json()

# Find the geometry - it might be in different formats
geom = None
if 'minecraft:geometry' in geom_data:
    geometries = geom_data.get('minecraft:geometry', [])
    if geometries:
        geom = geometries[0]
else:
    # Try finding geometry.* key
    for key in geom_data:
        if key.startswith('geometry.') and isinstance(geom_data[key], (list, dict)):
            if isinstance(geom_data[key], list):
                geom = geom_data[key][0]
            else:
                geom = geom_data[key]
            break

if not geom:
    print("Could not find geometry")
    exit(1)
bones = geom.get('bones', [])

print("="*70)
print("COW GEOMETRY - DEBUG ANALYSIS")
print("="*70)

body = next((b for b in bones if b['name'] == 'body'), None)
if body:
    print('\nBODY BONE (Root):')
    print(f'  Pivot: {body["pivot"]}')
    for idx, cube in enumerate(body['cubes']):
        origin = cube['origin']
        size = cube['size']
        
        # Minecraft: origin is minimum corner
        # Three.js: position is the center
        # So: center = origin + size/2
        center = [origin[i] + size[i]/2 for i in range(3)]
        pivot = body['pivot']
        local_center = [center[i] - pivot[i] for i in range(3)]
        
        print(f'\n  Cube {idx}:')
        print(f'    Origin (min corner): {origin}')
        print(f'    Size: {size}')
        print(f'    Center (origin + size/2): {center}')
        print(f'    Pivot: {pivot}')
        print(f'    Local center (center - pivot): {local_center}')
        print(f'    -> Mesh should be positioned at {local_center}')

head = next((b for b in bones if b['name'] == 'head'), None)
if head:
    print('\nHEAD BONE (Child of body):')
    print(f'  Parent: {head.get("parent")}')
    print(f'  Pivot: {head["pivot"]}')
    for idx, cube in enumerate(head['cubes']):
        origin = cube['origin']
        size = cube['size']
        center = [origin[i] + size[i]/2 for i in range(3)]
        pivot = head['pivot']
        local_center = [center[i] - pivot[i] for i in range(3)]
        
        print(f'\n  Cube {idx}:')
        print(f'    Origin: {origin}')
        print(f'    Size: {size}')
        print(f'    Center: {center}')
        print(f'    Pivot: {pivot}')
        print(f'    Local center (center - pivot): {local_center}')
        print(f'    -> Mesh should be positioned at {local_center}')

print("\n" + "="*70)
print("IMPORTANT: Z-AXIS INVERSION")
print("="*70)
print("\nMinecraft uses Y-up with Z-forward")
print("Three.js uses Y-up with Z-backward (toward camera)")
print("\nSo when positioning in local space:")
print("  x_local = center_x - pivot_x  (unchanged)")
print("  y_local = center_y - pivot_y  (unchanged)")
print("  z_local = -(center_z - pivot_z)  (INVERTED)")
print("\nBut wait! Let me check if we should invert at positioning or at the end...")
