"""The post-commit queue: savepoints and shutdown (wave B review M-2, M-3)."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

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


#: A job that has finished but whose done callback hasn't run yet is still in
#: the set. Run in a child process, because the bug spins without yielding and
#: nothing in-process can time it out.
_DRAIN_PROBE = """
import asyncio
from app.services import post_commit

async def main():
    async def job():
        return None
    task = asyncio.get_running_loop().create_task(job())
    post_commit._tasks.add(task)
    task.add_done_callback(post_commit._tasks.discard)
    await asyncio.sleep(0)
    assert task.done() and task in post_commit._tasks, "probe setup"
    await post_commit.drain()
    print("drained")

asyncio.run(main())
"""


async def test_drain_returns_when_a_finished_job_is_still_in_the_set() -> None:
    """A gather of finished tasks doesn't yield to the loop, so their done
    callbacks never got to take them out of the set and drain spun forever.
    The PG sidecar hung on it about one run in four. Red on f2fe0f85 (timed out)."""
    backend = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            [sys.executable, "-c", _DRAIN_PROBE],
            cwd=backend,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("drain() never returned with a finished job still in the set")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "drained"
