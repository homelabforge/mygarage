"""Utility for auto-syncing odometer records from service and fuel records.

Metric-canonical since v2.26.2: `odometer_km` (Decimal kilometers).

Since v2.27.0 the helper supports a `commit` flag so callers (e.g. the
extended fuel-tracking flow) can compose this into a single outer
transaction with other side effects.
"""

from collections.abc import Iterable, Sequence
from datetime import date as date_type
from decimal import Decimal
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OdometerRecord
from app.utils.odometer_tolerance import odometer_below

#: The start of every marker a tire event writes: `tire` (readings),
#: `tire_mount`, `tire_dismount`, `tire_retire`, `tire_lone_dismount`,
#: `tire_rotation` and `tire_set` all begin with it. Each belongs to the tire
#: event that wrote it (the period editor moves the mount and dismount ones,
#: a second retire moves the retire one, and `delete_tire` removes the tire's
#: own: its readings', retire and lone-dismount markers, plus the mount and
#: dismount markers of each of its periods), so no other source may take one over.
TIRE_MARKER_PREFIX = "[AUTO-SYNC from tire"

#: Sources that own exactly ONE odometer row per source record: their marker
#: embeds a per-record id and their edit paths move that row across dates
#: (issue #171). Tire markers are keyed by tire/period/event and mark one row
#: per reading date, so they must never get the vin-wide identity lookup.
SINGLE_ROW_SOURCES = frozenset({"fuel", "service_visit", "def"})


def is_tire_marked(record: OdometerRecord) -> bool:
    """Whether a tire event wrote this odometer record."""
    return record.notes is not None and record.notes.startswith(TIRE_MARKER_PREFIX)


def legacy_service_marker(source_id: int) -> str:
    """The pre-rename service marker, ``[AUTO-SYNC from service #N]``.

    Databases from before the ``service_visit`` marker rename still hold
    rows with this note. The delete path has always recognized it; ownership
    lookup must too, or a date edit misses the legacy row and re-creates the
    #171 duplicate for exactly the oldest data (codex PR review P1).
    """
    return f"[AUTO-SYNC from service #{source_id}]"


def auto_sync_marker(source_type: str, source_id: int) -> str:
    """The note that marks an odometer row as owned by one source record.

    Written here and matched by the cleanup paths that remove a synced row when
    its source is deleted. Those paths used to hardcode the format string, so
    the writer and the matcher were one edit apart from silently disagreeing --
    and a mismatch does not fail loudly, it just orphans the row.
    """
    return f"[AUTO-SYNC from {source_type} #{source_id}]"


async def same_day_records(db: AsyncSession, vin: str, date: date_type) -> Sequence[OdometerRecord]:
    """Every odometer record of `vin` on `date`, newest first.

    By SQL, so a caller on a session that does not autoflush must flush a
    pending move or delete before asking.
    """
    result = await db.execute(
        select(OdometerRecord)
        .where(OdometerRecord.vin == vin)
        .where(OdometerRecord.date == date)
        .order_by(OdometerRecord.id.desc())
    )
    return result.scalars().all()


async def _own_records(
    db: AsyncSession, vin: str, marker: str, source_type: str, source_id: int
) -> list[OdometerRecord]:
    """Every odometer record this source owns, on ANY date, newest first.

    Identity is the marker note (all sources), plus `fuel_record_id` for fuel
    (migration 055's FK survives note edits). Never `(vin, date)`: issue #171
    was exactly a date-scoped lookup missing the source's own row after a
    date edit, orphaning it and duplicating or hijacking on the new date.
    `hours_sync` has matched by source identity from the start; this brings
    the odometer helper in line.
    """
    conditions = [OdometerRecord.notes == marker]
    if source_type == "fuel":
        conditions.append(OdometerRecord.fuel_record_id == source_id)
    if source_type == "service_visit":
        conditions.append(OdometerRecord.notes == legacy_service_marker(source_id))
    result = await db.execute(
        select(OdometerRecord)
        .where(OdometerRecord.vin == vin)
        .where(or_(*conditions))
        .order_by(OdometerRecord.id.desc())
    )
    return list(result.scalars().all())


async def remove_synced_odometer(
    db: AsyncSession, vin: str, source_type: str, source_id: int
) -> None:
    """Delete the odometer reading(s) a source synced, when its reading is cleared.

    `sync_odometer_from_record` skips a None, so without this a cleared
    reading stayed in the log and kept feeding reminder projections. Only the
    rows `_own_records` finds go (this source's marker, or its fuel FK), so a
    manual, LiveLink or tire reading on the same day is never touched. The
    hours track does the same on a clear. Flushes, never commits.
    """
    marker = auto_sync_marker(source_type, source_id)
    for record in await _own_records(db, vin, marker, source_type, source_id):
        await db.delete(record)
    await db.flush()


def reads_at_or_above(records: Iterable[OdometerRecord], odometer_km: Decimal) -> bool:
    """Whether any of `records` reads at or above `odometer_km`.

    Within the same-reading tolerance (`app.utils.odometer_tolerance`): a record
    a few parts per million below counts as the same figure, so only records
    below by more than the tolerance leave the figure higher than the day's.
    """
    return any(not odometer_below(record.odometer_km, odometer_km) for record in records)


async def sync_odometer_from_record(
    db: AsyncSession,
    vin: str,
    date: date_type,
    odometer_km: Decimal | None,
    source_type: str,
    source_id: int,
    *,
    commit: bool = True,
    claim_other_records: bool = True,
    operation: Literal["create", "update"] = "create",
) -> OdometerRecord | None:
    """Create, update, or MOVE an odometer record from a service/fuel record.

    Behavior:
        - Skips sync if odometer_km is None
        - A record this source owns (`_own_records`: marker or fuel FK, any
          date) is updated in place, INCLUDING its date. Editing the source's
          date moves the row instead of orphaning it (issue #171)
        - Otherwise, on `operation="create"` only, the newest record of the
          new date that no tire event wrote: if it was auto-synced or from
          livelink, takes it over (user-entered fuel/service data is more
          authoritative than LiveLink); if it was manual, does not overwrite
        - On `operation="update"` with no owned row (a same-day sibling's
          create claimed it, or it was hand-deleted), a fresh row is created:
          an update NEVER claims another source's row, because the row it
          would find on the destination date belongs to someone else and a
          later delete of this source would cascade it away (issue #171's
          side effect)
        - A record a tire event wrote (`is_tire_marked`) is never taken over:
          the tire moves and deletes it by its own marker, so re-marking it
          would remove the tire's reading
        - Otherwise creates a new odometer record with source marker

    With `claim_other_records=False` the source never touches a record it did
    not create. A record it owns has its value (and date) updated. Otherwise,
    when any other record on that date (manual, LiveLink, or another source's
    automatic one) reads at or above the figure (`reads_at_or_above`),
    nothing is written: the day already has a reading at least as high.
    Otherwise, with no record on the date or only lower ones, a record with
    this source's marker is created; being the day's highest reading, it is
    the vehicle's current reading for that day (the highest reading on the
    latest date).
    The tire paths publish this way: a tire event's record is later moved or
    deleted by marker, so a record it had re-marked would take another
    source's reading with it.

    Args:
        commit: When True (default) the helper commits and refreshes within
            its own unit of work. When False the caller is responsible for
            committing — the helper still flushes so the row gets an id and
            any FK side effects are visible to subsequent queries inside the
            same transaction.
        claim_other_records: When True (default) the one-reading-per-day
            policy above applies, and an automatic or LiveLink record on the
            date becomes this source's ON CREATE. When False, see above.
        operation: "create" for a record's first sync, "update" when the
            caller is editing an existing source record. Only an update may
            move a row across dates, and only a create may claim.
    """
    if odometer_km is None:
        return None

    marker = auto_sync_marker(source_type, source_id)

    # Migration 055 added odometer_records.fuel_record_id with ON DELETE
    # CASCADE for fuel-sourced rows. Set it when source is 'fuel' so the
    # database can clean orphans when a fuel record is deleted; for
    # service/livelink the FK stays NULL (no fuel parent to cascade from).
    fk_value = source_id if source_type == "fuel" else None

    if source_type in SINGLE_ROW_SOURCES:
        own = await _own_records(db, vin, marker, source_type, source_id)
        existing = own[0] if own else None
        for extra in own[1:]:
            # Self-heal: pre-fix date edits left one owned row per edit behind
            # (issue #171). Keep the newest, drop the leftovers; migration 106
            # repairs stocks this path never revisits.
            await db.delete(extra)
    else:
        # Tire publishes: their markers are keyed by tire/period/event, not by
        # reading, so ONE marker legitimately marks a row per reading date. A
        # vin-wide identity lookup here collapsed that history into the newest
        # row (codex code review R1-H1), so identity stays DATE-scoped — the
        # pre-#171 shape. The period editor moves rows by its own marker.
        same_day = await same_day_records(db, vin, date)
        existing = next((row for row in same_day if row.notes == marker), None)

    if existing is None:
        if claim_other_records:
            if operation == "create":
                # idx_odometer_vin_date is NOT unique, and multiple readings on
                # one date are legitimate (a manual entry plus a device reading,
                # start/end of a trip day). Newest first, ordered
                # deterministically so repeated syncs pick the same target.
                same_day = await same_day_records(db, vin, date)
                candidate = next((row for row in same_day if not is_tire_marked(row)), None)
                if candidate is not None:
                    is_auto_synced = candidate.notes and "[AUTO-SYNC from" in candidate.notes
                    is_livelink = candidate.source == "livelink"
                    if not (is_auto_synced or is_livelink):
                        return None
                    existing = candidate
        else:
            same_day = await same_day_records(db, vin, date)
            if reads_at_or_above(same_day, odometer_km):
                return None

    if existing is not None:
        existing.date = date
        existing.odometer_km = odometer_km
        existing.notes = marker
        existing.source = source_type
        existing.fuel_record_id = fk_value
        if commit:
            await db.commit()
            await db.refresh(existing)
        else:
            await db.flush()
        return existing

    odometer_record = OdometerRecord(
        vin=vin,
        date=date,
        odometer_km=odometer_km,
        notes=marker,
        source=source_type,
        fuel_record_id=fk_value,
    )
    db.add(odometer_record)
    if commit:
        await db.commit()
        await db.refresh(odometer_record)
    else:
        await db.flush()
    return odometer_record
