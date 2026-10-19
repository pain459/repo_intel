"""FastAPI application factory with lifespan events and MCP server."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from repo_intel.api.metrics import get_http_metrics_middleware
from repo_intel.compaction.manager import AutoCheckpointScheduler
from repo_intel.config import get_settings, setup_logging
from repo_intel.db import models
from repo_intel.db.session import close_engine, get_engine, start_pool_metrics

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global auto-checkpoint scheduler (started in lifespan)
# ---------------------------------------------------------------------------
_auto_scheduler: AutoCheckpointScheduler | None = None

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def db_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Set up and tear down the DB engine."""
    settings = get_settings()
    setup_logging()
    _ = get_engine()  # triggers lazy engine creation
    _auto_scheduler = AutoCheckpointScheduler()
    _auto_scheduler.start()
    start_pool_metrics()
    logger.info("Application starting (host=%s, port=%s)", settings.host, settings.port)
    try:
        yield
    finally:
        if _auto_scheduler is not None:
            _auto_scheduler.stop()
            logger.info("Auto-checkpoint scheduler stopped")
        await close_engine()
        logger.info("Application shutting down")


# ---------------------------------------------------------------------------
# App factory — mounts MCP server alongside REST endpoints
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Build and return the FastAPI application instance."""
    # --- Create the MCP ASGI app ---
    from repo_intel.mcp.fastmcp import get_mcp_app  # noqa: PLC0415

    mcp_app_instance = get_mcp_app()
    mcp_lifespan_cm = mcp_app_instance.lifespan(mcp_app_instance)

    @asynccontextmanager
    async def combined_lifespan(fastapi_app: FastAPI) -> AsyncGenerator[None, None]:
        """Run both DB and FastMCP lifespans."""
        db_cm = db_lifespan(fastapi_app)
        await mcp_lifespan_cm.__aenter__()
        await db_cm.__aenter__()
        try:
            yield
        finally:
            await db_cm.__aexit__(None, None, None)
            await mcp_lifespan_cm.__aexit__(None, None, None)

    app = FastAPI(
        title="repo_intel",
        description="Persistent, searchable knowledge of Git repositories for coding agents.",
        version=getattr(models.Base.metadata, "version", "0.1.0"),
        lifespan=combined_lifespan,
    )

    # --- HTTP metrics middleware (counts & measures every request) ---
    app.add_middleware(get_http_metrics_middleware())

    # --- Mount MCP server at /mcp (for OpenCode and MCP clients) ---
    app.mount("/mcp", mcp_app_instance)
    logger.info("MCP server mounted at /mcp")

    # --- Register REST routers ---
    from repo_intel.api.checkpoints import router as cp_router  # noqa: PLC0415
    from repo_intel.api.health import health_router  # noqa: PLC0415
    from repo_intel.api.mcp import router as mcp_router  # noqa: PLC0415
    from repo_intel.api.memory import router as memory_router  # noqa: PLC0415
    from repo_intel.api.repositories import router as repo_router  # noqa: PLC0415
    from repo_intel.api.search import router as search_router  # noqa: PLC0415

    app.include_router(health_router, prefix="/health", tags=["health"])
    app.include_router(repo_router)
    app.include_router(search_router)
    app.include_router(mcp_router)
    app.include_router(memory_router)
    app.include_router(cp_router)

    from repo_intel.api.metrics import router as metrics_router  # noqa: PLC0415
    app.include_router(metrics_router, tags=["metrics"])

    return app


# --- uvicorn entry-point ---
app = create_app()
