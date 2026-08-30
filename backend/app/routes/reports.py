"""API routes for report generation and export."""

import csv
from datetime import datetime
from io import StringIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    FuelRecord as FuelRecordModel,
)
from app.models.service_visit import ServiceVisit
from app.models.user import User
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.service_visit_service import service_visit_cost_load_options
from app.utils.csv_emission import ODOMETER_COLUMN, VOLUME_COLUMN, cell_for, token_for
from app.utils.csv_safe import sanitize_csv_row
from app.utils.csv_units import (
    ALL_RECORDS_REPORT_HEADERS,
    DISTANCE,
    SERVICE_HISTORY_REPORT_HEADERS,
    VOLUME,
    report_header_row,
)
from app.utils.pdf_generator import PDFReportGenerator
from app.utils.render_context import render_context_for_request

router = APIRouter(prefix="/api/vehicles", tags=["Reports"])


def _service_visits_query(vin: str):
    """Build base query for service visits with eager-loaded line items + vendor.

    Uses service_visit_cost_load_options: this route only ever reads
    calculated_total_cost (needs cost_snapshot), never a usage's Supply row.
    """
    return (
        select(ServiceVisit)
        .options(*service_visit_cost_load_options())
        .where(ServiceVisit.vin == vin)
    )


@router.get("/{vin}/reports/service-history-pdf")
async def download_service_history_pdf(
    vin: str,
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    currency_code: str = Query("USD", description="ISO 4217 code; defaults to USD."),
    locale: str = Query("en-US", description="BCP 47 locale; defaults to en-US."),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Generate and download service history PDF report."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Parse dates
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None

    # Query service visits with line items + vendor
    query = _service_visits_query(vin)
    if start_dt:
        query = query.where(ServiceVisit.date >= start_dt)
    if end_dt:
        query = query.where(ServiceVisit.date <= end_dt)
    query = query.order_by(ServiceVisit.date.desc())

    result = await db.execute(query)
    visits = result.scalars().all()

    # Prepare vehicle info
    vehicle_info = {
        "vin": vehicle.vin,
        "year": vehicle.year,
        "make": vehicle.make,
        "model": vehicle.model,
        "license_plate": vehicle.license_plate,
    }

    # Prepare service records data — one row per line item for detail
    records_data = []
    for visit in visits:
        vendor_name = visit.vendor.name if visit.vendor else None
        if visit.line_items:
            for item in visit.line_items:
                records_data.append(
                    {
                        "date": visit.date,
                        "odometer_km": visit.odometer_km,
                        "service_category": visit.service_category,
                        "service_type": item.description,
                        "cost": item.cost,
                        "vendor_name": vendor_name,
                    }
                )
        else:
            # Visit with no line items (fee-only or notes-only)
            records_data.append(
                {
                    "date": visit.date,
                    "odometer_km": visit.odometer_km,
                    "service_category": visit.service_category,
                    "service_type": visit.notes or "Service",
                    "cost": visit.calculated_total_cost,
                    "vendor_name": vendor_name,
                }
            )

    # Generate PDF
    from app.utils.currency import normalize_pdf_currency_params

    safe_code, safe_locale = normalize_pdf_currency_params(currency_code, locale)
    pdf_gen = PDFReportGenerator(
        render_context=await render_context_for_request(current_user, db),
        currency_code=safe_code,
        locale=safe_locale,
    )
    pdf_buffer = pdf_gen.generate_service_history_pdf(vehicle_info, records_data, start_dt, end_dt)

    # Return as downloadable file
    filename = f"service_history_{vin}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{vin}/reports/sale-history-pdf")
async def download_sale_history_pdf(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Sanitized service history PDF for prospective buyers (no costs/vendors/plate)."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    query = _service_visits_query(vin).order_by(ServiceVisit.date.desc())
    result = await db.execute(query)
    visits = result.scalars().all()

    vehicle_info = {
        "vin": vehicle.vin,
        "year": vehicle.year,
        "make": vehicle.make,
        "model": vehicle.model,
    }

    records_data = []
    for visit in visits:
        if visit.line_items:
            for item in visit.line_items:
                records_data.append(
                    {
                        "date": visit.date,
                        "odometer_km": visit.odometer_km,
                        "service_type": item.description,
                    }
                )
        else:
            records_data.append(
                {
                    "date": visit.date,
                    "odometer_km": visit.odometer_km,
                    # NEVER visit.notes here: this PDF is handed to a buyer and its
                    # header promises costs, vendors and plates are omitted. Notes are
                    # free-form and routinely hold exactly those.
                    "service_type": visit.service_category or "Service",
                }
            )

    pdf_gen = PDFReportGenerator(
        render_context=await render_context_for_request(current_user, db),
    )
    pdf_buffer = pdf_gen.generate_sale_history_pdf(vehicle_info, records_data)
    filename = f"sale_history_{vin[-6:]}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{vin}/reports/cost-summary-pdf")
async def download_cost_summary_pdf(
    vin: str,
    year: int = Query(..., description="Year for cost summary"),
    currency_code: str = Query("USD", description="ISO 4217 code; defaults to USD."),
    locale: str = Query("en-US", description="BCP 47 locale; defaults to en-US."),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Generate and download annual cost summary PDF."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Check if vehicle is motorized (not a trailer or fifth wheel)
    is_motorized = vehicle.vehicle_type not in ["Trailer", "FifthWheel"]

    # Prepare vehicle info
    vehicle_info = {
        "vin": vehicle.vin,
        "year": vehicle.year,
        "make": vehicle.make,
        "model": vehicle.model,
        "vehicle_type": vehicle.vehicle_type,
    }

    # Query cost data for the year
    cost_data = {}

    # Service visits — use total_cost (backfilled by migration 039)
    service_result = await db.execute(
        select(
            func.count(ServiceVisit.id).label("count"),
            func.sum(ServiceVisit.total_cost).label("total"),
        )
        .where(ServiceVisit.vin == vin)
        .where(extract("year", ServiceVisit.date) == year)
    )
    service_stats = service_result.first()
    cost_data["service_count"] = (service_stats.count or 0) if service_stats else 0
    cost_data["service_total"] = (service_stats.total or 0) if service_stats else 0

    # Fuel records - only for motorized vehicles
    if is_motorized:
        fuel_result = await db.execute(
            select(
                func.count(FuelRecordModel.id).label("count"),
                func.sum(FuelRecordModel.cost).label("total"),
            )
            .where(FuelRecordModel.vin == vin)
            .where(extract("year", FuelRecordModel.date) == year)
        )
        fuel_stats = fuel_result.first()
        cost_data["fuel_count"] = (fuel_stats.count or 0) if fuel_stats else 0
        cost_data["fuel_total"] = (fuel_stats.total or 0) if fuel_stats else 0
    else:
        cost_data["fuel_count"] = 0
        cost_data["fuel_total"] = 0

    # Collision visits (service_category='Collision')
    collision_result = await db.execute(
        select(
            func.count(ServiceVisit.id).label("count"),
            func.sum(ServiceVisit.total_cost).label("total"),
        )
        .where(ServiceVisit.vin == vin)
        .where(ServiceVisit.service_category == "Collision")
        .where(extract("year", ServiceVisit.date) == year)
    )
    collision_stats = collision_result.first()
    cost_data["collision_count"] = (collision_stats.count or 0) if collision_stats else 0
    cost_data["collision_total"] = (collision_stats.total or 0) if collision_stats else 0

    # Upgrade visits (service_category='Upgrades')
    upgrade_result = await db.execute(
        select(
            func.count(ServiceVisit.id).label("count"),
            func.sum(ServiceVisit.total_cost).label("total"),
        )
        .where(ServiceVisit.vin == vin)
        .where(ServiceVisit.service_category == "Upgrades")
        .where(extract("year", ServiceVisit.date) == year)
    )
    upgrade_stats = upgrade_result.first()
    cost_data["upgrade_count"] = (upgrade_stats.count or 0) if upgrade_stats else 0
    cost_data["upgrade_total"] = (upgrade_stats.total or 0) if upgrade_stats else 0

    # Generate PDF
    from app.utils.currency import normalize_pdf_currency_params

    safe_code, safe_locale = normalize_pdf_currency_params(currency_code, locale)
    pdf_gen = PDFReportGenerator(
        render_context=await render_context_for_request(current_user, db),
        currency_code=safe_code,
        locale=safe_locale,
    )
    pdf_buffer = pdf_gen.generate_cost_summary_pdf(vehicle_info, cost_data, year)

    # Return as downloadable file
    filename = f"cost_summary_{vin}_{year}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{vin}/reports/tax-deduction-pdf")
async def download_tax_deduction_pdf(
    vin: str,
    year: int = Query(..., description="Tax year"),
    currency_code: str = Query("USD", description="ISO 4217 code; defaults to USD."),
    locale: str = Query("en-US", description="BCP 47 locale; defaults to en-US."),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Generate and download tax deduction report PDF."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Prepare vehicle info
    vehicle_info = {
        "vin": vehicle.vin,
        "year": vehicle.year,
        "make": vehicle.make,
        "model": vehicle.model,
    }

    # Query service visits with line items for the year
    visit_result = await db.execute(
        _service_visits_query(vin)
        .where(extract("year", ServiceVisit.date) == year)
        .order_by(ServiceVisit.date)
    )
    visits = visit_result.scalars().all()

    # Prepare deductible records — one row per line item
    deductible_records = []
    for visit in visits:
        for item in visit.line_items:
            if item.cost:
                deductible_records.append(
                    {
                        "date": visit.date,
                        "category": visit.service_category or "Service",
                        "description": item.description,
                        "cost": item.cost,
                    }
                )

    # Generate PDF
    from app.utils.currency import normalize_pdf_currency_params

    safe_code, safe_locale = normalize_pdf_currency_params(currency_code, locale)
    pdf_gen = PDFReportGenerator(
        render_context=await render_context_for_request(current_user, db),
        currency_code=safe_code,
        locale=safe_locale,
    )
    pdf_buffer = pdf_gen.generate_tax_deduction_pdf(vehicle_info, deductible_records, year)

    # Return as downloadable file
    filename = f"tax_deduction_{vin}_{year}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{vin}/reports/service-history-csv")
async def download_service_history_csv(
    vin: str,
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export service history to CSV, in the caller's own units."""
    # This docstring is the endpoint's public OpenAPI description, so the
    # reasoning lives here instead.
    #
    # A report is a render, so it follows the render policy: the CALLER's
    # units, never the vehicle owner's. There is deliberately no `?units=`
    # parameter. The backup export has one because a user chooses a backup's
    # format; a shared viewer reading a report should simply see their own
    # units, and `get_vehicle_or_403` admits admins and shared users whose
    # preferences differ from the owner's.
    #
    # `show_both` is ignored: a CSV cell is numeric, so it carries one number
    # in one unit, named by its header token. Rendering a counterpart into the
    # cell would make the column text a spreadsheet cannot sum.
    await get_vehicle_or_403(vin, current_user, db)
    context = await render_context_for_request(current_user, db)
    distance_token = token_for(ODOMETER_COLUMN, context.units)

    # Parse dates
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None

    # Query service visits with line items + vendor
    query = _service_visits_query(vin)
    if start_dt:
        query = query.where(ServiceVisit.date >= start_dt)
    if end_dt:
        query = query.where(ServiceVisit.date <= end_dt)
    query = query.order_by(ServiceVisit.date.desc())

    result = await db.execute(query)
    visits = result.scalars().all()

    # Create CSV
    output = StringIO()
    writer = csv.writer(output)

    # Header row and rejection guard share one source: see
    # `csv_units.SERVICE_HISTORY_REPORT_HEADERS`.
    writer.writerow(report_header_row(SERVICE_HISTORY_REPORT_HEADERS, {DISTANCE: distance_token}))

    # Write data - one row per line item.
    #
    # Every numeric cell on both reports tests `is None`, never truthiness.
    # The odometer used to be `visit.odometer_km or ""` and the cost
    # `if item.cost else ""`, and a falsy guard cannot tell a genuine
    # Decimal("0.00") from a missing value: it erased the first service on a
    # new vehicle logged at 0 km, and a warranty repair that really cost
    # $0.00, into the same blank cell a never-recorded value produces.
    # Deliberate, user-visible, in the changelog, and pinned by
    # tests/integration/routes/test_reports_csv_v6_units.py::TestAZeroIsARealValue.
    #
    # export.py's eleven CSV money cells still use the falsy idiom. That is a
    # separate export family this task does not touch, and the two surfaces
    # therefore disagree about zero until it is picked up.
    #
    # These cells format a Decimal directly (`f"{cost:.2f}"`), where they used
    # to cast to float first. That change is PROVABLY INERT, not merely
    # untestable, and this note exists so nobody re-opens it looking for a
    # missing test. ServiceLineItem.cost is Numeric(10, 2) and
    # FuelRecord.cost is Numeric(8, 2), so the value reaching `:.2f` carries
    # at most two decimals on either dialect: PostgreSQL rounds to scale on
    # insert, and SQLAlchemy's Numeric result processor re-quantizes to scale
    # on read for SQLite. Decimal's ROUND_HALF_EVEN and float's binary
    # rounding can only disagree when a third decimal digit exists to round,
    # and the column scale forbids one. There is nothing to observe, at any
    # precision, on any dialect, so there is no test to write.
    for visit in visits:
        vendor_name = visit.vendor.name if visit.vendor else ""
        for item in visit.line_items:
            writer.writerow(
                sanitize_csv_row(
                    [
                        visit.date.strftime("%Y-%m-%d") if visit.date else "",
                        cell_for(ODOMETER_COLUMN, distance_token, visit.odometer_km),
                        visit.service_category or "",
                        item.description or "",
                        f"{item.cost:.2f}" if item.cost is not None else "",
                        vendor_name,
                        visit.notes or "",
                    ]
                )
            )

    # Return as downloadable file
    output.seek(0)
    filename = f"service_history_{vin}_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{vin}/reports/all-records-csv")
async def download_all_records_csv(
    vin: str,
    year: int | None = Query(None, description="Filter by year"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export all maintenance records to CSV, in the caller's own units."""
    # Same render policy as `download_service_history_csv`, and for the same
    # reasons: the caller's units, no `?units=` parameter, `show_both` ignored.
    #
    # Distance and volume resolve independently, so a metric account that
    # prefers US gallons gets `Odometer (km)` alongside `Volume (gal_us)`.
    await get_vehicle_or_403(vin, current_user, db)
    context = await render_context_for_request(current_user, db)
    distance_token = token_for(ODOMETER_COLUMN, context.units)
    volume_token = token_for(VOLUME_COLUMN, context.units)

    # Create CSV
    output = StringIO()
    writer = csv.writer(output)

    # Header row and rejection guard share one source: see
    # `csv_units.ALL_RECORDS_REPORT_HEADERS`.
    writer.writerow(
        report_header_row(
            ALL_RECORDS_REPORT_HEADERS, {DISTANCE: distance_token, VOLUME: volume_token}
        )
    )

    # Query and write service visits with line items
    visit_query = _service_visits_query(vin)
    if year:
        visit_query = visit_query.where(extract("year", ServiceVisit.date) == year)
    visit_result = await db.execute(visit_query.order_by(ServiceVisit.date))
    for visit in visit_result.scalars():
        vendor_name = visit.vendor.name if visit.vendor else ""
        category = visit.service_category or "Maintenance"

        # Determine type label from category
        type_label = "Service"
        if category == "Collision":
            type_label = "Collision"
        elif category == "Upgrades":
            type_label = "Upgrade"

        for item in visit.line_items:
            writer.writerow(
                sanitize_csv_row(
                    [
                        visit.date.strftime("%Y-%m-%d") if visit.date else "",
                        type_label,
                        category,
                        item.description or "",
                        f"{item.cost:.2f}" if item.cost is not None else "",
                        cell_for(ODOMETER_COLUMN, distance_token, visit.odometer_km),
                        vendor_name,
                        # A service visit has no fuel volume. The quantity is
                        # ABSENT, not zero: `0` would claim the visit consumed
                        # nothing and would drag an average over the column.
                        "",
                    ]
                )
            )

    # Query and write fuel records
    fuel_query = select(FuelRecordModel).where(FuelRecordModel.vin == vin)
    if year:
        fuel_query = fuel_query.where(extract("year", FuelRecordModel.date) == year)
    fuel_result = await db.execute(fuel_query.order_by(FuelRecordModel.date))
    for record in fuel_result.scalars():
        writer.writerow(
            sanitize_csv_row(
                [
                    record.date.strftime("%Y-%m-%d") if record.date else "",
                    "Fuel",
                    "Fuel",
                    # T5-R6. This used to be `f"{record.liters}L"`: a raw
                    # canonical litre value with a hardcoded `L`, inside a
                    # free-text column, which is simply wrong for an imperial
                    # reader. The quantity now has its own numeric cell, and
                    # the description says what was bought -- the fuel-row
                    # analogue of a service row's line-item description.
                    record.fuel_type_used or "Fuel",
                    f"{record.cost:.2f}" if record.cost is not None else "",
                    cell_for(ODOMETER_COLUMN, distance_token, record.odometer_km),
                    "",  # No vendor: a fuel record has no service vendor.
                    cell_for(VOLUME_COLUMN, volume_token, record.liters),
                ]
            )
        )

    # Return as downloadable file
    output.seek(0)
    filename = f"all_records_{vin}_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
