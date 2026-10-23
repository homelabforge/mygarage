import csv
import io
import json
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper, selectinload

from app.config import settings
from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet
from app.database import get_db
from app.models import (
    DEFRecord,
    FuelRecord,
    HoursRecord,
    InsurancePolicy,
    InsurancePolicyVehicle,
    Note,
    OdometerRecord,
    ServiceVisit,
    TaxRecord,
    WarrantyRecord,
)
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.fuel_service import resolve_station_names
from app.utils.csv_emission import apply_unit_set, marker_for
from app.utils.csv_safe import sanitize_csv_row
from app.utils.insurance_coverages import coverage_text
from app.utils.insurance_shares import effective_shares
from app.utils.render_context import render_context_for_request

router = APIRouter(prefix="/api/export", tags=["export"])

# Initialize rate limiter for export endpoints
limiter = Limiter(key_func=get_remote_address)

# CSV and JSON export schema versions.
#
# Before issue #152 Task 1, CSV and JSON shared one EXPORT_SCHEMA_VERSION
# constant, so this history applies to both surfaces up to v5:
# - v2: legacy imperial.
# - v3: SI-metric canonical (issue #67).
# - v4: v3 + extended fuel-tracking columns (issue #69 / v2.27.0-rc2):
#       Filled At, Fuel Type Used, Station, Driver, Payment Method,
#       Trip Type, Outside Temp, OBC values. Purely additive, v3
#       importers continue to work.
# - v5: drops the fuel "Fuel Type" column, retired with the legacy
#       `fuel_records.fuel_type` DB column (migration 089). "Fuel Type Used"
#       carries the canonical enum. NOT additive, so the version moves; the
#       importer still reads "Fuel Type" from v4-and-older files.
#
# From v5 the two diverge. Bumping the CSV schema for the per-quantity unit
# headers landing later in this phase (#152) must not silently move the JSON
# backup contract too, so the constant is split:
# - CSV_SCHEMA_VERSION = "6": reserved for unit-preference-aware headers
#   landing in later tasks of this phase. Nothing in the CSV row shape
#   changes yet; only the version cell does (Task 1, #152).
# - JSON_SCHEMA_VERSION = "5": unchanged. The JSON backup's shape is not part
#   of this phase.
#
# CSV exports prepend a `units_version` column with CSV_SCHEMA_VERSION to
# every row; JSON exports include a top-level `"export_version"` set to
# JSON_SCHEMA_VERSION plus a `"units"` field.
# The importer (`app/routes/import_data.py`) reads the marker and falls back
# to v2 imperial conversion when it's missing (legacy v2 backups).
# - CSV "7" / JSON "6": additive fuel grade columns, #164 — `Octane` and
#   `Diesel Grade` in the fuel CSV, `octane`/`diesel_grade` keys in the JSON
#   fuel records (same additive treatment as the v3→v4 fuel columns).
# - JSON "7": additive `insurance_policies` list (household insurance,
#   migration 107). The CSV shape is unchanged, so its version is too.
# - JSON "8": each insurance entry carries `coverages` (the standard coverage
#   catalogue, migration 108) in place of the `coverage_limits` text box. The
#   CSV keeps its `Coverage Limits` column, now rendered from those rows and
#   read back through the same parser, so its shape and version are unchanged.
# - CSV "8": the service CSV numbers each visit in a `Visit` column, splits
#   `Notes` into `Item Notes` and `Visit Notes`, and adds `Tax`,
#   `Shop Supplies`, `Misc Fees` and `Insurance Claim` (J6). Rows sharing a
#   number import as one visit; an older file groups by date, odometer,
#   vendor and category. The other CSVs keep their shape.
# - JSON "9": every section writes every column (R1): `service_visits` with
#   nested `line_items` replaces `service_records`, the fuel, DEF, odometer
#   and hours rows carry the rest of their columns, the vehicle is written
#   whole, and `financing_records`, `tax_records`, `toll_tags`,
#   `toll_transactions`, `warranties` and `spot_rentals` are new. The
#   importer still reads v2 to v8, and a section a file lacks is empty.
CSV_SCHEMA_VERSION = "8"
JSON_SCHEMA_VERSION = "9"
EXPORT_UNITS = "metric"


_UNITS_QUERY_DESCRIPTION = (
    "Unit system for the exported values. OMIT this parameter to export in the "
    "caller's own unit preferences (the instance default on an auth_mode=none "
    "instance), which is the only way to receive a mixed set such as kilometres "
    "with UK gallons. Pass `metric` or `imperial` to force that preset instead. "
    "Every unit-bearing column names its unit in the header, e.g. `Odometer (mi)`, "
    "`Volume (gal_uk)`, `Price Per Unit (gal_uk)`."
)


async def resolve_export_units(
    requested: str | None, current_user: User | None, db: AsyncSession, *, vehicle: Vehicle
) -> UnitSet:
    """The unit set one CSV export is written in.

    Precedence: an explicit `?units=metric|imperial` wins outright and
    produces a clean PRESET export, whoever asked for it. Omitting the
    parameter uses the caller's own resolved set, and on an `auth_mode=none`
    instance -- where there is no caller to resolve from -- the instance
    default.

    The parameter has no default, deliberately. While it defaulted to
    `"metric"`, an omitted `?units` and an explicit `?units=metric` were
    indistinguishable here, so an account with mixed preferences could never
    receive its own headers: the frontend sent the binary system it had
    already collapsed that account into, and got a clean preset back.

    `resolve_gallon_flavour` deliberately plays no part any more. The
    instance-wide `imperial_gallon_standard` row used to decide which gallon
    an `?units=imperial` export was written in, which is how a UK instance
    emitted UK gallons under the marker `imperial_uk`. v6 stops emitting that
    marker: the gallon flavour travels in the header token, and it comes from
    the account (or from the explicitly requested preset), never from an
    instance setting.
    """
    if requested == "metric":
        return METRIC_PRESET
    if requested == "imperial":
        return IMPERIAL_PRESET
    # An explicit preset above is a clean preset and ignores the vehicle. The
    # default applies the vehicle's own odometer unit (#172); `vehicle` is
    # required so no export can forget it.
    return (await render_context_for_request(current_user, db, vehicle=vehicle)).units


def generate_csv_stream(
    headers: list[str], rows: list[list[Any]], unit_system: str = EXPORT_UNITS
) -> io.StringIO:
    """Generate CSV content with leading `units_version` + `unit_system` columns.

    `units_version` is the SCHEMA version; `unit_system` says which units the
    values are actually in. They are separate because they change for different
    reasons - conflating them is what let a v4 metric export be re-imported as
    imperial (#128). The importer reads `unit_system` first.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["units_version", "unit_system", *headers])
    # Neutralise CSV formula-injection in every data cell (header is static).
    writer.writerows([sanitize_csv_row([CSV_SCHEMA_VERSION, unit_system, *row]) for row in rows])
    output.seek(0)
    return output


def build_csv(headers: list[str], rows: list[list[Any]], units: UnitSet) -> io.StringIO:
    """Convert a canonical-metric table into `units` and stream it.

    One resolved `UnitSet` drives both halves of the file, so the values and
    the header tokens can never disagree: `app.utils.csv_emission` renames
    each unit-bearing header to `Base (token)` and converts that column's
    cells in the same pass, and the `unit_system` marker is derived from the
    same set.
    """
    headers, rows = apply_unit_set(headers, rows, units)
    return generate_csv_stream(headers, rows, unit_system=marker_for(units))


def _money_cell(value: Decimal | None) -> str:
    """A money cell: two places, blank only when there's no amount."""
    return f"{value:.2f}" if value is not None else ""


def _json_value(value: Any) -> Any:
    """A column value for the JSON backup: Decimal as a number, dates as ISO text."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _json_columns(row: Any, exclude: frozenset[str]) -> dict[str, Any]:
    """Every column of `row` but `exclude`, in model order (R1).

    A column added to the model is exported by default; the JSON coverage test
    fails until it is named there as exported or excluded.
    """
    mapper: Mapper[Any] = sa_inspect(type(row))
    return {
        column.key: _json_value(getattr(row, column.key))
        for column in mapper.columns
        if column.key not in exclude
    }


#: Left out of every section: the row's key, its vehicle (the file is the
#: vehicle's) and the bookkeeping timestamps.
_ALWAYS_EXCLUDED = frozenset({"id", "vin", "created_at", "updated_at"})
#: The vendor travels by name; the total is recomputed from the items and fees.
_SERVICE_VISIT_JSON_EXCLUDE = _ALWAYS_EXCLUDED | {"vendor_id", "total_cost"}
#: The visit is the parent; the inspection link travels as an index in the visit.
_LINE_ITEM_JSON_EXCLUDE = frozenset({"id", "visit_id", "triggered_by_inspection_id", "created_at"})
#: Every fuel column travels; the station and driver links go with their names.
_FUEL_JSON_EXCLUDE = _ALWAYS_EXCLUDED
#: The fill-up that wrote a synced DEF row is a fuel row on this instance.
_DEF_JSON_EXCLUDE = _ALWAYS_EXCLUDED | {"origin_fuel_record_id"}
#: The fill-up that owned the reading here; an imported reading is never owned (R4).
_ODOMETER_JSON_EXCLUDE = _ALWAYS_EXCLUDED | {"fuel_record_id"}
#: The same for the fill-up or visit an hours reading was synced from.
_HOURS_JSON_EXCLUDE = _ALWAYS_EXCLUDED | {"fuel_record_id", "service_visit_id"}
#: What the service exports read off a visit.
_SERVICE_VISIT_EXPORT_LOADS = (
    selectinload(ServiceVisit.line_items),
    selectinload(ServiceVisit.vendor),
)


async def _driver_usernames(db: AsyncSession, records: Sequence[FuelRecord]) -> dict[int, str]:
    """Each linked driver's username by user id, in one query, so a restore can check the link."""
    ids = {r.driver_user_id for r in records if r.driver_user_id}
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    return {user_id: username for user_id, username in rows.all()}


def _line_items_json(visit: ServiceVisit) -> list[dict[str, Any]]:
    """A visit's line items; an inspection link is the linked item's index here."""
    position = {item.id: index for index, item in enumerate(visit.line_items)}
    return [
        {
            **_json_columns(item, _LINE_ITEM_JSON_EXCLUDE),
            # A link outside the visit has no index here, so it drops.
            "triggered_by_inspection": position.get(item.triggered_by_inspection_id),
        }
        for item in visit.line_items
    ]


@router.get("/vehicles/{vin}/service/csv")
@limiter.limit(settings.rate_limit_exports)
async def export_service_records_csv(
    request: Request,
    vin: str,
    units: str | None = Query(
        None,
        pattern="^(metric|imperial)$",
        description=_UNITS_QUERY_DESCRIPTION,
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export service records as CSV (from ServiceVisit model)."""
    # Verify vehicle exists and user has access
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Every service visit with its line items and vendor. The rows carry each
    # item's own cost and the visit's fees, not the supply-inclusive total, so
    # supply usages aren't loaded.
    result = await db.execute(
        select(ServiceVisit)
        .where(ServiceVisit.vin == vin)
        .options(*_SERVICE_VISIT_EXPORT_LOADS)
        .order_by(ServiceVisit.date.desc())
    )
    visits = result.scalars().all()

    # One row per line item, numbered by visit (J6): rows sharing a `Visit`
    # number import as one visit. A visit with no items is one row with the
    # item's cells blank.
    headers = [
        "Visit",
        "Date",
        "Category",
        "Description",
        "Odometer (km)",
        "Engine Hours",
        "Cost",
        "Vendor",
        "Item Notes",
        "Tax",
        "Shop Supplies",
        "Misc Fees",
        "Insurance Claim",
        "Visit Notes",
    ]

    rows: list[list[Any]] = []
    for number, visit in enumerate(visits, start=1):
        vendor_name = visit.vendor.name if visit.vendor else ""
        # engine_hours: hour-metered vehicles (ATVs, side-by-sides, equipment).
        # Dimensionless — no unit conversion. `is not None` (not `or ""`) so a
        # genuine 0.0 reading isn't dropped, matching fuel's outside_temp_c/
        # obc_l_per_100km convention.
        engine_hours = f"{visit.engine_hours:.1f}" if visit.engine_hours is not None else ""
        # Description, Cost and Item Notes; blank on a visit with no items.
        item_cells = [
            [item.description, _money_cell(item.cost), item.notes or ""]
            for item in visit.line_items
        ] or [["", "", ""]]
        for description, cost, item_notes in item_cells:
            rows.append(
                [
                    str(number),
                    visit.date.isoformat(),
                    visit.service_category or "",
                    description,
                    visit.odometer_km,  # canonical Decimal or None; build_csv converts it
                    engine_hours,
                    cost,
                    vendor_name,
                    item_notes,
                    _money_cell(visit.tax_amount),
                    _money_cell(visit.shop_supplies),
                    _money_cell(visit.misc_fees),
                    visit.insurance_claim_number or "",
                    visit.notes or "",
                ]
            )

    output = build_csv(
        headers, rows, await resolve_export_units(units, current_user, db, vehicle=vehicle)
    )

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_service_records_{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vehicles/{vin}/fuel/csv")
@limiter.limit(settings.rate_limit_exports)
async def export_fuel_records_csv(
    request: Request,
    vin: str,
    units: str | None = Query(
        None,
        pattern="^(metric|imperial)$",
        description=_UNITS_QUERY_DESCRIPTION,
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export fuel records as CSV"""
    # Verify vehicle exists and user has access
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Get all fuel records
    result = await db.execute(
        select(FuelRecord).where(FuelRecord.vin == vin).order_by(FuelRecord.date.desc())
    )
    records = result.scalars().all()
    # "Station" showed only freetext, so it came out blank for every station
    # picked from the address book — issue #108 in CSV form. "Station ID" still
    # carries the FK, so the round-trip keeps its fidelity.
    station_names = await resolve_station_names(db, list(records))
    # "Driver" carries a linked driver's username the same way (T-5), so a
    # restore can tell whether this instance has that user.
    driver_usernames = await _driver_usernames(db, records)

    # Generate CSV.
    # NOTE: column set extended for v2.27.0-rc2 (#69 issue follow-up).
    # The ``CSV_SCHEMA_VERSION`` bump from "3" to "4" signalled importers
    # that the new columns may be present; "5" says the redundant legacy
    # "Fuel Type" column is gone and "Fuel Type Used" is the fuel type.
    headers = [
        "Date",
        "Filled At",
        "Odometer (km)",
        "Engine Hours",
        "Liters",
        "Price Per Liter",
        "Rebate",
        "Total Cost",
        "Full Tank",
        "Missed Fill-up",
        "Is Hauling",
        "Fuel Type Used",
        "Octane",
        "Diesel Grade",
        "Station ID",
        "Station",
        "Driver ID",
        "Driver",
        "Payment Method",
        "Trip Type",
        "Outside Temp (C)",
        "OBC L/100km",
        "OBC Avg Speed (km/h)",
        "OBC Trip Duration (s)",
        "SOC Start (%)",
        "SOC End (%)",
        "Charge Level",
        "Charge Location",
        "Battery SOH (%)",
        "Notes",
    ]

    rows = []
    for record in records:
        rows.append(
            [
                record.date.isoformat() if record.date else "",
                record.filled_at.isoformat() if record.filled_at else "",
                # Unit-bearing columns hand `build_csv` the raw canonical
                # `Decimal`: `csv_emission` owns both the conversion and the
                # per-column decimal places, so a cell's precision cannot
                # differ between the metric and non-metric spellings of the
                # same column.
                record.odometer_km,
                # Dimensionless — no unit conversion. `is not None` (not `or ""`)
                # so a genuine 0.0 reading isn't dropped, matching outside_temp_c
                # / obc_l_per_100km below.
                f"{record.engine_hours:.1f}" if record.engine_hours is not None else "",
                record.liters,
                record.price_per_unit,
                _money_cell(record.rebate),
                _money_cell(record.cost),
                "Yes" if record.is_full_tank else "No",
                "Yes" if record.missed_fillup else "No",
                "Yes" if record.is_hauling else "No",
                record.fuel_type_used or "",
                # Dimensionless grade fields (#164) — an octane is an int label,
                # not a unit-bearing quantity, so no csv_emission conversion.
                record.octane if record.octane is not None else "",
                record.diesel_grade or "",
                record.station_address_book_id or "",
                station_names.get(record.id) or "",
                record.driver_user_id or "",
                driver_usernames.get(record.driver_user_id) or record.driver_name_freetext or "",
                record.payment_method or "",
                record.trip_type or "",
                # Unit-bearing, and `is not None` rather than truthy: a
                # genuine 0.0 C or 0.0 km/h is a real reading. `csv_emission`
                # renders `None` as a blank cell.
                record.outside_temp_c,
                record.obc_l_per_100km,
                record.obc_avg_speed_kmh,
                record.obc_trip_duration_s if record.obc_trip_duration_s is not None else "",
                f"{record.soc_start_pct:.1f}" if record.soc_start_pct is not None else "",
                f"{record.soc_end_pct:.1f}" if record.soc_end_pct is not None else "",
                record.charge_level or "",
                record.charge_location or "",
                f"{record.battery_soh_pct:.1f}" if record.battery_soh_pct is not None else "",
                record.notes or "",
            ]
        )

    output = build_csv(
        headers, rows, await resolve_export_units(units, current_user, db, vehicle=vehicle)
    )

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_fuel_records_{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vehicles/{vin}/def/csv")
@limiter.limit(settings.rate_limit_exports)
async def export_def_records_csv(
    request: Request,
    vin: str,
    units: str | None = Query(
        None,
        pattern="^(metric|imperial)$",
        description=_UNITS_QUERY_DESCRIPTION,
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export DEF records as CSV."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    result = await db.execute(
        select(DEFRecord).where(DEFRecord.vin == vin).order_by(DEFRecord.date.desc())
    )
    records = result.scalars().all()

    headers = [
        "Date",
        "Odometer (km)",
        "Liters",
        "Price Per Unit",
        "Total Cost",
        "Fill Level",
        "Source",
        "Brand",
        "Notes",
    ]

    rows = []
    for record in records:
        rows.append(
            [
                record.date.isoformat() if record.date else "",
                record.odometer_km,
                record.liters,
                record.price_per_unit,
                _money_cell(record.cost),
                f"{record.fill_level:.2f}" if record.fill_level is not None else "",
                record.source or "",
                record.brand or "",
                record.notes or "",
            ]
        )

    output = build_csv(
        headers, rows, await resolve_export_units(units, current_user, db, vehicle=vehicle)
    )

    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_def_records_{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vehicles/{vin}/odometer/csv")
@limiter.limit(settings.rate_limit_exports)
async def export_odometer_records_csv(
    request: Request,
    vin: str,
    units: str | None = Query(
        None,
        pattern="^(metric|imperial)$",
        description=_UNITS_QUERY_DESCRIPTION,
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export odometer records as CSV"""
    # Verify vehicle exists and user has access
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Get all odometer records
    result = await db.execute(
        select(OdometerRecord)
        .where(OdometerRecord.vin == vin)
        .order_by(OdometerRecord.date.desc(), OdometerRecord.id.desc())
    )
    records = result.scalars().all()

    # Generate CSV
    headers = ["Date", "Reading (km)", "Notes"]

    rows = []
    for record in records:
        rows.append(
            [
                record.date.isoformat() if record.date else "",
                record.odometer_km,
                record.notes or "",
            ]
        )

    output = build_csv(
        headers, rows, await resolve_export_units(units, current_user, db, vehicle=vehicle)
    )

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_odometer_records_{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vehicles/{vin}/hours/csv")
@limiter.limit(settings.rate_limit_exports)
async def export_hours_records_csv(
    request: Request,
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export engine-hours records as CSV.

    Mirrors :func:`export_odometer_records_csv` — the hours track's
    standalone history CSV for hour-metered vehicles (ATVs, side-by-sides,
    equipment). Registered under this router (``/api/export``), not the
    hours CRUD router (``/api/vehicles/{vin}/hours``), to avoid shadowing
    that router's ``GET /{record_id}`` route.
    """
    # Verify vehicle exists and user has access
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Get all hours records
    result = await db.execute(
        select(HoursRecord).where(HoursRecord.vin == vin).order_by(HoursRecord.date.desc())
    )
    records = result.scalars().all()

    # Generate CSV. `source` documents provenance (manual/fuel/service_visit)
    # for the operator's reference — the importer always writes 'manual' on
    # re-import (see import_hours_csv), since a CSV can't carry a live FK to
    # a fuel/service row in the target vehicle's tables.
    headers = ["Date", "Engine Hours", "Notes", "Source"]

    rows = []
    for record in records:
        rows.append(
            [
                record.date.isoformat() if record.date else "",
                # Dimensionless — no unit conversion. `is not None` (not
                # `or ""`) so a genuine 0.0 reading isn't dropped.
                f"{record.engine_hours:.1f}" if record.engine_hours is not None else "",
                record.notes or "",
                record.source or "",
            ]
        )

    output = generate_csv_stream(headers, rows)

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_hours_records_{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vehicles/{vin}/warranties/csv")
@limiter.limit(settings.rate_limit_exports)
async def export_warranties_csv(
    request: Request,
    vin: str,
    units: str | None = Query(
        None,
        pattern="^(metric|imperial)$",
        description=_UNITS_QUERY_DESCRIPTION,
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export warranties as CSV"""
    # Verify vehicle exists and user has access
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Get all warranties
    result = await db.execute(
        select(WarrantyRecord)
        .where(WarrantyRecord.vin == vin)
        .order_by(WarrantyRecord.start_date.desc())
    )
    records = result.scalars().all()

    # Generate CSV
    # Every column here maps to a real WarrantyRecord attribute. The previous
    # set named five that do not exist (`coverage`, `cost`, `deductible`,
    # `max_claims`, `terms`), so this route returned 500 for any vehicle with a
    # warranty. `Mileage Limit (km)` is unit-bearing and resolved by build_csv.
    headers = [
        "Provider",
        "Type",
        "Policy Number",
        "Coverage Details",
        "Start Date",
        "End Date",
        "Mileage Limit (km)",
        "Notes",
    ]

    rows = []
    for record in records:
        rows.append(
            [
                record.provider or "",
                record.warranty_type or "",
                record.policy_number or "",
                record.coverage_details or "",
                record.start_date.isoformat() if record.start_date else "",
                record.end_date.isoformat() if record.end_date else "",
                # Canonical km. build_csv converts the cell and renames the
                # header token together, so the two cannot disagree.
                record.mileage_limit_km if record.mileage_limit_km is not None else None,
                record.notes or "",
            ]
        )

    output = build_csv(
        headers, rows, await resolve_export_units(units, current_user, db, vehicle=vehicle)
    )

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_warranties_{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


#: Reaching a policy THROUGH one of its links does not eager-load the policy's
#: own collections: SQLAlchemy will not walk back down the relationship it just
#: came up. Spell them out, or the first read is an async lazy load.
#: The sibling links are loaded only so `_insurance_share` can read their ids
#: and shares; `raiseload` keeps each of them from dragging its own coverages,
#: and shouts if anything ever reads one, which this export never does off a sibling.
_INSURANCE_LINK_LOADS = (
    selectinload(InsurancePolicyVehicle.policy)
    .selectinload(InsurancePolicy.vehicle_links)
    .raiseload(InsurancePolicyVehicle.coverages),
    selectinload(InsurancePolicyVehicle.policy).selectinload(InsurancePolicy.all_fields),
)


def _insurance_share(link: InsurancePolicyVehicle) -> float | None:
    """One vehicle's effective per-period share of its policy, for JSON."""
    policy = link.policy
    share = effective_shares(
        policy.premium_amount, [(item.id, item.premium_share) for item in policy.vehicle_links]
    ).get(link.id)
    return float(share) if share is not None else None


@router.get("/vehicles/{vin}/insurance/csv")
@limiter.limit(settings.rate_limit_exports)
async def export_insurance_csv(
    request: Request,
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export insurance records as CSV"""
    # Verify vehicle exists and user has access
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # One row per policy covering THIS vehicle. The columns are unchanged from
    # the per-vehicle era, so older files still import: Type, Deductible,
    # Coverage Limits and Notes are this vehicle's own, and Premium is its
    # effective share of the household policy.
    result = await db.execute(
        select(InsurancePolicyVehicle)
        .join(InsurancePolicy, InsurancePolicy.id == InsurancePolicyVehicle.policy_id)
        .where(InsurancePolicyVehicle.vin == vin)
        .options(*_INSURANCE_LINK_LOADS)
        .order_by(InsurancePolicy.start_date.desc())
    )
    links = result.scalars().all()

    # Generate CSV
    headers = [
        "Provider",
        "Policy Number",
        "Type",
        "Start Date",
        "End Date",
        "Premium",
        "Premium Frequency",
        "Deductible",
        "Coverage Limits",
        "Notes",
    ]

    rows = []
    for link in links:
        policy = link.policy
        share = effective_shares(
            policy.premium_amount, [(item.id, item.premium_share) for item in policy.vehicle_links]
        ).get(link.id)
        rows.append(
            [
                policy.provider or "",
                policy.policy_number or "",
                link.policy_type or "",
                policy.start_date.isoformat() if policy.start_date else "",
                policy.end_date.isoformat() if policy.end_date else "",
                f"{share:.2f}" if share is not None else "",
                policy.premium_frequency or "",
                f"{link.deductible:.2f}" if link.deductible is not None else "",
                coverage_text(link.coverages),
                link.notes or "",
            ]
        )

    output = generate_csv_stream(headers, rows)

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_insurance_{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vehicles/{vin}/tax/csv")
@limiter.limit(settings.rate_limit_exports)
async def export_tax_records_csv(
    request: Request,
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export tax records as CSV"""
    # Verify vehicle exists and user has access
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Get all tax records
    result = await db.execute(
        select(TaxRecord).where(TaxRecord.vin == vin).order_by(TaxRecord.date.desc())
    )
    records = result.scalars().all()

    # Generate CSV
    headers = [
        "Date",
        "Type",
        "Amount",
        "Renewal Date",
        "Notes",
    ]

    rows = []
    for record in records:
        rows.append(
            [
                record.date.isoformat() if record.date else "",
                record.tax_type or "",
                _money_cell(record.amount),
                record.renewal_date.isoformat() if record.renewal_date else "",
                record.notes or "",
            ]
        )

    output = generate_csv_stream(headers, rows)

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_tax_records_{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vehicles/{vin}/notes/csv")
@limiter.limit(settings.rate_limit_exports)
async def export_notes_csv(
    request: Request,
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export notes as CSV"""
    # Verify vehicle exists and user has access
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Get all notes
    result = await db.execute(select(Note).where(Note.vin == vin).order_by(Note.date.desc()))
    records = result.scalars().all()

    # Generate CSV
    headers = [
        "Date",
        "Title",
        "Content",
    ]

    rows = []
    for record in records:
        rows.append(
            [
                record.date.isoformat() if record.date else "",
                record.title or "",
                record.content or "",
            ]
        )

    output = generate_csv_stream(headers, rows)

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_notes_{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vehicles/{vin}/json")
@limiter.limit(settings.rate_limit_exports)
async def export_vehicle_json(
    request: Request,
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export complete vehicle data as JSON"""
    # Verify vehicle exists and user has access
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Get all related records. A visit carries its line items and vendor name;
    # supply usages aren't exported (J4), so they aren't loaded.
    service_result = await db.execute(
        select(ServiceVisit)
        .where(ServiceVisit.vin == vin)
        .options(*_SERVICE_VISIT_EXPORT_LOADS)
        .order_by(ServiceVisit.date.desc())
    )
    service_visits = service_result.scalars().all()

    fuel_result = await db.execute(
        select(FuelRecord).where(FuelRecord.vin == vin).order_by(FuelRecord.date.desc())
    )
    fuel_records = fuel_result.scalars().all()
    station_names = await resolve_station_names(db, list(fuel_records))
    driver_usernames = await _driver_usernames(db, fuel_records)

    odometer_result = await db.execute(
        select(OdometerRecord)
        .where(OdometerRecord.vin == vin)
        .order_by(OdometerRecord.date.desc(), OdometerRecord.id.desc())
    )
    odometer_records = odometer_result.scalars().all()

    hours_result = await db.execute(
        select(HoursRecord).where(HoursRecord.vin == vin).order_by(HoursRecord.date.desc())
    )
    hours_records = hours_result.scalars().all()

    note_result = await db.execute(select(Note).where(Note.vin == vin).order_by(Note.date.desc()))
    notes = note_result.scalars().all()

    insurance_result = await db.execute(
        select(InsurancePolicyVehicle)
        .where(InsurancePolicyVehicle.vin == vin)
        .options(*_INSURANCE_LINK_LOADS)
        .order_by(InsurancePolicyVehicle.id)
    )
    insurance_links = insurance_result.scalars().all()

    def_result = await db.execute(
        select(DEFRecord).where(DEFRecord.vin == vin).order_by(DEFRecord.date.desc())
    )
    def_records = def_result.scalars().all()

    # Build export data
    export_data = {
        "export_version": JSON_SCHEMA_VERSION,
        "units": EXPORT_UNITS,
        "export_date": datetime.now().isoformat(),
        "vehicle": {
            "vin": vehicle.vin,
            "year": vehicle.year,
            "make": vehicle.make,
            "model": vehicle.model,
            "trim": vehicle.trim,
            "color": vehicle.color,
            "license_plate": vehicle.license_plate,
            "purchase_date": vehicle.purchase_date.isoformat() if vehicle.purchase_date else None,
            "purchase_price": float(vehicle.purchase_price) if vehicle.purchase_price else None,
        },
        "service_visits": [
            {
                **_json_columns(v, _SERVICE_VISIT_JSON_EXCLUDE),
                "vendor_name": v.vendor.name if v.vendor else None,
                "line_items": _line_items_json(v),
            }
            for v in service_visits
        ],
        # The station and driver ids go with their names, so a restore keeps a
        # link only where this instance has the same entry or user (R6).
        "fuel_records": [
            {
                **_json_columns(r, _FUEL_JSON_EXCLUDE),
                "station_name": station_names.get(r.id),
                "driver_username": driver_usernames.get(r.driver_user_id)
                if r.driver_user_id
                else None,
            }
            for r in fuel_records
        ],
        "def_records": [_json_columns(r, _DEF_JSON_EXCLUDE) for r in def_records],
        "odometer_records": [_json_columns(r, _ODOMETER_JSON_EXCLUDE) for r in odometer_records],
        "hours_records": [_json_columns(r, _HOURS_JSON_EXCLUDE) for r in hours_records],
        "notes": [
            {
                "date": n.date.isoformat() if n.date else None,
                "title": n.title,
                "content": n.content,
            }
            for n in notes
        ],
        # This vehicle's place on each household policy. `premium_share` is the
        # EFFECTIVE share, so a restore reproduces what this vehicle cost even
        # when the other vehicles on the policy are not part of the backup.
        "insurance_policies": [
            {
                "provider": link.policy.provider,
                "policy_number": link.policy.policy_number,
                "start_date": link.policy.start_date.isoformat(),
                "end_date": link.policy.end_date.isoformat(),
                "premium_frequency": link.policy.premium_frequency,
                "policy_notes": link.policy.notes,
                "policy_fields": [{"label": f.label, "value": f.value} for f in link.policy.fields],
                "policy_type": link.policy_type,
                "premium_share": _insurance_share(link),
                "deductible": float(link.deductible) if link.deductible is not None else None,
                "coverages": [
                    {
                        "coverage_key": c.coverage_key,
                        "limit_primary": float(c.limit_primary)
                        if c.limit_primary is not None
                        else None,
                        "limit_secondary": float(c.limit_secondary)
                        if c.limit_secondary is not None
                        else None,
                        "deductible": float(c.deductible) if c.deductible is not None else None,
                        "premium": float(c.premium) if c.premium is not None else None,
                    }
                    for c in link.coverages
                ],
                "notes": link.notes,
                # Without it a restore silently puts a vehicle that LEFT the
                # policy back on it for the whole term.
                "effective_to": link.effective_to.isoformat() if link.effective_to else None,
                "fields": [{"label": f.label, "value": f.value} for f in link.fields],
            }
            for link in insurance_links
        ],
    }

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_complete_data_{datetime.now().strftime('%Y%m%d')}.json"

    # Convert to JSON string
    json_str = json.dumps(export_data, indent=2)

    return StreamingResponse(
        iter([json_str]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
