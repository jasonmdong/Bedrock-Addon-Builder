#!/usr/bin/env python3
import httpx

url = 'https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/models/entity/chicken.geo.json'
response = httpx.get(url)
geom_data = response.json()
geom = geom_data['minecraft:geometry'][0]
bones = geom.get('bones', [])

print("CHICKEN BONE PIVOTS:")
for bone in bones:
    pivot = bone.get('pivot', [0, 0, 0])
    parent = bone.get('parent', 'ROOT')
    name = bone['name']
    print(f"{name:10} parent={parent:5} pivot={pivot}")
