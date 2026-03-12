"""Tests for MCP context retrieval and structured prompt intent extraction."""

import os

os.environ["MCTOOLS_ENABLED"] = "false"

from backend.llm.llm import _get_full_system_prompt
from backend.llm.mcp_context import (
    MCPContext,
    _detect_template_type,
    _extract_errors,
    _format_for_prompt,
    _should_fetch_templates,
    _spec_to_validation_content,
    _truncate,
    is_retryable,
    mcp_validate_sync,
    retrieve_context_sync,
)
from backend.llm.prompt_intents import extract_prompt_intents


def test_disabled_returns_empty_context():
    ctx = retrieve_context_sync("make it fly", "entity_logic_ai", {"hp": 20})
    assert ctx is not None
    assert ctx.available is False
    assert ctx.has_content is False
    assert ctx.source_tools == []
    assert ctx.retrieval_ms == 0


def test_disabled_validation_returns_unavailable():
    val = mcp_validate_sync({"hp": 20})
    assert val is not None
    assert val.valid is True
    assert val.available is False
    assert val.errors == []


def test_prompt_intents_extract_constraints_and_template_hint():
    profile = extract_prompt_intents(
        "keep geometry the same but make it a flying crystal rhino with wings",
        "entity_logic_ai",
    )
    assert profile.constraints["preserve_geometry"] is True
    assert any(signal.name == "flying" for signal in profile.signals)
    assert "crystal" in profile.style_keywords
    assert profile.template_hint in {"large_animal", "flying"}


def test_template_heuristics_use_intent_profile():
    profile = extract_prompt_intents("create a spider model with longer legs", "entity_logic_ai")
    assert _should_fetch_templates("create a spider model with longer legs", "entity_logic_ai", profile) is True
    assert _detect_template_type("create a spider model with longer legs", "entity_logic_ai", profile) == "insect"

    non_geo = extract_prompt_intents("increase hp by 10", "entity_logic_ai")
    assert _should_fetch_templates("increase hp by 10", "entity_logic_ai", non_geo) is False


def test_prompt_without_mcp_or_intents():
    prompt = _get_full_system_prompt("entity_logic_ai", None, None, None)
    assert "AUTHORITATIVE BEDROCK SCHEMA" not in prompt
    assert "STRUCTURED USER INTENT" not in prompt


def test_prompt_with_structured_intent_block():
    profile = extract_prompt_intents("make it a tameable flying dragon", "entity_logic_ai")
    prompt = _get_full_system_prompt("entity_logic_ai", None, None, profile)
    assert "STRUCTURED USER INTENT" in prompt
    assert "tameable" in prompt.lower()
    assert "flying" in prompt.lower()


def test_error_extraction():
    texts = [
        "field hp is required but missing",
        "Everything looks fine",
        "Error: Invalid component structure",
        "\"invalidCommandSyntaxCount\": 0",
    ]
    errors = _extract_errors(texts)
    assert len(errors) == 2
    assert any("required" in e for e in errors)
    assert any("Invalid" in e for e in errors)


def test_retryable_errors():
    assert is_retryable(["field x is required"]) is True
    assert is_retryable(["Invalid type for hp"]) is True
    assert is_retryable(["Looks good"]) is False


def test_truncation_and_prompt_formatting():
    assert _truncate("hello", 10) == "hello"
    assert "truncated" in _truncate("x" * 10000, 50)

    formatted = _format_for_prompt("test_tool", [
        {"type": "text", "text": "Line 1"},
        {"type": "image", "data": "ignored"},
        {"type": "text", "text": "Line 2"},
    ])
    assert formatted == "Line 1\nLine 2"


def test_validation_conversion_for_internal_spec():
    spec = {
        "identifier": "custom:test_mob",
        "short_name": "test_mob",
        "display_name": "Test Mob",
        "hp": 20,
        "damage": 4,
        "speed": 0.25,
        "collision_box": {"width": 1, "height": 2},
        "scale": 1.0,
        "components": {"minecraft:can_fly": {}},
    }
    converted = _spec_to_validation_content(spec)
    entity = converted["minecraft:entity"]
    assert converted["format_version"] == "1.16.0"
    assert entity["description"]["identifier"] == "custom:test_mob"
    assert "minecraft:can_fly" in entity["components"]


if __name__ == "__main__":
    test_disabled_returns_empty_context()
    test_disabled_validation_returns_unavailable()
    test_prompt_intents_extract_constraints_and_template_hint()
    test_template_heuristics_use_intent_profile()
    test_prompt_without_mcp_or_intents()
    test_prompt_with_structured_intent_block()
    test_error_extraction()
    test_retryable_errors()
    test_truncation_and_prompt_formatting()
    test_validation_conversion_for_internal_spec()
    print("All MCP/prompt intent tests passed.")
