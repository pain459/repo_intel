"""Health-check endpoints: live and ready."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from repo_intel.config import get_settings
from repo_intel.db.session import get_session_factory

logger = logging.getLogger(__name__)

health_router = APIRouter()


@health_router.get("/live", status_code=status.HTTP_200_OK)
async def health_live() -> dict[str, str]:
    """Liveness probe — process is alive and serving."""
    return {"status": "ok"}


@health_router.get("/ready", status_code=status.HTTP_200_OK)
async def health_ready() -> dict:
    """Readiness probe — database reachable, Ollama reachable (if configured)."""
    details: dict = {"status": "ok"}
    is_ready = True

    # --- Check database ---
    db_ok = await _check_database()
    details["database"] = "ok" if db_ok else "unreachable"
    if not db_ok:
        is_ready = False

    # --- Check Ollama ---
    ollama_ok = await _check_ollama()
    details["ollama"] = "ok" if ollama_ok else "unreachable"
    if not ollama_ok:
        is_ready = False

    response_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    logger.info("Readiness check: %s", details)
    return JSONResponse(
        content={"status": "ok" if is_ready else "not_ready", **details},
        status_code=response_code,
    )


async def _check_database() -> bool:
    """Return True if the database accepts connections and the schema exists."""
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Database readiness check failed: %s", str(exc))
        return False


async def _check_ollama() -> bool:
    """Return True if the Ollama /api/tags endpoint returns 200."""
    settings = get_settings()
    try:
        url = f"{settings.ollama_base_url}/api/tags"
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
            resp = await client.get(url)
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("Ollama readiness check failed: %s", str(exc))
        return False
