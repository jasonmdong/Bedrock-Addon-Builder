"""One-time script to fix MoLang rotation expressions in animation_generation.py.

Changes query.modified_distance_moved -> query.anim_time in math.cos/sin expressions
while preserving anim_time_update: "query.modified_distance_moved" lines.
"""
import re

fpath = 'c:/Users/caitl/Bedrock-Addon-Builder/backend/llm/animation_generation.py'
content = open(fpath, 'r', encoding='utf-8').read()

before = content.count('query.modified_distance_moved')

# Replace query.modified_distance_moved with query.anim_time ONLY inside math.cos/math.sin expressions
content = re.sub(
    r'(math\.\w+\()(query\.modified_distance_moved)',
    r'\1query.anim_time',
    content
)

# Fix descriptive text that references the old pattern
content = content.replace(
    'Legs 0 & 3: "math.cos(query.modified_distance_moved',
    'Legs 0 & 3: "math.cos(query.anim_time'
)
content = content.replace(
    'Legs 1 & 2: "-math.cos(query.modified_distance_moved',
    'Legs 1 & 2: "-math.cos(query.anim_time'
)

# Fix the rule about what query to use in rotations
content = content.replace(
    '- Using query.anim_time for walk/run (MUST use query.modified_distance_moved)',
    '- Using query.modified_distance_moved directly in rotation (MUST use query.anim_time with anim_time_update)'
)

# Fix section header
content = content.replace(
    'WALK ANIMATION (query.modified_distance_moved)',
    'WALK ANIMATION (uses query.anim_time driven by anim_time_update)'
)

after = content.count('query.modified_distance_moved')
print(f'Before: {before} occurrences, After: {after} occurrences')
print(f'Replaced {before - after} rotation expressions')

# Verify anim_time_update lines are untouched
atl = [l.strip() for l in content.split('\n') if 'anim_time_update' in l]
print(f'anim_time_update lines remaining: {len(atl)}')
for l in atl[:5]:
    print(f'  {l[:100]}')

open(fpath, 'w', encoding='utf-8').write(content)
print('File saved.')
