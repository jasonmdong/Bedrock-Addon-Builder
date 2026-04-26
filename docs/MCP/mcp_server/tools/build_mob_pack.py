"""
Tool 2: build_mob_pack — Takes one or more mob specs and generates
a downloadable .mcpack ZIP (behavior pack with entity definitions).
"""

import io
import json
import base64
import zipfile

from .bedrock_reference import (
    generate_linked_manifests,
    generate_client_entity,
    generate_lang_file,
    generate_spawn_rules,
)


async def build_mob_pack(mobs: list[dict], pack_name: str = "custom_mobs") -> str:
    """
    Build .mcpack files from one or more mob entity specs.

    Generates TWO .mcpack files (behavior pack + resource pack) that are
    cross-linked via UUID dependencies so Minecraft loads both together.

    The behavior pack contains:
      - manifest.json (with dependency on RP)
      - entities/<mob>.json (server-side entity definition)
      - spawn_rules/<mob>.json (so mobs can spawn)

    The resource pack contains:
      - manifest.json (with dependency on BP)
      - entity/<mob>.entity.json (client entity: geometry, texture, materials)
      - textures/entity/<mob>.png (mob texture)
      - texts/en_US.lang (display names for entities and spawn eggs)

    Args:
        mobs: List of mob objects, each containing "entity" (the Bedrock entity JSON)
              and optionally "metadata" and "texture_base64" (PNG texture data).
        pack_name: Name for the addon pack (used in manifests and filename).

    Returns:
        JSON with base64-encoded .mcpack files and filenames.
    """
    # Sanitize pack name
    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in pack_name)

    # Generate cross-linked manifests (BP depends on RP and vice versa)
    bp_manifest, rp_manifest = generate_linked_manifests(pack_name)

    # Collect mob info for lang file
    lang_entries: list[tuple[str, str]] = []

    # ── Behavior Pack ─────────────────────────────────────────────────
    bp_buffer = io.BytesIO()

    with zipfile.ZipFile(bp_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(bp_manifest, indent=2))
        zf.writestr("pack_icon.png", _create_pack_icon())

        for mob in mobs:
            entity_data = mob.get("entity", mob)
            metadata = mob.get("metadata", {})

            mc_entity = entity_data.get("minecraft:entity", {})
            identifier = mc_entity.get("description", {}).get(
                "identifier", "custom:unknown_mob"
            )
            mob_name = identifier.split(":")[-1]
            display_name = metadata.get("display_name", mob_name.replace("_", " ").title())
            lang_entries.append((identifier, display_name))

            # Entity behavior definition
            zf.writestr(
                f"entities/{mob_name}.json",
                json.dumps(entity_data, indent=2),
            )

            # Spawn rules so the mob can spawn naturally and via /summon
            spawn_rules = generate_spawn_rules(identifier)
            zf.writestr(
                f"spawn_rules/{mob_name}.json",
                json.dumps(spawn_rules, indent=2),
            )

            # Loot table for item drops on death
            loot_drops = metadata.get("loot_drops", [])
            loot_table = _build_loot_table(loot_drops, mob_name)
            zf.writestr(
                f"loot_tables/entities/{mob_name}.json",
                json.dumps(loot_table, indent=2),
            )

    # ── Resource Pack ─────────────────────────────────────────────────
    rp_buffer = io.BytesIO()

    with zipfile.ZipFile(rp_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(rp_manifest, indent=2))
        zf.writestr("pack_icon.png", _create_pack_icon())

        # Language file (entity names + spawn egg names)
        lang_content = generate_lang_file(lang_entries)
        zf.writestr("texts/en_US.lang", lang_content)

        for mob in mobs:
            entity_data = mob.get("entity", mob)
            metadata = mob.get("metadata", {})
            texture_b64 = mob.get("texture_base64", None)
            geometry_data = mob.get("geometry_data", None)

            mc_entity = entity_data.get("minecraft:entity", {})
            identifier = mc_entity.get("description", {}).get(
                "identifier", "custom:unknown_mob"
            )
            mob_name = identifier.split(":")[-1]

            # Determine geometry ID — prefer custom geometry, fall back to vanilla
            style = metadata.get("suggested_style", "zombie")
            if geometry_data:
                # Extract the custom geometry ID from the geometry JSON
                geos = geometry_data.get("minecraft:geometry", [])
                if geos:
                    geometry_id = geos[0].get("description", {}).get(
                        "identifier", f"geometry.{mob_name}"
                    )
                else:
                    geometry_id = f"geometry.{mob_name}"

                # Write the custom geometry model file
                zf.writestr(
                    f"models/entity/{mob_name}.geo.json",
                    json.dumps(geometry_data, indent=2),
                )
            else:
                # No custom geometry — use vanilla geometry from style map
                geometry_id = None  # generate_client_entity will handle it

            # Client entity definition (geometry, texture path, materials)
            if geometry_id:
                # Build client entity with the custom geometry ID
                client_entity = _build_client_entity(identifier, mob_name, geometry_id)
            else:
                client_entity = generate_client_entity(identifier, mob_name, style)

            # Spawn egg colors from metadata
            if metadata.get("suggested_colors"):
                colors = metadata["suggested_colors"]
                ce_desc = client_entity["minecraft:client_entity"]["description"]
                ce_desc["spawn_egg"]["base_color"] = colors[0] if len(colors) > 0 else "#4A7023"
                ce_desc["spawn_egg"]["overlay_color"] = colors[1] if len(colors) > 1 else "#2E4F1E"

            zf.writestr(
                f"entity/{mob_name}.entity.json",
                json.dumps(client_entity, indent=2),
            )

            # Texture file
            if texture_b64:
                try:
                    texture_bytes = base64.b64decode(texture_b64)
                    zf.writestr(f"textures/entity/{mob_name}.png", texture_bytes)
                except Exception:
                    zf.writestr(f"textures/entity/{mob_name}.png", _create_placeholder_texture(style))
            else:
                zf.writestr(f"textures/entity/{mob_name}.png", _create_placeholder_texture(style))

    # Return both packs
    bp_bytes = bp_buffer.getvalue()
    rp_bytes = rp_buffer.getvalue()

    bp_encoded = base64.b64encode(bp_bytes).decode("utf-8")
    rp_encoded = base64.b64encode(rp_bytes).decode("utf-8")

    result = {
        "status": "success",
        "behavior_pack": {
            "filename": f"{safe_name}_BP.mcpack",
            "file_base64": bp_encoded,
            "size_bytes": len(bp_bytes),
        },
        "resource_pack": {
            "filename": f"{safe_name}_RP.mcpack",
            "file_base64": rp_encoded,
            "size_bytes": len(rp_bytes),
        },
        "mob_count": len(mobs),
    }

    return json.dumps(result)


def _build_loot_table(loot_drops: list, mob_name: str) -> dict:
    """Build a Bedrock loot table JSON from the _mob_forge_loot metadata.

    Args:
        loot_drops: List of dicts with item, count_min, count_max, chance.
        mob_name: Used as fallback if no drops are given.
    """
    pools = []
    if not loot_drops:
        # Default drop: 1-2 XP-like bones
        loot_drops = [{"item": "minecraft:bone", "count_min": 1, "count_max": 2, "chance": 1.0}]

    for drop in loot_drops:
        item = drop.get("item", "minecraft:bone")
        count_min = drop.get("count_min", 1)
        count_max = drop.get("count_max", 1)
        chance = drop.get("chance", 1.0)

        entry = {
            "type": "item",
            "name": item,
            "weight": 1,
        }
        # Add count function if more than 1
        if count_max > 1:
            entry["functions"] = [
                {"function": "set_count", "count": {"min": count_min, "max": count_max}}
            ]

        pool = {
            "rolls": 1,
            "entries": [entry],
        }
        # Add condition for chance < 1.0
        if chance < 1.0:
            pool["conditions"] = [
                {"condition": "random_chance", "chance": chance}
            ]

        pools.append(pool)

    return {"pools": pools}


def _build_client_entity(identifier: str, mob_name: str, geometry_id: str) -> dict:
    """Build a client entity definition pointing to a custom geometry ID."""
    return {
        "format_version": "1.10.0",
        "minecraft:client_entity": {
            "description": {
                "identifier": identifier,
                "materials": {"default": "entity_alphatest"},
                "textures": {
                    "default": f"textures/entity/{mob_name}"
                },
                "geometry": {
                    "default": geometry_id
                },
                "render_controllers": ["controller.render.default"],
                "spawn_egg": {
                    "base_color": "#4A7023",
                    "overlay_color": "#2E4F1E"
                }
            }
        }
    }


def _create_pack_icon() -> bytes:
    """Create a simple 64x64 pack icon PNG."""
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), (40, 40, 60, 255))
        draw = ImageDraw.Draw(img)
        # Pickaxe shape
        draw.rectangle([16, 8, 48, 24], fill=(80, 200, 120, 255))
        draw.rectangle([28, 24, 36, 56], fill=(139, 119, 101, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        return _minimal_png(64, 64, (40, 40, 60))


def _create_placeholder_texture(style: str = "biped") -> bytes:
    """Create a placeholder texture PNG sized for the given mob style."""
    from .bedrock_reference import STYLE_TEXTURE_SIZE
    w, h = STYLE_TEXTURE_SIZE.get(style, (64, 64))
    try:
        from PIL import Image

        img = Image.new("RGBA", (w, h), (100, 100, 100, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        return _minimal_png(w, h, (100, 100, 100))


def _minimal_png(width: int, height: int, color: tuple) -> bytes:
    """Create a minimal valid PNG without Pillow (fallback)."""
    import struct
    import zlib

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_data = b""
    for _ in range(height):
        raw_data += b"\x00"
        raw_data += bytes(color) * width

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr_data)
        + chunk(b"IDAT", zlib.compress(raw_data))
        + chunk(b"IEND", b"")
    )
