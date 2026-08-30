import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet
from app.database import get_db
from app.models import (
    DEFRecord,
    FuelRecord,
    HoursRecord,
    InsurancePolicy,
    Note,
    OdometerRecord,
    ServiceVisit,
    TaxRecord,
    WarrantyRecord,
)
from app.models.user import User
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.fuel_service import resolve_station_names
from app.services.service_visit_service import service_visit_cost_load_options
from app.utils.csv_emission import apply_unit_set, marker_for
from app.utils.csv_safe import sanitize_csv_row
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
CSV_SCHEMA_VERSION = "6"
JSON_SCHEMA_VERSION = "5"
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
    requested: str | None, current_user: User | None, db: AsyncSession
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
    return (await render_context_for_request(current_user, db)).units


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

    # Get all service visits with line items (+ supply usages) and vendor.
    # service_visit_cost_load_options: this route only reads
    # calculated_total_cost (needs cost_snapshot), never a usage's Supply row.
    result = await db.execute(
        select(ServiceVisit)
        .where(ServiceVisit.vin == vin)
        .options(*service_visit_cost_load_options())
        .order_by(ServiceVisit.date.desc())
    )
    visits = result.scalars().all()

    # Generate CSV — one row per line item for backward-compatible format
    headers = [
        "Date",
        "Category",
        "Description",
        "Odometer (km)",
        "Engine Hours",
        "Cost",
        "Vendor",
        "Notes",
    ]

    rows = []
    for visit in visits:
        vendor_name = visit.vendor.name if visit.vendor else ""
        # engine_hours: hour-metered vehicles (ATVs, side-by-sides, equipment).
        # Dimensionless — no unit conversion. `is not None` (not `or ""`) so a
        # genuine 0.0 reading isn't dropped, matching fuel's outside_temp_c/
        # obc_l_per_100km convention.
        engine_hours = f"{visit.engine_hours:.1f}" if visit.engine_hours is not None else ""
        if visit.line_items:
            for item in visit.line_items:
                rows.append(
                    [
                        visit.date.isoformat() if visit.date else "",
                        visit.service_category or "",
                        item.description or "",
                        visit.odometer_km or None,
                        engine_hours,
                        f"{item.cost:.2f}" if item.cost else "",
                        vendor_name,
                        item.notes or visit.notes or "",
                    ]
                )
        else:
            # Visit with no line items — single row with visit-level data
            rows.append(
                [
                    visit.date.isoformat() if visit.date else "",
                    visit.service_category or "",
                    "",
                    visit.odometer_km or None,
                    engine_hours,
                    f"{visit.calculated_total_cost:.2f}" if visit.calculated_total_cost else "",
                    vendor_name,
                    visit.notes or "",
                ]
            )

    output = build_csv(headers, rows, await resolve_export_units(units, current_user, db))

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
                # same column. `or None` keeps the pre-v6 behaviour of
                # blanking a falsy reading.
                record.odometer_km or None,
                # Dimensionless — no unit conversion. `is not None` (not `or ""`)
                # so a genuine 0.0 reading isn't dropped, matching outside_temp_c
                # / obc_l_per_100km below.
                f"{record.engine_hours:.1f}" if record.engine_hours is not None else "",
                record.liters or None,
                record.price_per_unit or None,
                f"{record.rebate:.2f}" if record.rebate else "",
                f"{record.cost:.2f}" if record.cost else "",
                "Yes" if record.is_full_tank else "No",
                "Yes" if record.missed_fillup else "No",
                "Yes" if record.is_hauling else "No",
                record.fuel_type_used or "",
                record.station_address_book_id or "",
                station_names.get(record.id) or "",
                record.driver_user_id or "",
                record.driver_name_freetext or "",
                record.payment_method or "",
                record.trip_type or "",
                # Unit-bearing, and `is not None` rather than truthy: a
                # genuine 0.0 C or 0.0 km/h is a real reading. `csv_emission`
                # renders `None` as a blank cell.
                record.outside_temp_c,
                record.obc_l_per_100km,
                record.obc_avg_speed_kmh,
                record.obc_trip_duration_s or "",
                f"{record.soc_start_pct:.1f}" if record.soc_start_pct is not None else "",
                f"{record.soc_end_pct:.1f}" if record.soc_end_pct is not None else "",
                record.charge_level or "",
                record.charge_location or "",
                f"{record.battery_soh_pct:.1f}" if record.battery_soh_pct is not None else "",
                record.notes or "",
            ]
        )

    output = build_csv(headers, rows, await resolve_export_units(units, current_user, db))

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
                record.odometer_km or None,
                record.liters or None,
                record.price_per_unit or None,
                f"{record.cost:.2f}" if record.cost else "",
                f"{record.fill_level:.2f}" if record.fill_level else "",
                record.source or "",
                record.brand or "",
                record.notes or "",
            ]
        )

    output = build_csv(headers, rows, await resolve_export_units(units, current_user, db))

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
        select(OdometerRecord).where(OdometerRecord.vin == vin).order_by(OdometerRecord.date.desc())
    )
    records = result.scalars().all()

    # Generate CSV
    headers = ["Date", "Reading (km)", "Notes"]

    rows = []
    for record in records:
        rows.append(
            [
                record.date.isoformat() if record.date else "",
                record.odometer_km or None,
                record.notes or "",
            ]
        )

    output = build_csv(headers, rows, await resolve_export_units(units, current_user, db))

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
    headers = [
        "Provider",
        "Type",
        "Coverage",
        "Start Date",
        "End Date",
        "Cost",
        "Deductible",
        "Max Claims",
        "Terms",
        "Notes",
    ]

    rows = []
    for record in records:
        rows.append(
            [
                record.provider or "",
                record.warranty_type or "",
                record.coverage or "",
                record.start_date.isoformat() if record.start_date else "",
                record.end_date.isoformat() if record.end_date else "",
                f"{record.cost:.2f}" if record.cost else "",
                f"{record.deductible:.2f}" if record.deductible else "",
                record.max_claims or "",
                record.terms or "",
                record.notes or "",
            ]
        )

    output = generate_csv_stream(headers, rows)

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_warranties_{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

    # Get all insurance records
    result = await db.execute(
        select(InsurancePolicy)
        .where(InsurancePolicy.vin == vin)
        .order_by(InsurancePolicy.start_date.desc())
    )
    records = result.scalars().all()

    # Generate CSV
    headers = [
        "Provider",
        "Policy Number",
        "Type",
        "Start Date",
        "End Date",
        "Premium",
        "Deductible",
        "Coverage Limits",
        "Notes",
    ]

    rows = []
    for record in records:
        rows.append(
            [
                record.provider or "",
                record.policy_number or "",
                record.policy_type or "",
                record.start_date.isoformat() if record.start_date else "",
                record.end_date.isoformat() if record.end_date else "",
                f"{record.premium:.2f}" if record.premium else "",
                f"{record.deductible:.2f}" if record.deductible else "",
                record.coverage_limits or "",
                record.notes or "",
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
                f"{record.amount:.2f}" if record.amount else "",
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

    # Get all related records. service_visit_cost_load_options: this route
    # only reads calculated_total_cost (needs cost_snapshot), never a usage's
    # Supply row.
    service_result = await db.execute(
        select(ServiceVisit)
        .where(ServiceVisit.vin == vin)
        .options(*service_visit_cost_load_options())
        .order_by(ServiceVisit.date.desc())
    )
    service_visits = service_result.scalars().all()

    fuel_result = await db.execute(
        select(FuelRecord).where(FuelRecord.vin == vin).order_by(FuelRecord.date.desc())
    )
    fuel_records = fuel_result.scalars().all()

    odometer_result = await db.execute(
        select(OdometerRecord).where(OdometerRecord.vin == vin).order_by(OdometerRecord.date.desc())
    )
    odometer_records = odometer_result.scalars().all()

    hours_result = await db.execute(
        select(HoursRecord).where(HoursRecord.vin == vin).order_by(HoursRecord.date.desc())
    )
    hours_records = hours_result.scalars().all()

    note_result = await db.execute(select(Note).where(Note.vin == vin).order_by(Note.date.desc()))
    notes = note_result.scalars().all()

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
        # Keep "service_records" key for backward-compatible JSON re-import
        "service_records": [
            {
                "date": v.date.isoformat() if v.date else None,
                "service_category": v.service_category,
                "service_type": v.line_items[0].description if v.line_items else None,
                "odometer_km": float(v.odometer_km) if v.odometer_km is not None else None,
                "cost": float(v.calculated_total_cost) if v.calculated_total_cost else None,
                "vendor_name": v.vendor.name if v.vendor else None,
                "notes": v.notes,
            }
            for v in service_visits
        ],
        "fuel_records": [
            {
                "date": r.date.isoformat() if r.date else None,
                "odometer_km": float(r.odometer_km) if r.odometer_km is not None else None,
                "liters": float(r.liters) if r.liters else None,
                "price_per_unit": float(r.price_per_unit) if r.price_per_unit else None,
                # Round-trips so a restored backup still knows what the price is
                # measured against; without it the import had to guess (#128).
                "price_basis": r.price_basis,
                "rebate": float(r.rebate) if r.rebate else None,
                "cost": float(r.cost) if r.cost else None,
                "is_full_tank": r.is_full_tank,
                "missed_fillup": r.missed_fillup,
                "is_hauling": r.is_hauling,
                "fuel_type_used": r.fuel_type_used,
                "notes": r.notes,
            }
            for r in fuel_records
        ],
        "def_records": [
            {
                "date": r.date.isoformat() if r.date else None,
                "odometer_km": float(r.odometer_km) if r.odometer_km is not None else None,
                "liters": float(r.liters) if r.liters else None,
                "price_per_unit": float(r.price_per_unit) if r.price_per_unit else None,
                "cost": float(r.cost) if r.cost else None,
                "fill_level": float(r.fill_level) if r.fill_level else None,
                "source": r.source,
                "brand": r.brand,
                "notes": r.notes,
            }
            for r in def_records
        ],
        "odometer_records": [
            {
                "date": r.date.isoformat() if r.date else None,
                "reading": float(r.odometer_km) if r.odometer_km is not None else None,
                "notes": r.notes,
            }
            for r in odometer_records
        ],
        "hours_records": [
            {
                "date": r.date.isoformat() if r.date else None,
                "engine_hours": float(r.engine_hours) if r.engine_hours is not None else None,
                "notes": r.notes,
                "source": r.source,
            }
            for r in hours_records
        ],
        "notes": [
            {
                "date": n.date.isoformat() if n.date else None,
                "title": n.title,
                "content": n.content,
            }
            for n in notes
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
