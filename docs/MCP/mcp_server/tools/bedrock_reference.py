"""
Bedrock Reference Data — Vanilla entity examples, valid component lists,
and template generators for Minecraft Bedrock Edition addons.
"""

import uuid
import json

# ─── Valid Bedrock Components ───────────────────────────────────────────────────

VALID_COMPONENTS = [
    "minecraft:health",
    "minecraft:attack",
    "minecraft:movement",
    "minecraft:movement.basic",
    "minecraft:movement.fly",
    "minecraft:movement.hover",
    "minecraft:movement.skip",
    "minecraft:movement.sway",
    "minecraft:jump.static",
    "minecraft:jump.dynamic",
    "minecraft:collision_box",
    "minecraft:type_family",
    "minecraft:nameable",
    "minecraft:physics",
    "minecraft:pushable",
    "minecraft:damage_sensor",
    "minecraft:breathable",
    "minecraft:burns_in_daylight",
    "minecraft:despawn",
    "minecraft:experience_reward",
    "minecraft:loot",
    "minecraft:scale",
    "minecraft:knockback_resistance",
    "minecraft:flying_speed",
    "minecraft:follow_range",
    "minecraft:is_baby",
    "minecraft:is_ignited",
    "minecraft:navigation.walk",
    "minecraft:navigation.fly",
    "minecraft:navigation.float",
    "minecraft:navigation.climb",
    "minecraft:navigation.swim",
    "minecraft:navigation.hover",
    "minecraft:behavior.float",
    "minecraft:behavior.melee_attack",
    "minecraft:behavior.ranged_attack",
    "minecraft:behavior.hurt_by_target",
    "minecraft:behavior.nearest_attackable_target",
    "minecraft:behavior.look_at_player",
    "minecraft:behavior.random_look_around",
    "minecraft:behavior.random_stroll",
    "minecraft:behavior.flee_sun",
    "minecraft:behavior.restrict_sun",
    "minecraft:behavior.avoid_mob_type",
    "minecraft:behavior.tempt",
    "minecraft:behavior.follow_parent",
    "minecraft:behavior.panic",
    "minecraft:behavior.mount_pathing",
    "minecraft:behavior.leap_at_target",
    "minecraft:behavior.swell",
    "minecraft:behavior.delayed_attack",
    "minecraft:behavior.charge_attack",
    "minecraft:behavior.stomp_attack",
    "minecraft:behavior.swim_idle",
    "minecraft:behavior.swim_wander",
    "minecraft:behavior.stalk_and_pounce_on_target",
    "minecraft:spell_effects",
    "minecraft:strength",
    "minecraft:can_fly",
    "minecraft:can_climb",
    "minecraft:fire_immune",
    "minecraft:is_hidden_when_invisible",
    "minecraft:mark_variant",
    "minecraft:variant",
    "minecraft:skin_id",
    "minecraft:spawn_entity",
    "minecraft:area_attack",
    "minecraft:explode",
    "minecraft:shooter",
    "minecraft:projectile",
]

# ─── Vanilla Entity Examples ────────────────────────────────────────────────────

ZOMBIE_EXAMPLE = {
    "format_version": "1.16.0",
    "minecraft:entity": {
        "description": {
            "identifier": "minecraft:zombie",
            "is_spawnable": True,
            "is_summonable": True,
            "is_experimental": False
        },
        "components": {
            "minecraft:health": {"value": 20, "max": 20},
            "minecraft:attack": {"damage": 3},
            "minecraft:movement": {"value": 0.23},
            "minecraft:collision_box": {"width": 0.6, "height": 1.9},
            "minecraft:type_family": {"family": ["zombie", "undead", "monster", "mob"]},
            "minecraft:nameable": {},
            "minecraft:physics": {},
            "minecraft:pushable": {"is_pushable": True, "is_pushable_by_piston": True},
            "minecraft:burns_in_daylight": {},
            "minecraft:despawn": {"despawn_from_distance": {}},
            "minecraft:experience_reward": {
                "on_death": "query.last_hit_by_player ? 5 + (query.equipment_count * Math.Random(1,3)) : 0"
            },
            "minecraft:navigation.walk": {
                "is_amphibious": False,
                "avoid_sun": True,
                "can_pass_doors": True,
                "can_break_doors": True,
                "can_walk": True
            },
            "minecraft:movement.basic": {},
            "minecraft:jump.static": {},
            "minecraft:behavior.float": {"priority": 0},
            "minecraft:behavior.melee_attack": {"priority": 3, "speed_multiplier": 1.0},
            "minecraft:behavior.hurt_by_target": {"priority": 1},
            "minecraft:behavior.nearest_attackable_target": {
                "priority": 2,
                "entity_types": [
                    {"filters": {"test": "is_family", "subject": "other", "value": "player"}, "max_dist": 35}
                ],
                "within_radius": 25.0
            },
            "minecraft:behavior.random_stroll": {"priority": 6, "speed_multiplier": 1.0},
            "minecraft:behavior.look_at_player": {"priority": 8, "look_distance": 6.0},
            "minecraft:behavior.random_look_around": {"priority": 9},
            "minecraft:behavior.flee_sun": {"priority": 2, "speed_multiplier": 1.0},
            "minecraft:behavior.restrict_sun": {"priority": 2}
        }
    }
}

CREEPER_EXAMPLE = {
    "format_version": "1.16.0",
    "minecraft:entity": {
        "description": {
            "identifier": "minecraft:creeper",
            "is_spawnable": True,
            "is_summonable": True,
            "is_experimental": False
        },
        "components": {
            "minecraft:health": {"value": 20, "max": 20},
            "minecraft:attack": {"damage": 3},
            "minecraft:movement": {"value": 0.2},
            "minecraft:collision_box": {"width": 0.6, "height": 1.7},
            "minecraft:type_family": {"family": ["creeper", "monster", "mob"]},
            "minecraft:nameable": {},
            "minecraft:physics": {},
            "minecraft:pushable": {"is_pushable": True, "is_pushable_by_piston": True},
            "minecraft:despawn": {"despawn_from_distance": {}},
            "minecraft:navigation.walk": {
                "can_pass_doors": True,
                "can_walk": True
            },
            "minecraft:movement.basic": {},
            "minecraft:jump.static": {},
            "minecraft:behavior.float": {"priority": 0},
            "minecraft:behavior.swell": {"priority": 2, "start_distance": 2.5, "stop_distance": 6.0},
            "minecraft:behavior.melee_attack": {"priority": 4, "speed_multiplier": 1.25},
            "minecraft:behavior.hurt_by_target": {"priority": 2},
            "minecraft:behavior.nearest_attackable_target": {
                "priority": 1,
                "entity_types": [
                    {"filters": {"test": "is_family", "subject": "other", "value": "player"}, "max_dist": 16}
                ]
            },
            "minecraft:behavior.random_stroll": {"priority": 5, "speed_multiplier": 0.8},
            "minecraft:behavior.look_at_player": {"priority": 6, "look_distance": 8.0},
            "minecraft:behavior.random_look_around": {"priority": 6},
            "minecraft:explode": {
                "fuse_length": 1.5,
                "fuse_lit": True,
                "power": 3,
                "causes_fire": False,
                "destroy_affected_by_griefing": True
            }
        }
    }
}

# ─── Geometry Mapping (Vanilla Bedrock Geometries) ──────────────────────────────
#
# Each "style" maps to a vanilla Bedrock geometry, a recommended collision_box,
# and a texture size.  The LLM is told to pick one of these styles explicitly.
# This ensures the 3D model, collision box, and texture UV all match.

STYLE_GEOMETRY_MAP = {
    # ── Humanoid / bipedal ────────────────────────────────────────
    "zombie":      "geometry.zombie",           # standard humanoid undead
    "skeleton":    "geometry.skeleton",          # thin humanoid with bow-arm
    "creeper":     "geometry.creeper",           # 4-legged faceless biped
    "player":      "geometry.humanoid.custom",   # full player model
    "villager":    "geometry.villager.v2",        # big-nose villager
    "witch":       "geometry.witch",             # tall villager-like
    "piglin":      "geometry.piglin",            # nether piglin humanoid
    "iron_golem":  "geometry.iron_golem",        # large bulky humanoid
    "snow_golem":  "geometry.snow_golem",        # snowman

    # ── Quadrupeds / animals ──────────────────────────────────────
    "cow":         "geometry.cow",               # medium 4-leg (cow, mooshroom)
    "pig":         "geometry.pig",               # small round 4-leg
    "sheep":       "geometry.sheep",             # woolly 4-leg, medium
    "wolf":        "geometry.wolf",              # dog/wolf 4-leg, slim
    "horse":       "geometry.horse.v2",          # tall 4-leg with long legs
    "llama":       "geometry.llama",             # tall 4-leg with long neck
    "fox":         "geometry.fox",               # small slinky 4-leg
    "cat":         "geometry.cat",               # tiny slim 4-leg
    "goat":        "geometry.goat",              # medium stocky 4-leg with horns
    "polar_bear":  "geometry.polarbear",         # large heavy 4-leg
    "ravager":     "geometry.ravager",           # massive armored 4-leg beast

    # ── Flying / airborne ─────────────────────────────────────────
    "phantom":     "geometry.phantom",           # flat wide-wing flyer
    "bee":         "geometry.bee",               # small round insect flyer
    "parrot":      "geometry.parrot",            # small bird
    "bat":         "geometry.bat",               # tiny flapping creature
    "ghast":       "geometry.ghast",             # large floating cube + tentacles
    "blaze":       "geometry.blaze",             # floating rod-based body
    "vex":         "geometry.vex",               # tiny winged humanoid

    # ── Aquatic ───────────────────────────────────────────────────
    "squid":       "geometry.squid",             # tentacled sea creature
    "dolphin":     "geometry.dolphin",           # sleek swimmer
    "guardian":    "geometry.guardian",           # spiky cube fish
    "turtle":      "geometry.turtle",            # flat shelled 4-leg
    "axolotl":     "geometry.axolotl",           # small amphibian

    # ── Arthropods / crawlers ─────────────────────────────────────
    "spider":      "geometry.spider",            # 8-leg wide body
    "silverfish":  "geometry.silverfish",        # tiny segmented worm
    "endermite":   "geometry.endermite",         # tiny mite

    # ── Special / other ───────────────────────────────────────────
    "slime":       "geometry.slime",             # bouncy translucent cube
    "chicken":     "geometry.chicken",           # small bird with legs
    "rabbit":      "geometry.rabbit",            # tiny hopping animal
    "enderman":    "geometry.enderman",          # very tall thin humanoid
    "wither_skeleton": "geometry.wither_skeleton", # tall dark skeleton
    "hoglin":      "geometry.hoglin",            # large nether beast
    "strider":     "geometry.strider",           # lava-walking long legs
    "frog":        "geometry.frog",              # small amphibian
    "warden":      "geometry.warden",            # massive eyeless brute
    "sniffer":     "geometry.sniffer",           # large friendly dinosaur-like
    "camel":       "geometry.camel",             # tall 4-leg with humps
}

# Collision boxes that match each geometry so the hitbox looks correct.
STYLE_COLLISION_BOX = {
    "zombie":      {"width": 0.6,  "height": 1.9},
    "skeleton":    {"width": 0.6,  "height": 1.9},
    "creeper":     {"width": 0.6,  "height": 1.7},
    "player":      {"width": 0.6,  "height": 1.8},
    "villager":    {"width": 0.6,  "height": 1.9},
    "witch":       {"width": 0.6,  "height": 1.9},
    "piglin":      {"width": 0.6,  "height": 1.9},
    "iron_golem":  {"width": 1.4,  "height": 2.7},
    "snow_golem":  {"width": 0.7,  "height": 1.9},
    "cow":         {"width": 0.9,  "height": 1.4},
    "pig":         {"width": 0.9,  "height": 0.9},
    "sheep":       {"width": 0.9,  "height": 1.3},
    "wolf":        {"width": 0.6,  "height": 0.85},
    "horse":       {"width": 1.4,  "height": 1.6},
    "llama":       {"width": 0.9,  "height": 1.87},
    "fox":         {"width": 0.6,  "height": 0.7},
    "cat":         {"width": 0.6,  "height": 0.7},
    "goat":        {"width": 0.9,  "height": 1.3},
    "polar_bear":  {"width": 1.3,  "height": 1.4},
    "ravager":     {"width": 1.95, "height": 2.2},
    "phantom":     {"width": 0.9,  "height": 0.5},
    "bee":         {"width": 0.7,  "height": 0.6},
    "parrot":      {"width": 0.5,  "height": 0.9},
    "bat":         {"width": 0.5,  "height": 0.9},
    "ghast":       {"width": 4.0,  "height": 4.0},
    "blaze":       {"width": 0.6,  "height": 1.8},
    "vex":         {"width": 0.4,  "height": 0.8},
    "squid":       {"width": 0.8,  "height": 0.8},
    "dolphin":     {"width": 0.9,  "height": 0.6},
    "guardian":     {"width": 0.85, "height": 0.85},
    "turtle":      {"width": 1.2,  "height": 0.4},
    "axolotl":     {"width": 0.75, "height": 0.42},
    "spider":      {"width": 1.4,  "height": 0.9},
    "silverfish":  {"width": 0.4,  "height": 0.3},
    "endermite":   {"width": 0.4,  "height": 0.3},
    "slime":       {"width": 2.04, "height": 2.04},
    "chicken":     {"width": 0.4,  "height": 0.7},
    "rabbit":      {"width": 0.4,  "height": 0.5},
    "enderman":    {"width": 0.6,  "height": 2.9},
    "wither_skeleton": {"width": 0.7, "height": 2.4},
    "hoglin":      {"width": 1.4,  "height": 1.4},
    "strider":     {"width": 0.9,  "height": 1.7},
    "frog":        {"width": 0.5,  "height": 0.5},
    "warden":      {"width": 0.9,  "height": 2.9},
    "sniffer":     {"width": 1.9,  "height": 1.75},
    "camel":       {"width": 1.7,  "height": 2.375},
}

STYLE_TEXTURE_SIZE = {
    "zombie":      (64, 64),
    "skeleton":    (64, 32),
    "creeper":     (64, 32),
    "player":      (64, 64),
    "villager":    (64, 64),
    "witch":       (64, 64),
    "piglin":      (64, 64),
    "iron_golem":  (128, 128),
    "snow_golem":  (64, 64),
    "cow":         (64, 32),
    "pig":         (64, 32),
    "sheep":       (64, 32),
    "wolf":        (64, 32),
    "horse":       (64, 64),
    "llama":       (128, 64),
    "fox":         (48, 32),
    "cat":         (64, 32),
    "goat":        (64, 64),
    "polar_bear":  (128, 64),
    "ravager":     (128, 128),
    "phantom":     (64, 64),
    "bee":         (64, 64),
    "parrot":      (32, 32),
    "bat":         (64, 64),
    "ghast":       (64, 32),
    "blaze":       (64, 32),
    "vex":         (64, 64),
    "squid":       (64, 32),
    "dolphin":     (64, 64),
    "guardian":    (64, 32),
    "turtle":      (128, 64),
    "axolotl":     (64, 64),
    "spider":      (64, 32),
    "silverfish":  (64, 32),
    "endermite":   (64, 32),
    "slime":       (64, 32),
    "chicken":     (64, 32),
    "rabbit":      (64, 32),
    "enderman":    (64, 32),
    "wither_skeleton": (64, 32),
    "hoglin":      (128, 64),
    "strider":     (64, 32),
    "frog":        (48, 48),
    "warden":      (128, 128),
    "sniffer":     (128, 128),
    "camel":       (128, 64),
}

# Human-readable guide injected into the LLM system prompt so it picks the
# best geometry for the mob description.  Grouped by body plan.
STYLE_GUIDE = """
## AVAILABLE MOB STYLES (you MUST pick exactly one)
Each style maps to a built-in vanilla Minecraft Bedrock geometry (3D model).
Pick the style whose BODY SHAPE best matches the mob the user described.

### Humanoid / Bipedal
| Style | Looks like | Best for |
|-------|-----------|----------|
| zombie | Standard undead humanoid | zombies, ghouls, walkers, humanoid monsters |
| skeleton | Thin bony humanoid | skeletons, liches, thin undead |
| creeper | Faceless 4-short-leg biped | creepers, faceless creatures, bomb mobs |
| player | Full human model with arms | humans, knights, wizards, NPCs |
| villager | Big-nose robed humanoid | merchants, clerics, robed figures |
| witch | Tall robed humanoid | witches, mages, sorcerers |
| piglin | Pig-faced humanoid | pig warriors, piglin variants |
| iron_golem | Very large bulky humanoid | golems, giants, titans, robots, large brutes |
| snow_golem | Snowman body (3 stacked) | snowmen, stacked round creatures |
| enderman | Very tall, very thin humanoid | tall slender creatures, shadow beings |
| wither_skeleton | Tall dark skeleton | large skeletons, death knights |

### Quadruped / Animals
| Style | Looks like | Best for |
|-------|-----------|----------|
| cow | Medium 4-leg animal | cows, bulls, oxen, medium mammals |
| pig | Small round 4-leg | pigs, boars, small round animals |
| sheep | Woolly medium 4-leg | sheep, fluffy animals |
| wolf | Slim 4-leg canine | wolves, dogs, foxes, coyotes |
| horse | Tall 4-leg with long legs | horses, unicorns, zebras, donkeys, large elegant animals |
| llama | Tall 4-leg with long neck | llamas, alpacas, giraffes, long-neck animals |
| fox | Small slinky 4-leg | foxes, weasels, small predators |
| cat | Tiny slim 4-leg | cats, kittens, small felines |
| goat | Stocky 4-leg with horns | goats, rams, ibex |
| polar_bear | Large heavy 4-leg | bears, **elephants**, hippos, rhinos, large heavy mammals |
| ravager | Massive armored beast | war beasts, siege animals, massive monsters |
| hoglin | Large nether beast | boar-beasts, warthogs, large tusked animals |
| sniffer | Large friendly dinosaur-like | dinosaurs, large docile creatures |
| camel | Tall 4-leg with humps | camels, tall desert animals |
| turtle | Flat shelled 4-leg | turtles, tortoises, armored low creatures |

### Flying / Airborne
| Style | Looks like | Best for |
|-------|-----------|----------|
| phantom | Flat wide-wing flyer | **dragons**, pterodactyls, large flying creatures, bats |
| bee | Small round insect flyer | bees, beetles, small flying insects |
| parrot | Small bird | birds, parrots, small flying animals |
| bat | Tiny flapping creature | bats, tiny flyers |
| ghast | Large floating cube + tentacles | ghasts, jellyfish, floating horrors, large flying monsters |
| blaze | Floating rod body | blazes, fire elementals, floating magic entities |
| vex | Tiny winged humanoid | fairies, pixies, small winged humanoids |

### Aquatic
| Style | Looks like | Best for |
|-------|-----------|----------|
| squid | Tentacled sea creature | squid, octopus, tentacle monsters |
| dolphin | Sleek swimmer | dolphins, sharks, fish, whales |
| guardian | Spiky cube fish | guardians, pufferfish, spiky sea monsters |
| axolotl | Small amphibian | salamanders, newts, small water creatures |

### Arthropods / Crawlers
| Style | Looks like | Best for |
|-------|-----------|----------|
| spider | Wide 8-leg body | spiders, scorpions, crabs, large insects |
| silverfish | Tiny segmented worm | worms, centipedes, maggots |
| endermite | Tiny mite | mites, ticks, tiny bugs |

### Other
| Style | Looks like | Best for |
|-------|-----------|----------|
| slime | Bouncy translucent cube | slimes, jellies, blobs, oozes |
| chicken | Small bird with legs | chickens, small ground birds |
| rabbit | Tiny hopping animal | rabbits, mice, hamsters, tiny animals |
| frog | Small amphibian | frogs, toads |
| strider | Lava-walking long legs | striders, tall-leg walkers |
| warden | Massive eyeless brute | wardens, huge blind monsters, boss-level brutes |
"""

# ─── System Prompt for generate_mob ─────────────────────────────────────────────

GENERATE_MOB_SYSTEM_PROMPT = f"""You are an expert Minecraft Bedrock Edition entity designer. Given a user's description of a custom mob, you generate a COMPLETE, VALID Bedrock entity behavior JSON file.

## RULES
1. Output ONLY valid JSON — no markdown, no commentary, no code fences.
2. Use format_version "1.16.0".
3. The entity identifier MUST use a custom namespace: "custom:<mob_name>" (e.g., "custom:fire_dragon"). Use snake_case for the mob name.
4. Include ALL required fields: format_version, minecraft:entity.description, minecraft:entity.components.
5. Only use components from this valid list:
{json.dumps(VALID_COMPONENTS, indent=2)}

## CRITICAL: CHOOSING A BODY STYLE
You MUST pick the right body style for the mob. The style determines the 3D model
(geometry) used in-game. An elephant MUST NOT use a humanoid model!

Add a top-level key "_mob_forge_style" set to one of the style names below.
This key is stripped after generation — it is NOT part of the Bedrock spec.
{STYLE_GUIDE}

## CRITICAL: COLLISION BOX MUST MATCH STYLE
Use the collision_box dimensions that match your chosen style.
Here are the correct collision boxes for every style:
{json.dumps(STYLE_COLLISION_BOX, indent=2)}

For example:
- If you pick style "polar_bear" for an elephant, use "minecraft:collision_box": {{"width": 1.3, "height": 1.4}}
- If you pick style "phantom" for a dragon, use "minecraft:collision_box": {{"width": 0.9, "height": 0.5}}
- If you pick style "zombie" for a zombie, use "minecraft:collision_box": {{"width": 0.6, "height": 1.9}}

## CRITICAL: SIZE AND SCALE
The collision_box only affects the hitbox. To make the mob VISUALLY larger, you MUST use
"minecraft:scale" component. This is very important for large creatures!

Scale guidelines:
- Tiny mobs (rabbit, bat, chicken): "minecraft:scale": {{"value": 0.5}} to {{"value": 0.8}}
- Normal mobs (zombie, wolf, pig): "minecraft:scale": {{"value": 1.0}} (default, can omit)
- Large mobs (horse, polar_bear, cow): "minecraft:scale": {{"value": 1.2}} to {{"value": 1.5}}
- Very large mobs (elephant, giraffe, dragon): "minecraft:scale": {{"value": 2.0}} to {{"value": 3.0}}
- Massive mobs (iron_golem, warden, giant): "minecraft:scale": {{"value": 2.5}} to {{"value": 4.0}}

Also set the collision_box to match the REAL size of the mob:
- An elephant should be: "minecraft:collision_box": {{"width": 2.0, "height": 3.0}}, "minecraft:scale": {{"value": 2.5}}
- A giraffe should be: "minecraft:collision_box": {{"width": 1.5, "height": 4.0}}, "minecraft:scale": {{"value": 2.5}}
- A dragon should be: "minecraft:collision_box": {{"width": 2.5, "height": 2.0}}, "minecraft:scale": {{"value": 2.5}}

You are NOT limited to the collision box values in the table above. Those are just vanilla defaults.
Adjust them to match the creature's actual proportions.

## STAT RANGES (strictly enforce)
- Health (minecraft:health.value): 1–2048
- Attack (minecraft:attack.damage): 1–100
- Movement speed (minecraft:movement.value): 0.05–2.0

## DIFFICULTY PRESETS
- "easy": Low HP (10-30), low damage (2-5), slow speed (0.1-0.2)
- "medium": Medium HP (30-80), medium damage (5-15), normal speed (0.2-0.4)
- "hard": High HP (80-200+), high damage (15-40+), fast speed (0.3-0.6), extra abilities

## CUSTOM ITEM DROPS — _mob_forge_loot
Add a top-level key "_mob_forge_loot" with a list of item drops.
Each drop has: "item" (Minecraft item ID), "count_min", "count_max", "chance" (0.0–1.0).
This is NOT part of the Bedrock spec — our system reads it and generates a proper loot table.

Example — a dragon that drops diamonds and blaze rods:
"_mob_forge_loot": [
  {{"item": "minecraft:diamond", "count_min": 1, "count_max": 3, "chance": 1.0}},
  {{"item": "minecraft:blaze_rod", "count_min": 2, "count_max": 5, "chance": 0.5}}
]

Example — an elephant that drops leather and beef:
"_mob_forge_loot": [
  {{"item": "minecraft:leather", "count_min": 2, "count_max": 5, "chance": 1.0}},
  {{"item": "minecraft:cooked_beef", "count_min": 1, "count_max": 3, "chance": 0.8}}
]

ALWAYS include meaningful loot that makes sense for the mob! A fire dragon should drop blaze rods,
diamonds, fire charges. An ice creature should drop snowballs, packed ice. Match the theme!
If the user says "drops X", include that item.

## BEHAVIOR PATTERNS — MAKE MOBS ACTUALLY DO THINGS!
You MUST include proper AI behaviors so the mob is functional in-game.

### HOSTILE MOB (attacks players on sight):
Include ALL of these:
- "minecraft:behavior.nearest_attackable_target": {{"priority": 1, "entity_types": [{{"filters": {{"test": "is_family", "subject": "other", "value": "player"}}, "max_dist": 35}}]}}
- "minecraft:behavior.hurt_by_target": {{"priority": 1}}
- "minecraft:behavior.melee_attack": {{"priority": 3, "speed_multiplier": 1.2}}
- "minecraft:behavior.random_stroll": {{"priority": 6, "speed_multiplier": 0.8}}
- "minecraft:behavior.look_at_player": {{"priority": 7, "look_distance": 8.0}}
- "minecraft:behavior.random_look_around": {{"priority": 8}}
- "minecraft:navigation.walk": {{"can_pass_doors": true, "can_walk": true, "avoid_water": true}}
- "minecraft:movement.basic": {{}}
- "minecraft:jump.static": {{}}
- "minecraft:behavior.float": {{"priority": 0}}

### PASSIVE MOB (wanders peacefully, flees when attacked):
Include ALL of these:
- "minecraft:behavior.panic": {{"priority": 1, "speed_multiplier": 1.5}}
- "minecraft:behavior.random_stroll": {{"priority": 5, "speed_multiplier": 0.8}}
- "minecraft:behavior.look_at_player": {{"priority": 6, "look_distance": 6.0}}
- "minecraft:behavior.random_look_around": {{"priority": 7}}
- "minecraft:navigation.walk": {{"can_pass_doors": true, "can_walk": true, "avoid_water": true}}
- "minecraft:movement.basic": {{}}
- "minecraft:jump.static": {{}}
- "minecraft:behavior.float": {{"priority": 0}}

### RANGED ATTACKER (shoots projectiles like fire, arrows, etc.):
In addition to hostile mob behaviors, replace melee_attack with:
- "minecraft:shooter": {{"def": "minecraft:small_fireball"}}
- "minecraft:behavior.ranged_attack": {{"priority": 3, "attack_interval_min": 2.0, "attack_interval_max": 5.0, "attack_radius": 15.0}}

For fire breathing mobs, also add:
- "minecraft:fire_immune": {{}}

### EXPLODING MOB (like a creeper):
Replace melee_attack with:
- "minecraft:behavior.swell": {{"priority": 2, "start_distance": 2.5, "stop_distance": 6.0}}
- "minecraft:explode": {{"fuse_length": 1.5, "fuse_lit": true, "power": 3, "causes_fire": false, "destroy_affected_by_griefing": true}}

### AREA ATTACK (stomps, ground pound):
Add alongside melee:
- "minecraft:area_attack": {{"damage_range": 0.2, "damage_per_tick": 4, "cause": "entity_attack"}}

## FLYING MOBS
If the mob can fly, you MUST include these components:
- "minecraft:movement.fly": {{}} (instead of minecraft:movement.basic)
- "minecraft:navigation.fly": {{"can_path_over_water": true, "can_path_over_lava": true}}
- "minecraft:can_fly": {{}}
Pick a flying style (phantom, ghast, blaze, bee, bat, vex, parrot).

## AQUATIC MOBS
If the mob lives in water, include:
- "minecraft:navigation.swim": {{}}
- "minecraft:breathable": {{"breathes_water": true, "breathes_air": false}}
- "minecraft:movement.sway": {{}}
Pick an aquatic style (squid, dolphin, guardian, axolotl, turtle).

## REFERENCE EXAMPLES
Vanilla zombie (hostile humanoid with full AI):
{json.dumps(ZOMBIE_EXAMPLE, indent=2)}

Vanilla creeper (exploding mob):
{json.dumps(CREEPER_EXAMPLE, indent=2)}

## OUTPUT FORMAT
Return ONLY the JSON object below. The "_mob_forge_style" and "_mob_forge_loot" keys are processed
by our system and stripped — they are NOT part of the Bedrock spec.
{{
  "_mob_forge_style": "<style_name>",
  "_mob_forge_loot": [
    {{"item": "minecraft:diamond", "count_min": 1, "count_max": 3, "chance": 1.0}}
  ],
  "format_version": "1.16.0",
  "minecraft:entity": {{
    "description": {{
      "identifier": "custom:<mob_name>",
      "is_spawnable": true,
      "is_summonable": true,
      "is_experimental": false
    }},
    "components": {{
      // health, attack, movement, scale, collision_box, loot, and ALL relevant behaviors
      // Include minecraft:loot with the path "loot_tables/entities/<mob_name>.json"
    }}
  }}
}}

IMPORTANT RULES:
1. "_mob_forge_style" is MANDATORY. Pick the best matching style.
2. "_mob_forge_loot" is MANDATORY. Include at least 1 meaningful drop.
3. ALWAYS include full AI behaviors (targeting, attacking, wandering).
4. Include "minecraft:loot": {{"table": "loot_tables/entities/<mob_name>.json"}} in components.
5. Do NOT include extra keys like "mob_metadata", "metadata", "notes".
6. The identifier should use snake_case (e.g., "custom:fire_dragon", "custom:jungle_elephant").
"""

# ─── System Prompt for generate_texture ─────────────────────────────────────────

GENERATE_TEXTURE_SYSTEM_PROMPT = """You are a pixel artist specializing in Minecraft Bedrock Edition mob textures.
You create pixel-art texture UV maps in the Minecraft style.

Given a mob description, body style, and color palette, generate a pixel-by-pixel color grid
for a {width}x{height} texture.

## HOW MINECRAFT TEXTURES WORK
Minecraft textures are UV-unwrapped flat images that wrap around 3D box-shaped body parts.
Each body part (head, body, legs, arms, etc.) has a specific rectangular region on the texture.
The texture is NOT a front-view picture of the mob — it's an UNWRAPPED SKIN.

## TEXTURE LAYOUT BY BODY TYPE
The "style" tells you what body parts exist and roughly where they go on the texture:

### Humanoid styles (zombie, skeleton, player, villager, etc.) — 64x64
- Top-left (0,0 to 32,16): Head (front face at ~8,8 to 16,16 — put eyes here)
- Middle-left (0,16 to 40,32): Body torso
- Bottom-left (0,32 to 16,48): Right leg
- Bottom-right (16,48 to 32,64): Left leg
- Right side (40,16 to 56,32): Right arm
- Far right (32,48 to 48,64): Left arm

### Quadruped styles (cow, pig, sheep, wolf, horse, polar_bear, etc.) — 64x32
- Top-left (0,0 to 24,8): Head (face region — put eyes, nose, ears)
- Middle (0,8 to 34,18): Body (main torso — largest area, use main color + shading)
- Bottom-left (0,18 to 12,32): Front legs
- Bottom-right (24,18 to 36,32): Back legs

### Flying styles (phantom, bat, ghast, blaze, etc.)
- Top: Head/face region
- Middle: Body/wing membrane (use accent colors for wing patterns)
- Bottom: Tail or tentacles

### Spider/arthropod — 64x32
- Top row: Head with multiple eyes (use red/bright dots for eyes)
- Middle: Thorax/abdomen
- Bottom strips: 8 leg segments

### Slime — 64x32
- Outer layer: semi-translucent green/color
- Inner: darker core with simple face (2 eyes + mouth)

## RULES
1. Output ONLY valid JSON — no markdown, no commentary, no code fences.
2. The grid is a 2D array of hex color strings, {height} rows x {width} columns.
3. Use ONLY colors from the provided palette (or slight brightness variations ±15%).
4. Use a darker shade for part boundaries/edges (1-2px borders between body parts).
5. Place EYES in the correct face region for the body type.
6. Make the mob RECOGNIZABLE — an elephant should have gray skin with big ears;
   a dragon should have scales and wing patterns; a pig should be pink with a snout.
7. DO NOT just fill the texture with a single color. Add detail, shading, and features.

## OUTPUT FORMAT
Return a JSON object:
{{
  "grid": [
    ["#hex", "#hex", ...],
    ["#hex", "#hex", ...],
    ...
  ],
  "description": "Brief description of the texture"
}}"""

# ─── Template Generators ────────────────────────────────────────────────────────

def generate_linked_manifests(pack_name: str, pack_description: str = "") -> tuple[dict, dict]:
    """
    Generate a behavior pack AND resource pack manifest that are
    cross-linked via the 'dependencies' array so Minecraft loads both.

    Returns:
        (bp_manifest, rp_manifest)
    """
    bp_uuid = str(uuid.uuid4())
    bp_module_uuid = str(uuid.uuid4())
    rp_uuid = str(uuid.uuid4())
    rp_module_uuid = str(uuid.uuid4())

    bp_manifest = {
        "format_version": 2,
        "header": {
            "name": pack_name,
            "description": pack_description or f"{pack_name} - Custom Mob Behavior Pack",
            "uuid": bp_uuid,
            "version": [1, 0, 0],
            "min_engine_version": [1, 16, 0]
        },
        "modules": [
            {
                "type": "data",
                "uuid": bp_module_uuid,
                "version": [1, 0, 0]
            }
        ],
        "dependencies": [
            {
                "uuid": rp_uuid,
                "version": [1, 0, 0]
            }
        ]
    }

    rp_manifest = {
        "format_version": 2,
        "header": {
            "name": f"{pack_name} Resources",
            "description": pack_description or f"{pack_name} - Custom Mob Resource Pack",
            "uuid": rp_uuid,
            "version": [1, 0, 0],
            "min_engine_version": [1, 16, 0]
        },
        "modules": [
            {
                "type": "resources",
                "uuid": rp_module_uuid,
                "version": [1, 0, 0]
            }
        ],
        "dependencies": [
            {
                "uuid": bp_uuid,
                "version": [1, 0, 0]
            }
        ]
    }

    return bp_manifest, rp_manifest


def generate_lang_file(mobs: list[tuple[str, str]]) -> str:
    """
    Generate a texts/en_US.lang file for entity & spawn egg display names.

    Args:
        mobs: List of (identifier, display_name) tuples.
              e.g. [("custom:fire_imp", "Fire Imp")]
    Returns:
        Contents of en_US.lang as a string.
    """
    lines = []
    for identifier, display_name in mobs:
        lines.append(f"entity.{identifier}.name={display_name}")
        lines.append(f"item.spawn_egg.entity.{identifier}.name=Spawn {display_name}")
    return "\n".join(lines) + "\n"


def generate_spawn_rules(identifier: str) -> dict:
    """
    Generate a basic spawn_rules JSON so the entity can be summoned
    and optionally spawns naturally.
    """
    return {
        "format_version": "1.8.0",
        "minecraft:spawn_rules": {
            "description": {
                "identifier": identifier,
                "population_control": "monster"
            },
            "conditions": [
                {
                    "minecraft:spawns_on_surface": {},
                    "minecraft:brightness_filter": {
                        "min": 0,
                        "max": 7,
                        "adjust_for_weather": True
                    },
                    "minecraft:weight": {
                        "default": 80
                    },
                    "minecraft:herd": {
                        "min_size": 1,
                        "max_size": 2
                    },
                    "minecraft:biome_filter": {
                        "test": "has_biome_tag",
                        "operator": "==",
                        "value": "overworld"
                    }
                }
            ]
        }
    }


def generate_client_entity(identifier: str, mob_name: str, style: str = "biped") -> dict:
    """Generate a resource pack client entity definition with the right vanilla geometry."""
    geometry = STYLE_GEOMETRY_MAP.get(style, "geometry.humanoid.custom")

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
                    "default": geometry
                },
                "render_controllers": ["controller.render.default"],
                "spawn_egg": {
                    "base_color": "#4A7023",
                    "overlay_color": "#2E4F1E"
                }
            }
        }
    }
