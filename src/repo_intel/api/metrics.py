"""Prometheus metrics endpoint for observability."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])

# ---------------------------------------------------------------------------
# Counters and histograms
# ---------------------------------------------------------------------------

SEARCH_REQUESTS = Counter(
    "repo_intel_search_requests_total",
    "Total search requests served",
    ["method"],
)

SEARCH_LATENCY = Histogram(
    "repo_intel_search_latency_seconds",
    "Search query latency (seconds)",
)

INDEX_CHUNKS = Counter(
    "repo_intel_index_chunks_total",
    "Total chunks indexed",
    ["chunk_type"],
)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    """Prometheus-compatible metrics endpoint."""
    return Response(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )
