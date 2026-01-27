import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import (
    FuelRecord,
    InsurancePolicy,
    Note,
    OdometerRecord,
    Reminder,
    ServiceRecord,
    TaxRecord,
    Vehicle,
    WarrantyRecord,
)
from app.models.user import User
from app.services.auth import require_auth

router = APIRouter(prefix="/api/export", tags=["export"])

# Initialize rate limiter for export endpoints
limiter = Limiter(key_func=get_remote_address)


def generate_csv_stream(headers: list[str], rows: list[list[Any]]) -> io.StringIO:
    """Generate CSV content as string stream"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    output.seek(0)
    return output


@router.get("/vehicles/{vin}/service/csv")
@limiter.limit(settings.rate_limit_exports)
async def export_service_records_csv(
    request: Request,
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export service records as CSV"""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get all service records
    result = await db.execute(
        select(ServiceRecord)
        .where(ServiceRecord.vin == vin)
        .order_by(ServiceRecord.date.desc())
    )
    records = result.scalars().all()

    # Generate CSV
    headers = [
        "Date",
        "Service Type",
        "Description",
        "Mileage",
        "Cost",
        "Vendor Name",
        "Vendor Location",
        "Notes",
    ]

    rows = []
    for record in records:
        rows.append(
            [
                record.date.isoformat() if record.date else "",
                record.service_category or "",
                record.service_type or "",
                record.mileage or "",
                f"{record.cost:.2f}" if record.cost else "",
                record.vendor_name or "",
                record.vendor_location or "",
                record.notes or "",
            ]
        )

    output = generate_csv_stream(headers, rows)

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
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export fuel records as CSV"""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get all fuel records
    result = await db.execute(
        select(FuelRecord).where(FuelRecord.vin == vin).order_by(FuelRecord.date.desc())
    )
    records = result.scalars().all()

    # Generate CSV
    headers = [
        "Date",
        "Mileage",
        "Gallons",
        "Price Per Gallon",
        "Total Cost",
        "Full Tank",
        "Missed Fill-up",
        "Is Hauling",
        "Fuel Type",
        "Notes",
    ]

    rows = []
    for record in records:
        rows.append(
            [
                record.date.isoformat() if record.date else "",
                record.mileage or "",
                f"{record.gallons:.3f}" if record.gallons else "",
                f"{record.price_per_unit:.3f}" if record.price_per_unit else "",
                f"{record.cost:.2f}" if record.cost else "",
                "Yes" if record.is_full_tank else "No",
                "Yes" if record.missed_fillup else "No",
                "Yes" if record.is_hauling else "No",
                record.fuel_type or "",
                record.notes or "",
            ]
        )

    output = generate_csv_stream(headers, rows)

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_fuel_records_{datetime.now().strftime('%Y%m%d')}.csv"

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
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Export odometer records as CSV"""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get all odometer records
    result = await db.execute(
        select(OdometerRecord)
        .where(OdometerRecord.vin == vin)
        .order_by(OdometerRecord.date.desc())
    )
    records = result.scalars().all()

    # Generate CSV
    headers = ["Date", "Reading", "Notes"]

    rows = []
    for record in records:
        rows.append(
            [
                record.date.isoformat() if record.date else "",
                record.mileage or "",
                record.notes or "",
            ]
        )

    output = generate_csv_stream(headers, rows)

    # Generate filename
    filename = f"{vehicle.year}_{vehicle.make}_{vehicle.model}_odometer_records_{datetime.now().strftime('%Y%m%d')}.csv"

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
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get all tax records
    result = await db.execute(
        select(TaxRecord).where(TaxRecord.vin == vin).order_by(TaxRecord.year.desc())
    )
    records = result.scalars().all()

    # Generate CSV
    headers = [
        "Year",
        "Type",
        "Amount",
        "Paid Date",
        "Due Date",
        "Jurisdiction",
        "Notes",
    ]

    rows = []
    for record in records:
        rows.append(
            [
                record.year or "",
                record.tax_type or "",
                f"{record.amount:.2f}" if record.amount else "",
                record.paid_date.isoformat() if record.paid_date else "",
                record.due_date.isoformat() if record.due_date else "",
                record.jurisdiction or "",
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
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get all notes
    result = await db.execute(
        select(Note).where(Note.vin == vin).order_by(Note.date.desc())
    )
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
    # Get vehicle
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get all related records
    service_result = await db.execute(
        select(ServiceRecord)
        .where(ServiceRecord.vin == vin)
        .order_by(ServiceRecord.date.desc())
    )
    service_records = service_result.scalars().all()

    fuel_result = await db.execute(
        select(FuelRecord).where(FuelRecord.vin == vin).order_by(FuelRecord.date.desc())
    )
    fuel_records = fuel_result.scalars().all()

    odometer_result = await db.execute(
        select(OdometerRecord)
        .where(OdometerRecord.vin == vin)
        .order_by(OdometerRecord.date.desc())
    )
    odometer_records = odometer_result.scalars().all()

    reminder_result = await db.execute(
        select(Reminder).where(Reminder.vin == vin).order_by(Reminder.created_at.desc())
    )
    reminders = reminder_result.scalars().all()

    note_result = await db.execute(
        select(Note).where(Note.vin == vin).order_by(Note.date.desc())
    )
    notes = note_result.scalars().all()

    # Build export data
    export_data = {
        "export_date": datetime.now().isoformat(),
        "vehicle": {
            "vin": vehicle.vin,
            "year": vehicle.year,
            "make": vehicle.make,
            "model": vehicle.model,
            "trim": vehicle.trim,
            "color": vehicle.color,
            "license_plate": vehicle.license_plate,
            "purchase_date": vehicle.purchase_date.isoformat()
            if vehicle.purchase_date
            else None,
            "purchase_price": float(vehicle.purchase_price)
            if vehicle.purchase_price
            else None,
        },
        "service_records": [
            {
                "date": r.date.isoformat() if r.date else None,
                "service_category": r.service_category,
                "service_type": r.service_type,
                "mileage": r.mileage,
                "cost": float(r.cost) if r.cost else None,
                "vendor_name": r.vendor_name,
                "vendor_location": r.vendor_location,
                "notes": r.notes,
            }
            for r in service_records
        ],
        "fuel_records": [
            {
                "date": r.date.isoformat() if r.date else None,
                "mileage": r.mileage,
                "gallons": float(r.gallons) if r.gallons else None,
                "price_per_unit": float(r.price_per_unit) if r.price_per_unit else None,
                "cost": float(r.cost) if r.cost else None,
                "is_full_tank": r.is_full_tank,
                "missed_fillup": r.missed_fillup,
                "is_hauling": r.is_hauling,
                "fuel_type": r.fuel_type,
                "notes": r.notes,
            }
            for r in fuel_records
        ],
        "odometer_records": [
            {
                "date": r.date.isoformat() if r.date else None,
                "reading": r.mileage,
                "notes": r.notes,
            }
            for r in odometer_records
        ],
        "reminders": [
            {
                "description": r.description,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "due_mileage": r.due_mileage,
                "is_completed": r.is_completed,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "is_recurring": r.is_recurring,
                "recurrence_days": r.recurrence_days,
                "recurrence_miles": r.recurrence_miles,
                "notes": r.notes,
            }
            for r in reminders
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
