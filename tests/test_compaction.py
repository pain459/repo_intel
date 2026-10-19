"""Tests for the compaction continuity manager."""

from __future__ import annotations

import asyncio
import warnings

import pytest

from repo_intel.compaction.manager import (
    AutoCheckpointScheduler,
    session_bootstrap,
)
from repo_intel.db.models import TaskCheckpoint
from repo_intel.db.session import get_session_factory

# ---------------------------------------------------------------------------
# AutoCheckpointScheduler lifecycle
# ---------------------------------------------------------------------------


class TestSchedulerLifecycle:
    def test_start_stop(self) -> None:
        s = AutoCheckpointScheduler(interval_s=9999)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            s.start()
            assert s._running is True
            s.stop()
        assert s._running is False
        # Clean up the orphaned task
        if s._task is not None:
            s._task.cancel()
            asyncio.get_event_loop().run_until_complete(s._task)

    def test_start_idempotent(self) -> None:
        s = AutoCheckpointScheduler(interval_s=9999)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            s.start()
            s.start()
        assert s._running is True
        s.stop()
        if s._task is not None:
            s._task.cancel()
            asyncio.get_event_loop().run_until_complete(s._task)


# ---------------------------------------------------------------------------
# Session bootstrap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_returns_structure() -> None:
    data = await session_bootstrap()
    assert "checkpoint" in data
    assert "verified_memories" in data
    assert isinstance(data["verified_memories"], list)


@pytest.mark.asyncio
async def test_bootstrap_with_session_id() -> None:
    factory = get_session_factory()
    async with factory() as session:
        cp = TaskCheckpoint(
            session_id="bootstrap-test-session",
            objective="test objective",
            current_state="in progress",
            pending_steps=["step 1"],
        )
        session.add(cp)
        await session.commit()
        cp_id = cp.id

    data = await session_bootstrap(session_id="bootstrap-test-session")
    assert data["checkpoint"] is not None
    assert data["checkpoint"]["id"] == str(cp_id)
    assert data["checkpoint"]["objective"] == "test objective"

    # Cleanup
    async with factory() as session:
        to_delete = await session.get(TaskCheckpoint, cp_id)
        if to_delete:
            await session.delete(to_delete)
            await session.commit()


@pytest.mark.asyncio
async def test_bootstrap_returns_none_for_unknown_session() -> None:
    data = await session_bootstrap(session_id="nonexistent-session-id")
    assert data["checkpoint"] is None
    assert data["session_id"] == "nonexistent-session-id"
