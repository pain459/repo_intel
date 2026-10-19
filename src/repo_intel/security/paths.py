"""Path safety: confinement, traversal detection, symlink escape prevention."""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SecurityConfig:
    """Runtime configuration for path security."""

    # Trusted roots discovered at startup. Repos must be inside one of these.
    allowed_roots: list[str] = field(default_factory=list)

    # Maximum depth for relative paths (prevent absurdly deep nesting).
    max_path_depth: int = 200

    # Allow symlinks inside repos? False by default (plan §10).
    allow_symlinks: bool = False

    # File extensions that are never indexed (credential-adjacent).
    secret_extensions: set[str] = field(
        default_factory=lambda: {
            ".pem", ".key", ".p12", ".pfx", ".keystore",
            ".jks", ".crt", ".cer", ".der",
        }
    )

    # Filenames that are never indexed.
    secret_filenames: set[str] = field(
        default_factory=lambda: {
            ".env", ".env.local", ".env.production", ".env.development",
            "id_rsa", "id_ed25519", "id_ecdsa",
            "netrc", ".netrc",
            "htpasswd",
            "terraform.tfvars",
        }
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def resolve_safe(base: str, target: str) -> str:
    """Resolve *target* relative to *base* and return the real absolute path.

    Raises ``ValueError`` on traversal escape or symlink hop outside *base*.
    """
    base = os.path.realpath(base)
    full = os.path.realpath(os.path.join(base, target))
    if not full.startswith(base + os.sep) and full != base:
        raise PathTraversalError(
            f"Path escapes repository root: {full!r} ∉ {base!r}"
        )
    return full


def is_inside_allowed_root(path: str, roots: list[str]) -> bool:
    """Return True if *path* is under one of the allowed roots."""
    real = os.path.realpath(path)
    for root in roots:
        real_root = os.path.realpath(root)
        if real == real_root or real.startswith(real_root + os.sep):
            return True
    return False


def is_safe_relative_path(rel_path: str) -> bool:
    """Return True if *rel_path* is a safe, non-traversing relative path.

    Rejects ``..`` components, absolute leaks, and excessively deep nesting.
    """
    p = pathlib.PurePosixPath(rel_path)
    if p.is_absolute():
        return False
    parts = p.parts
    if ".." in parts:
        return False
    if len(parts) > 200:
        return False
    return True


# ---------------------------------------------------------------------------
# Secret file detection
# ---------------------------------------------------------------------------


def is_secret_file(rel_path: str, config: SecurityConfig | None = None) -> bool:
    """Return True if the file looks like a credential or secret store."""
    if config is None:
        config = SecurityConfig()
    basename = os.path.basename(rel_path)
    if basename.lower() in config.secret_filenames:
        return True
    _, ext = os.path.splitext(basename.lower())
    if ext in config.secret_extensions:
        return True
    return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SecurityError(Exception):
    """Base class for security violations."""

    pass


class PathTraversalError(SecurityError):
    """Raised when a path escapes its allowed boundary."""

    pass


class SymlinkEscapeError(SecurityError):
    """Raised when a symlink resolves outside the repository root."""

    pass
