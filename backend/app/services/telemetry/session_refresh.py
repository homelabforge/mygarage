"""Debounced refresh of a closed drive session's aggregates, behind the commit."""

import asyncio
import logging
import time
import weakref
from dataclasses import dataclass
from functools import partial

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.models.drive_session import DriveSession
from app.services.post_commit import after_commit

logger = logging.getLogger(__name__)

#: A closed session a replay keeps landing in isn't recomputed per frame. The
#: refresh runs behind the commit, this long after the last frame that asked
#: for it, and no later than this long after the first (B6-12, D-7). The test
#: suite sets both to 0.
SESSION_REFRESH_DEBOUNCE_SECONDS = 2.0
SESSION_REFRESH_MAX_DELAY_SECONDS = 30.0


@dataclass
class _RefreshDue:
    first: float
    deadline: float


#: Session id -> the refresh job already waiting on it. Written by the JOB when
#: it starts, never when it's queued, so a transaction that rolls back after
#: queueing leaves nothing behind to suppress the next one (E-3).
_REFRESH_DUE: dict[int, _RefreshDue] = {}

#: Session id -> the lock its refreshes take, read through commit. Two side by
#: side let the older one, stuck on SQLite's write lock, commit last and put
#: back figures from a narrower window. Weak, so a lock goes when its jobs do.
_REFRESH_LOCKS: weakref.WeakValueDictionary[int, asyncio.Lock] = weakref.WeakValueDictionary()


def queue_session_refresh(db: AsyncSession, session_id: int) -> None:
    """Recompute a closed session's aggregates once ``db`` commits, debounced per session."""
    after_commit(
        db, partial(_refresh_session_debounced, session_id), label=f"refresh-session:{session_id}"
    )


async def _refresh_session_debounced(session_id: int, db: AsyncSession) -> None:
    """The queued job: the first one for a session waits out the debounce, the rest push it."""
    now = time.monotonic()
    due = _REFRESH_DUE.get(session_id)
    if due is not None:
        # Another job is already waiting: push its deadline and go.
        due.deadline = min(
            now + SESSION_REFRESH_DEBOUNCE_SECONDS, due.first + SESSION_REFRESH_MAX_DELAY_SECONDS
        )
        return
    due = _RefreshDue(first=now, deadline=now + SESSION_REFRESH_DEBOUNCE_SECONDS)
    _REFRESH_DUE[session_id] = due
    lock = _REFRESH_LOCKS.get(session_id)
    if lock is None:
        lock = _REFRESH_LOCKS[session_id] = asyncio.Lock()
    try:
        while (remaining := due.deadline - time.monotonic()) > 0:
            await asyncio.sleep(remaining)
        # Still registered while it waits, so a frame landing meanwhile folds
        # into this run: it reads after the lock, which is after that commit.
        await lock.acquire()
    except asyncio.CancelledError:
        # Shutdown mid-sleep or mid-wait on the lock (`post_commit.shutdown`):
        # refresh once now rather than lose the drain's last seconds to a
        # restart (E-12). No lock here, but ingest has stopped, so nothing can
        # widen the window under it. The runner won't commit after a
        # cancellation, so commit here.
        _REFRESH_DUE.pop(session_id, None)
        await _refresh_session_now(db, session_id)
        await db.commit()
        raise
    try:
        _REFRESH_DUE.pop(session_id, None)
        await _refresh_session_now(db, session_id)
        # Committed under the lock, or the next one could read before this lands.
        await db.commit()
    finally:
        lock.release()


async def _refresh_session_now(db: AsyncSession, session_id: int) -> None:
    """Recompute one closed session, if it's still there and still closed."""
    from app.services.session_service import SessionService  # local import avoids cycle

    session = await db.get(DriveSession, session_id)
    if session is None or session.ended_at is None:
        return  # merged away, or reopened: nothing to recompute
    await SessionService(db).refresh_aggregates(session)
    try:
        await db.flush()
    except StaleDataError:
        # A merge deleted the row while this was recomputing it. Nothing to
        # write, and not an error worth a traceback (M5).
        await db.rollback()
        logger.debug("Session %d went away mid-refresh; skipped", session_id)
