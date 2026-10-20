"""Hybrid retrieval types for search requests and responses."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

SearchMethod = Literal["exact", "lexical", "semantic", "symbol"]


@dataclass
class SearchResult:
    """One ranked hit returned by the hybrid search pipeline."""

    chunk_id: uuid.UUID
    path: str
    start_line: int
    end_line: int
    content_hash: str
    text: str
    estimated_tokens: int = 0
    retrieval_methods: list[SearchMethod] = field(default_factory=list)
    score: float = 0.0
    relevance_reason: str = ""
    # Index freshness metadata
    generation_created_at: str = ""
    is_stale: bool = False
    # Whether the chunk content was truncated to fit the token budget
    is_truncated: bool = False
    # Internal: generation ID for freshness lookup (not serialized to API)
    generation_id: str = ""


@dataclass
class SearchRequest:
    """Parameters for a hybrid search query."""

    query: str
    # Optional repository ID; None means search all registered repos
    repository_id: str | None = None
    # Maximum number of results to return
    limit: int = 10
    # Token budget for the combined response
    token_budget: int = 12_000
    # Minimum score threshold (0.0-1.0)
    min_score: float = 0.0
    # Whether to include full chunk content
    include_content: bool = True
