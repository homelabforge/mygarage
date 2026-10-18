"""The daily telemetry prune refuses a retention below the LiveLink minimum (O-T1).

`prune_old_telemetry` deletes every raw reading and location point older than
`now - retention_days`. A stored 0 puts that cutoff at now and a negative one in
the future, so every row goes. Only the typed LiveLink API enforces 30 to 365;
a hand edit, an old database or a full-backup swap can still hold anything, so
the task itself skips the prune and warns rather than clamp.

Session plumbing mirrors test_check_firmware_updates.py: the job opens
`AsyncSessionLocal()` itself, so `app.tasks.livelink_tasks.AsyncSessionLocal` is
patched to hand back the fixture session. The two prune methods are replaced by
recorders: a real prune here would delete other modules' old rows from the
shared test database, and "was it called, with what" is the whole question.
"""

from __future__ import annotations

import logging

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.services.location_service import LocationService
from app.services.telemetry_service import TelemetryService
from app.tasks import livelink_tasks

pytestmark = pytest.mark.asyncio

_RETENTION_KEY = "livelink_telemetry_retention_days"


class _PassthroughSessionContext:
    """Hand back the already-open fixture session without closing it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


@pytest_asyncio.fixture
async def seed_retention(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, livelink_enabled, keep_rows
):
    """Store a retention and record each prune instead of running it."""
    calls: list[tuple[str, int]] = []

    async def telemetry_prune(self: TelemetryService, retention_days: int) -> int:
        calls.append(("telemetry", retention_days))
        return 0

    async def location_prune(self: LocationService, retention_days: int) -> int:
        calls.append(("location", retention_days))
        return 0

    monkeypatch.setattr(TelemetryService, "prune_old_telemetry", telemetry_prune)
    monkeypatch.setattr(LocationService, "prune_old", location_prune)
    monkeypatch.setattr(
        livelink_tasks, "AsyncSessionLocal", lambda: _PassthroughSessionContext(db_session)
    )
    await keep_rows(_RETENTION_KEY)

    async def seed(retention: str) -> list[tuple[str, int]]:
        await db_session.execute(delete(Setting).where(Setting.key == _RETENTION_KEY))
        db_session.add(Setting(key=_RETENTION_KEY, value=retention, category="livelink"))
        await db_session.commit()
        return calls

    return seed


@pytest.mark.parametrize("retention", ["0", "-5", "29"])
async def test_a_retention_below_30_days_prunes_nothing_and_warns(
    seed_retention, caplog: pytest.LogCaptureFixture, retention: str
) -> None:
    calls = await seed_retention(retention)

    with caplog.at_level(logging.WARNING, logger="app.tasks.livelink_tasks"):
        await livelink_tasks.prune_old_telemetry()

    assert calls == []
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(retention in message and "30" in message for message in warnings), warnings


@pytest.mark.parametrize("retention", ["30", "90", "400"])
async def test_a_retention_of_30_days_or_more_prunes_at_that_retention(
    seed_retention, retention: str
) -> None:
    """Control, passes on main too. Above 365 is honoured: it only keeps more."""
    calls = await seed_retention(retention)

    await livelink_tasks.prune_old_telemetry()

    assert calls == [("telemetry", int(retention)), ("location", int(retention))]
