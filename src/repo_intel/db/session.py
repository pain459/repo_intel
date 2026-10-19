"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from repo_intel.config import get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None
_pool_report_task: asyncio.Task | None = None


def _build_engine() -> AsyncEngine:
    """Create the async engine from configuration."""
    settings = get_settings()
    url = settings.database_url
    logger.info("Creating database engine (%s)", url.split("://")[0])
    return create_async_engine(
        url,
        echo=(settings.log_level == "DEBUG"),
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )


def get_engine() -> AsyncEngine:
    """Return the (lazily created) async engine."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the (lazily created) async session factory."""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _async_session_factory


async def close_engine() -> None:
    """Dispose the engine (cleanup)."""
    global _engine, _pool_report_task
    if _pool_report_task is not None:
        _pool_report_task.cancel()
        try:
            await _pool_report_task
        except asyncio.CancelledError:
            pass
        _pool_report_task = None
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def _pool_metrics_loop() -> None:
    """Periodically publish DB pool statistics to Prometheus gauges."""
    from repo_intel.api.metrics import (
        DB_POOL_OVERFLOW,
        DB_POOL_SIZE,
        DB_POOL_USED,
    )

    engine = get_engine()
    pool = engine.pool

    try:
        while True:
            DB_POOL_SIZE.set(pool.size())
            DB_POOL_USED.set(pool.checkedout())
            DB_POOL_OVERFLOW.set(pool.overflow())
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        return


def start_pool_metrics() -> None:
    """Start the background pool metrics reporter."""
    global _pool_report_task
    if _pool_report_task is None:
        _pool_report_task = asyncio.create_task(_pool_metrics_loop())

