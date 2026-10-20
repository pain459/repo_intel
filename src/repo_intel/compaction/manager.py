"""Compaction continuity manager.

Provides auto-checkpoint scheduling, stale-checkpoint invalidation,
and session resume bootstrap so that a long-running task can survive
context compaction and resume with verified state.

The plan warns that OpenCode lifecycle hooks are unreliable and version
dependent, so this module deliberately works *without* them.  Agents
invoke ``compaction_checkpoint_save`` before compaction and
``session_bootstrap`` after; the worker periodically auto-saves as a
safety net.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from repo_intel.db import models
from repo_intel.db.session import get_session_factory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------
DEFAULT_AUTO_CHECKPOINT_INTERVAL_S = 900  # 15 min
DEFAULT_CHECKPOINT_STALE_THRESHOLD_H = 4

# ---------------------------------------------------------------------------
# Auto-checkpoint scheduler
# ---------------------------------------------------------------------------


class AutoCheckpointScheduler:
    """Periodically marks old checkpoints stale as a safety net."""

    def __init__(
        self,
        interval_s: int | None = None,
        stale_threshold_h: int | None = None,
    ) -> None:
        self.interval_s = interval_s or DEFAULT_AUTO_CHECKPOINT_INTERVAL_S
        self.stale_threshold_h = (
            stale_threshold_h or DEFAULT_CHECKPOINT_STALE_THRESHOLD_H
        )
        self._task: asyncio.Task | None = None
        self._running = False

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Start the background auto-checkpoint loop (fire-and-forget)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._loop())

    def stop(self) -> None:
        """Cancel the background loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    # -- internals ----------------------------------------------------------

    async def _loop(self) -> None:
        factory = get_session_factory()
        while self._running:
            try:
                await self._tick(factory)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("auto-checkpoint tick failed")
            try:
                await asyncio.sleep(self.interval_s)
            except asyncio.CancelledError:
                break

    async def _tick(self, factory) -> None:
        """One cycle: mark checkpoints older than the stale threshold."""
        stale_after = datetime.utcnow() - timedelta(
            hours=self.stale_threshold_h,
        )
        async with factory() as session:
            stmt = (
                select(models.TaskCheckpoint)
                .where(models.TaskCheckpoint.created_at < stale_after)
                .limit(50)
            )
            checkpoints = list(await session.scalars(stmt))
            for cp in checkpoints:
                await self._mark_stale(session, cp)

    async def _mark_stale(
        self,
        session,
        cp: models.TaskCheckpoint,
    ) -> None:
        """Tag checkpoint as stale in its evidence dict."""
        evidence = cp.evidence or {}
        compaction_info = evidence.setdefault("compaction", {})
        if "marked_stale_at" in compaction_info:
            return  # already marked
        compaction_info["marked_stale_at"] = datetime.utcnow().isoformat()
        cp.evidence = evidence
        await session.commit()
        logger.info(
            "Auto-compaction: checkpoint %s (%s) marked stale",
            cp.id,
            cp.session_id,
        )


# ---------------------------------------------------------------------------
# Session bootstrap
# ---------------------------------------------------------------------------


async def session_bootstrap(
    session_id: str | None = None,
    repository_id: str | None = None,
) -> dict:
    """Return the most recent checkpoint and verified memories for resume."""
    factory = get_session_factory()
    async with factory() as session:
        # Latest checkpoint
        cp_stmt = (
            select(models.TaskCheckpoint)
            .order_by(models.TaskCheckpoint.created_at.desc())
            .limit(1)
        )
        if session_id:
            cp_stmt = cp_stmt.where(
                models.TaskCheckpoint.session_id == session_id,
            )
        if repository_id:
            cp_stmt = cp_stmt.where(
                models.TaskCheckpoint.repository_id == repository_id,
            )
        cp = (await session.scalars(cp_stmt)).first()

        # Check if the checkpoint has been marked stale
        checkpoint_data = None
        is_stale = False
        if cp:
            evidence = cp.evidence or {}
            compaction_info = evidence.get("compaction", {})
            is_stale = "marked_stale_at" in compaction_info
            checkpoint_data = _checkpoint_to_dict(cp)
            if is_stale:
                checkpoint_data["stale"] = True
                checkpoint_data["marked_stale_at"] = compaction_info[
                    "marked_stale_at"
                ]

        # Recent verified memories
        mem_stmt = (
            select(models.Memory)
            .where(models.Memory.status == "verified")
            .order_by(models.Memory.created_at.desc())
            .limit(20)
        )
        if repository_id:
            mem_stmt = mem_stmt.where(
                models.Memory.repository_id == repository_id,
            )
        memories = list(await session.scalars(mem_stmt))

    return {
        "checkpoint": checkpoint_data,
        "verified_memories": [
            {
                "id": str(m.id),
                "kind": m.kind,
                "statement": m.statement,
                "created_at": str(m.created_at),
            }
            for m in memories
        ],
        "session_id": session_id,
        "repository_id": repository_id,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _checkpoint_to_dict(cp: models.TaskCheckpoint) -> dict:
    return {
        "id": str(cp.id),
        "session_id": cp.session_id,
        "repository_id": (
            str(cp.repository_id) if cp.repository_id else None
        ),
        "objective": cp.objective,
        "current_state": cp.current_state,
        "changed_files": cp.changed_files,
        "pending_steps": cp.pending_steps,
        "evidence": cp.evidence,
        "created_at": str(cp.created_at),
    }
