# Client entity animation bugs — reference

This document records **Bedrock client-side animation failures** seen with custom mobs in Bedrock Addon Builder: what players observe, why it happens in Minecraft’s engine, and how the builder mitigates it.

Official background:

- [Animations overview](https://learn.microsoft.com/en-us/minecraft/creator/documents/animations/animationsoverview?view=minecraft-bedrock-stable) — `animations` + `scripts.animate`, blend weights vs plain string entries.
- [Client entity JSON introduction](https://learn.microsoft.com/en-us/minecraft/creator/reference/content/entityreference/examples/cliententitydocumentation/cliententitydocumentationintroduction?view=minecraft-bedrock-stable) — `scripts.pre_animation`, `scripts.animate`, `scale`.

Vanilla examples in [Mojang/bedrock-samples](https://github.com/Mojang/bedrock-samples) (e.g. `resource_pack/entity/pig.entity.json`) use simple `scripts.animate` rows; many fliers (phantom, bat) rely heavily on **animation controllers** instead.

**Implementation in this repo:** `backend/build/builders.py` — `_build_scripts_animate_entries()`, `_inject_locomotion_pre_animation()`, `patch_resource_pack()`; `MCP/mcp_server/tools/build_mcworld.py` — `_build_client_entity()`.

---

## Symptom → likely cause → mitigation

| Symptom | Likely cause | Builder mitigation |
|--------|----------------|-------------------|
| **Mob invisible** | Invalid `minecraft:client_entity` / `description` (e.g. wrong `min_engine_version` type or value above pack). | Do **not** set `min_engine_version` in generated client entity unless it is a valid **string** and matches the pack; see comment in `patch_resource_pack()`. |
| **No animations at all** | Entire `scripts` block rejected (bad Molang in `pre_animation` / `animate`), or no `animations` map / empty `anim_refs`. | Prefer **simple** Molang (`math.max` nesting, avoid risky functions). Ensure procedural + LLM clips populate `animation_json` before `anim_refs` is built. |
| **Only idle plays; walk/fly never show** | (1) **Additive blending:** idle as a **plain string** stays at weight 1.0 while walk uses a **small** blend (`query.modified_move_speed` often ≈ 0 on custom entities). (2) **Fly mask too strict:** e.g. treating hover as “grounded” so fly weight is always 0. | (1) **`pre_animation`:** `variable.bab_locomotion = max(modified_move_speed, max(is_moving, ground_speed))`; walk uses `max(query.modified_move_speed, variable.bab_locomotion)`. (2) **Winged walkers:** ground vs air split uses `query.is_on_ground` plus `vertical_speed` thresholds; fly includes **`!query.is_on_ground`** so hover still gets fly. |
| **Idle + walk + fly all at full strength** | Multiple clips listed as **plain strings** in `scripts.animate` (each weight 1.0). | For **winged walkers** (has both fly and walk clips, not pure flier): idle / walk / fly use **dict entries** with Molang weights; ground vs air masks are mutually consistent. |
| **Attack/breath OK but locomotion dead** | Locomotion multiplied by “not attacking” Molang; stuck or noisy `variable.attacking` / `attack_time` zero walk/fly. | **Do not** gate idle/walk/fly with attack masks; gate **attack clips** only with `_MOLANG_ATTACK_PLAY`. |
| **Controllers “eat” clips** | Putting **animation controllers** in the client entity `animations` map auto-starts them; they can conflict with direct `scripts.animate` rows. | Controllers are **written** to `animation_controllers/*.json` for LLM/remap use but are **not** added to `anim_refs` / client `animations` for auto-init (see comments in `patch_resource_pack()`). |

---

## Technical notes

### Plain string vs blend dict

Per the Animations overview, each `scripts.animate` entry is either:

- A **string** — animation plays at full blend weight (1.0).
- A **dict** — e.g. `{ "walk": "query.modified_move_speed" }` — weight is the Molang expression (pig pattern).

Stacking several **strings** means **all** of those animations apply at full weight unless clips use disjoint bones.

### Why `query.modified_move_speed` fails custom mobs

On many **custom** entities the client still evaluates `scripts.animate`, but **`query.modified_move_speed`** can stay near **zero** while the mob is clearly moving. Merging **`query.is_moving`** and **`query.ground_speed`** in **`pre_animation`** (`variable.bab_locomotion`) and using that in walk blends matches the spirit of the pig pattern while remaining compatible with weak speed queries.

### Winged walker (e.g. dragon)

**Pure flier** (wings, no leg bones): `pure_flier=True` — main fly clip as a string; no walk row.

**Winged walker** (legs + fly clip): both walk and fly exist. Ground locomotion and air locomotion must use **non-overlapping** masks:

- **Ground:** `query.is_on_ground && abs(vertical_speed) < 0.15` (idle + walk).
- **Air:** `!query.is_on_ground || abs(vertical_speed) >= 0.15` (fly).

Earlier bugs used a loose “groundish” mask (`is_on_ground || low vertical_speed`), which kept **fly weight at zero** while **hovering** (vertical ≈ 0 but not on ground), so only idle appeared to work.

### `anim_time_update` stripping

`_sanitize_animations()` removes `anim_time_update` from walk/run clips to reduce jitter on custom pathfinding. Walk cycles then follow default timing; bone keyframes should still animate when blend weight > 0.

---

## Debugging checklist

1. **Resource pack** `entity/{short_name}.entity.json`: `minecraft:client_entity.description.animations` maps short names → full animation IDs; `scripts.animate` list matches those short names.
2. **`scripts.pre_animation`:** should include `variable.bab_locomotion = ...` when walk uses `variable.bab_locomotion`.
3. **Animation JSON:** `loop`, `animation_length`, bone names match geometry; no typos on bone keys.
4. **Behavior vs client identifier:** same entity id in behavior pack and client entity file.
5. Compare to vanilla pig: [pig.entity.json](https://github.com/Mojang/bedrock-samples/blob/main/resource_pack/entity/pig.entity.json) (`setup` + `{ "walk": "query.modified_move_speed" }`).

For the full pipeline, see [ANIMATION_PIPELINE.md](./ANIMATION_PIPELINE.md). For broader animation debugging, see [ANIMATION_DEBUG_GUIDE.md](../ANIMATION_DEBUG_GUIDE.md) in the repo root.

---

## Changelog (high level)

- **Invisible mob:** invalid `min_engine_version` on client entity — avoided in builder.
- **All clips stacked:** winged walkers switched from all-string `animate` rows to weighted dicts + ground/air split.
- **Only idle:** fixed fly mask + `bab_locomotion` + removed attack gating on locomotion.
- **No clips:** avoided fragile Molang; kept `pre_animation` to a single `math.max` assignment line.
