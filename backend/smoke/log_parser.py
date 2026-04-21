"""Session-sliced Bedrock Dedicated Server log scanner.

Parses captured BDS stdout for content errors and warnings without relying
on generic substring matching.  Each pattern is tied to a named rule so
callers can filter, deduplicate, and report precisely.

Usage:
    from backend.smoke.log_parser import parse_session_log, SmokeResult
    errors, warnings = parse_session_log(lines)
"""
import re
from dataclasses import dataclass, field
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Pattern catalog
# ---------------------------------------------------------------------------

class _Pattern(NamedTuple):
    regex: re.Pattern
    rule: str
    is_error: bool   # False → warning


# Ordered: more specific patterns first so "break on first match" is correct.
PATTERNS: list[_Pattern] = [
    # ── Pack loading failures ────────────────────────────────────────────────
    _Pattern(re.compile(r"\[Packs\].*can.t.*(?:load|parse)", re.I),  "pack_load_failure",    True),
    _Pattern(re.compile(r"\[Packs\].*failed.*load",          re.I),  "pack_load_failure",    True),
    _Pattern(re.compile(r"\[Packs\].*invalid.*manifest",     re.I),  "invalid_manifest",     True),
    _Pattern(re.compile(r"\[Packs\].*missing.*manifest",     re.I),  "missing_manifest",     True),
    _Pattern(re.compile(r"\[Packs\].*can.t.*find",           re.I),  "pack_not_found",       True),

    # ── ContentLog (structured output from BDS 1.20+) ───────────────────────
    _Pattern(re.compile(r"\[ContentLog\]\s*\[error\]",       re.I),  "content_log_error",    True),
    _Pattern(re.compile(r"\[ContentLog\]\s*\[warning\]",     re.I),  "content_log_warning",  False),

    # ── Entity / component errors ────────────────────────────────────────────
    _Pattern(re.compile(r"Unable to find (?:definition|component) for\s+['\"]?(\S+)", re.I),
             "missing_definition", True),
    _Pattern(re.compile(r"Failed to (?:load|resolve) entity\s+['\"]?(\S+)", re.I),
             "entity_load_failure", True),
    _Pattern(re.compile(r"Entity file .+ (?:has invalid|with invalid) format_version", re.I),
             "bad_format_version", True),
    _Pattern(re.compile(r"Invalid JSON in .+",                re.I),  "invalid_json",         True),
    _Pattern(re.compile(r"JSON parsing error",                re.I),  "json_parse_error",     True),

    # ── Texture / geometry ───────────────────────────────────────────────────
    _Pattern(re.compile(r"Texture .+ not found",              re.I),  "missing_texture",      True),
    _Pattern(re.compile(r"Geometry .+ not found",             re.I),  "missing_geometry",     True),
    _Pattern(re.compile(r"Unknown geometry",                  re.I),  "unknown_geometry",     True),
    _Pattern(re.compile(r"render controller .+ not found",    re.I),  "missing_render_ctrl",  True),

    # ── Script errors ────────────────────────────────────────────────────────
    _Pattern(re.compile(r"\[Script\].*[Ee]rror",              re.I),  "script_error",         True),
    _Pattern(re.compile(r"\[Script\].*[Ww]arning",           re.I),  "script_warning",        False),

    # ── Summon feedback (only meaningful after pack loaded) ──────────────────
    _Pattern(re.compile(r"No entity with type .+ was found",  re.I),  "entity_not_registered", True),
    _Pattern(re.compile(r"summon.*failed",                    re.I),  "summon_failed",         True),
    _Pattern(re.compile(r"Unable to summon",                  re.I),  "summon_failed",         True),
    _Pattern(re.compile(r"Unknown command",                   re.I),  "unknown_command",        True),

    # ── Soft warnings ────────────────────────────────────────────────────────
    _Pattern(re.compile(r"Unknown (?:block|item|component)\s+['\"]?(\S+)", re.I),
             "unknown_component", False),
    _Pattern(re.compile(r"deprecated",                        re.I),  "deprecated_api",        False),
]


# BDS lines that signal the world is loaded and the server is accepting commands.
READY_PATTERNS: list[re.Pattern] = [
    re.compile(r"Server started[.!]", re.I),
    re.compile(r"Server started\b",   re.I),
]


# Lines to skip — BDS startup noise unrelated to pack content.
IGNORE_PATTERNS: list[re.Pattern] = [
    re.compile(r"Running AutoCompaction",        re.I),
    re.compile(r"LevelStorage.*opened",          re.I),
    re.compile(r"IPv[46].*not supported",        re.I),
    re.compile(r"NO LOG FILE",                   re.I),
    re.compile(r"MemoryMappedFile",              re.I),
    re.compile(r"(Windows|Linux) x86_64",        re.I),
    re.compile(r"^$"),  # blank lines
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SmokeIssue:
    rule: str
    line: str
    line_number: int
    is_error: bool

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "line": self.line.strip(),
            "line_number": self.line_number,
            "severity": "error" if self.is_error else "warning",
        }


@dataclass
class SmokeResult:
    passed: bool
    errors: list[SmokeIssue] = field(default_factory=list)
    warnings: list[SmokeIssue] = field(default_factory=list)
    bds_ready: bool = False
    mob_identifiers: list[str] = field(default_factory=list)
    session_log: str = ""       # full captured stdout (capped to last 20 KB)
    error_message: str = ""     # set when BDS failed to start or timed out

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "bds_ready": self.bds_ready,
            "mob_identifiers": self.mob_identifiers,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "session_log": self.session_log[-20_000:],
            "error_message": self.error_message,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_session_log(lines: list[str]) -> tuple[list[SmokeIssue], list[SmokeIssue]]:
    """Scan *lines* for known Bedrock content error/warning patterns.

    Returns ``(errors, warnings)`` — each a list of :class:`SmokeIssue`.

    Rules:
    - Lines matching an IGNORE_PATTERN are skipped entirely.
    - Only the first matching PATTERN per line fires (patterns are ordered
      most-specific first, so this avoids duplicate issues per line).
    - Deduplication by (rule, stripped-line) is applied so BDS log spam
      (e.g. the same missing texture repeated 40×) produces one issue.
    """
    errors: list[SmokeIssue] = []
    warnings: list[SmokeIssue] = []
    seen: set[tuple[str, str]] = set()

    for i, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")

        if any(p.search(line) for p in IGNORE_PATTERNS):
            continue

        for pat in PATTERNS:
            if pat.regex.search(line):
                key = (pat.rule, line.strip())
                if key in seen:
                    break  # deduplicate
                seen.add(key)
                issue = SmokeIssue(
                    rule=pat.rule,
                    line=line,
                    line_number=i,
                    is_error=pat.is_error,
                )
                (errors if pat.is_error else warnings).append(issue)
                break  # one rule per line

    return errors, warnings
