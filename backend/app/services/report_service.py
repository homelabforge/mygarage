"""Report queries and row building for the per-vehicle PDF and CSV reports.

Every function takes the gated `Vehicle`, never a VIN off the request, so the
route's `get_vehicle_or_403` stays the only way in. The routes keep the HTTP
side: query params, the render context, the PDF generator, the filename and
the response.
"""

import csv
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO
from typing import Any

from sqlalchemy import Select, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FuelRecord as FuelRecordModel,
)
from app.models.service_visit import ServiceVisit
from app.models.vehicle import Vehicle
from app.schemas.vehicle import NON_MOTORIZED_VEHICLE_TYPES
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
from app.utils.render_context import RenderContext
from app.utils.vehicle_key import IDENTIFIER_LABELS, display_identifier


def _service_visits_query(vin: str) -> Select[ServiceVisit]:
    """Build base query for service visits with eager-loaded line items + vendor.

    Uses service_visit_cost_load_options: these reports only ever read
    calculated_total_cost (needs cost_snapshot), never a usage's Supply row.
    """
    return (
        select(ServiceVisit)
        .options(*service_visit_cost_load_options())
        .where(ServiceVisit.vin == vin)
    )


def _visit_lines(visit: ServiceVisit) -> list[tuple[str, Decimal | None]]:
    """(description, cost) for each row a visit puts in a report.

    One per line item. A visit with no line items still gets one row: its
    notes (or "Service") and its whole cost, fees included. With no tax or
    fees either it has no cost at all, so the cell stays blank, not 0.00.
    """
    if visit.line_items:
        return [(item.description or "", item.cost) for item in visit.line_items]
    # Supplies hang off line items, so an itemless visit has none.
    charges = (visit.tax_amount, visit.shop_supplies, visit.misc_fees)
    if all(charge is None for charge in charges):
        return [(visit.notes or "Service", None)]
    return [(visit.notes or "Service", visit.calculated_total_cost)]


async def service_history_pdf(
    db: AsyncSession,
    vehicle: Vehicle,
    gen: PDFReportGenerator,
    start_date: date | None,
    end_date: date | None,
) -> BytesIO:
    """Service history PDF, newest first, inside the date window.

    One row per line item, or one for a visit with none.
    """
    vin = vehicle.vin

    # Query service visits with line items + vendor
    query = _service_visits_query(vin)
    if start_date:
        query = query.where(ServiceVisit.date >= start_date)
    if end_date:
        query = query.where(ServiceVisit.date <= end_date)
    query = query.order_by(ServiceVisit.date.desc())

    result = await db.execute(query)
    visits = result.scalars().all()

    # Prepare vehicle info
    vehicle_info = {
        "vin": vehicle.vin,
        # What the PDF prints: the VIN, or a tractor's serial (#226).
        "identifier_label": IDENTIFIER_LABELS.get(display_identifier(vehicle)[0], "VIN"),
        "identifier": display_identifier(vehicle)[1],
        "year": vehicle.year,
        "make": vehicle.make,
        "model": vehicle.model,
        "license_plate": vehicle.license_plate,
    }

    # One row per line item for detail, or one for a visit with none
    records_data: list[dict[str, Any]] = []
    for visit in visits:
        vendor_name = visit.vendor.name if visit.vendor else None
        for description, cost in _visit_lines(visit):
            records_data.append(
                {
                    "date": visit.date,
                    "odometer_km": visit.odometer_km,
                    "service_category": visit.service_category,
                    "service_type": description,
                    "cost": cost,
                    "vendor_name": vendor_name,
                }
            )

    return gen.generate_service_history_pdf(vehicle_info, records_data, start_date, end_date)


async def sale_history_pdf(
    db: AsyncSession,
    vehicle: Vehicle,
    gen: PDFReportGenerator,
) -> BytesIO:
    """Sanitized service history PDF for prospective buyers (no costs/vendors/plate)."""
    query = _service_visits_query(vehicle.vin).order_by(ServiceVisit.date.desc())
    result = await db.execute(query)
    visits = result.scalars().all()

    vehicle_info = {
        "vin": vehicle.vin,
        # What the PDF prints: the VIN, or a tractor's serial (#226).
        "identifier_label": IDENTIFIER_LABELS.get(display_identifier(vehicle)[0], "VIN"),
        "identifier": display_identifier(vehicle)[1],
        "year": vehicle.year,
        "make": vehicle.make,
        "model": vehicle.model,
    }

    records_data: list[dict[str, Any]] = []
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

    return gen.generate_sale_history_pdf(vehicle_info, records_data)


async def cost_summary_pdf(
    db: AsyncSession,
    vehicle: Vehicle,
    gen: PDFReportGenerator,
    year: int,
) -> BytesIO:
    """Annual cost summary PDF: service, fuel, collision and upgrade totals for `year`."""
    vin = vehicle.vin
    is_motorized = vehicle.vehicle_type not in NON_MOTORIZED_VEHICLE_TYPES

    # Prepare vehicle info
    vehicle_info = {
        "vin": vehicle.vin,
        # What the PDF prints: the VIN, or a tractor's serial (#226).
        "identifier_label": IDENTIFIER_LABELS.get(display_identifier(vehicle)[0], "VIN"),
        "identifier": display_identifier(vehicle)[1],
        "year": vehicle.year,
        "make": vehicle.make,
        "model": vehicle.model,
        "vehicle_type": vehicle.vehicle_type,
    }

    # Query cost data for the year
    cost_data: dict[str, Any] = {}

    # total_cost caches calculated_total_cost (every visit write and import
    # recomputes it), so summing it in SQL matches what the history PDF shows.
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

    return gen.generate_cost_summary_pdf(vehicle_info, cost_data, year)


async def tax_deduction_pdf(
    db: AsyncSession,
    vehicle: Vehicle,
    gen: PDFReportGenerator,
    year: int,
) -> BytesIO:
    """Tax deduction PDF: every costed row in `year`, oldest first.

    One row per line item, or one for a visit with none.
    """
    # Prepare vehicle info
    vehicle_info = {
        "vin": vehicle.vin,
        # What the PDF prints: the VIN, or a tractor's serial (#226).
        "identifier_label": IDENTIFIER_LABELS.get(display_identifier(vehicle)[0], "VIN"),
        "identifier": display_identifier(vehicle)[1],
        "year": vehicle.year,
        "make": vehicle.make,
        "model": vehicle.model,
    }

    # Query service visits with line items for the year
    visit_result = await db.execute(
        _service_visits_query(vehicle.vin)
        .where(extract("year", ServiceVisit.date) == year)
        .order_by(ServiceVisit.date)
    )
    visits = visit_result.scalars().all()

    # One row per line item, or one for a visit with none, so a fee-only visit
    # counts. Anything costing nothing (or nothing recorded) still drops.
    deductible_records: list[dict[str, Any]] = []
    for visit in visits:
        for description, cost in _visit_lines(visit):
            if cost:
                deductible_records.append(
                    {
                        "date": visit.date,
                        "category": visit.service_category or "Service",
                        "description": description,
                        "cost": cost,
                    }
                )

    return gen.generate_tax_deduction_pdf(vehicle_info, deductible_records, year)


async def service_history_csv(
    db: AsyncSession,
    vehicle: Vehicle,
    context: RenderContext,
    start_date: date | None,
    end_date: date | None,
) -> str:
    """Service history CSV body in `context`'s units.

    One row per line item, or one for a visit with none.
    """
    distance_token = token_for(ODOMETER_COLUMN, context.units)

    # Query service visits with line items + vendor
    query = _service_visits_query(vehicle.vin)
    if start_date:
        query = query.where(ServiceVisit.date >= start_date)
    if end_date:
        query = query.where(ServiceVisit.date <= end_date)
    query = query.order_by(ServiceVisit.date.desc())

    result = await db.execute(query)
    visits = result.scalars().all()

    # Create CSV
    output = StringIO()
    writer = csv.writer(output)

    # Header row and rejection guard share one source: see
    # `csv_units.SERVICE_HISTORY_REPORT_HEADERS`.
    writer.writerow(report_header_row(SERVICE_HISTORY_REPORT_HEADERS, {DISTANCE: distance_token}))

    # Write data - one row per line item, or one for a visit with none.
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
    # missing test. ServiceLineItem.cost and FuelRecord.cost are both
    # ScaledNumeric(12, 2), so the value reaching `:.2f` carries at most two
    # decimals on either dialect: ScaledNumeric rounds every bind to scale
    # (as PostgreSQL does on insert), and SQLAlchemy's Numeric result
    # processor re-quantizes to scale on read for SQLite. Decimal's
    # ROUND_HALF_EVEN and float's binary rounding can only disagree when a
    # third decimal digit exists to round, and the column scale forbids one.
    # There is nothing to observe, at any precision, on any dialect, so there
    # is no test to write.
    for visit in visits:
        vendor_name = visit.vendor.name if visit.vendor else ""
        for description, cost in _visit_lines(visit):
            writer.writerow(
                sanitize_csv_row(
                    [
                        visit.date.strftime("%Y-%m-%d") if visit.date else "",
                        cell_for(ODOMETER_COLUMN, distance_token, visit.odometer_km),
                        visit.service_category or "",
                        description,
                        f"{cost:.2f}" if cost is not None else "",
                        vendor_name,
                        visit.notes or "",
                    ]
                )
            )

    output.seek(0)
    return output.getvalue()


async def all_records_csv(
    db: AsyncSession,
    vehicle: Vehicle,
    context: RenderContext,
    year: int | None,
) -> str:
    """All-records CSV body in `context`'s units: service rows, then fuel.

    One service row per line item, or one for a visit with none.
    """
    vin = vehicle.vin
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

    # Query and write service visits (an itemless visit still gets a row)
    visit_query = _service_visits_query(vin)
    if year is not None:
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

        for description, cost in _visit_lines(visit):
            writer.writerow(
                sanitize_csv_row(
                    [
                        visit.date.strftime("%Y-%m-%d") if visit.date else "",
                        type_label,
                        category,
                        description,
                        f"{cost:.2f}" if cost is not None else "",
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
    if year is not None:
        fuel_query = fuel_query.where(extract("year", FuelRecordModel.date) == year)
    fuel_result = await db.execute(fuel_query.order_by(FuelRecordModel.date))
    for record in fuel_result.scalars():
        writer.writerow(
            sanitize_csv_row(
                [
                    record.date.strftime("%Y-%m-%d") if record.date else "",
                    "Fuel",
                    "Fuel",
                    # This used to be `f"{record.liters}L"`: a raw canonical
                    # litre value with a hardcoded `L`, inside a free-text
                    # column, which is simply wrong for an imperial reader. The
                    # quantity now has its own numeric cell, and the description
                    # says what was bought: the fuel-row analogue of a service
                    # row's line-item description.
                    record.fuel_type_used or "Fuel",
                    f"{record.cost:.2f}" if record.cost is not None else "",
                    cell_for(ODOMETER_COLUMN, distance_token, record.odometer_km),
                    "",  # No vendor: a fuel record has no service vendor.
                    cell_for(VOLUME_COLUMN, volume_token, record.liters),
                ]
            )
        )

    output.seek(0)
    return output.getvalue()
