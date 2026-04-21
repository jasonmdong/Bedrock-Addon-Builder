"""Two-phase LLM orchestration: Plan → Execute.

Instead of asking the LLM to rewrite the entire spec in one shot, we:
  Phase 1 — Plan: ask a cheap, focused call what needs to change and why.
  Phase 2 — Execute: pass the original prompt + plan to the existing
            _call_provider pipeline, giving the LLM a clear scratchpad.

Benefits:
  - Weaker models (Ollama/llama3.2) perform significantly better when given
    an explicit list of what to add/remove rather than reasoning from scratch.
  - Component dependencies (swell→explode, tameable→beg, fly→navigation.fly)
    are resolved in the planning step, not left to chance.
  - The planning call is small/fast (~200-400 tokens output) so the latency
    overhead is minimal compared to the quality gain.

Usage:
    from backend.llm.orchestrator import build_plan, format_plan_for_prompt

    plan = build_plan(prompt, current_spec, provider_key, api_key, category)
    augmented_prompt = format_plan_for_prompt(prompt, plan)
    # then call _call_provider(augmented_prompt, ...)
"""

import copy
import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Load the vanilla reference for dynamic template generation
_REF_PATH = Path(__file__).resolve().parent.parent / "data" / "vanilla_reference.json"
_VANILLA_REF: dict = {}
try:
    _VANILLA_REF = json.loads(_REF_PATH.read_text(encoding="utf-8"))
except Exception:
    pass

# ---------------------------------------------------------------------------
# Planning system prompt
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """You are a Minecraft Bedrock Add-on spec planner.

Given a user instruction and the current mob spec, identify exactly what needs to change.
Return ONLY a JSON object with this structure:

{
  "reasoning": "Brief explanation of what needs to change and why (max 60 words)",
  "fields_to_change": {
    "field_name": new_value
  },
  "components_to_add": ["minecraft:component_name"],
  "components_to_remove": ["minecraft:component_name"],
  "component_values": {
    "minecraft:component_name": { ...full component config... }
  }
}

FIELD RULES:
- fields_to_change: only top-level spec fields (hp, damage, speed, scale, display_name,
  geometry, color_rgb, texture_hint, texture_instructions, loot_drops, collision_box)
- components_to_add: component keys to add/update inside "components"
- components_to_remove: component keys to null out (delete) inside "components"
- component_values: must contain an entry for EVERY component in components_to_add

COMPONENT DEPENDENCY RULES (ALWAYS enforce these):
- Flying: ADD minecraft:can_fly + minecraft:movement.fly + minecraft:navigation.fly
  REMOVE minecraft:movement.basic + minecraft:navigation.walk
- Exploding: ADD minecraft:behavior.swell + minecraft:explode
  REMOVE minecraft:behavior.melee_attack + minecraft:behavior.ranged_attack + minecraft:shooter
  (swell makes mob charge at target — incompatible with ranged)
- Ranged attack: ADD minecraft:shooter + minecraft:behavior.ranged_attack
  REMOVE minecraft:behavior.melee_attack + minecraft:behavior.swell + minecraft:explode
  (ranged keeps distance — incompatible with swell/explode)
- Tameable: ADD minecraft:tameable + minecraft:behavior.beg
- Aquatic: ADD minecraft:navigation.swim + minecraft:breathable + minecraft:movement.sway
  REMOVE minecraft:navigation.walk + minecraft:movement.basic
- Climbing: ADD minecraft:can_climb + minecraft:navigation.climb
  REMOVE minecraft:navigation.walk

PRIORITY RULES:
- Lower number = higher priority. Avoid giving two conflicting behaviors the same priority.
- Recommended: ranged_attack=2, swell=2 (never both on same mob), melee_attack=3,
  wander=5, look_at_player=6, beg=7

IMPORTANT:
- If the user only changes a stat (hp, damage, speed), fields_to_change is sufficient.
  Leave components_to_add/remove empty if no components need to change.
- Use ONLY the field names listed in the COMPONENT REFERENCE below. Extra/invented fields cause silent failure in Bedrock.
- Output ONLY the JSON, no markdown, no explanation outside the JSON.
"""


def _build_component_reference() -> str:
    """Generate COMPONENT REFERENCE section from vanilla_reference.json."""
    components = _VANILLA_REF.get("components", {})
    conflicts = _VANILLA_REF.get("conflicts", {})
    if not components:
        return ""

    lines = ["\nCOMPONENT REFERENCE (valid fields for each component):"]
    for name, info in components.items():
        valid_fields = info.get("valid_fields", {})
        invalid_fields = info.get("INVALID_FIELDS", [])

        # Build default example from valid_fields
        example = {}
        for field, meta in valid_fields.items():
            if "default" in meta:
                example[field] = meta["default"]
            elif meta.get("required") and meta.get("type") == "int":
                example[field] = 1
            elif meta.get("required") and meta.get("type") == "float":
                example[field] = 1.0
            elif meta.get("required") and meta.get("type") == "string":
                example[field] = ""

        field_names = list(valid_fields.keys())
        lines.append(f"\n{name}:")
        if info.get("description"):
            lines.append(f"  {info['description']}")
        if field_names:
            lines.append(f"  Valid fields: {', '.join(field_names)}")
        else:
            lines.append("  No fields (empty object)")
        if invalid_fields:
            lines.append(f"  INVALID (do NOT use): {', '.join(invalid_fields)}")

        # Show valid_projectiles for shooter
        if "valid_projectiles" in info:
            lines.append(f"  Valid projectiles: {', '.join(info['valid_projectiles'])}")

        # Show conflicts
        if name in conflicts:
            lines.append(f"  Conflicts with: {', '.join(conflicts[name])}")

    return "\n".join(lines)


def _get_planner_system_prompt() -> str:
    """Build the full planner system prompt with dynamic component reference."""
    return PLANNER_SYSTEM_PROMPT + _build_component_reference()

# ---------------------------------------------------------------------------
# Plan dataclass
# ---------------------------------------------------------------------------

class OrchestratorPlan:
    """Structured plan produced by the planning LLM call."""

    def __init__(self, raw: dict):
        self.reasoning: str = raw.get("reasoning", "")
        self.fields_to_change: dict = raw.get("fields_to_change", {})
        self.components_to_add: list[str] = raw.get("components_to_add", [])
        self.components_to_remove: list[str] = raw.get("components_to_remove", [])
        self.component_values: dict = raw.get("component_values", {})

    @property
    def has_changes(self) -> bool:
        return bool(
            self.fields_to_change
            or self.components_to_add
            or self.components_to_remove
        )

    def to_dict(self) -> dict:
        return {
            "reasoning": self.reasoning,
            "fields_to_change": self.fields_to_change,
            "components_to_add": self.components_to_add,
            "components_to_remove": self.components_to_remove,
            "component_values": self.component_values,
        }


# ---------------------------------------------------------------------------
# Phase 1: Planning call
# ---------------------------------------------------------------------------

def build_plan(
    prompt: str,
    current_spec: dict,
    provider_key: str,
    api_key: Optional[str],
    category: str = "entity_logic_ai",
) -> Optional[OrchestratorPlan]:
    """Call the LLM to produce a structured plan for what to change.

    Returns an OrchestratorPlan on success, or None if planning fails
    (caller should fall back to direct execution).
    """
    try:
        slim_spec = {k: v for k, v in current_spec.items()
                     if k not in ("geometry_json", "_template_base",
                                  "_texture_b64", "_mcp_meta", "_mcp_design")}
        user_content = (
            f"Current spec:\n{json.dumps(slim_spec, indent=2)}\n\n"
            f"Instruction:\n{prompt.strip()}"
        )

        raw = _call_planner(provider_key, api_key, user_content)
        plan = OrchestratorPlan(raw)

        print(
            f"[ORCHESTRATOR] Plan built — fields={list(plan.fields_to_change.keys())}, "
            f"add={plan.components_to_add}, remove={plan.components_to_remove}"
        )
        return plan

    except Exception as exc:
        log.warning("[ORCHESTRATOR] Planning call failed, falling back to direct: %s", exc)
        return None


def _call_planner(provider_key: str, api_key: Optional[str], user_content: str) -> dict:
    """Route planning call to the appropriate provider."""
    if provider_key in ("openai", "github"):
        return _plan_openai(api_key, user_content)
    elif provider_key == "deepseek":
        return _plan_deepseek(api_key, user_content)
    elif provider_key == "gemini":
        return _plan_gemini(api_key, user_content)
    elif provider_key == "claude" or provider_key == "claude-sonnet" or provider_key == "claude-opus":
        return _plan_claude(api_key, user_content)
    elif provider_key == "ollama":
        return _plan_ollama(api_key, user_content)
    else:
        return _plan_openai(api_key, user_content)


def _parse_json_response(content: str) -> dict:
    """Parse JSON from LLM response, stripping markdown fences if present."""
    content = content.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


def _plan_openai(api_key: Optional[str], user_content: str) -> dict:
    from openai import OpenAI
    from backend.config.settings import LLM_MODEL_NAME
    key = api_key or os.environ.get("GITHUB_TOKEN")
    if not key:
        raise RuntimeError("No API key for OpenAI planner")
    client = OpenAI(base_url="https://models.github.ai/inference", api_key=key)
    resp = client.chat.completions.create(
        model=LLM_MODEL_NAME,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _get_planner_system_prompt()},
            {"role": "user", "content": user_content},
        ],
    )
    return json.loads(resp.choices[0].message.content)


def _plan_deepseek(api_key: Optional[str], user_content: str) -> dict:
    from openai import OpenAI
    from backend.config.settings import DEEPSEEK_MODEL_NAME
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("No DEEPSEEK_API_KEY for planner")
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL_NAME,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _get_planner_system_prompt()},
            {"role": "user", "content": user_content},
        ],
        stream=False,
    )
    return json.loads(resp.choices[0].message.content)


def _plan_gemini(api_key: Optional[str], user_content: str) -> dict:
    from google import genai
    from backend.config.settings import GEMINI_MODEL_NAME
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("No GEMINI_API_KEY for planner")
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=GEMINI_MODEL_NAME,
        contents=user_content,
        config={
            "system_instruction": _get_planner_system_prompt(),
            "response_mime_type": "application/json",
        },
    )
    return json.loads(resp.text)


def _plan_claude(api_key: Optional[str], user_content: str) -> dict:
    import anthropic
    from backend.config.settings import CLAUDE_MODEL_NAME
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("No ANTHROPIC_API_KEY for planner")
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=CLAUDE_MODEL_NAME,
        max_tokens=512,
        system=_get_planner_system_prompt(),
        messages=[{"role": "user", "content": user_content}],
    )
    return _parse_json_response(resp.content[0].text)


def _plan_ollama(api_key: Optional[str], user_content: str) -> dict:
    from openai import OpenAI
    from backend.config.settings import OLLAMA_MODEL_NAME, OLLAMA_BASE_URL
    client = OpenAI(base_url=f"{OLLAMA_BASE_URL}/v1", api_key="ollama", timeout=30.0)
    resp = client.chat.completions.create(
        model=OLLAMA_MODEL_NAME,
        messages=[
            {"role": "system", "content": _get_planner_system_prompt()},
            {
                "role": "user",
                "content": user_content + "\n\nRespond with ONLY the JSON plan, no explanation.",
            },
        ],
        temperature=0.1,
    )
    return _parse_json_response(resp.choices[0].message.content)


# ---------------------------------------------------------------------------
# Phase 2: Format plan into an augmented prompt
# ---------------------------------------------------------------------------

def format_plan_for_prompt(original_prompt: str, plan: OrchestratorPlan) -> str:
    """Combine the original prompt with the structured plan.

    The result replaces the user prompt passed to _call_provider, giving the
    execution LLM a precise task list rather than open-ended reasoning.
    """
    lines = [original_prompt.strip(), "", "--- IMPLEMENTATION PLAN ---"]

    if plan.reasoning:
        lines.append(f"Reasoning: {plan.reasoning}")

    if plan.fields_to_change:
        lines.append("\nTop-level fields to update:")
        for field, value in plan.fields_to_change.items():
            lines.append(f"  - {field}: {json.dumps(value)}")

    if plan.components_to_add:
        lines.append("\nComponents to ADD (with values below):")
        for comp in plan.components_to_add:
            val = plan.component_values.get(comp, {})
            lines.append(f"  - {comp}: {json.dumps(val)}")

    if plan.components_to_remove:
        lines.append("\nComponents to REMOVE (omit entirely from the output JSON, do NOT set to null):")
        for comp in plan.components_to_remove:
            lines.append(f"  - {comp}")

    lines.append("\nApply this plan exactly. Return the complete updated spec as JSON.")
    lines.append("--- END PLAN ---")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plan-as-patch: apply a simple plan directly without a Phase 2 LLM call
# ---------------------------------------------------------------------------

KNOWN_TOP_LEVEL_FIELDS = {
    "identifier", "display_name", "short_name", "engine_min",
    "hp", "damage", "speed", "scale",
    "collision_box", "geometry", "geometry_json",
    "render_controller", "texture_hint", "texture_instructions",
    "egg_base", "egg_overlay", "color_rgb", "loot_drops",
}

# Component prefixes that are valid Bedrock entity components
_VALID_COMPONENT_PREFIXES = (
    "minecraft:behavior.", "minecraft:navigation.", "minecraft:movement.",
    "minecraft:can_fly", "minecraft:can_climb", "minecraft:shooter",
    "minecraft:explode", "minecraft:tameable", "minecraft:rideable",
    "minecraft:attack", "minecraft:fire_immune", "minecraft:area_attack",
    "minecraft:teleport", "minecraft:breathable", "minecraft:breedable",
    "minecraft:is_baby", "minecraft:knockback_resistance", "minecraft:scale",
    "minecraft:loot", "minecraft:flying_speed", "minecraft:input_ground_controlled",
    "minecraft:health", "minecraft:follow_range",
)


def plan_is_simple(plan: OrchestratorPlan) -> bool:
    """Return True if the plan can be applied directly as a patch.

    A plan is "simple" when:
      - All fields_to_change keys are known top-level spec fields
      - All components_to_add have corresponding entries in component_values
      - All component names look like valid Bedrock components
      - The reasoning doesn't signal ambiguity
    """
    # All fields must be known
    for field in plan.fields_to_change:
        if field not in KNOWN_TOP_LEVEL_FIELDS:
            return False

    # Geometry changes require LLM generation — never apply directly
    if "geometry" in plan.fields_to_change or "geometry_json" in plan.fields_to_change:
        return False

    # Every added component must have a value and look like a real component
    for comp in plan.components_to_add:
        if comp not in plan.component_values:
            return False
        if not any(comp.startswith(prefix) for prefix in _VALID_COMPONENT_PREFIXES):
            return False

    # Removed components must look valid
    for comp in plan.components_to_remove:
        if not any(comp.startswith(prefix) for prefix in _VALID_COMPONENT_PREFIXES):
            return False

    # Ambiguity markers in reasoning → fall back to full rewrite
    ambiguity = ("unsure", "unclear", "complex", "might need", "not certain")
    if any(word in plan.reasoning.lower() for word in ambiguity):
        return False

    return True


def apply_plan(plan: OrchestratorPlan, current_spec: dict) -> dict:
    """Apply a plan directly to the spec as a patch. No second LLM call needed.

    Returns a new spec dict with the plan's changes merged in.
    The caller is responsible for running validate_spec() on the result.
    """
    spec = copy.deepcopy(current_spec)

    # Apply field changes
    for field, value in plan.fields_to_change.items():
        spec[field] = value

    # Ensure components dict exists
    components = spec.setdefault("components", {})

    # Remove components
    for comp in plan.components_to_remove:
        components.pop(comp, None)

    # Add/update components
    for comp in plan.components_to_add:
        components[comp] = plan.component_values.get(comp, {})

    return spec


# ---------------------------------------------------------------------------
# Convenience: should we use orchestration for this provider/prompt?
# ---------------------------------------------------------------------------

_SIMPLE_PATTERNS = [
    # Pure stat changes — no benefit from planning
    r"^(double|triple|halve|increase|decrease|set|make)\s+(the\s+)?(hp|health|damage|speed|scale)\b",
    r"^(set|change)\s+\w+\s+to\s+\d",
]

import re
_SIMPLE_RE = [re.compile(p, re.IGNORECASE) for p in _SIMPLE_PATTERNS]


def should_use_orchestration(prompt: str, provider_key: str, force: bool = False) -> bool:
    """Decide whether to run the plan-then-execute pipeline.

    Auto-enabled for ollama (weaker local models benefit most from explicit plans).
    Opt-in for cloud providers via force=True (use_plan flag in request body).
    When force=True, simple prompts are NOT skipped — they'll use the fast
    direct-apply path (one cheap plan call, zero Phase 2 calls).
    """
    if not force and provider_key != "ollama":
        return False
    # When forced (Smart Plan mode), always orchestrate — even simple prompts
    # benefit from direct-apply (plan → patch, no full rewrite needed)
    if force:
        return True
    # For auto-enabled ollama, skip trivially simple prompts
    for pattern in _SIMPLE_RE:
        if pattern.match(prompt.strip()):
            return False
    return True
