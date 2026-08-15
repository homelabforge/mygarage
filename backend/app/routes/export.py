import csv
import io
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
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
from app.utils.csv_safe import sanitize_csv_row
from app.utils.units import UnitConverter

router = APIRouter(prefix="/api/export", tags=["export"])

# Initialize rate limiter for export endpoints
limiter = Limiter(key_func=get_remote_address)

# CSV/JSON export schema version.
# - v2: legacy imperial.
# - v3: SI-metric canonical (issue #67).
# - v4: v3 + extended fuel-tracking columns (issue #69 / v2.27.0-rc2):
#       Filled At, Fuel Type Used, Station, Driver, Payment Method,
#       Trip Type, Outside Temp, OBC values. Purely additive — v3
#       importers continue to work.
# CSV exports prepend a `units_version` column with this value to every row;
# JSON exports include a top-level `"export_version"` + `"units"` field.
# The importer (`app/routes/import_data.py`) reads the marker and falls back
# to v2 imperial conversion when it's missing (legacy v2 backups).
EXPORT_SCHEMA_VERSION = "4"
EXPORT_UNITS = "metric"


def _per_liter_to_per_gallon(value: Any) -> float | None:
    """A canonical per-litre price expressed per US gallon."""
    if value in (None, ""):
        return None
    return UnitConverter.round_result(Decimal(str(value)) * UnitConverter.GALLONS_TO_LITERS)


# Metric header -> (imperial header, value converter).
#
# The imperial names are deliberately the ones `import_data.py` ALREADY reads
# ("Mileage", "Gallons", "Price Per Gallon", "Reading"), so an imperial export
# round-trips through the existing importer and stays readable if the
# `unit_system` marker column is ever stripped by a spreadsheet.
_IMPERIAL_COLUMNS: dict[str, tuple[str, Any]] = {
    "Odometer (km)": ("Mileage", UnitConverter.km_to_miles),
    "Reading (km)": ("Reading", UnitConverter.km_to_miles),
    "Liters": ("Gallons", UnitConverter.liters_to_gallons),
    "Price Per Liter": ("Price Per Gallon", _per_liter_to_per_gallon),
    # DEF keeps the column name — that is the only key its importer reads —
    # but the value still has to move to per-gallon.
    "Price Per Unit": ("Price Per Unit", _per_liter_to_per_gallon),
    "Outside Temp (C)": ("Outside Temp (F)", UnitConverter.celsius_to_fahrenheit),
    "OBC L/100km": ("OBC MPG", UnitConverter.l100km_to_mpg),
    "OBC Avg Speed (km/h)": ("OBC Avg Speed (mph)", UnitConverter.km_to_miles),
}


def to_imperial(headers: list[str], rows: list[list[Any]]) -> tuple[list[str], list[list[Any]]]:
    """Rewrite metric headers and values to imperial.

    Storage is metric-canonical, so every export was metric regardless of the
    account's unit preference — unusable for someone migrating 15 years of
    imperial data into another program (#128). Columns with no unit
    (dates, notes, engine hours, costs) pass through untouched.
    """
    converters: list[Any] = []
    out_headers: list[str] = []
    for header in headers:
        mapped = _IMPERIAL_COLUMNS.get(header)
        if mapped is None:
            out_headers.append(header)
            converters.append(None)
        else:
            imperial_header, converter = mapped
            out_headers.append(imperial_header)
            converters.append(converter)

    out_rows = [
        [
            convert(value) if convert is not None and value not in (None, "") else value
            for value, convert in zip(row, converters, strict=True)
        ]
        for row in rows
    ]
    return out_headers, out_rows


def generate_csv_stream(
    headers: list[str], rows: list[list[Any]], unit_system: str = EXPORT_UNITS
) -> io.StringIO:
    """Generate CSV content with leading `units_version` + `unit_system` columns.

    `units_version` is the SCHEMA version; `unit_system` says which units the
    values are actually in. They are separate because they change for different
    reasons — conflating them is what let a v4 metric export be re-imported as
    imperial (#128). The importer reads `unit_system` first.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["units_version", "unit_system", *headers])
    # Neutralise CSV formula-injection in every data cell (header is static).
    writer.writerows([sanitize_csv_row([EXPORT_SCHEMA_VERSION, unit_system, *row]) for row in rows])
    output.seek(0)
    return output


@router.get("/vehicles/{vin}/service/csv")
@limiter.limit(settings.rate_limit_exports)
async def export_service_records_csv(
    request: Request,
    vin: str,
    units: str = Query(
        EXPORT_UNITS,
        pattern="^(metric|imperial)$",
        description="Unit system for the exported values. Defaults to metric "
        "(canonical storage); `imperial` converts distance, volume, price-per-volume "
        "and temperature, and renames those columns accordingly.",
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
                        visit.odometer_km or "",
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
                    visit.odometer_km or "",
                    engine_hours,
                    f"{visit.calculated_total_cost:.2f}" if visit.calculated_total_cost else "",
                    vendor_name,
                    visit.notes or "",
                ]
            )

    if units == "imperial":
        headers, rows = to_imperial(headers, rows)
    output = generate_csv_stream(headers, rows, unit_system=units)

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
    units: str = Query(
        EXPORT_UNITS,
        pattern="^(metric|imperial)$",
        description="Unit system for the exported values. Defaults to metric "
        "(canonical storage); `imperial` converts distance, volume, price-per-volume "
        "and temperature, and renames those columns accordingly.",
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
    # The ``EXPORT_SCHEMA_VERSION`` bump from "3" to "4" signals importers
    # that the new columns may be present. v3-format imports keep working
    # because the extension is purely additive.
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
        "Fuel Type",
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
                record.odometer_km or "",
                # Dimensionless — no unit conversion. `is not None` (not `or ""`)
                # so a genuine 0.0 reading isn't dropped, matching outside_temp_c
                # / obc_l_per_100km below.
                f"{record.engine_hours:.1f}" if record.engine_hours is not None else "",
                f"{record.liters:.3f}" if record.liters else "",
                f"{record.price_per_unit:.3f}" if record.price_per_unit else "",
                f"{record.rebate:.2f}" if record.rebate else "",
                f"{record.cost:.2f}" if record.cost else "",
                "Yes" if record.is_full_tank else "No",
                "Yes" if record.missed_fillup else "No",
                "Yes" if record.is_hauling else "No",
                record.fuel_type or "",
                record.fuel_type_used or "",
                record.station_address_book_id or "",
                station_names.get(record.id) or "",
                record.driver_user_id or "",
                record.driver_name_freetext or "",
                record.payment_method or "",
                record.trip_type or "",
                f"{record.outside_temp_c:.1f}" if record.outside_temp_c is not None else "",
                f"{record.obc_l_per_100km:.2f}" if record.obc_l_per_100km is not None else "",
                f"{record.obc_avg_speed_kmh:.1f}" if record.obc_avg_speed_kmh is not None else "",
                record.obc_trip_duration_s or "",
                f"{record.soc_start_pct:.1f}" if record.soc_start_pct is not None else "",
                f"{record.soc_end_pct:.1f}" if record.soc_end_pct is not None else "",
                record.charge_level or "",
                record.charge_location or "",
                f"{record.battery_soh_pct:.1f}" if record.battery_soh_pct is not None else "",
                record.notes or "",
            ]
        )

    if units == "imperial":
        headers, rows = to_imperial(headers, rows)
    output = generate_csv_stream(headers, rows, unit_system=units)

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
    units: str = Query(
        EXPORT_UNITS,
        pattern="^(metric|imperial)$",
        description="Unit system for the exported values. Defaults to metric "
        "(canonical storage); `imperial` converts distance, volume, price-per-volume "
        "and temperature, and renames those columns accordingly.",
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
                record.odometer_km or "",
                f"{record.liters:.3f}" if record.liters else "",
                f"{record.price_per_unit:.3f}" if record.price_per_unit else "",
                f"{record.cost:.2f}" if record.cost else "",
                f"{record.fill_level:.2f}" if record.fill_level else "",
                record.source or "",
                record.brand or "",
                record.notes or "",
            ]
        )

    if units == "imperial":
        headers, rows = to_imperial(headers, rows)
    output = generate_csv_stream(headers, rows, unit_system=units)

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
    units: str = Query(
        EXPORT_UNITS,
        pattern="^(metric|imperial)$",
        description="Unit system for the exported values. Defaults to metric "
        "(canonical storage); `imperial` converts distance, volume, price-per-volume "
        "and temperature, and renames those columns accordingly.",
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
                record.odometer_km or "",
                record.notes or "",
            ]
        )

    if units == "imperial":
        headers, rows = to_imperial(headers, rows)
    output = generate_csv_stream(headers, rows, unit_system=units)

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
        "export_version": EXPORT_SCHEMA_VERSION,
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
                "fuel_type": r.fuel_type,
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
