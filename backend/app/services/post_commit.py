"""Work that runs once a transaction commits, off the request or message path.

A notification sent before the commit goes out even when the commit fails,
so the next retry sends it again (the new-device notice, carry 9). And a send
awaited inline holds up whatever's ingesting while a notification service is
slow (B6-1). So both are queued on the session here and run in a background
task after the commit, each in a session of its own. A rollback drops them.

The hooks are SQLAlchemy's own session events, so every commit path (MQTT,
HTTPS, the scheduler) gets this without calling anything.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

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


def after_commit(db: AsyncSession, job: Job, *, label: str) -> None:
    """Run ``job`` once ``db``'s current transaction commits.

    The job runs in its own session on the same engine, so it sees what the
    transaction wrote. It's dropped if the transaction rolls back. ``label``
    names it in the log when it fails.
    """
    engine = db.bind
    if not isinstance(engine, AsyncEngine):
        # Every session in the app is bound to one engine; this keeps pyright
        # honest about it, and a stray unbound session fails loudly here.
        raise TypeError("after_commit needs a session bound to an AsyncEngine")
    db.info.setdefault(_PENDING, []).append((job, engine, label))


async def drain() -> None:
    """Wait for every queued job to finish. For tests and shutdown."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


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
    # A savepoint's commit fires this too, and that isn't the real commit yet.
    if session.get_nested_transaction() is not None:
        return
    jobs = session.info.pop(_PENDING, None)
    if not jobs:
        return
    loop = asyncio.get_running_loop()
    for job, engine, label in jobs:
        task = loop.create_task(_run(job, engine, label))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


@event.listens_for(Session, "after_transaction_end")
def _drop_jobs(session: Session, transaction: SessionTransaction) -> None:
    # Runs after `_start_jobs` on a commit, which has already taken the jobs,
    # so anything left here belonged to a transaction that didn't commit.
    if transaction.parent is None and session.info.pop(_PENDING, None):
        logger.debug("Dropped post-commit jobs from a transaction that didn't commit")
