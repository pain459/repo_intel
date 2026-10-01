"""Immutable records shared by indexing and retrieval modules."""

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from uuid import UUID

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require_nonblank(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be blank")


def _validate_relative_path(path: PurePosixPath) -> None:
    if str(path) in {"", "."} or path.is_absolute() or ".." in path.parts:
        raise ValueError("relative_path must stay within the repository")


def _validate_source_hash(source_hash: str) -> None:
    if _SHA256.fullmatch(source_hash) is None:
        raise ValueError("source_hash must be a lowercase SHA-256 digest")


class FileKind(StrEnum):
    """Scanner classification applied to a repository file."""

    PYTHON = "python"
    TEST = "test"
    DOCUMENTATION = "documentation"
    CONFIGURATION = "configuration"
    MIGRATION = "migration"
    GENERATED = "generated"
    BINARY = "binary"
    SENSITIVE = "sensitive"
    OVERSIZED = "oversized"
    IGNORED = "ignored"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class RepositoryRef:
    """Registered repository identity and canonical root."""

    repository_id: UUID
    root: Path

    def __post_init__(self) -> None:
        if not self.root.is_absolute():
            raise ValueError("repository root must be absolute")


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Traceable span within an authoritative repository file."""

    repository_id: UUID
    relative_path: PurePosixPath
    start_line: int
    end_line: int
    source_hash: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path)
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("line range must be one-based and ordered")
        _validate_source_hash(self.source_hash)


@dataclass(frozen=True, slots=True)
class ScannedFile:
    """Scanner output before source parsing."""

    repository_id: UUID
    relative_path: PurePosixPath
    kind: FileKind
    source_hash: str
    size_bytes: int

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path)
        _validate_source_hash(self.source_hash)
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")


@dataclass(frozen=True, slots=True)
class SymbolRecord:
    """Language parser output for one declared symbol."""

    symbol_id: str
    qualified_name: str
    kind: str
    location: SourceLocation

    def __post_init__(self) -> None:
        _require_nonblank("symbol_id", self.symbol_id)
        _require_nonblank("qualified_name", self.qualified_name)
        _require_nonblank("kind", self.kind)


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """Syntax-aware source chunk with optional symbol ownership."""

    chunk_id: str
    text: str
    location: SourceLocation
    symbol_id: str | None

    def __post_init__(self) -> None:
        _require_nonblank("chunk_id", self.chunk_id)
        _require_nonblank("text", self.text)
        if self.symbol_id is not None:
            _require_nonblank("symbol_id", self.symbol_id)


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """Complete structural parser result for one file."""

    file: ScannedFile
    symbols: tuple[SymbolRecord, ...]
    chunks: tuple[ChunkRecord, ...]


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Repository-scoped retrieval request."""

    repository_id: UUID
    query: str
    limit: int = 10

    def __post_init__(self) -> None:
        _require_nonblank("query", self.query)
        if self.limit < 1:
            raise ValueError("limit must be positive")


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Ranked evidence location and contributing retrieval signals."""

    location: SourceLocation
    score: float
    signals: tuple[str, ...]

    def __post_init__(self) -> None:
        if not math.isfinite(self.score):
            raise ValueError("score must be finite")
        for signal in self.signals:
            _require_nonblank("signal", signal)


@dataclass(frozen=True, slots=True)
class ContextPackage:
    """Budgeted evidence package returned to a coding agent."""

    query: str
    hits: tuple[SearchHit, ...]
    estimated_tokens: int
    token_budget: int

    def __post_init__(self) -> None:
        _require_nonblank("query", self.query)
        if self.token_budget < 1:
            raise ValueError("token_budget must be positive")
        if self.estimated_tokens < 0:
            raise ValueError("estimated_tokens must not be negative")
        if self.estimated_tokens > self.token_budget:
            raise ValueError("estimated_tokens must not exceed token_budget")
