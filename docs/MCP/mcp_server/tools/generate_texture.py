"""
Tool 3: generate_mob_texture — AI-informed pixel-art texture generation.
Uses GPT-4o to design a pixel color grid, then renders it to PNG with Pillow.
Falls back to algorithmic patterns if LLM parsing fails.
"""

import io
import json
import os
import base64
import random
from openai import OpenAI

from .bedrock_reference import GENERATE_TEXTURE_SYSTEM_PROMPT, STYLE_TEXTURE_SIZE, STYLE_GEOMETRY_MAP


MODEL_NAME = os.environ.get("MOB_FORGE_TEXTURE_MODEL") or os.environ.get("MOB_FORGE_MODEL") or "gpt-4o-mini"


def get_client() -> OpenAI:
    """Create OpenAI client configured for GitHub Models."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable is required.")
    return OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
    )


def hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color string to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


# Classify styles into body-plan families for the algorithmic fallback
_HUMANOID_STYLES = {
    "zombie", "skeleton", "creeper", "player", "villager", "witch",
    "piglin", "iron_golem", "snow_golem", "enderman", "wither_skeleton",
    "blaze", "vex",
}
_QUADRUPED_STYLES = {
    "cow", "pig", "sheep", "wolf", "horse", "llama", "fox", "cat",
    "goat", "polar_bear", "ravager", "hoglin", "sniffer", "camel",
    "turtle", "chicken", "rabbit", "frog", "strider",
}
_FLYING_STYLES = {"phantom", "bee", "parrot", "bat", "ghast"}
_AQUATIC_STYLES = {"squid", "dolphin", "guardian", "axolotl"}
_ARTHROPOD_STYLES = {"spider", "silverfish", "endermite"}
_SLIME_STYLES = {"slime"}


def generate_algorithmic_texture(
    width: int, height: int, colors: list[str], style: str
) -> list[list[str]]:
    """
    Fallback: generate a pixel grid algorithmically based on style and colors.
    Uses width x height (not square) to match the actual texture UV size.
    """
    if not colors:
        colors = ["#4A7023", "#2E4F1E", "#1A2E0F"]

    grid = []
    primary = colors[0]
    secondary = colors[1] if len(colors) > 1 else colors[0]
    accent = colors[2] if len(colors) > 2 else colors[0]
    dark = _darken(primary, 0.5)

    # Determine body-plan family
    if style in _HUMANOID_STYLES:
        family = "humanoid"
    elif style in _QUADRUPED_STYLES:
        family = "quadruped"
    elif style in _FLYING_STYLES:
        family = "flying"
    elif style in _AQUATIC_STYLES:
        family = "aquatic"
    elif style in _ARTHROPOD_STYLES:
        family = "spider"
    elif style in _SLIME_STYLES:
        family = "slime"
    else:
        family = "quadruped"  # safe default

    for y in range(height):
        row = []
        for x in range(width):
            # Outline
            if x == 0 or x == width - 1 or y == 0 or y == height - 1:
                row.append(dark)
            elif family == "humanoid":
                row.append(_biped_pattern(x, y, width, height, primary, secondary, accent))
            elif family == "quadruped":
                row.append(_quadruped_pattern(x, y, width, height, primary, secondary, accent))
            elif family == "flying":
                row.append(_dragon_pattern(x, y, width, height, primary, secondary, accent))
            elif family == "slime":
                row.append(_slime_pattern(x, y, width, height, primary, secondary, accent))
            elif family == "spider":
                row.append(_spider_pattern(x, y, width, height, primary, secondary, accent))
            elif family == "aquatic":
                row.append(_aquatic_pattern(x, y, width, height, primary, secondary, accent))
            else:
                row.append(primary if (x + y) % 2 == 0 else secondary)
        grid.append(row)
    return grid


def _biped_pattern(x, y, w, h, primary, secondary, accent):
    midx = w // 2
    # Head region (top quarter)
    if y < h // 4:
        # Eyes
        if y == h // 5 and (x == midx - 2 or x == midx + 1):
            return accent
        return secondary
    # Body (middle half)
    elif y < 3 * h // 4:
        return primary if abs(x - midx) < w // 3 else secondary
    # Legs (bottom quarter)
    else:
        return secondary if abs(x - midx) < w // 4 else primary


def _quadruped_pattern(x, y, w, h, primary, secondary, accent):
    midx = w // 2
    # Head (top quarter)
    if y < h // 4:
        if y == h // 6 and (x == midx - 2 or x == midx + 1):
            return accent  # eyes
        if y == h // 5 and midx - 1 <= x <= midx:
            return _darken(primary, 0.6)  # nose
        return secondary
    # Body (middle half)
    elif y < 3 * h // 4:
        # Slight shading variation
        if y % 4 == 0:
            return _darken(primary, 0.9)
        return primary
    # Legs (bottom quarter)
    else:
        lw = w // 6
        if (x < lw * 2 or x >= w - lw * 2) and y > 7 * h // 8:
            return secondary
        return primary


def _dragon_pattern(x, y, w, h, primary, secondary, accent):
    midx = w // 2
    if y < h // 4:
        # Head with horns
        if y < h // 8 and (x < w // 4 or x >= 3 * w // 4):
            return accent
        if y == h // 5 and (x == midx - 2 or x == midx + 1):
            return "#FF0000"  # Red eyes
        return secondary
    elif y < 3 * h // 4:
        # Wings pattern
        if abs(x - midx) > w // 3:
            return accent if y % 2 == 0 else _darken(accent, 0.7)
        return primary
    else:
        return secondary


def _slime_pattern(x, y, w, h, primary, secondary, accent):
    midx, midy = w // 2, h // 2
    dist = ((x - midx) ** 2 + (y - midy) ** 2) ** 0.5
    radius = min(midx, midy)
    if dist > radius - 1:
        return _darken(primary, 0.3)
    if y == midy - 2 and (x == midx - 2 or x == midx + 1):
        return accent  # eyes
    if y == midy + 1 and midx - 2 <= x <= midx + 1:
        return _darken(primary, 0.5)  # mouth
    if dist < radius // 2:
        return _lighten(primary, 1.3)
    return primary


def _spider_pattern(x, y, w, h, primary, secondary, accent):
    midx = w // 2
    # Eyes (red cluster)
    if h // 4 <= y <= h // 4 + 1:
        if midx - 3 <= x <= midx + 2:
            return "#FF0000"
    # Body
    if abs(x - midx) < w // 3 and h // 5 < y < 4 * h // 5:
        return primary
    # Legs
    if y == h // 2 and (x < w // 4 or x >= 3 * w // 4):
        return secondary
    if y == h // 2 + 2 and (x < w // 3 or x >= 2 * w // 3):
        return secondary
    return _darken(primary, 0.3) if abs(x - midx) < w // 2 else primary


def _aquatic_pattern(x, y, w, h, primary, secondary, accent):
    midx = w // 2
    # Streamlined body shape
    if y < h // 4:
        # Head/face
        if y == h // 6 and (x == midx - 2 or x == midx + 1):
            return accent  # eyes
        return secondary
    elif y < 3 * h // 4:
        # Body — gradient shading
        if y % 3 == 0:
            return _lighten(primary, 1.1)
        return primary
    else:
        # Tail
        if abs(x - midx) < w // 4:
            return secondary
        return _darken(primary, 0.7)


def _darken(hex_color: str, factor: float) -> str:
    r, g, b = hex_to_rgb(hex_color)
    return "#{:02x}{:02x}{:02x}".format(
        int(r * factor), int(g * factor), int(b * factor)
    )


def _lighten(hex_color: str, factor: float) -> str:
    r, g, b = hex_to_rgb(hex_color)
    return "#{:02x}{:02x}{:02x}".format(
        min(255, int(r * factor)),
        min(255, int(g * factor)),
        min(255, int(b * factor)),
    )


def render_grid_to_png(grid: list[list[str]], scale: int = 1) -> bytes:
    """Render a 2D hex color grid to a PNG image."""
    from PIL import Image

    height = len(grid)
    width = len(grid[0]) if grid else 0

    img = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))

    for y, row in enumerate(grid):
        for x, color in enumerate(row):
            if not color or color == "#00000000":
                rgba = (0, 0, 0, 0)
            else:
                rgb = hex_to_rgb(color)
                rgba = rgb + (255,)
            for sy in range(scale):
                for sx in range(scale):
                    img.putpixel((x * scale + sx, y * scale + sy), rgba)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def generate_mob_texture(
    mob_name: str,
    description: str = "",
    style: str = "zombie",
    colors: list[str] | None = None,
    size: int = 16,
) -> str:
    """
    Generate a pixel-art texture for a Minecraft mob.

    Args:
        mob_name: Name of the mob (for context)
        description: Description of the mob's appearance
        style: Body style — any key from STYLE_GEOMETRY_MAP (e.g. "polar_bear", "phantom")
        colors: List of hex color strings for the palette (e.g., ["#FF4400", "#FFaa00"])
        size: Ignored (kept for backwards compat). Actual size comes from STYLE_TEXTURE_SIZE.

    Returns:
        JSON with base64-encoded PNG and dimensions.
    """
    # Validate style against the expanded style map
    if style not in STYLE_GEOMETRY_MAP:
        style = "zombie"  # safe default
    if not colors:
        colors = ["#4A7023", "#2E4F1E", "#1A2E0F"]

    # Get correct texture dimensions for this style
    tex_w, tex_h = STYLE_TEXTURE_SIZE.get(style, (64, 64))

    grid = None

    # Try AI-generated texture first
    try:
        client = get_client()
        prompt = GENERATE_TEXTURE_SYSTEM_PROMPT.format(width=tex_w, height=tex_h)
        user_msg = (
            f"Mob: {mob_name}\n"
            f"Description: {description or mob_name}\n"
            f"Style: {style}\n"
            f"Color palette: {json.dumps(colors)}\n"
            f"Texture size: {tex_w}x{tex_h} (width x height)\n"
            f"Generate the pixel grid with exactly {tex_h} rows and {tex_w} columns.\n"
            f"Output ONLY JSON."
        )

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.8,
            max_tokens=16384,
        )

        raw = response.choices[0].message.content.strip()
        # Strip code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw = "\n".join(lines)

        parsed = json.loads(raw)
        ai_grid = parsed.get("grid", [])

        # Validate grid dimensions (height rows × width columns)
        if len(ai_grid) == tex_h and all(len(row) == tex_w for row in ai_grid):
            grid = ai_grid
    except Exception:
        pass  # Fall back to algorithmic

    # Fallback to algorithmic generation
    if grid is None:
        grid = generate_algorithmic_texture(tex_w, tex_h, colors, style)

    # Render to PNG — scale=1 since we're already at real texture size
    png_bytes = render_grid_to_png(grid, scale=1)
    encoded = base64.b64encode(png_bytes).decode("utf-8")

    result = {
        "status": "success",
        "mob_name": mob_name,
        "texture_base64": encoded,
        "width": tex_w,
        "height": tex_h,
        "style": style,
        "ai_generated": grid is not None,
    }

    return json.dumps(result)
