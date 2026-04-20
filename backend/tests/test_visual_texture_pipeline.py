from backend.llm.llm import (
    _is_visual_only_edit,
    _should_attempt_geometry_autofetch,
)
from backend.llm.prompt_intents import PromptIntentProfile
from backend.llm.texture_gen import _parse_texture_directives


def test_parse_texture_directives_reads_face_palette_from_instruction():
    role_overrides, face_overrides, face_palettes, extra_patterns = _parse_texture_directives(
        ["bottom red and blue"]
    )
    assert role_overrides == {}
    assert face_overrides == {}
    assert face_palettes["bottom"] == [(200, 40, 40), (40, 80, 200)]
    assert extra_patterns == []


def test_parse_texture_directives_reads_face_override_from_texture_hint():
    role_overrides, face_overrides, face_palettes, extra_patterns = _parse_texture_directives(
        None,
        texture_hint="paint the underside dark red",
    )
    assert role_overrides == {}
    assert face_palettes == {}
    assert face_overrides["bottom"] == (140, 20, 20)
    assert extra_patterns == []


def test_visual_only_edit_skips_geometry_autofetch_for_same_mob():
    before = {
        "display_name": "Shipwreck",
        "geometry": "geometry.shipwreck",
        "texture_hint": "weathered wood",
    }
    after = {
        "display_name": "Shipwreck",
        "geometry": "geometry.shipwreck",
        "texture_hint": "bottom red and blue",
    }

    assert _is_visual_only_edit(before, after) is True
    should_generate, reason = _should_attempt_geometry_autofetch(before, after)
    assert should_generate is False
    assert "same mob identity" in reason


def test_geometry_requested_still_allows_autofetch():
    before = {
        "display_name": "Shipwreck",
        "geometry": "geometry.shipwreck",
        "texture_hint": "weathered wood",
    }
    after = {
        "display_name": "Shipwreck",
        "geometry": "geometry.shipwreck",
        "texture_hint": "bottom red and blue",
    }
    intent = PromptIntentProfile(
        category="entity_logic_ai",
        constraints={"geometry_requested": True},
    )

    should_generate, _ = _should_attempt_geometry_autofetch(
        before,
        after,
        intent_profile=intent,
    )
    assert should_generate is True
