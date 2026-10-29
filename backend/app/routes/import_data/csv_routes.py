"""The nine native CSV import routes."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
from typing import Any

from fastapi import Depends, File, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.fuel import (
    PAYMENT_METHOD_VALUES,
    TRIP_TYPE_VALUES,
    FuelTypeEnum,
    normalize_fuel_type,
)
from app.database import get_db
from app.models import (
    DEFRecord,
    FuelRecord,
    HoursRecord,
    Note,
    OdometerRecord,
    ServiceVisit,
    TaxRecord,
    WarrantyRecord,
)
from app.models.user import User
from app.routes.import_data._common import (
    ImportResult,
    _blank_to_none,
    _ImportBoundError,
    _in_vocabulary,
    _InsuranceRowError,
    _read_csv_with_units,
    _read_mygarage_csv,
    _RowError,
    _unexpected_reason,
    _within_api_bounds,
    limiter,
    parse_bool,
    parse_date,
    parse_decimal,
    parse_int,
    router,
)
from app.routes.import_data._fuel import (
    _DRIVER_KEPT_AS_TEXT,
    _STATION_KEPT_AS_TEXT,
    _csv_fuel_price,
    _local_datetime,
    _portable_driver,
    _portable_station,
    _trip_seconds,
)
from app.routes.import_data._insurance import _import_insurance_row, _merge_converted
from app.routes.import_data._matching import (
    _canonical_cell,
    _converted_value_matches,
    _DuplicateMatcher,
    _matches,
    _money_matches,
    _odometer_matches,
    _or_blank_zero,
    _same_figure,
    _text_matches,
    _zero_was_blank,
)
from app.routes.import_data._readings import _ImportReadings, _without_sync_marker
from app.routes.import_data._service import (
    _VISIT_MATCH_LOADS,
    _parse_service_row,
    _row_item_counts,
    _same_visit,
    _ServiceCsvRow,
    _visit_disagreement,
    _visit_fee_key,
    _write_service_csv_visit,
)
from app.schemas.def_record import DEFRecordCreate
from app.schemas.fuel import (
    CHARGE_LEVEL_VALUES,
    CHARGE_LOCATION_VALUES,
    FuelRecordCreate,
    _validate_diesel_grade,
    _validate_octane,
)
from app.schemas.hours import HoursRecordCreate
from app.schemas.odometer import OdometerRecordCreate
from app.schemas.tax import TaxRecordCreate
from app.schemas.warranty import WarrantyRecordCreate
from app.services import maintenance_service
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.fuel_side_effects import invalidate_cache_for_vehicle
from app.services.insurance_service import InsuranceService
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.csv_units import (
    CONSUMPTION,
    DEF_PRICE,
    DISTANCE,
    FUEL_CONSUMPTION,
    FUEL_PRICE,
    FUEL_PROPANE_VOLUME,
    FUEL_SPEED,
    FUEL_TANK_SIZE,
    FUEL_TEMPERATURE,
    FUEL_VOLUME,
    MASS,
    MILEAGE_LIMIT_DISTANCE,
    ODOMETER_DISTANCE,
    PRICE_PER_VOLUME,
    PROPANE_VOLUME,
    READING_DISTANCE,
    SPEED,
    TEMPERATURE,
    VOLUME,
)
from app.utils.def_sync import ensure_def_capable
from app.utils.file_validation import validate_csv_upload
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_tolerance import KM_STEP, LITRE_STEP

logger = logging.getLogger(__name__)


@router.post("/vehicles/{vin}/service/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_service_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import service records from CSV file (creates ServiceVisit + ServiceLineItem)."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Validate and parse CSV, then settle the file's units once, before any
    # ORM write. A bad header or a self-contradictory file is refused whole
    # rather than half-imported (see `app.utils.csv_units`).
    csv_data = await validate_csv_upload(file)
    rows, units = _read_csv_with_units(csv_data, (ODOMETER_DISTANCE,))

    # The vehicle write lock, taken before the first read of stored rows and
    # before any write. On SQLite it opens the one transaction that every
    # row's savepoint nests in; without it each savepoint commits its row on
    # release (see `app.database`), and a failure later in the upload would
    # leave the rows before it behind. Every import route takes it the same way.
    await lock_vehicle_for_write(db, vin)
    # Taken before the first write; see `_converted_value_matches` for why.
    odometer_converted = units.converts(DISTANCE)
    matcher = await _DuplicateMatcher.before_import(db, ServiceVisit)
    readings = _ImportReadings()

    import_result = ImportResult()
    # The key compares only the columns the file has (T-16). Read off the
    # first row, so an upload with none has none.
    header: set[str] = set(rows[0]) if rows else set()
    carries_vendor = "Vendor" in header or "Vendor Name" in header
    carries_description = "Description" in header

    # Every row first, then each visit: a v8 row names its visit by number, an
    # older one belongs with the rows sharing its date, odometer, vendor and
    # category (G4-73). Counts stay per row (T-4).
    groups: dict[tuple[Any, ...], list[_ServiceCsvRow]] = {}
    for row_num, row in enumerate(rows, start=2):  # Start at 2 (header is row 1)
        try:
            parsed = _parse_service_row(row_num, row, units)
        except _RowError as e:
            import_result.add_error(row_num, e.reason)
            continue
        except Exception as e:
            # Intentional catch-all: per-row errors should not stop the import
            logger.error("Service import row %d failed: %s", row_num, sanitize_for_log(e))
            import_result.add_error(row_num, _unexpected_reason(e, "Invalid service record data"))
            continue
        groups.setdefault(parsed.group, []).append(parsed)

    for group in groups.values():
        # A MyGarage export never disagrees with itself, so this is a hand edit.
        # Refuse it rather than guess which row is right (K8).
        if (reason := _visit_disagreement(group)) is not None:
            for row in group:
                import_result.add_error(row.row_num, reason)
            continue
        first = group[0]
        try:
            # R5's service key: a stored visit on the day and odometer with the
            # same shop, fees and line items, each only where the file has it.
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    ServiceVisit,
                    ServiceVisit.vin == vin,
                    ServiceVisit.date == first.date,
                    _odometer_matches(
                        ServiceVisit,
                        first.odometer_km,
                        converted=odometer_converted,
                        last_id_before_import=matcher.last_id(ServiceVisit),
                    ),
                    *_visit_fee_key(first, header),
                    options=_VISIT_MATCH_LOADS,
                    same=lambda visit: _same_visit(
                        visit,
                        vendor_name=first.vendor_name,
                        check_vendor=carries_vendor,
                        items=_row_item_counts(group) if carries_description else None,
                    ),
                )
                is not None
            ):
                for _row in group:
                    import_result.add_skip()
                continue

            # A savepoint per visit, covering the vendor lookup/create, the
            # visit and its line items together: a CHECK or length violation
            # on any of them rolls the visit back alone instead of poisoning
            # the session for every visit and loop still to come.
            async with db.begin_nested():
                visit = await _write_service_csv_visit(db, vin, group)
        except _RowError as e:
            for row in group:
                import_result.add_error(row.row_num, e.reason)
            continue
        except Exception as e:
            # Intentional catch-all: one visit's failure should not stop the import
            logger.error(
                "Service import rows %s failed: %s",
                [r.row_num for r in group],
                sanitize_for_log(e),
            )
            for row in group:
                import_result.add_error(
                    row.row_num, _unexpected_reason(e, "Invalid service record data")
                )
            continue
        for _row in group:
            import_result.add_success()
        readings.add(
            "service_visit",
            visit.id,
            visit.date,
            odometer_km=visit.odometer_km,
            engine_hours=visit.engine_hours,
        )

    await readings.apply(db, vin, claim=False)
    await db.commit()
    # Imported services may be the newest of a rule's type: reconcile once per
    # upload (own lock, own commit), never per row.
    await maintenance_service.reconcile_vehicle(db, vin)
    await invalidate_cache_for_vehicle(vin)

    return import_result.to_dict()


@router.post("/vehicles/{vin}/fuel/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_fuel_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import fuel records from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # No DEF fill-level column is parsed from fuel CSV rows today, so there
    # is nothing to gate here yet. If one is ever added, gate it the same
    # way as the JSON fuel-record routes: call ensure_def_capable(vehicle)
    # before writing a DEF observation for a non-diesel vehicle.

    # Validate and parse CSV, then settle the file's units once, before any
    # ORM write (see `app.utils.csv_units`).
    csv_data = await validate_csv_upload(file)
    rows, units = _read_csv_with_units(
        csv_data,
        (
            ODOMETER_DISTANCE,
            FUEL_VOLUME,
            FUEL_PRICE,
            FUEL_TEMPERATURE,
            FUEL_CONSUMPTION,
            FUEL_SPEED,
            FUEL_PROPANE_VOLUME,
            FUEL_TANK_SIZE,
        ),
    )

    await lock_vehicle_for_write(db, vin)
    # Taken before the first write; see `_converted_value_matches` for why.
    odometer_converted = units.converts(DISTANCE)
    has_volume = units.column(VOLUME) is not None
    # v8 is the first fuel CSV to write a 0 L fill-up as 0, not a blank cell.
    zero_was_blank = _zero_was_blank(units.version, 8)
    matcher = await _DuplicateMatcher.before_import(db, FuelRecord)
    readings = _ImportReadings()

    import_result = ImportResult()

    for row_num, row in enumerate(rows, start=2):
        try:
            # Parse required fields
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            # Every unit-bearing column, converted into canonical metric
            # storage under the file's own units. v6 spells them
            # `Odometer (mi)` / `Volume (gal_uk)` / `Price Per Unit (gal_us)`;
            # v3-v5 spell them `Odometer (km)` / `Liters` / `Price Per Liter`;
            # v2 spells them `Mileage` / `Gallons` / `Price Per Gallon` and
            # means imperial (the ORM columns are metric, so storing miles
            # into odometer_km would lose ~38% of the distance).
            odometer_km = _canonical_cell(units, row, DISTANCE)
            liters = _canonical_cell(units, row, VOLUME)
            # v8's propane, tank and kWh columns (B3-3). The price is read after
            # them, since what it's per can depend on which of them the row has.
            propane_liters = _canonical_cell(units, row, PROPANE_VOLUME)
            tank_size_kg = _canonical_cell(units, row, MASS)
            tank_quantity = parse_int(row.get("Tank Quantity") or "")
            kwh = parse_decimal(row.get("kWh") or "")
            price_per_unit, price_basis = _csv_fuel_price(
                units, row, liters=liters, propane_liters=propane_liters, kwh=kwh
            )
            # Temperature, consumption and speed have been EXPORTED since v4
            # and were dropped on the way back in until #152 phase 2b, so a
            # fuel CSV could not round-trip them at all.
            outside_temp_c = _canonical_cell(units, row, TEMPERATURE)
            obc_l_per_100km = _canonical_cell(units, row, CONSUMPTION)
            obc_avg_speed_kmh = _canonical_cell(units, row, SPEED)

            # Engine-hours: hour-metered vehicles (ATVs, side-by-sides,
            # equipment). Dimensionless — no unit conversion, never present
            # in legacy v2 CSVs.
            engine_hours = parse_decimal(row.get("Engine Hours", ""))

            cost = parse_decimal(row.get("Total Cost", "") or row.get("Cost", ""))
            rebate = parse_decimal(row.get("Rebate", ""))
            is_full_tank = parse_bool(row.get("Full Tank", "True"))
            missed_fillup = parse_bool(row.get("Missed Fill-up", "False"))
            notes = row.get("Notes", "").strip() or None

            # Fuel type — surfaced by issue #69. rc1's importer dropped this
            # column entirely. Now: read it and route through the locale-aware
            # normalizer (so Polish "Benzyna" → gasoline, etc.) into the
            # canonical `fuel_type_used` enum. Unrecognized values fall through
            # to FuelTypeEnum.OTHER (a warning is logged) — we never silently
            # drop the row over fuel-type alone.
            #
            # "Fuel Type Used" is the v5 column; "Fuel Type" is what v4-and-older
            # exports (and every third-party sheet) call it, so both are read.
            raw_fuel_type = (
                (row.get("Fuel Type Used", "") or "").strip()
                or (row.get("Fuel Type", "") or "").strip()
                or None
            )
            normalized_fuel_type: FuelTypeEnum | None = normalize_fuel_type(raw_fuel_type)
            if raw_fuel_type and normalized_fuel_type is None:
                logger.warning(
                    "Fuel import row %d: unrecognized fuel type %r → 'other'",
                    row_num,
                    raw_fuel_type,
                )
                normalized_fuel_type = FuelTypeEnum.OTHER

            # #164 — octane + diesel grade (v7 columns; absent/blank = NULL).
            # The constructor below bypasses Pydantic, so the shared schema
            # validators run here: an invalid value fails this ROW through
            # the per-row error handler, never silently persisted (R1-M2).
            raw_octane = (row.get("Octane", "") or "").strip()
            octane = _validate_octane(int(raw_octane)) if raw_octane else None
            raw_grade = (row.get("Diesel Grade", "") or "").strip()
            diesel_grade = _validate_diesel_grade(raw_grade) if raw_grade else None

            # The fourteen columns the export has written since v4 and this
            # importer dropped (G3a-68). A short row's missing cell is None in
            # DictReader, hence `or ""` on every text read.
            filled_at = _local_datetime(row.get("Filled At"), "Filled At")
            is_hauling = parse_bool(row.get("Is Hauling", "False"))
            station_id = parse_int(row.get("Station ID", ""))
            station_cell = (row.get("Station") or "").strip() or None
            driver_id = parse_int(row.get("Driver ID", ""))
            driver_cell = (row.get("Driver") or "").strip() or None
            payment_method = _in_vocabulary(
                _blank_to_none((row.get("Payment Method") or "").strip()),
                "payment_method",
                PAYMENT_METHOD_VALUES,
            )
            trip_type = _in_vocabulary(
                _blank_to_none((row.get("Trip Type") or "").strip()), "trip_type", TRIP_TYPE_VALUES
            )
            obc_trip_duration_s = _trip_seconds(
                row.get("OBC Trip Duration (s)", ""), "OBC Trip Duration (s)"
            )
            soc_start_pct = parse_decimal(row.get("SOC Start (%)", ""))
            soc_end_pct = parse_decimal(row.get("SOC End (%)", ""))
            battery_soh_pct = parse_decimal(row.get("Battery SOH (%)", ""))
            charge_level = _in_vocabulary(
                _blank_to_none((row.get("Charge Level") or "").strip()),
                "charge_level",
                CHARGE_LEVEL_VALUES,
            )
            charge_location = _in_vocabulary(
                _blank_to_none((row.get("Charge Location") or "").strip()),
                "charge_location",
                CHARGE_LOCATION_VALUES,
            )
            # After every read, so each figure it names has been read (R1-F1).
            _within_api_bounds(
                FuelRecordCreate,
                odometer_km=odometer_km,
                engine_hours=engine_hours,
                liters=liters,
                propane_liters=propane_liters,
                tank_size_kg=tank_size_kg,
                tank_quantity=tank_quantity,
                kwh=kwh,
                price_per_unit=price_per_unit,
                cost=cost,
                rebate=rebate,
                outside_temp_c=outside_temp_c,
                obc_l_per_100km=obc_l_per_100km,
                obc_avg_speed_kmh=obc_avg_speed_kmh,
                soc_start_pct=soc_start_pct,
                soc_end_pct=soc_end_pct,
                battery_soh_pct=battery_soh_pct,
                obc_trip_duration_s=obc_trip_duration_s,
            )

            # R5's fuel key. A part is compared only when the file has its
            # column (T-16), so two same-day fill-ups at one odometer both
            # import (R1-H1).
            if skip_duplicates:
                key = [
                    FuelRecord.date == date,
                    _odometer_matches(
                        FuelRecord,
                        odometer_km,
                        converted=odometer_converted,
                        last_id_before_import=matcher.last_id(FuelRecord),
                    ),
                ]
                if "Filled At" in row:
                    key.append(_matches(FuelRecord.filled_at, filled_at))
                if has_volume:
                    key.append(
                        _or_blank_zero(
                            _converted_value_matches(
                                FuelRecord.liters,
                                liters,
                                LITRE_STEP,
                                converted=units.converts(VOLUME),
                                stored_before_import=FuelRecord.id <= matcher.last_id(FuelRecord),
                            ),
                            FuelRecord.liters,
                            liters,
                            zero_was_blank=zero_was_blank,
                        )
                    )
                if units.column(PROPANE_VOLUME):
                    key.append(_same_figure(FuelRecord.propane_liters, propane_liters))
                if units.column(MASS):
                    key.append(_same_figure(FuelRecord.tank_size_kg, tank_size_kg))
                if "Tank Quantity" in row:
                    key.append(_matches(FuelRecord.tank_quantity, tank_quantity))
                if "kWh" in row:
                    key.append(_same_figure(FuelRecord.kwh, kwh))
                if "Total Cost" in row or "Cost" in row:
                    key.append(_money_matches(FuelRecord.cost, cost))
                if await matcher.take(db, FuelRecord, FuelRecord.vin == vin, *key) is not None:
                    import_result.add_skip()
                    continue

            # With a Driver ID the Driver cell is the linked user's username (T-5).
            station_id, station_text, station_dropped = await _portable_station(
                db, station_id, station_cell
            )
            driver_id, driver_text, driver_dropped = await _portable_driver(
                db,
                driver_id,
                username=driver_cell if driver_id is not None else None,
                freetext=None if driver_id is not None else driver_cell,
            )

            # Create record
            record = FuelRecord(
                vin=vin,
                date=date,
                odometer_km=odometer_km,
                engine_hours=engine_hours,
                liters=liters,
                propane_liters=propane_liters,
                tank_size_kg=tank_size_kg,
                tank_quantity=tank_quantity,
                kwh=kwh,
                price_per_unit=price_per_unit,
                price_basis=price_basis,
                cost=cost,
                rebate=rebate,
                is_full_tank=is_full_tank,
                missed_fillup=missed_fillup,
                notes=notes,
                fuel_type_used=(
                    normalized_fuel_type.value if normalized_fuel_type is not None else None
                ),
                octane=octane,
                diesel_grade=diesel_grade,
                outside_temp_c=outside_temp_c,
                obc_l_per_100km=obc_l_per_100km,
                obc_avg_speed_kmh=obc_avg_speed_kmh,
                filled_at=filled_at,
                is_hauling=is_hauling,
                station_address_book_id=station_id,
                station_name_freetext=station_text,
                driver_user_id=driver_id,
                driver_name_freetext=driver_text,
                payment_method=payment_method,
                trip_type=trip_type,
                obc_trip_duration_s=obc_trip_duration_s,
                soc_start_pct=soc_start_pct,
                soc_end_pct=soc_end_pct,
                charge_level=charge_level,
                charge_location=charge_location,
                battery_soh_pct=battery_soh_pct,
            )
            # A savepoint per row, flushed inside it so the end-of-import sync
            # has the record's id, and a row the database rejects rolls back
            # alone instead of failing the whole upload at the final commit.
            async with db.begin_nested():
                db.add(record)
                await db.flush()
            readings.add(
                "fuel",
                record.id,
                record.date,
                odometer_km=record.odometer_km,
                engine_hours=record.engine_hours,
            )
            import_result.add_success()
            if station_dropped:
                import_result.add_warning(row_num, _STATION_KEPT_AS_TEXT)
            if driver_dropped:
                import_result.add_warning(row_num, _DRIVER_KEPT_AS_TEXT)

        except _RowError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Fuel import row %d failed: %s", row_num, sanitize_for_log(e))
            import_result.add_error(row_num, _unexpected_reason(e, "Invalid fuel record data"))

    await readings.apply(db, vin, claim=False)
    await db.commit()
    await invalidate_cache_for_vehicle(vin)

    return import_result.to_dict()


@router.post("/vehicles/{vin}/def/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_def_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import DEF records from CSV file."""
    vehicle = await get_vehicle_or_403(vin, current_user, db, require_write=True)
    # Same rule as the interactive create/update routes (Task 5): a fresh
    # CSV import is a new write, not a backup restore, so it is gated.
    ensure_def_capable(vehicle)

    csv_data = await validate_csv_upload(file)
    rows, units = _read_csv_with_units(csv_data, (ODOMETER_DISTANCE, FUEL_VOLUME, DEF_PRICE))

    await lock_vehicle_for_write(db, vin)
    # Taken before the first write; see `_converted_value_matches` for why.
    odometer_converted = units.converts(DISTANCE)
    has_volume = units.column(VOLUME) is not None
    # v8 is the first DEF CSV to write 0 L and a 0.00 fill level as 0, not blank.
    zero_was_blank = _zero_was_blank(units.version, 8)
    matcher = await _DuplicateMatcher.before_import(db, DEFRecord)
    readings = _ImportReadings()

    import_result = ImportResult()

    for row_num, row in enumerate(rows, start=2):
        try:
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            # v6 spells these `Odometer (mi)` / `Volume (gal_uk)` /
            # `Price Per Unit (gal_us)`; v3-v5 `Odometer (km)` / `Liters` /
            # `Price Per Unit`; v2 `Mileage` / `Gallons` in imperial. DEF's
            # price column keeps its name across all of them because that
            # name is the only key this importer has ever read.
            odometer_km = _canonical_cell(units, row, DISTANCE)
            liters = _canonical_cell(units, row, VOLUME)
            price_per_unit = _canonical_cell(units, row, PRICE_PER_VOLUME)
            cost = parse_decimal(row.get("Total Cost", "") or row.get("Cost", ""))
            fill_level = parse_decimal(row.get("Fill Level", ""))
            _within_api_bounds(
                DEFRecordCreate,
                odometer_km=odometer_km,
                liters=liters,
                price_per_unit=price_per_unit,
                cost=cost,
                fill_level=fill_level,
            )
            source = row.get("Source", "").strip() or None
            brand = row.get("Brand", "").strip() or None
            notes = row.get("Notes", "").strip() or None

            # R5's DEF key, each part only when the file has its column (T-16).
            # The CSV has no entry type.
            if skip_duplicates:
                key = [
                    DEFRecord.date == date,
                    _odometer_matches(
                        DEFRecord,
                        odometer_km,
                        converted=odometer_converted,
                        last_id_before_import=matcher.last_id(DEFRecord),
                    ),
                ]
                if has_volume:
                    key.append(
                        _or_blank_zero(
                            _converted_value_matches(
                                DEFRecord.liters,
                                liters,
                                LITRE_STEP,
                                converted=units.converts(VOLUME),
                                stored_before_import=DEFRecord.id <= matcher.last_id(DEFRecord),
                            ),
                            DEFRecord.liters,
                            liters,
                            zero_was_blank=zero_was_blank,
                        )
                    )
                if "Total Cost" in row or "Cost" in row:
                    key.append(_money_matches(DEFRecord.cost, cost))
                if "Fill Level" in row:
                    # NUMERIC(3,2).
                    key.append(
                        _or_blank_zero(
                            _same_figure(DEFRecord.fill_level, fill_level),
                            DEFRecord.fill_level,
                            fill_level,
                            zero_was_blank=zero_was_blank,
                        )
                    )
                if await matcher.take(db, DEFRecord, DEFRecord.vin == vin, *key) is not None:
                    import_result.add_skip()
                    continue

            record = DEFRecord(
                vin=vin,
                date=date,
                odometer_km=odometer_km,
                liters=liters,
                price_per_unit=price_per_unit,
                cost=cost,
                fill_level=fill_level,
                source=source,
                brand=brand,
                notes=notes,
            )
            # A savepoint per row, flushed inside it so the end-of-import sync
            # has the record's id, and a row the database rejects rolls back
            # alone instead of failing the whole upload at the final commit.
            async with db.begin_nested():
                db.add(record)
                await db.flush()
            readings.add("def", record.id, record.date, odometer_km=record.odometer_km)
            import_result.add_success()

        except _ImportBoundError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("DEF import row %d failed: %s", row_num, sanitize_for_log(e))
            import_result.add_error(row_num, _unexpected_reason(e, "Invalid DEF record data"))

    await readings.apply(db, vin, claim=False)
    await db.commit()
    await invalidate_cache_for_vehicle(vin)

    return import_result.to_dict()


@router.post("/vehicles/{vin}/odometer/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_odometer_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import odometer records from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Validate and parse CSV, then settle the file's units once, before any
    # ORM write (see `app.utils.csv_units`).
    csv_data = await validate_csv_upload(file)
    rows, units = _read_csv_with_units(csv_data, (READING_DISTANCE,))

    await lock_vehicle_for_write(db, vin)
    # Taken before the first write; see `_converted_value_matches` for why.
    odometer_converted = units.converts(DISTANCE)
    matcher = await _DuplicateMatcher.before_import(db, OdometerRecord)

    import_result = ImportResult()

    for row_num, row in enumerate(rows, start=2):
        try:
            # Parse required fields
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            # v6 spells this `Reading (mi)`; v3-v5 `Reading (km)` (or
            # `Mileage`); a bare `Reading` with no marker and no version is
            # the v2 standalone odometer export, which held MILES.
            odometer_km = _canonical_cell(units, row, DISTANCE)
            if odometer_km is None:
                import_result.add_error(row_num, "Reading is required")
                continue
            _within_api_bounds(OdometerRecordCreate, odometer_km=odometer_km)

            # A copied sync marker would make the reading look owned (R4, N-2).
            notes = _without_sync_marker(row.get("Notes", "").strip() or None)

            # Check for duplicates if requested
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    OdometerRecord,
                    OdometerRecord.vin == vin,
                    OdometerRecord.date == date,
                    _odometer_matches(
                        OdometerRecord,
                        odometer_km,
                        converted=odometer_converted,
                        last_id_before_import=matcher.last_id(OdometerRecord),
                    ),
                )
                is not None
            ):
                import_result.add_skip()
                continue

            # Create record
            record = OdometerRecord(vin=vin, date=date, odometer_km=odometer_km, notes=notes)
            # A savepoint per row. Without it the INSERT is only attempted at
            # the commit below, which is outside this handler: a CHECK
            # violation would escape the route as a 500 and discard every
            # valid row in the file along with the bad one.
            async with db.begin_nested():
                db.add(record)
            import_result.add_success()

        except _ImportBoundError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, sanitize_for_log(e))
            import_result.add_error(row_num, _unexpected_reason(e, "Invalid record data"))

    await db.commit()
    await invalidate_cache_for_vehicle(vin)

    return import_result.to_dict()


@router.post("/vehicles/{vin}/hours/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_hours_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import engine-hours records from CSV file.

    Mirrors :func:`import_odometer_csv` — the hours track's standalone
    history CSV for hour-metered vehicles. Registered under this router
    (``/api/import``), not the hours CRUD router (``/api/vehicles/{vin}/hours``),
    to avoid shadowing that router's ``GET/PUT/DELETE /{record_id}`` routes.

    Every imported row becomes a manual reading (``source='manual'``, both
    ``fuel_record_id``/``service_visit_id`` left null) regardless of what the
    exported "Source" column says — a CSV cannot carry a live foreign key to
    a fuel/service row in the *target* vehicle's tables, so re-establishing
    sync provenance on import would be fabricated.
    """
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader, _fields = _read_mygarage_csv(csv_data)

    await lock_vehicle_for_write(db, vin)
    matcher = await _DuplicateMatcher.before_import(db, HoursRecord)

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            # Parse required fields
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            # Dimensionless — no unit conversion, no legacy-v2 fallback (the
            # hours track didn't exist in v2/v3 exports).
            engine_hours = parse_decimal(row.get("Engine Hours", ""))
            if engine_hours is None:
                import_result.add_error(row_num, "Engine Hours is required")
                continue
            _within_api_bounds(HoursRecordCreate, engine_hours=engine_hours)

            # A copied sync marker would make the reading look owned (R4, N-2).
            notes = _without_sync_marker(row.get("Notes", "").strip() or None)

            # Check for duplicates if requested. NUMERIC(10,1); no source (T-19).
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    HoursRecord,
                    HoursRecord.vin == vin,
                    HoursRecord.date == date,
                    _same_figure(HoursRecord.engine_hours, engine_hours),
                )
                is not None
            ):
                import_result.add_skip()
                continue

            # Create record — always a manual reading (see docstring).
            record = HoursRecord(
                vin=vin,
                date=date,
                engine_hours=engine_hours,
                notes=notes,
                source="manual",
            )
            # A savepoint per row. Leaving it flushes the insert, so a row the
            # database rejects rolls back alone instead of failing the whole
            # upload at the final commit (production sessions do not autoflush).
            async with db.begin_nested():
                db.add(record)
            import_result.add_success()

        except _ImportBoundError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Hours import row %d failed: %s", row_num, sanitize_for_log(e))
            import_result.add_error(row_num, _unexpected_reason(e, "Invalid hours record data"))

    await db.commit()
    await invalidate_cache_for_vehicle(vin)

    return import_result.to_dict()


@router.post("/vehicles/{vin}/warranties/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_warranties_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import warranties from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Validate and parse CSV. Read through the unit machinery rather than a
    # bare DictReader: `Mileage Limit` is unit-bearing, so the file's own
    # marker decides whether the number is km or miles. A plain reader cannot
    # see a tokenised header at all, and would silently store miles as km.
    csv_data = await validate_csv_upload(file)
    rows, units = _read_csv_with_units(csv_data, (MILEAGE_LIMIT_DISTANCE,))

    await lock_vehicle_for_write(db, vin)
    matcher = await _DuplicateMatcher.before_import(db, WarrantyRecord)
    has_mileage_limit = units.column(DISTANCE) is not None

    import_result = ImportResult()

    for row_num, row in enumerate(rows, start=2):
        try:
            provider = row.get("Provider", "").strip() or None
            warranty_type = row.get("Type", "").strip() or None
            # `Coverage` is the pre-v3.3.0 spelling. Both are read so a file
            # exported before this release still imports rather than coming
            # back 200 with every row blamed on the user's file.
            coverage_details = (
                row.get("Coverage Details", "") or row.get("Coverage", "")
            ).strip() or None
            policy_number = row.get("Policy Number", "").strip() or None
            start_date = parse_date(row.get("Start Date", ""))
            end_date = parse_date(row.get("End Date", ""))
            mileage_limit_km = _canonical_cell(units, row, DISTANCE)
            _within_api_bounds(WarrantyRecordCreate, mileage_limit_km=mileage_limit_km)
            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested. A key part is compared only
            # when the file has its column (T-16): DictReader gives every row
            # each header key, so `in row` is a header check.
            if skip_duplicates and start_date and warranty_type:
                key = [
                    WarrantyRecord.warranty_type == warranty_type,
                    _text_matches(WarrantyRecord.provider, provider),
                    WarrantyRecord.start_date == start_date,
                ]
                if "End Date" in row:
                    key.append(_matches(WarrantyRecord.end_date, end_date))
                if "Policy Number" in row:
                    key.append(_text_matches(WarrantyRecord.policy_number, policy_number))
                if has_mileage_limit:
                    key.append(
                        _converted_value_matches(
                            WarrantyRecord.mileage_limit_km,
                            mileage_limit_km,
                            KM_STEP,
                            converted=units.converts(DISTANCE),
                            stored_before_import=(
                                WarrantyRecord.id <= matcher.last_id(WarrantyRecord)
                            ),
                        )
                    )
                if (
                    await matcher.take(db, WarrantyRecord, WarrantyRecord.vin == vin, *key)
                    is not None
                ):
                    import_result.add_skip()
                    continue

            # Create record
            record = WarrantyRecord(
                vin=vin,
                provider=provider,
                warranty_type=warranty_type,
                policy_number=policy_number,
                coverage_details=coverage_details,
                start_date=start_date,
                end_date=end_date,
                mileage_limit_km=mileage_limit_km,
                notes=notes,
            )
            # A savepoint per row. Without it the INSERT is only attempted at
            # the commit below, which is outside this handler: a CHECK
            # violation would escape the route as a 500 and discard every
            # valid row in the file along with the bad one.
            async with db.begin_nested():
                db.add(record)
            import_result.add_success()

        except _ImportBoundError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, sanitize_for_log(e))
            import_result.add_error(row_num, _unexpected_reason(e, "Invalid record data"))

    await db.commit()
    await invalidate_cache_for_vehicle(vin)

    return import_result.to_dict()


@router.post("/vehicles/{vin}/insurance/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_insurance_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import insurance records from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader, _fields = _read_mygarage_csv(csv_data)

    await lock_vehicle_for_write(db, vin)

    import_result = ImportResult()

    access = await InsuranceService(db).access_for(current_user)

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            record = {
                "provider": row.get("Provider", ""),
                "policy_number": row.get("Policy Number", ""),
                "policy_type": row.get("Type", "").strip() or None,
                "start_date": parse_date(row.get("Start Date", "")),
                "end_date": parse_date(row.get("End Date", "")),
                "premium": parse_decimal(row.get("Premium", "")),
                "premium_frequency": row.get("Premium Frequency", "").strip() or None,
                "deductible": parse_decimal(row.get("Deductible", "")),
                "notes": row.get("Notes", "").strip() or None,
            }
            # The flat file has one Coverage Limits column: converted whole,
            # the way migration 108 converts the column it replaced.
            _merge_converted(record, row.get("Coverage Limits", "").strip() or None)
            imported = await _import_insurance_row(
                db,
                access,
                vin,
                record,
                skip_duplicates,
            )
            if imported:
                import_result.add_success()
            else:
                import_result.add_skip()
        except (_InsuranceRowError, _ImportBoundError) as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, sanitize_for_log(e))
            import_result.add_error(row_num, _unexpected_reason(e, "Invalid record data"))

    await db.commit()
    await invalidate_cache_for_vehicle(vin)

    return import_result.to_dict()


@router.post("/vehicles/{vin}/tax/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_tax_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import tax records from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader, _fields = _read_mygarage_csv(csv_data)

    await lock_vehicle_for_write(db, vin)
    matcher = await _DuplicateMatcher.before_import(db, TaxRecord)

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            # TaxRecord has `date`, `tax_type`, `amount`, `renewal_date`,
            # `notes`. This importer previously read `Year`, `Paid Date`,
            # `Due Date` and `Jurisdiction` and constructed with four
            # attributes the model does not have, so no tax record has ever
            # imported. The export writes `Date` and `Renewal Date`; the two
            # halves now share one vocabulary.
            record_date = parse_date(row.get("Date", "")) or parse_date(row.get("Paid Date", ""))
            tax_type = row.get("Type", "").strip() or None
            amount = parse_decimal(row.get("Amount", ""))
            _within_api_bounds(TaxRecordCreate, amount=amount)
            renewal_date = parse_date(row.get("Renewal Date", "")) or parse_date(
                row.get("Due Date", "")
            )
            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested. A key part is compared only
            # when the file has its column (T-16): DictReader gives every row
            # each header key, so `in row` is a header check.
            if skip_duplicates and record_date:
                key = [TaxRecord.date == record_date, _matches(TaxRecord.tax_type, tax_type)]
                if "Amount" in row:
                    key.append(_money_matches(TaxRecord.amount, amount))
                if "Renewal Date" in row or "Due Date" in row:
                    key.append(_matches(TaxRecord.renewal_date, renewal_date))
                if await matcher.take(db, TaxRecord, TaxRecord.vin == vin, *key) is not None:
                    import_result.add_skip()
                    continue

            # Create record
            record = TaxRecord(
                vin=vin,
                date=record_date,
                tax_type=tax_type,
                amount=amount,
                renewal_date=renewal_date,
                notes=notes,
            )
            # A savepoint per row. Without it the INSERT is only attempted at
            # the commit below, which is outside this handler: a CHECK
            # violation would escape the route as a 500 and discard every
            # valid row in the file along with the bad one.
            async with db.begin_nested():
                db.add(record)
            import_result.add_success()

        except _ImportBoundError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, sanitize_for_log(e))
            import_result.add_error(row_num, _unexpected_reason(e, "Invalid record data"))

    await db.commit()
    await invalidate_cache_for_vehicle(vin)

    return import_result.to_dict()


@router.post("/vehicles/{vin}/notes/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_notes_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import notes from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader, _fields = _read_mygarage_csv(csv_data)

    await lock_vehicle_for_write(db, vin)
    matcher = await _DuplicateMatcher.before_import(db, Note)

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            date = parse_date(row.get("Date", ""))
            title = row.get("Title", "").strip() or None
            content = row.get("Content", "").strip() or None

            # Check for duplicates if requested. A key part is compared only
            # when the file has its column (T-16): DictReader gives every row
            # each header key, so `in row` is a header check.
            if skip_duplicates and date:
                key = [Note.date == date]
                if "Title" in row:
                    key.append(_text_matches(Note.title, title))
                if "Content" in row:
                    key.append(_matches(Note.content, content))
                if await matcher.take(db, Note, Note.vin == vin, *key) is not None:
                    import_result.add_skip()
                    continue

            # Create record
            record = Note(vin=vin, date=date, title=title, content=content)
            # A savepoint per row. Without it the INSERT is only attempted at
            # the commit below, which is outside this handler: a CHECK
            # violation would escape the route as a 500 and discard every
            # valid row in the file along with the bad one.
            async with db.begin_nested():
                db.add(record)
            import_result.add_success()

        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, sanitize_for_log(e))
            import_result.add_error(row_num, _unexpected_reason(e, "Invalid record data"))

    await db.commit()
    await invalidate_cache_for_vehicle(vin)

    return import_result.to_dict()
