"""Data import routes for MyGarage."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, date as date_type
from slowapi import Limiter
from slowapi.util import get_remote_address
import csv
import io
import json
from typing import Optional
from decimal import Decimal, InvalidOperation

from app.database import get_db
from app.models.user import User
from app.services.auth import require_auth
from app.models import (
    Vehicle, ServiceRecord, FuelRecord, OdometerRecord, Reminder, Note,
    WarrantyRecord, InsurancePolicy, TaxRecord
)
from app.config import settings
from app.utils.file_validation import validate_csv_upload

router = APIRouter(prefix="/api/import", tags=["import"])
limiter = Limiter(key_func=get_remote_address)


class ImportResult:
    """Result of an import operation."""
    def __init__(self):
        self.success_count = 0
        self.error_count = 0
        self.skipped_count = 0
        self.errors = []

    def add_success(self):
        self.success_count += 1

    def add_error(self, row_num: int, message: str):
        self.error_count += 1
        self.errors.append(f"Row {row_num}: {message}")

    def add_skip(self):
        self.skipped_count += 1

    def to_dict(self):
        return {
            "success_count": self.success_count,
            "error_count": self.error_count,
            "skipped_count": self.skipped_count,
            "errors": self.errors,
            "total_processed": self.success_count + self.error_count + self.skipped_count
        }


def parse_date(date_str: str) -> Optional[date_type]:
    """Parse date string in various formats."""
    if not date_str or date_str.strip() == "":
        return None

    date_str = date_str.strip()

    # Try different date formats
    formats = [
        "%Y-%m-%d",           # 2025-01-15
        "%m/%d/%Y",           # 01/15/2025
        "%m-%d-%Y",           # 01-15-2025
        "%Y/%m/%d",           # 2025/01/15
        "%d/%m/%Y",           # 15/01/2025
        "%b %d, %Y",          # Jan 15, 2025
        "%B %d, %Y",          # January 15, 2025
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Unable to parse date: {date_str}")


def parse_decimal(value: str) -> Optional[Decimal]:
    """Parse decimal value from string."""
    if not value or value.strip() == "":
        return None

    try:
        return Decimal(value.strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid decimal value: {value}")


def parse_int(value: str) -> Optional[int]:
    """Parse integer value from string."""
    if not value or value.strip() == "":
        return None

    try:
        return int(value.strip())
    except ValueError:
        raise ValueError(f"Invalid integer value: {value}")


def parse_bool(value: str) -> bool:
    """Parse boolean value from string."""
    if not value:
        return False

    value = value.strip().lower()
    return value in ("true", "yes", "1", "y")


@router.post("/vehicles/{vin}/service/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_service_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """Import service records from CSV file."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader = csv.DictReader(io.StringIO(csv_data))

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):  # Start at 2 (header is row 1)
        try:
            # Parse required fields
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            # Parse optional fields
            service_type = row.get("Service Type", "").strip() or None
            description = row.get("Description", "").strip() or None
            mileage = parse_int(row.get("Mileage", ""))
            cost = parse_decimal(row.get("Cost", ""))
            vendor_name = row.get("Vendor Name", "").strip() or None
            vendor_location = row.get("Vendor Location", "").strip() or None
            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested
            if skip_duplicates:
                existing = await db.execute(
                    select(ServiceRecord).where(
                        ServiceRecord.vin == vin,
                        ServiceRecord.date == date,
                        ServiceRecord.service_type == service_type,
                        ServiceRecord.mileage == mileage
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record
            record = ServiceRecord(
                vin=vin,
                date=date,
                service_type=service_type,
                description=description,
                mileage=mileage,
                cost=cost,
                vendor_name=vendor_name,
                vendor_location=vendor_location,
                notes=notes
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            # Intentional catch-all: per-row errors should not stop the import
            import_result.add_error(row_num, str(e))

    await db.commit()

    return import_result.to_dict()


@router.post("/vehicles/{vin}/fuel/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_fuel_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """Import fuel records from CSV file."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader = csv.DictReader(io.StringIO(csv_data))

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            # Parse required fields
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            # Parse optional fields
            mileage = parse_int(row.get("Mileage", ""))
            gallons = parse_decimal(row.get("Gallons", ""))
            price_per_unit = parse_decimal(row.get("Price Per Gallon", "") or row.get("Price/Gal", ""))
            cost = parse_decimal(row.get("Total Cost", "") or row.get("Cost", ""))
            is_full_tank = parse_bool(row.get("Full Tank", "True"))
            missed_fillup = parse_bool(row.get("Missed Fill-up", "False"))
            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested
            if skip_duplicates:
                existing = await db.execute(
                    select(FuelRecord).where(
                        FuelRecord.vin == vin,
                        FuelRecord.date == date,
                        FuelRecord.mileage == mileage
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record
            record = FuelRecord(
                vin=vin,
                date=date,
                mileage=mileage,
                gallons=gallons,
                price_per_unit=price_per_unit,
                cost=cost,
                is_full_tank=is_full_tank,
                missed_fillup=missed_fillup,
                notes=notes
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            import_result.add_error(row_num, str(e))

    await db.commit()

    return import_result.to_dict()


@router.post("/vehicles/{vin}/odometer/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_odometer_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """Import odometer records from CSV file."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader = csv.DictReader(io.StringIO(csv_data))

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            # Parse required fields
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            mileage = parse_int(row.get("Reading", "") or row.get("Mileage", ""))
            if mileage is None:
                import_result.add_error(row_num, "Reading/Mileage is required")
                continue

            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested
            if skip_duplicates:
                existing = await db.execute(
                    select(OdometerRecord).where(
                        OdometerRecord.vin == vin,
                        OdometerRecord.date == date,
                        OdometerRecord.mileage == mileage
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record
            record = OdometerRecord(
                vin=vin,
                date=date,
                mileage=mileage,
                notes=notes
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            import_result.add_error(row_num, str(e))

    await db.commit()

    return import_result.to_dict()


@router.post("/vehicles/{vin}/warranties/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_warranties_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """Import warranties from CSV file."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader = csv.DictReader(io.StringIO(csv_data))

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            provider = row.get("Provider", "").strip() or None
            warranty_type = row.get("Type", "").strip() or None
            coverage = row.get("Coverage", "").strip() or None
            start_date = parse_date(row.get("Start Date", ""))
            end_date = parse_date(row.get("End Date", ""))
            cost = parse_decimal(row.get("Cost", ""))
            deductible = parse_decimal(row.get("Deductible", ""))
            max_claims = parse_int(row.get("Max Claims", ""))
            terms = row.get("Terms", "").strip() or None
            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested
            if skip_duplicates and provider and start_date:
                existing = await db.execute(
                    select(WarrantyRecord).where(
                        WarrantyRecord.vin == vin,
                        WarrantyRecord.provider == provider,
                        WarrantyRecord.start_date == start_date
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record
            record = WarrantyRecord(
                vin=vin,
                provider=provider,
                warranty_type=warranty_type,
                coverage=coverage,
                start_date=start_date,
                end_date=end_date,
                cost=cost,
                deductible=deductible,
                max_claims=max_claims,
                terms=terms,
                notes=notes
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            import_result.add_error(row_num, str(e))

    await db.commit()

    return import_result.to_dict()


@router.post("/vehicles/{vin}/insurance/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_insurance_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """Import insurance records from CSV file."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader = csv.DictReader(io.StringIO(csv_data))

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            provider = row.get("Provider", "").strip() or None
            policy_number = row.get("Policy Number", "").strip() or None
            policy_type = row.get("Type", "").strip() or None
            start_date = parse_date(row.get("Start Date", ""))
            end_date = parse_date(row.get("End Date", ""))
            premium = parse_decimal(row.get("Premium", ""))
            deductible = parse_decimal(row.get("Deductible", ""))
            coverage_limits = row.get("Coverage Limits", "").strip() or None
            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested
            if skip_duplicates and policy_number:
                existing = await db.execute(
                    select(InsurancePolicy).where(
                        InsurancePolicy.vin == vin,
                        InsurancePolicy.policy_number == policy_number
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record
            record = InsurancePolicy(
                vin=vin,
                provider=provider,
                policy_number=policy_number,
                policy_type=policy_type,
                start_date=start_date,
                end_date=end_date,
                premium=premium,
                deductible=deductible,
                coverage_limits=coverage_limits,
                notes=notes
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            import_result.add_error(row_num, str(e))

    await db.commit()

    return import_result.to_dict()


@router.post("/vehicles/{vin}/tax/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_tax_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """Import tax records from CSV file."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader = csv.DictReader(io.StringIO(csv_data))

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            year = parse_int(row.get("Year", ""))
            tax_type = row.get("Type", "").strip() or None
            amount = parse_decimal(row.get("Amount", ""))
            paid_date = parse_date(row.get("Paid Date", ""))
            due_date = parse_date(row.get("Due Date", ""))
            jurisdiction = row.get("Jurisdiction", "").strip() or None
            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested
            if skip_duplicates and year and tax_type:
                existing = await db.execute(
                    select(TaxRecord).where(
                        TaxRecord.vin == vin,
                        TaxRecord.year == year,
                        TaxRecord.tax_type == tax_type
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record
            record = TaxRecord(
                vin=vin,
                year=year,
                tax_type=tax_type,
                amount=amount,
                paid_date=paid_date,
                due_date=due_date,
                jurisdiction=jurisdiction,
                notes=notes
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            import_result.add_error(row_num, str(e))

    await db.commit()

    return import_result.to_dict()


@router.post("/vehicles/{vin}/notes/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_notes_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """Import notes from CSV file."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader = csv.DictReader(io.StringIO(csv_data))

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            date = parse_date(row.get("Date", ""))
            title = row.get("Title", "").strip() or None
            content = row.get("Content", "").strip() or None

            # Check for duplicates if requested
            if skip_duplicates and date and title:
                existing = await db.execute(
                    select(Note).where(
                        Note.vin == vin,
                        Note.date == date,
                        Note.title == title
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record
            record = Note(
                vin=vin,
                date=date,
                title=title,
                content=content
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            import_result.add_error(row_num, str(e))

    await db.commit()

    return import_result.to_dict()


@router.post("/vehicles/{vin}/json")
async def import_vehicle_json(
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """Import complete vehicle data from JSON file."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Check file size BEFORE reading into memory to prevent DoS
    MAX_IMPORT_SIZE = 50 * 1024 * 1024  # 50MB max for import files
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Seek back to beginning

    if file_size > MAX_IMPORT_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds maximum of {MAX_IMPORT_SIZE // (1024 * 1024)}MB"
        )

    # Now read and parse JSON
    contents = await file.read()
    try:
        data = json.loads(contents.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

    results = {
        "service_records": {"success": 0, "errors": 0, "skipped": 0},
        "fuel_records": {"success": 0, "errors": 0, "skipped": 0},
        "odometer_records": {"success": 0, "errors": 0, "skipped": 0},
        "reminders": {"success": 0, "errors": 0, "skipped": 0},
        "notes": {"success": 0, "errors": 0, "skipped": 0},
        "errors": []
    }

    # Import service records
    for idx, record_data in enumerate(data.get("service_records", [])):
        try:
            date = datetime.fromisoformat(record_data["date"]).date()

            if skip_duplicates:
                existing = await db.execute(
                    select(ServiceRecord).where(
                        ServiceRecord.vin == vin,
                        ServiceRecord.date == date,
                        ServiceRecord.service_type == record_data.get("service_type"),
                        ServiceRecord.mileage == record_data.get("mileage")
                    )
                )
                if existing.scalar_one_or_none():
                    results["service_records"]["skipped"] += 1
                    continue

            record = ServiceRecord(
                vin=vin,
                date=date,
                service_type=record_data.get("service_type"),
                description=record_data.get("description"),
                mileage=record_data.get("mileage"),
                cost=Decimal(str(record_data["cost"])) if record_data.get("cost") else None,
                vendor_name=record_data.get("vendor_name"),
                vendor_location=record_data.get("vendor_location"),
                notes=record_data.get("notes")
            )
            db.add(record)
            results["service_records"]["success"] += 1
        except Exception as e:
            results["service_records"]["errors"] += 1
            results["errors"].append(f"Service record {idx}: {str(e)}")

    # Import fuel records
    for idx, record_data in enumerate(data.get("fuel_records", [])):
        try:
            date = datetime.fromisoformat(record_data["date"]).date()

            if skip_duplicates:
                existing = await db.execute(
                    select(FuelRecord).where(
                        FuelRecord.vin == vin,
                        FuelRecord.date == date,
                        FuelRecord.mileage == record_data.get("mileage")
                    )
                )
                if existing.scalar_one_or_none():
                    results["fuel_records"]["skipped"] += 1
                    continue

            record = FuelRecord(
                vin=vin,
                date=date,
                mileage=record_data.get("mileage"),
                gallons=Decimal(str(record_data["gallons"])) if record_data.get("gallons") else None,
                price_per_unit=Decimal(str(record_data["price_per_unit"])) if record_data.get("price_per_unit") else None,
                cost=Decimal(str(record_data["cost"])) if record_data.get("cost") else None,
                is_full_tank=record_data.get("is_full_tank", True),
                missed_fillup=record_data.get("missed_fillup", False),
                notes=record_data.get("notes")
            )
            db.add(record)
            results["fuel_records"]["success"] += 1
        except Exception as e:
            results["fuel_records"]["errors"] += 1
            results["errors"].append(f"Fuel record {idx}: {str(e)}")

    # Import odometer records
    for idx, record_data in enumerate(data.get("odometer_records", [])):
        try:
            date = datetime.fromisoformat(record_data["date"]).date()

            if skip_duplicates:
                existing = await db.execute(
                    select(OdometerRecord).where(
                        OdometerRecord.vin == vin,
                        OdometerRecord.date == date,
                        OdometerRecord.mileage == record_data["reading"]
                    )
                )
                if existing.scalar_one_or_none():
                    results["odometer_records"]["skipped"] += 1
                    continue

            record = OdometerRecord(
                vin=vin,
                date=date,
                mileage=record_data["reading"],
                notes=record_data.get("notes")
            )
            db.add(record)
            results["odometer_records"]["success"] += 1
        except Exception as e:
            results["odometer_records"]["errors"] += 1
            results["errors"].append(f"Odometer record {idx}: {str(e)}")

    # Import reminders
    for idx, reminder_data in enumerate(data.get("reminders", [])):
        try:
            due_date = datetime.fromisoformat(reminder_data["due_date"]).date() if reminder_data.get("due_date") else None

            reminder = Reminder(
                vin=vin,
                description=reminder_data["description"],
                due_date=due_date,
                due_mileage=reminder_data.get("due_mileage"),
                is_completed=reminder_data.get("is_completed", False),
                completed_at=datetime.fromisoformat(reminder_data["completed_at"]) if reminder_data.get("completed_at") else None,
                is_recurring=reminder_data.get("is_recurring", False),
                recurrence_days=reminder_data.get("recurrence_days"),
                recurrence_miles=reminder_data.get("recurrence_miles"),
                notes=reminder_data.get("notes")
            )
            db.add(reminder)
            results["reminders"]["success"] += 1
        except Exception as e:
            results["reminders"]["errors"] += 1
            results["errors"].append(f"Reminder {idx}: {str(e)}")

    # Import notes
    for idx, note_data in enumerate(data.get("notes", [])):
        try:
            date = datetime.fromisoformat(note_data["date"]).date()

            note = Note(
                vin=vin,
                date=date,
                title=note_data["title"],
                content=note_data["content"]
            )
            db.add(note)
            results["notes"]["success"] += 1
        except Exception as e:
            results["notes"]["errors"] += 1
            results["errors"].append(f"Note {idx}: {str(e)}")

    await db.commit()

    metric_keys = ("service_records", "fuel_records", "odometer_records", "reminders", "notes")
    for key in metric_keys:
        bucket = results[key]
        bucket["success_count"] = bucket.get("success", 0)
        bucket["error_count"] = bucket.get("errors", 0)
        bucket["skipped_count"] = bucket.get("skipped", 0)

    return results
