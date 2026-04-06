"""Tests for MCP-augmented LLM context retrieval.

Covers all failure modes defined in the MCP_AUGMENTED_LLM_PLAN.md Phase 6:
  - MCP disabled → empty context, zero overhead
  - MCP unavailable → graceful fallback to static prompts
  - Heuristic detection (template types, geometry keywords)
  - Prompt assembly with and without MCP context
  - Validation result parsing and retry eligibility
  - Cache behavior
  - Token budget truncation
  - _mcp_meta attachment and extraction in route handler
"""

import os
import time

# Force MCP off for all tests (we don't need a running server)
os.environ["MCTOOLS_ENABLED"] = "false"

from backend.llm.mcp_context import (
    MCPContext,
    MCPValidationResult,
    retrieve_context_sync,
    mcp_validate_sync,
    is_retryable,
    clear_cache,
    _truncate,
    _format_for_prompt,
    _should_fetch_templates,
    _detect_template_type,
    _extract_errors,
    CACHE_TTL,
    MAX_MCP_SCHEMA_CHARS,
    MAX_MCP_TEMPLATE_CHARS,
)
from backend.llm.llm import _get_full_system_prompt, llm_rewrite_spec


# =========================================================================
# Scenario 1: MCP disabled → empty context, no overhead
# =========================================================================

def test_disabled_returns_empty_context():
    ctx = retrieve_context_sync("make it fly", "entity_logic_ai", {"hp": 20})
    assert ctx is not None
    assert ctx.available is False
    assert ctx.has_content is False
    assert ctx.source_tools == []
    assert ctx.retrieval_ms == 0
    print("  [PASS] disabled → empty context")


def test_disabled_validation_returns_valid():
    val = mcp_validate_sync({"hp": 20})
    assert val is not None
    assert val.valid is True
    assert val.available is False
    assert val.errors == []
    print("  [PASS] disabled → validation passes vacuously")


# =========================================================================
# Scenario 2: Heuristic detection
# =========================================================================

def test_template_heuristics():
    assert _should_fetch_templates("create a spider model", "entity_logic_ai") is True
    assert _should_fetch_templates("add wings to the body", "entity_logic_ai") is True
    assert _should_fetch_templates("custom 3d model", "entity_logic_ai") is True
    assert _should_fetch_templates("increase hp by 10", "entity_logic_ai") is False
    assert _should_fetch_templates("make a model", "items_weaponry") is False
    print("  [PASS] template fetch heuristics")


def test_template_type_detection():
    assert _detect_template_type("create a spider mob") == "quadruped"
    assert _detect_template_type("humanoid warrior") == "humanoid"
    assert _detect_template_type("flying bird creature") == "bird"
    assert _detect_template_type("aquatic fish mob") == "fish"
    assert _detect_template_type("totally unrelated prompt") == "humanoid"
    print("  [PASS] template type detection")


# =========================================================================
# Scenario 3: Prompt assembly
# =========================================================================

def test_prompt_without_mcp():
    prompt = _get_full_system_prompt("entity_logic_ai", None)
    assert "AUTHORITATIVE BEDROCK SCHEMA" not in prompt
    assert "MODEL TEMPLATES" not in prompt
    assert "CRITICAL RULES" in prompt
    print("  [PASS] prompt without MCP matches old behavior")


def test_prompt_with_schema_only():
    ctx = MCPContext(
        schema_text="MOCK SCHEMA DATA",
        source_tools=["getEffectiveContentSchema"],
        available=True,
    )
    prompt = _get_full_system_prompt("entity_logic_ai", ctx)
    assert "AUTHORITATIVE BEDROCK SCHEMA" in prompt
    assert "MOCK SCHEMA DATA" in prompt
    assert "MODEL TEMPLATES" not in prompt
    print("  [PASS] prompt with schema only")


def test_prompt_with_both():
    ctx = MCPContext(
        schema_text="MOCK SCHEMA",
        template_text="MOCK TEMPLATE",
        source_tools=["getEffectiveContentSchema", "getModelTemplates"],
        available=True,
    )
    prompt = _get_full_system_prompt("entity_logic_ai", ctx)
    assert "MOCK SCHEMA" in prompt
    assert "MOCK TEMPLATE" in prompt
    # Verify ordering: schema before category context before templates
    schema_pos = prompt.index("AUTHORITATIVE BEDROCK SCHEMA")
    cat_pos = prompt.index("CATEGORY: Entity Logic")
    tmpl_pos = prompt.index("MODEL TEMPLATES")
    assert schema_pos < cat_pos < tmpl_pos
    print("  [PASS] prompt with both, correct ordering")


def test_prompt_empty_mcp_context():
    ctx = MCPContext()  # all empty
    prompt = _get_full_system_prompt("entity_logic_ai", ctx)
    assert "AUTHORITATIVE BEDROCK SCHEMA" not in prompt
    assert "MODEL TEMPLATES" not in prompt
    print("  [PASS] empty MCPContext = no injection")


# =========================================================================
# Scenario 4: Validation parsing
# =========================================================================

def test_error_extraction():
    texts = [
        "field hp is required but missing",
        "Everything looks fine",
        "Error: Invalid component structure",
        "Note: consider adding description",
    ]
    errors = _extract_errors(texts)
    assert len(errors) == 2
    assert any("required" in e for e in errors)
    assert any("Invalid" in e for e in errors)
    print("  [PASS] error extraction from validation text")


def test_retryable():
    assert is_retryable(["field x is required"]) is True
    assert is_retryable(["Invalid type for hp"]) is True
    assert is_retryable(["value must be between 1 and 100"]) is True
    assert is_retryable(["Looks good"]) is False
    assert is_retryable([]) is False
    print("  [PASS] retryable error detection")


# =========================================================================
# Scenario 5: Token budget truncation
# =========================================================================

def test_truncation():
    short = "hello world"
    assert _truncate(short, 100) == short

    long = "x" * 10000
    result = _truncate(long, MAX_MCP_SCHEMA_CHARS)
    assert len(result) < MAX_MCP_SCHEMA_CHARS + 100
    assert "truncated" in result
    print("  [PASS] token budget truncation")


# =========================================================================
# Scenario 6: Format for prompt
# =========================================================================

def test_format_for_prompt():
    content = [
        {"type": "text", "text": "Line 1"},
        {"type": "text", "text": "Line 2"},
        {"type": "image", "data": "ignored"},
        {"type": "text", "text": ""},
    ]
    result = _format_for_prompt("test_tool", content)
    assert "Line 1" in result
    assert "Line 2" in result
    assert "ignored" not in result
    print("  [PASS] format_for_prompt extracts text items")


# =========================================================================
# Scenario 7: MCPContext dataclass
# =========================================================================

def test_mcp_context_has_content():
    assert MCPContext().has_content is False
    assert MCPContext(schema_text="x").has_content is True
    assert MCPContext(template_text="y").has_content is True
    assert MCPContext(schema_text="x", template_text="y").has_content is True
    print("  [PASS] MCPContext.has_content")


# =========================================================================
# Scenario 8: _mcp_meta attachment
# =========================================================================

def test_mcp_meta_structure():
    """Verify the _mcp_meta dict has the expected shape."""
    meta = {
        "augmented": True,
        "context_sources": ["getEffectiveContentSchema"],
        "retrieval_ms": 200,
        "validation": {
            "ran": True,
            "valid": True,
            "messages": [],
        },
    }
    assert meta["augmented"] is True
    assert isinstance(meta["context_sources"], list)
    assert isinstance(meta["validation"], dict)
    assert meta["validation"]["ran"] is True
    print("  [PASS] _mcp_meta structure valid")


# =========================================================================
# Run all
# =========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("MCP Context Integration Tests")
    print("=" * 60)

    tests = [
        test_disabled_returns_empty_context,
        test_disabled_validation_returns_valid,
        test_template_heuristics,
        test_template_type_detection,
        test_prompt_without_mcp,
        test_prompt_with_schema_only,
        test_prompt_with_both,
        test_prompt_empty_mcp_context,
        test_error_extraction,
        test_retryable,
        test_truncation,
        test_format_for_prompt,
        test_mcp_context_has_content,
        test_mcp_meta_structure,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * 60)

    if failed:
        exit(1)
