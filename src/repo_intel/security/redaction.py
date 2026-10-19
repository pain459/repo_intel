"""Secret scanning and redaction for indexed content.

Scans source chunks *before* storing them and replaces obviously secret
values with ``***REDACTED***`` placeholders.  This is a best-effort
heuristic layer, not a substitute for real secret management.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Secret patterns — compiled once at module load
# ---------------------------------------------------------------------------

# GitHub token patterns
_RE_GITHUB_TOKEN = re.compile(
    r"(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}", re.IGNORECASE
)

# Generic API key patterns (key=value, key: value, "key": "value")
_GENERIC_KEY_NAMES = (
    "api_key|api_secret|api_password|apikey|api_secret_key|"
    "access_token|access_key|secret_key|private_key|"
    "auth_token|bearer_token|token"
)
_RE_API_KEY = re.compile(
    r"(?:^|[\s\"':,])"
    r"(?:" + _GENERIC_KEY_NAMES + r")"
    r"(?:\s*[=:]\s*)"
    r'(?:["\']?)([A-Za-z0-9_\-./+=]{16,})',
    re.IGNORECASE,
)

# AWS-style keys / secrets
_RE_AWS_ACCESS = re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}")
_RE_AWS_SECRET = re.compile(
    r"(?:aws_secret_access_key|aws_secret_key)\s*[=:]\s*['\"]?([A-Za-z0-9/+=]{20,})"
)

# Password in config / env assignments (supports key=val, key: val, "key": "val")
_RE_PASSWORD_ASSIGN = re.compile(
    r"(?:password|passwd|pwd)\s*[=:]\s*['\"]?([^'\"\s#,;}{\]\"\\]{4,})"
    r"(?:['\"])?",
    re.IGNORECASE,
)

# Private key headers
_RE_PRIVATE_KEY = re.compile(
    r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+|DSA\s+)?PRIVATE\s+KEY-----",
    re.IGNORECASE,
)

# Generic bearer tokens
_RE_BEARER = re.compile(
    r"(?:bearer|authorization)\s*[=:]\s*['\"]?\s*(Bearer\s+)?([A-Za-z0-9_\-./+=]{16,})",
    re.IGNORECASE,
)

# Connection strings with embedded passwords
_RE_CONN_STRING = re.compile(
    r"(?:postgres|mysql|mongodb|redis)://[^:]+:([^@]+)@", re.IGNORECASE,
)

# Google / service account keys
_RE_GCP_KEY = re.compile(
    r"(?:AIza[0-9A-Za-z\-_]{35}|ya29\.[A-Za-z0-9_\-]+)",
    re.IGNORECASE,
)

ALL_PATTERNS: list[tuple[re.Pattern[str], str, int | None]] = [
    # Pattern, replacement label, group-to-redact (None means full match)
    (_RE_PRIVATE_KEY, "****PRIVATE_KEY_REMOVED****", None),
    (_RE_GITHUB_TOKEN, "***REDACTED***", None),
    (_RE_AWS_ACCESS, "***REDACTED***", None),
    (_RE_GCP_KEY, "***REDACTED***", None),
    (_RE_AWS_SECRET, "***REDACTED***", 1),
    (_RE_PASSWORD_ASSIGN, "***REDACTED***", 1),
    (_RE_CONN_STRING, "***REDACTED***", 1),
    (_RE_BEARER, "***REDACTED***", 2),
    (_RE_API_KEY, "***REDACTED***", 1),
]

REDACTION_PLACEHOLDER = "***REDACTED***"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class RedactionResult:
    """Outcome of scanning one chunk of text."""

    cleaned_text: str
    patterns_matched: int  # how many secret patterns were hit
    pattern_labels: list[str]  # human-readable labels for logging


def redact_content(text: str) -> RedactionResult:
    """Scan *text* for secret patterns and return cleaned version.

    Replaces secret values with ``***REDACTED***`` in-place.
    Returns a ``RedactionResult`` with cleanup outcome.
    """
    if not text:
        return RedactionResult(cleaned_text=text, patterns_matched=0, pattern_labels=[])

    matched: list[str] = []
    cleaned = text

    for pattern, label, group_idx in ALL_PATTERNS:
        is_full = group_idx is None
        for m in pattern.finditer(cleaned):
            matched.append(label)
            if is_full:
                span = m.span(0)
            else:
                span = m.span(group_idx)
            cleaned = cleaned[: span[0]] + REDACTION_PLACEHOLDER + cleaned[span[1] :]

    return RedactionResult(
        cleaned_text=cleaned,
        patterns_matched=len(matched),
        pattern_labels=matched,
    )
