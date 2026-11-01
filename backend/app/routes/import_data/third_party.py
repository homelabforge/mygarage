"""The Fuelio, Drivvo, Tesla and generic fuel CSV imports."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.fuel import (
    normalize_fuel_type,
)
from app.database import get_db
from app.models import (
    FuelRecord,
)
from app.models.user import User
from app.routes.import_data._common import (
    ImportResult,
    _in_vocabulary,
    _RowError,
    _unexpected_reason,
    _within_api_bounds,
    limiter,
    router,
)
from app.routes.import_data._matching import (
    _converted_value_matches,
    _last_id_before_import,
    _odometer_matches,
)
from app.routes.import_data._readings import _ImportReadings
from app.schemas.fuel import (
    CHARGE_LEVEL_VALUES,
    CHARGE_LOCATION_VALUES,
    PRICE_BASIS_VALUES,
    FuelRecordCreate,
)
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.file_validation import validate_csv_upload
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_tolerance import LITRE_STEP

logger = logging.getLogger(__name__)


def _normalized_fuel_type(raw: str | None) -> str | None:
    """A legacy free-text fuel type as its canonical enum value, or None."""
    normalized = normalize_fuel_type(raw)
    return normalized.value if normalized is not None else None


@router.post("/vehicles/{vin}/fuel/fuelio")
@limiter.limit(settings.rate_limit_uploads)
async def import_fuelio_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    odometer_unit: str = Form("km"),
    decimal_separator: str = Form("dot"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import fuel records from a Fuelio CSV export.

    ``odometer_unit`` and ``decimal_separator`` declare how to read columns the
    export does not label. Defaults are metric and dot, matching storage.
    """
    return await _import_third_party_fuel(
        vin,
        file,
        skip_duplicates,
        db,
        current_user,
        "fuelio",
        _parse_options(odometer_unit, decimal_separator),
    )


@router.post("/vehicles/{vin}/fuel/drivvo")
@limiter.limit(settings.rate_limit_uploads)
async def import_drivvo_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    odometer_unit: str = Form("km"),
    decimal_separator: str = Form("dot"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import fuel records from a Drivvo CSV export.

    ``odometer_unit`` and ``decimal_separator`` declare how to read columns the
    export does not label. Defaults are metric and dot, matching storage.
    """
    return await _import_third_party_fuel(
        vin,
        file,
        skip_duplicates,
        db,
        current_user,
        "drivvo",
        _parse_options(odometer_unit, decimal_separator),
    )


@router.post("/vehicles/{vin}/fuel/tesla")
@limiter.limit(settings.rate_limit_uploads)
async def import_tesla_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    odometer_unit: str = Form("km"),
    decimal_separator: str = Form("dot"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import charge sessions from a Tesla / ABRP-style charge history CSV.

    ``odometer_unit`` and ``decimal_separator`` declare how to read columns the
    export does not label. Defaults are metric and dot, matching storage.
    """
    return await _import_third_party_fuel(
        vin,
        file,
        skip_duplicates,
        db,
        current_user,
        "tesla",
        _parse_options(odometer_unit, decimal_separator),
    )


@router.post("/vehicles/{vin}/fuel/external")
@limiter.limit(settings.rate_limit_uploads)
async def import_external_fuel_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    format: str | None = Form(None),
    odometer_unit: str = Form("km"),
    decimal_separator: str = Form("dot"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Auto-detect Fuelio / Drivvo / Tesla CSV format (or pass format= explicitly)."""
    csv_data = await validate_csv_upload(file)
    from app.services.import_adapters import PARSERS, detect_format

    fmt = (format or detect_format(csv_data) or "").lower()
    if fmt not in PARSERS:
        raise HTTPException(
            status_code=400,
            detail="Unrecognized CSV format — pass format=fuelio|drivvo|tesla",
        )
    # Re-wrap for the shared helper (it re-reads the upload); parse inline instead.
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    parsed = PARSERS[fmt](csv_data, _parse_options(odometer_unit, decimal_separator))
    await lock_vehicle_for_write(db, vin)
    return await _persist_parsed_fuel(vin, parsed, skip_duplicates, db)


# The natural key of a physical fill-up or charge session: when it happened,
# where the odometer stood, and how much went in.
#
# Deliberately NOT every persisted column. Cost, notes, location and SOC are
# metadata a user may correct in the source app between exports, so including
# them would make a re-import of a corrected file insert duplicates instead of
# skipping them. Two same-day sessions are told apart by filled_at, which the
# adapters now preserve; before that the time was truncated away and the only
# way to separate them was to compare mutable fields.
#
# When an export carries no time at all, filled_at is NULL on both rows and two
# sessions with the same odometer and the same amount are genuinely
# indistinguishable in the data, so collapsing them is correct.
def _third_party_duplicate_conditions(
    vin: str, row: Mapping[str, Any], last_id_before_import: int
) -> list[ColumnElement[bool]]:
    """The natural key above, as the conditions a stored duplicate must meet.

    `filled_at` and `kwh` are never converted and match exactly (`== None`
    renders as IS NULL). The odometer and the volume may have been converted
    from miles and gallons, and the adapters settle that per file (an explicit
    "(mi)" or "Gallons" header wins over the caller's option), so both are
    treated as converted: the band still applies only to a row stored before
    the import, and the time and the volume in the key tell two real fill-ups
    apart where the band alone could not.
    """
    return [
        FuelRecord.vin == vin,
        FuelRecord.date == row.get("date"),
        FuelRecord.filled_at == row.get("filled_at"),
        _odometer_matches(
            FuelRecord,
            row.get("odometer_km"),
            converted=True,
            last_id_before_import=last_id_before_import,
        ),
        _converted_value_matches(
            FuelRecord.liters,
            row.get("liters"),
            LITRE_STEP,
            converted=True,
            stored_before_import=FuelRecord.id <= last_id_before_import,
        ),
        FuelRecord.kwh == row.get("kwh"),
    ]


def _parse_options(odometer_unit: str, decimal_separator: str):
    """Build ParseOptions from form input, rejecting anything off-vocabulary."""
    from app.services.import_adapters import ParseOptions

    if odometer_unit not in ("km", "mi"):
        raise HTTPException(status_code=400, detail="odometer_unit must be km or mi")
    if decimal_separator not in ("dot", "comma"):
        raise HTTPException(status_code=400, detail="decimal_separator must be dot or comma")
    return ParseOptions(odometer_unit=odometer_unit, decimal_separator=decimal_separator)


async def _import_third_party_fuel(
    vin: str,
    file: UploadFile,
    skip_duplicates: bool,
    db: AsyncSession,
    current_user: User | None,
    format_name: str,
    opts=None,
):
    from app.services.import_adapters import PARSERS

    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    csv_data = await validate_csv_upload(file)
    parsed = PARSERS[format_name](csv_data, opts)
    await lock_vehicle_for_write(db, vin)
    return await _persist_parsed_fuel(vin, parsed, skip_duplicates, db)


async def _persist_parsed_fuel(
    vin: str,
    parsed: list[dict],
    skip_duplicates: bool,
    db: AsyncSession,
):
    import_result = ImportResult()
    # Odometer sync matches on (vin, date) and overwrites, so syncing every row
    # would let CSV order decide the stored value and reassign the cascade FK.
    # Sync once per date with the highest reading, which is the only choice
    # that survives reordering the file.
    readings = _ImportReadings()
    # Callers take the vehicle write lock first; see `_converted_value_matches`.
    last_id = await _last_id_before_import(db, FuelRecord)
    for row_num, row in enumerate(parsed, start=2):
        try:
            date = row.get("date")
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue
            odometer_km = row.get("odometer_km")
            _within_api_bounds(
                FuelRecordCreate,
                odometer_km=odometer_km,
                liters=row.get("liters"),
                kwh=row.get("kwh"),
                cost=row.get("cost"),
                price_per_unit=row.get("price_per_unit"),
                soc_start_pct=row.get("soc_start_pct"),
                soc_end_pct=row.get("soc_end_pct"),
                battery_soh_pct=row.get("battery_soh_pct"),
            )
            price_basis = _in_vocabulary(row.get("price_basis"), "price_basis", PRICE_BASIS_VALUES)
            charge_level = _in_vocabulary(
                row.get("charge_level"), "charge_level", CHARGE_LEVEL_VALUES
            )
            charge_location = _in_vocabulary(
                row.get("charge_location"), "charge_location", CHARGE_LOCATION_VALUES
            )
            if skip_duplicates:
                existing = await db.execute(
                    select(FuelRecord).where(*_third_party_duplicate_conditions(vin, row, last_id))
                )
                # .first(), not scalar_one_or_none(): pre-existing duplicates in
                # the table would otherwise raise MultipleResultsFound.
                if existing.scalars().first():
                    import_result.add_skip()
                    continue
            record = FuelRecord(
                vin=vin,
                date=date,
                filled_at=row.get("filled_at"),
                odometer_km=odometer_km,
                liters=row.get("liters"),
                kwh=row.get("kwh"),
                cost=row.get("cost"),
                price_per_unit=row.get("price_per_unit"),
                price_basis=price_basis,
                is_full_tank=bool(row.get("is_full_tank", True)),
                notes=row.get("notes"),
                # v4-and-older backups carry the retired free-text "fuel_type"
                # instead, so fall back to it through the normalizer rather
                # than restoring those records with no fuel type at all.
                fuel_type_used=row.get("fuel_type_used")
                or _normalized_fuel_type(row.get("fuel_type")),
                soc_start_pct=row.get("soc_start_pct"),
                soc_end_pct=row.get("soc_end_pct"),
                charge_level=charge_level,
                charge_location=charge_location,
                battery_soh_pct=row.get("battery_soh_pct"),
            )
            # Savepoint per row: the flush below populates record.id, and a bare
            # flush failure would poison the session for every remaining row.
            async with db.begin_nested():
                db.add(record)
                await db.flush()
            readings.add("fuel", record.id, record.date, odometer_km=record.odometer_km)
            import_result.add_success()
        except _RowError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("External fuel import row %d failed: %s", row_num, sanitize_for_log(e))
            import_result.add_error(row_num, _unexpected_reason(e, "Invalid fuel record data"))

    # The create path's claiming sync: a third-party export is no backup, so a
    # same-day automatic or LiveLink row is taken over as before (T-15, T-17).
    await readings.apply(db, vin, claim=True)

    await db.commit()
    return import_result.to_dict()
