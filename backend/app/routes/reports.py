"""API routes for report generation and export."""

import csv
from datetime import datetime
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    FuelRecord as FuelRecordModel,
)
from app.models import (
    ServiceRecord as ServiceRecordModel,
)
from app.models import (
    Vehicle,
)
from app.models.user import User
from app.services.auth import require_auth
from app.utils.pdf_generator import PDFReportGenerator

router = APIRouter(prefix="/api/vehicles", tags=["Reports"])


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

    # Query service records
    query = select(ServiceRecordModel).where(ServiceRecordModel.vin == vin)
    if start_dt:
        query = query.where(ServiceRecordModel.date >= start_dt)
    if end_dt:
        query = query.where(ServiceRecordModel.date <= end_dt)
    query = query.order_by(ServiceRecordModel.date.desc())

    result = await db.execute(query)
    service_records = result.scalars().all()

    # Prepare vehicle info
    vehicle_info = {
        "vin": vehicle.vin,
        "year": vehicle.year,
        "make": vehicle.make,
        "model": vehicle.model,
        "license_plate": vehicle.license_plate,
    }

    # Prepare service records data
    records_data = [
        {
            "date": record.date,
            "mileage": record.mileage,
            "service_category": record.service_category,
            "service_type": record.service_type,
            "cost": record.cost,
            "vendor_name": record.vendor_name,
        }
        for record in service_records
    ]

    # Generate PDF
    pdf_gen = PDFReportGenerator()
    pdf_buffer = pdf_gen.generate_service_history_pdf(
        vehicle_info, records_data, start_dt, end_dt
    )

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

    # Service records
    service_result = await db.execute(
        select(
            func.count(ServiceRecordModel.id).label("count"),
            func.sum(ServiceRecordModel.cost).label("total"),
        )
        .where(ServiceRecordModel.vin == vin)
        .where(extract("year", ServiceRecordModel.date) == year)
    )
    service_stats = service_result.first()
    cost_data["service_count"] = service_stats.count or 0
    cost_data["service_total"] = service_stats.total or 0

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
        cost_data["fuel_count"] = fuel_stats.count or 0
        cost_data["fuel_total"] = fuel_stats.total or 0
    else:
        cost_data["fuel_count"] = 0
        cost_data["fuel_total"] = 0

    # Collision records (now in service_records with service_type='Collision')
    collision_result = await db.execute(
        select(
            func.count(ServiceRecordModel.id).label("count"),
            func.sum(ServiceRecordModel.cost).label("total"),
        )
        .where(ServiceRecordModel.vin == vin)
        .where(ServiceRecordModel.service_type == "Collision")
        .where(extract("year", ServiceRecordModel.date) == year)
    )
    collision_stats = collision_result.first()
    cost_data["collision_count"] = collision_stats.count or 0
    cost_data["collision_total"] = collision_stats.total or 0

    # Upgrade records (now in service_records with service_type='Upgrades')
    upgrade_result = await db.execute(
        select(
            func.count(ServiceRecordModel.id).label("count"),
            func.sum(ServiceRecordModel.cost).label("total"),
        )
        .where(ServiceRecordModel.vin == vin)
        .where(ServiceRecordModel.service_type == "Upgrades")
        .where(extract("year", ServiceRecordModel.date) == year)
    )
    upgrade_stats = upgrade_result.first()
    cost_data["upgrade_count"] = upgrade_stats.count or 0
    cost_data["upgrade_total"] = upgrade_stats.total or 0

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

    # Query potentially deductible service records
    # (excluding routine maintenance like oil changes)
    service_result = await db.execute(
        select(ServiceRecordModel)
        .where(ServiceRecordModel.vin == vin)
        .where(extract("year", ServiceRecordModel.date) == year)
        .where(ServiceRecordModel.cost.is_not(None))
        .order_by(ServiceRecordModel.date)
    )
    service_records = service_result.scalars().all()

    # Prepare deductible records
    deductible_records = [
        {
            "date": record.date,
            "category": record.service_category or "Service",
            "description": record.service_type,
            "cost": record.cost,
        }
        for record in service_records
    ]

    # Generate PDF
    pdf_gen = PDFReportGenerator()
    pdf_buffer = pdf_gen.generate_tax_deduction_pdf(
        vehicle_info, deductible_records, year
    )

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

    # Query service records
    query = select(ServiceRecordModel).where(ServiceRecordModel.vin == vin)
    if start_dt:
        query = query.where(ServiceRecordModel.date >= start_dt)
    if end_dt:
        query = query.where(ServiceRecordModel.date <= end_dt)
    query = query.order_by(ServiceRecordModel.date.desc())

    result = await db.execute(query)
    service_records = result.scalars().all()

    # Create CSV
    output = StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(
        [
            "Date",
            "Mileage",
            "Service Type",
            "Description",
            "Cost",
            "Vendor Name",
            "Vendor Phone",
            "Notes",
        ]
    )

    # Write data
    for record in service_records:
        writer.writerow(
            [
                record.date.strftime("%Y-%m-%d") if record.date else "",
                record.mileage or "",
                record.service_category or "",
                record.service_type or "",
                f"{float(record.cost):.2f}" if record.cost else "",
                record.vendor_name or "",
                record.vendor_phone or "",
                record.notes or "",
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
    writer.writerow(
        ["Date", "Type", "Category", "Description", "Cost", "Mileage", "Vendor"]
    )

    # Query and write service records
    service_query = select(ServiceRecordModel).where(ServiceRecordModel.vin == vin)
    if year:
        service_query = service_query.where(
            extract("year", ServiceRecordModel.date) == year
        )
    service_result = await db.execute(service_query.order_by(ServiceRecordModel.date))
    for record in service_result.scalars():
        writer.writerow(
            [
                record.date.strftime("%Y-%m-%d") if record.date else "",
                "Service",
                record.service_category or "",
                record.service_type or "",
                f"{float(record.cost):.2f}" if record.cost else "",
                record.mileage or "",
                record.vendor_name or "",
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

    # Query and write collision records (now in service_records with service_type='Collision')
    collision_query = (
        select(ServiceRecordModel)
        .where(ServiceRecordModel.vin == vin)
        .where(ServiceRecordModel.service_type == "Collision")
    )
    if year:
        collision_query = collision_query.where(
            extract("year", ServiceRecordModel.date) == year
        )
    collision_result = await db.execute(
        collision_query.order_by(ServiceRecordModel.date)
    )
    for record in collision_result.scalars():
        writer.writerow(
            [
                record.date.strftime("%Y-%m-%d") if record.date else "",
                "Collision",
                "Collision",
                record.service_type or "",
                f"{float(record.cost):.2f}" if record.cost else "",
                record.mileage or "",
                record.vendor_name or "",
            ]
        )

    # Query and write upgrade records (now in service_records with service_type='Upgrades')
    upgrade_query = (
        select(ServiceRecordModel)
        .where(ServiceRecordModel.vin == vin)
        .where(ServiceRecordModel.service_type == "Upgrades")
    )
    if year:
        upgrade_query = upgrade_query.where(
            extract("year", ServiceRecordModel.date) == year
        )
    upgrade_result = await db.execute(upgrade_query.order_by(ServiceRecordModel.date))
    for record in upgrade_result.scalars():
        writer.writerow(
            [
                record.date.strftime("%Y-%m-%d") if record.date else "",
                "Upgrade",
                "Upgrades",
                record.service_type or "",
                f"{float(record.cost):.2f}" if record.cost else "",
                record.mileage or "",
                record.vendor_name or "",
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
