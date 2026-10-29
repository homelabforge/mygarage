"""DTCs in a JSON backup: every column, keyed on the code and when it was first seen (K11).

A flat section, matched one to one like recalls (R5). One rule sits over the
key: a vehicle holds one active row per code, so an active copy of a code
that's already active here is skipped with a warning, whatever the file says.
"""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_dtc import VehicleDTC
from app.routes.import_data._common import (
    _json_bool,
    _json_row_datetime,
    _json_text,
    _RowError,
    _unexpected_reason,
)
from app.routes.import_data._families import as_object
from app.routes.import_data._matching import _DuplicateMatcher
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


def _required_text(row: Mapping[str, Any], key: str) -> str:
    """Text the row must carry: the column is NOT NULL."""
    value = _json_text(row, key)
    if value is None:
        raise _RowError(f"{key} is missing")
    return value


def _required_datetime(row: Mapping[str, Any], key: str) -> datetime:
    """A timestamp the row must carry. The column's now() default would make one up."""
    value = _json_row_datetime(row, key)
    if value is None:
        raise _RowError(f"{key} is missing")
    return value


def _dtc_from_json(vin: str, row: Mapping[str, Any]) -> VehicleDTC:
    """One DTC as an unsaved row, every column the export writes.

    Text is read as given (NB-1), and the code and device id aren't upper-cased:
    a restore keeps what was stored. A missing severity gets the column default.
    """
    return VehicleDTC(
        vin=vin,
        device_id=_required_text(row, "device_id"),
        code=_required_text(row, "code"),
        description=_json_text(row, "description"),
        severity=_json_text(row, "severity"),
        user_notes=_json_text(row, "user_notes"),
        first_seen=_required_datetime(row, "first_seen"),
        last_seen=_required_datetime(row, "last_seen"),
        cleared_at=_json_row_datetime(row, "cleared_at"),
        is_active=_json_bool(row, "is_active", default=True),
    )


def _json_dtc_key(dtc: VehicleDTC) -> list[ColumnElement[bool]]:
    """S6's DTC key: the code and when it was first seen. The route adds the vehicle."""
    return [VehicleDTC.code == dtc.code, VehicleDTC.first_seen == dtc.first_seen]


async def _active_here(db: AsyncSession, vin: str, code: str) -> bool:
    """Whether the vehicle has an active row of `code`, any row at all.

    A row this import wrote counts, and so does one a live report just committed.
    """
    result = await db.execute(
        select(VehicleDTC.id)
        .where(VehicleDTC.vin == vin, VehicleDTC.code == code, VehicleDTC.is_active.is_(True))
        .limit(1)
    )
    return result.first() is not None


def _skip_active_copy(bucket: dict[str, int], warnings: list[str], idx: int, code: str) -> None:
    """Skip an active copy of a code that's active here, and say so (K11)."""
    bucket["skipped"] += 1
    warnings.append(
        f"DTC {idx}: {code} is already active on this vehicle, so this copy wasn't imported"
    )


async def import_dtcs(
    db: AsyncSession,
    vin: str,
    rows: Sequence[Any],
    *,
    matcher: _DuplicateMatcher,
    skip_duplicates: bool,
    bucket: dict[str, int],
    errors: list[str],
    warnings: list[str],
) -> None:
    """Import the file's DTCs one row at a time, a bad one a row error (3a's flat loop).

    Nothing here notifies: only telemetry ingest creates a DTC and tells anyone.
    """
    # Anything an earlier section left pending fails here, not on DTC 0's insert.
    await db.flush()
    for idx, row in enumerate(rows):
        try:
            dtc = _dtc_from_json(vin, as_object(row))
            if skip_duplicates:
                stored: VehicleDTC | None = await matcher.take(
                    db, VehicleDTC, VehicleDTC.vin == vin, *_json_dtc_key(dtc)
                )
                if stored is not None:
                    bucket["skipped"] += 1
                    continue

            code, active = dtc.code, dtc.is_active
            # Looked for first, so the rule holds where 137 couldn't build its index.
            if active and await _active_here(db, vin, code):
                _skip_active_copy(bucket, warnings, idx, code)
                continue
            # Then the index (migration 137) says no to a live report that lands
            # between the look and the insert, so the race can't leave two.
            try:
                async with db.begin_nested():
                    db.add(dtc)
                    await db.flush()
            except IntegrityError:
                # A cleared row never meets the index, so it's some other failure.
                if not (active and await _active_here(db, vin, code)):
                    raise
                _skip_active_copy(bucket, warnings, idx, code)
                continue
            bucket["success"] += 1
        except _RowError as e:
            bucket["errors"] += 1
            errors.append(f"DTC {idx}: {e.reason}")
        except Exception as e:
            bucket["errors"] += 1
            logger.warning("Import: DTC %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"DTC {idx}: {_unexpected_reason(e)}")
