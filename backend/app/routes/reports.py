"""API routes for report generation and export."""

import csv
from datetime import datetime
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import (
    FuelRecord as FuelRecordModel,
)
from app.models import (
    Vehicle,
)
from app.models.service_visit import ServiceVisit
from app.models.user import User
from app.services.auth import require_auth
from app.utils.pdf_generator import PDFReportGenerator

router = APIRouter(prefix="/api/vehicles", tags=["Reports"])


def _service_visits_query(vin: str):
    """Build base query for service visits with eager-loaded line items + vendor."""
    return (
        select(ServiceVisit)
        .options(selectinload(ServiceVisit.line_items))
        .options(selectinload(ServiceVisit.vendor))
        .where(ServiceVisit.vin == vin)
    )


@router.get("/{vin}/reports/service-history-pdf")
async def download_service_history_pdf(
    vin: str,
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Generate and download service history PDF report."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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
                        "mileage": visit.mileage,
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
                    "mileage": visit.mileage,
                    "service_category": visit.service_category,
                    "service_type": visit.notes or "Service",
                    "cost": visit.calculated_total_cost,
                    "vendor_name": vendor_name,
                }
            )

    # Generate PDF
    pdf_gen = PDFReportGenerator()
    pdf_buffer = pdf_gen.generate_service_history_pdf(vehicle_info, records_data, start_dt, end_dt)

    # Return as downloadable file
    filename = f"service_history_{vin}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{vin}/reports/cost-summary-pdf")
async def download_cost_summary_pdf(
    vin: str,
    year: int = Query(..., description="Year for cost summary"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Generate and download annual cost summary PDF."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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
    pdf_gen = PDFReportGenerator()
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
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Generate and download tax deduction report PDF."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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
    pdf_gen = PDFReportGenerator()
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
    """Export service history to CSV."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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

    # Write header
    writer.writerow(
        [
            "Date",
            "Mileage",
            "Category",
            "Description",
            "Cost",
            "Vendor",
            "Notes",
        ]
    )

    # Write data — one row per line item
    for visit in visits:
        vendor_name = visit.vendor.name if visit.vendor else ""
        for item in visit.line_items:
            writer.writerow(
                [
                    visit.date.strftime("%Y-%m-%d") if visit.date else "",
                    visit.mileage or "",
                    visit.service_category or "",
                    item.description or "",
                    f"{float(item.cost):.2f}" if item.cost else "",
                    vendor_name,
                    visit.notes or "",
                ]
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
    """Export all maintenance records to CSV."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Create CSV
    output = StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(["Date", "Type", "Category", "Description", "Cost", "Mileage", "Vendor"])

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
                [
                    visit.date.strftime("%Y-%m-%d") if visit.date else "",
                    type_label,
                    category,
                    item.description or "",
                    f"{float(item.cost):.2f}" if item.cost else "",
                    visit.mileage or "",
                    vendor_name,
                ]
            )

    # Query and write fuel records
    fuel_query = select(FuelRecordModel).where(FuelRecordModel.vin == vin)
    if year:
        fuel_query = fuel_query.where(extract("year", FuelRecordModel.date) == year)
    fuel_result = await db.execute(fuel_query.order_by(FuelRecordModel.date))
    for record in fuel_result.scalars():
        writer.writerow(
            [
                record.date.strftime("%Y-%m-%d") if record.date else "",
                "Fuel",
                "Fuel",
                f"{record.gallons}gal" if record.gallons else "",
                f"{float(record.cost):.2f}" if record.cost else "",
                record.mileage or "",
                "",  # No station field in FuelRecord model
            ]
        )

    # Return as downloadable file
    output.seek(0)
    filename = f"all_records_{vin}_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
