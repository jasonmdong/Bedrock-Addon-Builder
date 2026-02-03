"""LLM Response Scoring System for Bedrock Addon Builder.

This module provides:
1. Semantic consistency checking (component dependencies, logical coherence)
2. Golden test case validation
3. Scoring utilities for comparing LLM providers
"""
import json
from typing import Optional
from dataclasses import dataclass, field


# =============================================================================
# SEMANTIC CONSISTENCY RULES
# =============================================================================

# Component dependency rules: if key exists, values must also exist
COMPONENT_DEPENDENCIES = {
    "minecraft:behavior.swell": ["minecraft:explode"],
    "minecraft:behavior.tempt": ["minecraft:navigation.walk"],
    "minecraft:shooter": ["minecraft:behavior.ranged_attack"],
    "minecraft:rideable": ["minecraft:input_ground_controlled"],
    "minecraft:tameable": ["minecraft:behavior.beg"],
    "minecraft:healable": ["minecraft:tameable"],
}

# Components that imply certain field values
COMPONENT_FIELD_IMPLICATIONS = {
    "minecraft:is_baby": {"scale": {"max": 0.9}},
    "minecraft:can_fly": {"speed": {"min": 0.1}},
}

# Valid Minecraft Bedrock components (subset - expand as needed)
VALID_COMPONENTS = {
    # Movement & Navigation
    "minecraft:navigation.walk",
    "minecraft:navigation.fly",
    "minecraft:navigation.swim",
    "minecraft:navigation.climb",
    "minecraft:movement.basic",
    "minecraft:movement.fly",
    "minecraft:movement.swim",
    "minecraft:jump.static",
    "minecraft:can_fly",
    "minecraft:can_climb",
    
    # Combat & Damage
    "minecraft:attack",
    "minecraft:shooter",
    "minecraft:explode",
    "minecraft:behavior.swell",
    "minecraft:behavior.melee_attack",
    "minecraft:behavior.ranged_attack",
    "minecraft:projectile",
    
    # AI Behaviors
    "minecraft:behavior.follow_owner",
    "minecraft:behavior.tempt",
    "minecraft:behavior.beg",
    "minecraft:behavior.panic",
    "minecraft:behavior.random_stroll",
    "minecraft:behavior.look_at_player",
    "minecraft:behavior.hurt_by_target",
    "minecraft:behavior.nearest_attackable_target",
    "minecraft:behavior.float",
    "minecraft:behavior.leap_at_target",
    
    # Interaction
    "minecraft:tameable",
    "minecraft:healable",
    "minecraft:rideable",
    "minecraft:input_ground_controlled",
    "minecraft:leashable",
    "minecraft:nameable",
    
    # Properties
    "minecraft:is_baby",
    "minecraft:scale",
    "minecraft:health",
    "minecraft:collision_box",
    "minecraft:physics",
    "minecraft:pushable",
    "minecraft:breathable",
    
    # Spawning
    "minecraft:spawn_entity",
    "minecraft:type_family",
}


@dataclass
class SemanticCheckResult:
    """Result of a semantic consistency check."""
    rule_name: str
    passed: bool
    message: str


@dataclass 
class SemanticScore:
    """Overall semantic scoring result."""
    score: float  # 0.0 to 1.0
    checks_passed: int
    checks_total: int
    results: list[SemanticCheckResult] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "checks_passed": self.checks_passed,
            "checks_total": self.checks_total,
            "results": [
                {"rule": r.rule_name, "passed": r.passed, "message": r.message}
                for r in self.results
            ]
        }


def check_semantic_consistency(spec: dict) -> SemanticScore:
    """Check a spec for semantic consistency issues.
    
    Returns a score from 0.0 to 1.0 based on rule compliance.
    """
    results = []
    components = spec.get("components", {}) or {}
    
    # Normalize component keys (handle both with and without minecraft: prefix)
    normalized_components = {}
    for key, value in components.items():
        if value is not None:  # null means deleted
            normalized_components[key] = value
    
    # Check component dependencies
    for trigger, required in COMPONENT_DEPENDENCIES.items():
        if trigger in normalized_components:
            for req in required:
                passed = req in normalized_components
                results.append(SemanticCheckResult(
                    rule_name=f"dependency:{trigger}→{req}",
                    passed=passed,
                    message=f"'{trigger}' requires '{req}'" if not passed else "OK"
                ))
    
    # Check component-field implications
    for component, field_rules in COMPONENT_FIELD_IMPLICATIONS.items():
        if component in normalized_components:
            for field_name, constraints in field_rules.items():
                field_value = spec.get(field_name)
                if field_value is not None:
                    passed = True
                    msg = "OK"
                    
                    if "min" in constraints and field_value < constraints["min"]:
                        passed = False
                        msg = f"'{field_name}' should be >= {constraints['min']} when '{component}' is present"
                    if "max" in constraints and field_value > constraints["max"]:
                        passed = False
                        msg = f"'{field_name}' should be <= {constraints['max']} when '{component}' is present"
                    
                    results.append(SemanticCheckResult(
                        rule_name=f"implication:{component}→{field_name}",
                        passed=passed,
                        message=msg
                    ))
    
    # Check for hallucinated components (optional - can be strict or lenient)
    for comp_name in normalized_components.keys():
        # Only check minecraft: prefixed components
        if comp_name.startswith("minecraft:"):
            passed = comp_name in VALID_COMPONENTS
            if not passed:
                results.append(SemanticCheckResult(
                    rule_name=f"valid_component:{comp_name}",
                    passed=False,
                    message=f"Unknown component '{comp_name}' - may be hallucinated"
                ))
    
    # Calculate score
    if not results:
        return SemanticScore(score=1.0, checks_passed=0, checks_total=0, results=[])
    
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    
    return SemanticScore(
        score=passed / total if total > 0 else 1.0,
        checks_passed=passed,
        checks_total=total,
        results=results
    )


# =============================================================================
# GOLDEN TEST CASES
# =============================================================================

@dataclass
class GoldenTestCase:
    """A golden test case with prompt, input, and expected output criteria."""
    name: str
    description: str
    prompt: str
    input_spec: dict
    required_components: list[str] = field(default_factory=list)
    forbidden_components: list[str] = field(default_factory=list)
    required_fields: dict = field(default_factory=dict)  # field_name -> {"equals", "min", "max", "contains"}
    should_not_change: list[str] = field(default_factory=list)
    expected_output: Optional[dict] = None  # Full expected output for exact matching


@dataclass
class GoldenTestResult:
    """Result of running a golden test."""
    test_name: str
    passed: bool
    score: float  # 0.0 to 1.0
    checks: list[dict]  # Individual check results
    semantic_score: Optional[SemanticScore] = None
    error: Optional[str] = None


# Golden test cases - prompts with expected outputs
GOLDEN_TESTS: list[GoldenTestCase] = [
    GoldenTestCase(
        name="basic_explode",
        description="Mob should explode when near players (creeper-like)",
        prompt="Make this mob explode when it gets close to players",
        input_spec={
            "identifier": "custom:test_mob",
            "display_name": "Test Mob",
            "short_name": "test_mob",
            "hp": 20,
            "damage": 0,
            "speed": 0.25,
            "components": {}
        },
        required_components=[
            "minecraft:behavior.swell",
            "minecraft:explode"
        ],
        required_fields={
            "components.minecraft:explode.fuse_length": {"min": 0.5, "max": 10},
        }
    ),
    
    GoldenTestCase(
        name="double_health",
        description="Double the mob's health",
        prompt="Double the health",
        input_spec={
            "identifier": "custom:test_mob",
            "display_name": "Test Mob",
            "short_name": "test_mob",
            "hp": 20,
            "damage": 5,
            "speed": 0.25,
            "components": {}
        },
        required_fields={
            "hp": {"equals": 40}
        },
        should_not_change=["damage", "speed", "identifier"]
    ),
    
    GoldenTestCase(
        name="make_fly",
        description="Make the mob able to fly",
        prompt="Make it fly",
        input_spec={
            "identifier": "custom:test_mob",
            "display_name": "Test Mob",
            "short_name": "test_mob",
            "hp": 20,
            "damage": 5,
            "speed": 0.25,
            "components": {}
        },
        required_components=["minecraft:can_fly"],
        should_not_change=["hp", "damage"]
    ),
    
    GoldenTestCase(
        name="tameable_mob",
        description="Make the mob tameable by players",
        prompt="Make this mob tameable with bones",
        input_spec={
            "identifier": "custom:test_mob",
            "display_name": "Test Mob",
            "short_name": "test_mob",
            "hp": 20,
            "damage": 5,
            "speed": 0.25,
            "components": {}
        },
        required_components=["minecraft:tameable"],
    ),
    
    GoldenTestCase(
        name="increase_speed",
        description="Increase mob speed by 50%",
        prompt="Increase the speed by 50%",
        input_spec={
            "identifier": "custom:test_mob",
            "display_name": "Test Mob",
            "short_name": "test_mob",
            "hp": 20,
            "damage": 5,
            "speed": 0.20,
            "components": {}
        },
        required_fields={
            "speed": {"equals": 0.30}
        },
        should_not_change=["hp", "damage"]
    ),
    
    GoldenTestCase(
        name="ranged_attack",
        description="Give the mob a ranged attack",
        prompt="Make it shoot fireballs at players",
        input_spec={
            "identifier": "custom:test_mob",
            "display_name": "Test Mob",
            "short_name": "test_mob",
            "hp": 20,
            "damage": 5,
            "speed": 0.25,
            "components": {}
        },
        required_components=[
            "minecraft:shooter",
            "minecraft:behavior.ranged_attack"
        ],
    ),
    
    GoldenTestCase(
        name="baby_variant",
        description="Make a baby version of the mob",
        prompt="Make this a baby mob",
        input_spec={
            "identifier": "custom:test_mob",
            "display_name": "Test Mob",
            "short_name": "test_mob",
            "hp": 20,
            "damage": 5,
            "speed": 0.25,
            "scale": 1.0,
            "components": {}
        },
        required_components=["minecraft:is_baby"],
        required_fields={
            "scale": {"max": 0.75}
        }
    ),
    
    GoldenTestCase(
        name="rename_mob",
        description="Rename the mob",
        prompt="Rename this mob to 'Fire Dragon'",
        input_spec={
            "identifier": "custom:test_mob",
            "display_name": "Test Mob",
            "short_name": "test_mob",
            "hp": 20,
            "damage": 5,
            "speed": 0.25,
            "components": {}
        },
        required_fields={
            "display_name": {"contains": "Fire Dragon"}
        },
        should_not_change=["hp", "damage", "speed"]
    ),
    
    GoldenTestCase(
        name="hostile_mob",
        description="Make the mob hostile to players",
        prompt="Make this mob attack players on sight",
        input_spec={
            "identifier": "custom:test_mob",
            "display_name": "Test Mob",
            "short_name": "test_mob",
            "hp": 20,
            "damage": 0,
            "speed": 0.25,
            "components": {}
        },
        required_components=[
            "minecraft:behavior.nearest_attackable_target",
            "minecraft:behavior.melee_attack"
        ],
        required_fields={
            "damage": {"min": 1}  # Should have some damage to attack
        }
    ),
    
    GoldenTestCase(
        name="rideable_mob",
        description="Make the mob rideable",
        prompt="Make this mob rideable by players",
        input_spec={
            "identifier": "custom:test_mob",
            "display_name": "Test Mob",
            "short_name": "test_mob",
            "hp": 20,
            "damage": 5,
            "speed": 0.25,
            "components": {}
        },
        required_components=[
            "minecraft:rideable",
            "minecraft:input_ground_controlled"
        ],
    ),
]


def _get_nested_value(obj: dict, path: str):
    """Get a nested value from a dict using dot notation (e.g., 'components.minecraft:explode.fuse_length')."""
    keys = path.split(".")
    current = obj
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def run_golden_test(test: GoldenTestCase, output_spec: dict) -> GoldenTestResult:
    """Run a single golden test against an LLM output.
    
    Returns a GoldenTestResult with pass/fail and detailed checks.
    """
    checks = []
    
    components = output_spec.get("components", {}) or {}
    
    # Check required components
    for comp in test.required_components:
        present = comp in components and components[comp] is not None
        checks.append({
            "type": "required_component",
            "component": comp,
            "passed": present,
            "message": f"Required component '{comp}'" + (" present" if present else " MISSING")
        })
    
    # Check forbidden components
    for comp in test.forbidden_components:
        absent = comp not in components or components[comp] is None
        checks.append({
            "type": "forbidden_component",
            "component": comp,
            "passed": absent,
            "message": f"Forbidden component '{comp}'" + (" absent" if absent else " PRESENT (should not be)")
        })
    
    # Check required fields
    for field_path, constraints in test.required_fields.items():
        value = _get_nested_value(output_spec, field_path)
        passed = True
        messages = []
        
        if value is None:
            passed = False
            messages.append(f"Field '{field_path}' is missing")
        else:
            if "equals" in constraints:
                if value != constraints["equals"]:
                    passed = False
                    messages.append(f"Expected {constraints['equals']}, got {value}")
            if "min" in constraints:
                if value < constraints["min"]:
                    passed = False
                    messages.append(f"Expected >= {constraints['min']}, got {value}")
            if "max" in constraints:
                if value > constraints["max"]:
                    passed = False
                    messages.append(f"Expected <= {constraints['max']}, got {value}")
            if "contains" in constraints:
                if constraints["contains"] not in str(value):
                    passed = False
                    messages.append(f"Expected to contain '{constraints['contains']}', got '{value}'")
        
        checks.append({
            "type": "required_field",
            "field": field_path,
            "passed": passed,
            "value": value,
            "message": "; ".join(messages) if messages else "OK"
        })
    
    # Check fields that should not change
    for field_name in test.should_not_change:
        original = test.input_spec.get(field_name)
        current = output_spec.get(field_name)
        passed = original == current
        checks.append({
            "type": "unchanged_field",
            "field": field_name,
            "passed": passed,
            "original": original,
            "current": current,
            "message": f"Field '{field_name}' should not change" + (" (unchanged)" if passed else f" (was {original}, now {current})")
        })
    
    # Run semantic consistency check
    semantic = check_semantic_consistency(output_spec)
    
    # Calculate overall score
    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    
    # Combine golden test score with semantic score
    golden_score = passed_checks / total_checks if total_checks > 0 else 1.0
    combined_score = (golden_score + semantic.score) / 2 if semantic.checks_total > 0 else golden_score
    
    return GoldenTestResult(
        test_name=test.name,
        passed=all(c["passed"] for c in checks) and semantic.score >= 0.8,
        score=combined_score,
        checks=checks,
        semantic_score=semantic
    )


def run_all_golden_tests(output_specs: dict[str, dict]) -> dict[str, GoldenTestResult]:
    """Run all golden tests against a dict of {test_name: output_spec}.
    
    Returns a dict of {test_name: GoldenTestResult}.
    """
    results = {}
    for test in GOLDEN_TESTS:
        if test.name in output_specs:
            results[test.name] = run_golden_test(test, output_specs[test.name])
    return results


# =============================================================================
# PROVIDER COMPARISON
# =============================================================================

@dataclass
class ProviderScore:
    """Aggregated score for an LLM provider."""
    provider: str
    tests_passed: int
    tests_total: int
    average_score: float
    test_results: list[GoldenTestResult]
    
    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "tests_passed": self.tests_passed,
            "tests_total": self.tests_total,
            "average_score": self.average_score,
            "pass_rate": self.tests_passed / self.tests_total if self.tests_total > 0 else 0,
            "test_results": [
                {
                    "name": r.test_name,
                    "passed": r.passed,
                    "score": r.score,
                }
                for r in self.test_results
            ]
        }


def score_provider(provider: str, test_results: list[GoldenTestResult]) -> ProviderScore:
    """Calculate aggregate score for a provider based on test results."""
    passed = sum(1 for r in test_results if r.passed)
    total = len(test_results)
    avg_score = sum(r.score for r in test_results) / total if total > 0 else 0
    
    return ProviderScore(
        provider=provider,
        tests_passed=passed,
        tests_total=total,
        average_score=avg_score,
        test_results=test_results
    )


def compare_providers(provider_results: dict[str, list[GoldenTestResult]]) -> dict:
    """Compare multiple providers and generate a comparison report.
    
    Args:
        provider_results: Dict of {provider_name: [GoldenTestResult, ...]}
    
    Returns:
        Comparison report dict
    """
    scores = {}
    for provider, results in provider_results.items():
        scores[provider] = score_provider(provider, results)
    
    # Rank by average score
    ranked = sorted(scores.values(), key=lambda s: s.average_score, reverse=True)
    
    return {
        "ranking": [s.provider for s in ranked],
        "scores": {p: s.to_dict() for p, s in scores.items()},
        "best_provider": ranked[0].provider if ranked else None,
        "summary": {
            p: {
                "pass_rate": f"{s.tests_passed}/{s.tests_total}",
                "avg_score": round(s.average_score, 3)
            }
            for p, s in scores.items()
        }
    }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_golden_test_by_name(name: str) -> Optional[GoldenTestCase]:
    """Get a golden test case by name."""
    for test in GOLDEN_TESTS:
        if test.name == name:
            return test
    return None


def list_golden_tests() -> list[dict]:
    """List all available golden tests."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "prompt": t.prompt
        }
        for t in GOLDEN_TESTS
    ]
