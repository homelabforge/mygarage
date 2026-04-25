"""Data import routes for MyGarage.

CSV/JSON exports from v2.26.2+ carry a schema marker:
  - CSV: leading `units_version` column on every row (= "3" for SI metric)
  - JSON: top-level `"export_version"` and `"units"` keys

This importer accepts both v3 (metric) and legacy v2 (imperial). When the
marker is missing or `"2"`, imperial-named fields are read and converted
on ingest. v3 reads new metric fields verbatim. The legacy ORM kwargs
were already updated to the new column names so v2 fallback paths must
convert before constructing the model.
"""

import csv
import io
import json
import logging
from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import (
    DEFRecord,
    FuelRecord,
    InsurancePolicy,
    Note,
    OdometerRecord,
    Reminder,
    ServiceLineItem,
    ServiceVisit,
    TaxRecord,
    WarrantyRecord,
)
from app.models.user import User
from app.models.vendor import Vendor
from app.services.auth import get_vehicle_or_403, require_auth
from app.utils.file_validation import validate_csv_upload
from app.utils.logging_utils import sanitize_for_log
from app.utils.units import UnitConverter


# Conversion helpers for legacy-v2-CSV imports. Each takes a Decimal in the
# imperial unit and returns the metric Decimal. None passes through.
def _mi_to_km(value: Decimal | None) -> Decimal | None:
    return value * UnitConverter.MILES_TO_KM if value is not None else None


def _gal_to_l(value: Decimal | None) -> Decimal | None:
    return value * UnitConverter.GALLONS_TO_LITERS if value is not None else None


def _per_gal_to_per_l(value: Decimal | None) -> Decimal | None:
    """Price/volume: $/gal → $/L (divide by 3.78541)."""
    return value / UnitConverter.GALLONS_TO_LITERS if value is not None else None


def _row_is_legacy_v2(row: dict) -> bool:
    """Detect whether a CSV row was exported by a v2 (imperial) build.

    v3+ exports include `units_version="3"`. v2 exports omit the column.
    Treat empty/missing as legacy. Imperial-keyed columns (`Mileage`,
    `Gallons`) without the marker also signal legacy.
    """
    version = (row.get("units_version") or "").strip()
    if version == "3":
        return False
    if version and version != "3":
        return True
    # No marker → infer from column shape: "Mileage"/"Gallons" present without
    # "Odometer (km)"/"Liters" means legacy.
    has_imperial = bool(row.get("Mileage") or row.get("Gallons"))
    has_metric = bool(row.get("Odometer (km)") or row.get("Liters"))
    return has_imperial and not has_metric


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/import", tags=["import"])

# Valid service categories matching the ServiceVisit check constraint
VALID_SERVICE_CATEGORIES = {"Maintenance", "Inspection", "Collision", "Upgrades", "Detailing"}
limiter = Limiter(key_func=get_remote_address)


class ImportResult:
    """Result of an import operation."""

    def __init__(self):
        self.success_count: int = 0
        self.error_count: int = 0
        self.skipped_count: int = 0
        self.errors: list[str] = []

    def add_success(self) -> None:
        self.success_count += 1

    def add_error(self, row_num: int, message: str) -> None:
        self.error_count += 1
        self.errors.append(f"Row {row_num}: {message}")

    def add_skip(self) -> None:
        self.skipped_count += 1

    def to_dict(self) -> dict[str, int | list[str]]:
        return {
            "success_count": self.success_count,
            "error_count": self.error_count,
            "skipped_count": self.skipped_count,
            "errors": self.errors,
            "total_processed": self.success_count + self.error_count + self.skipped_count,
        }


def parse_date(date_str: str) -> date_type | None:
    """Parse date string in various formats."""
    if not date_str or date_str.strip() == "":
        return None

    date_str = date_str.strip()

    # Try different date formats
    formats = [
        "%Y-%m-%d",  # 2025-01-15
        "%m/%d/%Y",  # 01/15/2025
        "%m-%d-%Y",  # 01-15-2025
        "%Y/%m/%d",  # 2025/01/15
        "%d/%m/%Y",  # 15/01/2025
        "%b %d, %Y",  # Jan 15, 2025
        "%B %d, %Y",  # January 15, 2025
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Unable to parse date: {date_str}")


def parse_decimal(value: str) -> Decimal | None:
    """Parse decimal value from string."""
    if not value or value.strip() == "":
        return None

    try:
        return Decimal(value.strip())
    except InvalidOperation, ValueError:
        raise ValueError(f"Invalid decimal value: {value}")


def parse_int(value: str) -> int | None:
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
    current_user: User | None = Depends(require_auth),
):
    """Import service records from CSV file (creates ServiceVisit + ServiceLineItem)."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

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

            # Parse optional fields — accept both old and new header names
            raw_category = row.get("Category", "").strip() or None
            service_type = row.get("Service Type", "").strip() or None
            description = row.get("Description", "").strip() or None

            # "Category" maps to service_category if valid; "Service Type" is the description
            if raw_category and raw_category in VALID_SERVICE_CATEGORIES:
                category = raw_category
            elif service_type and service_type in VALID_SERVICE_CATEGORIES:
                category = service_type
            else:
                category = None

            # Use service_type or raw_category as description fallback
            if not description:
                description = service_type or raw_category
            # Legacy v2 CSV header is "Mileage" (miles); v3 uses "Odometer (km)".
            # Convert legacy values to km on ingest so the metric ORM column is correct.
            odometer_raw = parse_decimal(row.get("Odometer (km)", "") or row.get("Mileage", ""))
            odometer_km = _mi_to_km(odometer_raw) if _row_is_legacy_v2(row) else odometer_raw
            cost = parse_decimal(row.get("Cost", ""))
            vendor_name = (
                row.get("Vendor", "").strip() or row.get("Vendor Name", "").strip() or None
            )
            notes = row.get("Notes", "").strip() or None

            # Check for duplicates against ServiceVisit
            if skip_duplicates:
                existing = await db.execute(
                    select(ServiceVisit).where(
                        ServiceVisit.vin == vin,
                        ServiceVisit.date == date,
                        ServiceVisit.odometer_km == odometer_km,
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Lookup or create Vendor
            vendor_id = None
            if vendor_name:
                vendor_result = await db.execute(
                    select(Vendor).where(Vendor.name == vendor_name).limit(1)
                )
                vendor = vendor_result.scalar_one_or_none()
                if not vendor:
                    vendor = Vendor(name=vendor_name)
                    db.add(vendor)
                    await db.flush()
                vendor_id = vendor.id

            # Create ServiceVisit with one line item per CSV row
            visit = ServiceVisit(
                vin=vin,
                date=date,
                odometer_km=odometer_km,
                service_category=category or "Maintenance",
                vendor_id=vendor_id,
                notes=notes,
                total_cost=cost or Decimal("0"),
            )
            db.add(visit)
            await db.flush()

            line_item = ServiceLineItem(
                visit_id=visit.id,
                description=description or category or "Service",
                cost=cost or Decimal("0"),
            )
            db.add(line_item)
            import_result.add_success()

        except Exception as e:
            # Intentional catch-all: per-row errors should not stop the import
            logger.error("Service import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid service record data")

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
    current_user: User | None = Depends(require_auth),
):
    """Import fuel records from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

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

            # Parse optional fields. v3+ uses "Odometer (km)"/"Liters" with a
            # `units_version` marker; legacy v2 uses "Mileage"/"Gallons" and
            # the values must be converted from imperial to metric on ingest
            # (the ORM column is metric — storing miles into odometer_km
            # would lose ~38% of the distance).
            legacy_v2 = _row_is_legacy_v2(row)

            odometer_raw = parse_decimal(row.get("Odometer (km)", "") or row.get("Mileage", ""))
            volume_raw = parse_decimal(row.get("Liters", "") or row.get("Gallons", ""))
            price_raw = parse_decimal(
                row.get("Price Per Liter", "")
                or row.get("Price Per Gallon", "")
                or row.get("Price/Gal", "")
            )

            if legacy_v2:
                odometer_km = _mi_to_km(odometer_raw)
                liters = _gal_to_l(volume_raw)
                price_per_unit = _per_gal_to_per_l(price_raw)
            else:
                odometer_km = odometer_raw
                liters = volume_raw
                price_per_unit = price_raw

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
                        FuelRecord.odometer_km == odometer_km,
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record
            record = FuelRecord(
                vin=vin,
                date=date,
                odometer_km=odometer_km,
                liters=liters,
                price_per_unit=price_per_unit,
                cost=cost,
                is_full_tank=is_full_tank,
                missed_fillup=missed_fillup,
                notes=notes,
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            logger.error("Fuel import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid fuel record data")

    await db.commit()

    return import_result.to_dict()


@router.post("/vehicles/{vin}/def/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_def_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import DEF records from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    csv_data = await validate_csv_upload(file)
    csv_reader = csv.DictReader(io.StringIO(csv_data))

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            # Legacy v2 CSV uses "Mileage"/"Gallons" (imperial); v3 uses
            # "Odometer (km)"/"Liters". Legacy values are converted to metric.
            legacy_v2 = _row_is_legacy_v2(row)
            odometer_raw = parse_decimal(row.get("Odometer (km)", "") or row.get("Mileage", ""))
            volume_raw = parse_decimal(row.get("Liters", "") or row.get("Gallons", ""))
            price_raw = parse_decimal(row.get("Price Per Unit", ""))
            if legacy_v2:
                odometer_km = _mi_to_km(odometer_raw)
                liters = _gal_to_l(volume_raw)
                price_per_unit = _per_gal_to_per_l(price_raw)
            else:
                odometer_km = odometer_raw
                liters = volume_raw
                price_per_unit = price_raw
            cost = parse_decimal(row.get("Total Cost", "") or row.get("Cost", ""))
            fill_level = parse_decimal(row.get("Fill Level", ""))
            source = row.get("Source", "").strip() or None
            brand = row.get("Brand", "").strip() or None
            notes = row.get("Notes", "").strip() or None

            if skip_duplicates:
                existing = await db.execute(
                    select(DEFRecord).where(
                        DEFRecord.vin == vin,
                        DEFRecord.date == date,
                        DEFRecord.odometer_km == odometer_km,
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            record = DEFRecord(
                vin=vin,
                date=date,
                odometer_km=odometer_km,
                liters=liters,
                price_per_unit=price_per_unit,
                cost=cost,
                fill_level=fill_level,
                source=source,
                brand=brand,
                notes=notes,
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            logger.error("DEF import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid DEF record data")

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
    current_user: User | None = Depends(require_auth),
):
    """Import odometer records from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

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

            # Legacy v2 CSV uses "Mileage" (miles); v3 uses "Reading (km)"
            # or "Reading". Convert legacy mileage → km on ingest.
            odometer_raw = parse_decimal(
                row.get("Reading (km)", "") or row.get("Reading", "") or row.get("Mileage", "")
            )
            if odometer_raw is None:
                import_result.add_error(row_num, "Reading is required")
                continue
            odometer_km = _mi_to_km(odometer_raw) if _row_is_legacy_v2(row) else odometer_raw

            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested
            if skip_duplicates:
                existing = await db.execute(
                    select(OdometerRecord).where(
                        OdometerRecord.vin == vin,
                        OdometerRecord.date == date,
                        OdometerRecord.odometer_km == odometer_km,
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record
            record = OdometerRecord(vin=vin, date=date, odometer_km=odometer_km, notes=notes)
            db.add(record)
            import_result.add_success()

        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid record data")

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
    current_user: User | None = Depends(require_auth),
):
    """Import warranties from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

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
                        WarrantyRecord.start_date == start_date,
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
                notes=notes,
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid record data")

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
    current_user: User | None = Depends(require_auth),
):
    """Import insurance records from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

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
                        InsurancePolicy.policy_number == policy_number,
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
                notes=notes,
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid record data")

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
    current_user: User | None = Depends(require_auth),
):
    """Import tax records from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

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
                        TaxRecord.tax_type == tax_type,
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
                notes=notes,
            )
            db.add(record)
            import_result.add_success()

        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid record data")

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
    current_user: User | None = Depends(require_auth),
):
    """Import notes from CSV file."""
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

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
                    select(Note).where(Note.vin == vin, Note.date == date, Note.title == title)
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record
            record = Note(vin=vin, date=date, title=title, content=content)
            db.add(record)
            import_result.add_success()

        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid record data")

    await db.commit()

    return import_result.to_dict()


@router.post("/vehicles/{vin}/json")
async def import_vehicle_json(
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import complete vehicle data from JSON file."""
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

    # Detect schema version. v3+ exports include `"export_version": "3"` and
    # `"units": "metric"`. Pre-v3 backups omit both — treat as legacy v2 and
    # convert imperial values to metric on ingest.
    export_version = str(data.get("export_version") or "").strip()
    units = str(data.get("units") or "").strip().lower()
    is_legacy_v2 = export_version != "3" and units != "metric"
    if is_legacy_v2:
        logger.warning(
            "JSON import for vin=%s detected legacy v2 backup (no export_version "
            "marker); converting imperial values to metric on ingest.",
            sanitize_for_log(vin),
        )

    def _maybe_mi_to_km(val: Any) -> Decimal | None:
        if val is None or val == "":
            return None
        d = Decimal(str(val))
        return d * UnitConverter.MILES_TO_KM if is_legacy_v2 else d

    def _maybe_gal_to_l(val: Any) -> Decimal | None:
        if val is None or val == "":
            return None
        d = Decimal(str(val))
        return d * UnitConverter.GALLONS_TO_LITERS if is_legacy_v2 else d

    def _maybe_per_gal_to_per_l(val: Any) -> Decimal | None:
        if val is None or val == "":
            return None
        d = Decimal(str(val))
        return d / UnitConverter.GALLONS_TO_LITERS if is_legacy_v2 else d

    results = {
        "service_records": {"success": 0, "errors": 0, "skipped": 0},
        "fuel_records": {"success": 0, "errors": 0, "skipped": 0},
        "def_records": {"success": 0, "errors": 0, "skipped": 0},
        "odometer_records": {"success": 0, "errors": 0, "skipped": 0},
        "reminders": {"success": 0, "errors": 0, "skipped": 0},
        "notes": {"success": 0, "errors": 0, "skipped": 0},
        "errors": [],
    }

    # Import service records (creates ServiceVisit + ServiceLineItem + Vendor)
    for idx, record_data in enumerate(data.get("service_records", [])):
        try:
            date = datetime.fromisoformat(record_data["date"]).date()

            # Legacy v2 used "mileage" (miles); v3 uses "odometer_km" (km).
            imported_odometer_km = _maybe_mi_to_km(
                record_data.get("odometer_km") or record_data.get("mileage")
            )

            if skip_duplicates:
                existing = await db.execute(
                    select(ServiceVisit).where(
                        ServiceVisit.vin == vin,
                        ServiceVisit.date == date,
                        ServiceVisit.odometer_km == imported_odometer_km,
                    )
                )
                if existing.scalar_one_or_none():
                    results["service_records"]["skipped"] += 1
                    continue

            # Lookup or create Vendor
            vendor_id = None
            vendor_name = record_data.get("vendor_name")
            if vendor_name:
                vendor_result = await db.execute(
                    select(Vendor).where(Vendor.name == vendor_name).limit(1)
                )
                vendor = vendor_result.scalar_one_or_none()
                if not vendor:
                    vendor = Vendor(name=vendor_name)
                    db.add(vendor)
                    await db.flush()
                vendor_id = vendor.id

            cost = Decimal(str(record_data["cost"])) if record_data.get("cost") else Decimal("0")
            description = (
                record_data.get("service_type") or record_data.get("description") or "Service"
            )
            category = record_data.get("service_category") or "Maintenance"

            visit = ServiceVisit(
                vin=vin,
                date=date,
                odometer_km=imported_odometer_km,
                service_category=category,
                vendor_id=vendor_id,
                notes=record_data.get("notes"),
                total_cost=cost,
            )
            db.add(visit)
            await db.flush()

            line_item = ServiceLineItem(
                visit_id=visit.id,
                description=description,
                cost=cost,
            )
            db.add(line_item)
            results["service_records"]["success"] += 1
        except Exception as e:
            results["service_records"]["errors"] += 1
            results["errors"].append(f"Service record {idx}: {str(e)}")

    # Import fuel records
    for idx, record_data in enumerate(data.get("fuel_records", [])):
        try:
            date = datetime.fromisoformat(record_data["date"]).date()

            # v3 uses "odometer_km"/"liters"; legacy v2 uses "mileage"/"gallons"
            # in imperial — convert via the helpers above.
            imported_odometer_km = _maybe_mi_to_km(
                record_data.get("odometer_km") or record_data.get("mileage")
            )
            imported_liters = _maybe_gal_to_l(
                record_data.get("liters") or record_data.get("gallons")
            )
            imported_ppu = _maybe_per_gal_to_per_l(record_data.get("price_per_unit"))

            if skip_duplicates:
                existing = await db.execute(
                    select(FuelRecord).where(
                        FuelRecord.vin == vin,
                        FuelRecord.date == date,
                        FuelRecord.odometer_km == imported_odometer_km,
                    )
                )
                if existing.scalar_one_or_none():
                    results["fuel_records"]["skipped"] += 1
                    continue

            record = FuelRecord(
                vin=vin,
                date=date,
                odometer_km=imported_odometer_km,
                liters=imported_liters,
                price_per_unit=imported_ppu,
                cost=Decimal(str(record_data["cost"])) if record_data.get("cost") else None,
                is_full_tank=record_data.get("is_full_tank", True),
                missed_fillup=record_data.get("missed_fillup", False),
                notes=record_data.get("notes"),
            )
            db.add(record)
            results["fuel_records"]["success"] += 1
        except Exception as e:
            results["fuel_records"]["errors"] += 1
            results["errors"].append(f"Fuel record {idx}: {str(e)}")

    # Import DEF records
    for idx, record_data in enumerate(data.get("def_records", [])):
        try:
            date = datetime.fromisoformat(record_data["date"]).date()

            # v3 uses "odometer_km"/"liters"; legacy v2 uses "mileage"/"gallons".
            imported_odometer_km = _maybe_mi_to_km(
                record_data.get("odometer_km") or record_data.get("mileage")
            )
            imported_liters = _maybe_gal_to_l(
                record_data.get("liters") or record_data.get("gallons")
            )
            imported_ppu = _maybe_per_gal_to_per_l(record_data.get("price_per_unit"))

            if skip_duplicates:
                existing = await db.execute(
                    select(DEFRecord).where(
                        DEFRecord.vin == vin,
                        DEFRecord.date == date,
                        DEFRecord.odometer_km == imported_odometer_km,
                    )
                )
                if existing.scalar_one_or_none():
                    results["def_records"]["skipped"] += 1
                    continue

            record = DEFRecord(
                vin=vin,
                date=date,
                odometer_km=imported_odometer_km,
                liters=imported_liters,
                price_per_unit=imported_ppu,
                cost=Decimal(str(record_data["cost"])) if record_data.get("cost") else None,
                fill_level=Decimal(str(record_data["fill_level"]))
                if record_data.get("fill_level")
                else None,
                source=record_data.get("source"),
                brand=record_data.get("brand"),
                notes=record_data.get("notes"),
            )
            db.add(record)
            results["def_records"]["success"] += 1
        except Exception as e:
            results["def_records"]["errors"] += 1
            results["errors"].append(f"DEF record {idx}: {str(e)}")

    # Import odometer records
    for idx, record_data in enumerate(data.get("odometer_records", [])):
        try:
            date = datetime.fromisoformat(record_data["date"]).date()

            # v2 used "reading" (miles), v3 uses "odometer_km".
            imported_odometer_km = _maybe_mi_to_km(
                record_data.get("odometer_km") or record_data.get("reading")
            )

            if skip_duplicates:
                existing = await db.execute(
                    select(OdometerRecord).where(
                        OdometerRecord.vin == vin,
                        OdometerRecord.date == date,
                        OdometerRecord.odometer_km == imported_odometer_km,
                    )
                )
                if existing.scalar_one_or_none():
                    results["odometer_records"]["skipped"] += 1
                    continue

            record = OdometerRecord(
                vin=vin,
                date=date,
                odometer_km=imported_odometer_km,
                notes=record_data.get("notes"),
            )
            db.add(record)
            results["odometer_records"]["success"] += 1
        except Exception as e:
            results["odometer_records"]["errors"] += 1
            results["errors"].append(f"Odometer record {idx}: {str(e)}")

    # Import reminders → map to vehicle_reminders
    for idx, reminder_data in enumerate(data.get("reminders", [])):
        try:
            # Determine reminder type from recurrence fields
            is_recurring = reminder_data.get("is_recurring", False)
            recurrence_days = reminder_data.get("recurrence_days", 0)
            recurrence_miles = reminder_data.get("recurrence_miles")

            has_date = bool(is_recurring and recurrence_days)
            has_miles = bool(is_recurring and recurrence_miles)

            if has_date and has_miles:
                reminder_type = "both"
            elif has_miles:
                reminder_type = "mileage"
            else:
                reminder_type = "date"

            # Calculate due_date from recurrence_days
            due_date = None
            if has_date and recurrence_days:
                due_date = (date_type.today() + timedelta(days=recurrence_days)).isoformat()

            reminder = Reminder(
                vin=vin,
                title=reminder_data["description"],
                reminder_type=reminder_type,
                due_date=due_date,
                due_mileage_km=recurrence_miles if has_miles else None,
                status="pending",
                notes=reminder_data.get("notes"),
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
                content=note_data["content"],
            )
            db.add(note)
            results["notes"]["success"] += 1
        except Exception as e:
            results["notes"]["errors"] += 1
            results["errors"].append(f"Note {idx}: {str(e)}")

    await db.commit()

    metric_keys = (
        "service_records",
        "fuel_records",
        "def_records",
        "odometer_records",
        "reminders",
        "notes",
    )
    for key in metric_keys:
        bucket = results[key]
        bucket["success_count"] = bucket.get("success", 0)
        bucket["error_count"] = bucket.get("errors", 0)
        bucket["skipped_count"] = bucket.get("skipped", 0)

    return results
