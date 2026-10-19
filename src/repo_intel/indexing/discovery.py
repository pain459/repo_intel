"""File discovery with gitignore filtering, binary detection, and security."""

from __future__ import annotations

import hashlib
import logging
import os
import stat
from dataclasses import dataclass

from pathspec import GitIgnoreSpec, PathSpec

from repo_intel.config import get_settings
from repo_intel.security.paths import (
    SecurityConfig as _SecurityConfig,
)
from repo_intel.security.paths import (
    is_safe_relative_path,
    is_secret_file,
)

logger = logging.getLogger(__name__)

# Default security config (loaded once).
_DEFAULT_SECURITY = _SecurityConfig()

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_default = get_settings()

# Well-known ignore patterns (always excluded)
_ALWAYS_EXCLUDE = {
    "*.pyc",
    "*.pyo",
    "__pycache__",
    ".git/",
    ".tox/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    "node_modules/",
    ".venv/",
    "venv/",
    ".env/",
    ".env",          # the .env file itself (not just .env/ directories)
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.test",
    "*.egg-info/",
    "*.whl",
    "*.so",
    "*.dylib",
    "*.dll",
    ".DS_Store",
    "Thumbs.db",
    # Credential files
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    ".ssh/",
    "netrc",
    ".netrc",
    "htpasswd",
    "terraform.tfvars",
}

# Known binary extensions
_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".tgz",
    ".exe", ".bin", ".dat", ".o", ".a", ".lib",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".mp4", ".avi", ".mov", ".wav",
    ".svg",  # vector, but skip for indexing
}


@dataclass
class DiscoveredFile:
    """Metadata for a file eligible for indexing."""

    repository_path: str  # absolute path to repo root
    relative_path: str  # path relative to repo root
    size_bytes: int
    content_hash: str  # SHA-256 hex digest
    language: str  # rough language guess from extension
    worktree_dirty: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_hash(file_path: os.PathLike[str] | str) -> str | None:
    """Read *file_path* and return sha256 hex digest, or None on failure."""
    try:
        raw = open(file_path, "rb").read()
        return hashlib.sha256(raw).hexdigest()
    except (OSError, PermissionError):
        return None


def _is_binary(file_path: os.PathLike[str] | str, size_limit: int = 80) -> bool:
    """Heuristic: open in binary mode, check for null bytes in first N bytes."""
    try:
        with open(file_path, "rb") as f:
            head = f.read(size_limit)
        return b"\x00" in head
    except (OSError, PermissionError):
        return True  # treat unreadable as binary


def _load_gitignore(repo_root: str) -> PathSpec | None:
    """Load .gitignore from *repo_root* if it exists."""
    gitignore_path = os.path.join(repo_root, ".gitignore")
    if not os.path.isfile(gitignore_path):
        return None
    try:
        patterns = []
        with open(gitignore_path) as f:
            patterns.extend(line.rstrip("\n") for line in f)
        return GitIgnoreSpec.from_lines(patterns)
    except OSError:
        return None


def _load_exclude_patterns(repo_root: str) -> PathSpec | None:
    """Load .git/info/exclude or .repo_intel_ignore for additional exclusions."""
    exclude_files = [
        os.path.join(repo_root, ".git", "info", "exclude"),
        os.path.join(repo_root, ".repo_intel_ignore"),
    ]
    patterns: list[str] = list(_ALWAYS_EXCLUDE)
    for ef in exclude_files:
        if os.path.isfile(ef):
            try:
                with open(ef) as f:
                    patterns.extend(line.rstrip("\n") for line in f)
            except OSError:
                pass
    return GitIgnoreSpec.from_lines(patterns) if patterns else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_files(
    repo_root: str,
    gitignore: PathSpec | None = None,
    exclude_spec: PathSpec | None = None,
    max_bytes: int | None = None,
) -> list[DiscoveredFile]:
    """Walk *repo_root* and return files eligible for indexing.

    Parameters
    ----------
    repo_root:
        Absolute path to the Git repo root.
    gitignore:
        Pre-loaded ``.gitignore`` spec (loaded from disk if None).
    exclude_spec:
        Additional exclusion patterns (always-excluded dirs, etc.).
    max_bytes:
        Maximum file size in bytes; larger files are skipped.

    Returns
    -------
    list[DiscoveredFile] of eligible files, sorted by relative path.
    """
    if max_bytes is None:
        max_bytes = _default.max_file_bytes

    if gitignore is None:
        gitignore = _load_gitignore(repo_root)
    if exclude_spec is None:
        exclude_spec = _load_exclude_patterns(repo_root)

    results: list[DiscoveredFile] = []

    for dirpath, dirnames, filenames in os.walk(repo_root, followlinks=False):
        # Prune excluded directories early
        rel_dir = os.path.relpath(dirpath, repo_root)
        if rel_dir != ".":
            if gitignore and gitignore.match_file(rel_dir + "/"):
                dirnames.clear()
                continue
            if exclude_spec and exclude_spec.match_file(rel_dir + "/"):
                dirnames.clear()
                continue

        # Skip hidden directories (node_modules, .git, etc.)
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d != "node_modules"
        ]

        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abs_path, repo_root)

            # Quick exclusion checks
            if gitignore and gitignore.match_file(rel_path):
                continue
            if exclude_spec and exclude_spec.match_file(rel_path):
                continue

            # Symlink check
            if os.path.islink(abs_path):
                continue

            # Security: reject traversal paths
            if not is_safe_relative_path(rel_path):
                logger.warning("Unsafe path rejected: %s", rel_path)
                continue

            # Security: skip secret/credential files
            if is_secret_file(rel_path):
                logger.debug("Secret file skipped: %s", rel_path)
                continue

            # Size check
            try:
                file_stat = os.stat(abs_path)
            except OSError:
                continue

            # Skip non-regular files
            if not stat.S_ISREG(file_stat.st_mode):
                continue

            if file_stat.st_size > max_bytes:
                continue

            # Skip empty files
            if file_stat.st_size == 0:
                continue

            # Binary check
            ext = _get_ext(filename)
            if ext in _BINARY_EXTS:
                continue
            if _is_binary(abs_path):
                continue

            # Compute content hash
            content_hash = _compute_hash(abs_path)
            if content_hash is None:
                continue

            results.append(
                DiscoveredFile(
                    repository_path=repo_root,
                    relative_path=rel_path,
                    size_bytes=file_stat.st_size,
                    content_hash=content_hash,
                    language=_detect_language(rel_path),
                )
            )

    results.sort(key=lambda f: f.relative_path)
    return results


# ---------------------------------------------------------------------------
# Language detection (lightweight, extension-based)
# ---------------------------------------------------------------------------

_LANG_EXT_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".md": "markdown",
    ".rst": "rst",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".dockerfile": "dockerfile",
    ".tf": "hcl",
    ".lua": "lua",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".erl": "erlang",
    ".ex": "elixir",
    ".exs": "elixir",
    ".dart": "dart",
    ".cs": "csharp",
    ".fs": "fsharp",
    ".r": "r",
    ".R": "r",
    ".jl": "julia",
    ".v": "verilog",
    ".sv": "systemverilog",
    ".proto": "protobuf",
    ".graphql": "graphql",
    ".vue": "vue",
    ".svelte": "svelte",
    ".elm": "elm",
    ".clj": "clojure",
    ".lisp": "lisp",
    ".zig": "zig",
    ".nim": "nim",
}


def _get_ext(filename: str) -> str:
    """Return the lowercase extension including dot, or ''."""
    _, ext = os.path.splitext(filename)
    return ext.lower()


def _detect_language(relative_path: str) -> str:
    """Guess the programming language from file extension."""
    # Special case: Dockerfile
    basename = os.path.basename(relative_path)
    if basename.lower() in ("dockerfile", "containerfile"):
        return "dockerfile"
    return _LANG_EXT_MAP.get(_get_ext(relative_path), "")
