"""Prometheus metrics endpoint and HTTP middleware for observability."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP request metrics
# ---------------------------------------------------------------------------

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_class"],
)

HTTP_LATENCY = Histogram(
    "http_request_latency_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

HTTP_ACTIVE = Gauge(
    "http_requests_active",
    "Currently in-flight HTTP requests",
    ["method", "endpoint"],
)

# ---------------------------------------------------------------------------
# Search-specific metrics
# ---------------------------------------------------------------------------

SEARCH_REQUESTS = Counter(
    "repo_intel_search_requests_total",
    "Total search requests served",
    ["source"],  # "rest" or "mcp"
)

SEARCH_LATENCY = Histogram(
    "repo_intel_search_latency_seconds",
    "Search query latency (seconds)",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

SEARCH_RESULTS = Histogram(
    "repo_intel_search_results_count",
    "Number of results returned per search",
    buckets=(0, 1, 2, 5, 10, 15, 20, 30, 50, 100),
)

SEARCH_STALE_RESULTS = Counter(
    "repo_intel_search_stale_results_total",
    "Stale search results (index > 1 hour old)",
)

# ---------------------------------------------------------------------------
# MCP tool call metrics
# ---------------------------------------------------------------------------

MCP_TOOL_CALLS = Counter(
    "mcp_tool_calls_total",
    "Total MCP tool calls",
    ["tool_name", "status"],  # status: "success" or "error"
)

MCP_TOOL_LATENCY = Histogram(
    "mcp_tool_call_latency_seconds",
    "MCP tool call latency (seconds)",
    ["tool_name"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ---------------------------------------------------------------------------
# Indexing metrics
# ---------------------------------------------------------------------------

INDEX_CHUNKS = Counter(
    "repo_intel_index_chunks_total",
    "Total chunks indexed",
    ["chunk_type"],
)

INDEX_BYTES = Counter(
    "repo_intel_index_bytes_total",
    "Total bytes indexed",
)

# ---------------------------------------------------------------------------
# Connection pool metrics
# ---------------------------------------------------------------------------

DB_POOL_SIZE = Gauge(
    "repo_intel_db_pool_size",
    "Database connection pool configured size",
)

DB_POOL_USED = Gauge(
    "repo_intel_db_pool_used",
    "Database connection pool used connections",
)

DB_POOL_OVERFLOW = Gauge(
    "repo_intel_db_pool_overflow",
    "Database connection pool overflow connections",
)

# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    """Prometheus-compatible metrics endpoint."""
    return Response(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )

# ---------------------------------------------------------------------------
# Middleware factory
# ---------------------------------------------------------------------------


def get_http_metrics_middleware():
    """Return a Starlette middleware class that tracks HTTP request metrics.

    Skips /metrics and /health* endpoints to avoid self-referential noise.
    """
    from starlette.middleware.base import BaseHTTPMiddleware  # noqa: PLC0415
    from starlette.requests import Request as StarletteRequest  # noqa: PLC0415
    from starlette.responses import Response as StarletteResponse  # noqa: PLC0415

    class HttpMetricsMiddleware(BaseHTTPMiddleware):
        async def dispatch(
            self, request: StarletteRequest, call_next
        ) -> StarletteResponse:
            endpoint = request.url.path
            method = request.method

            # Skip metrics and health endpoints to avoid polluting the data
            if endpoint.startswith(("/metrics", "/health")):
                return await call_next(request)

            HTTP_ACTIVE.labels(method=method, endpoint=endpoint).inc()
            try:
                t0 = time.monotonic()
                response = await call_next(request)
                elapsed = time.monotonic() - t0
                status_class = f"{response.status_code // 100}xx"

                HTTP_REQUESTS.labels(
                    method=method,
                    endpoint=endpoint,
                    status_class=status_class,
                ).inc()
                HTTP_LATENCY.labels(method=method, endpoint=endpoint).observe(elapsed)
                return response
            finally:
                HTTP_ACTIVE.labels(method=method, endpoint=endpoint).dec()

    return HttpMetricsMiddleware
