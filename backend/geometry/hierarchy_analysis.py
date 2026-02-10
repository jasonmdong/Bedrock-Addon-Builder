#!/usr/bin/env python3
"""
Create a comprehensive test showing what the rendering should look like.
This explains the Three.js transform hierarchy and how bones compose.
"""

print("""
THREE.JS TRANSFORM HIERARCHY AND COMPOSITION
=============================================

When we have:
  rootGroup (the model)
    ├── bodyGroup
    │   ├── body_mesh_0
    │   ├── body_mesh_1
    │   ├── headGroup (CHILD of bodyGroup)
    │   │   ├── head_mesh_0
    │   │   ├── head_mesh_1
    │   │   └── head_mesh_2 (horns)
    │   ├── leg0Group
    │   ├── leg1Group
    │   ├── leg2Group
    │   └── leg3Group
    └── ...

The transforms COMPOSE as follows:

1. Body meshes are positioned relative to bodyGroup's origin
   - bodyGroup.position = body.pivot = [0, 19, 2]
   - body_mesh_0.position = [0, 1, -2] (relative to bodyGroup)
   - World position of body_mesh_0 = bodyGroup.position + body_mesh_0.position
                                   = [0, 19, 2] + [0, 1, -2]
                                   = [0, 20, 0] ✓

2. Head group is positioned relative to bodyGroup
   - headGroup.position = head.pivot = [0, 20, -8] (this is in BODY space!)
   - Wait... is head.pivot in body space or world space?

CRITICAL QUESTION: Are pivots in PARENT space or WORLD space?

Looking at the data:
  body.pivot = [0, 19, 2]  (root bone)
  head.pivot = [0, 20, -8]  (child of body)
  
If head.pivot is in WORLD space, then:
  - The head's rotation center is at [0, 20, -8] in world space
  - But since head is child of body, we need to apply body's transforms first
  
If head.pivot is in BODY space (relative to body), then:
  - The head's rotation center is at [0, 20, -8] relative to body's pivot
  - Relative to body's pivot [0, 19, 2]:
    - head in body space: [0-0, 20-19, -8-2] = [0, 1, -10]

Let me think about this differently. In Bedrock's model structure:
- Bones can have parents
- When we set a bone's pivot and position, are these in parent space or world space?

From the Bedrock wiki and testing:
- Bone.pivot is the ROTATION PIVOT of that bone
- When a bone is parented, the pivot is treated as LOCAL to that parent
- So head.pivot = [0, 20, -8] is indeed in WORLD coordinates, but since it's a child of body,
  the THREE.js transform handles it correctly by adding child groups to parent groups

Wait, I think I'm overcomplicating this. Let me re-read the original Bedrock spec:

In Bedrock:
- Each bone has a pivot point
- Bones can have parents  
- When a bone is rotated, it rotates around its pivot
- The position is implicit: it's where the pivot is

So if we're building a THREE.js hierarchy:
  bodyGroup.position = [0, 19, 2] (body's pivot in world space)
  headGroup.position = [0, 20, -8] (head's pivot in world space)
  
But when we ADD headGroup as a CHILD of bodyGroup:
  bodyGroup.add(headGroup)
  
Then the headGroup's position is interpreted as LOCAL to bodyGroup's coordinate system!
So we need to convert head's world-space pivot to body-space:
  head_in_body_space = head.pivot - body.pivot
                     = [0, 20, -8] - [0, 19, 2]
                     = [0, 1, -10]

This is the key issue! When setting up the hierarchy, we need to convert parent-relative positions!

Let me verify this is the issue...
""")

# Calculate the conversion
body_pivot = [0, 19, 2]
head_pivot = [0, 20, -8]
head_in_body_space = [head_pivot[i] - body_pivot[i] for i in range(3)]

print(f"""
CONVERSION TEST:
  body.pivot (world): {body_pivot}
  head.pivot (world): {head_pivot}
  
When we add headGroup to bodyGroup:
  We should set headGroup.position to head's position in BODY SPACE
  
  head_in_body_space = head.pivot - body.pivot
                     = {head_in_body_space}
                     
So the code should be:
  headGroup.position.set({head_in_body_space[0]}, {head_in_body_space[1]}, {head_in_body_space[2]})
  
Then when Three.js renders:
  - bodyGroup is at [0, 19, 2] in world
  - headGroup is at [0, 1, -10] in body space
  - So head's world position is [0, 19, 2] + [0, 1, -10] = [0, 20, -8] ✓
  
And cubes in head are positioned relative to headGroup's origin:
  - head_mesh_0 should be at [0, 0, -3] (local to headGroup)
  - World position: [0, 20, -8] + [0, 0, -3] = [0, 20, -11] (center of head cube)
  
But wait, the cube center should be [0, 20, -11] in world space... let me verify:
  head cube 0 origin: [-4, 16, -14]
  size: [8, 8, 6]
  center: [0, 20, -11] ✓
  
So the cube world position is correct!

But the local position relative to headGroup should be:
  local = world - headGroup.world_position
        = [0, 20, -11] - [0, 20, -8]
        = [0, 0, -3]
        
Which matches what we calculated: center - pivot = [0, 20, -11] - [0, 20, -8] = [0, 0, -3] ✓

So the fix is:
  When adding child bones to parent bones, we need to adjust the position to parent space!
""")
