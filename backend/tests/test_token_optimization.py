from backend.llm.llm import (
    _get_full_system_prompt,
    _prepare_spec_for_llm,
    _should_use_compact_prompt,
)
from backend.llm.prompt_intents import extract_prompt_intents


SPEC = {
    "identifier": "custom:test_mob",
    "display_name": "Test Mob",
    "short_name": "test_mob",
    "hp": 20,
    "damage": 5,
    "speed": 0.25,
    "scale": 1.0,
    "geometry": "geometry.test_mob",
    "texture_hint": "gray",
    "texture_instructions": [],
    "color_rgb": [128, 128, 128],
    "components": {
        "minecraft:behavior.melee_attack": {"priority": 3},
        "minecraft:behavior.random_stroll": {"priority": 5},
    },
}


def test_compact_prompt_enabled_for_visual_edit():
    profile = extract_prompt_intents("make the texture blue", "entity_logic_ai")
    assert _should_use_compact_prompt("entity_logic_ai", profile) is True

    prompt = _get_full_system_prompt("entity_logic_ai", None, None, profile)
    assert "COMPACT EDIT MODE" in prompt
    assert "Schema:" not in prompt


def test_prepare_spec_for_visual_edit_omits_components():
    profile = extract_prompt_intents("make the texture blue", "entity_logic_ai")
    serialized = _prepare_spec_for_llm(SPEC, profile)
    assert '"components"' not in serialized
    assert '"texture_hint"' in serialized
    assert '"geometry"' in serialized


def test_prepare_spec_for_stat_edit_keeps_stats_and_omits_texture_fields():
    profile = extract_prompt_intents("double the health", "entity_logic_ai")
    serialized = _prepare_spec_for_llm(SPEC, profile)
    assert '"hp"' in serialized
    assert '"damage"' in serialized
    assert '"texture_hint"' not in serialized
    assert '"components"' not in serialized
