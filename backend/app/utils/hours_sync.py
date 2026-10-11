"""Utility for auto-syncing engine-hours records from service and fuel records.

Parallel to :mod:`app.utils.odometer_sync`, with one deliberate divergence
(resolves R1-H2 from the hours-usage-model plan): a synced row is located by
SOURCE IDENTITY — ``fuel_record_id`` or ``service_visit_id`` — never by
``(vin, date)`` and never by parsing the ``[AUTO-SYNC ...]`` note marker. That
gives service-sourced rows a stable identity so they can be removed by FK
cascade (``ON DELETE CASCADE``) when their parent service visit is deleted,
rather than orphaning the way the odometer track does today.

The exception is ``publish_marked_hours``, for tire events, which have no FK:
their rows carry the event's marker, ``source`` set to the tire source, both
FKs null, so the FK paths here never see them (#217).

The caller composes this into an outer transaction (the fuel/service create
and update flows), so both helpers accept a ``commit`` flag: ``True``
(default) commits and refreshes within its own unit of work; ``False`` only
flushes, so the row gets an id and any FK side effects are visible to
subsequent queries inside the same transaction, and the caller commits once
at the end — mirroring ``odometer_sync``'s ``commit`` flag.
"""

from collections.abc import Sequence
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HoursRecord
from app.utils.hours_tolerance import hours_below
from app.utils.odometer_sync import auto_sync_marker

# The only source identities a synced hours row can carry. Exhaustive on
# purpose: an unrecognized source_type must fail loudly rather than silently
# fall through to service_visit_id (which would filter on the wrong column,
# miss any existing synced row for the real source, and create a duplicate
# with BOTH FK columns null).
_SOURCE_TYPES = ("fuel", "service_visit")


def _validate_source_type(source_type: str) -> None:
    """Raise ValueError if source_type isn't a known source-identity column."""
    if source_type not in _SOURCE_TYPES:
        raise ValueError(
            f"Unknown hours source_type {source_type!r}; expected one of {_SOURCE_TYPES}"
        )


def _source_identity_filter(source_type: str, source_id: int) -> ColumnElement[bool]:
    """Build the WHERE clause matching a synced row by source identity.

    ``source_type == "fuel"`` matches on ``fuel_record_id``;
    ``"service_visit"`` matches on ``service_visit_id``. Never ``(vin, date)``,
    never note-parsing.
    """
    _validate_source_type(source_type)
    if source_type == "fuel":
        return HoursRecord.fuel_record_id == source_id
    return HoursRecord.service_visit_id == source_id


async def _commit_or_flush(
    db: AsyncSession, *, commit: bool, refresh: HoursRecord | None = None
) -> None:
    """Commit+refresh or flush-only, per the shared ``commit`` flag contract.

    When ``commit`` is True, commits the unit of work and refreshes
    ``refresh`` (if given) so callers see server-assigned values. When False,
    only flushes — the row gets an id and FK side effects become visible to
    subsequent queries in the same transaction, but the caller commits once
    at the end.
    """
    if commit:
        await db.commit()
        if refresh is not None:
            await db.refresh(refresh)
    else:
        await db.flush()


async def sync_hours_from_record(
    db: AsyncSession,
    vin: str,
    date: date_type,
    engine_hours: Decimal | None,
    source_type: str,
    source_id: int,
    *,
    commit: bool = True,
) -> HoursRecord | None:
    """Create, update, or delete an engine-hours record from a service/fuel record.

    Behavior:
        - Locates any existing synced row by SOURCE IDENTITY (``fuel_record_id``
          when ``source_type == "fuel"``, ``service_visit_id`` when
          ``source_type == "service_visit"``) — never by ``(vin, date)`` and
          never by note-parsing. Raises ``ValueError`` for any other
          ``source_type``.
        - If ``engine_hours`` is ``None``: deletes the existing synced row (the
          reading was cleared on the source record) and returns ``None``. A
          no-op (no commit/flush) when no synced row exists.
        - If a synced row exists: updates its ``engine_hours``, ``date``,
          ``source``, and marker note in place — the SAME row, never a
          duplicate. The FK column that identified it is already correct and
          is left as-is.
        - If none exists: creates one with the matching FK column set
          (``fuel_record_id`` or ``service_visit_id``), ``source=source_type``,
          and note ``[AUTO-SYNC from {source_type} #{source_id}]``.
        - Manual rows (``source='manual'``, both FKs null) are never located by
          the source-identity lookup, so they are never touched — even when
          they share the same ``(vin, date)`` as a synced row.
        - Never writes ``vehicles.current_hours``. Latest hours is derived at
          read time from ``hours_records`` (see ``app.services.hours_service``)
          — there is no cache to keep consistent.

    Args:
        commit: When True (default) the helper commits and refreshes within
            its own unit of work. When False the caller is responsible for
            committing — the helper still flushes so the row gets an id and
            any FK side effects are visible to subsequent queries inside the
            same transaction.

    Returns:
        The created/updated ``HoursRecord``, or ``None`` when the row was
        deleted (or never existed) because ``engine_hours`` is ``None``.

    Raises:
        ValueError: if ``source_type`` isn't ``"fuel"`` or ``"service_visit"``.
    """
    existing = (
        await db.execute(select(HoursRecord).where(_source_identity_filter(source_type, source_id)))
    ).scalar_one_or_none()

    if engine_hours is None:
        if existing is None:
            return None
        await db.delete(existing)
        await _commit_or_flush(db, commit=commit)
        return None

    auto_sync_marker = f"[AUTO-SYNC from {source_type} #{source_id}]"

    if existing is not None:
        existing.engine_hours = engine_hours
        existing.date = date
        existing.source = source_type
        existing.notes = auto_sync_marker
        await _commit_or_flush(db, commit=commit, refresh=existing)
        return existing

    hours_record = HoursRecord(
        vin=vin,
        date=date,
        engine_hours=engine_hours,
        notes=auto_sync_marker,
        source=source_type,
        fuel_record_id=source_id if source_type == "fuel" else None,
        service_visit_id=source_id if source_type == "service_visit" else None,
    )
    db.add(hours_record)
    await _commit_or_flush(db, commit=commit, refresh=hours_record)
    return hours_record


async def remove_synced_hours(
    db: AsyncSession,
    source_type: str,
    source_id: int,
    *,
    commit: bool = True,
) -> None:
    """Delete the hours record synced from a given source, if any.

    Located by SOURCE IDENTITY, same as :func:`sync_hours_from_record`. A
    parent fuel/service-visit delete already cascades this row away via
    ``ON DELETE CASCADE`` (PG enforced; SQLite via ``PRAGMA foreign_keys=ON``,
    active in prod) — this is for explicit cleanup paths that want to remove
    the synced reading without deleting the parent record.

    Args:
        commit: When True (default) commits. When False only flushes, so the
            caller can compose this into a larger transaction.

    Raises:
        ValueError: if ``source_type`` isn't ``"fuel"`` or ``"service_visit"``.
    """
    result = await db.execute(
        delete(HoursRecord).where(_source_identity_filter(source_type, source_id))
    )
    if result.rowcount:
        await _commit_or_flush(db, commit=commit)


async def same_day_hours(db: AsyncSession, vin: str, date: date_type) -> Sequence[HoursRecord]:
    """Every hours row of `vin` on `date`, newest first. By SQL, so flush a pending move first."""
    result = await db.execute(
        select(HoursRecord)
        .where(HoursRecord.vin == vin, HoursRecord.date == date)
        .order_by(HoursRecord.id.desc())
    )
    return result.scalars().all()


async def publish_marked_hours(
    db: AsyncSession,
    vin: str,
    date: date_type,
    engine_hours: Decimal | None,
    source_type: str,
    source_id: int,
) -> HoursRecord | None:
    """Record an event's hour meter as a row it owns by marker, for events with no FK (#217).

    Same rules as the tire odometer publish: update our own row on that day,
    publish nothing when another row that day reads at or above the figure,
    otherwise add our row. FKs stay null. Flushes, never commits.
    """
    if engine_hours is None:
        return None
    marker = auto_sync_marker(source_type, source_id)
    same_day = await same_day_hours(db, vin, date)
    existing = next((row for row in same_day if row.notes == marker), None)
    if existing is not None:
        existing.engine_hours = engine_hours
        await db.flush()
        return existing
    if any(not hours_below(row.engine_hours, engine_hours) for row in same_day):
        return None
    record = HoursRecord(
        vin=vin, date=date, engine_hours=engine_hours, notes=marker, source=source_type
    )
    db.add(record)
    await db.flush()
    return record
