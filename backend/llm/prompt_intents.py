"""Structured prompt intent extraction for the LLM pipeline.

Turns free-form user instructions into compact, typed signals that can be:
- injected into prompts for better grounding
- logged as stage artifacts for debugging
- reused by MCP template selection and repair flows
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PromptSignal:
    """A detected capability or style signal in the user's prompt."""

    name: str
    confidence: float
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


@dataclass
class PromptChange:
    """A structured requested change, usually a stat or hard instruction."""

    field: str
    operation: str
    value: float | int | str | None = None
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "operation": self.operation,
            "value": self.value,
            "evidence": self.evidence,
        }


@dataclass
class PromptIntentProfile:
    """Structured interpretation of a user prompt."""

    category: str
    signals: list[PromptSignal] = field(default_factory=list)
    requested_changes: list[PromptChange] = field(default_factory=list)
    constraints: dict[str, bool] = field(default_factory=dict)
    style_keywords: list[str] = field(default_factory=list)
    template_hint: str = ""
    intent_notes: list[str] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return bool(
            self.signals
            or self.requested_changes
            or self.constraints
            or self.style_keywords
            or self.template_hint
            or self.intent_notes
        )

    @property
    def wants_geometry_template(self) -> bool:
        if self.constraints.get("geometry_requested"):
            return True
        return bool(self.template_hint)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "signals": [signal.to_dict() for signal in self.signals],
            "requested_changes": [change.to_dict() for change in self.requested_changes],
            "constraints": dict(sorted(self.constraints.items())),
            "style_keywords": self.style_keywords,
            "template_hint": self.template_hint,
            "intent_notes": list(self.intent_notes),
        }

    def to_prompt_block(self) -> str:
        """Format the extracted facts for prompt injection."""
        if not self.has_content:
            return ""

        lines = ["--- STRUCTURED USER INTENT ---"]

        if self.signals:
            lines.append("Detected signals:")
            for signal in self.signals:
                evidence = ", ".join(signal.evidence[:3])
                lines.append(f"- {signal.name} (confidence={signal.confidence:.2f}; evidence={evidence})")

        if self.requested_changes:
            lines.append("Requested changes:")
            for change in self.requested_changes:
                if change.value is None:
                    lines.append(f"- {change.field}: {change.operation} ({change.evidence})")
                else:
                    lines.append(f"- {change.field}: {change.operation} -> {change.value} ({change.evidence})")

        if self.constraints:
            lines.append("Hard constraints:")
            for key, value in sorted(self.constraints.items()):
                if value:
                    lines.append(f"- {key}")

        if self.style_keywords:
            lines.append(f"Style keywords: {', '.join(self.style_keywords)}")

        if self.template_hint:
            lines.append(f"Template hint: {self.template_hint}")

        if self.intent_notes:
            lines.append("Directive notes (must follow):")
            for note in self.intent_notes:
                lines.append(f"- {note}")

        lines.append("Treat these extracted facts as user intent anchors. Do not ignore explicit constraints.")
        lines.append("--- END STRUCTURED USER INTENT ---")
        return "\n".join(lines)


_SIGNAL_KEYWORDS: dict[str, list[str]] = {
    "flying": ["fly", "flying", "hover", "hovering", "winged", "wings", "airborne"],
    "ranged_attack": [
        "ranged", "projectile", "shoot", "shooting", "fireball",
        "fire breath", "fire-breath", "fire breathing", "fire-breathing", "breathes fire", "breath fire",
        "flame", "arrow", "beam", "blast", "spit",
    ],
    "exploding": ["explode", "exploding", "explosion", "detonate", "bomb", "self-destruct"],
    "passive": ["passive", "friendly", "peaceful", "docile", "harmless"],
    "tameable": ["tame", "tameable", "tamable", "pet", "mount", "rideable", "ridable"],
    "aquatic": ["aquatic", "water", "underwater", "swim", "swimming", "fish", "ocean", "sea"],
    "climbing": ["climb", "climbing", "crawl", "wall climb", "spider-like"],
    "boss": ["boss", "miniboss", "mini-boss", "elite", "legendary", "titan"],
    "geometry_edit": ["geometry", "model", "shape", "bones", "3d", "body", "head", "legs", "wings"],
    "visual_edit": ["texture", "skin", "look", "appearance", "color", "colored", "paint", "visual"],
}

_STYLE_KEYWORDS = [
    "lava", "fire", "ice", "crystal", "shadow", "robot", "ghost", "stone",
    "wood", "mushroom", "gold", "diamond", "rhino", "dragon", "golem",
    "spider", "bird", "fish", "fox", "bear", "tiger", "phoenix",
]

_TEMPLATE_KEYWORDS: dict[str, list[str]] = {
    "humanoid": ["humanoid", "human", "zombie", "skeleton", "villager", "warrior", "knight"],
    "small_animal": [
        "pig", "sheep", "rabbit", "chicken", "cat", "dog", "pet",
        "clifford", "puppy", "pooch", "canine", "dachshund", "husky", "corgi",
    ],
    "large_animal": ["cow", "horse", "wolf", "bear", "lion", "tiger", "rhino", "elephant"],
    "bird": ["bird", "parrot", "owl", "eagle", "crow", "wings"],
    "fish": ["fish", "salmon", "cod", "shark", "dolphin"],
    "insect": ["spider", "bee", "scorpion", "ant", "bug", "insect"],
    "flying": ["bat", "dragon", "phantom", "wyvern", "phoenix"],
    "golem": ["golem", "construct"],
    "robot": ["robot", "mech", "android", "automaton"],
}

_STAT_PATTERNS = [
    (re.compile(r"\bset\s+(?:the\s+)?(hp|health|damage|speed|scale)\s+to\s+([0-9]+(?:\.[0-9]+)?)", re.I), "set"),
    (re.compile(r"\bmake\s+(?:it\s+)?(faster|slower|bigger|smaller)\b", re.I), "qualitative"),
    (re.compile(r"\b(double|triple|halve)\s+(?:the\s+)?(hp|health|damage|speed|scale)\b", re.I), "multiplier"),
    (re.compile(r"\b(increase|decrease)\s+(?:the\s+)?(hp|health|damage|speed|scale)\s+(?:by\s+([0-9]+(?:\.[0-9]+)?))?\b", re.I), "delta"),
]

# Prefer word-boundary matching so "giant" does not match insect keyword "ant".
_FLYING_CREATURE_PRIMARY: tuple[str, ...] = (
    "dragon",
    "wyvern",
    "phantom",
    "phoenix",
    "pterodactyl",
)


def _template_kw_matches(prompt_lower: str, kw: str) -> bool:
    if " " in kw:
        return kw in prompt_lower
    return re.search(rf"\b{re.escape(kw)}\b", prompt_lower) is not None


_CONSTRAINT_PATTERNS: dict[str, list[str]] = {
    "preserve_geometry": ["keep geometry", "same geometry", "don't change geometry", "do not change geometry"],
    "preserve_texture": ["keep texture", "same texture", "don't change texture", "do not change texture"],
    "preserve_behavior": ["keep behavior", "same behavior", "don't change behavior", "do not change behavior"],
    "geometry_requested": ["geometry", "model", "shape", "bones", "3d model", "custom model"],
    "visual_requested": ["texture", "appearance", "skin", "look", "color"],
}


def _coerce_number(raw: str) -> float | int | None:
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return None
    return int(num) if num.is_integer() else num


def _normalize_field(field: str) -> str:
    return "hp" if field.lower() == "health" else field.lower()


def _extract_signals(prompt_lower: str) -> list[PromptSignal]:
    signals: list[PromptSignal] = []
    for name, keywords in _SIGNAL_KEYWORDS.items():
        matched = [kw for kw in keywords if kw in prompt_lower]
        if matched:
            confidence = min(1.0, 0.35 + 0.2 * len(matched))
            signals.append(PromptSignal(name=name, confidence=confidence, evidence=matched[:4]))
    signals.sort(key=lambda sig: (-sig.confidence, sig.name))
    return signals


def _extract_changes(prompt: str) -> list[PromptChange]:
    changes: list[PromptChange] = []
    for pattern, op_type in _STAT_PATTERNS:
        for match in pattern.finditer(prompt):
            text = match.group(0)
            if op_type == "set":
                field = _normalize_field(match.group(1))
                value = _coerce_number(match.group(2))
                changes.append(PromptChange(field=field, operation="set", value=value, evidence=text))
            elif op_type == "qualitative":
                word = match.group(1).lower()
                field = "speed" if word in ("faster", "slower") else "scale"
                changes.append(PromptChange(field=field, operation=word, evidence=text))
            elif op_type == "multiplier":
                multiplier = {"double": 2, "triple": 3, "halve": 0.5}[match.group(1).lower()]
                field = _normalize_field(match.group(2))
                changes.append(PromptChange(field=field, operation="multiply", value=multiplier, evidence=text))
            elif op_type == "delta":
                field = _normalize_field(match.group(2))
                direction = match.group(1).lower()
                value = _coerce_number(match.group(3)) if match.group(3) else None
                changes.append(PromptChange(field=field, operation=direction, value=value, evidence=text))
    return changes


def _extract_constraints(prompt_lower: str) -> dict[str, bool]:
    constraints: dict[str, bool] = {}
    for name, phrases in _CONSTRAINT_PATTERNS.items():
        constraints[name] = any(phrase in prompt_lower for phrase in phrases)
    return constraints


def _extract_style_keywords(prompt_lower: str) -> list[str]:
    return [kw for kw in _STYLE_KEYWORDS if kw in prompt_lower]


def _detect_template_hint(prompt_lower: str, signals: list[PromptSignal]) -> str:
    def any_kw(keywords: list[str]) -> bool:
        return any(_template_kw_matches(prompt_lower, kw) for kw in keywords)

    small_kws = _TEMPLATE_KEYWORDS["small_animal"]
    large_kws = _TEMPLATE_KEYWORDS["large_animal"]
    wants_pure_flying_creature = any_kw(list(_FLYING_CREATURE_PRIMARY))
    has_quadruped_name = any_kw(small_kws) or any_kw(large_kws)

    if has_quadruped_name and not wants_pure_flying_creature:
        if any_kw(small_kws):
            return "small_animal"
        return "large_animal"

    for template_name, keywords in _TEMPLATE_KEYWORDS.items():
        if any_kw(keywords):
            return template_name
    if any(signal.name == "geometry_edit" for signal in signals):
        return "humanoid"
    return ""


def _collect_intent_notes(prompt_lower: str, signals: list[PromptSignal]) -> list[str]:
    notes: list[str] = []

    def any_kw(keywords: list[str]) -> bool:
        return any(_template_kw_matches(prompt_lower, kw) for kw in keywords)

    small_kws = _TEMPLATE_KEYWORDS["small_animal"]
    large_kws = _TEMPLATE_KEYWORDS["large_animal"]
    explicit_dragon_like = any_kw(list(_FLYING_CREATURE_PRIMARY))
    mammal_hits = any_kw(small_kws) or any_kw(large_kws)

    wants_fly = any(s.name == "flying" for s in signals)
    wants_breath_or_spit = any(s.name == "ranged_attack" for s in signals)

    if mammal_hits and not explicit_dragon_like and (wants_fly or wants_breath_or_spit):
        notes.append(
            "Named mammal/pet keywords with flying or ranged/flame attack: keep a QUADRUPED layout "
            "(body, head, leg0-leg3). If flying is requested, add wing_left and wing_right attached at the torso; "
            "do not replace the body with a horizontal dragon or duck-like hull. "
            "Use a geometry id that matches the animal (e.g. geometry.custom_clifford), not geometry.custom_dragon, "
            "unless the user explicitly asked for a dragon."
        )

    if re.search(r"\b(dragon|wyvern|wyrm|drake)\b", prompt_lower):
        notes.append(
            "Dragon / wyvern style: use **four legs** (e.g. leg_front_left, leg_front_right, leg_back_left, "
            "leg_back_right), plus wing_left and wing_right on the body, head at negative Z. "
            "Place the **bottom of the feet / lowest body cube at Y=0** so the mob stands on the ground in-game "
            "(do not leave the whole rig floating above y=0)."
        )

    if re.search(r"\bclifford\b", prompt_lower) or re.search(r"big\s+red\s+dog", prompt_lower):
        notes.append(
            "Clifford / big red dog: set scale to at least 2.0, enlarge body and head cubes (roughly 12–20 units wide "
            "for the torso), and raise collision_box (e.g. height 1.6–2.2) so the mob reads as large."
        )
    elif re.search(r"\b(giant|huge|massive|enormous)\b", prompt_lower):
        notes.append(
            "User asked for very large size: use scale >= 1.9 with proportionally larger cubes and collision_box."
        )
    elif re.search(r"\bbig\b", prompt_lower) and any_kw(
        ["dog", "wolf", "cat", "clifford", "horse", "cow", "pig", "bear", "lion", "tiger"]
    ):
        notes.append(
            "User asked for a big animal: use scale >= 1.7 with larger body/head cubes than a default wolf-sized mob."
        )

    return notes


def extract_prompt_intents(prompt: str, category: str = "entity_logic_ai") -> PromptIntentProfile:
    """Extract structured prompt facts from a free-form instruction."""
    prompt = (prompt or "").strip()
    prompt_lower = prompt.lower()

    signals = _extract_signals(prompt_lower)
    requested_changes = _extract_changes(prompt)
    constraints = _extract_constraints(prompt_lower)
    style_keywords = _extract_style_keywords(prompt_lower)
    template_hint = _detect_template_hint(prompt_lower, signals)
    intent_notes = _collect_intent_notes(prompt_lower, signals)

    return PromptIntentProfile(
        category=category,
        signals=signals,
        requested_changes=requested_changes,
        constraints=constraints,
        style_keywords=style_keywords,
        template_hint=template_hint,
        intent_notes=intent_notes,
    )
