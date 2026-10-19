"""Log credential redaction filter.

Applies the same secret-detection patterns used for content redaction to
log messages, preventing accidental credential leakage if a config value
or environment variable ends up in a log line.
"""

from __future__ import annotations

import logging
import re
from typing import Final

# ---------------------------------------------------------------------------
# Re-use the redaction patterns from security.redaction for consistency
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: Final[list[tuple[re.Pattern[str], str, int | None]]] = [
    # Private key headers
    (
        re.compile(
            r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+|DSA\s+)?PRIVATE\s+KEY-----",
            re.IGNORECASE,
        ),
        "****PRIVATE_KEY_REMOVED****",
        None,
    ),
    # GitHub tokens
    (
        re.compile(r"(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}", re.IGNORECASE),
        "***REDACTED***",
        None,
    ),
    # AWS access keys
    (re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"), "***REDACTED***", None),
    # Connection strings with embedded passwords
    (
        re.compile(r"(?:postgres|mysql|mongodb|redis)://[^:]+:([^@]+)@", re.IGNORECASE),
        "***REDACTED***",
        1,
    ),
    # Password / secret assignments
    (
        re.compile(
            r"(?:password|passwd|pwd|secret)\s*[=:]\s*['\"]?([^'\"\s#,;}{\]\"\\]{4,})"
            r"(?:['\"])?",
            re.IGNORECASE,
        ),
        "***REDACTED***",
        1,
    ),
    # Generic bearer / auth tokens
    (
        re.compile(
            r"(?:bearer|authorization)\s*[=:]\s*['\"]?\s*(Bearer\s+)?([A-Za-z0-9_\-./+=]{16,})",
            re.IGNORECASE,
        ),
        "***REDACTED***",
        2,
    ),
]

REDACTION_PLACEHOLDER: Final[str] = "***REDACTED***"


# ---------------------------------------------------------------------------
# Filter implementation
# ---------------------------------------------------------------------------


class CredentialFilter(logging.Filter):
    """Logging filter that redacts credential patterns from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Return True to allow the record, after redacting secrets."""
        record.msg = self._redact(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._redact(str(v)) for k, v in record.args.items()
                }
            else:
                record.args = tuple(self._redact(str(a)) for a in record.args)
        return True

    @staticmethod
    def _redact(text: str) -> str:
        """Apply secret patterns to *text* and return cleaned version."""
        for pattern, label, group_idx in _SECRET_PATTERNS:
            is_full = group_idx is None
            for match in pattern.finditer(text):
                span = match.span(0) if is_full else match.span(group_idx)
                text = text[: span[0]] + REDACTION_PLACEHOLDER + text[span[1] :]
        return text


def apply_credential_filter() -> None:
    """Add the credential filter to the root logger.

    Call this once during application startup (after ``setup_logging``).
    """
    root_logger = logging.getLogger()
    root_logger.addFilter(CredentialFilter())
