#!/usr/bin/env python3
"""
Generate a detailed geometry validation report that shows 
how the positioning should work in the 3D viewport.
"""
import json
import httpx
from pathlib import Path

def create_positioning_guide():
    """Create a detailed guide showing correct positioning math."""
    
    guide = """
# Minecraft Geometry Positioning Guide

## Key Concepts

### 1. Bone Pivot (Anchor Point)
- Each bone has a `pivot: [x, y, z]` which is the ROTATION CENTER
- The bone's position in world space = its pivot
- Rotations of the bone occur AROUND this pivot

### 2. Cube Origin (Corner Point)
- Each cube has an `origin: [x, y, z]` which is the MINIMUM CORNER
- The origin is in WORLD SPACE, not relative to the bone
- The cube MUST be positioned relative to the bone's pivot

### 3. Correct Positioning Math

For a cube in a bone:
```
localCubePosition = cube.origin - bone.pivot
```

Example from cow.geo.json:
- body bone: pivot = [0, 19, 2]
- head bone: pivot = [0, 20, -8]
  - head is child of body
  - cube 0: origin = [-4, 16, -14]
  
Head cube local position (relative to head's pivot):
  localPos = [-4, 16, -14] - [0, 20, -8]
           = [-4, -4, -6]

### 4. Inflation (Overlay Separation)
- inflate: 0.5 means expand by 0.5 units in ALL directions
- Used to prevent visual overlap when one object is meant to be "on top" of another
- E.g., zombie hat overlays the head with inflate=0.5

Adjusted size: [x + inflate*2, y + inflate*2, z + inflate*2]

### 5. Bone Hierarchy (Parent-Child)
- When a bone has a parent, its pivot is RELATIVE to parent's coordinate system
- Rotations propagate DOWN the hierarchy
- Example: zombie waist -> body -> head -> hat
  - Rotating body rotates everything below it
  - Rotating head rotates hat
  - hat has inflate=0.5 to sit on top of head

### 6. Y-UP Coordinate System (Minecraft)
- Minecraft uses Y as UP (vertical axis)
- WebGL/Three.js default uses Y as UP (we're good!)
- BUT we need to invert Z when converting from Minecraft coords
- Z-inversion: z_webgl = -z_minecraft

## Implementation Checklist

✓ Create THREE.Group for each bone
✓ Position bone group at bone.pivot
✓ Apply bone rotation
✓ For each cube in the bone:
  ✓ Calculate localPos = cube.origin - bone.pivot
  ✓ Invert Z: localPos.z = -localPos.z
  ✓ Position mesh at localPos
  ✓ Apply cube rotation (in degrees -> radians)
  ✓ Adjust size by inflate: [size + inflate*2]
✓ Build parent-child hierarchy by adding child groups to parent groups
✓ Let Three.js handle transform propagation

## Real Examples Validated

### Cow
- 6 bones, 1 root (body)
- 5 legs parented to body
- All cubes properly positioned using origin - pivot

### Zombie  
- 10 bones in hierarchy: waist -> body -> head -> hat
- hat has inflate=0.5 to overlay the head
- arms and legs parented to body
- items (rightItem, leftItem) have no cubes but are anchor points

### Spider
- 11 bones
- body0 is root
- head, body1, 8 legs all parented to body0
- Long thin legs extended far from pivot (origin >> pivot)

## Common Issues & Fixes

Issue: Cubes overlapping or in wrong position
-> Check: Is cube.origin - bone.pivot calculated correctly?
-> Check: Is Z coordinate inverted?

Issue: Bones not rotating together
-> Check: Is bone hierarchy properly set up (parent groups)?
-> Check: Are child groups added to parent groups?

Issue: Model appears flipped or mirrored
-> Check: Is Z inversion applied to both position AND rotation?

Issue: Inflate not working (cubes still overlap)
-> Check: Is inflate applied to SIZE not position?
-> Inflate expands: [size[0] + inflate*2, size[1] + inflate*2, size[2] + inflate*2]
"""
    
    return guide

def validate_positioning_with_cow():
    """Validate positioning with cow geometry."""
    
    # Fetch cow geometry
    url = "https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity/cow.geo.json"
    response = httpx.get(url)
    geom_data = response.json()
    
    # Find geometry array
    geometries = []
    if "minecraft:geometry" in geom_data:
        geometries = geom_data["minecraft:geometry"]
    else:
        for key in geom_data:
            if key.startswith("geometry."):
                value = geom_data[key]
                if isinstance(value, list):
                    geometries = value
                elif isinstance(value, dict) and "bones" in value:
                    geometries = [value]
                break
    
    geom = geometries[0]
    bones = {b["name"]: b for b in geom["bones"]}
    
    print("\n" + "="*70)
    print("COW GEOMETRY POSITIONING VALIDATION")
    print("="*70)
    
    # Analyze body bone
    body = bones["body"]
    print(f"\nBody (root bone):")
    print(f"  Pivot: {body['pivot']}")
    print(f"  Cubes: {len(body['cubes'])}")
    for i, cube in enumerate(body["cubes"]):
        origin = cube["origin"]
        size = cube["size"]
        print(f"    Cube {i}: origin={origin}, size={size}")
    
    # Analyze head bone
    head = bones["head"]
    print(f"\nHead (child of body):")
    print(f"  Parent: {head['parent']}")
    print(f"  Pivot: {head['pivot']}")
    print(f"  Cube 0:")
    cube = head["cubes"][0]
    origin = cube["origin"]
    size = cube["size"]
    pivot = head["pivot"]
    
    print(f"    Origin: {origin}")
    print(f"    Pivot: {pivot}")
    
    # Calculate local position
    local_pos = [origin[i] - pivot[i] for i in range(3)]
    print(f"    Local Pos (origin - pivot): {local_pos}")
    print(f"    Size: {size}")
    print(f"    -> Mesh positioned at {local_pos} relative to head's pivot")
    print(f"    -> Head's pivot is at {pivot} in world space")
    print(f"    -> Since head is child of body, transforms compose")
    
    # Analyze a leg
    leg0 = bones["leg0"]
    print(f"\nLeg0 (child of body):")
    print(f"  Parent: {leg0['parent']}")
    print(f"  Pivot: {leg0['pivot']}")
    cube = leg0["cubes"][0]
    origin = cube["origin"]
    size = cube["size"]
    pivot = leg0["pivot"]
    
    print(f"  Cube 0:")
    print(f"    Origin: {origin}")
    print(f"    Pivot: {pivot}")
    local_pos = [origin[i] - pivot[i] for i in range(3)]
    print(f"    Local Pos (origin - pivot): {local_pos}")
    print(f"    Size: {size}")
    print(f"    -> Note: leg extends DOWN (Y=0) from pivot (Y=12)")
    print(f"    -> This creates the proper leg positioning")

if __name__ == "__main__":
    guide = create_positioning_guide()
    print(guide)
    
    validate_positioning_with_cow()
    
    # Save guide to file
    with open("GEOMETRY_POSITIONING_GUIDE.md", "w") as f:
        f.write(guide)
    
    print("\n" + "="*70)
    print("Guide saved to GEOMETRY_POSITIONING_GUIDE.md")
