"""Daily telemetry summaries are household days, stored as dates.

The 01:00 job used to cut days at UTC midnight, so a New York evening drive
landed on the next day's summary. A day is now the household's: its UTC window
starts at local midnight, so a DST day runs 23 or 25 hours, and a reading at
exactly local midnight belongs to the new day only.

The zone in every case is America/New_York. 2026-03-08 is the spring-forward
Sunday (EST UTC-5 until 07:00 UTC, EDT UTC-4 after) and 2026-11-01 the fall-back
one (EDT until 06:00 UTC, EST after).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.settings import Setting
from app.models.vehicle_telemetry import TelemetryDailySummary, VehicleTelemetry
from app.services.telemetry_service import TelemetryService
from app.tasks import livelink_tasks
from app.utils import household_time
from app.utils.household_time import household_day_utc_bounds

pytestmark = pytest.mark.asyncio

NEW_YORK = ZoneInfo("America/New_York")
# The readiness guard's per-process cache, reset by path so a move only touches this line.
GUARD_FLAG = "app.services.telemetry_service._summary_date_ready"


class _PassthroughSessionContext:
    """Hand back the already-open fixture session without closing it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


@pytest.fixture
def new_york() -> None:
    household_time.household_zone_var.set(NEW_YORK)


@pytest_asyncio.fixture
async def vehicle(db_session: AsyncSession, make_livelink_vehicle) -> AsyncGenerator[tuple]:
    """A vehicle and device of our own; its readings and summaries go afterwards."""
    # The suite never drops these, so each test needs its own.
    vin, device = await make_livelink_vehicle("dsum", uuid4().hex[:6])
    await db_session.commit()
    yield vin, device.device_id
    await db_session.rollback()
    await db_session.execute(delete(TelemetryDailySummary).where(TelemetryDailySummary.vin == vin))
    await db_session.execute(delete(VehicleTelemetry).where(VehicleTelemetry.vin == vin))
    await db_session.commit()


async def _readings(
    db: AsyncSession, vin: str, device_id: str, key: str, rows: list[tuple[datetime, float]]
) -> None:
    for at, value in rows:
        db.add(
            VehicleTelemetry(vin=vin, device_id=device_id, param_key=key, value=value, timestamp=at)
        )
    await db.commit()


async def _summaries(db: AsyncSession, vin: str, key: str) -> dict[date, tuple]:
    rows = (
        await db.execute(
            select(
                TelemetryDailySummary.date,
                TelemetryDailySummary.min_value,
                TelemetryDailySummary.max_value,
                TelemetryDailySummary.avg_value,
                TelemetryDailySummary.sample_count,
            ).where(TelemetryDailySummary.vin == vin, TelemetryDailySummary.param_key == key)
        )
    ).all()
    return {r[0]: (r[1], r[2], r[3], r[4]) for r in rows}


async def _row_count(db: AsyncSession, vin: str) -> int | None:
    return await db.scalar(
        select(func.count())
        .select_from(TelemetryDailySummary)
        .where(TelemetryDailySummary.vin == vin)
    )


async def test_day_bounds_follow_the_household_clock(new_york) -> None:
    # Spring forward: local midnight is still EST, the next one is EDT, so 23 hours.
    assert household_day_utc_bounds(date(2026, 3, 8)) == (
        datetime(2026, 3, 8, 5, 0),
        datetime(2026, 3, 9, 4, 0),
    )
    # A plain EDT day.
    assert household_day_utc_bounds(date(2026, 3, 10)) == (
        datetime(2026, 3, 10, 4, 0),
        datetime(2026, 3, 11, 4, 0),
    )
    # Fall back: EDT midnight to EST midnight, 25 hours.
    assert household_day_utc_bounds(date(2026, 11, 1)) == (
        datetime(2026, 11, 1, 4, 0),
        datetime(2026, 11, 2, 5, 0),
    )


async def test_readings_land_on_their_household_day(
    db_session: AsyncSession, vehicle, new_york
) -> None:
    vin, device_id = vehicle
    # 03:30 UTC is 23:30 on the 9th in New York, 04:30 UTC is 00:30 on the 10th.
    await _readings(
        db_session,
        vin,
        device_id,
        "DSUM_SPLIT",
        [(datetime(2026, 3, 10, 3, 30), 1.0), (datetime(2026, 3, 10, 4, 30), 2.0)],
    )
    svc = TelemetryService(db_session)

    await svc.generate_daily_summary(date(2026, 3, 9), vin=vin)
    await svc.generate_daily_summary(date(2026, 3, 10), vin=vin)

    assert await _summaries(db_session, vin, "DSUM_SPLIT") == {
        date(2026, 3, 9): (1.0, 1.0, 1.0, 1),
        date(2026, 3, 10): (2.0, 2.0, 2.0, 1),
    }


async def test_a_reading_at_household_midnight_counts_on_the_new_day_only(
    db_session: AsyncSession, vehicle, new_york
) -> None:
    vin, device_id = vehicle
    # 04:00 UTC on the 10th is exactly midnight in New York (EDT by then).
    await _readings(db_session, vin, device_id, "DSUM_MIDNIGHT", [(datetime(2026, 3, 10, 4), 5.0)])
    svc = TelemetryService(db_session)

    assert await svc.generate_daily_summary(date(2026, 3, 9), vin=vin) == 0
    assert await svc.generate_daily_summary(date(2026, 3, 10), vin=vin) == 1

    assert await _summaries(db_session, vin, "DSUM_MIDNIGHT") == {
        date(2026, 3, 10): (5.0, 5.0, 5.0, 1),
    }


async def test_the_spring_forward_day_covers_its_23_hours(
    db_session: AsyncSession, vehicle, new_york
) -> None:
    vin, device_id = vehicle
    await _readings(
        db_session,
        vin,
        device_id,
        "DSUM_SPRING",
        [
            (datetime(2026, 3, 8, 4, 59, 59), 100.0),  # 23:59:59 on the 7th
            (datetime(2026, 3, 8, 6, 59), 1.0),  # 01:59 EST, just before the gap
            (datetime(2026, 3, 8, 7, 0), 3.0),  # 03:00 EDT, just after it
            (datetime(2026, 3, 9, 3, 59, 59), 5.0),  # 23:59:59 EDT, last second of the 8th
            (datetime(2026, 3, 9, 4, 0), 200.0),  # midnight on the 9th
        ],
    )

    await TelemetryService(db_session).generate_daily_summary(date(2026, 3, 8), vin=vin)

    assert await _summaries(db_session, vin, "DSUM_SPRING") == {
        date(2026, 3, 8): (1.0, 5.0, 3.0, 3),
    }


async def test_the_fall_back_day_covers_its_25_hours(
    db_session: AsyncSession, vehicle, new_york
) -> None:
    vin, device_id = vehicle
    await _readings(
        db_session,
        vin,
        device_id,
        "DSUM_FALL",
        [
            (datetime(2026, 11, 1, 3, 59, 59), 100.0),  # 23:59:59 on Oct 31
            (datetime(2026, 11, 1, 5, 30), 1.0),  # the first 01:30 (EDT)
            (datetime(2026, 11, 1, 6, 30), 2.0),  # the repeated 01:30 (EST)
            (datetime(2026, 11, 2, 4, 59), 6.0),  # 23:59 EST, a 24-hour day would drop it
            (datetime(2026, 11, 2, 5, 0), 200.0),  # midnight on the 2nd
        ],
    )

    await TelemetryService(db_session).generate_daily_summary(date(2026, 11, 1), vin=vin)

    assert await _summaries(db_session, vin, "DSUM_FALL") == {
        date(2026, 11, 1): (1.0, 6.0, 3.0, 3),
    }


async def test_rerunning_a_day_updates_the_one_row(
    db_session: AsyncSession, vehicle, new_york
) -> None:
    vin, device_id = vehicle
    await _readings(db_session, vin, device_id, "DSUM_RERUN", [(datetime(2026, 3, 10, 12), 4.0)])
    svc = TelemetryService(db_session)
    await svc.generate_daily_summary(date(2026, 3, 10), vin=vin)
    # A late reading shows up, then the day runs again.
    await _readings(db_session, vin, device_id, "DSUM_RERUN", [(datetime(2026, 3, 10, 13), 8.0)])

    await svc.generate_daily_summary(date(2026, 3, 10), vin=vin)

    assert await _summaries(db_session, vin, "DSUM_RERUN") == {
        date(2026, 3, 10): (4.0, 8.0, 6.0, 2),
    }
    assert await _row_count(db_session, vin) == 1


@pytest_asyncio.fixture
async def job_settings(
    db_session: AsyncSession, keep_rows, livelink_enabled, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[None]:
    """New York household, aggregation on, the job on the fixture session, today 03-11."""
    keys = {"timezone": "America/New_York", "livelink_daily_aggregation_enabled": "true"}
    await keep_rows(*keys)
    for key, value in keys.items():
        await db_session.execute(delete(Setting).where(Setting.key == key))
        db_session.add(Setting(key=key, value=value))
    await db_session.commit()
    monkeypatch.setattr(
        livelink_tasks, "AsyncSessionLocal", lambda: _PassthroughSessionContext(db_session)
    )
    monkeypatch.setattr(livelink_tasks, "household_today", lambda: date(2026, 3, 11))
    # The job sums every vehicle, so anything it writes beyond ours goes too.
    before = set((await db_session.scalars(select(TelemetryDailySummary.id))).all())
    yield
    await db_session.rollback()
    after = set((await db_session.scalars(select(TelemetryDailySummary.id))).all())
    if after - before:
        await db_session.execute(
            delete(TelemetryDailySummary).where(TelemetryDailySummary.id.in_(after - before))
        )
        await db_session.commit()


async def test_the_job_upserts_the_last_three_household_days(
    db_session: AsyncSession, vehicle, job_settings
) -> None:
    vin, device_id = vehicle
    # Local noon on each day from the 7th to the 11th.
    await _readings(
        db_session,
        vin,
        device_id,
        "DSUM_JOB",
        [
            (datetime(2026, 3, 7, 17), 7.0),
            (datetime(2026, 3, 8, 16), 8.0),
            (datetime(2026, 3, 9, 16), 9.0),
            (datetime(2026, 3, 10, 16), 10.0),
            (datetime(2026, 3, 11, 16), 11.0),
        ],
    )

    await livelink_tasks.generate_daily_summaries()

    expected = {
        date(2026, 3, 8): (8.0, 8.0, 8.0, 1),
        date(2026, 3, 9): (9.0, 9.0, 9.0, 1),
        date(2026, 3, 10): (10.0, 10.0, 10.0, 1),
    }
    assert await _summaries(db_session, vin, "DSUM_JOB") == expected

    await livelink_tasks.generate_daily_summaries()

    assert await _summaries(db_session, vin, "DSUM_JOB") == expected
    assert await _row_count(db_session, vin) == 3


async def test_a_ready_column_is_remembered(
    db_session: AsyncSession, vehicle, new_york, monkeypatch: pytest.MonkeyPatch
) -> None:
    vin, _device_id = vehicle
    monkeypatch.setattr(GUARD_FLAG, False)
    from app.services import telemetry_service

    await TelemetryService(db_session).generate_daily_summary(date(2026, 3, 10), vin=vin)

    assert telemetry_service._summary_date_ready is True


# The 032 table as SQLite holds it until 164 runs.
_OLD_SUMMARY_DDL = """
CREATE TABLE telemetry_daily_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
    param_key VARCHAR(100) NOT NULL,
    date DATETIME NOT NULL,
    min_value FLOAT,
    max_value FLOAT,
    avg_value FLOAT,
    sample_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(vin, param_key, date)
)
"""


async def test_the_job_writes_nothing_until_164_has_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Own engine: the shared test database already has DATE from create_all.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")
    try:
        async with engine.begin() as conn:
            tables = [Base.metadata.tables[m.__tablename__] for m in (Setting, VehicleTelemetry)]
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
            await conn.execute(text(_OLD_SUMMARY_DDL))
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with sessionmaker() as s:
            s.add(Setting(key="livelink_enabled", value="true"))
            s.add(
                VehicleTelemetry(
                    vin="DSUMOLD0000000001",
                    device_id="dsumold",
                    param_key="DSUM_OLD",
                    value=1.0,
                    timestamp=datetime(2026, 3, 10, 16),
                )
            )
            await s.commit()
        monkeypatch.setattr(livelink_tasks, "AsyncSessionLocal", sessionmaker)
        monkeypatch.setattr(livelink_tasks, "household_today", lambda: date(2026, 3, 11))
        monkeypatch.setattr(GUARD_FLAG, False)

        with caplog.at_level(logging.ERROR):
            await livelink_tasks.generate_daily_summaries()

        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT * FROM telemetry_daily_summary"))).all()
        assert rows == []
        errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
        # One refusal per day the job tried, each naming 164, and nothing else went wrong.
        assert len(errors) == 3, errors
        assert all("164" in message for message in errors), errors
        from app.services import telemetry_service

        assert telemetry_service._summary_date_ready is False
    finally:
        await engine.dispose()
