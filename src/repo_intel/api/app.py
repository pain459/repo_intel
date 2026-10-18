"""FastAPI application factory with lifespan events."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from repo_intel.config import get_settings, setup_logging
from repo_intel.db import models
from repo_intel.db.session import close_engine, get_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan: set up and tear down the DB engine."""
    settings = get_settings()
    setup_logging()
    _ = get_engine()  # triggers lazy engine creation
    logger.info("Application starting (host=%s, port=%s)", settings.host, settings.port)
    yield
    await close_engine()
    logger.info("Application shutting down")


def create_app() -> FastAPI:
    """Build and return the FastAPI application instance."""
    app = FastAPI(
        title="repo_intel",
        description="Persistent, searchable knowledge of Git repositories for coding agents.",
        version=getattr(models.Base.metadata, "version", "0.1.0"),
        lifespan=lifespan,
    )

    # --- Register routers ---
    from repo_intel.api.health import health_router  # noqa: PLC0415

    app.include_router(health_router, prefix="/health", tags=["health"])

    return app


# --- uvicorn entry-point ---
app = create_app()
