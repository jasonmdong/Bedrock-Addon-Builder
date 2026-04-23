"""
Demo: Dynamic Prompt Assembly
==============================
Shows how the system builds smaller, targeted prompts based on what the
user actually asks — instead of always sending a large static prompt.

Run:
    python scripts/demo_dynamic_prompting.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

os.environ["MCTOOLS_ENABLED"] = "false"

from backend.core.core import DEFAULTS
from backend.llm.dynamic_context import build_dynamic_context
from backend.llm.llm import _get_full_system_prompt, _get_legacy_system_prompt_for_tests
from backend.llm.prompt_intents import extract_prompt_intents

# ---------------------------------------------------------------------------
# Prompts that represent different use cases
# ---------------------------------------------------------------------------
DEMO_PROMPTS = [
    ("Increase hp by 10.",                                  "Simple stat change — no extras needed"),
    ("Make it drop diamonds on death.",                     "Loot table — should include loot section"),
    ("Change its texture color to red.",                    "Visual edit — should include visuals section"),
    ("Make it fly and keep its current custom geometry.",   "Geometry + behavior — should include both"),
    ("Make it fly, drop gold, and change color to blue.",   "Everything — should include all sections"),
]


def estimate_tokens(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def detect_sections(prompt: str, profile) -> list[str]:
    """Mirror the section-detection logic from _get_full_system_prompt."""
    sections = ["behavior"]  # always included for entity_logic_ai
    prompt_l = prompt.lower()

    _geo_adjacent = ("texture","color","colour","scale","size","shape","model",
                     "geometry","bone","skin","appearance","look","visual")
    prompt_touches_visuals = any(k in prompt_l for k in _geo_adjacent)

    include_geo = False
    include_geo_preservation = False
    include_visuals = False
    include_loot = False

    if profile:
        if profile.constraints.get("geometry_requested") or any(
            s.name == "geometry_edit" for s in profile.signals
        ):
            include_geo = True
        if profile.constraints.get("preserve_geometry") or prompt_touches_visuals:
            include_geo_preservation = True
        if profile.constraints.get("visual_requested") or any(
            s.name == "visual_edit" for s in profile.signals
        ):
            include_visuals = True

    if any(k in prompt_l for k in ("drop", "drops", "loot", "on death", "upon death")):
        include_loot = True

    if include_geo:
        sections.append("geometry")
    if include_geo_preservation:
        sections.append("geometry_preservation")
    if include_visuals:
        sections.append("visuals")
    if include_loot:
        sections.append("loot")

    return sections


def run_demo():
    # Column widths
    col_prompt = 50
    col_sections = 32
    col_tokens = 9
    col_legacy = 9
    col_saved = 9

    header = (
        f"{'Prompt':<{col_prompt}} "
        f"{'Sections included':<{col_sections}} "
        f"{'Tokens':>{col_tokens}} "
        f"{'Legacy':>{col_legacy}} "
        f"{'Saved':>{col_saved}}"
    )
    divider = "-" * len(header)

    print()
    print("=" * len(header))
    print("  DYNAMIC PROMPT ASSEMBLY — TOKEN SAVINGS DEMO")
    print("=" * len(header))
    print(header)
    print(divider)

    for prompt, description in DEMO_PROMPTS:
        profile = extract_prompt_intents(prompt, "entity_logic_ai")
        dyn_ctx = build_dynamic_context(prompt, "entity_logic_ai")

        dynamic, _, _ = _get_full_system_prompt(prompt, DEFAULTS, "entity_logic_ai", None, dyn_ctx, profile)
        legacy  = _get_legacy_system_prompt_for_tests(prompt, DEFAULTS, "entity_logic_ai", None, dyn_ctx, profile)

        dynamic_tokens = estimate_tokens(dynamic)
        legacy_tokens  = estimate_tokens(legacy)
        saved          = legacy_tokens - dynamic_tokens
        saved_pct      = round(100 * saved / legacy_tokens) if legacy_tokens else 0

        sections = detect_sections(prompt, profile)
        sections_str = ", ".join(sections)

        prompt_display = (prompt[:col_prompt - 3] + "...") if len(prompt) > col_prompt else prompt

        print(
            f"{prompt_display:<{col_prompt}} "
            f"{sections_str:<{col_sections}} "
            f"{dynamic_tokens:>{col_tokens},} "
            f"{legacy_tokens:>{col_legacy},} "
            f"{f'-{saved} ({saved_pct}%)':>{col_saved}}"
        )
        print(f"  -> {description}")
        print()

    print(divider)
    print("Legend: Tokens = dynamic prompt | Legacy = old static prompt | Saved = tokens eliminated")
    print()
    print("Tip: Run with a custom prompt:")
    print('  python scripts/demo_dynamic_prompting.py "make it invisible and silent"')
    print()

    # Allow passing a single custom prompt as CLI arg
    if len(sys.argv) > 1:
        custom = " ".join(sys.argv[1:])
        print(f"{'=' * len(header)}")
        print(f"  CUSTOM PROMPT: {custom!r}")
        print(f"{'=' * len(header)}")
        profile = extract_prompt_intents(custom, "entity_logic_ai")
        dyn_ctx = build_dynamic_context(custom, "entity_logic_ai")
        dynamic, _, _ = _get_full_system_prompt(custom, DEFAULTS, "entity_logic_ai", None, dyn_ctx, profile)
        legacy  = _get_legacy_system_prompt_for_tests(custom, DEFAULTS, "entity_logic_ai", None, dyn_ctx, profile)
        sections = detect_sections(custom, profile)
        print(f"  Sections: {', '.join(sections)}")
        print(f"  Dynamic tokens: {estimate_tokens(dynamic):,}")
        print(f"  Legacy tokens:  {estimate_tokens(legacy):,}")
        print(f"  Saved:          {estimate_tokens(legacy) - estimate_tokens(dynamic):,}")
        print()


if __name__ == "__main__":
    run_demo()
