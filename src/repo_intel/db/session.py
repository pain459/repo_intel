"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

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
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
