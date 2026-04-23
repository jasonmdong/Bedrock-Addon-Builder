"""Regression tests for dynamic prompt assembly (no pytest required)."""

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

os.environ["MCTOOLS_ENABLED"] = "false"

from backend.core.core import DEFAULTS
from backend.llm.dynamic_context import build_dynamic_context
from backend.llm.llm import _get_full_system_prompt, _get_legacy_system_prompt_for_tests, _has_custom_geometry
from backend.llm.prompt_intents import extract_prompt_intents


def test_dynamic_prompt_smaller_than_legacy_for_common_requests():
    user_prompt = "Make this mob fly and breathe fire while keeping its current shape."
    profile = extract_prompt_intents(user_prompt, "entity_logic_ai")
    dyn = build_dynamic_context(user_prompt, "entity_logic_ai")

    legacy = _get_legacy_system_prompt_for_tests(user_prompt, DEFAULTS, "entity_logic_ai", None, dyn, profile)
    dynamic, _, _ = _get_full_system_prompt(user_prompt, DEFAULTS, "entity_logic_ai", None, dyn, profile)

    assert len(dynamic) < len(legacy)
    # Ensure the new prompt still contains core guidance + injected intent
    assert "CRITICAL RULES" in dynamic
    assert "STRUCTURED USER INTENT" in dynamic


def test_prompt_includes_loot_section_only_when_relevant():
    base_spec = dict(DEFAULTS)

    p_no_loot = "Increase hp by 10."
    prof_no = extract_prompt_intents(p_no_loot, "entity_logic_ai")
    dyn_no = build_dynamic_context(p_no_loot, "entity_logic_ai")
    prompt_no, _, _ = _get_full_system_prompt(p_no_loot, base_spec, "entity_logic_ai", None, dyn_no, prof_no)
    assert "LOOT DROPS" not in prompt_no

    p_loot = "Make it drop diamonds on death."
    prof_yes = extract_prompt_intents(p_loot, "entity_logic_ai")
    dyn_yes = build_dynamic_context(p_loot, "entity_logic_ai")
    prompt_yes, _, _ = _get_full_system_prompt(p_loot, base_spec, "entity_logic_ai", None, dyn_yes, prof_yes)
    assert "LOOT DROPS" in prompt_yes


def test_custom_geometry_triggers_preservation_context():
    spec = dict(DEFAULTS)
    spec["geometry"] = "geometry.custom_test"
    spec["geometry_json"] = {
        "format_version": "1.12.0",
        "minecraft:geometry": [
            {
                "description": {"identifier": "geometry.custom_test", "texture_width": 64, "texture_height": 64},
                "bones": [{"name": "root", "pivot": [0, 0, 0]}],
            }
        ],
    }
    assert _has_custom_geometry(spec) is True

    # A visual/appearance prompt should trigger preservation when custom geo exists
    user_prompt = "Change its texture color to blue."
    prof = extract_prompt_intents(user_prompt, "entity_logic_ai")
    dyn = build_dynamic_context(user_prompt, "entity_logic_ai")
    prompt, _, _ = _get_full_system_prompt(user_prompt, spec, "entity_logic_ai", None, dyn, prof)

    assert "PRESERVE GEOMETRY ON ITERATION" in prompt

    # A pure stat change should NOT trigger preservation even with custom geo
    stat_prompt = "Increase speed a little."
    prof2 = extract_prompt_intents(stat_prompt, "entity_logic_ai")
    dyn2 = build_dynamic_context(stat_prompt, "entity_logic_ai")
    prompt2, _, _ = _get_full_system_prompt(stat_prompt, spec, "entity_logic_ai", None, dyn2, prof2)

    assert "PRESERVE GEOMETRY ON ITERATION" not in prompt2


if __name__ == "__main__":
    test_dynamic_prompt_smaller_than_legacy_for_common_requests()
    test_prompt_includes_loot_section_only_when_relevant()
    test_custom_geometry_triggers_preservation_context()
    print("All dynamic prompt tests passed.")

