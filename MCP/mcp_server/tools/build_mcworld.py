"""
Tool: build_mcworld — Creates a .mcworld file containing a flat creative world
with behavior/resource packs embedded and the custom mob auto-summoned via
a tick function (commands run on world load).

A .mcworld is a ZIP of a Bedrock world directory:
  - level.dat          (little-endian NBT with 8-byte header)
  - level.dat_old      (copy of level.dat)
  - world_icon.jpeg    (optional thumbnail)
  - behavior_packs/    (embedded BP folder)
  - resource_packs/    (embedded RP folder)
  - db/                (LevelDB world data — empty is okay, Minecraft regenerates)

The level.dat enables cheats, sets creative mode, uses a flat world generator,
and references the embedded packs via world_behavior_packs.json / world_resource_packs.json.
A tick.json + mcfunction auto-summons the mob near spawn.
"""

import io
import json
import struct
import base64
import uuid
import time
import zipfile


def _anim_short_key(anim_key: str, mob_name: str) -> str:
    """Extract short animation key (e.g. 'walk') from a full animation ID.

    Handles mismatches between mob_name and the animation prefix.
    For example, mob_name='my_first_mob' but anim_key='animation.custom_dragon.walk'
    -> returns 'walk' (the last dot-segment).
    """
    prefix = f"animation.{mob_name}."
    if anim_key.startswith(prefix):
        return anim_key[len(prefix):]
    parts = anim_key.split(".")
    if len(parts) >= 3 and parts[0] == "animation":
        return parts[-1]
    return anim_key


def _get_wing_bone_names(geo_data: dict) -> list:
    """Return names of wing bones in the geometry."""
    names = []
    if not geo_data or not isinstance(geo_data, dict):
        return names
    for geo_entry in geo_data.get("minecraft:geometry", []):
        for bone in geo_entry.get("bones", []):
            name = bone.get("name", "")
            if "wing" in name.lower():
                names.append(name)
    return names


def _fix_geometry_scale(geo_data: dict) -> None:
    """Scale up LLM geometry that is too small for Minecraft."""
    MIN_BODY_DIMENSION = 6

    for geo_entry in geo_data.get("minecraft:geometry", []):
        bones = geo_entry.get("bones", [])
        if not bones:
            continue

        max_dim = 0
        for bone in bones:
            for cube in bone.get("cubes", []):
                sz = cube.get("size", [0, 0, 0])
                max_dim = max(max_dim, *[abs(s) for s in sz])

        if max_dim < MIN_BODY_DIMENSION and max_dim > 0:
            scale_factor = round(MIN_BODY_DIMENSION / max_dim + 0.5)
            scale_factor = max(2, min(scale_factor, 6))

            for bone in bones:
                for cube in bone.get("cubes", []):
                    origin = cube.get("origin", [0, 0, 0])
                    size = cube.get("size", [0, 0, 0])
                    cube["origin"] = [round(v * scale_factor, 1) for v in origin]
                    cube["size"] = [round(v * scale_factor, 1) for v in size]
                pivot = bone.get("pivot", [0, 0, 0])
                bone["pivot"] = [round(v * scale_factor, 1) for v in pivot]


def _fix_geometry_legs(geo_data: dict) -> None:
    """Fix LLM geometry where legs go underground or overlap with the body."""
    _LEG_KEYWORDS = ["leg", "foot", "feet", "hoof", "paw"]
    _BODY_KEYWORDS = ["body", "torso", "chest", "abdomen", "spine", "root"]

    def _is_leg(name: str) -> bool:
        n = name.lower().replace("_", " ")
        return any(kw in n for kw in _LEG_KEYWORDS)

    def _is_body(name: str) -> bool:
        n = name.lower().replace("_", " ")
        return any(kw in n for kw in _BODY_KEYWORDS)

    for geo_entry in geo_data.get("minecraft:geometry", []):
        bones = geo_entry.get("bones", [])
        if not bones:
            continue

        body_cube = None
        leg_bones = []
        for bone in bones:
            cubes = bone.get("cubes", [])
            if not cubes:
                continue
            if _is_body(bone.get("name", "")) and not body_cube:
                body_cube = cubes[0]
            elif _is_leg(bone.get("name", "")):
                leg_bones.append(bone)

        if not leg_bones:
            continue

        leg_ys = []
        leg_hs = []
        for lb in leg_bones:
            for c in lb.get("cubes", []):
                leg_ys.append(c.get("origin", [0, 0, 0])[1])
                leg_hs.append(c.get("size", [0, 0, 0])[1])
        if not leg_ys:
            continue

        min_leg_y = min(leg_ys)

        if min_leg_y < 0:
            shift = -min_leg_y
            for bone in bones:
                for c in bone.get("cubes", []):
                    o = c.get("origin", [0, 0, 0])
                    o[1] += shift
                    c["origin"] = o
                p = bone.get("pivot", [0, 0, 0])
                p[1] += shift
                bone["pivot"] = p
            return

        if not body_cube:
            return
        body_y = body_cube.get("origin", [0, 0, 0])[1]
        max_leg_h = max(leg_hs)
        overlap = body_y - min_leg_y
        if overlap >= 0 and overlap < max_leg_h * 0.5:
            shift = max_leg_h - overlap
            if shift <= 0:
                return
            for bone in bones:
                if _is_leg(bone.get("name", "")):
                    continue
                for c in bone.get("cubes", []):
                    o = c.get("origin", [0, 0, 0])
                    o[1] += shift
                    c["origin"] = o
                p = bone.get("pivot", [0, 0, 0])
                p[1] += shift
                bone["pivot"] = p


def _sanitize_animations(animation_json: dict) -> None:
    """Fix common LLM animation issues at build time.

    - Removes anim_time_update from walk/run animations (causes jitter
      on custom entities whose pathfinding movement isn't smooth).
    """
    for anim_key, anim_data in animation_json.get("animations", {}).items():
        if not isinstance(anim_data, dict):
            continue
        last_seg = anim_key.rsplit(".", 1)[-1].lower()
        if last_seg in ("walk", "walking", "run", "running"):
            anim_data.pop("anim_time_update", None)

from .bedrock_reference import (
    generate_linked_manifests,
    generate_client_entity,
    generate_lang_file,
    generate_spawn_rules,
)


# ─── Bedrock Little-Endian NBT Writer ────────────────────────────────────────

TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12


def _write_tag_name(buf: io.BytesIO, tag_type: int, name: str):
    """Write tag type byte + name (little-endian short length + utf-8)."""
    buf.write(struct.pack("<B", tag_type))
    encoded = name.encode("utf-8")
    buf.write(struct.pack("<H", len(encoded)))
    buf.write(encoded)


def _write_string(buf: io.BytesIO, value: str):
    encoded = value.encode("utf-8")
    buf.write(struct.pack("<H", len(encoded)))
    buf.write(encoded)


def _write_compound(buf: io.BytesIO, data: dict, root: bool = False):
    """Recursively write a compound tag in Bedrock little-endian NBT."""
    for key, value in data.items():
        if isinstance(value, dict):
            if "_type" in value:
                # Typed value: {"_type": "byte", "_value": 1}
                t = value["_type"]
                v = value["_value"]
                if t == "byte":
                    _write_tag_name(buf, TAG_BYTE, key)
                    buf.write(struct.pack("<b", v))
                elif t == "short":
                    _write_tag_name(buf, TAG_SHORT, key)
                    buf.write(struct.pack("<h", v))
                elif t == "int":
                    _write_tag_name(buf, TAG_INT, key)
                    buf.write(struct.pack("<i", v))
                elif t == "long":
                    _write_tag_name(buf, TAG_LONG, key)
                    buf.write(struct.pack("<q", v))
                elif t == "float":
                    _write_tag_name(buf, TAG_FLOAT, key)
                    buf.write(struct.pack("<f", v))
                elif t == "double":
                    _write_tag_name(buf, TAG_DOUBLE, key)
                    buf.write(struct.pack("<d", v))
                elif t == "string":
                    _write_tag_name(buf, TAG_STRING, key)
                    _write_string(buf, v)
                elif t == "int_list":
                    _write_tag_name(buf, TAG_LIST, key)
                    buf.write(struct.pack("<B", TAG_INT))
                    buf.write(struct.pack("<i", len(v)))
                    for item in v:
                        buf.write(struct.pack("<i", item))
            else:
                # Nested compound
                _write_tag_name(buf, TAG_COMPOUND, key)
                _write_compound(buf, value)
        elif isinstance(value, str):
            _write_tag_name(buf, TAG_STRING, key)
            _write_string(buf, value)
        elif isinstance(value, bool):
            _write_tag_name(buf, TAG_BYTE, key)
            buf.write(struct.pack("<b", 1 if value else 0))
        elif isinstance(value, int):
            _write_tag_name(buf, TAG_INT, key)
            buf.write(struct.pack("<i", value))
        elif isinstance(value, float):
            _write_tag_name(buf, TAG_FLOAT, key)
            buf.write(struct.pack("<f", value))
        elif isinstance(value, list):
            # Assume list of ints (for version arrays)
            _write_tag_name(buf, TAG_LIST, key)
            if len(value) > 0 and isinstance(value[0], int):
                buf.write(struct.pack("<B", TAG_INT))
                buf.write(struct.pack("<i", len(value)))
                for item in value:
                    buf.write(struct.pack("<i", item))
            else:
                buf.write(struct.pack("<B", TAG_END))
                buf.write(struct.pack("<i", 0))

    # End tag
    buf.write(struct.pack("<B", TAG_END))


def build_level_dat(world_name: str, bp_uuid: str, rp_uuid: str) -> bytes:
    """
    Build a minimal Bedrock level.dat binary.
    8-byte header (version=10, payload_length) + little-endian NBT compound.
    """
    flat_layers = json.dumps({
        "biome_id": 1,
        "block_layers": [
            {"block_name": "minecraft:bedrock", "count": 1},
            {"block_name": "minecraft:dirt", "count": 2},
            {"block_name": "minecraft:grass_block", "count": 1}
        ],
        "encoding_version": 6,
        "structure_options": None,
        "world_version": "version.post_1_18"
    })

    nbt_data = {
        "abilities": {
            "attackmobs": {"_type": "byte", "_value": 1},
            "attackplayers": {"_type": "byte", "_value": 1},
            "build": {"_type": "byte", "_value": 1},
            "doorsandswitches": {"_type": "byte", "_value": 1},
            "flying": {"_type": "byte", "_value": 0},
            "flySpeed": {"_type": "float", "_value": 0.05},
            "instabuild": {"_type": "byte", "_value": 0},
            "invulnerable": {"_type": "byte", "_value": 0},
            "lightning": {"_type": "byte", "_value": 0},
            "mayfly": {"_type": "byte", "_value": 1},
            "mine": {"_type": "byte", "_value": 1},
            "op": {"_type": "byte", "_value": 1},
            "opencontainers": {"_type": "byte", "_value": 1},
            "teleport": {"_type": "byte", "_value": 1},
            "walkSpeed": {"_type": "float", "_value": 0.1},
        },
        "baseGameVersion": "*",
        "cheatsEnabled": {"_type": "byte", "_value": 1},
        "commandblockoutput": {"_type": "byte", "_value": 1},
        "commandblocksenabled": {"_type": "byte", "_value": 1},
        "commandsEnabled": {"_type": "byte", "_value": 1},
        "currentTick": {"_type": "long", "_value": 1},
        "Difficulty": 1,
        "dodaylightcycle": {"_type": "byte", "_value": 1},
        "doentitydrops": {"_type": "byte", "_value": 1},
        "dofiretick": {"_type": "byte", "_value": 1},
        "doimmediaterespawn": {"_type": "byte", "_value": 0},
        "doinsomnia": {"_type": "byte", "_value": 1},
        "domobloot": {"_type": "byte", "_value": 1},
        "domobspawning": {"_type": "byte", "_value": 1},
        "dotiledrops": {"_type": "byte", "_value": 1},
        "doweathercycle": {"_type": "byte", "_value": 1},
        "drowningdamage": {"_type": "byte", "_value": 1},
        "falldamage": {"_type": "byte", "_value": 1},
        "firedamage": {"_type": "byte", "_value": 1},
        "FlatWorldLayers": flat_layers,
        "ForceGameType": {"_type": "byte", "_value": 0},
        "functioncommandlimit": 10000,
        "GameType": 1,  # Creative
        "Generator": 2,  # Flat
        "hasBeenLoadedInCreative": {"_type": "byte", "_value": 1},
        "immutableWorld": {"_type": "byte", "_value": 0},
        "InventoryVersion": "1.20.0",
        "keepinventory": {"_type": "byte", "_value": 1},
        "LANBroadcast": {"_type": "byte", "_value": 1},
        "LANBroadcastIntent": {"_type": "byte", "_value": 1},
        "lastOpenedWithVersion": [1, 20, 0, 0, 0],
        "LastPlayed": {"_type": "long", "_value": int(time.time())},
        "LevelName": world_name,
        "lightningLevel": {"_type": "float", "_value": 0.0},
        "lightningTime": 0,
        "LimitedWorldOriginX": 0,
        "LimitedWorldOriginY": 32767,
        "LimitedWorldOriginZ": 0,
        "maxcommandchainlength": 65535,
        "MinimumCompatibleClientVersion": [1, 20, 0, 0, 0],
        "mobgriefing": {"_type": "byte", "_value": 1},
        "MultiplayerGame": {"_type": "byte", "_value": 1},
        "MultiplayerGameIntent": {"_type": "byte", "_value": 1},
        "naturalregeneration": {"_type": "byte", "_value": 1},
        "NetherScale": 8,
        "NetworkVersion": 594,
        "permissionsLevel": 1,
        "Platform": 2,
        "PlatformBroadcastIntent": 3,
        "pvp": {"_type": "byte", "_value": 1},
        "rainLevel": {"_type": "float", "_value": 0.0},
        "rainTime": 0,
        "RandomSeed": {"_type": "long", "_value": 12345},
        "randomtickspeed": 1,
        "sendcommandfeedback": {"_type": "byte", "_value": 1},
        "serverChunkTickRange": 4,
        "showcoordinates": {"_type": "byte", "_value": 1},
        "showdeathmessages": {"_type": "byte", "_value": 1},
        "spawnMobs": {"_type": "byte", "_value": 1},
        "spawnradius": 5,
        "SpawnX": 0,
        "SpawnY": 4,
        "SpawnZ": 0,
        "startWithMapEnabled": {"_type": "byte", "_value": 0},
        "StorageVersion": 10,
        "texturePacksRequired": {"_type": "byte", "_value": 0},
        "Time": {"_type": "long", "_value": 0},
        "tntexplodes": {"_type": "byte", "_value": 1},
        "useMsaGamertagsOnly": {"_type": "byte", "_value": 0},
        "WorldVersion": 1,
        "XBLBroadcastIntent": 3,
        "experiments": {
            "experiments_ever_used": {"_type": "byte", "_value": 0},
            "saved_with_toggled_experiments": {"_type": "byte", "_value": 0},
        },
    }

    # Write root compound tag
    payload = io.BytesIO()
    # Root compound tag: type(1 byte) + name
    _write_tag_name(payload, TAG_COMPOUND, "")
    _write_compound(payload, nbt_data)

    nbt_bytes = payload.getvalue()

    # 8-byte header: version (int32 LE) + payload length (int32 LE)
    header = struct.pack("<II", 10, len(nbt_bytes))
    return header + nbt_bytes


# ─── .mcworld Builder ────────────────────────────────────────────────────────

async def build_mcworld(mobs: list[dict], pack_name: str = "custom_mobs") -> str:
    """
    Build a .mcworld file containing a flat creative world with
    custom mobs already set up to spawn.

    The world includes:
      - Flat creative world with cheats enabled
      - Embedded behavior pack (entity definitions + spawn rules)
      - Embedded resource pack (client entity + textures + lang)
      - A tick function that auto-summons each mob near spawn on first load

    Args:
        mobs: List of mob objects, each with "entity", "metadata", "texture_base64".
        pack_name: Name for the addon pack.

    Returns:
        JSON with base64-encoded .mcworld file and filename.
    """
    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in pack_name)
    world_name = f"Mob Forge - {pack_name}"

    # Generate linked manifests
    bp_manifest, rp_manifest = generate_linked_manifests(pack_name)
    bp_uuid = bp_manifest["header"]["uuid"]
    rp_uuid = rp_manifest["header"]["uuid"]

    # Collect mob info
    lang_entries = []
    mob_identifiers = []

    mcworld_buffer = io.BytesIO()

    with zipfile.ZipFile(mcworld_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

        # ── level.dat ─────────────────────────────────────────────────
        level_dat = build_level_dat(world_name, bp_uuid, rp_uuid)
        zf.writestr("level.dat", level_dat)
        zf.writestr("level.dat_old", level_dat)

        # ── levelname.txt ─────────────────────────────────────────────
        zf.writestr("levelname.txt", world_name)

        # ── world_behavior_packs.json ─────────────────────────────────
        # Tells the world which BP to activate
        zf.writestr("world_behavior_packs.json", json.dumps([
            {"pack_id": bp_uuid, "version": [1, 0, 0]}
        ], indent=2))

        # ── world_resource_packs.json ─────────────────────────────────
        zf.writestr("world_resource_packs.json", json.dumps([
            {"pack_id": rp_uuid, "version": [1, 0, 0]}
        ], indent=2))

        # ── Behavior Pack (embedded) ──────────────────────────────────
        bp_prefix = f"behavior_packs/{safe_name}_BP"

        zf.writestr(f"{bp_prefix}/manifest.json",
                     json.dumps(bp_manifest, indent=2))
        zf.writestr(f"{bp_prefix}/pack_icon.png", _create_pack_icon())

        for mob in mobs:
            entity_data = mob.get("entity", mob)
            metadata = mob.get("metadata", {})

            entity_data.setdefault("minecraft:entity", {})
            mc_entity = entity_data["minecraft:entity"]
            mc_entity.setdefault("description", {})
            identifier = mc_entity["description"].get(
                "identifier", "custom:unknown_mob"
            )
            mob_name = identifier.split(":")[-1]
            display_name = metadata.get(
                "display_name", mob_name.replace("_", " ").title()
            )
            lang_entries.append((identifier, display_name))
            mob_identifiers.append(identifier)

            # Sanitize behavior entity before writing
            mc_entity.setdefault("components", {})
            bp_comps = mc_entity["components"]

            # Normalize unreliable fireball projectiles
            if "minecraft:shooter" in bp_comps:
                _proj = bp_comps["minecraft:shooter"].get("def", "")
                if _proj in ("minecraft:fireball", "minecraft:dragon_fireball",
                             "minecraft:large_fireball"):
                    bp_comps["minecraft:shooter"]["def"] = "minecraft:small_fireball"

            # Remove melee when ranged attack is present
            if "minecraft:shooter" in bp_comps and "minecraft:behavior.ranged_attack" in bp_comps:
                bp_comps.pop("minecraft:behavior.melee_attack", None)

            # Ensure fly components AND behaviors when mob has fly animations,
            # wing bones, or fly-related components.
            _fly_keys = ("minecraft:can_fly", "minecraft:movement.fly",
                         "minecraft:navigation.fly", "minecraft:flying_speed")
            _mob_anim = mob.get("animation_json") or {}
            _mob_geo = mob.get("geometry_data") or {}
            _has_fly = (
                any("fly" in k for k in _mob_anim.get("animations", {}))
                or bool(_get_wing_bone_names(_mob_geo))
                or any(k in bp_comps for k in _fly_keys)
            )
            if _has_fly:
                bp_comps.pop("minecraft:movement.basic", None)
                bp_comps.setdefault("minecraft:movement.fly", {})
                bp_comps.pop("minecraft:navigation.walk", None)
                bp_comps.setdefault("minecraft:navigation.fly", {
                    "can_path_over_water": True,
                    "can_path_over_lava": True,
                })
                bp_comps.setdefault("minecraft:can_fly", {})
                bp_comps.setdefault("minecraft:flying_speed", {"value": 0.4})
                bp_comps.pop("minecraft:behavior.wander", None)
                bp_comps["minecraft:behavior.float"] = {"priority": 0}
                if "minecraft:behavior.random_fly" not in bp_comps:
                    bp_comps["minecraft:behavior.random_fly"] = {
                        "priority": 5,
                        "avoid_damage_blocks": True,
                        "can_land_on_trees": False,
                        "xz_dist": 15,
                        "y_dist": 5,
                        "y_offset": 0,
                        "speed_multiplier": 1.0,
                    }
                if "minecraft:behavior.random_stroll" not in bp_comps:
                    bp_comps["minecraft:behavior.random_stroll"] = {
                        "priority": 7,
                        "speed_multiplier": 0.6,
                    }

            # Ensure targeting filter has required "subject" field
            _nat = bp_comps.get("minecraft:behavior.nearest_attackable_target", {})
            for _et in _nat.get("entity_types", []):
                _f = _et.get("filters", {})
                if _f.get("test") == "is_family" and "subject" not in _f:
                    _f["subject"] = "other"

            # Entity behavior file
            zf.writestr(
                f"{bp_prefix}/entities/{mob_name}.json",
                json.dumps(entity_data, indent=2),
            )

            # Loot table for item drops on death
            loot_drops = metadata.get("loot_drops", [])
            loot_table = _build_loot_table(loot_drops, mob_name)
            zf.writestr(
                f"{bp_prefix}/loot_tables/entities/{mob_name}.json",
                json.dumps(loot_table, indent=2),
            )

            # NOTE: No spawn_rules in .mcworld — mobs are summoned once
            # via the one-shot mcfunction, not spawned naturally.

        # ── One-shot summon via player tag ───────────────────────────
        # tick.json calls startup every tick; startup uses a player tag
        # as a one-shot gate. Uses OLD Bedrock execute syntax which works
        # on all versions (no min_engine_version requirement).
        #
        # Old Bedrock execute: execute <selector> <x> <y> <z> <command>
        startup_lines = []
        # Summon each mob near the first player who hasn't been tagged yet
        for i, ident in enumerate(mob_identifiers):
            offset_x = 2 + (i * 4)
            startup_lines.append(
                f"execute @a[tag=!mf_spawned] ~ ~ ~ summon {ident} ~{offset_x} ~ ~2"
            )
        startup_lines.append(
            'execute @a[tag=!mf_spawned] ~ ~ ~ tellraw @a {"rawtext":[{"text":"§aMob Forge: §fCustom mobs summoned near you!"}]}'
        )
        # Tag all players so it never runs again
        startup_lines.append("tag @a add mf_spawned")
        zf.writestr(
            f"{bp_prefix}/functions/startup.mcfunction",
            "\n".join(startup_lines) + "\n",
        )

        # tick.json — calls startup every tick (startup handles the one-shot logic)
        zf.writestr(
            f"{bp_prefix}/functions/tick.json",
            json.dumps({"values": ["startup"]}, indent=2),
        )

        # ── Resource Pack (embedded) ──────────────────────────────────
        rp_prefix = f"resource_packs/{safe_name}_RP"

        zf.writestr(f"{rp_prefix}/manifest.json",
                     json.dumps(rp_manifest, indent=2))
        zf.writestr(f"{rp_prefix}/pack_icon.png", _create_pack_icon())

        # Language file
        lang_content = generate_lang_file(lang_entries)
        zf.writestr(f"{rp_prefix}/texts/en_US.lang", lang_content)

        for mob in mobs:
            entity_data = mob.get("entity", mob)
            metadata = mob.get("metadata", {})
            texture_b64 = mob.get("texture_base64", None)
            geometry_data = mob.get("geometry_data", None)
            anim_json = mob.get("animation_json", None)
            anim_ctrl_json = mob.get("animation_controller_json", None)

            mc_entity = entity_data.get("minecraft:entity", {})
            identifier = mc_entity.get("description", {}).get(
                "identifier", "custom:unknown_mob"
            )
            mob_name = identifier.split(":")[-1]
            style = metadata.get("suggested_style", "zombie")

            # Determine geometry ID — prefer custom geometry, fall back to vanilla
            if geometry_data:
                _fix_geometry_scale(geometry_data)
                _fix_geometry_legs(geometry_data)

                geos = geometry_data.get("minecraft:geometry", [])
                if geos:
                    geometry_id = geos[0].get("description", {}).get(
                        "identifier", f"geometry.{mob_name}"
                    )
                else:
                    geometry_id = f"geometry.{mob_name}"

                # Write custom geometry model file
                zf.writestr(
                    f"{rp_prefix}/models/entity/{mob_name}.geo.json",
                    json.dumps(geometry_data, indent=2),
                )
            else:
                geometry_id = None

            # Auto-generate fly animation if mob has wing bones but none
            _wing_names = _get_wing_bone_names(geometry_data) if geometry_data else []
            if _wing_names:
                if not anim_json or not isinstance(anim_json, dict):
                    anim_json = {"format_version": "1.8.0", "animations": {}}
                _anims = anim_json.setdefault("animations", {})
                if not any("fly" in k.lower() for k in _anims):
                    _fly_key = f"animation.{mob_name}.fly"
                    _fly_bones = {}
                    for _wn in _wing_names:
                        if "left" in _wn.lower():
                            _fly_bones[_wn] = {"rotation": {"0.0": [0, 0, -45], "0.5": [0, 0, 15], "1.0": [0, 0, -45]}}
                        elif "right" in _wn.lower():
                            _fly_bones[_wn] = {"rotation": {"0.0": [0, 0, 45], "0.5": [0, 0, -15], "1.0": [0, 0, 45]}}
                        else:
                            _fly_bones[_wn] = {"rotation": {"0.0": [0, 0, -30], "0.5": [0, 0, 30], "1.0": [0, 0, -30]}}
                    _fly_bones["body"] = {"rotation": {"0.0": [2, 0, 0], "0.5": [-2, 0, 0], "1.0": [2, 0, 0]}}
                    _anims[_fly_key] = {"loop": True, "animation_length": 1.0, "bones": _fly_bones}

            # Sanitize + build short-name map and remap controller references
            anim_short_map = {}
            if anim_json and isinstance(anim_json, dict) and anim_json.get("animations"):
                import copy as _cp
                anim_json = _cp.deepcopy(anim_json)
                _sanitize_animations(anim_json)

                for anim_key in anim_json["animations"]:
                    short_key = _anim_short_key(anim_key, mob_name)
                    anim_short_map[short_key] = anim_key

                zf.writestr(
                    f"{rp_prefix}/animations/{mob_name}.animation.json",
                    json.dumps(anim_json, indent=2),
                )

            if anim_ctrl_json and isinstance(anim_ctrl_json, dict) and anim_ctrl_json.get("animation_controllers"):
                if anim_short_map:
                    anim_ctrl_json = _remap_controller_to_short_names(
                        anim_ctrl_json, anim_short_map
                    )
                zf.writestr(
                    f"{rp_prefix}/animation_controllers/{mob_name}.controllers.json",
                    json.dumps(anim_ctrl_json, indent=2),
                )

            # Client entity (with animation/controller refs wired in)
            if geometry_id:
                client_entity = _build_client_entity(
                    identifier, mob_name, geometry_id,
                    animation_json=anim_json,
                    animation_controller_json=anim_ctrl_json,
                )
            else:
                client_entity = generate_client_entity(identifier, mob_name, style)

            if metadata.get("suggested_colors"):
                colors = metadata["suggested_colors"]
                ce_desc = client_entity["minecraft:client_entity"]["description"]
                ce_desc["spawn_egg"]["base_color"] = (
                    colors[0] if len(colors) > 0 else "#4A7023"
                )
                ce_desc["spawn_egg"]["overlay_color"] = (
                    colors[1] if len(colors) > 1 else "#2E4F1E"
                )

            zf.writestr(
                f"{rp_prefix}/entity/{mob_name}.entity.json",
                json.dumps(client_entity, indent=2),
            )

            # Texture
            texture_bytes = None
            if texture_b64:
                try:
                    texture_bytes = base64.b64decode(texture_b64)
                except Exception:
                    texture_bytes = None

            if not texture_bytes and geometry_data:
                try:
                    from backend.llm.texture_gen import generate_mob_texture as _gen_tex
                    import base64 as _b64m
                    _display = metadata.get("display_name", mob_name.replace("_", " ").title())
                    _tex_url = _gen_tex(
                        geometry_json=geometry_data,
                        display_name=_display,
                        short_name=mob_name,
                    )
                    if _tex_url and "," in _tex_url:
                        texture_bytes = _b64m.b64decode(_tex_url.split(",", 1)[1])
                except Exception:
                    pass

            if not texture_bytes:
                texture_bytes = _create_placeholder_texture(style)

            zf.writestr(
                f"{rp_prefix}/textures/entity/{mob_name}.png",
                texture_bytes,
            )

    mcworld_bytes = mcworld_buffer.getvalue()
    encoded = base64.b64encode(mcworld_bytes).decode("utf-8")

    return json.dumps({
        "status": "success",
        "filename": f"{safe_name}.mcworld",
        "file_base64": encoded,
        "size_bytes": len(mcworld_bytes),
        "mob_count": len(mobs),
        "mob_identifiers": mob_identifiers,
        "instructions": (
            f"Double-click {safe_name}.mcworld to import into Minecraft Bedrock. "
            "The world is a flat creative world with cheats enabled. "
            "Your custom mobs will be auto-summoned near spawn. "
            "You can also use /summon <identifier> to spawn more."
        ),
    })


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_loot_table(loot_drops: list, mob_name: str) -> dict:
    """Build a Bedrock loot table JSON from the _mob_forge_loot metadata."""
    pools = []
    if not loot_drops:
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
        if count_max > 1:
            entry["functions"] = [
                {"function": "set_count", "count": {"min": count_min, "max": count_max}}
            ]

        pool = {
            "rolls": 1,
            "entries": [entry],
        }
        if chance < 1.0:
            pool["conditions"] = [
                {"condition": "random_chance", "chance": chance}
            ]

        pools.append(pool)

    return {"pools": pools}


def _remap_controller_to_short_names(
    animation_controller_json: dict,
    anim_short_map: dict,
) -> dict:
    """Rewrite animation controller to use short names instead of full IDs.

    Bedrock requires animation controllers to reference animations by the
    short names defined in the client entity's 'animations' dict, NOT by
    full identifiers like 'animation.mob.walk'.
    """
    import copy
    ctrl = copy.deepcopy(animation_controller_json)
    reverse = {v: k for k, v in anim_short_map.items()}

    for controller in ctrl.get("animation_controllers", {}).values():
        for state in controller.get("states", {}).values():
            anims = state.get("animations")
            if not isinstance(anims, list):
                continue
            new_anims = []
            for entry in anims:
                if isinstance(entry, str):
                    new_anims.append(reverse.get(entry, entry))
                elif isinstance(entry, dict):
                    new_anims.append(
                        {reverse.get(k, k): v for k, v in entry.items()}
                    )
                else:
                    new_anims.append(entry)
            state["animations"] = new_anims
    return ctrl


def _build_client_entity(
    identifier: str,
    mob_name: str,
    geometry_id: str,
    animation_json: dict = None,
    animation_controller_json: dict = None,
) -> dict:
    """Build a client entity definition with optional animation/controller refs."""
    desc = {
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

    # Register individual animation clips in the animations dict
    anim_refs = {}
    if animation_json and isinstance(animation_json, dict) and animation_json.get("animations"):
        for anim_key in animation_json["animations"]:
            short_key = _anim_short_key(anim_key, mob_name)
            anim_refs[short_key] = anim_key

    # Also register animation controller shortname (keeps it loadable)
    has_controller = (
        animation_controller_json
        and isinstance(animation_controller_json, dict)
        and animation_controller_json.get("animation_controllers")
    )
    if has_controller:
        for ctrl_key in animation_controller_json["animation_controllers"]:
            short_ctrl_key = ctrl_key.replace(
                f"controller.animation.{mob_name}.", ""
            ).replace("controller.animation.", "")
            anim_refs[short_ctrl_key] = ctrl_key

    if anim_refs:
        desc["animations"] = anim_refs

        has_walk = any(
            k in ("walk", "walking", "run", "running")
            for k, v in anim_refs.items()
            if not v.startswith("controller.animation.")
        )
        has_fly = any(
            k in ("fly", "flying")
            for k, v in anim_refs.items()
            if not v.startswith("controller.animation.")
        )
        animate_list = []
        for short_key, full_id in anim_refs.items():
            if full_id.startswith("controller.animation."):
                continue
            if short_key == "idle":
                if has_fly and has_walk:
                    cond = "query.is_on_ground && !query.is_moving"
                elif has_fly:
                    cond = "query.is_on_ground"
                elif has_walk:
                    cond = "!query.is_moving"
                else:
                    cond = "1.0"
                animate_list.append({short_key: cond})
            elif short_key in ("walk", "walking", "run", "running"):
                if has_fly:
                    animate_list.append({short_key: "query.is_on_ground && query.is_moving"})
                else:
                    animate_list.append({short_key: "query.is_moving"})
            elif short_key in ("fly", "flying"):
                animate_list.append({short_key: "!query.is_on_ground"})
            elif short_key in ("attack", "attacking", "breath", "fire",
                               "fire_breath", "fire_attack", "shoot",
                               "bite", "charge"):
                animate_list.append({short_key: "variable.attacking"})
            else:
                pass
        if animate_list:
            desc["scripts"] = {"animate": animate_list}

    return {
        "format_version": "1.10.0",
        "minecraft:client_entity": {
            "description": desc
        }
    }


def _create_pack_icon() -> bytes:
    """Create a simple 64x64 pack icon PNG."""
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), (40, 40, 60, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([16, 8, 48, 24], fill=(80, 200, 120, 255))
        draw.rectangle([28, 24, 36, 56], fill=(139, 119, 101, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        return _minimal_png(64, 64, (40, 40, 60))


def _create_placeholder_texture(style: str = "biped") -> bytes:
    """Create a placeholder texture with some color variation instead of flat gray."""
    from .bedrock_reference import STYLE_TEXTURE_SIZE
    w, h = STYLE_TEXTURE_SIZE.get(style, (64, 64))
    try:
        from PIL import Image
        import random as _rng
        _rng.seed(42)

        img = Image.new("RGBA", (w, h), (120, 110, 100, 255))
        for py in range(h):
            for px in range(w):
                noise = _rng.randint(-10, 10)
                base_r = 120 + noise
                base_g = 110 + noise
                base_b = 100 + noise
                img.putpixel((px, py), (
                    max(0, min(255, base_r)),
                    max(0, min(255, base_g)),
                    max(0, min(255, base_b)),
                    255,
                ))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        return _minimal_png(w, h, (120, 110, 100))


def _minimal_png(width: int, height: int, color: tuple) -> bytes:
    """Create a minimal valid PNG without Pillow."""
    import zlib

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return (struct.pack(">I", len(data)) + c +
                struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

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
