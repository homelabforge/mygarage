"""The post-commit queue: savepoints and shutdown (wave B review M-2, M-3)."""

from __future__ import annotations

import asyncio
import logging

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import post_commit
from app.services.post_commit import after_commit, drain

pytestmark = pytest.mark.asyncio


async def test_a_job_queued_in_a_rolled_back_savepoint_never_runs(db_session: AsyncSession):
    """M-3: only a root rollback dropped jobs, so one queued inside a savepoint
    that rolled back still ran when the outer transaction committed. Red on
    f3a8b81c (it ran)."""
    ran: list[str] = []

    async def outer(_own: AsyncSession) -> None:
        ran.append("outer")

    async def inner(_own: AsyncSession) -> None:
        ran.append("inner")

    after_commit(db_session, outer, label="outer")
    with pytest.raises(RuntimeError):
        async with db_session.begin_nested():
            after_commit(db_session, inner, label="inner")
            raise RuntimeError("the savepoint fails")
    await db_session.commit()
    await drain()

    assert ran == ["outer"]


async def test_a_job_queued_in_a_released_savepoint_runs_after_the_root_commit(
    db_session: AsyncSession,
):
    """Regression guard: a savepoint that's released hands its jobs to the
    transaction around it, and they still wait for the real commit. Kills
    dropping a savepoint's jobs however it ends."""
    ran: list[str] = []

    async def inner(_own: AsyncSession) -> None:
        ran.append("inner")

    async with db_session.begin_nested():
        after_commit(db_session, inner, label="inner")
    await asyncio.sleep(0)
    assert ran == []

    await db_session.commit()
    await drain()

    assert ran == ["inner"]


async def test_shutdown_waits_for_a_job_that_finishes(db_session: AsyncSession):
    """M-2: a notice sent just before shutdown gets to finish."""
    ran: list[str] = []

    async def quick(_own: AsyncSession) -> None:
        await asyncio.sleep(0.01)
        ran.append("sent")

    after_commit(db_session, quick, label="quick")
    await db_session.commit()

    await post_commit.shutdown(timeout=2)

    assert ran == ["sent"]


async def test_shutdown_cancels_a_job_that_outlives_its_budget(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
):
    """M-2: one stuck on a dead notification service is cancelled and named,
    instead of being destroyed with the loop."""
    started = asyncio.Event()

    async def stuck(_own: AsyncSession) -> None:
        started.set()
        await asyncio.Event().wait()

    after_commit(db_session, stuck, label="stuck alert")
    await db_session.commit()
    await asyncio.wait_for(started.wait(), timeout=2)

    try:
        with caplog.at_level(logging.WARNING, logger="app.services.post_commit"):
            await post_commit.shutdown(timeout=0.05)

        assert not post_commit._tasks
        assert any("stuck alert" in r.getMessage() for r in caplog.records)
    finally:
        # Whatever happened above, the stuck job mustn't outlive the test:
        # the suite's drain would wait on it for ever.
        for task in list(post_commit._tasks):
            task.cancel()
        await asyncio.gather(*list(post_commit._tasks), return_exceptions=True)
