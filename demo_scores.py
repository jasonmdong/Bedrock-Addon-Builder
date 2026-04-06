#!/usr/bin/env python3
"""
Demo: Fake multi-provider LLM scoring comparison.

Uses the real scoring infrastructure (llm_scoring.py) but with hand-crafted
responses that simulate how different real providers might perform, with
deliberate mistakes to make scores realistic and varied.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.llm.llm_scoring import (
    GOLDEN_TESTS,
    run_golden_test,
    compare_providers,
    GoldenTestResult,
)

# ---------------------------------------------------------------------------
# Simulated responses per provider.
# Each entry is {test_name: output_spec_or_error_flag}.
# Providers intentionally make different mistakes so scores vary.
# ---------------------------------------------------------------------------

def perfect_response(test):
    """Build the ideal response for a test (same as the mock provider in run_golden_tests.py)."""
    spec = dict(test.input_spec)
    if "components" not in spec:
        spec["components"] = {}
    spec["components"] = dict(spec.get("components") or {})

    if test.name == "basic_explode":
        spec["components"]["minecraft:behavior.swell"] = {"start_distance": 2.5, "stop_distance": 6.0}
        spec["components"]["minecraft:explode"] = {"fuse_length": 1.5, "power": 3, "causes_fire": False}
    elif test.name == "double_health":
        spec["hp"] = spec["hp"] * 2
    elif test.name == "make_fly":
        spec["components"]["minecraft:can_fly"] = {}
    elif test.name == "tameable_mob":
        spec["components"]["minecraft:tameable"] = {"tame_items": ["bone"]}
        spec["components"]["minecraft:behavior.beg"] = {"priority": 9}
    elif test.name == "increase_speed":
        spec["speed"] = round(spec["speed"] * 1.5, 2)
    elif test.name == "ranged_attack":
        spec["components"]["minecraft:shooter"] = {"def": "minecraft:fireball"}
        spec["components"]["minecraft:behavior.ranged_attack"] = {"attack_interval": 3.0}
    elif test.name == "baby_variant":
        spec["components"]["minecraft:is_baby"] = {}
        spec["scale"] = 0.5
    elif test.name == "rename_mob":
        spec["display_name"] = "Fire Dragon"
    elif test.name == "hostile_mob":
        spec["components"]["minecraft:behavior.nearest_attackable_target"] = {
            "entity_types": [{"filters": {"test": "is_family", "value": "player"}}]
        }
        spec["components"]["minecraft:behavior.melee_attack"] = {"speed_multiplier": 1.0}
        spec["damage"] = max(spec.get("damage", 0), 3)
    elif test.name == "rideable_mob":
        spec["components"]["minecraft:rideable"] = {"seat_count": 1}
        spec["components"]["minecraft:input_ground_controlled"] = {}
    return spec


def simulate_gpt4o(test):
    """GPT-4o: near-perfect, one small miss on increase_speed (rounds wrong)."""
    spec = perfect_response(test)
    if test.name == "increase_speed":
        spec["speed"] = 0.29  # off by 0.01 – fails the equals:0.30 check
    return spec


def simulate_claude(test):
    """Claude: great, but forgets minecraft:behavior.beg on tameable and hallucinates a component."""
    spec = perfect_response(test)
    if test.name == "tameable_mob":
        del spec["components"]["minecraft:behavior.beg"]  # missing dependency
    if test.name == "hostile_mob":
        spec["components"]["minecraft:behavior.custom_aggro"] = {}  # hallucinated component
    return spec


def simulate_gemini(test):
    """Gemini: good overall, struggles with baby_variant scale and ranged_attack dependency."""
    spec = perfect_response(test)
    if test.name == "baby_variant":
        spec["scale"] = 0.8   # too big – fails max:0.75
    if test.name == "ranged_attack":
        del spec["components"]["minecraft:behavior.ranged_attack"]  # missing required component
    return spec


def simulate_deepseek(test):
    """DeepSeek: solid but changes fields it shouldn't and misses explode fuse_length."""
    spec = perfect_response(test)
    if test.name == "double_health":
        spec["speed"] = 0.35   # altered a should_not_change field
    if test.name == "basic_explode":
        # fuse_length missing → fails required_field check
        spec["components"]["minecraft:explode"] = {"power": 3, "causes_fire": False}
    return spec


def simulate_ollama(test):
    """Ollama (llama3.2): weakest; misses several components and alters unchanged fields."""
    spec = perfect_response(test)
    if test.name == "basic_explode":
        del spec["components"]["minecraft:explode"]                  # missing required component
    if test.name == "tameable_mob":
        del spec["components"]["minecraft:behavior.beg"]             # missing dependency
    if test.name == "ranged_attack":
        del spec["components"]["minecraft:behavior.ranged_attack"]   # missing required
    if test.name == "rename_mob":
        spec["hp"] = 25                                              # should_not_change violated
    if test.name == "hostile_mob":
        spec["damage"] = 0                                           # required_field min:1 violated
    return spec


PROVIDERS = {
    "gpt-4o":      simulate_gpt4o,
    "claude-3.5":  simulate_claude,
    "gemini-1.5":  simulate_gemini,
    "deepseek-v3": simulate_deepseek,
    "ollama-llama3": simulate_ollama,
}


def run_provider(name, response_fn):
    results = []
    print(f"\n{'='*60}")
    print(f"Provider: {name}")
    print(f"{'='*60}")
    for test in GOLDEN_TESTS:
        output = response_fn(test)
        result = run_golden_test(test, output)
        status = "PASS" if result.passed else "FAIL"
        icon = "[+]" if result.passed else "[-]"
        print(f"  {icon} {status}  {test.name:<28} score: {result.score:.2f}")
        results.append(result)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    avg = sum(r.score for r in results) / total
    print(f"\n  Summary: {passed}/{total} passed   avg score: {avg:.3f}")
    return results


def main():
    print("\n" + "="*60)
    print("  BEDROCK ADDON BUILDER — LLM PROVIDER DEMO COMPARISON")
    print("  (simulated responses — no real API calls)")
    print("="*60)

    all_results = {}
    for name, fn in PROVIDERS.items():
        all_results[name] = run_provider(name, fn)

    # Final ranking
    report = compare_providers(all_results)

    print("\n\n" + "="*60)
    print("  FINAL RANKINGS")
    print("="*60)
    for rank, provider in enumerate(report["ranking"], 1):
        s = report["scores"][provider]
        bar = "#" * int(s["average_score"] * 20)
        bar = bar.ljust(20, ".")
        print(f"  {rank}. {provider:<18} [{bar}]  {s['tests_passed']}/{s['tests_total']} passed  avg {s['average_score']:.3f}")

    print(f"\n  >> Best Provider: {report['best_provider']}")
    print()


if __name__ == "__main__":
    main()
