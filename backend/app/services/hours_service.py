"""Shared engine-hours read helpers (used by dashboard + vehicle-detail routes).

The ONE canonical helper for "current hours" — see the hours-usage-model plan
§1. Every consumer (detail-stats, hero/card, reminders, widget, analytics,
PDF) calls this; none may re-derive "latest" differently. Latest hours is
derived at read time from ``hours_records`` — there is no cache column to
keep consistent (``vehicles.current_hours`` is retired as a read source).
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HoursRecord
from app.utils.household_time import household_today


async def latest_engine_hours_and_date(
    db: AsyncSession, vin: str
) -> tuple[Decimal | None, date | None]:
    """Return the single canonical engine-hours reading and its date for a vin.

    ``ORDER BY engine_hours DESC, date DESC, id DESC LIMIT 1``: a physical
    hour-meter is monotonic, so "current" is the MAX reading on record, not
    necessarily the most recently dated one — a lower-hours manual correction
    entered after a higher reading must not make current hours appear to go
    backwards. Ties on ``engine_hours`` break to the newest ``date``; ties on
    both break to the highest ``id``. Deterministic on SQLite (prod) AND
    PostgreSQL (CI). Fetched ONCE per call so the displayed reading and any
    hours-reminder evaluation always agree. Returns ``(None, None)`` when the
    vehicle has no hours reading.
    """
    row = (
        await db.execute(
            select(HoursRecord.engine_hours, HoursRecord.date)
            .where(HoursRecord.vin == vin)
            .order_by(
                HoursRecord.engine_hours.desc(),
                HoursRecord.date.desc(),
                HoursRecord.id.desc(),
            )
            .limit(1)
        )
    ).first()
    if row is None:
        return None, None
    return row[0], row[1]


async def nearest_hours_record(db: AsyncSession, vin: str, on: date) -> HoursRecord | None:
    """The hours row closest to `on` by day distance, a tie going to the earlier one."""
    before = (
        await db.execute(
            select(HoursRecord)
            .where(HoursRecord.vin == vin, HoursRecord.date <= on)
            .order_by(
                HoursRecord.date.desc(), HoursRecord.engine_hours.desc(), HoursRecord.id.desc()
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    after = (
        await db.execute(
            select(HoursRecord)
            .where(HoursRecord.vin == vin, HoursRecord.date > on)
            .order_by(HoursRecord.date.asc(), HoursRecord.engine_hours.asc(), HoursRecord.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if before is None:
        return after
    if after is None:
        return before
    if (on - before.date).days <= (after.date - on).days:
        return before
    return after


async def nearest_hours(db: AsyncSession, vin: str, on: date) -> Decimal | None:
    """The engine-hours reading closest to `on` by day distance, or None.

    The mirror of ``odometer_service.nearest_odometer``: the latest reading on
    or before `on` and the earliest after it, then the smaller day distance,
    a tie going to the earlier one. Lives here because this module is the one
    home for hours reads.
    """
    record = await nearest_hours_record(db, vin, on)
    return record.engine_hours if record is not None else None


async def set_manual_current_hours(
    db: AsyncSession,
    vin: str,
    engine_hours: Decimal,
    *,
    commit: bool = False,
) -> HoursRecord:
    """Upsert TODAY's manual engine-hours reading, idempotently (R2-H1).

    Retires ``vehicles.current_hours`` as a write target — the vehicle
    create/update flow (``services/vehicle_service.py``) intercepts a
    submitted ``current_hours`` value out of its setattr path and calls this
    instead, so the reading lands in the authoritative ``hours_records``
    history that :func:`latest_engine_hours_and_date` derives "current" from,
    rather than a dead column nothing reads for display anymore.

    Locates the existing manual row for this vin dated today — ``source ==
    'manual'`` with BOTH ``fuel_record_id`` and ``service_visit_id`` null,
    the same identity a fuel/service-synced row (``app.utils.hours_sync``)
    never carries — and updates its ``engine_hours`` in place. A repeated
    call the SAME day (e.g. two vehicle updates in one session) updates that
    ONE row rather than creating a second: at most one manual row per vin
    per day, in the common case. Creates one when absent.

    The manual-hours CRUD endpoint (``POST /api/vehicles/{vin}/hours``) has
    no same-day uniqueness guard, so more than one matching row CAN exist by
    the time this upsert runs. Tolerate that: order by ``id DESC`` and take
    the newest match with ``.scalars().first()`` rather than
    ``scalar_one_or_none()``, which raises ``MultipleResultsFound`` (an
    unhandled 500 on the vehicle-update path) the moment a second manual row
    for today exists.

    Args:
        commit: When True, commits and refreshes within its own unit of
            work. When False (the default — vehicle create/update composes
            this into their own transaction) only flushes, so the row is
            visible to the caller's own commit.

    Returns:
        The created or updated ``HoursRecord``.
    """
    today = household_today()
    existing = (
        (
            await db.execute(
                select(HoursRecord)
                .where(
                    HoursRecord.vin == vin,
                    HoursRecord.date == today,
                    HoursRecord.source == "manual",
                    HoursRecord.fuel_record_id.is_(None),
                    HoursRecord.service_visit_id.is_(None),
                )
                .order_by(HoursRecord.id.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )

    if existing is not None:
        existing.engine_hours = engine_hours
        if commit:
            await db.commit()
            await db.refresh(existing)
        else:
            await db.flush()
        return existing

    record = HoursRecord(
        vin=vin,
        date=today,
        engine_hours=engine_hours,
        notes="[manual current-hours entry]",
        source="manual",
    )
    db.add(record)
    if commit:
        await db.commit()
        await db.refresh(record)
    else:
        await db.flush()
    return record
