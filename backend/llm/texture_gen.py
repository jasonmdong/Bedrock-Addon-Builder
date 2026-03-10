"""Geometry-aware procedural texture generator for Minecraft Bedrock mobs.

Generates textures by reading the ACTUAL geometry UV map — every bone,
every cube, every face's exact UV coordinates — and painting the texture
atlas pixel-by-pixel against that map.

Pipeline:
  1. Fill entire atlas with opaque base color (no transparent gaps)
  2. Walk geometry: bone → cube → compute all 6 face UV rects
  3. Paint each face rect with role-specific color + per-face shading
  4. Overlay patterns (spots, stripes, etc.) on painted UV regions only
  5. Paint features (eyes on head front face)
  6. Encode to PNG → base64 data URL

No external dependencies beyond Python stdlib (raw PNG encoding).
"""

import base64
import math
import random
import struct
import binascii
import zlib
from typing import Optional


# ---------------------------------------------------------------------------
# PNG encoder for per-pixel RGBA data
# ---------------------------------------------------------------------------

def _make_png_from_pixels(width: int, height: int, pixels: list) -> bytes:
    """Encode a 2D pixel grid [y][x] of (r,g,b,a) tuples to PNG."""
    sig = b'\x89PNG\r\n\x1a\n'

    def chunk(name, data):
        return (struct.pack(">I", len(data)) + name + data +
                struct.pack(">I", binascii.crc32(name + data) & 0xffffffff))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    raw_rows = []
    for y in range(height):
        row_bytes = b'\x00'  # filter byte (none)
        for x in range(width):
            r, g, b, a = pixels[y][x]
            row_bytes += bytes([r & 0xFF, g & 0xFF, b & 0xFF, a & 0xFF])
        raw_rows.append(row_bytes)

    raw = b''.join(raw_rows)
    comp = zlib.compress(raw, level=9)
    return sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', comp) + chunk(b'IEND', b'')


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

def _clamp(v: int) -> int:
    return max(0, min(255, int(v)))


def _darken(rgb: tuple, factor: float = 0.7) -> tuple:
    return tuple(_clamp(c * factor) for c in rgb)


def _lighten(rgb: tuple, factor: float = 1.3) -> tuple:
    return tuple(_clamp(c * factor) for c in rgb)


def _blend(c1: tuple, c2: tuple, t: float) -> tuple:
    return tuple(_clamp(a + (b - a) * t) for a, b in zip(c1, c2))


# ---------------------------------------------------------------------------
# Bone role classification
# ---------------------------------------------------------------------------

_ROLE_KEYWORDS = {
    "head":  ["head", "skull", "cranium"],
    "face":  ["jaw", "mouth", "snout", "nose", "beak", "muzzle", "horn"],
    "body":  ["body", "torso", "chest", "trunk", "abdomen", "spine", "root"],
    "leg":   ["leg", "foot", "feet", "hoof", "paw", "thigh", "shin", "calf"],
    "arm":   ["arm", "hand", "wing", "fin", "flipper", "claw"],
    "tail":  ["tail"],
    "ear":   ["ear"],
}


def _classify_bone(bone_name: str) -> str:
    name = bone_name.lower().replace("_", " ")
    for role, keywords in _ROLE_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return role
    return "body"


# ---------------------------------------------------------------------------
# Face shading multipliers — makes 3D look more natural
# ---------------------------------------------------------------------------

_FACE_SHADE = {
    "top":    1.15,   # brightest — lit from above
    "front":  1.0,    # neutral
    "right":  0.92,
    "back":   0.85,
    "left":   0.88,
    "bottom": 0.75,   # darkest — underside
    # Per-face UV dict keys (Bedrock uses these names)
    "north":  1.0,
    "south":  0.85,
    "east":   0.92,
    "west":   0.88,
    "up":     1.15,
    "down":   0.75,
}


# ---------------------------------------------------------------------------
# Bedrock Box UV layout
# ---------------------------------------------------------------------------

def _box_uv_faces(u: int, v: int, w: int, h: int, d: int) -> dict:
    """Compute all 6 face UV rects for Bedrock box UV mapping.

    Standard Bedrock box UV layout for cube at uv=[u,v], size=[w,h,d]:

         u    u+d   u+d+w  u+2d+w
      v  ┌─────┬──────┬──────┬──────┐
         │     │ Top  │      │Bottom│
    v+d  ├─────┼──────┼──────┼──────┤
         │Right│Front │ Left │ Back │
   v+d+h └─────┴──────┴──────┴──────┘

    Right = East (+X), Left = West (-X), Front = North (-Z), Back = South (+Z)

    Returns dict of face_name → (fu, fv, fw, fh).
    """
    w = max(w, 0)
    h = max(h, 0)
    d = max(d, 0)

    return {
        "top":    (u + d,       v,       w, d),
        "bottom": (u + d + w,   v,       w, d),
        "right":  (u,           v + d,   d, h),
        "front":  (u + d,       v + d,   w, h),
        "left":   (u + d + w,   v + d,   d, h),
        "back":   (u + 2*d + w, v + d,   w, h),
    }


# ---------------------------------------------------------------------------
# Per-face UV dict handling (new Bedrock format)
# ---------------------------------------------------------------------------

def _perface_uv_rects(uv_dict: dict, cube_size: list) -> dict:
    """Extract face rects from per-face UV format.

    Per-face UV looks like:
      {"north": {"uv": [0,0], "uv_size": [8,8]}, ...}
    """
    w, h, d = (int(cube_size[0]), int(cube_size[1]), int(cube_size[2])
               if len(cube_size) >= 3 else (0, 0, 0))

    # Default uv_size per face based on cube dimensions
    _defaults = {
        "north": (w, h), "south": (w, h),
        "east":  (d, h), "west":  (d, h),
        "up":    (w, d), "down":  (w, d),
    }

    faces = {}
    for face_key, face_data in uv_dict.items():
        if not isinstance(face_data, dict):
            continue
        fuv = face_data.get("uv", [0, 0])
        default_size = _defaults.get(face_key, (w, h))
        fsize = face_data.get("uv_size", list(default_size))
        fu, fv = int(fuv[0]), int(fuv[1])
        fw = int(abs(fsize[0])) if len(fsize) > 0 else 0
        fh = int(abs(fsize[1])) if len(fsize) > 1 else 0
        # Handle negative uv_size (Bedrock flips the face)
        if len(fsize) > 0 and fsize[0] < 0:
            fu += int(fsize[0])
        if len(fsize) > 1 and fsize[1] < 0:
            fv += int(fsize[1])
        faces[face_key] = (fu, fv, fw, fh)
    return faces


# ---------------------------------------------------------------------------
# Pattern detection & application
# ---------------------------------------------------------------------------

def _detect_pattern(display_name: str, texture_hint: str) -> str:
    text = f"{display_name} {texture_hint}".lower()
    if any(w in text for w in ["giraffe", "leopard", "cheetah", "dalmatian", "spotted"]):
        return "spots"
    if any(w in text for w in ["tiger", "zebra", "striped", "bee", "wasp"]):
        return "stripes"
    if any(w in text for w in ["cow", "patched", "piebald", "pinto"]):
        return "patches"
    if any(w in text for w in ["snake", "lizard", "dragon", "reptile", "scales",
                                "crocodile", "alligator"]):
        return "scales"
    return "none"


def _apply_pattern(pixels, rects, pattern, base_rgb, tex_w, tex_h):
    """Apply a pattern over a list of UV rects."""
    if pattern == "none":
        return
    for (fx, fy, fw, fh) in rects:
        if fw < 3 or fh < 3:
            continue
        seed = fx * 997 + fy * 131
        if pattern == "spots":
            _paint_spots(pixels, fx, fy, fw, fh, base_rgb, tex_w, tex_h, seed)
        elif pattern == "stripes":
            _paint_stripes(pixels, fx, fy, fw, fh, base_rgb, tex_w, tex_h)
        elif pattern == "patches":
            _paint_patches(pixels, fx, fy, fw, fh, base_rgb, tex_w, tex_h, seed)
        elif pattern == "scales":
            _paint_scales(pixels, fx, fy, fw, fh, base_rgb, tex_w, tex_h)


def _paint_spots(pixels, x, y, w, h, base_rgb, tw, th, seed):
    rng = random.Random(seed)
    spot_color = _darken(base_rgb, 0.5)
    count = max(1, (w * h) // 18)
    for _ in range(count):
        sx = x + rng.randint(1, max(1, w - 2))
        sy = y + rng.randint(1, max(1, h - 2))
        r = rng.randint(1, max(1, min(w, h) // 4))
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx*dx + dy*dy <= r*r:
                    px, py = sx + dx, sy + dy
                    if 0 <= px < tw and 0 <= py < th:
                        pixels[py][px] = (*spot_color, 255)


def _paint_stripes(pixels, x, y, w, h, base_rgb, tw, th):
    stripe_color = _darken(base_rgb, 0.45)
    sw = max(1, min(w, h) // 5)
    for py in range(y, min(y + h, th)):
        for px in range(x, min(x + w, tw)):
            if 0 <= px < tw and 0 <= py < th:
                if ((px + py) // sw) % 2 == 0:
                    pixels[py][px] = (*stripe_color, 255)


def _paint_patches(pixels, x, y, w, h, base_rgb, tw, th, seed):
    rng = random.Random(seed)
    patch_color = _darken(base_rgb, 0.4)
    count = max(1, (w * h) // 25)
    for _ in range(count):
        cx = x + rng.randint(0, max(0, w - 1))
        cy = y + rng.randint(0, max(0, h - 1))
        r = rng.randint(1, max(1, min(w, h) // 3))
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if abs(dx) + abs(dy) <= r:
                    px, py = cx + dx, cy + dy
                    if 0 <= px < tw and 0 <= py < th:
                        pixels[py][px] = (*patch_color, 255)


def _paint_scales(pixels, x, y, w, h, base_rgb, tw, th):
    dark = _darken(base_rgb, 0.82)
    light = _lighten(base_rgb, 1.12)
    for py in range(y, min(y + h, th)):
        for px in range(x, min(x + w, tw)):
            if 0 <= px < tw and 0 <= py < th:
                if ((px // 2) + (py // 2)) % 2 == 0:
                    pixels[py][px] = (*dark, 255)
                elif (px + py) % 3 == 0:
                    pixels[py][px] = (*light, 255)


# ---------------------------------------------------------------------------
# Feature painters
# ---------------------------------------------------------------------------

def _paint_eyes(pixels, x, y, w, h, tw, th):
    """Paint 2-pixel eyes on a head front face."""
    if w < 4 or h < 4:
        return
    ey = y + h // 3
    lx = x + w // 3
    rx = x + (2 * w) // 3
    white = (255, 255, 255, 255)
    black = (20, 20, 20, 255)
    for ex in (lx, rx):
        for dy in range(min(2, th - ey)):
            for dx in range(min(2, tw - ex)):
                px, py = ex + dx, ey + dy
                if 0 <= px < tw and 0 <= py < th:
                    pixels[py][px] = white
        if 0 <= ex < tw and 0 <= ey < th:
            pixels[ey][ex] = black
    # Nose
    nx, ny = x + w // 2, ey + max(2, h // 4)
    if 0 <= nx < tw and 0 <= ny < th:
        pixels[ny][nx] = (60, 40, 30, 255)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_mob_texture(
    geometry_json: dict,
    display_name: str = "Custom Mob",
    color_rgb: Optional[list] = None,
    texture_hint: str = "",
    short_name: str = "custom_mob",
) -> str:
    """Generate a fully geometry-aware procedural texture.

    Reads every bone → cube → UV coordinate in the geometry and paints
    the texture atlas so every referenced pixel is covered with the
    correct body-part color, shading, and optional pattern.

    Returns base64 data URL (data:image/png;base64,...) or "".
    """
    if not geometry_json or "minecraft:geometry" not in geometry_json:
        return ""
    try:
        geom = geometry_json["minecraft:geometry"][0]
    except (IndexError, KeyError, TypeError):
        return ""

    desc = geom.get("description", {})
    tex_w = max(1, int(desc.get("texture_width", 64)))
    tex_h = max(1, int(desc.get("texture_height", 64)))
    bones = geom.get("bones", [])
    if not bones:
        return ""

    # Resolve base color
    if color_rgb and len(color_rgb) >= 3:
        base_rgb = (int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2]))
    else:
        base_rgb = _guess_base_color(display_name)

    pattern = _detect_pattern(display_name, texture_hint)

    # Role → color mapping
    role_colors = {
        "head":  _lighten(base_rgb, 1.10),
        "face":  _lighten(base_rgb, 1.05),
        "body":  base_rgb,
        "leg":   _darken(base_rgb, 0.75),
        "arm":   _darken(base_rgb, 0.80),
        "tail":  _darken(base_rgb, 0.85),
        "ear":   _lighten(base_rgb, 1.15),
    }

    # ── Step 1: Fill entire atlas with opaque base color ──
    # This guarantees NO transparent pixels anywhere. Even if a UV
    # region is missed, the mob won't have black/invisible patches.
    rng_base = random.Random(42)
    pixels = [
        [(*_noisy(base_rgb, 4, rng_base), 255) for _ in range(tex_w)]
        for _ in range(tex_h)
    ]

    # ── Step 2: Walk geometry and paint every face UV rect ──
    head_fronts = []     # for eye painting
    pattern_rects = []   # for pattern overlay

    for bone in bones:
        role = _classify_bone(bone.get("name", ""))
        bone_color = role_colors.get(role, base_rgb)

        for cube_idx, cube in enumerate(bone.get("cubes", [])):
            uv = cube.get("uv")
            size = cube.get("size")
            if uv is None or not size:
                continue

            # Determine face rects depending on UV format
            if isinstance(uv, dict):
                face_rects = _perface_uv_rects(uv, size)
            elif isinstance(uv, (list, tuple)) and len(uv) >= 2:
                iu, iv = int(round(uv[0])), int(round(uv[1]))
                iw = int(round(size[0])) if len(size) > 0 else 0
                ih = int(round(size[1])) if len(size) > 1 else 0
                id_ = int(round(size[2])) if len(size) > 2 else 0
                face_rects = _box_uv_faces(iu, iv, iw, ih, id_)
            else:
                continue

            # Paint each face
            seed = cube_idx * 31 + hash(bone.get("name", "")) % 10000
            for face_name, (fu, fv, fw, fh) in face_rects.items():
                if fw <= 0 or fh <= 0:
                    continue

                shade = _FACE_SHADE.get(face_name, 1.0)
                face_color = tuple(_clamp(c * shade) for c in bone_color)

                _fill_region(pixels, fu, fv, fw, fh,
                             face_color, tex_w, tex_h, seed + hash(face_name) % 1000)

                # Track for feature painting
                if role == "head" and face_name in ("front", "north"):
                    head_fronts.append((fu, fv, fw, fh))
                if role in ("body", "head", "tail"):
                    pattern_rects.append((fu, fv, fw, fh))

    # ── Step 3: Apply patterns over relevant UV regions ──
    _apply_pattern(pixels, pattern_rects, pattern, base_rgb, tex_w, tex_h)

    # ── Step 4: Paint features (eyes on head) ──
    for (fx, fy, fw, fh) in head_fronts:
        _paint_eyes(pixels, fx, fy, fw, fh, tex_w, tex_h)

    # ── Step 5: Encode PNG → base64 ──
    png_bytes = _make_png_from_pixels(tex_w, tex_h, pixels)
    b64 = base64.b64encode(png_bytes).decode('ascii')
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Pixel painting helpers
# ---------------------------------------------------------------------------

def _noisy(rgb: tuple, amount: int, rng: random.Random) -> tuple:
    """Return rgb with subtle per-pixel noise."""
    return tuple(_clamp(c + rng.randint(-amount, amount)) for c in rgb)


def _fill_region(pixels, x, y, w, h, rgb, tex_w, tex_h, seed=0):
    """Fill a rectangular UV region with color + subtle noise."""
    rng = random.Random(seed * 31 + x * 7 + y)
    for py in range(max(0, y), min(y + h, tex_h)):
        for px in range(max(0, x), min(x + w, tex_w)):
            noise = rng.randint(-5, 5)
            pixels[py][px] = (
                _clamp(rgb[0] + noise),
                _clamp(rgb[1] + noise),
                _clamp(rgb[2] + noise),
                255,
            )


# ---------------------------------------------------------------------------
# Color guessing from display name
# ---------------------------------------------------------------------------

def _guess_base_color(display_name: str) -> tuple:
    name = display_name.lower()
    _MAP = {
        "elephant": (140, 140, 130), "giraffe": (200, 170, 80),
        "tiger": (220, 150, 40),     "lion": (210, 170, 80),
        "bear": (100, 70, 40),       "polar bear": (230, 230, 235),
        "wolf": (160, 155, 150),     "fox": (210, 120, 40),
        "cat": (180, 140, 80),       "dog": (160, 120, 70),
        "horse": (140, 100, 60),     "cow": (160, 130, 90),
        "pig": (230, 170, 160),      "sheep": (220, 220, 215),
        "chicken": (210, 200, 180),  "duck": (200, 190, 50),
        "frog": (80, 160, 60),       "snake": (80, 120, 50),
        "spider": (60, 50, 45),      "dragon": (100, 40, 40),
        "fire": (200, 80, 20),       "ice": (150, 200, 230),
        "water": (60, 120, 200),     "shark": (120, 130, 145),
        "whale": (70, 90, 120),      "dolphin": (140, 160, 180),
        "bird": (100, 140, 180),     "parrot": (200, 60, 60),
        "penguin": (30, 30, 35),     "monkey": (130, 90, 50),
        "gorilla": (60, 55, 50),     "zombie": (80, 120, 80),
        "skeleton": (200, 200, 190), "creeper": (70, 160, 70),
        "enderman": (20, 20, 20),    "blaze": (230, 180, 40),
        "golem": (180, 175, 165),    "slime": (100, 200, 80),
        "phantom": (70, 80, 120),    "turtle": (70, 130, 60),
        "rabbit": (160, 140, 110),   "deer": (150, 120, 70),
        "moose": (100, 75, 45),      "crocodile": (80, 100, 50),
        "alligator": (70, 90, 45),   "rhino": (130, 125, 115),
        "hippo": (140, 120, 130),    "zebra": (220, 220, 215),
        "panda": (240, 240, 235),    "flamingo": (240, 150, 160),
        "owl": (140, 120, 80),       "bat": (60, 50, 50),
        "scorpion": (80, 60, 30),    "beetle": (40, 50, 30),
        "butterfly": (180, 100, 200),"bee": (220, 190, 50),
    }
    for key, color in _MAP.items():
        if key in name:
            return color
    return (140, 130, 120)
