"""Implementation boundaries for repository-intelligence services."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from repo_intel.domain import (
    ContextPackage,
    ParsedFile,
    RepositoryRef,
    ScannedFile,
    SearchHit,
    SearchRequest,
)


@runtime_checkable
class RepositoryScanner(Protocol):
    def scan(self, repository: RepositoryRef) -> tuple[ScannedFile, ...]: ...


@runtime_checkable
class MetadataStore(Protocol):
    def replace_inventory(
        self,
        repository: RepositoryRef,
        files: Sequence[ScannedFile],
    ) -> None: ...


@runtime_checkable
class SourceParser(Protocol):
    def parse(self, file: ScannedFile, source: str) -> ParsedFile: ...


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...


@runtime_checkable
class Retriever(Protocol):
    def search(self, request: SearchRequest) -> tuple[SearchHit, ...]: ...


@runtime_checkable
class ContextComposer(Protocol):
    def compose(
        self,
        request: SearchRequest,
        hits: Sequence[SearchHit],
        token_budget: int,
    ) -> ContextPackage: ...


__all__ = [
    "ContextComposer",
    "Embedder",
    "MetadataStore",
    "RepositoryScanner",
    "Retriever",
    "SourceParser",
]
