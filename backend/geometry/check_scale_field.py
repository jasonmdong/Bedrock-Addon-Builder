import json
import os

def check_scale(geometry_path):
    """Check for scale field in geometry"""
    with open(geometry_path, 'r') as f:
        data = json.load(f)
    
    # Check top-level scale
    if 'scale' in data:
        print(f"Top-level scale: {data['scale']}")
    
    # Check bone-level scale
    for bone in data.get('bones', []):
        if 'scale' in bone:
            print(f"Bone '{bone['name']}' scale: {bone['scale']}")

# Check all geometries
base_path = r"c:\Users\caitl\Bedrock-Addon-Builder\data\specs"
for filename in os.listdir(base_path):
    if filename.endswith('.json'):
        print(f"\n=== {filename} ===")
        check_scale(os.path.join(base_path, filename))
