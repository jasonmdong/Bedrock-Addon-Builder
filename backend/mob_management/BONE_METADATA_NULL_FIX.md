# ✅ Bone Metadata Extraction - Supports Both Geometry Formats

## Overview

The `extract_bone_metadata()` function now supports **two different geometry formats** used in Minecraft Bedrock geometry files and handles NULL cases properly.

---

## Supported Geometry Formats

### Format 1: Standard (minecraft:geometry array)

```json
{
  "format_version": "1.12.0",
  "minecraft:geometry": [
    {
      "description": {
        "identifier": "geometry.creeper"
      },
      "bones": [
        {
          "name": "body",
          "pivot": [0.0, 18.0, 0.0],
          "parent": null
        },
        {
          "name": "head",
          "pivot": [0.0, 24.0, 0.0],
          "parent": "body"
        }
      ]
    }
  ]
}
```

**Used by**: Most modern mobs (creeper, zombie, etc.)

---

### Format 2: Alternative (geometry.{name} object)

```json
{
  "format_version": "1.8.0",
  "geometry.bat": {
    "visible_bounds_width": 1,
    "visible_bounds_height": 1,
    "bones": [
      {
        "name": "head",
        "pivot": [0.0, 24.0, 0.0]
      },
      {
        "name": "body",
        "pivot": [0.0, 24.0, 0.0]
      }
    ]
  }
}
```

**Used by**: Older mob formats (bat, chicken, some legacy entities)

---

## How It Works

The function now uses a **two-step approach**:

### Step 1: Try Standard Format
```python
geometries = data.get("minecraft:geometry", [])
if geometries and len(geometries) > 0:
    bones_list = geometries[0].get("bones", [])
```

### Step 2: Fallback to Alternative Format
```python
if not bones_list:
    for key in data.keys():
        if key.startswith("geometry."):
            geometry_obj = data[key]
            if isinstance(geometry_obj, dict) and "bones" in geometry_obj:
                bones_list = geometry_obj.get("bones", [])
                break
```

### Step 3: Return Result
```python
if not bones_list:
    return None  # No bones found in either format
else:
    return {
        "bone_count": len(bones_list),
        "bones": [...]
    }
```

---

## When bone_metadata is NULL

`bone_metadata` will be NULL when:

1. ✅ **Geometry fetch failed** (network error, file not found)
2. ✅ **No bones in standard format** AND **no bones in alternative format**
3. ✅ **Entity has no bones** (items, projectiles like arrows)
4. ✅ **Parsing error occurred**
5. ✅ **Input is None**

---

## When bone_metadata Has Data

`bone_metadata` will contain JSONB data when bones are found in **either format**:

```json
{
  "bone_count": 12,
  "bones": [
    {
      "name": "body",
      "parent": null,
      "pivot": [0, 0, 0]
    },
    {
      "name": "head",
      "parent": "body",
      "pivot": [0, 24, 0]
    }
  ]
}
```

---

## Example Output

```
Processing: creeper
  Extracted 12 bones
✓ Inserted mob: creeper

Processing: bat
  Found bones in alternative format: geometry.bat
  Extracted 2 bones
✓ Inserted mob: bat

Processing: arrow
  ⚠ No bones found in geometry (tried both formats)
✓ Inserted mob: arrow
```

---

## Benefits

### Before Fix:
- ❌ Only supported standard `minecraft:geometry` format
- ❌ Returned empty dict `{}` for alternative format → not NULL in database
- ❌ Many mobs had missing bone data

### After Fix:
- ✅ Supports both standard and alternative formats
- ✅ Returns `None` when no bones found → NULL in database
- ✅ Extracts bones from older geometry files (bat, chicken, etc.)
- ✅ Clear logging shows which format was used

---

## Code Changes

**File**: `get_bone_data.py`

**Key Changes**:
1. Added fallback to check for `geometry.*` keys
2. Returns `None` instead of `{}` when no bones found
3. Added logging to show which format was detected
4. Handles `None` input gracefully

---

## Testing

Run the test script to verify both formats work:

```bash
python test_bone_formats.py
```

Expected output:
```
Test 1: Standard Format (minecraft:geometry)
  Extracted 2 bones
✓ Success! Found 2 bones

Test 2: Alternative Format (geometry.bat)
  Found bones in alternative format: geometry.bat
  Extracted 2 bones
✓ Success! Found 2 bones

Test 3: No Bones (should return None)
  ⚠ No bones found in geometry (tried both formats)
✓ Correctly returned None

All Tests Complete!
```

---

## Database Impact

**Query to see which format was used**:

```sql
-- Mobs with bone data (from either format)
SELECT mob_name, bone_metadata->'bone_count' as bone_count
FROM mob_geometries 
WHERE bone_metadata IS NOT NULL
ORDER BY bone_count DESC;

-- Mobs with NULL bone_metadata (no bones in either format)
SELECT mob_name 
FROM mob_geometries 
WHERE bone_metadata IS NULL;
```

---

## Summary

✅ **Supports two geometry formats** - standard and alternative
✅ **Returns NULL properly** - when no bones exist in either format
✅ **Better coverage** - extracts bones from older mob files
✅ **Clear logging** - shows which format was detected
✅ **Backward compatible** - still works with existing mobs

Now when you run `python main.py`, mobs with bones in **either format** will have their bone metadata extracted and stored! 🎉

