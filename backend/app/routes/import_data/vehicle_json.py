"""The vehicle JSON backup import."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import json
import logging
from collections.abc import Mapping
from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import (
    DEFRecord,
    FinancingRecord,
    FuelRecord,
    HoursRecord,
    Note,
    OdometerRecord,
    Reminder,
    ServiceLineItem,
    ServiceVisit,
    SpotRental,
    TaxRecord,
    TollTag,
    TollTransaction,
    WarrantyRecord,
)
from app.models.recall import Recall
from app.models.supply import Supply, SupplyUsage
from app.models.user import User
from app.models.vehicle_dtc import VehicleDTC
from app.routes.import_data._common import (
    _SERVICE_CATEGORIES,
    VALID_SERVICE_CATEGORIES,
    _blank_to_none,
    _ImportBoundError,
    _in_vocabulary,
    _InsuranceRowError,
    _is_blank,
    _json_decimal,
    _json_first_decimal,
    _json_int,
    _json_row_date,
    _json_row_datetime,
    _json_text,
    _RowError,
    _unexpected_reason,
    _within_api_bounds,
    limiter,
    router,
)
from app.routes.import_data._families import run_family
from app.routes.import_data._fuel import (
    _DRIVER_KEPT_AS_TEXT,
    _STATION_KEPT_AS_TEXT,
    _def_record_from_json,
    _fuel_record_from_json,
    _json_def_key,
    _json_fuel_key,
    _portable_driver,
    _portable_station,
    _same_fuel_type,
)
from app.routes.import_data._insurance import (
    _coverages_from_rows,
    _import_insurance_row,
    _merge_converted,
)
from app.routes.import_data._matching import (
    _COLUMN_SCALE,
    _at_scale,
    _column_step,
    _DuplicateMatcher,
    _matches,
    _money_matches,
    _odometer_matches,
    _same_figure,
    _text_matches,
    _zero_was_blank,
)
from app.routes.import_data._readings import (
    _ImportReadings,
    _portable_odometer_source,
    _without_sync_marker,
)
from app.routes.import_data._records import (
    _BILL_AMOUNTS,
    _bill_counts,
    _financing_record_from_json,
    _json_financing_key,
    _json_spot_rental_key,
    _json_tax_key,
    _json_toll_transaction_key,
    _json_warranty_key,
    _spot_rental_from_json,
    _tax_record_from_json,
    _toll_system_name,
    _toll_tag_from_json,
    _toll_tag_key,
    _toll_transaction_from_json,
    _warranty_from_json,
)
from app.routes.import_data._service import (
    _ITEM_KEY_FIELDS,
    _VISIT_MATCH_LOADS,
    _item_counts,
    _item_key_value,
    _line_item_from_json,
    _same_visit,
    _vendor_id_for,
    _visit_total,
)
from app.routes.import_data.json_brakes import parse_brakes, write_brakes
from app.routes.import_data.json_dtcs import import_dtcs
from app.routes.import_data.json_recalls import import_recalls
from app.routes.import_data.json_schedule import (
    manual_reminder_key,
    parse_rules,
    reminder_from_json,
    write_rules,
)
from app.routes.import_data.json_supplies import (
    SupplyResolver,
    line_item_usage_counts,
    line_item_usages_from_json,
    parse_supplies,
    write_supplies,
)
from app.routes.import_data.json_tires import (
    parse_tires,
    sync_imported_tires,
    write_tires,
)
from app.schemas.hours import HoursRecordCreate
from app.schemas.odometer import OdometerRecordCreate
from app.schemas.reminder import ReminderCreate
from app.schemas.service_visit import (
    ServiceLineItemCreate,
    ServiceVisitCreate,
)
from app.services import maintenance_service
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.brake_service import BrakeService
from app.services.fuel_side_effects import invalidate_cache_for_vehicle
from app.services.insurance_service import InsuranceService
from app.services.reminder_service import start_readings
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.csv_units import (
    DISTANCE,
    PRICE_PER_VOLUME,
    VOLUME,
)
from app.utils.household_time import household_date, household_today
from app.utils.logging_utils import sanitize_for_log
from app.utils.maintenance_types import classify
from app.utils.units import UnitConverter

logger = logging.getLogger(__name__)


#: The top-level lists a vehicle JSON backup may carry. The route's order is S7's, not this tuple's.
_JSON_IMPORT_SECTIONS = (
    "service_records",
    "service_visits",
    "fuel_records",
    "def_records",
    "odometer_records",
    "hours_records",
    "reminders",
    "notes",
    "insurance_policies",
    "financing_records",
    "tax_records",
    "toll_tags",
    "toll_transactions",
    "warranties",
    "spot_rentals",
    "maintenance_rules",
    "tire_sets",
    "tires",
    "brake_axles",
    "brake_jobs",
    "brake_measurements",
    "supplies",
    "manual_reminders",
    "recalls",
    "dtcs",
)

#: The response's buckets, one per section it counts, in the order the import
#: runs them. The frontend's SECTIONS (utils/importSummary.ts) copies this order.
_JSON_RESULT_BUCKETS = (
    "supplies",
    "service_records",
    "fuel_records",
    "def_records",
    "odometer_records",
    "hours_records",
    "reminders",
    "notes",
    "insurance_policies",
    "financing_records",
    "tax_records",
    "toll_tags",
    "toll_transactions",
    "warranties",
    "spot_rentals",
    "maintenance_rules",
    "recalls",
    "dtcs",
    "tire_sets",
    "tires",
    "brake_axles",
    "brake_jobs",
    "brake_measurements",
)


@router.post("/vehicles/{vin}/json")
@limiter.limit(settings.rate_limit_uploads)
async def import_vehicle_json(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import a vehicle's records from a JSON export."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Check file size BEFORE reading into memory to prevent DoS
    max_import_size = 50 * 1024 * 1024  # 50MB max for import files
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Seek back to beginning

    if file_size > max_import_size:
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds maximum of {max_import_size // (1024 * 1024)}MB",
        )

    # Now read and parse JSON
    contents = await file.read()
    try:
        data = json.loads(contents.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

    # Every section is settled here, before the lock and before any write. A
    # missing or null section is empty; anything else that is not a list
    # refuses the whole file, instead of raising halfway through the loops
    # below with the sections before it already written.
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="The import file must be a JSON object")
    backup = cast(dict[str, Any], data)
    sections: dict[str, list[Any]] = {}
    for section in _JSON_IMPORT_SECTIONS:
        value = backup.get(section)
        if value is None:
            sections[section] = []
        elif isinstance(value, list):
            sections[section] = cast(list[Any], value)
        else:
            raise HTTPException(status_code=400, detail=f"{section} must be a list of records")

    # Detect schema version. v3+ exports include `"export_version": "3"` and
    # `"units": "metric"`. Pre-v3 backups omit both — treat as legacy v2 and
    # convert imperial values to metric on ingest.
    export_version = str(backup.get("export_version") or "").strip()
    units = str(backup.get("units") or "").strip().lower()
    is_legacy_v2 = export_version != "3" and units != "metric"
    # v9 is the first JSON export to write a 0 L fill-up and a 0.00 fill level as 0.
    zero_was_null = _zero_was_blank(export_version, 9)
    if is_legacy_v2:
        logger.warning(
            "JSON import for vin=%s detected legacy v2 backup (no export_version "
            "marker); converting imperial values to metric on ingest.",
            sanitize_for_log(vin),
        )

    # A legacy figure is converted, so it is rounded to its column's scale
    # (R7, T-10); a v3+ figure is canonical already and is left as given.
    # Each takes the figure read by `_json_decimal`, so a word or a true is a
    # row error that names its field (F-4).
    def _maybe_mi_to_km(d: Decimal | None) -> Decimal | None:
        # Infinity and NaN pass for the bounds check to name. An sNaN isn't
        # finite either, so it passes too: multiplying it below would raise.
        if d is None or not is_legacy_v2 or not d.is_finite():
            return d
        return _at_scale(d * UnitConverter.MILES_TO_KM, _COLUMN_SCALE[DISTANCE])

    def _maybe_gal_to_l(d: Decimal | None) -> Decimal | None:
        if d is None or not is_legacy_v2 or not d.is_finite():
            return d
        return _at_scale(d * UnitConverter.US_GALLONS_TO_LITERS, _COLUMN_SCALE[VOLUME])

    def _maybe_per_gal_to_per_l(d: Decimal | None) -> Decimal | None:
        if d is None or not is_legacy_v2 or not d.is_finite():
            return d
        return _at_scale(d / UnitConverter.US_GALLONS_TO_LITERS, _COLUMN_SCALE[PRICE_PER_VOLUME])

    await lock_vehicle_for_write(db, vin)
    # Taken before the first section writes: only a row at or below these can
    # carry the pre-v3.4.0 factors (see `_converted_value_matches`), and a v3
    # backup is canonical already, so only a legacy one was converted. The same
    # ceilings keep a row this import wrote from being a duplicate (R5).
    matcher = await _DuplicateMatcher.before_import(
        db,
        ServiceVisit,
        Supply,
        FuelRecord,
        DEFRecord,
        OdometerRecord,
        HoursRecord,
        FinancingRecord,
        TaxRecord,
        TollTag,
        TollTransaction,
        WarrantyRecord,
        SpotRental,
        Reminder,
        Note,
        Recall,
        VehicleDTC,
    )
    readings = _ImportReadings()

    errors: list[str] = []
    warnings: list[str] = []
    results: dict[str, Any] = {
        name: {"success": 0, "errors": 0, "skipped": 0} for name in _JSON_RESULT_BUCKETS
    } | {"errors": errors, "warnings": warnings}

    # Pinned supplies come first, whole or not at all and only into a vehicle
    # with none pinned, so a visit's usage can name one by its place in the file.
    user_id = current_user.id if current_user else None
    supplies = await run_family(
        db,
        vin,
        "supplies",
        sections,
        results,
        errors,
        warnings,
        parse=lambda: parse_supplies(vin, sections, user_id),
        write=lambda plan: write_supplies(db, plan, current_user),
    )
    if supplies.outcome == "written" and supplies.plan is not None:
        warnings.extend(supplies.plan.warnings)
    resolver = SupplyResolver(vin, sections["supplies"], user_id, supplies)

    # Import service records (creates ServiceVisit + ServiceLineItem + Vendor)
    for idx, record_data in enumerate(sections["service_records"]):
        try:
            date = _json_row_date(record_data)

            # Legacy v2 used "mileage" (miles); v3 uses "odometer_km" (km).
            imported_odometer_km = _maybe_mi_to_km(
                _json_first_decimal(record_data, "odometer_km", "mileage")
            )
            cost = _json_decimal(record_data, "cost")
            _within_api_bounds(ServiceVisitCreate, odometer_km=imported_odometer_km)
            _within_api_bounds(ServiceLineItemCreate, cost=cost)

            # T-18: a v<=8 entry carries the first item's description and the
            # visit total, which sums the items, tax and fees; so the total
            # stands in for them. v8 wrote no claim number.
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    ServiceVisit,
                    ServiceVisit.vin == vin,
                    ServiceVisit.date == date,
                    _odometer_matches(
                        ServiceVisit,
                        imported_odometer_km,
                        converted=is_legacy_v2,
                        last_id_before_import=matcher.last_id(ServiceVisit),
                    ),
                    *(
                        [_money_matches(ServiceVisit.total_cost, cost)]
                        if "cost" in record_data
                        else []
                    ),
                    options=_VISIT_MATCH_LOADS,
                    same=lambda visit: _same_visit(
                        visit,
                        vendor_name=record_data.get("vendor_name"),
                        check_vendor="vendor_name" in record_data,
                        items=None,
                    ),
                )
                is not None
            ):
                results["service_records"]["skipped"] += 1
                continue

            description = (
                record_data.get("service_type") or record_data.get("description") or "Service"
            )
            # Only a name IN VALID_SERVICE_CATEGORIES is accepted, the same
            # vocabulary the CSV importer matches against. Reported as this
            # row's error rather than left for the database's own CHECK
            # constraint to reject.
            raw_category = record_data.get("service_category")
            if raw_category and raw_category not in VALID_SERVICE_CATEGORIES:
                results["service_records"]["errors"] += 1
                errors.append(
                    f"Service record {idx}: service_category {raw_category!r} is not "
                    "a recognized category"
                )
                continue
            category = raw_category or "Maintenance"

            # A savepoint per row, covering the vendor lookup/create, the
            # visit and its line item together: a CHECK or length violation
            # on any of them rolls the whole row back alone instead of
            # poisoning the session for every row and loop still to come.
            async with db.begin_nested():
                visit = ServiceVisit(
                    vin=vin,
                    date=date,
                    odometer_km=imported_odometer_km,
                    service_category=category,
                    vendor_id=await _vendor_id_for(db, record_data.get("vendor_name")),
                    notes=record_data.get("notes"),
                    total_cost=cost if cost is not None else Decimal("0"),
                )
                db.add(visit)
                await db.flush()

                line_item = ServiceLineItem(
                    visit_id=visit.id,
                    description=description,
                    maintenance_type=classify(description),
                    cost=cost,
                )
                db.add(line_item)
            readings.add(
                "service_visit",
                visit.id,
                visit.date,
                odometer_km=visit.odometer_km,
                engine_hours=visit.engine_hours,
            )
            results["service_records"]["success"] += 1
        except _RowError as e:
            results["service_records"]["errors"] += 1
            errors.append(f"Service record {idx}: {e.reason}")
        except Exception as e:
            results["service_records"]["errors"] += 1
            logger.warning("Import: service record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Service record {idx}: {_unexpected_reason(e)}")

    # Import v9 service visits whole: the visit, its line items in order and
    # the inspection links between them. Counted with the v<=8 entries (T-4).
    for idx, visit_data in enumerate(sections["service_visits"]):
        try:
            date = _json_row_date(visit_data)
            odometer_km = _maybe_mi_to_km(_json_decimal(visit_data, "odometer_km"))
            engine_hours = _json_decimal(visit_data, "engine_hours")
            tax_amount = _json_decimal(visit_data, "tax_amount")
            shop_supplies = _json_decimal(visit_data, "shop_supplies")
            misc_fees = _json_decimal(visit_data, "misc_fees")
            _within_api_bounds(
                ServiceVisitCreate,
                odometer_km=odometer_km,
                engine_hours=engine_hours,
                tax_amount=tax_amount,
                shop_supplies=shop_supplies,
                misc_fees=misc_fees,
            )
            # The API allows a visit with no category, so None stays None.
            service_category = _in_vocabulary(
                _blank_to_none(visit_data.get("service_category")),
                "service_category",
                _SERVICE_CATEGORIES,
            )
            raw_items = visit_data.get("line_items")
            if not isinstance(raw_items, list):
                raise _RowError("line_items must be a list")
            line_items = cast(list[Any], raw_items)
            items = [
                _line_item_from_json(position, item, len(line_items))
                for position, item in enumerate(line_items)
            ]
            # Beside the item, not in it, so each reason names its usage.
            usages = [
                line_item_usages_from_json(position, item, sections["supplies"])
                for position, item in enumerate(line_items)
            ]
            # The supplies a visit used count toward its total (K12).
            total_cost = _visit_total(
                (columns["cost"] for columns, _link in items),
                tax_amount,
                shop_supplies,
                misc_fees,
                usage_costs=(u.cost_snapshot for item_usages in usages for u in item_usages),
            )
            # As given: the CSV and v8 imports make vendors with no length cap, and
            # _vendor_id_for matches the exact name, so a cut name would make a second.
            vendor_name = _json_text(visit_data, "vendor_name")
            insurance_claim_number = _json_text(visit_data, "insurance_claim_number")
            notes = _json_text(visit_data, "notes")

            # R5's service key. The visit's own amounts and claim number are in
            # it, so two visits that differ only there can't both match one
            # stored visit (Codex R2); each only when the entry has it (T-16).
            fee_key = [
                condition
                for key, condition in (
                    ("tax_amount", _money_matches(ServiceVisit.tax_amount, tax_amount)),
                    ("shop_supplies", _money_matches(ServiceVisit.shop_supplies, shop_supplies)),
                    ("misc_fees", _money_matches(ServiceVisit.misc_fees, misc_fees)),
                    (
                        "insurance_claim_number",
                        _text_matches(ServiceVisit.insurance_claim_number, insurance_claim_number),
                    ),
                    # C-5: the visit's own hours reading and category.
                    ("engine_hours", _same_figure(ServiceVisit.engine_hours, engine_hours)),
                    (
                        "service_category",
                        _matches(ServiceVisit.service_category, service_category),
                    ),
                )
                if key in visit_data  # T-16: a v9 export writes them all
            ]
            # The items' other fields, each only when every item has it (T-16).
            item_fields = tuple(
                f for f in _ITEM_KEY_FIELDS if all(f in item for item in line_items)
            )
            # What each item used, when every item says (T-16). A 3a file's
            # don't, so its visits keep the key they had (R1-H4).
            compare_usages = all("supply_usages" in item for item in line_items)
            usage_keys = (
                [
                    line_item_usage_counts(
                        position,
                        await resolver.stored_before(db, item_usages, matcher.last_id(Supply)),
                        sections["supplies"],
                    )
                    for position, item_usages in enumerate(usages)
                ]
                if skip_duplicates and compare_usages
                else []
            )
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    ServiceVisit,
                    ServiceVisit.vin == vin,
                    ServiceVisit.date == date,
                    _odometer_matches(
                        ServiceVisit,
                        odometer_km,
                        converted=is_legacy_v2,
                        last_id_before_import=matcher.last_id(ServiceVisit),
                    ),
                    *fee_key,
                    options=_VISIT_MATCH_LOADS,
                    same=lambda visit: _same_visit(
                        visit,
                        vendor_name=vendor_name,
                        check_vendor=True,
                        items=_item_counts(
                            (
                                columns["description"],
                                columns["cost"],
                                *(_item_key_value(f, columns[f]) for f in item_fields),
                                *([usage_keys[position]] if compare_usages else []),
                            )
                            for position, (columns, _link) in enumerate(items)
                        ),
                        item_fields=item_fields,
                        compare_usages=compare_usages,
                    ),
                )
                is not None
            ):
                results["service_records"]["skipped"] += 1
                continue

            # One savepoint for the visit, its items and their links, so a row
            # the database rejects rolls back whole and alone.
            async with db.begin_nested():
                visit = ServiceVisit(
                    vin=vin,
                    date=date,
                    odometer_km=odometer_km,
                    engine_hours=engine_hours,
                    service_category=service_category,
                    vendor_id=await _vendor_id_for(db, vendor_name),
                    tax_amount=tax_amount,
                    shop_supplies=shop_supplies,
                    misc_fees=misc_fees,
                    insurance_claim_number=insurance_claim_number,
                    notes=notes,
                    total_cost=total_cost,
                )
                db.add(visit)
                await db.flush()
                written = [
                    ServiceLineItem(visit_id=visit.id, **columns) for columns, _link in items
                ]
                db.add_all(written)
                await db.flush()
                # An item's link is an index into this visit's items, so it's
                # set once every item has its id.
                for line_item, (_columns, link) in zip(written, items, strict=True):
                    if link is not None:
                        line_item.triggered_by_inspection_id = written[link].id
                # What each item used, its supply found or added in this savepoint.
                for position, (line_item, item_usages) in enumerate(
                    zip(written, usages, strict=True)
                ):
                    for k, usage in enumerate(item_usages):
                        try:
                            supply_id = await resolver.resolve(db, usage.ref)
                        except _RowError as e:
                            raise _RowError(
                                f"line item {position}, supply usage {k}: {e.reason}"
                            ) from e
                        db.add(
                            SupplyUsage(
                                supply_id=supply_id,
                                service_line_item_id=line_item.id,
                                quantity=usage.quantity,
                                unit_cost_snapshot=usage.unit_cost_snapshot,
                                cost_snapshot=usage.cost_snapshot,
                            )
                        )
                await db.flush()
            # The savepoint held, so the supplies it added stay.
            warnings.extend(resolver.visit_done())
            readings.add(
                "service_visit",
                visit.id,
                visit.date,
                odometer_km=visit.odometer_km,
                engine_hours=visit.engine_hours,
            )
            results["service_records"]["success"] += 1
        except _RowError as e:
            resolver.visit_failed()
            results["service_records"]["errors"] += 1
            errors.append(f"Service visit {idx}: {e.reason}")
        except Exception as e:
            resolver.visit_failed()
            results["service_records"]["errors"] += 1
            logger.warning("Import: service visit %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Service visit {idx}: {_unexpected_reason(e)}")

    # Import fuel records. Every column the export writes is read back (R2); a
    # v<=8 row lacks the newer keys, which read as None or the model default.
    for idx, record_data in enumerate(sections["fuel_records"]):
        try:
            date = _json_row_date(record_data)
            # v3 uses "odometer_km"/"liters"; legacy v2 uses "mileage"/"gallons"
            # in imperial, converted by the helpers above. A 0 is a figure.
            record = _fuel_record_from_json(
                vin,
                date,
                record_data,
                idx=idx,
                odometer_km=_maybe_mi_to_km(
                    _json_first_decimal(record_data, "odometer_km", "mileage")
                ),
                liters=_maybe_gal_to_l(_json_first_decimal(record_data, "liters", "gallons")),
                price_per_unit=_maybe_per_gal_to_per_l(
                    _json_decimal(record_data, "price_per_unit")
                ),
            )
            # The links are checked against this instance after the duplicate
            # check; the station's name is the resolved one a v9 export writes.
            station_id = _json_int(record_data, "station_address_book_id")
            station_name = _json_text(record_data, "station_name") or _json_text(
                record_data, "station_name_freetext"
            )
            driver_id = _json_int(record_data, "driver_user_id")
            driver_username = _json_text(record_data, "driver_username")
            driver_freetext = _json_text(record_data, "driver_name_freetext")

            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    FuelRecord,
                    FuelRecord.vin == vin,
                    *_json_fuel_key(
                        record_data,
                        record,
                        converted=is_legacy_v2,
                        last_id=matcher.last_id(FuelRecord),
                        zero_was_null=zero_was_null,
                    ),
                    same=_same_fuel_type(record_data, record),
                )
                is not None
            ):
                results["fuel_records"]["skipped"] += 1
                continue

            (
                record.station_address_book_id,
                record.station_name_freetext,
                station_dropped,
            ) = await _portable_station(db, station_id, station_name)
            (
                record.driver_user_id,
                record.driver_name_freetext,
                driver_dropped,
            ) = await _portable_driver(db, driver_id, driver_username, driver_freetext)
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
            results["fuel_records"]["success"] += 1
            if station_dropped:
                warnings.append(f"Fuel record {idx}: {_STATION_KEPT_AS_TEXT}")
            if driver_dropped:
                warnings.append(f"Fuel record {idx}: {_DRIVER_KEPT_AS_TEXT}")
        except _RowError as e:
            results["fuel_records"]["errors"] += 1
            errors.append(f"Fuel record {idx}: {e.reason}")
        except Exception as e:
            results["fuel_records"]["errors"] += 1
            logger.warning("Import: fuel record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Fuel record {idx}: {_unexpected_reason(e)}")

    # Import DEF records
    # Deliberately NOT gated by ensure_def_capable (unlike import_def_csv and
    # the interactive create/update routes): this is a full-fidelity backup
    # restore, not a new write. A user's own archive must always restore
    # completely, even if it contains DEF rows for a vehicle whose fuel type
    # has since changed (or never was diesel per current data) — refusing to
    # restore data the user already had would be a data-loss bug, not a
    # safety feature.
    for idx, record_data in enumerate(sections["def_records"]):
        try:
            date = _json_row_date(record_data)
            # v3 uses "odometer_km"/"liters"; legacy v2 uses "mileage"/"gallons".
            # A 0 is a figure (G3a-75).
            record = _def_record_from_json(
                vin,
                date,
                record_data,
                odometer_km=_maybe_mi_to_km(
                    _json_first_decimal(record_data, "odometer_km", "mileage")
                ),
                liters=_maybe_gal_to_l(_json_first_decimal(record_data, "liters", "gallons")),
                price_per_unit=_maybe_per_gal_to_per_l(
                    _json_decimal(record_data, "price_per_unit")
                ),
            )

            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    DEFRecord,
                    DEFRecord.vin == vin,
                    *_json_def_key(
                        record_data,
                        record,
                        converted=is_legacy_v2,
                        last_id=matcher.last_id(DEFRecord),
                        zero_was_null=zero_was_null,
                    ),
                )
                is not None
            ):
                results["def_records"]["skipped"] += 1
                continue

            # A savepoint per row, flushed inside it so the end-of-import sync
            # has the record's id, and a row the database rejects rolls back
            # alone instead of failing the whole upload at the final commit.
            async with db.begin_nested():
                db.add(record)
                await db.flush()
            readings.add("def", record.id, record.date, odometer_km=record.odometer_km)
            results["def_records"]["success"] += 1
        except _RowError as e:
            results["def_records"]["errors"] += 1
            errors.append(f"DEF record {idx}: {e.reason}")
        except Exception as e:
            results["def_records"]["errors"] += 1
            logger.warning("Import: DEF record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"DEF record {idx}: {_unexpected_reason(e)}")

    # Import odometer records
    for idx, record_data in enumerate(sections["odometer_records"]):
        try:
            date = _json_row_date(record_data)

            # v2 used "reading" (miles), v3 uses "odometer_km".
            imported_odometer_km = _maybe_mi_to_km(
                _json_first_decimal(record_data, "odometer_km", "reading")
            )
            # The column is NOT NULL: refused here, not by the database (T-6).
            if imported_odometer_km is None:
                raise _RowError("odometer_km is missing")
            _within_api_bounds(OdometerRecordCreate, odometer_km=imported_odometer_km)

            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    OdometerRecord,
                    OdometerRecord.vin == vin,
                    OdometerRecord.date == date,
                    _odometer_matches(
                        OdometerRecord,
                        imported_odometer_km,
                        converted=is_legacy_v2,
                        last_id_before_import=matcher.last_id(OdometerRecord),
                    ),
                )
                is not None
            ):
                results["odometer_records"]["skipped"] += 1
                continue

            # No copied sync marker and a portable source (R4, N-2): a v8 file
            # has no source, so its rows read as manual.
            record = OdometerRecord(
                vin=vin,
                date=date,
                odometer_km=imported_odometer_km,
                notes=_without_sync_marker(record_data.get("notes")),
                source=_portable_odometer_source(record_data.get("source")),
            )
            # A savepoint per row. Leaving it flushes the insert, so a row the
            # database rejects rolls back alone instead of failing the whole
            # upload at the final commit (production sessions do not autoflush).
            async with db.begin_nested():
                db.add(record)
            results["odometer_records"]["success"] += 1
        except _RowError as e:
            results["odometer_records"]["errors"] += 1
            errors.append(f"Odometer record {idx}: {e.reason}")
        except Exception as e:
            results["odometer_records"]["errors"] += 1
            logger.warning("Import: odometer record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Odometer record {idx}: {_unexpected_reason(e)}")

    # Import engine-hours readings. Always manual rows with no FKs, like the
    # CSV importer: a file can't carry a live link to this vehicle's fuel or
    # service rows. Dimensionless, so no legacy-v2 conversion.
    for idx, record_data in enumerate(sections["hours_records"]):
        try:
            date = _json_row_date(record_data)
            # Through _json_decimal, so a word names its field.
            engine_hours = _json_decimal(record_data, "engine_hours")
            if engine_hours is None:
                results["hours_records"]["errors"] += 1
                errors.append(f"Hours record {idx}: engine hours are required")
                continue
            _within_api_bounds(HoursRecordCreate, engine_hours=engine_hours)

            # NUMERIC(10,1); no source in the key (T-19).
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
                results["hours_records"]["skipped"] += 1
                continue

            record = HoursRecord(
                vin=vin,
                date=date,
                engine_hours=engine_hours,
                notes=_without_sync_marker(record_data.get("notes")),
                source="manual",
            )
            async with db.begin_nested():
                db.add(record)
            results["hours_records"]["success"] += 1
        except _RowError as e:
            results["hours_records"]["errors"] += 1
            errors.append(f"Hours record {idx}: {e.reason}")
        except Exception as e:
            results["hours_records"]["errors"] += 1
            logger.warning("Import: hours record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Hours record {idx}: {_unexpected_reason(e)}")

    # Before the reminders, which count from the current reading (T-2).
    await readings.apply(db, vin, claim=False)

    # Read once, here: the odometer and hours sections have flushed by now
    # (each row leaves a savepoint), and no reminder row writes a reading.
    start_km, start_hours = await start_readings(db, vin)

    def _exported_due_point(
        reminder_data: dict[str, Any],
    ) -> tuple[date_type | None, Decimal | None]:
        """The due date and odometer the row was exported with, mileage in km."""
        due_date = (
            None
            if _is_blank(reminder_data.get("due_date"))
            else _json_row_date(reminder_data, "due_date")
        )
        due_km = _maybe_mi_to_km(_json_decimal(reminder_data, "due_mileage"))
        if due_km is not None:
            # NaN, sNaN and Infinity get the bounds message: == 0 raises on sNaN.
            if not due_km.is_finite():
                _within_api_bounds(ReminderCreate, due_mileage_km=due_km)
            # v2 saved 0 for no mileage.
            if due_km == 0:
                due_km = None
        if due_km is not None:
            # Rounded first so the message shows the figure we'd store. One too long
            # to round (1e26) is past the cap, and the bounds check says so.
            try:
                due_km = due_km.quantize(_column_step(Reminder.due_mileage_km))
            except InvalidOperation:
                _within_api_bounds(ReminderCreate, due_mileage_km=due_km)
                raise
        _within_api_bounds(ReminderCreate, due_mileage_km=due_km)
        return due_date, due_km

    def _pending_due_point(
        reminder_data: dict[str, Any],
    ) -> tuple[date_type | None, Decimal | None, bool]:
        """A pending row's due date and odometer in km, and whether its mileage half dropped."""
        mileage_dropped = False
        is_recurring = reminder_data.get("is_recurring", False)
        recurrence_days = reminder_data.get("recurrence_days", 0)
        recurrence_miles = reminder_data.get("recurrence_miles")

        has_date = bool(is_recurring and recurrence_days)
        has_miles = bool(is_recurring and recurrence_miles)

        # A negative interval would import already overdue; the bounds check stops it.
        miles = _json_decimal(reminder_data, "recurrence_miles") if has_miles else None
        _within_api_bounds(ReminderCreate, due_mileage_km=miles)

        # The point the row was exported with, recurring or not (J3): the schedule
        # said it. A stale backup imports overdue, which is honest.
        due_date, due_km = _exported_due_point(reminder_data)
        if is_recurring and due_date is None and due_km is None:
            interval_km = _maybe_mi_to_km(miles)
            if interval_km is not None:
                # The interval counts from the odometer after the import.
                # With no reading, a date side carries the row on its own
                # and the miles half drops; a miles-only row can't import.
                if start_km is not None:
                    due_km = (start_km + interval_km).quantize(
                        _column_step(Reminder.due_mileage_km)
                    )
                    _within_api_bounds(ReminderCreate, due_mileage_km=due_km)
                elif not has_date:
                    raise _RowError("no odometer reading to count from")
                else:
                    mileage_dropped = True

            # Calculate due_date from recurrence_days
            if has_date and recurrence_days:
                # A date object, in the household zone. The previous code
                # assigned .isoformat() -- a str the Date column rejects at
                # flush -- so every recurring-days row errored out of the
                # import; the per-row savepoint made it look like bad data.
                due_date = household_today() + timedelta(days=recurrence_days)

        # A pending reminder with nothing to come due on would never fire.
        if due_date is None and due_km is None:
            raise _RowError("no due date or mileage to import")
        return due_date, due_km, mileage_dropped

    # Import reminders → map to vehicle_reminders
    for idx, reminder_data in enumerate(sections["reminders"]):
        try:
            is_completed = bool(reminder_data.get("is_completed"))
            completed_at: datetime | None = None
            mileage_dropped = False
            if is_completed:
                # Comes back as done, due where it was. Not logged as a
                # service visit: the same import may already carry that work.
                completed_at = _json_row_datetime(reminder_data, "completed_at")
                due_date, due_km = _exported_due_point(reminder_data)
            else:
                due_date, due_km, mileage_dropped = _pending_due_point(reminder_data)

            if due_date is not None and due_km is not None:
                reminder_type = "both"
            elif due_km is not None:
                reminder_type = "mileage"
            else:
                reminder_type = "date"

            title = reminder_data["description"]
            status = "done" if is_completed else "pending"
            # A person made these too, so a rule's or a sync's reminder is never spent (S6).
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    Reminder,
                    Reminder.vin == vin,
                    Reminder.rule_id.is_(None),
                    Reminder.source.is_(None),
                    Reminder.title == title,
                    Reminder.reminder_type == reminder_type,
                    _matches(Reminder.due_date, due_date),
                    _same_figure(Reminder.due_mileage_km, due_km),
                    Reminder.status == status,
                )
                is not None
            ):
                results["reminders"]["skipped"] += 1
                continue

            reminder = Reminder(
                vin=vin,
                title=title,
                reminder_type=reminder_type,
                due_date=due_date,
                due_mileage_km=due_km,
                start_odometer_km=start_km,
                start_hours=start_hours,
                status=status,
                completed_at=completed_at,
                completed_date=household_date(completed_at) if completed_at is not None else None,
                notes=reminder_data.get("notes"),
                maintenance_type=classify(title),
            )
            # A savepoint per row. A row the database still rejects rolls
            # back alone here, instead of poisoning the session for every
            # row and loop still to come.
            async with db.begin_nested():
                db.add(reminder)
            results["reminders"]["success"] += 1
            if mileage_dropped:
                warnings.append(
                    f"Reminder {idx}: no odometer reading to count the mileage from, "
                    "imported with its date only"
                )
        except _RowError as e:
            results["reminders"]["errors"] += 1
            errors.append(f"Reminder {idx}: {e.reason}")
        except Exception as e:
            results["reminders"]["errors"] += 1
            logger.warning("Import: reminder %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Reminder {idx}: {_unexpected_reason(e)}")

    # Import notes
    for idx, note_data in enumerate(sections["notes"]):
        try:
            date = _json_row_date(note_data)
            content = note_data.get("content")
            if _is_blank(content):
                raise _RowError("content is missing")
            # Optional, and blank is NULL. No length cap: the notes CSV writes
            # titles unbounded on SQLite (NB-1).
            title = _json_text(note_data, "title")

            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    Note,
                    Note.vin == vin,
                    Note.date == date,
                    # T-16: a row with no title key matches any title.
                    *([_text_matches(Note.title, title)] if "title" in note_data else []),
                    Note.content == content,
                )
                is not None
            ):
                results["notes"]["skipped"] += 1
                continue

            note = Note(vin=vin, date=date, title=title, content=content)
            # A savepoint per row. A row the database still rejects rolls
            # back alone here, instead of poisoning the session for every
            # row and loop still to come.
            async with db.begin_nested():
                db.add(note)
            results["notes"]["success"] += 1
        except _RowError as e:
            results["notes"]["errors"] += 1
            errors.append(f"Note {idx}: {e.reason}")
        except Exception as e:
            results["notes"]["errors"] += 1
            logger.warning("Import: note %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Note {idx}: {_unexpected_reason(e)}")

    # Import insurance: each entry is THIS vehicle's place on a household policy.
    insurance_access = await InsuranceService(db).access_for(current_user)
    for idx, entry in enumerate(sections["insurance_policies"]):
        try:
            premium = entry.get("premium_share")
            deductible = entry.get("deductible")
            record = {
                "provider": entry["provider"],
                "policy_number": entry["policy_number"],
                "policy_type": entry.get("policy_type"),
                "start_date": datetime.fromisoformat(entry["start_date"]).date(),
                "end_date": datetime.fromisoformat(entry["end_date"]).date(),
                "premium": Decimal(str(premium)) if premium is not None else None,
                "premium_frequency": (entry.get("premium_frequency") or "").strip() or None,
                "deductible": Decimal(str(deductible)) if deductible is not None else None,
                "coverages": _coverages_from_rows(entry.get("coverages") or []),
                "notes": entry.get("notes"),
                "fields": entry.get("fields") or [],
                "policy_fields": entry.get("policy_fields") or [],
                "policy_notes": entry.get("policy_notes"),
                "effective_to": (
                    datetime.fromisoformat(entry["effective_to"]).date()
                    if entry.get("effective_to")
                    else None
                ),
            }
            # Schema 7 and older carried one coverage text box instead. It is
            # converted whole, so a restored old backup lands what an in-place
            # upgrade would have: the rows, the named fields AND the prose.
            if entry.get("coverages") is None:
                _merge_converted(record, entry.get("coverage_limits"))
            imported = await _import_insurance_row(
                db,
                insurance_access,
                vin,
                record,
                skip_duplicates=True,
            )
            results["insurance_policies"]["success" if imported else "skipped"] += 1
        except (_InsuranceRowError, _ImportBoundError) as e:
            results["insurance_policies"]["errors"] += 1
            errors.append(f"Insurance policy {idx}: {e.reason}")
        except Exception as e:
            results["insurance_policies"]["errors"] += 1
            logger.warning("Import: insurance policy %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Insurance policy {idx}: {_unexpected_reason(e)}")

    # Import financing. The lender travels by name and is looked up or made in
    # the row's savepoint, as a service visit's vendor is (R6).
    for idx, row in enumerate(sections["financing_records"]):
        try:
            record = _financing_record_from_json(vin, row)
            # As given, same as a service visit's vendor.
            lender = _json_text(row, "vendor_name")
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    FinancingRecord,
                    FinancingRecord.vin == vin,
                    *_json_financing_key(record),
                    options=(selectinload(FinancingRecord.vendor),),
                    same=(
                        (lambda f: (f.vendor.name if f.vendor else None) == lender)
                        if "vendor_name" in row
                        else None
                    ),
                )
                is not None
            ):
                results["financing_records"]["skipped"] += 1
                continue

            async with db.begin_nested():
                record.vendor_id = await _vendor_id_for(db, lender)
                db.add(record)
            results["financing_records"]["success"] += 1
        except _RowError as e:
            results["financing_records"]["errors"] += 1
            errors.append(f"Financing record {idx}: {e.reason}")
        except Exception as e:
            results["financing_records"]["errors"] += 1
            logger.warning("Import: financing record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Financing record {idx}: {_unexpected_reason(e)}")

    # Import tax records
    for idx, row in enumerate(sections["tax_records"]):
        try:
            record = _tax_record_from_json(vin, row)
            if (
                skip_duplicates
                and await matcher.take(
                    db, TaxRecord, TaxRecord.vin == vin, *_json_tax_key(row, record)
                )
                is not None
            ):
                results["tax_records"]["skipped"] += 1
                continue

            async with db.begin_nested():
                db.add(record)
            results["tax_records"]["success"] += 1
        except _RowError as e:
            results["tax_records"]["errors"] += 1
            errors.append(f"Tax record {idx}: {e.reason}")
        except Exception as e:
            results["tax_records"]["errors"] += 1
            logger.warning("Import: tax record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Tax record {idx}: {_unexpected_reason(e)}")

    # Import toll tags. A transaction names its tag by the tag's index in this
    # file (R6), so each tag written or matched is kept by that index, with
    # its key; a tag that failed has neither, and its transactions are stored,
    # and keyed, untagged (Fable F-3).
    tag_ids: dict[int, int] = {}
    tag_keys: dict[int, tuple[str, str]] = {}
    for idx, row in enumerate(sections["toll_tags"]):
        try:
            tag = _toll_tag_from_json(vin, row)
            # The system is compared under its listed name on the loaded rows,
            # since a stored one may still be spelled as typed.
            stored = (
                await matcher.take(
                    db,
                    TollTag,
                    TollTag.vin == vin,
                    TollTag.tag_number == tag.tag_number,
                    same=lambda t: _toll_system_name(t.toll_system) == tag.toll_system,
                )
                if skip_duplicates
                else None
            )
            if stored is not None:
                tag_ids[idx] = stored.id
                tag_keys[idx] = (tag.toll_system, tag.tag_number)
                results["toll_tags"]["skipped"] += 1
                continue

            async with db.begin_nested():
                db.add(tag)
                await db.flush()
            tag_ids[idx] = tag.id
            tag_keys[idx] = (tag.toll_system, tag.tag_number)
            results["toll_tags"]["success"] += 1
        except _RowError as e:
            results["toll_tags"]["errors"] += 1
            errors.append(f"Toll tag {idx}: {e.reason}")
        except Exception as e:
            results["toll_tags"]["errors"] += 1
            logger.warning("Import: toll tag %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Toll tag {idx}: {_unexpected_reason(e)}")

    # Import toll transactions. Two same-day charges at one plaza are two rows,
    # and a re-import matches each to one stored charge (R1-H1). A null
    # toll_tag_index is untagged; an absent key matches a toll with any tag (T-16).
    for idx, row in enumerate(sections["toll_transactions"]):
        try:
            record, tag_index = _toll_transaction_from_json(vin, row, len(sections["toll_tags"]))
            tag_key = tag_keys.get(tag_index) if tag_index is not None else None
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    TollTransaction,
                    TollTransaction.vin == vin,
                    *_json_toll_transaction_key(record),
                    options=(selectinload(TollTransaction.toll_tag),),
                    same=(
                        (lambda t: _toll_tag_key(t.toll_tag) == tag_key)
                        if "toll_tag_index" in row
                        else None
                    ),
                )
                is not None
            ):
                results["toll_transactions"]["skipped"] += 1
                continue

            record.toll_tag_id = tag_ids.get(tag_index) if tag_index is not None else None
            async with db.begin_nested():
                db.add(record)
            results["toll_transactions"]["success"] += 1
            if tag_index is not None and record.toll_tag_id is None:
                warnings.append(
                    f"Toll transaction {idx}: its toll tag was not imported, saved without one"
                )
        except _RowError as e:
            results["toll_transactions"]["errors"] += 1
            errors.append(f"Toll transaction {idx}: {e.reason}")
        except Exception as e:
            results["toll_transactions"]["errors"] += 1
            logger.warning("Import: toll transaction %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Toll transaction {idx}: {_unexpected_reason(e)}")

    # Import warranties
    for idx, row in enumerate(sections["warranties"]):
        try:
            record = _warranty_from_json(vin, row)
            if (
                skip_duplicates
                and await matcher.take(
                    db, WarrantyRecord, WarrantyRecord.vin == vin, *_json_warranty_key(row, record)
                )
                is not None
            ):
                results["warranties"]["skipped"] += 1
                continue

            async with db.begin_nested():
                db.add(record)
            results["warranties"]["success"] += 1
        except _RowError as e:
            results["warranties"]["errors"] += 1
            errors.append(f"Warranty {idx}: {e.reason}")
        except Exception as e:
            results["warranties"]["errors"] += 1
            logger.warning("Import: warranty %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Warranty {idx}: {_unexpected_reason(e)}")

    # Import spot rentals with their bills. A rental skipped as a duplicate
    # skips its bills; one written writes them in its savepoint.
    for idx, row in enumerate(sections["spot_rentals"]):
        try:
            rental, bills = _spot_rental_from_json(vin, row)
            # Each amount only when every bill has it (T-16); the bills are
            # objects by now, or the parse above refused the row.
            raw_bills = cast(list[Mapping[str, Any]], row.get("billings", []))
            amounts = tuple(n for n in _BILL_AMOUNTS if all(n in b for b in raw_bills))
            bill_counts = _bill_counts(bills, amounts)
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    SpotRental,
                    SpotRental.vin == vin,
                    *_json_spot_rental_key(row, rental),
                    options=(selectinload(SpotRental.billings),),
                    same=(
                        (lambda r: _bill_counts(r.billings, amounts) == bill_counts)
                        if "billings" in row
                        else None
                    ),
                )
                is not None
            ):
                results["spot_rentals"]["skipped"] += 1
                continue

            async with db.begin_nested():
                db.add(rental)
                await db.flush()
                for bill in bills:
                    bill.spot_rental_id = rental.id
                db.add_all(bills)
                await db.flush()
            results["spot_rentals"]["success"] += 1
        except _RowError as e:
            results["spot_rentals"]["errors"] += 1
            errors.append(f"Spot rental {idx}: {e.reason}")
        except Exception as e:
            results["spot_rentals"]["errors"] += 1
            logger.warning("Import: spot rental %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Spot rental {idx}: {_unexpected_reason(e)}")

    # The rules come with their reminders, whole or not at all, and only into a
    # vehicle with no rules. The reconcile after the commit keeps their due points (K1).
    rules = await run_family(
        db,
        vin,
        "maintenance_rules",
        sections,
        results,
        errors,
        warnings,
        parse=lambda: parse_rules(vin, sections),
        write=lambda plan: write_rules(db, plan),
    )
    if rules.outcome == "written" and rules.plan is not None:
        warnings.extend(rules.plan.warnings)

    # Reminders a person made, every status, counted with the legacy ones (T-4).
    # The v2 loop reads ["description"], so v9 writes them in their own list (N-3).
    for idx, row in enumerate(sections["manual_reminders"]):
        try:
            reminder, type_dropped = reminder_from_json(vin, row)
            # A rule's or a sync's reminder with the same title is never spent.
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    Reminder,
                    Reminder.vin == vin,
                    Reminder.rule_id.is_(None),
                    Reminder.source.is_(None),
                    *manual_reminder_key(row, reminder),
                )
                is not None
            ):
                results["reminders"]["skipped"] += 1
                continue

            async with db.begin_nested():
                db.add(reminder)
            results["reminders"]["success"] += 1
            if type_dropped:
                warnings.append(
                    f"Manual reminder {idx}: its maintenance type isn't a code, "
                    "so it was saved without one"
                )
        except _RowError as e:
            results["reminders"]["errors"] += 1
            errors.append(f"Manual reminder {idx}: {e.reason}")
        except Exception as e:
            results["reminders"]["errors"] += 1
            logger.warning("Import: manual reminder %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Manual reminder {idx}: {_unexpected_reason(e)}")

    # Recalls, keyed on the campaign. One the nightly check put back gains the file's resolution.
    await import_recalls(
        db,
        vin,
        sections["recalls"],
        matcher=matcher,
        skip_duplicates=skip_duplicates,
        bucket=results["recalls"],
        errors=errors,
    )

    # DTCs, keyed on code and first seen. The index keeps one active row per code.
    await import_dtcs(
        db,
        vin,
        sections["dtcs"],
        matcher=matcher,
        skip_duplicates=skip_duplicates,
        bucket=results["dtcs"],
        errors=errors,
        warnings=warnings,
    )

    # The tire family comes in whole or not at all, and only into a vehicle with no tires.
    tires = await run_family(
        db,
        vin,
        "tires",
        sections,
        results,
        errors,
        warnings,
        parse=lambda: parse_tires(vin, sections),
        write=lambda plan: write_tires(db, plan),
    )

    # Brakes too: whole or not at all, and only into a vehicle with no brake records.
    brakes = await run_family(
        db,
        vin,
        "brakes",
        sections,
        results,
        errors,
        warnings,
        parse=lambda: parse_brakes(vin, sections),
        write=lambda plan: write_brakes(db, plan),
    )

    # Only the tires this import wrote can raise a low-tread reminder (N-2).
    if tires.outcome == "written" and tires.plan is not None:
        try:
            async with db.begin_nested():
                await sync_imported_tires(db, tires.plan)
        except Exception as e:
            # Derived data, like the reading sync: the tires stay without it.
            logger.warning(
                "Import: low-tread sync failed for vin=%s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )

    # A LOW corner in the file raises its reminder now, not at 08:00 (N-2). A
    # skipped family brought nothing new, so only a written one runs the pass.
    if brakes.outcome == "written":
        try:
            async with db.begin_nested():
                await BrakeService(db).raise_reminders_for(vin)
        except Exception as e:
            # The brakes stay; the 08:00 pass raises it instead.
            logger.warning(
                "Import: brake reminder raise failed for vin=%s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )

    await db.commit()
    # Imported services may be the newest of a rule's type: reconcile once.
    await maintenance_service.reconcile_vehicle(db, vin)
    await invalidate_cache_for_vehicle(vin)

    for key in _JSON_RESULT_BUCKETS:
        bucket = results[key]
        bucket["success_count"] = bucket.get("success", 0)
        bucket["error_count"] = bucket.get("errors", 0)
        bucket["skipped_count"] = bucket.get("skipped", 0)

    return results
