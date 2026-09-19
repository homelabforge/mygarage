"""Data import routes for MyGarage.

CSV/JSON exports from v2.26.2+ carry a schema marker:
  - CSV: leading `units_version` column on every row (= "3" for SI metric)
  - JSON: top-level `"export_version"` and `"units"` keys

JSON backups are still schema 5 and still resolve units file-wide, below.
CSV moved to schema 6 for issue #152: a per-quantity unit preference makes a
single `metric`/`imperial` marker unable to describe a file whose distance is
miles and whose volume is litres, so a v6 CSV column names its own unit with
a phase-1 vocabulary token (`Odometer (mi)`, `Volume (gal_uk)`).

`app.utils.csv_units` owns that decision for the four unit-bearing CSV pairs
(service, fuel, DEF, odometer). It resolves the unit from the FILE alone --
header token, then marker, then `units_version`, then a narrow inference over
the column names -- and refuses the upload rather than guessing when the file
is ambiguous. It never reads the importing account's preferences: doing that
is what once multiplied an old US-gallon backup by 4.54609 on a
UK-configured instance and wrote the result into canonical storage
permanently.

This importer still accepts every older shape: v3-v5 metric
(`Odometer (km)` / `Liters` / `Price Per Liter`) and legacy v2 imperial
(`Mileage` / `Gallons` / `Price Per Gallon`), which is converted on ingest
because the ORM columns are metric.
"""

import csv
import io
import json
import logging
from collections.abc import Mapping, Sequence
from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import ColumnElement, Numeric, and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.config import settings
from app.constants.fuel import FuelTypeEnum, normalize_fuel_type
from app.database import get_db
from app.models import (
    DEFRecord,
    FuelRecord,
    HoursRecord,
    InsurancePolicy,
    InsurancePolicyField,
    InsurancePolicyVehicle,
    Note,
    OdometerRecord,
    Reminder,
    ServiceLineItem,
    ServiceVisit,
    TaxRecord,
    WarrantyRecord,
)
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vendor import Vendor
from app.schemas.fuel import _validate_diesel_grade, _validate_octane
from app.services import maintenance_service
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.fuel_side_effects import (
    apply_fuel_record_side_effects,
    invalidate_cache_for_vehicle,
)
from app.services.insurance_service import InsuranceService
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.csv_units import (
    CONSUMPTION,
    DEF_PRICE,
    DISTANCE,
    FUEL_CONSUMPTION,
    FUEL_PRICE,
    FUEL_SPEED,
    FUEL_TEMPERATURE,
    FUEL_VOLUME,
    MILEAGE_LIMIT_DISTANCE,
    ODOMETER_DISTANCE,
    PRICE_PER_VOLUME,
    READING_DISTANCE,
    SPEED,
    TEMPERATURE,
    VOLUME,
    CsvUnitContext,
    QuantitySpec,
    build_csv_unit_context,
)
from app.utils.def_sync import ensure_def_capable
from app.utils.file_validation import validate_csv_upload
from app.utils.household_time import household_today
from app.utils.logging_utils import sanitize_for_log
from app.utils.maintenance_types import classify
from app.utils.odometer_tolerance import KM_STEP, LITRE_STEP, conversion_tolerance
from app.utils.units import UnitConverter

logger = logging.getLogger(__name__)


def _coerce_octane(value: object) -> int | None:
    """A backup's octane as an int, or a ValueError for a fractional one.

    JSON numbers arrive as int or float; a float only passes when it is
    integral, because int() would otherwise store 91.9 as 91 and let 150.9
    sneak under the 150 bound the API enforces (codex code review R1-M1).
    Strings raise in int() and fail the row like any other bad field.
    """
    if value is None:
        return None
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"octane must be a whole number, got {value!r}")
    return int(value)  # type: ignore[arg-type]


def _derive_price_basis(
    price_per_unit: Decimal | None,
    *,
    liters: Decimal | None = None,
    propane_liters: Decimal | None = None,
    kwh: Decimal | None = None,
) -> str | None:
    """Which denominator `price_per_unit` is measured against.

    Mirrors migration 053's rule verbatim, on the post-053 metric columns.
    Imports previously left this NULL, and the frontend's `priceToDisplay`
    converts a stored price to the user's units ONLY when the basis says
    `per_volume` — so on an imperial account every imported fill-up showed
    the canonical per-litre figure under a "Price/Gal" heading. $2.50/gal
    was stored correctly as $0.660/L and then rendered as "0.66" (#128).

    Returns None when there is no price, since there is then nothing to
    interpret — a basis on a priceless row would be noise.
    """
    if price_per_unit is None:
        return None
    if kwh is not None and liters is None and propane_liters is None:
        return "per_kwh"
    if liters is not None or propane_liters is not None:
        return "per_volume"
    return None


def _normalized_fuel_type(raw: str | None) -> str | None:
    """A legacy free-text fuel type as its canonical enum value, or None."""
    normalized = normalize_fuel_type(raw)
    return normalized.value if normalized is not None else None


async def _last_id_before_import(db: AsyncSession, model: Any) -> int:
    """The highest `model.id` stored when an import begins, or 0 for an empty table.

    Ids only grow, so every row this import writes sits above it, and a row at
    or below it was stored before the import started. Taken after the vehicle
    write lock and before the first row is written.
    """
    return int((await db.execute(select(func.max(model.id)))).scalar() or 0)


def _within(
    column: InstrumentedAttribute[Any], value: Decimal, half_width: Decimal
) -> ColumnElement[bool]:
    """`column` within `half_width` of `value`, compared exactly on every dialect.

    The bounds are bound as an unscaled NUMERIC. Bound with the column's own
    type, PostgreSQL casts them to its NUMERIC(10, 2) and rounds them, so a
    half-step window around 100000.00 reached 100000.01 and swallowed the next
    step on PostgreSQL only.
    """
    return column.between(
        literal(value - half_width, Numeric()), literal(value + half_width, Numeric())
    )


def _converted_value_matches(
    column: InstrumentedAttribute[Any],
    value: Decimal | None,
    step: Decimal,
    *,
    converted: bool,
    stored_before_import: ColumnElement[bool],
) -> ColumnElement[bool]:
    """A duplicate-check condition on a column holding a unit-converted value.

    A stored row matches when it holds the same figure at the column's
    precision: within half a `step`, which covers PostgreSQL rounding the value
    on write and SQLite keeping it as given.

    Only one case can sit further away. A value converted from miles or gallons
    in this import meets a row stored with the truncated pre-v3.4.0 factors a
    few parts per million off, on top of that rounding
    (`conversion_tolerance`, shared with tire history). That band is allowed
    ONLY for a `converted` value and ONLY against a row `stored_before_import`.
    Applied to every check, it skipped a second, genuinely different same-day
    reading inside it (0.31 km at 100,000 km), including one this import had
    just written.

    An absent value still matches only NULL. More than one stored row can
    match, so a caller treats any match as the duplicate rather than asking for
    exactly one.
    """
    if value is None:
        return column.is_(None)
    half_step = step / 2
    same_figure = _within(column, value, half_step)
    if not converted:
        return same_figure
    drifted = and_(stored_before_import, _within(column, value, conversion_tolerance(value, step)))
    return or_(same_figure, drifted)


def _odometer_matches(
    model: Any, odometer_km: Decimal | None, *, converted: bool, last_id_before_import: int
) -> ColumnElement[bool]:
    """`_converted_value_matches` for `model.odometer_km`, in km."""
    return _converted_value_matches(
        model.odometer_km,
        odometer_km,
        KM_STEP,
        converted=converted,
        stored_before_import=model.id <= last_id_before_import,
    )


router = APIRouter(prefix="/api/import", tags=["import"])

#: The record lists a vehicle JSON backup may carry, in the order they import.
_JSON_IMPORT_SECTIONS = (
    "service_records",
    "fuel_records",
    "def_records",
    "odometer_records",
    "reminders",
    "notes",
    "insurance_policies",
)

# Valid service categories matching the ServiceVisit check constraint
VALID_SERVICE_CATEGORIES = {"Maintenance", "Inspection", "Collision", "Upgrades", "Detailing"}
limiter = Limiter(key_func=get_remote_address)


class _InsuranceRowError(ValueError):
    """An insurance row that cannot be imported, with a user-facing reason."""


def _whole_cents(value: Decimal | None, column: str) -> Decimal | None:
    """The amount, or a row error when it has a fraction of a cent."""
    if value is None:
        return None
    if value != value.quantize(Decimal("0.01")):
        raise _InsuranceRowError(f"{column} must be a whole number of cents")
    if value < 0:
        raise _InsuranceRowError(f"{column} must not be negative")
    return value


async def _import_insurance_row(
    db: AsyncSession,
    access: Any,
    vin: str,
    row: dict[str, Any],
    created_in_run: set[int],
    skip_duplicates: bool,
) -> bool:
    """Put one vehicle's insurance row onto a household policy.

    Returns False when the row was skipped as a duplicate. The policy is found
    by the same key migration 107 merges on, so importing two vehicles' files
    rebuilds ONE household policy.

    THE IMPORTER NEVER REWRITES EXISTING MONEY. A policy created earlier in this
    same import accumulates its total from the rows; a PRE-EXISTING policy only
    ever grows by the imported vehicle's own premium, which by construction
    leaves every existing effective share unchanged. An unknown (blank) premium
    is never attached to a priced pre-existing policy, because an unset share
    would dilute every sibling; it gets a policy of its own.
    """
    provider = (row["provider"] or "").strip()
    number = (row["policy_number"] or "").strip()
    # Importers build ORM rows directly, so the API schema's whole-cents rule
    # does not reach them: 0.005 + 0.005 adds up to a 0.01 premium here and is
    # then STORED as two 0.01 shares, which no longer fit it.
    premium: Decimal | None = _whole_cents(row["premium"], "Premium")
    row["deductible"] = _whole_cents(row["deductible"], "Deductible")
    frequency = row["premium_frequency"]

    candidates = (
        (
            await db.execute(
                select(InsurancePolicy)
                .where(
                    func.lower(func.trim(InsurancePolicy.provider)) == provider.lower(),
                    func.trim(InsurancePolicy.policy_number) == number,
                    InsurancePolicy.start_date == row["start_date"],
                    InsurancePolicy.end_date == row["end_date"],
                    InsurancePolicy.premium_frequency.is_(None)
                    if frequency is None
                    else InsurancePolicy.premium_frequency == frequency,
                )
                .order_by(InsurancePolicy.id)
                # Two imports for DIFFERENT vehicles hold different vehicle locks
                # on PostgreSQL yet can target the same policy, and both add to
                # its premium: lock the policy rows before reading their money.
                # (SQLite imports already hold the database write lock, and
                # `with_for_update` compiles away there.)
                .with_for_update(of=InsurancePolicy)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    # THE OWNER BOUNDARY, same as migration 107's merge key: a row joins a
    # policy only when every vehicle already on it belongs to this vehicle's
    # owner (an empty policy counts by its creator). Without it an admin
    # importing two owners' look-alike files would weld them into one policy,
    # and each owner would gain a window into, and a say over, the other's.
    owner_id = await db.scalar(select(Vehicle.user_id).where(Vehicle.vin == vin))
    linked_vins = {link.vin for p in candidates for link in p.vehicle_links}
    owners = (
        dict(
            (
                await db.execute(
                    select(Vehicle.vin, Vehicle.user_id).where(Vehicle.vin.in_(linked_vins))
                )
            ).all()
        )
        if linked_vins
        else {}
    )

    def _same_owner(policy: InsurancePolicy) -> bool:
        if not policy.vehicle_links:
            return policy.created_by_user_id == owner_id
        return all(owners.get(link.vin) == owner_id for link in policy.vehicle_links)

    readable = [p for p in candidates if access.can_read(p) and _same_owner(p)]
    if skip_duplicates and any(link.vin == vin for p in readable for link in p.vehicle_links):
        return False

    target: InsurancePolicy | None = None
    for policy in readable:
        if any(link.vin == vin for link in policy.vehicle_links):
            continue
        if policy.id in created_in_run:
            target = policy
            break
        if premium is None and policy.premium_amount is not None:
            continue
        if not access.can_write(policy):
            raise _InsuranceRowError(
                "this policy already exists and adding a vehicle to it needs write "
                "access to every vehicle it covers"
            )
        target = policy
        break

    # Children are appended while a new policy is still PENDING: once flushed,
    # touching its unloaded collections would be an async lazy load.
    async with db.begin_nested():
        is_new = target is None
        if target is None:
            target = InsurancePolicy(
                provider=provider,
                policy_number=number,
                start_date=row["start_date"],
                end_date=row["end_date"],
                premium_amount=premium,
                premium_frequency=frequency,
                notes=row.get("policy_notes"),
                created_by_user_id=access.user_id,
            )
            db.add(target)
            for order, item in enumerate(row.get("policy_fields") or []):
                target.all_fields.append(
                    InsurancePolicyField(label=item["label"], value=item["value"], sort_order=order)
                )
        elif target.id in created_in_run:
            target.premium_amount = (
                target.premium_amount + premium
                if target.premium_amount is not None and premium is not None
                else None
            )
        elif target.premium_amount is not None and premium is not None:
            target.premium_amount = target.premium_amount + premium

        link = InsurancePolicyVehicle(
            vin=vin,
            policy_type=row["policy_type"],
            premium_share=premium,
            deductible=row["deductible"],
            coverage_limits=row["coverage_limits"],
            notes=row["notes"],
            effective_to=row.get("effective_to"),
        )
        target.vehicle_links.append(link)
        for order, item in enumerate(row.get("fields") or []):
            target.all_fields.append(
                InsurancePolicyField(
                    policy_vehicle=link, label=item["label"], value=item["value"], sort_order=order
                )
            )
        await db.flush()
    if is_new:
        created_in_run.add(target.id)
    return True


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


def _read_csv_with_units(
    csv_data: str, specs: Sequence[QuantitySpec]
) -> tuple[list[dict[str, Any]], CsvUnitContext]:
    """Every data row, plus the ONE unit context they are all read under.

    `unit_system` and `units_version` are written into every data row by
    `export.generate_csv_stream`, not once per file, so a later row can
    disagree with the first and be converted under a context it does not
    belong to. The whole upload is read up front (already size-bounded by
    `validate_csv_upload`) so that disagreement is detectable and so every
    rejection lands before a single ORM row is added.
    """
    reader = csv.DictReader(io.StringIO(csv_data))
    rows = list(reader)
    return rows, build_csv_unit_context(reader.fieldnames, rows, specs)


def _canonical_cell(units: CsvUnitContext, row: Mapping[str, Any], quantity: str) -> Decimal | None:
    """One row's `quantity`, converted into canonical metric storage.

    None when the file has no column for that quantity, so an importer can
    ask for every quantity it supports without first checking which the file
    happens to carry. The unit comes from the file alone (see
    `app.utils.csv_units`), never from the importing account's preferences.
    """
    header = units.column(quantity)
    if header is None:
        return None
    return units.to_canonical(quantity, parse_decimal(row.get(header, "")))


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

    # Validate and parse CSV, then settle the file's units once, before any
    # ORM write. A bad header or a self-contradictory file is refused whole
    # rather than half-imported (see `app.utils.csv_units`).
    csv_data = await validate_csv_upload(file)
    rows, units = _read_csv_with_units(csv_data, (ODOMETER_DISTANCE,))

    # The vehicle write lock, taken before the first read of stored rows and
    # before any write. On SQLite it opens the one transaction that every
    # row's savepoint nests in; without it each savepoint commits its row on
    # release (see `app.database`), and a failure later in the upload would
    # leave the rows before it behind. Every import route takes it the same way.
    await lock_vehicle_for_write(db, vin)
    # Taken before the first write; see `_converted_value_matches` for why.
    odometer_converted = units.converts(DISTANCE)
    last_id = await _last_id_before_import(db, ServiceVisit)

    import_result = ImportResult()

    for row_num, row in enumerate(rows, start=2):  # Start at 2 (header is row 1)
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
            # Distance arrives as a v6 token header (`Odometer (mi)`), as
            # `Odometer (km)`, or as legacy v2 `Mileage` in miles. `units`
            # already resolved which, from the file and nothing else.
            odometer_km = _canonical_cell(units, row, DISTANCE)
            # Engine-hours: hour-metered vehicles (ATVs, side-by-sides, equipment).
            # Dimensionless — no unit conversion (never present in legacy v2 CSVs).
            engine_hours = parse_decimal(row.get("Engine Hours", ""))
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
                        _odometer_matches(
                            ServiceVisit,
                            odometer_km,
                            converted=odometer_converted,
                            last_id_before_import=last_id,
                        ),
                    )
                )
                if existing.scalars().first():
                    import_result.add_skip()
                    continue

            # A savepoint per row, covering the vendor lookup/create, the
            # visit and its line item together: a CHECK or length violation
            # on any of them rolls the whole row back alone instead of
            # poisoning the session for every row and loop still to come.
            async with db.begin_nested():
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
                    engine_hours=engine_hours,
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
                    maintenance_type=classify(description or category or "Service"),
                    cost=cost or Decimal("0"),
                )
                db.add(line_item)
            import_result.add_success()

        except Exception as e:
            # Intentional catch-all: per-row errors should not stop the import
            logger.error("Service import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid service record data")

    await db.commit()
    # Imported services may be the newest of a rule's type: reconcile once per
    # upload (own lock, own commit), never per row.
    await maintenance_service.reconcile_vehicle(db, vin)

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

    # No DEF fill-level column is parsed from fuel CSV rows today, so there
    # is nothing to gate here yet. If one is ever added, gate it the same
    # way as the JSON fuel-record routes: call ensure_def_capable(vehicle)
    # before writing a DEF observation for a non-diesel vehicle.

    # Validate and parse CSV, then settle the file's units once, before any
    # ORM write (see `app.utils.csv_units`).
    csv_data = await validate_csv_upload(file)
    rows, units = _read_csv_with_units(
        csv_data,
        (
            ODOMETER_DISTANCE,
            FUEL_VOLUME,
            FUEL_PRICE,
            FUEL_TEMPERATURE,
            FUEL_CONSUMPTION,
            FUEL_SPEED,
        ),
    )

    await lock_vehicle_for_write(db, vin)
    # Taken before the first write; see `_converted_value_matches` for why.
    odometer_converted = units.converts(DISTANCE)
    last_id = await _last_id_before_import(db, FuelRecord)

    import_result = ImportResult()

    for row_num, row in enumerate(rows, start=2):
        try:
            # Parse required fields
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            # Every unit-bearing column, converted into canonical metric
            # storage under the file's own units. v6 spells them
            # `Odometer (mi)` / `Volume (gal_uk)` / `Price Per Unit (gal_us)`;
            # v3-v5 spell them `Odometer (km)` / `Liters` / `Price Per Liter`;
            # v2 spells them `Mileage` / `Gallons` / `Price Per Gallon` and
            # means imperial (the ORM columns are metric, so storing miles
            # into odometer_km would lose ~38% of the distance).
            odometer_km = _canonical_cell(units, row, DISTANCE)
            liters = _canonical_cell(units, row, VOLUME)
            price_per_unit = _canonical_cell(units, row, PRICE_PER_VOLUME)
            # Temperature, consumption and speed have been EXPORTED since v4
            # and were dropped on the way back in until #152 phase 2b, so a
            # fuel CSV could not round-trip them at all.
            outside_temp_c = _canonical_cell(units, row, TEMPERATURE)
            obc_l_per_100km = _canonical_cell(units, row, CONSUMPTION)
            obc_avg_speed_kmh = _canonical_cell(units, row, SPEED)

            # Engine-hours: hour-metered vehicles (ATVs, side-by-sides,
            # equipment). Dimensionless — no unit conversion, never present
            # in legacy v2 CSVs.
            engine_hours = parse_decimal(row.get("Engine Hours", ""))

            cost = parse_decimal(row.get("Total Cost", "") or row.get("Cost", ""))
            rebate = parse_decimal(row.get("Rebate", ""))
            is_full_tank = parse_bool(row.get("Full Tank", "True"))
            missed_fillup = parse_bool(row.get("Missed Fill-up", "False"))
            notes = row.get("Notes", "").strip() or None

            # Fuel type — surfaced by issue #69. rc1's importer dropped this
            # column entirely. Now: read it and route through the locale-aware
            # normalizer (so Polish "Benzyna" → gasoline, etc.) into the
            # canonical `fuel_type_used` enum. Unrecognized values fall through
            # to FuelTypeEnum.OTHER (a warning is logged) — we never silently
            # drop the row over fuel-type alone.
            #
            # "Fuel Type Used" is the v5 column; "Fuel Type" is what v4-and-older
            # exports (and every third-party sheet) call it, so both are read.
            raw_fuel_type = (
                (row.get("Fuel Type Used", "") or "").strip()
                or (row.get("Fuel Type", "") or "").strip()
                or None
            )
            normalized_fuel_type: FuelTypeEnum | None = normalize_fuel_type(raw_fuel_type)
            if raw_fuel_type and normalized_fuel_type is None:
                logger.warning(
                    "Fuel import row %d: unrecognized fuel type %r → 'other'",
                    row_num,
                    raw_fuel_type,
                )
                normalized_fuel_type = FuelTypeEnum.OTHER

            # #164 — octane + diesel grade (v7 columns; absent/blank = NULL).
            # The constructor below bypasses Pydantic, so the shared schema
            # validators run here: an invalid value fails this ROW through
            # the per-row error handler, never silently persisted (R1-M2).
            raw_octane = (row.get("Octane", "") or "").strip()
            octane = _validate_octane(int(raw_octane)) if raw_octane else None
            raw_grade = (row.get("Diesel Grade", "") or "").strip()
            diesel_grade = _validate_diesel_grade(raw_grade) if raw_grade else None

            # Check for duplicates if requested
            if skip_duplicates:
                existing = await db.execute(
                    select(FuelRecord).where(
                        FuelRecord.vin == vin,
                        FuelRecord.date == date,
                        _odometer_matches(
                            FuelRecord,
                            odometer_km,
                            converted=odometer_converted,
                            last_id_before_import=last_id,
                        ),
                    )
                )
                if existing.scalars().first():
                    import_result.add_skip()
                    continue

            # Create record
            record = FuelRecord(
                vin=vin,
                date=date,
                odometer_km=odometer_km,
                engine_hours=engine_hours,
                liters=liters,
                price_per_unit=price_per_unit,
                price_basis=_derive_price_basis(price_per_unit, liters=liters),
                cost=cost,
                rebate=rebate,
                is_full_tank=is_full_tank,
                missed_fillup=missed_fillup,
                notes=notes,
                fuel_type_used=(
                    normalized_fuel_type.value if normalized_fuel_type is not None else None
                ),
                octane=octane,
                diesel_grade=diesel_grade,
                outside_temp_c=outside_temp_c,
                obc_l_per_100km=obc_l_per_100km,
                obc_avg_speed_kmh=obc_avg_speed_kmh,
            )
            # A savepoint per row. Leaving it flushes the insert, so the next
            # row's duplicate check sees this one (production sessions do not
            # autoflush), and a row the database rejects rolls back alone
            # instead of failing the whole upload at the final commit.
            async with db.begin_nested():
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
    vehicle = await get_vehicle_or_403(vin, current_user, db, require_write=True)
    # Same rule as the interactive create/update routes (Task 5): a fresh
    # CSV import is a new write, not a backup restore, so it is gated.
    ensure_def_capable(vehicle)

    csv_data = await validate_csv_upload(file)
    rows, units = _read_csv_with_units(csv_data, (ODOMETER_DISTANCE, FUEL_VOLUME, DEF_PRICE))

    await lock_vehicle_for_write(db, vin)
    # Taken before the first write; see `_converted_value_matches` for why.
    odometer_converted = units.converts(DISTANCE)
    last_id = await _last_id_before_import(db, DEFRecord)

    import_result = ImportResult()

    for row_num, row in enumerate(rows, start=2):
        try:
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            # v6 spells these `Odometer (mi)` / `Volume (gal_uk)` /
            # `Price Per Unit (gal_us)`; v3-v5 `Odometer (km)` / `Liters` /
            # `Price Per Unit`; v2 `Mileage` / `Gallons` in imperial. DEF's
            # price column keeps its name across all of them because that
            # name is the only key this importer has ever read.
            odometer_km = _canonical_cell(units, row, DISTANCE)
            liters = _canonical_cell(units, row, VOLUME)
            price_per_unit = _canonical_cell(units, row, PRICE_PER_VOLUME)
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
                        _odometer_matches(
                            DEFRecord,
                            odometer_km,
                            converted=odometer_converted,
                            last_id_before_import=last_id,
                        ),
                    )
                )
                if existing.scalars().first():
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
            # A savepoint per row. Leaving it flushes the insert, so the next
            # row's duplicate check sees this one (production sessions do not
            # autoflush), and a row the database rejects rolls back alone
            # instead of failing the whole upload at the final commit.
            async with db.begin_nested():
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

    # Validate and parse CSV, then settle the file's units once, before any
    # ORM write (see `app.utils.csv_units`).
    csv_data = await validate_csv_upload(file)
    rows, units = _read_csv_with_units(csv_data, (READING_DISTANCE,))

    await lock_vehicle_for_write(db, vin)
    # Taken before the first write; see `_converted_value_matches` for why.
    odometer_converted = units.converts(DISTANCE)
    last_id = await _last_id_before_import(db, OdometerRecord)

    import_result = ImportResult()

    for row_num, row in enumerate(rows, start=2):
        try:
            # Parse required fields
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            # v6 spells this `Reading (mi)`; v3-v5 `Reading (km)` (or
            # `Mileage`); a bare `Reading` with no marker and no version is
            # the v2 standalone odometer export, which held MILES.
            odometer_km = _canonical_cell(units, row, DISTANCE)
            if odometer_km is None:
                import_result.add_error(row_num, "Reading is required")
                continue

            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested
            if skip_duplicates:
                existing = await db.execute(
                    select(OdometerRecord).where(
                        OdometerRecord.vin == vin,
                        OdometerRecord.date == date,
                        _odometer_matches(
                            OdometerRecord,
                            odometer_km,
                            converted=odometer_converted,
                            last_id_before_import=last_id,
                        ),
                    )
                )
                if existing.scalars().first():
                    import_result.add_skip()
                    continue

            # Create record
            record = OdometerRecord(vin=vin, date=date, odometer_km=odometer_km, notes=notes)
            # A savepoint per row. Without it the INSERT is only attempted at
            # the commit below, which is outside this handler: a CHECK
            # violation would escape the route as a 500 and discard every
            # valid row in the file along with the bad one.
            async with db.begin_nested():
                db.add(record)
            import_result.add_success()

        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid record data")

    await db.commit()

    return import_result.to_dict()


@router.post("/vehicles/{vin}/hours/csv")
@limiter.limit(settings.rate_limit_uploads)
async def import_hours_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import engine-hours records from CSV file.

    Mirrors :func:`import_odometer_csv` — the hours track's standalone
    history CSV for hour-metered vehicles. Registered under this router
    (``/api/import``), not the hours CRUD router (``/api/vehicles/{vin}/hours``),
    to avoid shadowing that router's ``GET/PUT/DELETE /{record_id}`` routes.

    Every imported row becomes a manual reading (``source='manual'``, both
    ``fuel_record_id``/``service_visit_id`` left null) regardless of what the
    exported "Source" column says — a CSV cannot carry a live foreign key to
    a fuel/service row in the *target* vehicle's tables, so re-establishing
    sync provenance on import would be fabricated.
    """
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Validate and parse CSV
    csv_data = await validate_csv_upload(file)
    csv_reader = csv.DictReader(io.StringIO(csv_data))

    await lock_vehicle_for_write(db, vin)

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            # Parse required fields
            date = parse_date(row.get("Date", ""))
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue

            # Dimensionless — no unit conversion, no legacy-v2 fallback (the
            # hours track didn't exist in v2/v3 exports).
            engine_hours = parse_decimal(row.get("Engine Hours", ""))
            if engine_hours is None:
                import_result.add_error(row_num, "Engine Hours is required")
                continue

            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested
            if skip_duplicates:
                existing = await db.execute(
                    select(HoursRecord).where(
                        HoursRecord.vin == vin,
                        HoursRecord.date == date,
                        HoursRecord.engine_hours == engine_hours,
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record — always a manual reading (see docstring).
            record = HoursRecord(
                vin=vin,
                date=date,
                engine_hours=engine_hours,
                notes=notes,
                source="manual",
            )
            # A savepoint per row. Leaving it flushes the insert, so the next
            # row's duplicate check sees this one (production sessions do not
            # autoflush), and a row the database rejects rolls back alone
            # instead of failing the whole upload at the final commit.
            async with db.begin_nested():
                db.add(record)
            import_result.add_success()

        except Exception as e:
            logger.error("Hours import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid hours record data")

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

    # Validate and parse CSV. Read through the unit machinery rather than a
    # bare DictReader: `Mileage Limit` is unit-bearing, so the file's own
    # marker decides whether the number is km or miles. A plain reader cannot
    # see a tokenised header at all, and would silently store miles as km.
    csv_data = await validate_csv_upload(file)
    rows, units = _read_csv_with_units(csv_data, (MILEAGE_LIMIT_DISTANCE,))

    await lock_vehicle_for_write(db, vin)

    import_result = ImportResult()

    for row_num, row in enumerate(rows, start=2):
        try:
            provider = row.get("Provider", "").strip() or None
            warranty_type = row.get("Type", "").strip() or None
            # `Coverage` is the pre-v3.3.0 spelling. Both are read so a file
            # exported before this release still imports rather than coming
            # back 200 with every row blamed on the user's file.
            coverage_details = (
                row.get("Coverage Details", "") or row.get("Coverage", "")
            ).strip() or None
            policy_number = row.get("Policy Number", "").strip() or None
            start_date = parse_date(row.get("Start Date", ""))
            end_date = parse_date(row.get("End Date", ""))
            mileage_limit_km = _canonical_cell(units, row, DISTANCE)
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
                policy_number=policy_number,
                coverage_details=coverage_details,
                start_date=start_date,
                end_date=end_date,
                mileage_limit_km=mileage_limit_km,
                notes=notes,
            )
            # A savepoint per row. Without it the INSERT is only attempted at
            # the commit below, which is outside this handler: a CHECK
            # violation would escape the route as a 500 and discard every
            # valid row in the file along with the bad one.
            async with db.begin_nested():
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

    await lock_vehicle_for_write(db, vin)

    import_result = ImportResult()

    access = await InsuranceService(db).access_for(current_user)
    created_in_run: set[int] = set()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            imported = await _import_insurance_row(
                db,
                access,
                vin,
                {
                    "provider": row.get("Provider", ""),
                    "policy_number": row.get("Policy Number", ""),
                    "policy_type": row.get("Type", "").strip() or None,
                    "start_date": parse_date(row.get("Start Date", "")),
                    "end_date": parse_date(row.get("End Date", "")),
                    "premium": parse_decimal(row.get("Premium", "")),
                    "premium_frequency": row.get("Premium Frequency", "").strip() or None,
                    "deductible": parse_decimal(row.get("Deductible", "")),
                    "coverage_limits": row.get("Coverage Limits", "").strip() or None,
                    "notes": row.get("Notes", "").strip() or None,
                },
                created_in_run,
                skip_duplicates,
            )
            if imported:
                import_result.add_success()
            else:
                import_result.add_skip()
        except _InsuranceRowError as e:
            import_result.add_error(row_num, str(e))
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

    await lock_vehicle_for_write(db, vin)

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            # TaxRecord has `date`, `tax_type`, `amount`, `renewal_date`,
            # `notes`. This importer previously read `Year`, `Paid Date`,
            # `Due Date` and `Jurisdiction` and constructed with four
            # attributes the model does not have, so no tax record has ever
            # imported. The export writes `Date` and `Renewal Date`; the two
            # halves now share one vocabulary.
            record_date = parse_date(row.get("Date", "")) or parse_date(row.get("Paid Date", ""))
            tax_type = row.get("Type", "").strip() or None
            amount = parse_decimal(row.get("Amount", ""))
            renewal_date = parse_date(row.get("Renewal Date", "")) or parse_date(
                row.get("Due Date", "")
            )
            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested
            if skip_duplicates and record_date and tax_type:
                existing = await db.execute(
                    select(TaxRecord).where(
                        TaxRecord.vin == vin,
                        TaxRecord.date == record_date,
                        TaxRecord.tax_type == tax_type,
                    )
                )
                if existing.scalar_one_or_none():
                    import_result.add_skip()
                    continue

            # Create record
            record = TaxRecord(
                vin=vin,
                date=record_date,
                tax_type=tax_type,
                amount=amount,
                renewal_date=renewal_date,
                notes=notes,
            )
            # A savepoint per row. Without it the INSERT is only attempted at
            # the commit below, which is outside this handler: a CHECK
            # violation would escape the route as a 500 and discard every
            # valid row in the file along with the bad one.
            async with db.begin_nested():
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

    await lock_vehicle_for_write(db, vin)

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
            # A savepoint per row. Without it the INSERT is only attempted at
            # the commit below, which is outside this handler: a CHECK
            # violation would escape the route as a 500 and discard every
            # valid row in the file along with the bad one.
            async with db.begin_nested():
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

    # Every section is settled here, before the lock and before any write. A
    # missing or null section is empty; anything else that is not a list
    # refuses the whole file, instead of raising halfway through the loops
    # below with the sections before it already written.
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="The import file must be a JSON object")
    backup = cast(dict[str, Any], data)
    sections: dict[str, list[Any]] = {}
    for section in _JSON_IMPORT_SECTIONS:
        value = backup.get(section)
        if value is None:
            sections[section] = []
        elif isinstance(value, list):
            sections[section] = cast(list[Any], value)
        else:
            raise HTTPException(status_code=400, detail=f"{section} must be a list of records")

    # Detect schema version. v3+ exports include `"export_version": "3"` and
    # `"units": "metric"`. Pre-v3 backups omit both — treat as legacy v2 and
    # convert imperial values to metric on ingest.
    export_version = str(backup.get("export_version") or "").strip()
    units = str(backup.get("units") or "").strip().lower()
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
        return d * UnitConverter.US_GALLONS_TO_LITERS if is_legacy_v2 else d

    def _maybe_per_gal_to_per_l(val: Any) -> Decimal | None:
        if val is None or val == "":
            return None
        d = Decimal(str(val))
        return d / UnitConverter.US_GALLONS_TO_LITERS if is_legacy_v2 else d

    await lock_vehicle_for_write(db, vin)
    # Taken before the first section writes: only a row at or below these can
    # carry the pre-v3.4.0 factors (see `_converted_value_matches`), and a v3
    # backup is canonical already, so only a legacy one was converted.
    last_ids = {
        model: await _last_id_before_import(db, model)
        for model in (ServiceVisit, FuelRecord, DEFRecord, OdometerRecord)
    }

    results = {
        "service_records": {"success": 0, "errors": 0, "skipped": 0},
        "fuel_records": {"success": 0, "errors": 0, "skipped": 0},
        "def_records": {"success": 0, "errors": 0, "skipped": 0},
        "odometer_records": {"success": 0, "errors": 0, "skipped": 0},
        "reminders": {"success": 0, "errors": 0, "skipped": 0},
        "notes": {"success": 0, "errors": 0, "skipped": 0},
        "insurance_policies": {"success": 0, "errors": 0, "skipped": 0},
        "errors": [],
    }

    # Import service records (creates ServiceVisit + ServiceLineItem + Vendor)
    for idx, record_data in enumerate(sections["service_records"]):
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
                        _odometer_matches(
                            ServiceVisit,
                            imported_odometer_km,
                            converted=is_legacy_v2,
                            last_id_before_import=last_ids[ServiceVisit],
                        ),
                    )
                )
                if existing.scalars().first():
                    results["service_records"]["skipped"] += 1
                    continue

            cost = Decimal(str(record_data["cost"])) if record_data.get("cost") else Decimal("0")
            description = (
                record_data.get("service_type") or record_data.get("description") or "Service"
            )
            # Only a name IN VALID_SERVICE_CATEGORIES is accepted, the same
            # vocabulary the CSV importer matches against. Reported as this
            # row's error rather than left for the database's own CHECK
            # constraint to reject.
            raw_category = record_data.get("service_category")
            if raw_category and raw_category not in VALID_SERVICE_CATEGORIES:
                results["service_records"]["errors"] += 1
                results["errors"].append(
                    f"Service record {idx}: service_category {raw_category!r} is not "
                    "a recognized category"
                )
                continue
            category = raw_category or "Maintenance"

            # A savepoint per row, covering the vendor lookup/create, the
            # visit and its line item together: a CHECK or length violation
            # on any of them rolls the whole row back alone instead of
            # poisoning the session for every row and loop still to come.
            async with db.begin_nested():
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
                    maintenance_type=classify(description),
                    cost=cost,
                )
                db.add(line_item)
            results["service_records"]["success"] += 1
        except Exception as e:
            results["service_records"]["errors"] += 1
            logger.warning("Import: service record %s failed: %s", idx, sanitize_for_log(e))
            results["errors"].append(f"Service record {idx}: could not be imported")

    # Import fuel records
    for idx, record_data in enumerate(sections["fuel_records"]):
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

            # The export has always written fuel_type_used and is_hauling but
            # this constructor silently dropped both, so a restored backup
            # lost them. Same locale-tolerant normalization as the CSV path.
            raw_fuel_type = (record_data.get("fuel_type_used") or "").strip() or None
            normalized_fuel_type = normalize_fuel_type(raw_fuel_type)
            if raw_fuel_type and normalized_fuel_type is None:
                logger.warning(
                    "Fuel import record %s: unrecognized fuel type %r → 'other'",
                    idx,
                    raw_fuel_type,
                )
                normalized_fuel_type = FuelTypeEnum.OTHER

            if skip_duplicates:
                existing = await db.execute(
                    select(FuelRecord).where(
                        FuelRecord.vin == vin,
                        FuelRecord.date == date,
                        _odometer_matches(
                            FuelRecord,
                            imported_odometer_km,
                            converted=is_legacy_v2,
                            last_id_before_import=last_ids[FuelRecord],
                        ),
                    )
                )
                if existing.scalars().first():
                    results["fuel_records"]["skipped"] += 1
                    continue

            record = FuelRecord(
                vin=vin,
                date=date,
                odometer_km=imported_odometer_km,
                liters=imported_liters,
                price_per_unit=imported_ppu,
                price_basis=(
                    record_data.get("price_basis")
                    or _derive_price_basis(imported_ppu, liters=imported_liters)
                ),
                cost=Decimal(str(record_data["cost"])) if record_data.get("cost") else None,
                rebate=Decimal(str(record_data["rebate"])) if record_data.get("rebate") else None,
                is_full_tank=record_data.get("is_full_tank", True),
                missed_fillup=record_data.get("missed_fillup", False),
                is_hauling=record_data.get("is_hauling", False),
                fuel_type_used=(
                    normalized_fuel_type.value if normalized_fuel_type is not None else None
                ),
                # #164 — direct ORM construction bypasses Pydantic, so the
                # shared validators run here per-row (R1-M2). _coerce_octane
                # rejects a fractional value instead of silently truncating it
                # the way a bare int() would (91.9 -> 91; codex review R1-M1).
                octane=_validate_octane(_coerce_octane(record_data.get("octane"))),
                diesel_grade=_validate_diesel_grade(record_data.get("diesel_grade")),
                notes=record_data.get("notes"),
            )
            # A savepoint per row. Leaving it flushes the insert, so the next
            # row's duplicate check sees this one (production sessions do not
            # autoflush), and a row the database rejects rolls back alone
            # instead of failing the whole upload at the final commit.
            async with db.begin_nested():
                db.add(record)
            results["fuel_records"]["success"] += 1
        except Exception as e:
            results["fuel_records"]["errors"] += 1
            logger.warning("Import: fuel record %s failed: %s", idx, sanitize_for_log(e))
            results["errors"].append(f"Fuel record {idx}: could not be imported")

    # Import DEF records
    # Deliberately NOT gated by ensure_def_capable (unlike import_def_csv and
    # the interactive create/update routes): this is a full-fidelity backup
    # restore, not a new write. A user's own archive must always restore
    # completely, even if it contains DEF rows for a vehicle whose fuel type
    # has since changed (or never was diesel per current data) — refusing to
    # restore data the user already had would be a data-loss bug, not a
    # safety feature.
    for idx, record_data in enumerate(sections["def_records"]):
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
                        _odometer_matches(
                            DEFRecord,
                            imported_odometer_km,
                            converted=is_legacy_v2,
                            last_id_before_import=last_ids[DEFRecord],
                        ),
                    )
                )
                if existing.scalars().first():
                    results["def_records"]["skipped"] += 1
                    continue

            # No price_basis here: DEF is volume-only, has no such column, and
            # the UI passes 'per_volume' as a literal when displaying it.
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
            # A savepoint per row. Leaving it flushes the insert, so the next
            # row's duplicate check sees this one (production sessions do not
            # autoflush), and a row the database rejects rolls back alone
            # instead of failing the whole upload at the final commit.
            async with db.begin_nested():
                db.add(record)
            results["def_records"]["success"] += 1
        except Exception as e:
            results["def_records"]["errors"] += 1
            logger.warning("Import: DEF record %s failed: %s", idx, sanitize_for_log(e))
            results["errors"].append(f"DEF record {idx}: could not be imported")

    # Import odometer records
    for idx, record_data in enumerate(sections["odometer_records"]):
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
                        _odometer_matches(
                            OdometerRecord,
                            imported_odometer_km,
                            converted=is_legacy_v2,
                            last_id_before_import=last_ids[OdometerRecord],
                        ),
                    )
                )
                if existing.scalars().first():
                    results["odometer_records"]["skipped"] += 1
                    continue

            record = OdometerRecord(
                vin=vin,
                date=date,
                odometer_km=imported_odometer_km,
                notes=record_data.get("notes"),
            )
            # A savepoint per row. Leaving it flushes the insert, so the next
            # row's duplicate check sees this one (production sessions do not
            # autoflush), and a row the database rejects rolls back alone
            # instead of failing the whole upload at the final commit.
            async with db.begin_nested():
                db.add(record)
            results["odometer_records"]["success"] += 1
        except Exception as e:
            results["odometer_records"]["errors"] += 1
            logger.warning("Import: odometer record %s failed: %s", idx, sanitize_for_log(e))
            results["errors"].append(f"Odometer record {idx}: could not be imported")

    # Import reminders → map to vehicle_reminders
    for idx, reminder_data in enumerate(sections["reminders"]):
        try:
            # Determine reminder type from recurrence fields
            is_recurring = reminder_data.get("is_recurring", False)
            recurrence_days = reminder_data.get("recurrence_days", 0)
            recurrence_miles = reminder_data.get("recurrence_miles")

            has_date = bool(is_recurring and recurrence_days)
            has_miles = bool(is_recurring and recurrence_miles)

            # The database requires a positive due_mileage_km when one is set
            # (check_due_mileage_km); reject a negative recurrence here
            # rather than letting that CHECK reject the row. Not clamped: a
            # negative value is reported, never silently corrected.
            if has_miles and Decimal(str(recurrence_miles)) <= 0:
                results["reminders"]["errors"] += 1
                results["errors"].append(f"Reminder {idx}: recurrence_miles must be positive")
                continue

            if has_date and has_miles:
                reminder_type = "both"
            elif has_miles:
                reminder_type = "mileage"
            else:
                reminder_type = "date"

            # Calculate due_date from recurrence_days
            due_date = None
            if has_date and recurrence_days:
                # A date object, in the household zone. The previous code
                # assigned .isoformat() -- a str the Date column rejects at
                # flush -- so every recurring-days row errored out of the
                # import; the per-row savepoint made it look like bad data.
                due_date = household_today() + timedelta(days=recurrence_days)

            reminder = Reminder(
                vin=vin,
                title=reminder_data["description"],
                reminder_type=reminder_type,
                due_date=due_date,
                due_mileage_km=recurrence_miles if has_miles else None,
                status="pending",
                notes=reminder_data.get("notes"),
                maintenance_type=classify(reminder_data["description"]),
            )
            # A savepoint per row. A row the database still rejects rolls
            # back alone here, instead of poisoning the session for every
            # row and loop still to come.
            async with db.begin_nested():
                db.add(reminder)
            results["reminders"]["success"] += 1
        except Exception as e:
            results["reminders"]["errors"] += 1
            logger.warning("Import: reminder %s failed: %s", idx, sanitize_for_log(e))
            results["errors"].append(f"Reminder {idx}: could not be imported")

    # Import notes
    for idx, note_data in enumerate(sections["notes"]):
        try:
            date = datetime.fromisoformat(note_data["date"]).date()

            note = Note(
                vin=vin,
                date=date,
                title=note_data["title"],
                content=note_data["content"],
            )
            # A savepoint per row. A row the database still rejects rolls
            # back alone here, instead of poisoning the session for every
            # row and loop still to come.
            async with db.begin_nested():
                db.add(note)
            results["notes"]["success"] += 1
        except Exception as e:
            results["notes"]["errors"] += 1
            logger.warning("Import: note %s failed: %s", idx, sanitize_for_log(e))
            results["errors"].append(f"Note {idx}: could not be imported")

    # Import insurance: each entry is THIS vehicle's place on a household policy.
    insurance_access = await InsuranceService(db).access_for(current_user)
    insurance_created: set[int] = set()
    for idx, entry in enumerate(sections["insurance_policies"]):
        try:
            premium = entry.get("premium_share")
            deductible = entry.get("deductible")
            imported = await _import_insurance_row(
                db,
                insurance_access,
                vin,
                {
                    "provider": entry["provider"],
                    "policy_number": entry["policy_number"],
                    "policy_type": entry.get("policy_type"),
                    "start_date": datetime.fromisoformat(entry["start_date"]).date(),
                    "end_date": datetime.fromisoformat(entry["end_date"]).date(),
                    "premium": Decimal(str(premium)) if premium is not None else None,
                    "premium_frequency": entry.get("premium_frequency"),
                    "deductible": Decimal(str(deductible)) if deductible is not None else None,
                    "coverage_limits": entry.get("coverage_limits"),
                    "notes": entry.get("notes"),
                    "fields": entry.get("fields") or [],
                    "policy_fields": entry.get("policy_fields") or [],
                    "policy_notes": entry.get("policy_notes"),
                    "effective_to": (
                        datetime.fromisoformat(entry["effective_to"]).date()
                        if entry.get("effective_to")
                        else None
                    ),
                },
                insurance_created,
                skip_duplicates=True,
            )
            results["insurance_policies"]["success" if imported else "skipped"] += 1
        except Exception as e:
            results["insurance_policies"]["errors"] += 1
            logger.warning("Import: insurance policy %s failed: %s", idx, sanitize_for_log(e))
            results["errors"].append(f"Insurance policy {idx}: could not be imported")

    await db.commit()
    # Imported services may be the newest of a rule's type: reconcile once.
    await maintenance_service.reconcile_vehicle(db, vin)

    metric_keys = (
        "service_records",
        "fuel_records",
        "def_records",
        "odometer_records",
        "reminders",
        "notes",
        "insurance_policies",
    )
    for key in metric_keys:
        bucket = results[key]
        bucket["success_count"] = bucket.get("success", 0)
        bucket["error_count"] = bucket.get("errors", 0)
        bucket["skipped_count"] = bucket.get("skipped", 0)

    return results


@router.post("/vehicles/{vin}/fuel/fuelio")
@limiter.limit(settings.rate_limit_uploads)
async def import_fuelio_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    odometer_unit: str = Form("km"),
    decimal_separator: str = Form("dot"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import fuel records from a Fuelio CSV export.

    ``odometer_unit`` and ``decimal_separator`` declare how to read columns the
    export does not label. Defaults are metric and dot, matching storage.
    """
    return await _import_third_party_fuel(
        vin,
        file,
        skip_duplicates,
        db,
        current_user,
        "fuelio",
        _parse_options(odometer_unit, decimal_separator),
    )


@router.post("/vehicles/{vin}/fuel/drivvo")
@limiter.limit(settings.rate_limit_uploads)
async def import_drivvo_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    odometer_unit: str = Form("km"),
    decimal_separator: str = Form("dot"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import fuel records from a Drivvo CSV export.

    ``odometer_unit`` and ``decimal_separator`` declare how to read columns the
    export does not label. Defaults are metric and dot, matching storage.
    """
    return await _import_third_party_fuel(
        vin,
        file,
        skip_duplicates,
        db,
        current_user,
        "drivvo",
        _parse_options(odometer_unit, decimal_separator),
    )


@router.post("/vehicles/{vin}/fuel/tesla")
@limiter.limit(settings.rate_limit_uploads)
async def import_tesla_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    odometer_unit: str = Form("km"),
    decimal_separator: str = Form("dot"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Import charge sessions from a Tesla / ABRP-style charge history CSV.

    ``odometer_unit`` and ``decimal_separator`` declare how to read columns the
    export does not label. Defaults are metric and dot, matching storage.
    """
    return await _import_third_party_fuel(
        vin,
        file,
        skip_duplicates,
        db,
        current_user,
        "tesla",
        _parse_options(odometer_unit, decimal_separator),
    )


@router.post("/vehicles/{vin}/fuel/external")
@limiter.limit(settings.rate_limit_uploads)
async def import_external_fuel_csv(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    format: str | None = Form(None),
    odometer_unit: str = Form("km"),
    decimal_separator: str = Form("dot"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Auto-detect Fuelio / Drivvo / Tesla CSV format (or pass format= explicitly)."""
    csv_data = await validate_csv_upload(file)
    from app.services.import_adapters import PARSERS, detect_format

    fmt = (format or detect_format(csv_data) or "").lower()
    if fmt not in PARSERS:
        raise HTTPException(
            status_code=400,
            detail="Unrecognized CSV format — pass format=fuelio|drivvo|tesla",
        )
    # Re-wrap for the shared helper (it re-reads the upload); parse inline instead.
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    parsed = PARSERS[fmt](csv_data, _parse_options(odometer_unit, decimal_separator))
    await lock_vehicle_for_write(db, vin)
    return await _persist_parsed_fuel(vin, parsed, skip_duplicates, db)


# The natural key of a physical fill-up or charge session: when it happened,
# where the odometer stood, and how much went in.
#
# Deliberately NOT every persisted column. Cost, notes, location and SOC are
# metadata a user may correct in the source app between exports, so including
# them would make a re-import of a corrected file insert duplicates instead of
# skipping them. Two same-day sessions are told apart by filled_at, which the
# adapters now preserve; before that the time was truncated away and the only
# way to separate them was to compare mutable fields.
#
# When an export carries no time at all, filled_at is NULL on both rows and two
# sessions with the same odometer and the same amount are genuinely
# indistinguishable in the data, so collapsing them is correct.
def _third_party_duplicate_conditions(
    vin: str, row: Mapping[str, Any], last_id_before_import: int
) -> list[ColumnElement[bool]]:
    """The natural key above, as the conditions a stored duplicate must meet.

    `filled_at` and `kwh` are never converted and match exactly (`== None`
    renders as IS NULL). The odometer and the volume may have been converted
    from miles and gallons, and the adapters settle that per file (an explicit
    "(mi)" or "Gallons" header wins over the caller's option), so both are
    treated as converted: the band still applies only to a row stored before
    the import, and the time and the volume in the key tell two real fill-ups
    apart where the band alone could not.
    """
    return [
        FuelRecord.vin == vin,
        FuelRecord.date == row.get("date"),
        FuelRecord.filled_at == row.get("filled_at"),
        _odometer_matches(
            FuelRecord,
            row.get("odometer_km"),
            converted=True,
            last_id_before_import=last_id_before_import,
        ),
        _converted_value_matches(
            FuelRecord.liters,
            row.get("liters"),
            LITRE_STEP,
            converted=True,
            stored_before_import=FuelRecord.id <= last_id_before_import,
        ),
        FuelRecord.kwh == row.get("kwh"),
    ]


def _parse_options(odometer_unit: str, decimal_separator: str):
    """Build ParseOptions from form input, rejecting anything off-vocabulary."""
    from app.services.import_adapters import ParseOptions

    if odometer_unit not in ("km", "mi"):
        raise HTTPException(status_code=400, detail="odometer_unit must be km or mi")
    if decimal_separator not in ("dot", "comma"):
        raise HTTPException(status_code=400, detail="decimal_separator must be dot or comma")
    return ParseOptions(odometer_unit=odometer_unit, decimal_separator=decimal_separator)


async def _import_third_party_fuel(
    vin: str,
    file: UploadFile,
    skip_duplicates: bool,
    db: AsyncSession,
    current_user: User | None,
    format_name: str,
    opts=None,
):
    from app.services.import_adapters import PARSERS

    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    csv_data = await validate_csv_upload(file)
    parsed = PARSERS[format_name](csv_data, opts)
    await lock_vehicle_for_write(db, vin)
    return await _persist_parsed_fuel(vin, parsed, skip_duplicates, db)


async def _persist_parsed_fuel(
    vin: str,
    parsed: list[dict],
    skip_duplicates: bool,
    db: AsyncSession,
):
    import_result = ImportResult()
    # date -> (odometer_km, record). Odometer sync matches on (vin, date) and
    # overwrites, so syncing every row would let CSV order decide the stored
    # value and reassign the cascade FK. Sync once per date with the highest
    # reading, which is the only choice that survives reordering the file.
    best_per_date: dict[date_type, tuple[Decimal, FuelRecord]] = {}
    # Callers take the vehicle write lock first; see `_converted_value_matches`.
    last_id = await _last_id_before_import(db, FuelRecord)
    for row_num, row in enumerate(parsed, start=2):
        try:
            date = row.get("date")
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue
            odometer_km = row.get("odometer_km")
            if skip_duplicates:
                existing = await db.execute(
                    select(FuelRecord).where(*_third_party_duplicate_conditions(vin, row, last_id))
                )
                # .first(), not scalar_one_or_none(): pre-existing duplicates in
                # the table would otherwise raise MultipleResultsFound.
                if existing.scalars().first():
                    import_result.add_skip()
                    continue
            record = FuelRecord(
                vin=vin,
                date=date,
                filled_at=row.get("filled_at"),
                odometer_km=odometer_km,
                liters=row.get("liters"),
                kwh=row.get("kwh"),
                cost=row.get("cost"),
                price_per_unit=row.get("price_per_unit"),
                price_basis=row.get("price_basis"),
                is_full_tank=bool(row.get("is_full_tank", True)),
                notes=row.get("notes"),
                # v4-and-older backups carry the retired free-text "fuel_type"
                # instead, so fall back to it through the normalizer rather
                # than restoring those records with no fuel type at all.
                fuel_type_used=row.get("fuel_type_used")
                or _normalized_fuel_type(row.get("fuel_type")),
                soc_start_pct=row.get("soc_start_pct"),
                soc_end_pct=row.get("soc_end_pct"),
                charge_level=row.get("charge_level"),
                charge_location=row.get("charge_location"),
                battery_soh_pct=row.get("battery_soh_pct"),
            )
            # Savepoint per row: the flush below populates record.id, and a bare
            # flush failure would poison the session for every remaining row.
            async with db.begin_nested():
                db.add(record)
                await db.flush()
            if record.odometer_km is not None:
                best = best_per_date.get(record.date)
                if best is None or record.odometer_km > best[0]:
                    best_per_date[record.date] = (record.odometer_km, record)
            import_result.add_success()
        except Exception as e:
            logger.error("External fuel import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid fuel record data")

    for _odometer, record in best_per_date.values():
        try:
            async with db.begin_nested():
                await apply_fuel_record_side_effects(db, record)
        except Exception as e:
            # Derived data only. Log and keep the fuel rows: letting this escape
            # would reach get_db's handler, which rolls back the outer
            # transaction and would discard the entire import.
            logger.warning("Odometer sync failed for imported fuel record %s: %s", record.id, e)

    await db.commit()
    await invalidate_cache_for_vehicle(vin)
    return import_result.to_dict()
