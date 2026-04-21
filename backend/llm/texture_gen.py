"""Geometry-aware procedural texture generator for Minecraft Bedrock mobs.

Generates textures by reading the ACTUAL geometry UV map — every bone,
every cube, every face's exact UV coordinates — and painting the texture
atlas pixel-by-pixel against that map.

Pipeline:
  1. Fill entire atlas with opaque base color (no transparent gaps)
  2. Walk geometry: bone -> cube -> compute all 6 face UV rects
  3. Paint each face rect with role-specific color + per-face shading
  4. Overlay patterns (spots, stripes, etc.) on painted UV regions only
  5. Paint features (eyes, mouth on head front face)
  6. Encode to PNG -> base64 data URL

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
# PNG encoder
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
        row_bytes = b'\x00'
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


def _hue_shift(rgb: tuple, degrees: float) -> tuple:
    """Shift hue by rotating RGB channels through HSV space."""
    r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    diff = mx - mn
    if diff < 0.001:
        return rgb
    if mx == r:
        h = 60.0 * (((g - b) / diff) % 6)
    elif mx == g:
        h = 60.0 * (((b - r) / diff) + 2)
    else:
        h = 60.0 * (((r - g) / diff) + 4)
    s = diff / mx if mx > 0 else 0
    v = mx
    h = (h + degrees) % 360
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if h < 60:
        r2, g2, b2 = c, x, 0
    elif h < 120:
        r2, g2, b2 = x, c, 0
    elif h < 180:
        r2, g2, b2 = 0, c, x
    elif h < 240:
        r2, g2, b2 = 0, x, c
    elif h < 300:
        r2, g2, b2 = x, 0, c
    else:
        r2, g2, b2 = c, 0, x
    return (_clamp((r2 + m) * 255), _clamp((g2 + m) * 255), _clamp((b2 + m) * 255))


def _generate_palette(base_rgb: tuple) -> dict:
    """Generate a multi-color palette from a base color.

    Returns distinct colors for different body roles so the mob doesn't
    look like a single-colored blob.
    """
    belly = _lighten(base_rgb, 1.35)
    belly = _blend(belly, (230, 220, 200), 0.3)

    accent = _hue_shift(base_rgb, 30)
    accent = _lighten(accent, 1.1)

    membrane = _blend(base_rgb, (180, 140, 100), 0.4)
    membrane = _lighten(membrane, 1.15)

    return {
        "head":  _lighten(base_rgb, 1.08),
        "face":  _lighten(base_rgb, 1.04),
        "body":  base_rgb,
        "belly": belly,
        "leg":   _darken(base_rgb, 0.78),
        "arm":   membrane,
        "tail":  _darken(accent, 0.85),
        "ear":   _lighten(accent, 1.15),
    }


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
# Face shading multipliers
# ---------------------------------------------------------------------------

_FACE_SHADE = {
    "top":    1.12,
    "front":  1.0,
    "right":  0.90,
    "back":   0.82,
    "left":   0.86,
    "bottom": 0.72,
    "north":  1.0,
    "south":  0.82,
    "east":   0.90,
    "west":   0.86,
    "up":     1.12,
    "down":   0.72,
}


# ---------------------------------------------------------------------------
# Bedrock Box UV layout
# ---------------------------------------------------------------------------

def _box_uv_faces(u: int, v: int, w: int, h: int, d: int) -> dict:
    """Compute all 6 face UV rects for Bedrock **box** UV (uv: [u, v]).

    Names match Bedrock cardinals: north = face toward -Z (entity front when modeled
    correctly), south = +Z, east = +X, west = -X, up/down = ±Y. Layout matches
    `frontend/js/viewer/viewer3d.js` applyBoxUV (Three.js +X,-X,+Y,-Y,+Z,-Z order).
    """
    w = max(w, 0)
    h = max(h, 0)
    d = max(d, 0)
    return {
        "up":    (u + d,       v,       w, d),
        "down":  (u + d + w,   v,       w, d),
        "east":  (u,           v + d,   d, h),
        "north": (u + d,       v + d,   w, h),
        "west":  (u + d + w,   v + d,   d, h),
        "south": (u + 2*d + w, v + d,   w, h),
    }


# ---------------------------------------------------------------------------
# Per-face UV dict handling
# ---------------------------------------------------------------------------

def _perface_uv_rects(uv_dict: dict, cube_size: list) -> dict:
    """Extract face rects from per-face UV format."""
    w = int(cube_size[0]) if len(cube_size) > 0 else 0
    h = int(cube_size[1]) if len(cube_size) > 1 else 0
    d = int(cube_size[2]) if len(cube_size) > 2 else 0

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
        if len(fsize) > 0 and fsize[0] < 0:
            fu += int(fsize[0])
        if len(fsize) > 1 and fsize[1] < 0:
            fv += int(fsize[1])
        faces[face_key] = (fu, fv, fw, fh)
    return faces


# ---------------------------------------------------------------------------
# Texture instruction parsing
# ---------------------------------------------------------------------------

_COLOR_WORDS: dict[str, tuple] = {
    "red": (200, 40, 40), "dark red": (140, 20, 20), "light red": (230, 100, 100),
    "bright red": (240, 50, 50),
    "blue": (40, 80, 200), "dark blue": (20, 40, 140), "light blue": (120, 170, 230),
    "bright blue": (50, 100, 240),
    "green": (40, 160, 40), "dark green": (20, 100, 20), "light green": (120, 210, 120),
    "bright green": (50, 220, 50),
    "yellow": (220, 210, 40), "gold": (210, 175, 30), "orange": (220, 130, 30),
    "purple": (130, 40, 180), "pink": (220, 140, 170), "magenta": (180, 40, 140),
    "brown": (120, 75, 35), "dark brown": (70, 40, 20), "light brown": (170, 130, 80),
    "black": (25, 25, 25), "white": (240, 240, 240), "gray": (140, 140, 140),
    "grey": (140, 140, 140), "dark gray": (80, 80, 80), "light gray": (200, 200, 200),
    "cyan": (40, 190, 200), "teal": (40, 150, 150),
    "crimson": (160, 20, 30), "scarlet": (200, 30, 30), "ivory": (230, 225, 210),
    "silver": (190, 190, 200), "tan": (200, 170, 120), "olive": (120, 130, 40),
}

_ROLE_ALIASES: dict[str, str] = {
    "legs": "leg", "arms": "arm", "tails": "tail", "ears": "ear",
    "wings": "arm", "wing": "arm", "claws": "arm",
    "feet": "leg", "paws": "leg", "hooves": "leg",
    "horns": "face", "snout": "face", "fangs": "face", "jaw": "face",
    "torso": "body", "chest": "body", "belly": "body", "back": "body",
}


def _parse_hex_color(text: str) -> Optional[tuple]:
    import re
    m = re.search(r'#([0-9a-fA-F]{6})\b', text)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.search(r'#([0-9a-fA-F]{3})\b', text)
    if m:
        h = m.group(1)
        return (int(h[0]*2, 16), int(h[1]*2, 16), int(h[2]*2, 16))
    return None


def _find_color_in_text(text: str) -> Optional[tuple]:
    hex_color = _parse_hex_color(text)
    if hex_color:
        return hex_color
    for cname in sorted(_COLOR_WORDS, key=len, reverse=True):
        if cname in text:
            return _COLOR_WORDS[cname]
    return None


def _parse_texture_instructions(
    instructions: Optional[list],
) -> tuple[dict[str, tuple], list[str]]:
    """Parse texture_instructions into per-role color overrides and patterns."""
    if not instructions:
        return {}, []

    expanded: list[str] = []
    for instr in instructions:
        if not isinstance(instr, str):
            continue
        parts = [p.strip() for p in instr.split(",")]
        if len(parts) > 1:
            expanded.extend(p for p in parts if p)
        else:
            expanded.append(instr)

    role_overrides: dict[str, tuple] = {}
    extra_patterns: list[str] = []
    canonical_roles = set(_ROLE_KEYWORDS.keys())

    for instr in expanded:
        if not isinstance(instr, str):
            continue
        text = instr.strip().lower()
        if not text:
            continue
        color = _find_color_in_text(text)
        found_roles: list[str] = []
        for role in canonical_roles:
            if role in text:
                found_roles.append(role)
        for alias, canonical in _ROLE_ALIASES.items():
            if alias in text and canonical not in found_roles:
                found_roles.append(canonical)
        if color and found_roles:
            for role in found_roles:
                role_overrides[role] = color
        elif not found_roles:
            extra_patterns.append(text)

    return role_overrides, extra_patterns


# ---------------------------------------------------------------------------
# Pattern detection & application
# ---------------------------------------------------------------------------

def _detect_patterns(display_name: str, texture_hint: str,
                     extra_keywords: Optional[list] = None) -> list[str]:
    text = f"{display_name} {texture_hint}".lower()
    if extra_keywords:
        text += " " + " ".join(extra_keywords)

    patterns = []
    if any(w in text for w in ["giraffe", "leopard", "cheetah", "dalmatian",
                                "spotted", "dotted", "freckled"]):
        patterns.append("spots")
    if any(w in text for w in ["tiger", "zebra", "striped", "bee", "wasp", "banded"]):
        patterns.append("stripes")
    if any(w in text for w in ["cow", "patched", "piebald", "pinto",
                                "mossy", "cracked"]):
        patterns.append("patches")
    if any(w in text for w in ["snake", "lizard", "dragon", "reptile", "scales",
                                "crocodile", "alligator"]):
        patterns.append("scales")
    if any(w in text for w in ["fur", "furry", "fluffy", "fuzzy", "hairy"]):
        patterns.append("fur")
    if any(w in text for w in ["glow", "glowing", "magma", "lava", "ember",
                                "neon", "luminous"]):
        patterns.append("glow")
    if any(w in text for w in ["rocky", "stone", "rock", "cobble", "granite",
                                "gravel"]):
        patterns.append("rocky")
    return patterns


def _apply_patterns(pixels, rects, patterns: list[str], base_rgb, tex_w, tex_h):
    for pattern in patterns:
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
            elif pattern == "fur":
                _paint_fur(pixels, fx, fy, fw, fh, base_rgb, tex_w, tex_h, seed)
            elif pattern == "glow":
                _paint_glow(pixels, fx, fy, fw, fh, base_rgb, tex_w, tex_h)
            elif pattern == "rocky":
                _paint_rocky(pixels, fx, fy, fw, fh, base_rgb, tex_w, tex_h, seed)


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


def _paint_fur(pixels, x, y, w, h, base_rgb, tw, th, seed):
    rng = random.Random(seed)
    light = _lighten(base_rgb, 1.15)
    dark = _darken(base_rgb, 0.80)
    for py in range(y, min(y + h, th)):
        for px in range(x, min(x + w, tw)):
            if 0 <= px < tw and 0 <= py < th:
                v = rng.random()
                if v < 0.15:
                    pixels[py][px] = (*light, 255)
                elif v < 0.30:
                    pixels[py][px] = (*dark, 255)


def _paint_glow(pixels, x, y, w, h, base_rgb, tw, th):
    cx, cy = x + w // 2, y + h // 2
    max_dist = math.sqrt((w / 2) ** 2 + (h / 2) ** 2) or 1
    glow_color = _lighten(base_rgb, 1.5)
    for py in range(y, min(y + h, th)):
        for px in range(x, min(x + w, tw)):
            if 0 <= px < tw and 0 <= py < th:
                dist = math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
                t = 1.0 - min(dist / max_dist, 1.0)
                if t > 0.3:
                    blended = _blend(base_rgb, glow_color, t * 0.6)
                    pixels[py][px] = (*blended, 255)


def _paint_rocky(pixels, x, y, w, h, base_rgb, tw, th, seed):
    rng = random.Random(seed)
    dark = _darken(base_rgb, 0.55)
    mid = _darken(base_rgb, 0.75)
    count = max(2, (w * h) // 12)
    for _ in range(count):
        sx = x + rng.randint(0, max(0, w - 1))
        sy = y + rng.randint(0, max(0, h - 1))
        size = rng.randint(1, max(1, min(w, h) // 4))
        color = dark if rng.random() < 0.5 else mid
        for dy in range(-size, size + 1):
            for dx in range(-size, size + 1):
                if rng.random() < 0.7 and abs(dx) + abs(dy) <= size + 1:
                    px, py_ = sx + dx, sy + dy
                    if 0 <= px < tw and 0 <= py_ < th:
                        pixels[py_][px] = (*color, 255)


# ---------------------------------------------------------------------------
# Feature painters — eyes, mouth, nose proportional to face size
# ---------------------------------------------------------------------------

def _paint_eyes(pixels, x, y, w, h, tw, th):
    """Paint proportionally-sized eyes with iris, pupil, and highlight.

    All draws are clipped to the north-face rectangle [x,y]+[w,h]. Previously
    we only clipped to the full atlas, so features could spill into the UV
    island below (often the head's *down* face), which looked like a second
    pair of eyes on the underside in-game.
    """
    if w < 4 or h < 4:
        return

    def _on_face(px: int, py: int) -> bool:
        return x <= px < x + w and y <= py < y + h and 0 <= px < tw and 0 <= py < th

    eye_size = max(2, min(w // 5, h // 4))
    eye_y = y + h // 3

    left_eye_x = x + w // 4 - eye_size // 2
    right_eye_x = x + (3 * w) // 4 - eye_size // 2

    white = (255, 255, 255)
    iris_color = (60, 40, 20)
    pupil_color = (10, 10, 10)
    highlight = (240, 240, 255)

    for ex_start in (left_eye_x, right_eye_x):
        # White sclera
        for dy in range(eye_size):
            for dx in range(eye_size):
                px = ex_start + dx
                py = eye_y + dy
                if _on_face(px, py):
                    pixels[py][px] = (*white, 255)

        # Iris (centered, slightly smaller)
        iris_size = max(1, eye_size * 2 // 3)
        iris_x = ex_start + (eye_size - iris_size) // 2
        iris_y = eye_y + (eye_size - iris_size) // 2
        for dy in range(iris_size):
            for dx in range(iris_size):
                px = iris_x + dx
                py = iris_y + dy
                if _on_face(px, py):
                    pixels[py][px] = (*iris_color, 255)

        # Pupil (center dot)
        pupil_size = max(1, iris_size // 2)
        pupil_x = iris_x + (iris_size - pupil_size) // 2
        pupil_y = iris_y + (iris_size - pupil_size) // 2
        for dy in range(pupil_size):
            for dx in range(pupil_size):
                px = pupil_x + dx
                py = pupil_y + dy
                if _on_face(px, py):
                    pixels[py][px] = (*pupil_color, 255)

        # Highlight (top-right pixel of each eye)
        hx = ex_start + eye_size - max(1, eye_size // 3)
        hy = eye_y + max(0, eye_size // 4)
        if _on_face(hx, hy):
            pixels[hy][hx] = (*highlight, 255)

    # Nose/nostrils centered below eyes
    nose_y = eye_y + eye_size + max(1, h // 6)
    nose_w = max(2, w // 6)
    nose_color = (50, 35, 30)
    for dx in range(nose_w):
        nx = x + w // 2 - nose_w // 2 + dx
        if _on_face(nx, nose_y):
            pixels[nose_y][nx] = (*nose_color, 255)

    # Mouth line
    mouth_y = nose_y + max(1, h // 8)
    mouth_w = max(2, w // 3)
    mouth_color = (40, 25, 25)
    if mouth_y < y + h - 1:
        for dx in range(mouth_w):
            mx = x + w // 2 - mouth_w // 2 + dx
            if _on_face(mx, mouth_y):
                pixels[mouth_y][mx] = (*mouth_color, 255)


# ---------------------------------------------------------------------------
# Shading helpers
# ---------------------------------------------------------------------------

def _fill_region_shaded(pixels, x, y, w, h, rgb, tex_w, tex_h, seed=0,
                        face_name="front"):
    """Fill a rectangular UV region with gradient shading and edge darkening."""
    rng = random.Random(seed * 31 + x * 7 + y)
    edge_dark = _darken(rgb, 0.65)

    is_top = face_name in ("top", "up")
    is_bottom = face_name in ("bottom", "down")

    for py_idx in range(max(0, y), min(y + h, tex_h)):
        for px_idx in range(max(0, x), min(x + w, tex_w)):
            local_x = px_idx - x
            local_y = py_idx - y

            # Edge darkening (1-2px border)
            dist_to_edge = min(local_x, local_y, w - 1 - local_x, h - 1 - local_y)
            if dist_to_edge <= 0 and w > 4 and h > 4:
                pixels[py_idx][px_idx] = (*edge_dark, 255)
                continue

            # Vertical gradient: lighter at top, darker at bottom
            v_ratio = local_y / max(1, h - 1)
            if is_bottom:
                grad_factor = 0.85
            elif is_top:
                grad_factor = 1.05
            else:
                grad_factor = 1.08 - (v_ratio * 0.2)

            noise = rng.randint(-6, 6)
            pixels[py_idx][px_idx] = (
                _clamp(rgb[0] * grad_factor + noise),
                _clamp(rgb[1] * grad_factor + noise),
                _clamp(rgb[2] * grad_factor + noise),
                255,
            )


def _fill_belly_shading(pixels, x, y, w, h, body_color, belly_color,
                        tex_w, tex_h, seed=0):
    """Fill a body face with two-tone belly shading (lighter bottom half)."""
    rng = random.Random(seed)
    for py_idx in range(max(0, y), min(y + h, tex_h)):
        for px_idx in range(max(0, x), min(x + w, tex_w)):
            local_y = py_idx - y
            v_ratio = local_y / max(1, h - 1)

            if v_ratio > 0.55:
                t = (v_ratio - 0.55) / 0.45
                color = _blend(body_color, belly_color, min(t, 1.0))
            else:
                color = body_color

            noise = rng.randint(-5, 5)
            pixels[py_idx][px_idx] = (
                _clamp(color[0] + noise),
                _clamp(color[1] + noise),
                _clamp(color[2] + noise),
                255,
            )


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_mob_texture(
    geometry_json: dict,
    display_name: str = "Custom Mob",
    color_rgb: Optional[list] = None,
    texture_hint: str = "",
    short_name: str = "custom_mob",
    texture_instructions: Optional[list] = None,
) -> str:
    """Generate a geometry-aware procedural texture with proper shading,
    distinct body-part colors, proportional eyes, and edge detail.

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

    if color_rgb and len(color_rgb) >= 3:
        base_rgb = (int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2]))
    else:
        base_rgb = _guess_base_color(display_name)

    role_overrides, extra_patterns = _parse_texture_instructions(texture_instructions)
    patterns = _detect_patterns(display_name, texture_hint, extra_patterns)

    palette = _generate_palette(base_rgb)
    for role, color in role_overrides.items():
        palette[role] = color

    # Step 1: Fill atlas with noisy base color (no transparent pixels)
    rng_base = random.Random(42)
    pixels = [
        [(*_noisy(base_rgb, 4, rng_base), 255) for _ in range(tex_w)]
        for _ in range(tex_h)
    ]

    # Step 2: Walk geometry and paint each face UV rect
    head_fronts = []
    pattern_rects = []

    for bone in bones:
        role = _classify_bone(bone.get("name", ""))
        bone_color = palette.get(role, base_rgb)

        for cube_idx, cube in enumerate(bone.get("cubes", [])):
            uv = cube.get("uv")
            size = cube.get("size")
            if uv is None or not size:
                continue

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

            seed = cube_idx * 31 + hash(bone.get("name", "")) % 10000
            for face_name, (fu, fv, fw, fh) in face_rects.items():
                if fw <= 0 or fh <= 0:
                    continue

                shade = _FACE_SHADE.get(face_name, 1.0)
                face_color = tuple(_clamp(c * shade) for c in bone_color)

                is_body_underside = (
                    role == "body"
                    and face_name in ("bottom", "down")
                )
                is_body_front = (
                    role == "body"
                    and face_name == "north"
                )

                if is_body_underside:
                    _fill_region_shaded(
                        pixels, fu, fv, fw, fh,
                        palette.get("belly", _lighten(base_rgb, 1.3)),
                        tex_w, tex_h, seed, face_name,
                    )
                elif is_body_front:
                    _fill_belly_shading(
                        pixels, fu, fv, fw, fh,
                        face_color, palette.get("belly", _lighten(base_rgb, 1.3)),
                        tex_w, tex_h, seed,
                    )
                else:
                    _fill_region_shaded(
                        pixels, fu, fv, fw, fh, face_color,
                        tex_w, tex_h, seed + hash(face_name) % 1000,
                        face_name,
                    )

                # Bedrock north = -Z (muzzle direction). Do not treat legacy "front"
                # as a separate slot — box UV now emits "north" only for that face.
                if role == "head" and face_name == "north":
                    head_fronts.append((fu, fv, fw, fh))
                if role in ("body", "head", "tail"):
                    pattern_rects.append((fu, fv, fw, fh))

    # Step 3: Patterns
    _apply_patterns(pixels, pattern_rects, patterns, base_rgb, tex_w, tex_h)

    # Step 4: Eyes and facial features — single largest head north face only.
    # Multiple head cubes (snout, ears) would otherwise duplicate eyes on side UVs.
    if head_fronts:
        fx, fy, fw, fh = max(head_fronts, key=lambda r: r[2] * r[3])
        _paint_eyes(pixels, fx, fy, fw, fh, tex_w, tex_h)

    # Step 5: Encode
    png_bytes = _make_png_from_pixels(tex_w, tex_h, pixels)
    b64 = base64.b64encode(png_bytes).decode('ascii')
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noisy(rgb: tuple, amount: int, rng: random.Random) -> tuple:
    return tuple(_clamp(c + rng.randint(-amount, amount)) for c in rgb)


# ---------------------------------------------------------------------------
# Color guessing — returns multi-tone base colors for known mob types
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
        "spider": (60, 50, 45),      "dragon": (160, 40, 40),
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
        "unicorn": (240, 235, 245),  "phoenix": (230, 100, 20),
        "griffin": (180, 150, 90),    "wyvern": (100, 60, 80),
        "dinosaur": (100, 130, 70),  "raptor": (90, 110, 60),
        "charizard": (230, 130, 40), "pikachu": (240, 210, 60),
    }
    for key, color in _MAP.items():
        if key in name:
            return color
    return (140, 130, 120)
