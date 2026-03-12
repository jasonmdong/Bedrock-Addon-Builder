#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Golden Test Runner for LLM Provider Comparison.

This script runs all golden test cases against one or more LLM providers
and generates a comparison report.

Usage:
    python run_golden_tests.py                    # Run with all available providers
    python run_golden_tests.py --provider openai  # Run with specific provider
    python run_golden_tests.py --provider deepseek --provider gemini  # Multiple providers
    python run_golden_tests.py --provider mock    # Run with mock (simulated perfect responses)
    python run_golden_tests.py --dry-run          # Show tests without running LLM
    python run_golden_tests.py --output report.json  # Save results to file
"""
import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Ensure stdout handles Unicode on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.llm.llm_scoring import (
    GOLDEN_TESTS,
    run_golden_test,
    compare_providers,
    GoldenTestResult,
    check_semantic_consistency,
)
from backend.llm.llm import llm_rewrite_spec
from backend.schemas.spec_utils import validate_spec, SpecValidationError


def mock_llm_response(test) -> dict:
    """Generate a mock 'perfect' response for testing the scoring system.
    
    This simulates what a perfect LLM would return for each test case.
    """
    spec = dict(test.input_spec)
    
    # Apply expected changes based on test name
    if test.name == "basic_explode":
        spec["components"] = spec.get("components", {})
        spec["components"]["minecraft:behavior.swell"] = {"start_distance": 2.5, "stop_distance": 6.0}
        spec["components"]["minecraft:explode"] = {"fuse_length": 1.5, "power": 3, "causes_fire": False}
    
    elif test.name == "double_health":
        spec["hp"] = spec.get("hp", 20) * 2
    
    elif test.name == "make_fly":
        spec["components"] = spec.get("components", {})
        spec["components"]["minecraft:can_fly"] = {}
    
    elif test.name == "tameable_mob":
        spec["components"] = spec.get("components", {})
        spec["components"]["minecraft:tameable"] = {"tame_items": ["bone"]}
        spec["components"]["minecraft:behavior.beg"] = {"priority": 9}  # Required by semantic rules
    
    elif test.name == "increase_speed":
        spec["speed"] = round(spec.get("speed", 0.20) * 1.5, 2)
    
    elif test.name == "ranged_attack":
        spec["components"] = spec.get("components", {})
        spec["components"]["minecraft:shooter"] = {"def": "minecraft:fireball"}
        spec["components"]["minecraft:behavior.ranged_attack"] = {"attack_interval": 3.0}
    
    elif test.name == "baby_variant":
        spec["components"] = spec.get("components", {})
        spec["components"]["minecraft:is_baby"] = {}
        spec["scale"] = 0.5
    
    elif test.name == "rename_mob":
        spec["display_name"] = "Fire Dragon"
    
    elif test.name == "hostile_mob":
        spec["components"] = spec.get("components", {})
        spec["components"]["minecraft:behavior.nearest_attackable_target"] = {"entity_types": [{"filters": {"test": "is_family", "value": "player"}}]}
        spec["components"]["minecraft:behavior.melee_attack"] = {"speed_multiplier": 1.0}
        spec["damage"] = max(spec.get("damage", 0), 3)  # Ensure damage >= 1
    
    elif test.name == "rideable_mob":
        spec["components"] = spec.get("components", {})
        spec["components"]["minecraft:rideable"] = {"seat_count": 1}
        spec["components"]["minecraft:input_ground_controlled"] = {}
    
    return spec


def run_single_test(test, provider: str, api_key: str = None) -> tuple[GoldenTestResult, dict]:
    """Run a single golden test against a provider.
    
    Returns (GoldenTestResult, output_spec or error dict)
    """
    print(f"  Running: {test.name}...", end=" ", flush=True)
    
    try:
        # Use mock for testing the scoring system without API calls
        if provider == "mock":
            output_spec = mock_llm_response(test)
        else:
            # Call the LLM
            output_spec = llm_rewrite_spec(
                prompt=test.prompt,
                current=test.input_spec,
                provider=provider,
                api_key=api_key
            )
        
        # Run the golden test
        result = run_golden_test(test, output_spec)
        
        status = "[PASS]" if result.passed else "[FAIL]"
        print(f"{status} (score: {result.score:.2f})")
        
        return result, output_spec, test.input_spec
        
    except SpecValidationError as e:
        print(f"[ERROR] VALIDATION ERROR: {e}")
        return GoldenTestResult(
            test_name=test.name,
            passed=False,
            score=0.0,
            checks=[],
            error=f"Validation error: {e}"
        ), {"error": str(e)}, test.input_spec
        
    except Exception as e:
        print(f"[ERROR] {e}")
        return GoldenTestResult(
            test_name=test.name,
            passed=False,
            score=0.0,
            checks=[],
            error=str(e)
        ), {"error": str(e)}, test.input_spec


def run_tests_for_provider(provider: str, api_key: str = None, tests: list = None, verbose: bool = False) -> list[GoldenTestResult]:
    """Run all golden tests for a single provider."""
    tests = tests or GOLDEN_TESTS
    results = []
    
    print(f"\n{'='*60}")
    print(f"Provider: {provider.upper()}")
    print(f"{'='*60}")
    
    for test in tests:
        try:
            result, output_spec, input_spec = run_single_test(test, provider, api_key)
        except Exception as e:
            print(f"[ERROR] Test {test.name} crashed: {e}")
            result = GoldenTestResult(
                test_name=test.name,
                passed=False,
                score=0.0,
                checks=[],
                error=str(e)
            )
        results.append(result)
        
        # Show detailed check results in verbose mode
        if verbose and result.checks:
            print(f"      Checks ({len([c for c in result.checks if c['passed']])}/{len(result.checks)} passed):")
            for check in result.checks:
                icon = "✓" if check['passed'] else "✗"
                check_type = check.get('type', 'unknown')
                message = check.get('message', '')
                print(f"        {icon} [{check_type}] {message}")
    
    # Summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    avg_score = sum(r.score for r in results) / total if total > 0 else 0
    
    print(f"\nSummary: {passed}/{total} passed, avg score: {avg_score:.2f}")
    
    return results


def generate_report(provider_results: dict[str, list[GoldenTestResult]]) -> dict:
    """Generate a full comparison report."""
    comparison = compare_providers(provider_results)
    
    # Add metadata
    report = {
        "generated_at": datetime.now().isoformat(),
        "total_tests": len(GOLDEN_TESTS),
        "providers_tested": list(provider_results.keys()),
        **comparison
    }
    
    return report


def print_report(report: dict):
    """Print a formatted report to console."""
    print("\n" + "="*60)
    print("COMPARISON REPORT")
    print("="*60)
    
    print(f"\nGenerated: {report['generated_at']}")
    print(f"Tests run: {report['total_tests']}")
    print(f"Providers: {', '.join(report['providers_tested'])}")
    
    print("\n--- Rankings ---")
    for i, provider in enumerate(report['ranking'], 1):
        score_data = report['scores'][provider]
        print(f"  {i}. {provider}: {score_data['tests_passed']}/{score_data['tests_total']} passed, "
              f"avg score: {score_data['average_score']:.3f}")
    
    print("\n--- Detailed Results ---")
    for provider, score_data in report['scores'].items():
        print(f"\n{provider}:")
        for test_result in score_data['test_results']:
            status = "[PASS]" if test_result['passed'] else "[FAIL]"
            print(f"  {status} {test_result['name']}: {test_result['score']:.2f}")
    
    if report.get('best_provider'):
        print(f"\nBest Provider: {report['best_provider']}")


def dry_run():
    """Show available tests without running LLM."""
    print("\n--- Available Golden Tests ---\n")
    for i, test in enumerate(GOLDEN_TESTS, 1):
        print(f"{i}. {test.name}")
        print(f"   Description: {test.description}")
        print(f"   Prompt: \"{test.prompt}\"")
        print(f"   Required components: {test.required_components}")
        if test.required_fields:
            print(f"   Required fields: {list(test.required_fields.keys())}")
        if test.should_not_change:
            print(f"   Should not change: {test.should_not_change}")
        print()


def get_api_key_for_provider(provider: str) -> str:
    """Get API key from environment for a provider."""
    if provider.lower() == "mock":
        return "mock"  # No API key needed for mock
    if provider.lower() == "ollama":
        return "ollama"  # No API key needed for local Ollama
    key_map = {
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
    }
    env_var = key_map.get(provider.lower())
    if env_var:
        return os.environ.get(env_var)
    return None


def main():
    parser = argparse.ArgumentParser(description="Run golden tests against LLM providers")
    parser.add_argument(
        "--provider", "-p",
        action="append",
        dest="providers",
        help="Provider(s) to test (can specify multiple). Options: openai, deepseek, gemini, claude, ollama, mock"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file for JSON report"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show available tests without running LLM"
    )
    parser.add_argument(
        "--test", "-t",
        action="append",
        dest="tests",
        help="Specific test(s) to run by name (can specify multiple)"
    )
    parser.add_argument(
        "--api-key",
        help="API key (overrides environment variable)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed check results for each test"
    )
    
    args = parser.parse_args()
    
    if args.dry_run:
        dry_run()
        return
    
    # Determine which providers to test
    providers = args.providers or ["openai"]  # Default to openai
    
    # Filter tests if specific ones requested
    tests_to_run = GOLDEN_TESTS
    if args.tests:
        tests_to_run = [t for t in GOLDEN_TESTS if t.name in args.tests]
        if not tests_to_run:
            print(f"Error: No tests found matching: {args.tests}")
            print("Available tests:", [t.name for t in GOLDEN_TESTS])
            sys.exit(1)
    
    # Run tests for each provider
    all_results = {}
    for provider in providers:
        api_key = args.api_key or get_api_key_for_provider(provider)
        if not api_key:
            print(f"\n[WARN] No API key found for {provider}. Set {provider.upper()}_API_KEY environment variable.")
            continue
        
        try:
            results = run_tests_for_provider(provider, api_key, tests_to_run, verbose=args.verbose)
            all_results[provider] = results
        except Exception as e:
            print(f"\n[ERROR] Failed to run tests for {provider}: {e}")
    
    if not all_results:
        print("\n[ERROR] No providers were tested. Check your API keys.")
        sys.exit(1)
    
    # Generate and print report
    report = generate_report(all_results)
    print_report(report)
    
    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(report, indent=2))
        print(f"\n📄 Report saved to: {output_path}")


if __name__ == "__main__":
    main()
