import math
from collections.abc import Callable, Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path, PurePosixPath
from typing import cast
from uuid import UUID, uuid4

import pytest

from repo_intel.domain import (
    ChunkRecord,
    ContextPackage,
    FileKind,
    ParsedFile,
    RepositoryRef,
    ScannedFile,
    SearchHit,
    SearchRequest,
    SourceLocation,
    SymbolRecord,
)
from repo_intel.ports import (
    ContextComposer,
    Embedder,
    MetadataStore,
    RepositoryScanner,
    Retriever,
    SourceParser,
)

REPOSITORY_ID = UUID("12345678-1234-5678-1234-567812345678")
SOURCE_HASH = "a" * 64


def valid_location() -> SourceLocation:
    return SourceLocation(
        repository_id=REPOSITORY_ID,
        relative_path=PurePosixPath("src/example.py"),
        start_line=1,
        end_line=3,
        source_hash=SOURCE_HASH,
    )


def valid_file() -> ScannedFile:
    return ScannedFile(
        repository_id=REPOSITORY_ID,
        relative_path=PurePosixPath("src/example.py"),
        kind=FileKind.PYTHON,
        source_hash=SOURCE_HASH,
        size_bytes=80,
    )


def test_domain_records_are_immutable() -> None:
    repository = RepositoryRef(repository_id=REPOSITORY_ID, root=Path("/workspace/project"))

    with pytest.raises(FrozenInstanceError):
        setattr(repository, "root", Path("/another/project"))


@pytest.mark.parametrize("root", [Path("project"), Path(".")])
def test_repository_root_must_be_absolute(root: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        RepositoryRef(repository_id=uuid4(), root=root)


@pytest.mark.parametrize(
    "relative_path",
    [PurePosixPath("/absolute.py"), PurePosixPath("../outside.py"), PurePosixPath(".")],
)
def test_source_location_rejects_unsafe_relative_paths(relative_path: PurePosixPath) -> None:
    with pytest.raises(ValueError, match="relative_path"):
        SourceLocation(
            repository_id=REPOSITORY_ID,
            relative_path=relative_path,
            start_line=1,
            end_line=1,
            source_hash=SOURCE_HASH,
        )


@pytest.mark.parametrize(
    ("start_line", "end_line"),
    [(0, 1), (-1, 1), (3, 2)],
)
def test_source_location_rejects_invalid_line_ranges(start_line: int, end_line: int) -> None:
    with pytest.raises(ValueError, match="line"):
        SourceLocation(
            repository_id=REPOSITORY_ID,
            relative_path=PurePosixPath("src/example.py"),
            start_line=start_line,
            end_line=end_line,
            source_hash=SOURCE_HASH,
        )


@pytest.mark.parametrize("source_hash", ["", "a" * 63, "A" * 64, "g" * 64])
def test_records_reject_invalid_sha256(source_hash: str) -> None:
    with pytest.raises(ValueError, match="source_hash"):
        ScannedFile(
            repository_id=REPOSITORY_ID,
            relative_path=PurePosixPath("src/example.py"),
            kind=FileKind.PYTHON,
            source_hash=source_hash,
            size_bytes=1,
        )


def test_scanned_file_rejects_negative_size() -> None:
    with pytest.raises(ValueError, match="size_bytes"):
        ScannedFile(
            repository_id=REPOSITORY_ID,
            relative_path=PurePosixPath("src/example.py"),
            kind=FileKind.PYTHON,
            source_hash=SOURCE_HASH,
            size_bytes=-1,
        )


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: SymbolRecord("", "package.symbol", "function", valid_location()),
        lambda: SymbolRecord("symbol-id", " ", "function", valid_location()),
        lambda: SymbolRecord("symbol-id", "package.symbol", "", valid_location()),
        lambda: ChunkRecord("", "source", valid_location(), None),
        lambda: ChunkRecord("chunk-id", " ", valid_location(), None),
        lambda: ChunkRecord("chunk-id", "source", valid_location(), " "),
    ],
)
def test_symbol_and_chunk_identifiers_must_be_nonblank(constructor: object) -> None:
    factory = cast(Callable[[], object], constructor)
    with pytest.raises(ValueError, match="blank"):
        factory()


def test_parsed_file_preserves_symbols_and_chunks() -> None:
    symbol = SymbolRecord("symbol-id", "package.symbol", "function", valid_location())
    chunk = ChunkRecord("chunk-id", "def symbol(): ...", valid_location(), symbol.symbol_id)

    parsed = ParsedFile(file=valid_file(), symbols=(symbol,), chunks=(chunk,))

    assert parsed.symbols == (symbol,)
    assert parsed.chunks == (chunk,)


@pytest.mark.parametrize(("query", "limit"), [("", 10), ("   ", 10), ("valid", 0)])
def test_search_request_rejects_blank_query_or_nonpositive_limit(query: str, limit: int) -> None:
    with pytest.raises(ValueError):
        SearchRequest(repository_id=REPOSITORY_ID, query=query, limit=limit)


@pytest.mark.parametrize("score", [math.inf, -math.inf, math.nan])
def test_search_hit_rejects_nonfinite_scores(score: float) -> None:
    with pytest.raises(ValueError, match="score"):
        SearchHit(location=valid_location(), score=score, signals=("lexical",))


def test_search_hit_rejects_blank_signal() -> None:
    with pytest.raises(ValueError, match="signal"):
        SearchHit(location=valid_location(), score=1.0, signals=(" ",))


@pytest.mark.parametrize(
    ("query", "estimated_tokens", "token_budget"),
    [("", 0, 1), ("query", -1, 1), ("query", 2, 1), ("query", 0, 0)],
)
def test_context_package_rejects_invalid_budget_state(
    query: str,
    estimated_tokens: int,
    token_budget: int,
) -> None:
    with pytest.raises(ValueError):
        ContextPackage(
            query=query,
            hits=(),
            estimated_tokens=estimated_tokens,
            token_budget=token_budget,
        )


class FakeScanner:
    def scan(self, repository: RepositoryRef) -> tuple[ScannedFile, ...]:
        del repository
        return ()


class FakeStore:
    def replace_inventory(
        self,
        repository: RepositoryRef,
        files: Sequence[ScannedFile],
    ) -> None:
        del repository, files


class FakeParser:
    def parse(self, file: ScannedFile, source: str) -> ParsedFile:
        del source
        return ParsedFile(file=file, symbols=(), chunks=())


class FakeEmbedder:
    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple((0.0,) for _ in texts)


class FakeRetriever:
    def search(self, request: SearchRequest) -> tuple[SearchHit, ...]:
        del request
        return ()


class FakeComposer:
    def compose(
        self,
        request: SearchRequest,
        hits: Sequence[SearchHit],
        token_budget: int,
    ) -> ContextPackage:
        return ContextPackage(
            request.query,
            tuple(hits),
            estimated_tokens=0,
            token_budget=token_budget,
        )


def test_ports_accept_structural_implementations() -> None:
    assert isinstance(FakeScanner(), RepositoryScanner)
    assert isinstance(FakeStore(), MetadataStore)
    assert isinstance(FakeParser(), SourceParser)
    assert isinstance(FakeEmbedder(), Embedder)
    assert isinstance(FakeRetriever(), Retriever)
    assert isinstance(FakeComposer(), ContextComposer)
