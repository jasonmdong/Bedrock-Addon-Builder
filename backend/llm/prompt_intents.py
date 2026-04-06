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

    @property
    def has_content(self) -> bool:
        return bool(
            self.signals
            or self.requested_changes
            or self.constraints
            or self.style_keywords
            or self.template_hint
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

        lines.append("Treat these extracted facts as user intent anchors. Do not ignore explicit constraints.")
        lines.append("--- END STRUCTURED USER INTENT ---")
        return "\n".join(lines)


_SIGNAL_KEYWORDS: dict[str, list[str]] = {
    "flying": ["fly", "flying", "hover", "hovering", "winged", "wings", "airborne"],
    "ranged_attack": ["ranged", "projectile", "shoot", "shooting", "fireball", "fire breath", "fire-breath", "flame", "arrow", "beam", "blast", "spit"],
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
    "small_animal": ["pig", "sheep", "rabbit", "chicken", "cat", "dog", "pet"],
    "large_animal": ["cow", "horse", "wolf", "bear", "lion", "tiger", "rhino", "elephant"],
    "bird": ["bird", "parrot", "owl", "eagle", "crow", "wings"],
    "fish": ["fish", "salmon", "cod", "shark", "dolphin"],
    "insect": ["spider", "bee", "scorpion", "ant", "bug", "insect"],
    "flying": ["bat", "dragon", "phantom", "wyvern", "phoenix", "flying"],
    "golem": ["golem", "construct"],
    "robot": ["robot", "mech", "android", "automaton"],
}

_STAT_PATTERNS = [
    (re.compile(r"\bset\s+(?:the\s+)?(hp|health|damage|speed|scale)\s+to\s+([0-9]+(?:\.[0-9]+)?)", re.I), "set"),
    (re.compile(r"\bmake\s+(?:it\s+)?(faster|slower|bigger|smaller)\b", re.I), "qualitative"),
    (re.compile(r"\b(double|triple|halve)\s+(?:the\s+)?(hp|health|damage|speed|scale)\b", re.I), "multiplier"),
    (re.compile(r"\b(increase|decrease)\s+(?:the\s+)?(hp|health|damage|speed|scale)\s+(?:by\s+([0-9]+(?:\.[0-9]+)?))?\b", re.I), "delta"),
]

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
    for template_name, keywords in _TEMPLATE_KEYWORDS.items():
        if any(kw in prompt_lower for kw in keywords):
            return template_name
    if any(signal.name == "geometry_edit" for signal in signals):
        return "humanoid"
    return ""


def extract_prompt_intents(prompt: str, category: str = "entity_logic_ai") -> PromptIntentProfile:
    """Extract structured prompt facts from a free-form instruction."""
    prompt = (prompt or "").strip()
    prompt_lower = prompt.lower()

    signals = _extract_signals(prompt_lower)
    requested_changes = _extract_changes(prompt)
    constraints = _extract_constraints(prompt_lower)
    style_keywords = _extract_style_keywords(prompt_lower)
    template_hint = _detect_template_hint(prompt_lower, signals)

    return PromptIntentProfile(
        category=category,
        signals=signals,
        requested_changes=requested_changes,
        constraints=constraints,
        style_keywords=style_keywords,
        template_hint=template_hint,
    )
