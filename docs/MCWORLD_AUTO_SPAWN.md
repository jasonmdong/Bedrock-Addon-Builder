# Testing the Pack in the MC World: Auto-Spawn Explained

This document explains how the Bedrock Addon Builder gets your custom entity to spawn automatically when you load the built `.mcworld` file, and how to test it reliably.

---

## Table of Contents

1. [Overview](#overview)
2. [How the Spawn System Works](#how-the-spawn-system-works)
3. [Player Detection and Timing](#player-detection-and-timing)
4. [Where the Code Lives](#where-the-code-lives)
5. [How the .mcworld Is Built](#how-the-mcworld-is-built)
6. [Testing the Pack in the MC World](#testing-the-pack-in-the-mc-world)
7. [Inside the .mcworld File](#inside-the-mcworld-file)
8. [Troubleshooting](#troubleshooting)

---

## Overview

When you build an addon and choose **mcworld** (or download the `.mcworld` from a bundle), the world is set up so that:

- **2 seconds** after you join the world, your custom mob(s) are **summoned right on your position** (`~ ~ ~`).
- This happens **once per world load**: the game uses a **tag** and a **scoreboard** so it doesn’t spawn again every tick.
- **Cheats are enabled** in that world so the `/summon` command is allowed.

The same spawn logic is included in the **behavior pack** itself, so it also works if you install the **.mcpack** or **.mcaddon** into any world (as long as that world has cheats enabled).

---

## How the Spawn System Works

### 1. Tick functions (Bedrock)

Minecraft Bedrock runs **functions** listed in `tick.json` **every gameplay tick** (20 times per second). The behavior pack contains:

- **`functions/tick.json`** – tells the game to run `spawn_mobs` every tick.
- **`functions/spawn_mobs.mcfunction`** – the commands that detect the player, wait 2 seconds, then summon and mark done.

So the game doesn’t “know” the exact moment the player “spawns in” in a special way; it just runs `spawn_mobs` every tick and the commands inside decide when to act.

### 2. What `spawn_mobs.mcfunction` does (step by step)

Each tick, the following runs in order:

| Step | Command | Purpose |
|------|---------|--------|
| 1 | `scoreboard objectives add addon_spawn dummy` | Ensure the “timer” objective exists (fails harmlessly if it already does). |
| 2 | `scoreboard players add @a[tag=!mob_spawned] addon_spawn 1` | For every player **without** the `mob_spawned` tag, add 1 to their `addon_spawn` score. So each such player’s score increases by 1 every tick. |
| 3 | `execute as @a[tag=!mob_spawned,scores={addon_spawn=40..},c=1] at @s run summon <identifier> ~ ~ ~` | For **one** player who still has no tag and has score ≥ 40, run `summon` **at that player’s position** (`at @s`), so the mob appears at `~ ~ ~` relative to them (i.e. on the player). Repeated for each custom entity in your spec. |
| 4 | `tag @a[scores={addon_spawn=40..}] add mob_spawned` | Give the `mob_spawned` tag to all players with score ≥ 40. Those players will no longer be selected by `tag=!mob_spawned`, so they stop getting score and never trigger summon again. |

So:

- **“When the player spawns in”** = as soon as they are in `@a`. The tick runs every 1/20th of a second, so within one tick of joining, they start getting `addon_spawn` +1 per tick.
- **“When to load the mob”** = after **40 ticks** (2 seconds). That’s when `scores={addon_spawn=40..}` is true and we run `summon` and add the tag.

No separate “player spawn event” is used; it’s all driven by tick + scoreboard + tag.

### 3. Why 2 seconds (40 ticks)?

- **Gameplay tick** in Bedrock is 20 ticks per second, so **40 ticks = 2 seconds**.
- The first ticks can run **before the world is fully loaded**; waiting 2 seconds gives the world and the player time to be in a good state before running `summon` at the player’s feet.
- Shorter delays can sometimes cause odd behavior (e.g. spawning in the void or wrong position); 2 seconds is a safe default.

### 4. Why spawn at `~ ~ ~`?

- `execute as <player> at @s run summon ... ~ ~ ~` runs the summon **at the player’s current position**.
- So the entity appears **right on the player** (same block or very close), which makes it easy to see and confirms the system is working.

---

## Player Detection and Timing

- **Who is tracked?** Any player in the world (`@a`) who does **not** have the tag `mob_spawned`.
- **How we “track” them:** We don’t listen to a “player joined” event. Every tick we:
  - Add 1 to `addon_spawn` for all `@a[tag=!mob_spawned]`.
  - Once a player’s `addon_spawn` reaches 40, we run the summon for that player (with `c=1` so only one player is used for the summon) and then tag all players with score ≥ 40 so they never trigger again.
- **When the mob loads:** Exactly when that player’s score first hits 40 or above, i.e. **2 seconds after they started being counted** (which is effectively 2 seconds after they were in the world and had no tag).

So:

- **First time you load the world:** You have no tag; your score goes 0 → 1 → 2 → … → 40 over 2 seconds; then the mob is summoned and you get the tag.
- **If you leave and rejoin the same world:** You still have the tag, so you’re never selected again; no second spawn.
- **If you create a new world with the same pack:** You have no tag in the new world, so after 2 seconds the mob spawns again.

---

## Where the Code Lives

Spawn logic is generated in **two** places so both the standalone packs and the .mcworld behave the same:

| Location | When it runs | What it does |
|----------|----------------|--------------|
| **`backend/core/builders.py`** | When building the addon (`patch_behavior_pack`) | Creates `functions/spawn_mobs.mcfunction` and `functions/tick.json` inside the **behavior pack** that gets zipped into `.mcpack` and `.mcaddon`. |
| **`backend/core/packaging.py`** | When building a **.mcworld** (`_spawn_entities_in_world`) | Writes the same `spawn_mobs.mcfunction` and `tick.json` into the behavior pack **inside the world folder** before zipping the .mcworld. |

So whether you use the .mcworld or install the .mcpack/.mcaddon into another world, the behavior pack already contains the same spawn logic.

---

## How the .mcworld Is Built

When you choose **mcworld** (or build a bundle that includes it), the backend:

1. **Starts from a template world**  
   Copies a base world from `data/templates/` (e.g. `base_world` or `base_world.mcworld`).

2. **Puts the addon packs into the world**  
   - Behavior pack → `world_root/behavior_packs/custom_addon_beh/`  
   - Resource pack → `world_root/resource_packs/custom_addon_res/`  
   So the .mcworld already contains the packs (including their `functions/` and entity files).

3. **Links the packs to the world**  
   Writes:
   - `world_behavior_packs.json` – list of `{ "pack_id": "<behavior pack UUID>", "version": [1,0,0] }`
   - `world_resource_packs.json` – same for the resource pack  
   so the world automatically enables these packs when you open it.

4. **Enables cheats**  
   Patches `level.dat` (NBT) to set:
   - `commandsEnabled` = 1  
   - `cheatsEnabled` = 1  
   so that the tick function’s `/summon` is allowed.

5. **Ensures spawn logic is in the behavior pack**  
   `_spawn_entities_in_world` writes `spawn_mobs.mcfunction` and `tick.json` into `behavior_packs/custom_addon_beh/functions/` (same as in the pack built by `builders.py`).

6. **Zips the world**  
   The resulting `.mcworld` is a ZIP of the world folder (with `level.dat`, `levelname.txt`, `world_behavior_packs.json`, `world_resource_packs.json`, `behavior_packs/`, `resource_packs/`, etc.).

So when you “load the mcworld,” you’re opening a world that already has your packs applied and cheats on, and the tick function runs as soon as the world is running.

---

## Testing the Pack in the MC World

### Prerequisites

- Minecraft Bedrock Edition (Windows 10/11, Xbox, or mobile).
- A built addon with at least one mob; build with **mcworld** or download the `.mcworld` from the bundle.

### Step-by-step test

1. **Build the addon**  
   In the app, configure your mob(s) and run **Build**. Choose **mcworld** as the build mode (or use the bundle and take the `.mcworld` from the ZIP).

2. **Get the .mcworld file**  
   - If the UI offers a direct “Download .mcworld” link, use it.  
   - Or download the bundle ZIP and extract the file named like `<short_name>.mcworld` (e.g. `camel_custom.mcworld`).

3. **Import into Minecraft**  
   - **Windows (Store/PC):** Double-click the `.mcworld` file; it should open with Minecraft and prompt to import the world.  
   - Or in Minecraft: **Play** → **Worlds** → **Import** (or “Import World”) and select the `.mcworld` file.

4. **Open the world**  
   Start the imported world. The world name is typically “Add-on: &lt;display_name&gt;” (e.g. “Add-on: Camel Custom”).

5. **Wait 2 seconds**  
   Do not change dimension or leave the world. After about **2 seconds**, the custom entity should be summoned **on your position** (you may need to step back to see it clearly).

6. **Verify**  
   - You should see your custom mob (model/texture from the resource pack, behavior from the behavior pack).  
   - It should only spawn once per world load. Reloading the world (leave and re-enter the same save) should not spawn a second set; creating a **new** world with the same pack will trigger spawn again after 2 seconds.

### What you should see

- **In the world:** After ~2 seconds, one (or more) of your custom mobs at your location.  
- **In the build log (if you look at server logs):** Lines like `[WORLD] Enabled cheats/commands in level.dat` and `[WORLD] Will auto-spawn <identifier> near player on world load`.

### Optional: manual summon

If cheats are enabled (they are in our .mcworld), you can also run in chat:

```text
/summon <identifier>
```

Example: if your entity identifier is `custom:camel_custom`, run:

```text
/summon custom:camel_custom
```

The entity will spawn at your feet. This is useful to test the entity without waiting for the auto-spawn.

---

## Inside the .mcworld File

The `.mcworld` file is a ZIP. Its structure looks like this (conceptually):

```text
level.dat
levelname.txt
world_behavior_packs.json
world_resource_packs.json
world_icon.png (if present)
behavior_packs/
  custom_addon_beh/
    manifest.json
    entities/
      <short_name>.entity.json
    functions/
      tick.json
      spawn_mobs.mcfunction
    texts/
      en_US.lang
resource_packs/
  custom_addon_res/
    manifest.json
    entity/
      <short_name>.client.entity.json
    textures/
      ...
    ...
```

- **`world_behavior_packs.json`** / **`world_resource_packs.json`** tell the game which packs to load (by UUID).  
- **`behavior_packs/custom_addon_beh/functions/`** is where the 2-second delayed spawn is defined.  
- **`level.dat`** is the one we patch so cheats/commands are on.

You can rename `.mcworld` to `.zip` and open it in a file explorer to inspect these files; rename back to `.mcworld` before importing into Minecraft.

---

## Troubleshooting

| Problem | What to check |
|--------|----------------|
| **Mob never appears** | 1) Wait at least 2–3 seconds after the world loads. 2) Confirm you’re testing the **.mcworld** (or a world where you added the **behavior** pack and have cheats on). 3) Try `/summon <your_identifier>` in chat; if that fails, the entity isn’t registered (check pack applied and identifier spelling). |
| **Mob spawns underground or in the void** | Current logic spawns at `~ ~ ~` (player position). If you’re in the void or inside a block when the 2s timer fires, the mob can end up there. Wait until you’re on solid ground before the 2 seconds elapse. |
| **Mob spawns many times** | That would mean the tag/scoreboard logic isn’t running (e.g. pack not applied, or tick.json not present). Ensure you’re using a freshly built .mcworld and that the behavior pack is enabled for that world. |
| **“Cheats are disabled” when using /summon** | Our .mcworld has cheats enabled. If you copied the pack into another world, enable **Activate Cheats** in that world’s settings. |
| **.mcworld fails to build** | You’ll see a warning like “.mcworld could not be created because no base world template was found.” Add a world template (e.g. `data/templates/base_world` or `base_world.mcworld`) as described in the project docs. |

---

## Summary

- The game runs **`spawn_mobs` every tick** via **`tick.json`**.
- **Player “spawn”** is not a special event; we just count **any player without the `mob_spawned` tag** and add 1 to their **`addon_spawn`** score every tick.
- **When to load the mob:** when that score reaches **40** (2 seconds). Then we **summon** at the player (`~ ~ ~`) and give them the **`mob_spawned`** tag so it only happens once per load.
- The **.mcworld** is a preconfigured world with your packs embedded, pack links set, and cheats enabled, so opening it and waiting ~2 seconds is enough to test the auto-spawn. For quick checks, use **/summon &lt;identifier&gt;** in chat.
