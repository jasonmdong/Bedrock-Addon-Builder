#!/usr/bin/env python3
"""
Verify that the new positioning formula produces correct results.
"""
import httpx

url = 'https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity/cow.geo.json'
response = httpx.get(url)
geom_data = response.json()

# Find geometry
for key in geom_data:
    if key.startswith('geometry.'):
        geom = geom_data[key] if isinstance(geom_data[key], dict) else geom_data[key][0]
        break
else:
    geom = geom_data['minecraft:geometry'][0]

bones = geom.get('bones', [])

print("="*70)
print("GEOMETRY POSITIONING VERIFICATION")
print("="*70)

# Test body
body = next(b for b in bones if b['name'] == 'body')
print("\nBODY BONE:")
print(f"  Pivot: {body['pivot']}")

cube = body['cubes'][0]
origin = cube['origin']
size = cube['size']
pivot = body['pivot']

# New formula: cubeCenter - pivot
cube_center = [origin[i] + size[i]/2 for i in range(3)]
local_pos = [cube_center[i] - pivot[i] for i in range(3)]

print(f"  Cube 0:")
print(f"    Origin (min corner): {origin}")
print(f"    Size: {size}")
print(f"    Cube center: {cube_center}")
print(f"    Pivot: {pivot}")
print(f"    Local position: {local_pos}")
print(f"    Expected in Three.js: mesh.position.set({local_pos[0]}, {local_pos[1]}, {local_pos[2]})")

# Test head
head = next(b for b in bones if b['name'] == 'head')
print("\nHEAD BONE (child of body):")
print(f"  Pivot: {head['pivot']}")

cube = head['cubes'][0]
origin = cube['origin']
size = cube['size']
pivot = head['pivot']

cube_center = [origin[i] + size[i]/2 for i in range(3)]
local_pos = [cube_center[i] - pivot[i] for i in range(3)]

print(f"  Cube 0:")
print(f"    Origin: {origin}")
print(f"    Size: {size}")
print(f"    Cube center: {cube_center}")
print(f"    Pivot: {pivot}")
print(f"    Local position: {local_pos}")
print(f"    Expected in Three.js: mesh.position.set({local_pos[0]}, {local_pos[1]}, {local_pos[2]})")

# Test horns (head cubes 1 and 2)
print(f"\n  Cube 1 (horn):")
cube = head['cubes'][1]
origin = cube['origin']
size = cube['size']
cube_center = [origin[i] + size[i]/2 for i in range(3)]
local_pos = [cube_center[i] - pivot[i] for i in range(3)]
print(f"    Origin: {origin}")
print(f"    Center: {cube_center}")
print(f"    Pivot: {head['pivot']}")
print(f"    Local position: {local_pos}")
print(f"    Expected in Three.js: mesh.position.set({local_pos[0]}, {local_pos[1]}, {local_pos[2]})")

print("\n" + "="*70)
print("BONE POSITIONS (in world space, not relative to parent)")
print("="*70)

for bone in bones:
    pivot = bone['pivot']
    parent = bone.get('parent', 'ROOT')
    print(f"\n{bone['name']}:")
    print(f"  Parent: {parent}")
    print(f"  Pivot (world space, but relative to parent): {pivot}")
    print(f"  Expected THREE.Group position: boneGroup.position.set({pivot[0]}, {pivot[1]}, {pivot[2]})")
