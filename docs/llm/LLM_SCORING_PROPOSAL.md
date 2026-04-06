# LLM Response Scoring System Proposal

## Problem Statement

The Bedrock Addon Builder uses LLMs to generate mob specifications based on user prompts. Currently, we only validate **structural correctness** (JSON schema, field types, value ranges) but have no way to measure **semantic quality**—whether the output actually does what the user asked.

Key issues:
- DeepSeek outputs are inconsistent/low quality compared to other providers
- No objective way to compare providers or measure improvement
- No data to guide prompt engineering or context improvements

As Rishit noted: *"What we can control is the context, not the inside of the LLM."* To improve context effectively, we need metrics.

---

## Proposed Scoring Approach

### Multi-Layer Validation

We propose a **3-tier scoring system**, each layer catching different types of failures:

```
┌─────────────────────────────────────────────────────────┐
│  TIER 3: Intent Alignment (LLM-as-Judge)                │
│  "Does this do what the user actually asked?"           │
├─────────────────────────────────────────────────────────┤
│  TIER 2: Semantic Consistency                           │
│  "Are the components logically coherent?"               │
├─────────────────────────────────────────────────────────┤
│  TIER 1: Structural Validity (Already Exists)           │
│  "Is this valid JSON matching the schema?"              │
└─────────────────────────────────────────────────────────┘
```

---

## Tier 1: Structural Validity ✅ (Already Implemented)

**What it checks:**
- Valid JSON
- Required fields present
- Types correct (hp is integer, color_rgb is array, etc.)
- Values in valid ranges (hp: 1-2048, speed: 0-2, etc.)

**Implementation:** `validate_spec()` in `spec_utils.py`

**Limitation:** A spec can be structurally valid but semantically broken (e.g., creeper with `behavior.swell` but no `explode` component).

---

## Tier 2: Semantic Consistency Rules

**What it checks:**
- Component dependencies (if A exists, B must exist)
- Logical coherence (baby mobs should have scale < 1)
- No hallucinated components (only valid Minecraft components)

### Example Rules

| Rule | Condition | Required |
|------|-----------|----------|
| Explosive mob | `behavior.swell` exists | `explode` must exist |
| Flying mob | `can_fly: true` | Should have flying movement |
| Tameable mob | `tameable` exists | Should have `behavior.beg` or similar |
| Baby variant | `is_baby: true` | `scale` should be < 1.0 |
| Shooter mob | `shooter` exists | Valid projectile definition |

### Scoring

```python
def semantic_score(spec: dict) -> float:
    """Returns 0.0-1.0 based on consistency rule compliance."""
    rules_checked = 0
    rules_passed = 0
    
    components = spec.get("components", {})
    
    # Rule: Explosive mobs need both swell and explode
    if "minecraft:behavior.swell" in components:
        rules_checked += 1
        if "minecraft:explode" in components:
            rules_passed += 1
    
    # Rule: Flying mobs should have flying movement
    if components.get("minecraft:can_fly"):
        rules_checked += 1
        if "minecraft:navigation.fly" in components or "minecraft:fly_speed" in components:
            rules_passed += 1
    
    # ... more rules
    
    return rules_passed / rules_checked if rules_checked > 0 else 1.0
```

**Why this approach:**
- Objective and automatable
- Catches real Minecraft functionality bugs
- Fast to run (no API calls)

---

## Tier 3: Intent Alignment (LLM-as-Judge)

**What it checks:**
- Does the output match what the user asked for?
- Did it change only what was requested?
- Is the implementation reasonable?

### Approach

Use a second LLM call to evaluate the first one's output:

```python
JUDGE_PROMPT = """
You are evaluating an LLM's response for a Minecraft mob generator.

USER REQUEST: {user_prompt}

INPUT SPEC (before): {input_spec}

OUTPUT SPEC (after): {output_spec}

Score the response on these criteria (1-5 each):

1. INTENT_MATCH: Does the output implement what the user asked?
2. MINIMAL_CHANGE: Did it avoid unnecessary modifications?
3. CORRECTNESS: Would this actually work in Minecraft?

Return JSON: {"intent_match": N, "minimal_change": N, "correctness": N, "explanation": "..."}
"""
```

**Why LLM-as-Judge:**
- Handles nuance that rules can't capture
- Can evaluate creative/subjective requests
- Industry standard for LLM evaluation (used by OpenAI, Anthropic internally)

**Tradeoffs:**
- Costs API calls
- Not 100% reliable (judge can make mistakes)
- Best used for sampling, not every request

---

## Golden Test Cases

A curated set of prompt → expected output pairs for regression testing.

### How It Works

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         GOLDEN TEST FLOW                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. FIXED INPUT SPEC                                                    │
│     ┌─────────────────────────────────────────┐                         │
│     │ {                                       │                         │
│     │   "identifier": "custom:test_mob",      │                         │
│     │   "hp": 20,                             │                         │
│     │   "damage": 5,                          │                         │
│     │   "speed": 0.25,                        │                         │
│     │   "components": {}                      │                         │
│     │ }                                       │                         │
│     └─────────────────────────────────────────┘                         │
│                          │                                              │
│                          ▼                                              │
│  2. PROMPT: "Double the health"                                         │
│                          │                                              │
│                          ▼                                              │
│  3. CALL LLM API (OpenAI, DeepSeek, Gemini, etc.)                       │
│     ┌─────────────────────────────────────────┐                         │
│     │  llm_rewrite_spec(                      │                         │
│     │    prompt="Double the health",          │                         │
│     │    current=input_spec,                  │                         │
│     │    provider="openai",                   │                         │
│     │    api_key="sk-..."                     │                         │
│     │  )                                      │                         │
│     └─────────────────────────────────────────┘                         │
│                          │                                              │
│                          ▼                                              │
│  4. LLM RETURNS OUTPUT SPEC                                             │
│     ┌─────────────────────────────────────────┐                         │
│     │ {                                       │                         │
│     │   "identifier": "custom:test_mob",      │                         │
│     │   "hp": 40,  ◄── Changed by LLM         │                         │
│     │   "damage": 5,                          │                         │
│     │   "speed": 0.25,                        │                         │
│     │   "components": {}                      │                         │
│     │ }                                       │                         │
│     └─────────────────────────────────────────┘                         │
│                          │                                              │
│                          ▼                                              │
│  5. COMPARE OUTPUT TO EXPECTED CRITERIA                                 │
│     ┌─────────────────────────────────────────┐                         │
│     │ required_fields:                        │                         │
│     │   hp: {equals: 40}        ✅ PASS       │                         │
│     │                                         │                         │
│     │ should_not_change:                      │                         │
│     │   damage: 5 → 5           ✅ PASS       │                         │
│     │   speed: 0.25 → 0.25      ✅ PASS       │                         │
│     │   identifier: unchanged   ✅ PASS       │                         │
│     └─────────────────────────────────────────┘                         │
│                          │                                              │
│                          ▼                                              │
│  6. CALCULATE SCORE                                                     │
│     ┌─────────────────────────────────────────┐                         │
│     │ Golden Test Score: 4/4 checks = 1.00    │                         │
│     │ Semantic Score: 0/0 rules = 1.00        │                         │
│     │ Combined Score: 1.00                    │                         │
│     │ Result: ✅ PASS                         │                         │
│     └─────────────────────────────────────────┘                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Test Case Structure

Each golden test defines:

| Field | Purpose | Example |
|-------|---------|---------|
| `input_spec` | Fixed starting mob spec (same for all providers) | `{"hp": 20, "damage": 5, ...}` |
| `prompt` | The user instruction to send to the LLM | `"Double the health"` |
| `required_components` | Components that MUST exist in output | `["minecraft:explode"]` |
| `required_fields` | Field values that MUST match criteria | `{"hp": {"equals": 40}}` |
| `should_not_change` | Fields the LLM should NOT modify | `["damage", "speed"]` |

### Example Test Cases

```python
GOLDEN_TESTS = [
    {
        "name": "basic_explode",
        "prompt": "Make this mob explode when near players",
        "input_spec": {"identifier": "custom:test", "hp": 20, "components": {}},
        "required_components": [
            "minecraft:behavior.swell",
            "minecraft:explode"
        ],
        "required_fields": {
            "components.minecraft:explode.fuse_length": {"min": 0.5}
        }
    },
    {
        "name": "double_health",
        "prompt": "Double the health",
        "input_spec": {"identifier": "custom:test", "hp": 20, "damage": 5, "speed": 0.25},
        "required_fields": {
            "hp": {"equals": 40}
        },
        "should_not_change": ["damage", "speed", "identifier"]
    },
    {
        "name": "make_fly",
        "prompt": "Make it fly",
        "input_spec": {"identifier": "custom:test", "hp": 20, "components": {}},
        "required_components": ["minecraft:can_fly"],
        "should_not_change": ["hp", "damage"]
    }
]
```

### Running Tests Against Real LLMs

```bash
# Test a single provider
python backend/run_golden_tests.py --provider openai --api-key "sk-..."

# Compare multiple providers
python backend/run_golden_tests.py --provider openai --provider deepseek --provider gemini

# Save results to file
python backend/run_golden_tests.py --provider openai --output results.json

# Test without API (uses mock "perfect" responses)
python backend/run_golden_tests.py --provider mock
```

### What Gets Compared

When you run tests against a real LLM:

1. **Same input** → Every provider gets the exact same `input_spec`
2. **Same prompt** → Every provider gets the exact same instruction
3. **Different outputs** → Each LLM returns its own interpretation
4. **Same scoring** → All outputs are evaluated against the same criteria

This gives you an **apples-to-apples comparison** of LLM quality.

**Use cases:**
- Compare providers on identical prompts
- Catch regressions when changing prompts/context
- Build confidence before deploying changes

---

## Why This Approach vs Alternatives

### Alternative 1: Pure Human Evaluation
- **Pros:** Ground truth, catches everything
- **Cons:** Slow, expensive, doesn't scale, subjective
- **Our approach:** Use human eval to validate the scoring system, then automate

### Alternative 2: In-Game Testing
- **Pros:** Ultimate ground truth—does it work in Minecraft?
- **Cons:** Requires Bedrock runtime, complex infrastructure, slow
- **Our approach:** Good future goal, but semantic rules catch most issues faster

### Alternative 3: Embedding Similarity
- **Pros:** Can compare output to "ideal" outputs
- **Cons:** Doesn't work well for structured JSON, misses functional correctness
- **Our approach:** Not suitable for this domain

### Alternative 4: Only Golden Tests
- **Pros:** Simple, objective
- **Cons:** Only catches issues you thought to test for
- **Our approach:** Golden tests + semantic rules + LLM-judge covers more ground

---

## Implementation Phases

### Phase 1: Foundation ✅ IMPLEMENTED
- [x] Implement semantic consistency checker → `backend/llm_scoring.py`
- [x] Create 10 golden test cases → `backend/llm_scoring.py` (GOLDEN_TESTS)
- [x] Add logging for LLM inputs/outputs → `backend/llm_logger.py`

**Files created:**
- `backend/llm_scoring.py` - Semantic checker + golden tests + provider comparison
- `backend/llm_logger.py` - Request/response logging to `data/llm_logs/`
- `backend/run_golden_tests.py` - CLI tool to run tests against providers

**Usage:**
```bash
# See available tests
python backend/run_golden_tests.py --dry-run

# Run tests against a provider
python backend/run_golden_tests.py --provider openai

# Compare multiple providers
python backend/run_golden_tests.py --provider openai --provider deepseek --output report.json
```

### Phase 2: Comparison (Next Week)
- [ ] Run golden tests across providers (DeepSeek, OpenAI, Gemini, Claude)
- [ ] Generate comparison report with scores
- [ ] Identify specific failure patterns for DeepSeek

### Phase 3: LLM-as-Judge (Future)
- [ ] Implement judge prompt
- [ ] Sample-based evaluation (not every request)
- [ ] Human validation of judge accuracy

### Phase 4: Feedback Loop (Future)
- [ ] Add 👍/👎 buttons to UI
- [ ] Log user feedback
- [ ] Use feedback to improve golden tests and rules

---

## Success Metrics

1. **Provider comparison:** Quantified score difference between DeepSeek and alternatives
2. **Regression detection:** Catch quality drops when changing prompts/context
3. **Improvement tracking:** Measure gains from MCP integration or prompt changes

---

## Open Questions for Mentors

1. Are there specific Minecraft component interactions we should prioritize in semantic rules?
2. Should we invest in in-game validation infrastructure?
3. What's the acceptable latency for scoring (can we use LLM-as-judge in production)?
4. Are there existing Bedrock addon validation tools we could leverage?
