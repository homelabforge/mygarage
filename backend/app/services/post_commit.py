"""Work that runs once a transaction commits, off the request or message path.

A notification sent before the commit goes out even when the commit fails,
so the next retry sends it again (the new-device notice, carry 9). And a send
awaited inline holds up whatever's ingesting while a notification service is
slow (B6-1). So both are queued on the session here and run in a background
task after the commit, each in a session of its own. A rollback drops them,
a savepoint's rollback included: a job belongs to the transaction it was
queued in, and a released savepoint hands its jobs to the one around it.

The hooks are SQLAlchemy's own session events, so every commit path (MQTT,
HTTPS, the scheduler) gets this without calling anything. Shutdown waits for
what's still running (`shutdown`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

#: A job gets a session of its own; the one that queued it may be closed by then.
Job = Callable[[AsyncSession], Awaitable[object]]

_PENDING = "post_commit_jobs"

#: Strong references, so a running job isn't garbage collected (same as the SD
#: backfill tasks in livelink_service).
_tasks: set[asyncio.Task[None]] = set()


@dataclass
class _Queued:
    job: Job
    engine: AsyncEngine
    label: str
    #: The savepoint it was queued in, or None for the root transaction.
    owner: SessionTransaction | None


def after_commit(db: AsyncSession, job: Job, *, label: str) -> None:
    """Run ``job`` once ``db``'s current transaction commits.

    The job runs in its own session on the same engine, so it sees what the
    transaction wrote. It's dropped if the transaction it was queued in rolls
    back, a savepoint included. ``label`` names it in the log when it fails.
    """
    engine = db.bind
    if not isinstance(engine, AsyncEngine):
        # Every session in the app is bound to one engine; this keeps pyright
        # honest about it, and a stray unbound session fails loudly here.
        raise TypeError("after_commit needs a session bound to an AsyncEngine")
    owner = db.sync_session.get_nested_transaction()
    db.info.setdefault(_PENDING, []).append(_Queued(job, engine, label, owner))


async def drain() -> None:
    """Wait for every queued job to finish. For tests."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
        # A finished job leaves the set from its done callback, which needs a
        # turn of the loop. A gather of finished tasks doesn't give it one, so
        # without this the loop spun forever on a job that had just finished.
        await asyncio.sleep(0)


async def shutdown(timeout: float) -> None:
    """Give the running jobs ``timeout`` seconds, then cancel what's left.

    Called from the app's shutdown after ingest has stopped, so nothing new
    lands behind it. Left to the loop, a job was destroyed mid-send. One that's
    cancelled is named in the log; an alert's hold was committed with its
    reading, so it's tried again one cooldown later.
    """
    if not _tasks:
        return
    _done, late = await asyncio.wait(list(_tasks), timeout=timeout)
    if not late:
        return
    logger.warning(
        "Cancelled %d post-commit job(s) still running at shutdown: %s",
        len(late),
        ", ".join(sorted(sanitize_for_log(task.get_name()) for task in late)),
    )
    for task in late:
        task.cancel()
    await asyncio.gather(*late, return_exceptions=True)


async def _run(job: Job, engine: AsyncEngine, label: str) -> None:
    async with AsyncSession(engine, expire_on_commit=False, autoflush=False) as db:
        try:
            await job(db)
            await db.commit()
        except Exception:  # noqa: BLE001 - a background job has nobody to raise to
            await db.rollback()
            logger.exception("Post-commit job failed: %s", sanitize_for_log(label))


@event.listens_for(Session, "after_commit")
def _start_jobs(session: Session) -> None:
    released = session.get_nested_transaction()
    if released is not None:
        # A savepoint's release: its jobs now ride on the transaction around
        # it, and still wait for the real commit.
        parent = released.parent if released.parent is not None and released.parent.nested else None
        for queued in session.info.get(_PENDING, []):
            if queued.owner is released:
                queued.owner = parent
        return
    jobs: list[_Queued] = session.info.pop(_PENDING, [])
    if not jobs:
        return
    loop = asyncio.get_running_loop()
    for queued in jobs:
        task = loop.create_task(_run(queued.job, queued.engine, queued.label), name=queued.label)
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


@event.listens_for(Session, "after_transaction_end")
def _drop_jobs(session: Session, transaction: SessionTransaction) -> None:
    # Runs after `_start_jobs` on a commit, which has already taken (or, for a
    # savepoint, handed on) the jobs, so anything still owned here belonged to
    # a transaction that didn't commit.
    pending: list[_Queued] = session.info.get(_PENDING, [])
    if not pending:
        return
    if transaction.parent is None:
        session.info.pop(_PENDING, None)
        logger.debug("Dropped post-commit jobs from a transaction that didn't commit")
    elif transaction.nested:
        kept = [queued for queued in pending if queued.owner is not transaction]
        if len(kept) < len(pending):
            session.info[_PENDING] = kept
            logger.debug("Dropped post-commit jobs from a savepoint that rolled back")
