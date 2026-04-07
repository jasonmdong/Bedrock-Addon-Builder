#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Token Usage & Speed Benchmark for LLM Providers.

Runs a matrix of prompts × providers and reports token counts,
cost estimates, and latency so you can identify expensive prompts
and slow models.

Usage:
    # Single provider, all prompts
    python backend/tests/run_token_tests.py --provider openai

    # Compare multiple providers
    python backend/tests/run_token_tests.py --provider openai --provider gemini

    # Run a specific prompt group only
    python backend/tests/run_token_tests.py --provider openai --group short

    # Show aggregated stats from existing logs (no API calls)
    python backend/tests/run_token_tests.py --from-logs

    # Save results to JSON
    python backend/tests/run_token_tests.py --provider openai --output token_report.json
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.llm.llm import _call_provider
from backend.llm.llm_logger import get_provider_stats, list_logs

# ---------------------------------------------------------------------------
# Test prompt corpus — three length groups
# ---------------------------------------------------------------------------

BASE_SPEC = {
    "identifier": "custom:test_mob",
    "display_name": "Test Mob",
    "short_name": "test_mob",
    "hp": 20,
    "damage": 5,
    "speed": 0.25,
    "scale": 1.0,
    "components": {},
}

PROMPTS = {
    "short": [
        {"name": "double_health", "prompt": "Double the health."},
        {"name": "make_fast", "prompt": "Make it faster."},
        {"name": "rename", "prompt": "Rename it to Fire Golem."},
    ],
    "medium": [
        {"name": "add_explode", "prompt": "Make this mob explode like a creeper when it gets close to players."},
        {"name": "add_fly", "prompt": "Make this mob fly and increase its speed to match a flying creature."},
        {"name": "make_hostile", "prompt": "Make this mob hostile: it should chase and attack players on sight."},
    ],
    "long": [
        {
            "name": "full_rework",
            "prompt": (
                "Rework this mob into a boss-tier dragon. "
                "Give it very high health (200+), strong melee attack (15 damage), "
                "flying ability, a ranged fireball attack, "
                "and make it aggressive toward all players and animals. "
                "Scale it up to 3.0. Name it 'Ancient Dragon'."
            ),
        },
        {
            "name": "balanced_warrior",
            "prompt": (
                "Transform this into a balanced warrior mob with medium health (50), "
                "moderate damage (8), normal walk speed, and melee attack behavior. "
                "It should be tameable with bones and follow the player when tamed. "
                "Give it a baby variant at 0.5 scale. Name it 'Iron Sentinel'."
            ),
        },
    ],
}

ALL_PROMPTS = {p["name"]: p for group in PROMPTS.values() for p in group}


# ---------------------------------------------------------------------------
# Cost estimates (USD per 1K tokens) — update as pricing changes
# ---------------------------------------------------------------------------

COST_PER_1K = {
    "openai":   {"prompt": 0.005,  "completion": 0.015},   # gpt-4o
    "deepseek": {"prompt": 0.00027,"completion": 0.0011},   # deepseek-chat
    "gemini":   {"prompt": 0.00025,"completion": 0.0005},   # gemini-1.5-flash
    "claude":   {"prompt": 0.003,  "completion": 0.015},    # claude-3-haiku
    "ollama":   {"prompt": 0.0,    "completion": 0.0},      # local
}


def estimate_cost(provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = COST_PER_1K.get(provider, {"prompt": 0.0, "completion": 0.0})
    return (prompt_tokens / 1000 * rates["prompt"] +
            completion_tokens / 1000 * rates["completion"])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_prompt(provider: str, api_key: str, name: str, prompt: str) -> dict:
    """Run a single prompt and return timing + token data."""
    t0 = time.time()
    error = None
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    try:
        _spec, usage = _call_provider(
            prompt=prompt,
            current=BASE_SPEC,
            provider_key=provider,
            api_key=api_key,
            category="entity_logic_ai",
        )
    except Exception as exc:
        error = str(exc)

    duration_ms = int((time.time() - t0) * 1000)

    result = {
        "prompt_name": name,
        "prompt_chars": len(prompt),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "duration_ms": duration_ms,
        "tokens_per_sec": (
            round(usage.get("completion_tokens", 0) / (duration_ms / 1000), 1)
            if duration_ms > 0 else 0
        ),
        "estimated_cost_usd": estimate_cost(
            provider,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        ),
        "error": error,
    }
    return result


def run_benchmark(provider: str, api_key: str, groups: list[str]) -> list[dict]:
    results = []
    prompts_to_run = []
    for g in groups:
        prompts_to_run.extend(PROMPTS.get(g, []))

    print(f"\n{'='*64}")
    print(f"Provider: {provider.upper()}  |  Prompts: {len(prompts_to_run)}")
    print(f"{'='*64}")
    print(f"  {'Prompt':<22} {'P.Tok':>7} {'C.Tok':>7} {'Total':>7} {'ms':>6} {'tok/s':>6} {'$':>8}")
    print(f"  {'-'*22} {'-'*7} {'-'*7} {'-'*7} {'-'*6} {'-'*6} {'-'*8}")

    for p in prompts_to_run:
        r = run_prompt(provider, api_key, p["name"], p["prompt"])
        results.append(r)
        if r["error"]:
            print(f"  {r['prompt_name']:<22} ERROR: {r['error'][:40]}")
        else:
            print(
                f"  {r['prompt_name']:<22} "
                f"{r['prompt_tokens']:>7,} "
                f"{r['completion_tokens']:>7,} "
                f"{r['total_tokens']:>7,} "
                f"{r['duration_ms']:>6,} "
                f"{r['tokens_per_sec']:>6.1f} "
                f"${r['estimated_cost_usd']:>7.5f}"
            )

    # Summary row
    valid = [r for r in results if not r["error"]]
    if valid:
        tot_tokens = sum(r["total_tokens"] for r in valid)
        tot_cost = sum(r["estimated_cost_usd"] for r in valid)
        avg_ms = int(sum(r["duration_ms"] for r in valid) / len(valid))
        print(f"  {'TOTAL / AVG':<22} {'':>7} {'':>7} {tot_tokens:>7,} {avg_ms:>6,} {'':>6} ${tot_cost:>7.5f}")

    return results


# ---------------------------------------------------------------------------
# Log-based stats (no API calls)
# ---------------------------------------------------------------------------

def show_log_stats():
    stats = get_provider_stats()
    if not stats:
        print("No logs found. Run some benchmarks first.")
        return

    print(f"\n{'='*72}")
    print("AGGREGATED TOKEN STATS FROM LOGS")
    print(f"{'='*72}")
    print(f"  {'Provider':<12} {'Calls':>6} {'AvgPTok':>8} {'AvgCTok':>8} {'AvgTotal':>9} {'AvgMs':>7} {'ErrRate':>8}")
    print(f"  {'-'*12} {'-'*6} {'-'*8} {'-'*8} {'-'*9} {'-'*7} {'-'*8}")

    for provider, s in sorted(stats.items()):
        print(
            f"  {provider:<12} "
            f"{s['total_calls']:>6} "
            f"{(s['avg_prompt_tokens'] or 0):>8,} "
            f"{(s['avg_completion_tokens'] or 0):>8,} "
            f"{(s['avg_total_tokens'] or 0):>9,} "
            f"{int(s['avg_duration_ms'] or 0):>7,} "
            f"{s['error_rate']:>7.1%}"
        )

    # Most recent calls with token data
    recent = [l for l in list_logs(limit=20) if l.get("token_usage", {}).get("total_tokens")]
    if recent:
        print(f"\nMost recent {len(recent)} calls with token data:")
        print(f"  {'Provider':<12} {'Prompt':<30} {'Tokens':>7} {'ms':>6}")
        for l in recent[:10]:
            u = l.get("token_usage", {})
            print(
                f"  {l['provider']:<12} "
                f"{l['prompt'][:30]:<30} "
                f"{u.get('total_tokens', 0):>7,} "
                f"{(l.get('duration_ms') or 0):>6,}"
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def get_api_key(provider: str) -> str | None:
    if provider in ("mock", "ollama"):
        return provider
    key_map = {
        "openai":   "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini":   "GEMINI_API_KEY",
        "claude":   "ANTHROPIC_API_KEY",
    }
    env_var = key_map.get(provider)
    return os.environ.get(env_var) if env_var else None


def main():
    parser = argparse.ArgumentParser(description="Token usage & speed benchmark for LLM providers")
    parser.add_argument("--provider", "-p", action="append", dest="providers",
                        help="Provider(s) to benchmark: openai, deepseek, gemini, claude, ollama")
    parser.add_argument("--group", "-g", action="append", dest="groups",
                        choices=["short", "medium", "long"],
                        help="Prompt length group(s) to run (default: all)")
    parser.add_argument("--from-logs", action="store_true",
                        help="Show stats aggregated from existing logs (no API calls)")
    parser.add_argument("--output", "-o", help="Save JSON results to this file")
    parser.add_argument("--api-key", help="Override API key for all providers")
    args = parser.parse_args()

    if args.from_logs:
        show_log_stats()
        return

    if not args.providers:
        parser.error("Specify at least one --provider (or use --from-logs)")

    groups = args.groups or ["short", "medium", "long"]
    all_results = {}

    for provider in args.providers:
        api_key = args.api_key or get_api_key(provider)
        if not api_key:
            print(f"[WARN] No API key for {provider}, skipping.")
            continue
        all_results[provider] = run_benchmark(provider, api_key, groups)

    if args.output and all_results:
        out = {
            "generated_at": datetime.now().isoformat(),
            "providers": args.providers,
            "groups": groups,
            "results": all_results,
        }
        Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nResults saved to {args.output}")

    # Cross-provider comparison
    if len(all_results) > 1:
        print(f"\n{'='*64}")
        print("CROSS-PROVIDER COMPARISON (averages over valid runs)")
        print(f"{'='*64}")
        print(f"  {'Provider':<12} {'AvgTokens':>10} {'AvgMs':>7} {'TotalCost':>11}")
        for provider, results in all_results.items():
            valid = [r for r in results if not r["error"]]
            if not valid:
                continue
            avg_tok = int(sum(r["total_tokens"] for r in valid) / len(valid))
            avg_ms = int(sum(r["duration_ms"] for r in valid) / len(valid))
            total_cost = sum(r["estimated_cost_usd"] for r in valid)
            print(f"  {provider:<12} {avg_tok:>10,} {avg_ms:>7,} ${total_cost:>10.5f}")


if __name__ == "__main__":
    main()
