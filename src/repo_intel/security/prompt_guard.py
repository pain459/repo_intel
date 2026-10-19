"""Prompt-injection detection for search queries.

Catches common adversarial patterns in user-supplied query text before the
text reaches the embedding model or database.  This is a heuristic filter,
not a substitute for proper input validation at the application boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Patterns — compiled once at module load
# ---------------------------------------------------------------------------

# Ignore-prefixed instructions (e.g. "Ignore previous instructions and ...")
_RE_IGNORE_INSTRUCTIONS = re.compile(
    r"(?:ignore|disregard|override|bypass|forget|drop)"
    r"\s+(?:all\s+)?(?:the\s+)?"
    r"(?:previous\s+|prior\s+)?"
    r"(?:system\s+)?"
    r"(?:instructions|rules|guidelines|context|message|prompt)",
    re.IGNORECASE,
)

# Role-play / persona adoption ("You are now / Act as ...")
_RE_ROLE_PLAY = re.compile(
    r"(?:you\s+(?:are\s+)?(?:now\s+)?(?:(?:are|become)\s+)?|you\s+(?:should|must)\s+"
    r"(?:are|become)\s+|act\s+(?:as|like)\s+|pretend\s+(?:to\s+)?be\s+)"
    r"(?:a|an|the)\s+\w+",
    re.IGNORECASE,
)

# Output-format extraction ("output only", "return raw", "print the system prompt")
_RE_LEAK_PROMPT = re.compile(
    r"(?:system\s*prompt|system\s*message|initial\s*instructions)",
    re.IGNORECASE,
)

# Base64-encoded payloads (>64 chars of base64 is often obfuscated injection)
_RE_BASE64_BLOB = re.compile(
    r"[A-Za-z0-9+/]{64,}={0,2}"
)

# Leet speak obfuscation markers
_LEET_MAP = {"@": "a", "3": "e", "1": "i", "0": "o", "$": "s", "7": "t", "+": "t"}


def _deleet(text: str) -> str:
    """Normalize leet-speak characters for pattern matching."""
    return "".join(_LEET_MAP.get(ch, ch) for ch in text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class PromptGuardReport:
    """Outcome of scanning one query."""

    is_suspicious: bool
    matched_patterns: list[str]


def check_prompt_injection(query: str) -> PromptGuardReport:
    """Scan *query* for adversarial injection patterns.

    Returns a ``PromptGuardReport`` with flags and matched pattern labels.
    """
    if not query:
        return PromptGuardReport(is_suspicious=False, matched_patterns=[])

    matched: list[str] = []
    normalized = _deleet(query)

    if _RE_IGNORE_INSTRUCTIONS.search(normalized):
        matched.append("ignore_instructions")
    if _RE_ROLE_PLAY.search(normalized):
        matched.append("role_play")
    if _RE_LEAK_PROMPT.search(normalized):
        matched.append("system_prompt_leak")
    if _RE_BASE64_BLOB.search(query):
        matched.append("base64_payload")

    return PromptGuardReport(
        is_suspicious=len(matched) > 0,
        matched_patterns=matched,
    )


def sanitize_query(query: str) -> str:
    """Return *query* stripped of obvious injection payloads.

    If the query is flagged as fully adversarial (no natural language content
    beyond the injection), returns an empty string so the search returns no
    results. Otherwise returns the original query unchanged.
    """
    report = check_prompt_injection(query)
    if report.is_suspicious:
        remaining = query
        for pattern in (_RE_IGNORE_INSTRUCTIONS, _RE_ROLE_PLAY, _RE_LEAK_PROMPT):
            remaining = pattern.sub("", remaining)
        cleaned = remaining.strip()
        # Remove common connectors left behind after injection stripped
        cleaned = re.sub(
            r"^(?:and|so|then|just|only|please|okay|sure)\s*",
            "", cleaned, flags=re.IGNORECASE,
        )
        cleaned = cleaned.strip()
        if not cleaned or len(cleaned) < len(query) * 0.3:
            return ""
        return cleaned
    return query
