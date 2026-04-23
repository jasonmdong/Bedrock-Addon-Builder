import argparse
import difflib
import json
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    import tiktoken
except ImportError:
    tiktoken = None

from backend.core.core import DEFAULTS
from backend.llm.dynamic_context import build_dynamic_context
from backend.llm.llm import (
    _get_full_system_prompt,
    _get_compact_system_prompt,
    _get_legacy_system_prompt_for_tests,
    _prepare_spec_for_llm,
)
from backend.llm.prompt_intents import extract_prompt_intents


def estimate_tokens(text: str, model: str = "gpt-4.1") -> int:
    if tiktoken is not None:
        try:
            enc = tiktoken.encoding_for_model(model)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    # fallback heuristic
    return max(1, len(text) // 4)


def build_user_message(prompt: str, current_spec: dict) -> str:
    return f"Current spec:\n{_prepare_spec_for_llm(current_spec)}\n\nInstruction:\n{prompt.strip()}"


def compare_prompts(prompt: str, category: str = "entity_logic_ai", model: str = "gpt-4.1") -> dict:
    intent_profile = extract_prompt_intents(prompt, category)
    dynamic_ctx = build_dynamic_context(prompt, category)

    legacy_system = _get_legacy_system_prompt_for_tests(prompt, DEFAULTS, category, None, dynamic_ctx, intent_profile)
    dynamic_system, _, _ = _get_full_system_prompt(prompt, DEFAULTS, category, None, dynamic_ctx, intent_profile)
    compact_system = _get_compact_system_prompt(category, intent_profile)
    user_message = build_user_message(prompt, DEFAULTS)

    legacy_tokens = estimate_tokens(legacy_system + "\n" + user_message, model)
    dynamic_tokens = estimate_tokens(dynamic_system + "\n" + user_message, model)
    compact_tokens = estimate_tokens(compact_system + "\n" + user_message, model)
    legacy_chars = len(legacy_system)
    dynamic_chars = len(dynamic_system)
    compact_chars = len(compact_system)
    user_chars = len(user_message)
    return {
        "prompt": prompt,
        "category": category,
        "model": model,
        "intent_profile": intent_profile.to_dict(),
        "legacy_system_chars": legacy_chars,
        "dynamic_system_chars": dynamic_chars,
        "compact_system_chars": compact_chars,
        "user_chars": user_chars,
        "legacy_system_tokens": estimate_tokens(legacy_system, model),
        "dynamic_system_tokens": estimate_tokens(dynamic_system, model),
        "compact_system_tokens": estimate_tokens(compact_system, model),
        "user_tokens": estimate_tokens(user_message, model),
        "legacy_total_tokens": legacy_tokens,
        "dynamic_total_tokens": dynamic_tokens,
        "compact_total_tokens": compact_tokens,
        "legacy_system": legacy_system,
        "dynamic_system": dynamic_system,
        "compact_system": compact_system,
        "user_message": user_message,
    }


def print_comparison(result: dict, show_full: bool = False, show_diff: bool = False):
    print("=== Prompt Token Comparison ===")
    print(f"Prompt: {result['prompt']}")
    print(f"Category: {result['category']}")
    print(f"Model: {result['model']}")
    print("\nSystem prompt sizes:")
    print(f"  Legacy system prompt:  {result['legacy_system_chars']} chars, {result['legacy_system_tokens']} tokens")
    print(f"  Dynamic system prompt: {result['dynamic_system_chars']} chars, {result['dynamic_system_tokens']} tokens")
    print(f"  Compact system prompt: {result['compact_system_chars']} chars, {result['compact_system_tokens']} tokens")
    print(f"  Savings (legacy → dynamic): {result['legacy_system_chars'] - result['dynamic_system_chars']} chars, {result['legacy_system_tokens'] - result['dynamic_system_tokens']} tokens")
    print(f"  Savings (dynamic → compact): {result['dynamic_system_chars'] - result['compact_system_chars']} chars, {result['dynamic_system_tokens'] - result['compact_system_tokens']} tokens")
    print("\nUser message size:")
    print(f"  User message: {result['user_chars']} chars, {result['user_tokens']} tokens")
    print("\nTotal request size:")
    print(f"  Legacy total:  {result['legacy_total_tokens']} tokens")
    print(f"  Dynamic total: {result['dynamic_total_tokens']} tokens")
    print(f"  Compact total: {result['compact_total_tokens']} tokens")
    print(f"  Total savings (legacy → dynamic): {result['legacy_total_tokens'] - result['dynamic_total_tokens']} tokens")
    print(f"  Total savings (dynamic → compact): {result['dynamic_total_tokens'] - result['compact_total_tokens']} tokens")

    print("\nExtracted intent profile:")
    print(json.dumps(result['intent_profile'], indent=2))

    if show_full:
        print("\n--- LEGACY SYSTEM PROMPT ---")
        print(result['legacy_system'])
        print("\n--- DYNAMIC SYSTEM PROMPT ---")
        print(result['dynamic_system'])
        print("\n--- COMPACT SYSTEM PROMPT ---")
        print(result['compact_system'])
        print("\n--- USER MESSAGE ---")
        print(result['user_message'])
    elif show_diff:
        diff = difflib.unified_diff(
            result['dynamic_system'].splitlines(True),
            result['compact_system'].splitlines(True),
            fromfile='dynamic_system',
            tofile='compact_system',
            lineterm='',
        )
        print("\n--- System prompt diff (dynamic vs compact) ---")
        for i, line in enumerate(diff):
            if i >= 120:
                print('... diff truncated ...')
                break
            print(line)


def main():
    parser = argparse.ArgumentParser(description='Compare legacy, dynamic, and compact LLM system prompts for MobSpec editing.')
    parser.add_argument('prompt', nargs='?', default='Make this mob fly and breathe fire while keeping its current shape.', help='User instruction prompt to compare')
    parser.add_argument('--category', default='entity_logic_ai', help='LLM category to use')
    parser.add_argument('--model', default='gpt-4.1', help='Model name for token estimation')
    parser.add_argument('--full', action='store_true', help='Print full prompt contents')
    parser.add_argument('--diff', action='store_true', help='Print the system prompt diff between dynamic and compact prompts')
    args = parser.parse_args()

    result = compare_prompts(args.prompt, args.category, args.model)
    print_comparison(result, show_full=args.full, show_diff=args.diff)


if __name__ == '__main__':
    main()
