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
import operator
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal, cast, get_args

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import ColumnElement, Numeric, and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, selectinload
from sqlalchemy.sql.base import ExecutableOption

from app.config import settings
from app.constants.fuel import (
    PAYMENT_METHOD_VALUES,
    TRIP_TYPE_VALUES,
    FuelTypeEnum,
    normalize_fuel_type,
)
from app.database import get_db
from app.models import (
    AddressBookEntry,
    DEFRecord,
    FinancingRecord,
    FuelRecord,
    HoursRecord,
    InsuranceCoverage,
    InsurancePolicy,
    InsurancePolicyField,
    InsurancePolicyVehicle,
    Note,
    OdometerRecord,
    Reminder,
    ServiceLineItem,
    ServiceVisit,
    SpotRental,
    SpotRentalBilling,
    TaxRecord,
    TollTag,
    TollTransaction,
    WarrantyRecord,
)
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vendor import Vendor
from app.schemas._money import MONEY_MAX
from app.schemas.def_record import DEFRecordCreate
from app.schemas.financing import FinancingCategory, FinancingRecordCreate
from app.schemas.fuel import (
    CHARGE_LEVEL_VALUES,
    CHARGE_LOCATION_VALUES,
    PRICE_BASIS_VALUES,
    FuelRecordCreate,
    _parse_obc_trip_duration,
    _validate_diesel_grade,
    _validate_octane,
)
from app.schemas.hours import HoursRecordCreate
from app.schemas.insurance import CoverageEntry, PolicyVehicleCreate
from app.schemas.maintenance import validate_maintenance_type
from app.schemas.odometer import OdometerRecordCreate
from app.schemas.reminder import ReminderCreate
from app.schemas.service_visit import (
    InspectionResult,
    InspectionSeverity,
    ServiceCategory,
    ServiceLineItemCreate,
    ServiceVisitCreate,
)
from app.schemas.spot_rental import SpotRentalCreate
from app.schemas.spot_rental_billing import SpotRentalBillingCreate
from app.schemas.tax import TaxRecordCreate, TaxType
from app.schemas.toll import TollTransactionCreate, _normalize_toll_system, _tidy_toll_system
from app.schemas.warranty import WarrantyRecordCreate
from app.services import maintenance_service
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.fuel_side_effects import invalidate_cache_for_vehicle
from app.services.insurance_service import InsuranceService
from app.services.reminder_service import start_readings
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.csv_safe import unquote_csv_cell
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
from app.utils.hours_sync import same_day_hours, sync_hours_from_record
from app.utils.hours_tolerance import hours_below
from app.utils.household_time import household_date, household_today
from app.utils.insurance_coverages import (
    COVERAGE_BY_KEY,
    coverage_row,
    parse_coverage_lines,
    place_leftovers,
)
from app.utils.logging_utils import sanitize_for_log
from app.utils.maintenance_types import classify, resolve_type
from app.utils.money_fits import too_large
from app.utils.odometer_sync import sync_odometer_from_record
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


def _matches(column: InstrumentedAttribute[Any], value: Any) -> ColumnElement[bool]:
    """`column` equal to `value`, or NULL when `value` is None."""
    return column.is_(None) if value is None else column == value


def _same_figure(
    column: InstrumentedAttribute[Any], value: Decimal | None, step: Decimal
) -> ColumnElement[bool]:
    """`column` holds `value` at its scale: within half a `step`, or NULL for None.

    SQLite keeps a REAL as given, so a figure stored past the scale (an API or
    metric-JSON write is never rounded) reads back, and exports, rounded; an
    exact `=` against that export never meets the stored row (Fable F-1, T-20).
    `step` is the column's own: 0.01 for NUMERIC(n,2), 0.001 for (n,3), 0.1 for (n,1).
    """
    return column.is_(None) if value is None else _within(column, value, step / 2)


#: Every money column is NUMERIC(12,2) (schemas/_money.py).
_MONEY_STEP = Decimal("0.01")


def _money_matches(
    column: InstrumentedAttribute[Any], value: Decimal | None
) -> ColumnElement[bool]:
    """`column` holds the same amount to the cent; 0 and NULL match each other (v8 wrote $0 as null)."""
    if value is None or value == 0:
        return or_(column.is_(None), _within(column, Decimal(0), _MONEY_STEP / 2))
    return _within(column, value, _MONEY_STEP / 2)


def _zero_was_blank(version: str, faithful_from: int) -> bool:
    """Whether a file of schema `version` predates its export writing a 0 as 0.

    The fuel and DEF exports wrote a 0 L fill-up and a 0.00 fill level as a
    blank cell up to CSV v7 and as null up to JSON v8. A blank or unreadable
    version is an older file.
    """
    try:
        return int(version) < faithful_from
    except ValueError:
        return True


def _or_blank_zero(
    condition: ColumnElement[bool],
    column: InstrumentedAttribute[Any],
    value: Decimal | None,
    step: Decimal,
    *,
    zero_was_blank: bool,
) -> ColumnElement[bool]:
    """`condition`, which a missing `value` makes `IS NULL`, or a stored 0 when that file blanked one.

    Only an older file's blank stands for a 0 (`_zero_was_blank`); a newer one's
    is a missing figure, another row than the 0.
    """
    if value is not None or not zero_was_blank:
        return condition
    return or_(condition, _within(column, Decimal(0), step / 2))


class _DuplicateMatcher:
    """Duplicate checks that pair the file with the stored rows one to one (R5).

    A file row is a duplicate only of a row stored before this import began,
    with the same portable content, that no earlier file row has matched; the
    lowest such id is taken and spent. So a file's identical rows all import
    into an empty target, a target holding one of them gains the rest, a
    re-import adds nothing, and a row this import wrote is never a duplicate.
    """

    def __init__(self, last_ids: Mapping[type[Any], int]) -> None:
        self._last_ids = dict(last_ids)
        self._spent: dict[type[Any], set[int]] = {}

    @classmethod
    async def before_import(cls, db: AsyncSession, *models: type[Any]) -> _DuplicateMatcher:
        """Taken after the vehicle lock and before the first write, like `_last_id_before_import`."""
        return cls({model: await _last_id_before_import(db, model) for model in models})

    def last_id(self, model: type[Any]) -> int:
        """The highest id `model` held when the import began."""
        return self._last_ids[model]

    async def take(
        self,
        db: AsyncSession,
        model: type[Any],
        *conditions: ColumnElement[bool],
        options: Sequence[ExecutableOption] = (),
        same: Callable[[Any], bool] | None = None,
    ) -> Any | None:
        """Spend the lowest unspent stored row matching `conditions` and `same`; None when none does.

        `same` compares what SQL can't, such as a visit's line items, on rows
        loaded with `options`.
        """
        spent = self._spent.setdefault(model, set())
        result = await db.execute(
            select(model)
            .where(model.id <= self._last_ids[model], *conditions)
            .options(*options)
            .order_by(model.id)
        )
        for row in result.scalars():
            if row.id in spent or (same is not None and not same(row)):
                continue
            spent.add(row.id)
            return row
        return None


#: Every sync marker: `auto_sync_marker` writes `[AUTO-SYNC from <source> #<id>]`
#: (utils/odometer_sync.py:51-59, utils/hours_sync.py:142), and the odometer
#: claim rule treats any note containing `[AUTO-SYNC from` as auto-synced
#: (odometer_sync.py:228).
_SYNC_MARKER = re.compile(r"\[AUTO-SYNC from [^\]]*\]")

#: The odometer sources a reading keeps through a move. The rest (fuel,
#: service_visit, def, the legacy service, and tire, tire_rotation, tire_set,
#: tire_mount, tire_dismount) name a record on the instance that wrote them.
_PORTABLE_ODOMETER_SOURCES = frozenset({"manual", "livelink", "webhook"})


def _without_sync_marker(notes: Any) -> Any:
    """Notes with every sync marker taken out, None when nothing else is left.

    A copied marker made the reading look owned: the next same-day fill-up took
    it over, and a delete of a record with the marker's id removed it (N-2).
    """
    if not isinstance(notes, str):
        return notes
    return _SYNC_MARKER.sub("", notes).strip() or None


def _portable_odometer_source(source: Any) -> str:
    """The source an imported odometer reading keeps: its own if portable, else manual."""
    return source if source in _PORTABLE_ODOMETER_SOURCES else "manual"


#: The scale of the column each converted quantity lands in: odometer and
#: mileage limit NUMERIC(10,2), volume NUMERIC(9,3), unit price NUMERIC(12,3),
#: temperature NUMERIC(4,1), consumption NUMERIC(5,2), speed NUMERIC(5,1).
_COLUMN_SCALE: Mapping[str, Decimal] = {
    DISTANCE: Decimal("0.01"),
    VOLUME: Decimal("0.001"),
    PRICE_PER_VOLUME: Decimal("0.001"),
    TEMPERATURE: Decimal("0.1"),
    CONSUMPTION: Decimal("0.01"),
    SPEED: Decimal("0.1"),
}


def _at_scale(value: Decimal | None, scale: Decimal) -> Decimal | None:
    """`value` rounded to its column's scale, half up, as PostgreSQL rounds NUMERIC.

    SQLite keeps a REAL as given, so an unrounded conversion read back differently
    there (G5a-80). A value that can't be rounded (Infinity, NaN, more digits than
    the context holds) passes through, and the bounds check after it refuses it.
    """
    if value is None or not value.is_finite():
        return value
    try:
        return value.quantize(scale, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return value


@dataclass(frozen=True)
class _Reading:
    """One reading an imported record carries, and the record that owns it."""

    source_type: str
    source_id: int
    value: Decimal


class _ImportReadings:
    """The readings an import's records carry, synced once a day at its end (R3).

    The create paths sync each record as it's written. An import syncs once per
    day and track, with that day's highest reading: the odometer sync takes over
    an auto-synced row on its date, so syncing every row let file order pick the
    stored value. A tie keeps the record added first.
    """

    def __init__(self) -> None:
        self._odometer: dict[date_type, _Reading] = {}
        self._hours: dict[date_type, _Reading] = {}

    def add(
        self,
        source_type: Literal["fuel", "service_visit", "def"],
        source_id: int,
        day: date_type,
        *,
        odometer_km: Decimal | None,
        engine_hours: Decimal | None = None,
    ) -> None:
        """Note one written record's readings. Only fuel and service visits carry hours."""
        for readings, value in ((self._odometer, odometer_km), (self._hours, engine_hours)):
            if value is None:
                continue
            best = readings.get(day)
            if best is None or value > best.value:
                readings[day] = _Reading(source_type, source_id, value)

    async def apply(self, db: AsyncSession, vin: str, *, claim: bool) -> None:
        """Sync each day's reading. A failure is logged and the imported rows stay.

        With `claim`, the odometer sync may take over a same-day automatic or
        LiveLink row (the create paths' rule, kept for the third-party importers).
        Without it, nothing stored is touched: a day that already reads at or
        above the figure gets nothing, any other day a row of its own (R1-H2).
        """
        for day, reading in self._odometer.items():
            try:
                async with db.begin_nested():
                    await sync_odometer_from_record(
                        db=db,
                        vin=vin,
                        date=day,
                        odometer_km=reading.value,
                        source_type=reading.source_type,
                        source_id=reading.source_id,
                        commit=False,
                        claim_other_records=claim,
                    )
            except Exception as e:
                # Derived data only. Escaping would reach get_db's handler, which
                # rolls back the outer transaction and the whole import with it.
                logger.warning(
                    "Odometer sync failed for imported %s record %s: %s",
                    reading.source_type,
                    reading.source_id,
                    sanitize_for_log(e),
                )
        for day, reading in self._hours.items():
            try:
                async with db.begin_nested():
                    # The hours sync has no same-day rule, so a reading the file's
                    # hours section already restored would land twice (T-1). This
                    # is the odometer's non-claiming rule, applied to hours.
                    same_day = await same_day_hours(db, vin, day)
                    if any(not hours_below(row.engine_hours, reading.value) for row in same_day):
                        continue
                    await sync_hours_from_record(
                        db=db,
                        vin=vin,
                        date=day,
                        engine_hours=reading.value,
                        source_type=reading.source_type,
                        source_id=reading.source_id,
                        commit=False,
                    )
            except Exception as e:
                logger.warning(
                    "Hours sync failed for imported %s record %s: %s",
                    reading.source_type,
                    reading.source_id,
                    sanitize_for_log(e),
                )


router = APIRouter(prefix="/api/import", tags=["import"])

#: The record lists a vehicle JSON backup may carry, in the order they import.
_JSON_IMPORT_SECTIONS = (
    "service_records",
    "service_visits",
    "fuel_records",
    "def_records",
    "odometer_records",
    "hours_records",
    "reminders",
    "notes",
    "insurance_policies",
    "financing_records",
    "tax_records",
    "toll_tags",
    "toll_transactions",
    "warranties",
    "spot_rentals",
)

#: The API's words for a visit's and a line item's category and an inspection's
#: result and severity (the CHECK lists, `models/service_visit.py` and
#: `models/service_line_item.py`).
_SERVICE_CATEGORIES: tuple[str, ...] = get_args(ServiceCategory)
# Valid service categories matching the ServiceVisit check constraint; the same
# list, so the two can't drift.
VALID_SERVICE_CATEGORIES = frozenset(_SERVICE_CATEGORIES)
_INSPECTION_RESULTS: tuple[str, ...] = get_args(InspectionResult)
_INSPECTION_SEVERITIES: tuple[str, ...] = get_args(InspectionSeverity)
_FINANCING_CATEGORIES: tuple[str, ...] = get_args(FinancingCategory)
_TAX_TYPES: tuple[str, ...] = get_args(TaxType)
#: TollTagCreate's statuses (schemas/toll.py:66-73); the column has no CHECK.
_TOLL_TAG_STATUSES = ("active", "inactive")
#: The check_warranty_type CHECK (models/warranty.py:48-51); the schema takes any string.
_WARRANTY_TYPES = (
    "Manufacturer",
    "Powertrain",
    "Extended",
    "Bumper-to-Bumper",
    "Emissions",
    "Corrosion",
    "Other",
)
limiter = Limiter(key_func=get_remote_address)


class _RowError(ValueError):
    """A row that cannot be imported, with a reason the user sees.

    Handlers send `e.reason`, not the exception itself: CodeQL reads any
    exception text in a response as a leaked stack trace, and the reason is
    always our own.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _InsuranceRowError(_RowError):
    """An insurance row that cannot be imported, with a user-facing reason."""


def _is_blank(raw: Any) -> bool:
    """Whether a cell holds nothing: missing, null, or only whitespace."""
    return raw is None or (isinstance(raw, str) and not raw.strip())


def _json_row_date(record_data: Mapping[str, Any], key: str = "date") -> date_type:
    """The row's date under `key`, or a row error that says what's wrong with it."""
    raw = record_data.get(key)
    if _is_blank(raw):
        raise _RowError(f"{key} is missing")
    if not isinstance(raw, str):
        raise _RowError(f"{key} is not a valid date (expected YYYY-MM-DD)")
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError as e:
        raise _RowError(f"{key} is not a valid date (expected YYYY-MM-DD)") from e


def _json_optional_date(record_data: Mapping[str, Any], key: str) -> date_type | None:
    """The row's date under `key`, None when it's blank, a row error when it won't parse."""
    return None if _is_blank(record_data.get(key)) else _json_row_date(record_data, key)


def _json_row_datetime(record_data: dict[str, Any], key: str) -> datetime | None:
    """The row's timestamp under `key` as naive UTC, None when it's missing.

    A naive value is read as UTC, like every timestamp column here. Anything
    that won't parse is a row error.
    """
    raw = record_data.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise _RowError(f"{key} is not a valid date and time")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as e:
        raise _RowError(f"{key} is not a valid date and time") from e
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


def _whole_cents(value: Decimal | None, column: str) -> Decimal | None:
    """The amount, or a row error when it has a fraction of a cent."""
    if value is None:
        return None
    if value != value.quantize(Decimal("0.01")):
        raise _InsuranceRowError(f"{column} must be a whole number of cents")
    if value < 0:
        raise _InsuranceRowError(f"{column} must not be negative")
    return value


def _whole_count(value: Decimal, column: str) -> Decimal:
    """A count slot's value, or a row error when it has a fraction.

    A count is a number of days, not money, so the whole-cents rule lets 30.5
    through. The flat exports write a count with no decimals, which turns a
    stored 30.5 into 30 the next time the policy is exported.
    """
    if value != value.to_integral_value():
        raise _InsuranceRowError(f"{column} must be a whole number")
    return value


# The four bounds a Create schema's Field(ge=, gt=, le=, lt=) leaves in
# `FieldInfo.metadata`, read by attribute so annotated-types stays pydantic's
# dependency and not ours, with how each reads in a row error.
_API_BOUNDS = (
    ("ge", operator.ge, "at least"),
    ("gt", operator.gt, "more than"),
    ("le", operator.le, "at most"),
    ("lt", operator.lt, "less than"),
)


class _ImportBoundError(_RowError):
    """An imported number the API would refuse, with a reason the user sees."""


def _within_api_bounds(schema: type[BaseModel], **values: Decimal | int | None) -> None:
    """Refuse an imported number the API would refuse for the same field.

    Importers build ORM rows directly, so the Create schemas' bounds never
    ran on imported data and a negative cost or a NaN went straight in. Only
    the bounds are checked, not the precision rules: converted gallons run
    past the three decimal places `liters` allows, and would all fail.
    """
    for name, value in values.items():
        # Looked up first, so a misspelt name fails every row, not only
        # the rows that happen to fill that column.
        metadata = schema.model_fields[name].metadata
        if value is None:
            continue
        number = value if isinstance(value, Decimal) else Decimal(str(value))
        if not number.is_finite():
            raise _ImportBoundError(f"{name} must be a number")
        for bound in metadata:
            for attr, holds, reads in _API_BOUNDS:
                limit = getattr(bound, attr, None)
                if limit is None:
                    continue
                # A float bound (le=9999.999) compared as a float sits a hair
                # below 9999.999 and refused the value pydantic accepts.
                exact = Decimal(str(limit)) if isinstance(limit, float) else limit
                if not holds(number, exact):
                    # Plain digits: str() of Decimal("1e12") reads 1E+12.
                    raise _ImportBoundError(
                        f"{name} must be {reads} {exact}, not {format(number, 'f')}"
                    )


def _in_vocabulary(value: Any, field: str, vocabulary: tuple[str, ...]) -> str | None:
    """The value, or a row error when it's a word the API would refuse.

    A stored one used to break the fuel list. Blank stays allowed: that's an
    empty cell, not a word. The reason never quotes the cell, so nothing
    imported reaches the response or a log through it.
    """
    if value is None or value == "" or value in vocabulary:
        return value
    raise _RowError(f"{field} must be one of {', '.join(vocabulary)}")


def _blank_to_none(value: Any) -> Any:
    """None for a blank cell. A CHECK refuses '' where it allows NULL (P2E2)."""
    return None if _is_blank(value) else value


def _json_decimal(row: Mapping[str, Any], key: str) -> Decimal | None:
    """The number under `key`, None when it's missing or blank, a row error when it isn't one."""
    value = row.get(key)
    if _is_blank(value):
        return None
    if isinstance(value, bool):
        raise _RowError(f"{key} is not a number")
    try:
        return Decimal(str(value))
    except InvalidOperation as e:
        raise _RowError(f"{key} is not a number") from e


def _json_text(row: Mapping[str, Any], key: str, *, max_length: int | None = None) -> str | None:
    """The text under `key`, None when it's missing or blank, a row error when it isn't text.

    PostgreSQL refuses a number in a text column where SQLite stores it, and a
    value past a String(`max_length`) column where SQLite keeps it, so the two
    backends would disagree about the same file.
    """
    value = _blank_to_none(row.get(key))
    if value is not None and not isinstance(value, str):
        raise _RowError(f"{key} must be text")
    if value is not None and max_length is not None and len(value) > max_length:
        raise _RowError(f"{key} must be at most {max_length} characters")
    return value


def _first_present(row: Mapping[str, Any], *keys: str) -> Any:
    """The value under the first of `keys` that holds one: a v3+ name before its v2 alias.

    `row.get("odometer_km") or row.get("mileage")` read a 0 as missing (G3a-75).
    """
    for key in keys:
        if not _is_blank(row.get(key)):
            return row.get(key)
    return None


def _json_int(row: Mapping[str, Any], key: str) -> int | None:
    """A whole number under `key`, None when it's missing, a row error otherwise."""
    raw = row.get(key)
    if _is_blank(raw):
        return None
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, float) and raw.is_integer():
        return int(raw)
    raise _RowError(f"{key} is not a whole number")


def _local_datetime(raw: Any, key: str) -> datetime | None:
    """A fill-up's naive local time. The export never writes a zone; one given is dropped."""
    if _is_blank(raw):
        return None
    if not isinstance(raw, str):
        raise _RowError(f"{key} is not a valid date and time")
    try:
        return datetime.fromisoformat(raw.strip()).replace(tzinfo=None)
    except ValueError as e:
        raise _RowError(f"{key} is not a valid date and time") from e


def _trip_seconds(raw: Any, key: str) -> int | None:
    """The trip duration in seconds, read the way the API reads it."""
    try:
        return _parse_obc_trip_duration(raw)
    except ValueError as e:
        raise _RowError(f"{key} must be whole seconds, HH:MM or HH:MM:SS") from e


#: The warnings for a link this instance can't confirm (R6), added once the row is written.
_STATION_KEPT_AS_TEXT = "station not in this address book, kept as text"
_DRIVER_KEPT_AS_TEXT = "driver not on this instance, kept as text"


async def _portable_station(
    db: AsyncSession, station_id: int | None, name: str | None
) -> tuple[int | None, str | None, bool]:
    """The station id and text to store, and whether a link was dropped (R6).

    The id stays only when this address book holds it under the same name (the
    export writes the resolved name), so a file from another instance never
    links someone else's entry. Otherwise the name is kept as text.
    """
    text = (name or "").strip()[:150] or None
    if station_id is None:
        return None, text, False
    entry = await db.get(AddressBookEntry, station_id)
    if (
        entry is not None
        and text
        and (entry.business_name or "").strip().casefold() == text.casefold()
    ):
        return station_id, None, False
    return None, text, True


async def _portable_driver(
    db: AsyncSession, driver_id: int | None, username: str | None, freetext: str | None
) -> tuple[int | None, str | None, bool]:
    """The driver id and text to store, and whether a link was dropped (R6).

    The id stays only when it is a user here with the exported username. The
    API checks nothing more for a driver (T-5).
    """
    if driver_id is None:
        return None, ((freetext or "").strip()[:100] or None), False
    user = await db.get(User, driver_id)
    if user is not None and username and user.username.casefold() == username.strip().casefold():
        return driver_id, freetext, False
    return None, ((freetext or username or "").strip()[:100] or None), True


#: Who writes a DEF row: a purchase (the column default, models/def_record.py:44-46)
#: or the fuel form's fill-level sync (utils/def_sync.py:72). No CHECK backs it.
_DEF_ENTRY_TYPES = ("purchase", "auto_fuel_sync")


def _fuel_record_from_json(
    vin: str,
    date: date_type,
    row: Mapping[str, Any],
    *,
    idx: int,
    odometer_km: Decimal | None,
    liters: Decimal | None,
    price_per_unit: Decimal | None,
) -> FuelRecord:
    """A JSON fuel row as an unsaved record, the API's rules re-applied (R2).

    `odometer_km`, `liters` and `price_per_unit` arrive converted from a legacy
    file. The station and driver links are left for the caller to set once this
    instance has confirmed them (R6).
    """
    filled_at = _local_datetime(row.get("filled_at"), "filled_at")
    engine_hours = _json_decimal(row, "engine_hours")
    propane_liters = _json_decimal(row, "propane_liters")
    tank_size_kg = _json_decimal(row, "tank_size_kg")
    tank_quantity = _json_int(row, "tank_quantity")
    kwh = _json_decimal(row, "kwh")
    soc_start_pct = _json_decimal(row, "soc_start_pct")
    soc_end_pct = _json_decimal(row, "soc_end_pct")
    battery_soh_pct = _json_decimal(row, "battery_soh_pct")
    cost = _json_decimal(row, "cost")
    rebate = _json_decimal(row, "rebate")
    outside_temp_c = _json_decimal(row, "outside_temp_c")
    obc_l_per_100km = _json_decimal(row, "obc_l_per_100km")
    obc_avg_speed_kmh = _json_decimal(row, "obc_avg_speed_kmh")
    obc_trip_duration_s = _trip_seconds(row.get("obc_trip_duration_s"), "obc_trip_duration_s")
    _within_api_bounds(
        FuelRecordCreate,
        odometer_km=odometer_km,
        engine_hours=engine_hours,
        liters=liters,
        propane_liters=propane_liters,
        tank_size_kg=tank_size_kg,
        tank_quantity=tank_quantity,
        kwh=kwh,
        soc_start_pct=soc_start_pct,
        soc_end_pct=soc_end_pct,
        battery_soh_pct=battery_soh_pct,
        cost=cost,
        rebate=rebate,
        price_per_unit=price_per_unit,
        outside_temp_c=outside_temp_c,
        obc_l_per_100km=obc_l_per_100km,
        obc_avg_speed_kmh=obc_avg_speed_kmh,
        obc_trip_duration_s=obc_trip_duration_s,
    )
    price_basis = _in_vocabulary(
        _blank_to_none(row.get("price_basis")), "price_basis", PRICE_BASIS_VALUES
    ) or _derive_price_basis(price_per_unit, liters=liters, propane_liters=propane_liters, kwh=kwh)

    # The export has always written fuel_type_used and is_hauling but the
    # importer silently dropped both, so a restored backup lost them. Same
    # locale-tolerant normalization as the CSV path.
    raw_fuel_type = (row.get("fuel_type_used") or "").strip() or None
    normalized_fuel_type = normalize_fuel_type(raw_fuel_type)
    if raw_fuel_type and normalized_fuel_type is None:
        logger.warning(
            "Fuel import record %s: unrecognized fuel type %r → 'other'",
            idx,
            raw_fuel_type,
        )
        normalized_fuel_type = FuelTypeEnum.OTHER

    return FuelRecord(
        vin=vin,
        date=date,
        filled_at=filled_at,
        odometer_km=odometer_km,
        engine_hours=engine_hours,
        liters=liters,
        propane_liters=propane_liters,
        tank_size_kg=tank_size_kg,
        tank_quantity=tank_quantity,
        kwh=kwh,
        soc_start_pct=soc_start_pct,
        soc_end_pct=soc_end_pct,
        charge_level=_in_vocabulary(
            _blank_to_none(row.get("charge_level")), "charge_level", CHARGE_LEVEL_VALUES
        ),
        charge_location=_in_vocabulary(
            _blank_to_none(row.get("charge_location")), "charge_location", CHARGE_LOCATION_VALUES
        ),
        battery_soh_pct=battery_soh_pct,
        cost=cost,
        rebate=rebate,
        price_per_unit=price_per_unit,
        price_basis=price_basis,
        fuel_type_used=normalized_fuel_type.value if normalized_fuel_type is not None else None,
        # #164: direct ORM construction bypasses Pydantic, so the shared
        # validators run here per row (R1-M2). _coerce_octane rejects a
        # fractional value instead of silently truncating it the way a bare
        # int() would (91.9 -> 91; codex review R1-M1).
        octane=_validate_octane(_coerce_octane(row.get("octane"))),
        diesel_grade=_validate_diesel_grade(row.get("diesel_grade")),
        is_full_tank=row.get("is_full_tank", True),
        missed_fillup=row.get("missed_fillup", False),
        is_hauling=row.get("is_hauling", False),
        notes=row.get("notes"),
        payment_method=_in_vocabulary(
            _blank_to_none(row.get("payment_method")), "payment_method", PAYMENT_METHOD_VALUES
        ),
        trip_type=_in_vocabulary(
            _blank_to_none(row.get("trip_type")), "trip_type", TRIP_TYPE_VALUES
        ),
        outside_temp_c=outside_temp_c,
        obc_l_per_100km=obc_l_per_100km,
        obc_avg_speed_kmh=obc_avg_speed_kmh,
        obc_trip_duration_s=obc_trip_duration_s,
    )


def _json_fuel_key(
    row: Mapping[str, Any],
    record: FuelRecord,
    *,
    converted: bool,
    last_id: int,
    zero_was_null: bool,
) -> list[ColumnElement[bool]]:
    """R5's fuel key: date and odometer always, the rest only when the row has the key (T-16).

    A v9 row carries every key, so an hours-only or propane fill-up with no
    odometer is told apart by its quantities (R1-H1). A v<=8 file wrote 0 L
    as null, so there its null also matches a stored 0 (`zero_was_null`).
    """
    key = [
        FuelRecord.date == record.date,
        _odometer_matches(
            FuelRecord, record.odometer_km, converted=converted, last_id_before_import=last_id
        ),
    ]
    if "filled_at" in row:
        key.append(_matches(FuelRecord.filled_at, record.filled_at))
    if "liters" in row or "gallons" in row:
        key.append(
            _or_blank_zero(
                _converted_value_matches(
                    FuelRecord.liters,
                    record.liters,
                    LITRE_STEP,
                    converted=converted,
                    stored_before_import=FuelRecord.id <= last_id,
                ),
                FuelRecord.liters,
                record.liters,
                LITRE_STEP,
                zero_was_blank=zero_was_null,
            )
        )
    # NUMERIC(8,3) and (9,3).
    if "kwh" in row:
        key.append(_same_figure(FuelRecord.kwh, record.kwh, Decimal("0.001")))
    if "propane_liters" in row:
        key.append(_same_figure(FuelRecord.propane_liters, record.propane_liters, Decimal("0.001")))
    if "cost" in row:
        key.append(_money_matches(FuelRecord.cost, record.cost))
    return key


def _def_record_from_json(
    vin: str,
    date: date_type,
    row: Mapping[str, Any],
    *,
    odometer_km: Decimal | None,
    liters: Decimal | None,
    price_per_unit: Decimal | None,
) -> DEFRecord:
    """A JSON DEF row as an unsaved record, the API's rules re-applied (R2).

    No price_basis: DEF is volume-only, has no such column, and the UI passes
    'per_volume' as a literal when displaying it. No origin_fuel_record_id
    either: the fill-up it named is on the instance that wrote the file.
    """
    cost = _json_decimal(row, "cost")
    fill_level = _json_decimal(row, "fill_level")
    _within_api_bounds(
        DEFRecordCreate,
        odometer_km=odometer_km,
        liters=liters,
        price_per_unit=price_per_unit,
        cost=cost,
        fill_level=fill_level,
    )
    return DEFRecord(
        vin=vin,
        date=date,
        odometer_km=odometer_km,
        liters=liters,
        price_per_unit=price_per_unit,
        cost=cost,
        fill_level=fill_level,
        source=_json_text(row, "source"),
        brand=_json_text(row, "brand"),
        notes=_json_text(row, "notes"),
        entry_type=_in_vocabulary(
            _blank_to_none(row.get("entry_type")), "entry_type", _DEF_ENTRY_TYPES
        )
        or "purchase",
    )


def _json_def_key(
    row: Mapping[str, Any],
    record: DEFRecord,
    *,
    converted: bool,
    last_id: int,
    zero_was_null: bool,
) -> list[ColumnElement[bool]]:
    """R5's DEF key: date and odometer always, the rest only when the row has the key (T-16).

    A v<=8 file wrote 0 L and a 0.00 fill level as null, so there its null also
    matches a stored 0 (`zero_was_null`).
    """
    key = [
        DEFRecord.date == record.date,
        _odometer_matches(
            DEFRecord, record.odometer_km, converted=converted, last_id_before_import=last_id
        ),
    ]
    if "liters" in row or "gallons" in row:
        key.append(
            _or_blank_zero(
                _converted_value_matches(
                    DEFRecord.liters,
                    record.liters,
                    LITRE_STEP,
                    converted=converted,
                    stored_before_import=DEFRecord.id <= last_id,
                ),
                DEFRecord.liters,
                record.liters,
                LITRE_STEP,
                zero_was_blank=zero_was_null,
            )
        )
    if "cost" in row:
        key.append(_money_matches(DEFRecord.cost, record.cost))
    # NUMERIC(3,2).
    if "fill_level" in row:
        key.append(
            _or_blank_zero(
                _same_figure(DEFRecord.fill_level, record.fill_level, Decimal("0.01")),
                DEFRecord.fill_level,
                record.fill_level,
                Decimal("0.01"),
                zero_was_blank=zero_was_null,
            )
        )
    if "entry_type" in row:
        key.append(DEFRecord.entry_type == record.entry_type)
    return key


def _line_item_from_json(position: int, item: Any, count: int) -> tuple[dict[str, Any], int | None]:
    """One v9 line item's columns, and the index of the item that triggered it.

    The API's rules re-applied (R2); a row error names the item by `position`.
    """
    try:
        if not isinstance(item, Mapping):
            raise _RowError("must be an object")
        item = cast(Mapping[str, Any], item)
        description = _json_text(item, "description")
        if description is None:
            raise _RowError("description is missing")
        notes = _json_text(item, "notes")
        cost = _json_decimal(item, "cost")
        _within_api_bounds(ServiceLineItemCreate, cost=cost)
        category = _in_vocabulary(
            _blank_to_none(item.get("category")), "category", _SERVICE_CATEGORIES
        )
        inspection_result = _in_vocabulary(
            _blank_to_none(item.get("inspection_result")), "inspection_result", _INSPECTION_RESULTS
        )
        inspection_severity = _in_vocabulary(
            _blank_to_none(item.get("inspection_severity")),
            "inspection_severity",
            _INSPECTION_SEVERITIES,
        )
        try:
            maintenance_type = validate_maintenance_type(
                _blank_to_none(item.get("maintenance_type"))
            )
        except (ValueError, TypeError) as e:
            raise _RowError(
                "maintenance_type must be a lowercase snake_case code (2-50 chars)"
            ) from e
        link = item.get("triggered_by_inspection")
        if link is not None and (
            isinstance(link, bool)
            or not isinstance(link, int)
            or link not in range(count)
            or link == position
        ):
            raise _RowError(
                "triggered_by_inspection must be the index of another line item in this visit"
            )
    except _RowError as e:
        raise _RowError(f"line item {position}: {e.reason}") from e
    columns = {
        "description": description,
        "category": category,
        "maintenance_type": resolve_type(maintenance_type, description),
        "cost": cost,
        "notes": notes,
        "is_inspection": bool(item.get("is_inspection", False)),
        "inspection_result": inspection_result,
        "inspection_severity": inspection_severity,
    }
    return columns, link


def _json_amount(row: Mapping[str, Any], schema: type[BaseModel]) -> Decimal:
    """A row's required `amount`, held to `schema`'s bounds."""
    amount = _json_decimal(row, "amount")
    if amount is None:
        raise _RowError("amount is missing")
    _within_api_bounds(schema, amount=amount)
    return amount


def _financing_record_from_json(vin: str, row: Mapping[str, Any]) -> FinancingRecord:
    """A v9 financing row as an unsaved record, the API's rules re-applied (R2).

    The lender travels by name; the caller looks it up or makes it in the
    row's savepoint (R6).
    """
    date = _json_row_date(row)
    amount = _json_amount(row, FinancingRecordCreate)
    category = _in_vocabulary(
        _blank_to_none(row.get("category")), "category", _FINANCING_CATEGORIES
    )
    if category is None:
        raise _RowError("category is missing")
    return FinancingRecord(
        vin=vin, date=date, amount=amount, category=category, notes=_json_text(row, "notes")
    )


def _json_financing_key(record: FinancingRecord) -> list[ColumnElement[bool]]:
    """R5's financing key but the lender, which the caller compares on the loaded rows."""
    return [
        FinancingRecord.date == record.date,
        _money_matches(FinancingRecord.amount, record.amount),
        FinancingRecord.category == record.category,
    ]


def _tax_record_from_json(vin: str, row: Mapping[str, Any]) -> TaxRecord:
    """A v9 tax row as an unsaved record. No type is allowed: NULL passes the CHECK."""
    date = _json_row_date(row)
    tax_type = _in_vocabulary(_blank_to_none(row.get("tax_type")), "tax_type", _TAX_TYPES)
    amount = _json_amount(row, TaxRecordCreate)
    return TaxRecord(
        vin=vin,
        date=date,
        tax_type=tax_type,
        amount=amount,
        renewal_date=_json_optional_date(row, "renewal_date"),
        notes=_json_text(row, "notes"),
    )


def _json_tax_key(row: Mapping[str, Any], record: TaxRecord) -> list[ColumnElement[bool]]:
    """R5's tax key, each optional part only when the row has it (T-16).

    A type-less row matches a stored NULL type, so it dedups too.
    """
    key = [TaxRecord.date == record.date, _money_matches(TaxRecord.amount, record.amount)]
    if "tax_type" in row:
        key.append(_matches(TaxRecord.tax_type, record.tax_type))
    if "renewal_date" in row:
        key.append(_matches(TaxRecord.renewal_date, record.renewal_date))
    return key


def _toll_tag_from_json(vin: str, row: Mapping[str, Any]) -> TollTag:
    """A v9 toll tag as an unsaved record, its system named as the create schema names it.

    The schema's two steps in its order: tidy the whitespace, hold the length,
    then map a spelling people type to the listed name (schemas/toll.py).
    """
    raw_system = _json_text(row, "toll_system")
    if raw_system is None:
        raise _RowError("toll_system is missing")
    tidied = _tidy_toll_system(raw_system)
    if len(tidied) > 50:
        raise _RowError("toll_system must be at most 50 characters")
    tag_number = _json_text(row, "tag_number", max_length=50)
    if tag_number is None:
        raise _RowError("tag_number is missing")
    status = _in_vocabulary(_blank_to_none(row.get("status")), "status", _TOLL_TAG_STATUSES)
    return TollTag(
        vin=vin,
        toll_system=_normalize_toll_system(tidied),
        tag_number=tag_number,
        status=status or "active",
        notes=_json_text(row, "notes"),
    )


def _toll_tag_key(tag: TollTag | None) -> tuple[str, str] | None:
    """A tag as a transaction's key names it: its system and number, None for no tag."""
    return (tag.toll_system, tag.tag_number) if tag is not None else None


def _toll_transaction_from_json(
    vin: str, row: Mapping[str, Any], tag_count: int
) -> tuple[TollTransaction, int | None]:
    """A v9 toll as an unsaved record, and the index of its tag in the file's toll_tags."""
    date = _json_row_date(row)
    amount = _json_amount(row, TollTransactionCreate)
    location = _json_text(row, "location", max_length=200)
    if location is None:
        raise _RowError("location is missing")
    index = row.get("toll_tag_index")
    if index is not None and (
        isinstance(index, bool) or not isinstance(index, int) or index not in range(tag_count)
    ):
        raise _RowError("toll_tag_index must be the index of a toll tag in this file")
    record = TollTransaction(
        vin=vin, date=date, amount=amount, location=location, notes=_json_text(row, "notes")
    )
    return record, index


def _json_toll_transaction_key(record: TollTransaction) -> list[ColumnElement[bool]]:
    """R5's toll key but the tag, which the caller compares on the loaded rows."""
    return [
        TollTransaction.date == record.date,
        _money_matches(TollTransaction.amount, record.amount),
        TollTransaction.location == record.location,
    ]


def _warranty_from_json(vin: str, row: Mapping[str, Any]) -> WarrantyRecord:
    """A v9 warranty as an unsaved record, its type held to the CHECK's list (R2)."""
    warranty_type = _blank_to_none(row.get("warranty_type"))
    if warranty_type is None:
        raise _RowError("warranty_type is missing")
    warranty_type = _in_vocabulary(warranty_type, "warranty_type", _WARRANTY_TYPES)
    start_date = _json_row_date(row, "start_date")
    mileage_limit_km = _json_decimal(row, "mileage_limit_km")
    _within_api_bounds(WarrantyRecordCreate, mileage_limit_km=mileage_limit_km)
    return WarrantyRecord(
        vin=vin,
        warranty_type=warranty_type,
        provider=_json_text(row, "provider", max_length=100),
        start_date=start_date,
        end_date=_json_optional_date(row, "end_date"),
        mileage_limit_km=mileage_limit_km,
        coverage_details=_json_text(row, "coverage_details"),
        policy_number=_json_text(row, "policy_number", max_length=50),
        notes=_json_text(row, "notes"),
    )


def _json_warranty_key(row: Mapping[str, Any], record: WarrantyRecord) -> list[ColumnElement[bool]]:
    """R5's warranty key, each optional part only when the row has it (T-16).

    The mileage limit is NUMERIC(10,2): 36,000 mi is stored as 57936.384 on
    SQLite and exported as 57936.38, so it matches within half a cent (T-20).
    """
    key = [
        WarrantyRecord.warranty_type == record.warranty_type,
        WarrantyRecord.start_date == record.start_date,
    ]
    if "provider" in row:
        key.append(_matches(WarrantyRecord.provider, record.provider))
    if "end_date" in row:
        key.append(_matches(WarrantyRecord.end_date, record.end_date))
    if "policy_number" in row:
        key.append(_matches(WarrantyRecord.policy_number, record.policy_number))
    if "mileage_limit_km" in row:
        key.append(
            _same_figure(WarrantyRecord.mileage_limit_km, record.mileage_limit_km, Decimal("0.01"))
        )
    return key


def _billing_from_json(
    position: int, bill: Any, check_in_date: date_type, check_out_date: date_type | None
) -> SpotRentalBilling:
    """One v9 bill as an unsaved record; the caller sets its rental once that has an id.

    Its date is held to the rental's stay, as the billing route holds it (T-7).
    A row error names the bill by `position`.
    """
    try:
        if not isinstance(bill, Mapping):
            raise _RowError("must be an object")
        bill = cast(Mapping[str, Any], bill)
        billing_date = _json_row_date(bill, "billing_date")
        monthly_rate = _json_decimal(bill, "monthly_rate")
        electric = _json_decimal(bill, "electric")
        water = _json_decimal(bill, "water")
        waste = _json_decimal(bill, "waste")
        total = _json_decimal(bill, "total")
        _within_api_bounds(
            SpotRentalBillingCreate,
            monthly_rate=monthly_rate,
            electric=electric,
            water=water,
            waste=waste,
            total=total,
        )
        notes = _json_text(bill, "notes", max_length=1000)
        if billing_date < check_in_date:
            raise _RowError("billing date cannot be before check-in date")
        if check_out_date is not None and billing_date > check_out_date:
            raise _RowError("billing date cannot be after check-out date")
    except _RowError as e:
        raise _RowError(f"billing {position}: {e.reason}") from e
    return SpotRentalBilling(
        billing_date=billing_date,
        monthly_rate=monthly_rate,
        electric=electric,
        water=water,
        waste=waste,
        total=total,
        notes=notes,
    )


def _spot_rental_from_json(
    vin: str, row: Mapping[str, Any]
) -> tuple[SpotRental, list[SpotRentalBilling]]:
    """A v9 rental and its bills as unsaved records, the API's rules re-applied (R2).

    No vehicle-type gate and no invented first bill: a backup restores whole,
    with the bills it carries (T-7).
    """
    check_in_date = _json_row_date(row, "check_in_date")
    check_out_date = _json_optional_date(row, "check_out_date")
    nightly_rate = _json_decimal(row, "nightly_rate")
    weekly_rate = _json_decimal(row, "weekly_rate")
    monthly_rate = _json_decimal(row, "monthly_rate")
    electric = _json_decimal(row, "electric")
    water = _json_decimal(row, "water")
    waste = _json_decimal(row, "waste")
    total_cost = _json_decimal(row, "total_cost")
    _within_api_bounds(
        SpotRentalCreate,
        nightly_rate=nightly_rate,
        weekly_rate=weekly_rate,
        monthly_rate=monthly_rate,
        electric=electric,
        water=water,
        waste=waste,
        total_cost=total_cost,
    )
    location_name = _json_text(row, "location_name", max_length=100)
    raw_bills = row.get("billings")
    if not isinstance(raw_bills, list):
        raise _RowError("billings must be a list")
    bills = [
        _billing_from_json(position, bill, check_in_date, check_out_date)
        for position, bill in enumerate(cast(list[Any], raw_bills))
    ]
    rental = SpotRental(
        vin=vin,
        location_name=location_name,
        location_address=_json_text(row, "location_address"),
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        nightly_rate=nightly_rate,
        weekly_rate=weekly_rate,
        monthly_rate=monthly_rate,
        electric=electric,
        water=water,
        waste=waste,
        total_cost=total_cost,
        amenities=_json_text(row, "amenities"),
        notes=_json_text(row, "notes"),
    )
    return rental, bills


def _json_spot_rental_key(row: Mapping[str, Any], rental: SpotRental) -> list[ColumnElement[bool]]:
    """R5's rental key but the bills, each optional part only when the row has it (T-16)."""
    key = [SpotRental.check_in_date == rental.check_in_date]
    if "location_name" in row:
        key.append(_matches(SpotRental.location_name, rental.location_name))
    if "check_out_date" in row:
        key.append(_matches(SpotRental.check_out_date, rental.check_out_date))
    if "total_cost" in row:
        key.append(_money_matches(SpotRental.total_cost, rental.total_cost))
    return key


def _bill_counts(
    pairs: Iterable[tuple[date_type, Decimal | None]],
) -> Counter[tuple[date_type, Decimal]]:
    """A rental's bills as counts, each total at the cent, a missing one as 0."""
    return Counter(
        (billing_date, _at_scale(total, _MONEY_STEP) or Decimal(0)) for billing_date, total in pairs
    )


def _coverages_from_rows(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The standard coverages of a schema-8 backup entry.

    Importers build ORM rows directly, so the API schema's rules do not reach
    them and are re-applied here from the same catalogue: a slot the catalogue
    does not give a coverage is an error rather than a silently dropped amount,
    every money figure is a whole number of cents, and a count is whole.
    """
    rows = []
    for item in raw:
        key = item.get("coverage_key")
        coverage = COVERAGE_BY_KEY.get(key)
        if coverage is None:
            logger.warning("Import: unknown insurance coverage %s, skipped", sanitize_for_log(key))
            continue
        slots = dict(coverage.slots())
        values = {}
        for name in ("limit_primary", "limit_secondary", "deductible", "premium"):
            value = item.get(name)
            value = Decimal(str(value)) if value is not None else None
            slot = slots.get(name)
            column = f"{coverage.label} {name}"
            if value is not None and slot is None:
                raise _InsuranceRowError(f"{key} has no {name}")
            if value is not None and slot is not None and slot.kind == "count":
                value = _whole_count(value, column)
            values[name] = _whole_cents(value, column)
        rows.append({"coverage_key": key, **values})
    return rows


def _coverages_from_text(text: str | None) -> tuple[list[dict[str, Any]], list[dict], list[str]]:
    """A free-text coverage box as coverages, named fields and leftover prose.

    The CSV column and a schema-7 backup both carry one text box, read here
    through the SAME parser migration 108 uses AND placed the same way, so a
    restored old backup lands exactly what an in-place upgrade would have
    produced rather than only its coverage rows.
    """
    parse = parse_coverage_lines(text)
    leftover_fields, kept_prose = place_leftovers(parse)
    fields = [{"label": label, "value": value} for label, value in leftover_fields]
    return [coverage_row(item) for item in parse.coverages], fields, kept_prose


def _merge_converted(row: dict[str, Any], text: str | None) -> None:
    """Fold a text box's conversion into a row that may already carry its own
    named fields and notes; nothing the box held is dropped."""
    coverages, fields, notes = _coverages_from_text(text)
    row["coverages"] = coverages
    row["fields"] = [*(row.get("fields") or []), *fields]
    if notes:
        row["notes"] = "\n".join(filter(None, [(row.get("notes") or "").rstrip(), *notes])) or None


def _insurance_amounts_within_api_bounds(row: dict[str, Any]) -> None:
    """Hold a row's share, deductible and coverage amounts to the API's bounds.

    Importers build ORM rows directly, so the Create schemas never ran on them,
    and a number past its column was a 500 on PostgreSQL.
    """
    _within_api_bounds(
        PolicyVehicleCreate, premium_share=row["premium"], deductible=row["deductible"]
    )
    coverages: list[dict[str, Any]] = row.get("coverages") or []
    for coverage in coverages:
        try:
            _within_api_bounds(
                CoverageEntry,
                limit_primary=coverage.get("limit_primary"),
                limit_secondary=coverage.get("limit_secondary"),
                deductible=coverage.get("deductible"),
                premium=coverage.get("premium"),
            )
        except _ImportBoundError as e:
            raise _ImportBoundError(f"{coverage.get('coverage_key')} {e.reason}") from e


def _grown_premium(total: Decimal, premium: Decimal) -> Decimal:
    """A policy's premium plus one more vehicle's. Each fits, the sum may not."""
    grown = total + premium
    if grown > MONEY_MAX:
        raise _ImportBoundError(too_large("The policy premium"))
    return grown


async def _import_insurance_row(
    db: AsyncSession,
    access: Any,
    vin: str,
    row: dict[str, Any],
    skip_duplicates: bool,
) -> bool:
    """Put one vehicle's insurance row onto a household policy.

    Returns False when the row was skipped as a duplicate. The policy is found
    by the same key migration 107 merges on, so importing two vehicles' files
    rebuilds ONE household policy.

    THE IMPORTER NEVER REWRITES EXISTING MONEY. A PRE-EXISTING policy only
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
    _insurance_amounts_within_api_bounds(row)
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
        elif target.premium_amount is not None and premium is not None:
            target.premium_amount = _grown_premium(target.premium_amount, premium)

        link = InsurancePolicyVehicle(
            vin=vin,
            policy_type=row["policy_type"],
            premium_share=premium,
            deductible=row["deductible"],
            notes=row["notes"],
            effective_to=row.get("effective_to"),
        )
        target.vehicle_links.append(link)
        for coverage in row.get("coverages") or []:
            link.coverages.append(InsuranceCoverage(**coverage))
        for order, item in enumerate(row.get("fields") or []):
            target.all_fields.append(
                InsurancePolicyField(
                    policy_vehicle=link, label=item["label"], value=item["value"], sort_order=order
                )
            )
        await db.flush()
    return True


class ImportResult:
    """Result of an import operation."""

    def __init__(self):
        self.success_count: int = 0
        self.error_count: int = 0
        self.skipped_count: int = 0
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def add_success(self) -> None:
        self.success_count += 1

    def add_error(self, row_num: int, message: str) -> None:
        self.error_count += 1
        self.errors.append(f"Row {row_num}: {message}")

    def add_warning(self, row_num: int, message: str) -> None:
        """A row that imported, but not whole."""
        self.warnings.append(f"Row {row_num}: {message}")

    def add_skip(self) -> None:
        self.skipped_count += 1

    def to_dict(self) -> dict[str, int | list[str]]:
        return {
            "success_count": self.success_count,
            "error_count": self.error_count,
            "skipped_count": self.skipped_count,
            "errors": self.errors,
            "warnings": self.warnings,
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
    value = units.to_canonical(quantity, parse_decimal(row.get(header, "")))
    # R7: a converted figure is rounded to its column's scale before the write,
    # so SQLite stores what PostgreSQL would; a canonical one is left as given.
    return _at_scale(value, _COLUMN_SCALE[quantity]) if units.converts(quantity) else value


@dataclass(frozen=True)
class _ServiceCsvRow:
    """One service CSV row: its visit's columns and its own line item."""

    row_num: int
    visit_number: str | None
    date: date_type
    category: str | None
    odometer_km: Decimal | None
    engine_hours: Decimal | None
    vendor_name: str | None
    tax_amount: Decimal | None
    shop_supplies: Decimal | None
    misc_fees: Decimal | None
    insurance_claim_number: str | None
    split_notes: bool  # the file has Item Notes and Visit Notes (v8)
    visit_notes: str | None
    item_notes: str | None  # a v<=7 file's one Notes cell lands here and in visit_notes
    description: str | None
    cost: Decimal | None
    has_item: bool

    @property
    def group(self) -> tuple[Any, ...]:
        """The visit the row belongs to: its number, else what one visit's rows share."""
        if self.visit_number:
            return ("visit", self.visit_number)
        return ("shared", self.date, self.odometer_km, self.vendor_name, self.category)


def _parse_service_row(
    row_num: int, row: Mapping[str, Any], units: CsvUnitContext
) -> _ServiceCsvRow:
    """One service CSV row read and held to the API's bounds; a row error says what's wrong."""

    def text(column: str) -> str | None:
        # The export quotes a formula-like cell; the quote isn't the text (T-21).
        return unquote_csv_cell(row.get(column) or "").strip() or None

    date = parse_date(row.get("Date") or "")
    if not date:
        raise _RowError("Date is required")

    # Parse optional fields; accept both old and new header names
    raw_category = text("Category")
    service_type = text("Service Type")
    raw_description = text("Description")

    # "Category" maps to service_category if valid; "Service Type" is the description
    if raw_category and raw_category in VALID_SERVICE_CATEGORIES:
        category = raw_category
    elif service_type and service_type in VALID_SERVICE_CATEGORIES:
        category = service_type
    else:
        category = None

    # Distance arrives as a v6 token header (`Odometer (mi)`), as
    # `Odometer (km)`, or as legacy v2 `Mileage` in miles. `units`
    # already resolved which, from the file and nothing else.
    odometer_km = _canonical_cell(units, row, DISTANCE)
    # Engine-hours: hour-metered vehicles (ATVs, side-by-sides, equipment).
    # Dimensionless, no unit conversion (never present in legacy v2 CSVs).
    engine_hours = parse_decimal(row.get("Engine Hours") or "")
    cost = parse_decimal(row.get("Cost") or "")
    tax_amount = parse_decimal(row.get("Tax") or "")
    shop_supplies = parse_decimal(row.get("Shop Supplies") or "")
    misc_fees = parse_decimal(row.get("Misc Fees") or "")
    _within_api_bounds(
        ServiceVisitCreate,
        odometer_km=odometer_km,
        engine_hours=engine_hours,
        tax_amount=tax_amount,
        shop_supplies=shop_supplies,
        misc_fees=misc_fees,
    )
    _within_api_bounds(ServiceLineItemCreate, cost=cost)

    split_notes = "Item Notes" in row or "Visit Notes" in row
    if split_notes:
        item_notes = text("Item Notes")
        visit_notes = text("Visit Notes")
    else:
        item_notes = visit_notes = text("Notes")
    return _ServiceCsvRow(
        row_num=row_num,
        visit_number=(row.get("Visit") or "").strip() or None,
        date=date,
        category=category,
        odometer_km=odometer_km,
        engine_hours=engine_hours,
        vendor_name=text("Vendor") or text("Vendor Name"),
        tax_amount=tax_amount,
        shop_supplies=shop_supplies,
        misc_fees=misc_fees,
        insurance_claim_number=text("Insurance Claim"),
        split_notes=split_notes,
        visit_notes=visit_notes,
        item_notes=item_notes,
        # Use service_type or raw_category as description fallback
        description=raw_description or service_type or raw_category,
        cost=cost,
        # In v8 a row with no item cells is a visit with no line items, the
        # one row the export writes for one. An older file has no such row.
        has_item=(
            not split_notes
            or raw_description is not None
            or cost is not None
            or item_notes is not None
        ),
    )


async def _vendor_id_for(db: AsyncSession, name: str | None) -> int | None:
    """The vendor called `name`, made when there's none yet; None for no name."""
    if not name:
        return None
    vendor = (
        (await db.execute(select(Vendor).where(Vendor.name == name).limit(1))).scalars().first()
    )
    if vendor is None:
        vendor = Vendor(name=name)
        db.add(vendor)
        await db.flush()
    return vendor.id


def _visit_fee_key(row: _ServiceCsvRow) -> tuple[ColumnElement[bool], ...]:
    """A visit's own amounts and claim number as match conditions; 0 and NULL alike.

    Without them two visits that differ only in tax match the same stored
    visit, and the first spends it (Codex R2).
    """
    return (
        _money_matches(ServiceVisit.tax_amount, row.tax_amount),
        _money_matches(ServiceVisit.shop_supplies, row.shop_supplies),
        _money_matches(ServiceVisit.misc_fees, row.misc_fees),
        _matches(ServiceVisit.insurance_claim_number, row.insurance_claim_number),
    )


#: What `_same_visit` reads off a stored visit.
_VISIT_MATCH_LOADS = (selectinload(ServiceVisit.vendor), selectinload(ServiceVisit.line_items))


def _item_counts(pairs: Iterable[tuple[str, Decimal | None]]) -> Counter[tuple[str, Decimal]]:
    """(description, cost) pairs as counts, the cost at the cent, a missing one as 0 (v7 wrote $0 blank).

    The cent is the column's scale; a stored row reads back at it through the ORM (T-20).
    """
    return Counter(
        (description, _at_scale(cost, _MONEY_STEP) or Decimal(0)) for description, cost in pairs
    )


def _row_item_counts(group: list[_ServiceCsvRow]) -> Counter[tuple[str, Decimal]]:
    """The line items a group of rows writes, as `_write_service_csv_visit` names them."""
    return _item_counts(
        (row.description or row.category or "Service", row.cost) for row in group if row.has_item
    )


def _same_visit(
    visit: ServiceVisit,
    *,
    vendor_name: str | None,
    check_vendor: bool,
    items: Counter[tuple[str, Decimal]] | None,
) -> bool:
    """Whether a stored visit (vendor and items loaded) is the file's visit (R5).

    `items` None means the file doesn't carry them, so they aren't compared.
    """
    if check_vendor and (visit.vendor.name if visit.vendor else None) != vendor_name:
        return False
    return items is None or _item_counts((i.description, i.cost) for i in visit.line_items) == items


def _visit_total(item_costs: Iterable[Decimal | None], *fees: Decimal | None) -> Decimal:
    """A written visit's total: its items' costs and its fees, the ones it has.

    A row error past the largest amount the column holds, though each part fits.
    """
    total = sum((amount for amount in (*item_costs, *fees) if amount is not None), Decimal(0))
    if total > MONEY_MAX:
        raise _ImportBoundError(too_large("The visit total"))
    return total


async def _write_service_csv_visit(
    db: AsyncSession, vin: str, group: list[_ServiceCsvRow]
) -> ServiceVisit:
    """One visit and its line items from a group of rows; the first row supplies the visit's columns."""
    first = group[0]
    if first.split_notes:
        visit_notes = first.visit_notes
        visit_took_notes = False
    else:
        # A v<=7 row's Notes were its item's, or the visit's when the item had
        # none, so the same Notes on every row are the visit's (T-13).
        visit_took_notes = len({row.item_notes for row in group}) == 1
        visit_notes = first.item_notes if visit_took_notes else None
    item_rows = [row for row in group if row.has_item]
    total_cost = _visit_total(
        (row.cost for row in item_rows), first.tax_amount, first.shop_supplies, first.misc_fees
    )

    visit = ServiceVisit(
        vin=vin,
        date=first.date,
        odometer_km=first.odometer_km,
        engine_hours=first.engine_hours,
        service_category=first.category or "Maintenance",
        vendor_id=await _vendor_id_for(db, first.vendor_name),
        tax_amount=first.tax_amount,
        shop_supplies=first.shop_supplies,
        misc_fees=first.misc_fees,
        insurance_claim_number=first.insurance_claim_number,
        notes=visit_notes,
        total_cost=total_cost,
    )
    db.add(visit)
    await db.flush()
    for row in item_rows:
        description = row.description or row.category or "Service"
        db.add(
            ServiceLineItem(
                visit_id=visit.id,
                description=description,
                maintenance_type=classify(description),
                # A blank cost stays blank (R2); it used to be written as 0.
                cost=row.cost,
                notes=None if visit_took_notes else row.item_notes,
            )
        )
    await db.flush()
    return visit


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
    matcher = await _DuplicateMatcher.before_import(db, ServiceVisit)
    readings = _ImportReadings()

    import_result = ImportResult()
    # The key compares only the columns the file has (T-16): a v8 file writes
    # Tax, Shop Supplies, Misc Fees and Insurance Claim together, an older one
    # none of them. Read off the first row, so an upload with none has none.
    header: set[str] = set(rows[0]) if rows else set()
    carries_vendor = "Vendor" in header or "Vendor Name" in header
    carries_description = "Description" in header
    carries_fees = "Tax" in header

    # Every row first, then each visit: a v8 row names its visit by number, an
    # older one belongs with the rows sharing its date, odometer, vendor and
    # category (G4-73). Counts stay per row (T-4).
    groups: dict[tuple[Any, ...], list[_ServiceCsvRow]] = {}
    for row_num, row in enumerate(rows, start=2):  # Start at 2 (header is row 1)
        try:
            parsed = _parse_service_row(row_num, row, units)
        except _RowError as e:
            import_result.add_error(row_num, e.reason)
            continue
        except Exception as e:
            # Intentional catch-all: per-row errors should not stop the import
            logger.error("Service import row %d failed: %s", row_num, sanitize_for_log(e))
            import_result.add_error(row_num, "Invalid service record data")
            continue
        groups.setdefault(parsed.group, []).append(parsed)

    for group in groups.values():
        first = group[0]
        try:
            # R5's service key: a stored visit on the day and odometer with the
            # same shop, fees and line items, each only where the file has it.
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    ServiceVisit,
                    ServiceVisit.vin == vin,
                    ServiceVisit.date == first.date,
                    _odometer_matches(
                        ServiceVisit,
                        first.odometer_km,
                        converted=odometer_converted,
                        last_id_before_import=matcher.last_id(ServiceVisit),
                    ),
                    *(_visit_fee_key(first) if carries_fees else ()),
                    options=_VISIT_MATCH_LOADS,
                    same=lambda visit: _same_visit(
                        visit,
                        vendor_name=first.vendor_name,
                        check_vendor=carries_vendor,
                        items=_row_item_counts(group) if carries_description else None,
                    ),
                )
                is not None
            ):
                for _row in group:
                    import_result.add_skip()
                continue

            # A savepoint per visit, covering the vendor lookup/create, the
            # visit and its line items together: a CHECK or length violation
            # on any of them rolls the visit back alone instead of poisoning
            # the session for every visit and loop still to come.
            async with db.begin_nested():
                visit = await _write_service_csv_visit(db, vin, group)
        except _RowError as e:
            for row in group:
                import_result.add_error(row.row_num, e.reason)
            continue
        except Exception as e:
            # Intentional catch-all: one visit's failure should not stop the import
            logger.error(
                "Service import rows %s failed: %s",
                [r.row_num for r in group],
                sanitize_for_log(e),
            )
            for row in group:
                import_result.add_error(row.row_num, "Invalid service record data")
            continue
        for _row in group:
            import_result.add_success()
        readings.add(
            "service_visit",
            visit.id,
            visit.date,
            odometer_km=visit.odometer_km,
            engine_hours=visit.engine_hours,
        )

    await readings.apply(db, vin, claim=False)
    await db.commit()
    # Imported services may be the newest of a rule's type: reconcile once per
    # upload (own lock, own commit), never per row.
    await maintenance_service.reconcile_vehicle(db, vin)
    await invalidate_cache_for_vehicle(vin)

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
    has_volume = units.column(VOLUME) is not None
    # v8 is the first fuel CSV to write a 0 L fill-up as 0, not a blank cell.
    zero_was_blank = _zero_was_blank(units.version, 8)
    matcher = await _DuplicateMatcher.before_import(db, FuelRecord)
    readings = _ImportReadings()

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

            # The fourteen columns the export has written since v4 and this
            # importer dropped (G3a-68). A short row's missing cell is None in
            # DictReader, hence `or ""` on every text read.
            filled_at = _local_datetime(row.get("Filled At"), "Filled At")
            is_hauling = parse_bool(row.get("Is Hauling", "False"))
            station_id = parse_int(row.get("Station ID", ""))
            station_cell = unquote_csv_cell((row.get("Station") or "").strip()) or None
            driver_id = parse_int(row.get("Driver ID", ""))
            driver_cell = unquote_csv_cell((row.get("Driver") or "").strip()) or None
            payment_method = _in_vocabulary(
                _blank_to_none((row.get("Payment Method") or "").strip()),
                "payment_method",
                PAYMENT_METHOD_VALUES,
            )
            trip_type = _in_vocabulary(
                _blank_to_none((row.get("Trip Type") or "").strip()), "trip_type", TRIP_TYPE_VALUES
            )
            obc_trip_duration_s = _trip_seconds(
                row.get("OBC Trip Duration (s)", ""), "OBC Trip Duration (s)"
            )
            soc_start_pct = parse_decimal(row.get("SOC Start (%)", ""))
            soc_end_pct = parse_decimal(row.get("SOC End (%)", ""))
            battery_soh_pct = parse_decimal(row.get("Battery SOH (%)", ""))
            charge_level = _in_vocabulary(
                _blank_to_none((row.get("Charge Level") or "").strip()),
                "charge_level",
                CHARGE_LEVEL_VALUES,
            )
            charge_location = _in_vocabulary(
                _blank_to_none((row.get("Charge Location") or "").strip()),
                "charge_location",
                CHARGE_LOCATION_VALUES,
            )
            # After every read, so each figure it names has been read (R1-F1).
            _within_api_bounds(
                FuelRecordCreate,
                odometer_km=odometer_km,
                engine_hours=engine_hours,
                liters=liters,
                price_per_unit=price_per_unit,
                cost=cost,
                rebate=rebate,
                outside_temp_c=outside_temp_c,
                obc_l_per_100km=obc_l_per_100km,
                obc_avg_speed_kmh=obc_avg_speed_kmh,
                soc_start_pct=soc_start_pct,
                soc_end_pct=soc_end_pct,
                battery_soh_pct=battery_soh_pct,
                obc_trip_duration_s=obc_trip_duration_s,
            )

            # R5's fuel key. The CSV carries no kWh or propane (J7). A part is
            # compared only when the file has its column (T-16), so two same-day
            # fill-ups at one odometer both import (R1-H1).
            if skip_duplicates:
                key = [
                    FuelRecord.date == date,
                    _odometer_matches(
                        FuelRecord,
                        odometer_km,
                        converted=odometer_converted,
                        last_id_before_import=matcher.last_id(FuelRecord),
                    ),
                ]
                if "Filled At" in row:
                    key.append(_matches(FuelRecord.filled_at, filled_at))
                if has_volume:
                    key.append(
                        _or_blank_zero(
                            _converted_value_matches(
                                FuelRecord.liters,
                                liters,
                                LITRE_STEP,
                                converted=units.converts(VOLUME),
                                stored_before_import=FuelRecord.id <= matcher.last_id(FuelRecord),
                            ),
                            FuelRecord.liters,
                            liters,
                            LITRE_STEP,
                            zero_was_blank=zero_was_blank,
                        )
                    )
                if "Total Cost" in row or "Cost" in row:
                    key.append(_money_matches(FuelRecord.cost, cost))
                if await matcher.take(db, FuelRecord, FuelRecord.vin == vin, *key) is not None:
                    import_result.add_skip()
                    continue

            # With a Driver ID the Driver cell is the linked user's username (T-5).
            station_id, station_text, station_dropped = await _portable_station(
                db, station_id, station_cell
            )
            driver_id, driver_text, driver_dropped = await _portable_driver(
                db,
                driver_id,
                username=driver_cell if driver_id is not None else None,
                freetext=None if driver_id is not None else driver_cell,
            )

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
                filled_at=filled_at,
                is_hauling=is_hauling,
                station_address_book_id=station_id,
                station_name_freetext=station_text,
                driver_user_id=driver_id,
                driver_name_freetext=driver_text,
                payment_method=payment_method,
                trip_type=trip_type,
                obc_trip_duration_s=obc_trip_duration_s,
                soc_start_pct=soc_start_pct,
                soc_end_pct=soc_end_pct,
                charge_level=charge_level,
                charge_location=charge_location,
                battery_soh_pct=battery_soh_pct,
            )
            # A savepoint per row, flushed inside it so the end-of-import sync
            # has the record's id, and a row the database rejects rolls back
            # alone instead of failing the whole upload at the final commit.
            async with db.begin_nested():
                db.add(record)
                await db.flush()
            readings.add(
                "fuel",
                record.id,
                record.date,
                odometer_km=record.odometer_km,
                engine_hours=record.engine_hours,
            )
            import_result.add_success()
            if station_dropped:
                import_result.add_warning(row_num, _STATION_KEPT_AS_TEXT)
            if driver_dropped:
                import_result.add_warning(row_num, _DRIVER_KEPT_AS_TEXT)

        except _RowError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Fuel import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid fuel record data")

    await readings.apply(db, vin, claim=False)
    await db.commit()
    await invalidate_cache_for_vehicle(vin)

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
    has_volume = units.column(VOLUME) is not None
    # v8 is the first DEF CSV to write 0 L and a 0.00 fill level as 0, not blank.
    zero_was_blank = _zero_was_blank(units.version, 8)
    matcher = await _DuplicateMatcher.before_import(db, DEFRecord)
    readings = _ImportReadings()

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
            _within_api_bounds(
                DEFRecordCreate,
                odometer_km=odometer_km,
                liters=liters,
                price_per_unit=price_per_unit,
                cost=cost,
                fill_level=fill_level,
            )
            source = row.get("Source", "").strip() or None
            brand = row.get("Brand", "").strip() or None
            notes = row.get("Notes", "").strip() or None

            # R5's DEF key, each part only when the file has its column (T-16).
            # The CSV has no entry type.
            if skip_duplicates:
                key = [
                    DEFRecord.date == date,
                    _odometer_matches(
                        DEFRecord,
                        odometer_km,
                        converted=odometer_converted,
                        last_id_before_import=matcher.last_id(DEFRecord),
                    ),
                ]
                if has_volume:
                    key.append(
                        _or_blank_zero(
                            _converted_value_matches(
                                DEFRecord.liters,
                                liters,
                                LITRE_STEP,
                                converted=units.converts(VOLUME),
                                stored_before_import=DEFRecord.id <= matcher.last_id(DEFRecord),
                            ),
                            DEFRecord.liters,
                            liters,
                            LITRE_STEP,
                            zero_was_blank=zero_was_blank,
                        )
                    )
                if "Total Cost" in row or "Cost" in row:
                    key.append(_money_matches(DEFRecord.cost, cost))
                if "Fill Level" in row:
                    # NUMERIC(3,2).
                    key.append(
                        _or_blank_zero(
                            _same_figure(DEFRecord.fill_level, fill_level, Decimal("0.01")),
                            DEFRecord.fill_level,
                            fill_level,
                            Decimal("0.01"),
                            zero_was_blank=zero_was_blank,
                        )
                    )
                if await matcher.take(db, DEFRecord, DEFRecord.vin == vin, *key) is not None:
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
            # A savepoint per row, flushed inside it so the end-of-import sync
            # has the record's id, and a row the database rejects rolls back
            # alone instead of failing the whole upload at the final commit.
            async with db.begin_nested():
                db.add(record)
                await db.flush()
            readings.add("def", record.id, record.date, odometer_km=record.odometer_km)
            import_result.add_success()

        except _ImportBoundError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("DEF import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid DEF record data")

    await readings.apply(db, vin, claim=False)
    await db.commit()
    await invalidate_cache_for_vehicle(vin)

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
    matcher = await _DuplicateMatcher.before_import(db, OdometerRecord)

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
            _within_api_bounds(OdometerRecordCreate, odometer_km=odometer_km)

            # A copied sync marker would make the reading look owned (R4, N-2).
            notes = _without_sync_marker(row.get("Notes", "").strip() or None)

            # Check for duplicates if requested
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    OdometerRecord,
                    OdometerRecord.vin == vin,
                    OdometerRecord.date == date,
                    _odometer_matches(
                        OdometerRecord,
                        odometer_km,
                        converted=odometer_converted,
                        last_id_before_import=matcher.last_id(OdometerRecord),
                    ),
                )
                is not None
            ):
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

        except _ImportBoundError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid record data")

    await db.commit()
    await invalidate_cache_for_vehicle(vin)

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
    matcher = await _DuplicateMatcher.before_import(db, HoursRecord)

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
            _within_api_bounds(HoursRecordCreate, engine_hours=engine_hours)

            # A copied sync marker would make the reading look owned (R4, N-2).
            notes = _without_sync_marker(row.get("Notes", "").strip() or None)

            # Check for duplicates if requested. NUMERIC(10,1); no source (T-19).
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    HoursRecord,
                    HoursRecord.vin == vin,
                    HoursRecord.date == date,
                    _same_figure(HoursRecord.engine_hours, engine_hours, Decimal("0.1")),
                )
                is not None
            ):
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
            # A savepoint per row. Leaving it flushes the insert, so a row the
            # database rejects rolls back alone instead of failing the whole
            # upload at the final commit (production sessions do not autoflush).
            async with db.begin_nested():
                db.add(record)
            import_result.add_success()

        except _ImportBoundError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Hours import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid hours record data")

    await db.commit()
    await invalidate_cache_for_vehicle(vin)

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
    matcher = await _DuplicateMatcher.before_import(db, WarrantyRecord)
    has_mileage_limit = units.column(DISTANCE) is not None

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
            _within_api_bounds(WarrantyRecordCreate, mileage_limit_km=mileage_limit_km)
            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested. A key part is compared only
            # when the file has its column (T-16): DictReader gives every row
            # each header key, so `in row` is a header check.
            if skip_duplicates and start_date and warranty_type:
                key = [
                    WarrantyRecord.warranty_type == warranty_type,
                    _matches(WarrantyRecord.provider, provider),
                    WarrantyRecord.start_date == start_date,
                ]
                if "End Date" in row:
                    key.append(_matches(WarrantyRecord.end_date, end_date))
                if "Policy Number" in row:
                    key.append(_matches(WarrantyRecord.policy_number, policy_number))
                if has_mileage_limit:
                    key.append(
                        _converted_value_matches(
                            WarrantyRecord.mileage_limit_km,
                            mileage_limit_km,
                            KM_STEP,
                            converted=units.converts(DISTANCE),
                            stored_before_import=(
                                WarrantyRecord.id <= matcher.last_id(WarrantyRecord)
                            ),
                        )
                    )
                if (
                    await matcher.take(db, WarrantyRecord, WarrantyRecord.vin == vin, *key)
                    is not None
                ):
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

        except _ImportBoundError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid record data")

    await db.commit()
    await invalidate_cache_for_vehicle(vin)

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

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            record = {
                "provider": row.get("Provider", ""),
                "policy_number": row.get("Policy Number", ""),
                "policy_type": row.get("Type", "").strip() or None,
                "start_date": parse_date(row.get("Start Date", "")),
                "end_date": parse_date(row.get("End Date", "")),
                "premium": parse_decimal(row.get("Premium", "")),
                "premium_frequency": row.get("Premium Frequency", "").strip() or None,
                "deductible": parse_decimal(row.get("Deductible", "")),
                "notes": row.get("Notes", "").strip() or None,
            }
            # The flat file has one Coverage Limits column: converted whole,
            # the way migration 108 converts the column it replaced.
            _merge_converted(record, row.get("Coverage Limits", "").strip() or None)
            imported = await _import_insurance_row(
                db,
                access,
                vin,
                record,
                skip_duplicates,
            )
            if imported:
                import_result.add_success()
            else:
                import_result.add_skip()
        except (_InsuranceRowError, _ImportBoundError) as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid record data")

    await db.commit()
    await invalidate_cache_for_vehicle(vin)

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
    matcher = await _DuplicateMatcher.before_import(db, TaxRecord)

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
            _within_api_bounds(TaxRecordCreate, amount=amount)
            renewal_date = parse_date(row.get("Renewal Date", "")) or parse_date(
                row.get("Due Date", "")
            )
            notes = row.get("Notes", "").strip() or None

            # Check for duplicates if requested. A key part is compared only
            # when the file has its column (T-16): DictReader gives every row
            # each header key, so `in row` is a header check.
            if skip_duplicates and record_date:
                key = [TaxRecord.date == record_date, _matches(TaxRecord.tax_type, tax_type)]
                if "Amount" in row:
                    key.append(_money_matches(TaxRecord.amount, amount))
                if "Renewal Date" in row or "Due Date" in row:
                    key.append(_matches(TaxRecord.renewal_date, renewal_date))
                if await matcher.take(db, TaxRecord, TaxRecord.vin == vin, *key) is not None:
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

        except _ImportBoundError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("Import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid record data")

    await db.commit()
    await invalidate_cache_for_vehicle(vin)

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
    matcher = await _DuplicateMatcher.before_import(db, Note)

    import_result = ImportResult()

    for row_num, row in enumerate(csv_reader, start=2):
        try:
            date = parse_date(row.get("Date", ""))
            title = row.get("Title", "").strip() or None
            content = row.get("Content", "").strip() or None

            # Check for duplicates if requested. A key part is compared only
            # when the file has its column (T-16): DictReader gives every row
            # each header key, so `in row` is a header check.
            if skip_duplicates and date:
                key = [Note.date == date]
                if "Title" in row:
                    key.append(_matches(Note.title, title))
                if "Content" in row:
                    key.append(_matches(Note.content, content))
                if await matcher.take(db, Note, Note.vin == vin, *key) is not None:
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
    await invalidate_cache_for_vehicle(vin)

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
    # v9 is the first JSON export to write a 0 L fill-up and a 0.00 fill level as 0.
    zero_was_null = _zero_was_blank(export_version, 9)
    if is_legacy_v2:
        logger.warning(
            "JSON import for vin=%s detected legacy v2 backup (no export_version "
            "marker); converting imperial values to metric on ingest.",
            sanitize_for_log(vin),
        )

    # A legacy figure is converted, so it is rounded to its column's scale
    # (R7, T-10); a v3+ figure is canonical already and is left as given.
    def _maybe_mi_to_km(val: Any) -> Decimal | None:
        if val is None or val == "":
            return None
        d = Decimal(str(val))
        # Infinity and NaN pass for the bounds check to name. An sNaN isn't
        # finite either, so it passes too: multiplying it below would raise.
        if not is_legacy_v2 or not d.is_finite():
            return d
        return _at_scale(d * UnitConverter.MILES_TO_KM, Decimal("0.01"))

    def _maybe_gal_to_l(val: Any) -> Decimal | None:
        if val is None or val == "":
            return None
        d = Decimal(str(val))
        if not is_legacy_v2 or not d.is_finite():
            return d
        return _at_scale(d * UnitConverter.US_GALLONS_TO_LITERS, Decimal("0.001"))

    def _maybe_per_gal_to_per_l(val: Any) -> Decimal | None:
        if val is None or val == "":
            return None
        d = Decimal(str(val))
        if not is_legacy_v2 or not d.is_finite():
            return d
        return _at_scale(d / UnitConverter.US_GALLONS_TO_LITERS, Decimal("0.001"))

    await lock_vehicle_for_write(db, vin)
    # Taken before the first section writes: only a row at or below these can
    # carry the pre-v3.4.0 factors (see `_converted_value_matches`), and a v3
    # backup is canonical already, so only a legacy one was converted. The same
    # ceilings keep a row this import wrote from being a duplicate (R5).
    matcher = await _DuplicateMatcher.before_import(
        db,
        ServiceVisit,
        FuelRecord,
        DEFRecord,
        OdometerRecord,
        HoursRecord,
        FinancingRecord,
        TaxRecord,
        TollTag,
        TollTransaction,
        WarrantyRecord,
        SpotRental,
    )
    readings = _ImportReadings()

    errors: list[str] = []
    warnings: list[str] = []
    results = {
        "service_records": {"success": 0, "errors": 0, "skipped": 0},
        "fuel_records": {"success": 0, "errors": 0, "skipped": 0},
        "def_records": {"success": 0, "errors": 0, "skipped": 0},
        "odometer_records": {"success": 0, "errors": 0, "skipped": 0},
        "hours_records": {"success": 0, "errors": 0, "skipped": 0},
        "reminders": {"success": 0, "errors": 0, "skipped": 0},
        "notes": {"success": 0, "errors": 0, "skipped": 0},
        "insurance_policies": {"success": 0, "errors": 0, "skipped": 0},
        "financing_records": {"success": 0, "errors": 0, "skipped": 0},
        "tax_records": {"success": 0, "errors": 0, "skipped": 0},
        "toll_tags": {"success": 0, "errors": 0, "skipped": 0},
        "toll_transactions": {"success": 0, "errors": 0, "skipped": 0},
        "warranties": {"success": 0, "errors": 0, "skipped": 0},
        "spot_rentals": {"success": 0, "errors": 0, "skipped": 0},
        "errors": errors,
        "warnings": warnings,
    }

    # Import service records (creates ServiceVisit + ServiceLineItem + Vendor)
    for idx, record_data in enumerate(sections["service_records"]):
        try:
            date = _json_row_date(record_data)

            # Legacy v2 used "mileage" (miles); v3 uses "odometer_km" (km).
            imported_odometer_km = _maybe_mi_to_km(
                _first_present(record_data, "odometer_km", "mileage")
            )
            cost = _json_decimal(record_data, "cost")
            _within_api_bounds(ServiceVisitCreate, odometer_km=imported_odometer_km)
            _within_api_bounds(ServiceLineItemCreate, cost=cost)

            # T-18: a v<=8 entry carries the first item's description and the
            # visit total, which sums the items, tax and fees; so the total
            # stands in for them. v8 wrote no claim number.
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    ServiceVisit,
                    ServiceVisit.vin == vin,
                    ServiceVisit.date == date,
                    _odometer_matches(
                        ServiceVisit,
                        imported_odometer_km,
                        converted=is_legacy_v2,
                        last_id_before_import=matcher.last_id(ServiceVisit),
                    ),
                    *(
                        [_money_matches(ServiceVisit.total_cost, cost)]
                        if "cost" in record_data
                        else []
                    ),
                    options=_VISIT_MATCH_LOADS,
                    same=lambda visit: _same_visit(
                        visit,
                        vendor_name=record_data.get("vendor_name"),
                        check_vendor="vendor_name" in record_data,
                        items=None,
                    ),
                )
                is not None
            ):
                results["service_records"]["skipped"] += 1
                continue

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
                errors.append(
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
                visit = ServiceVisit(
                    vin=vin,
                    date=date,
                    odometer_km=imported_odometer_km,
                    service_category=category,
                    vendor_id=await _vendor_id_for(db, record_data.get("vendor_name")),
                    notes=record_data.get("notes"),
                    total_cost=cost if cost is not None else Decimal("0"),
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
            readings.add(
                "service_visit",
                visit.id,
                visit.date,
                odometer_km=visit.odometer_km,
                engine_hours=visit.engine_hours,
            )
            results["service_records"]["success"] += 1
        except _RowError as e:
            results["service_records"]["errors"] += 1
            errors.append(f"Service record {idx}: {e.reason}")
        except Exception as e:
            results["service_records"]["errors"] += 1
            logger.warning("Import: service record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Service record {idx}: could not be imported")

    # Import v9 service visits whole: the visit, its line items in order and
    # the inspection links between them. Counted with the v<=8 entries (T-4).
    for idx, visit_data in enumerate(sections["service_visits"]):
        try:
            date = _json_row_date(visit_data)
            odometer_km = _maybe_mi_to_km(visit_data.get("odometer_km"))
            engine_hours = _json_decimal(visit_data, "engine_hours")
            tax_amount = _json_decimal(visit_data, "tax_amount")
            shop_supplies = _json_decimal(visit_data, "shop_supplies")
            misc_fees = _json_decimal(visit_data, "misc_fees")
            _within_api_bounds(
                ServiceVisitCreate,
                odometer_km=odometer_km,
                engine_hours=engine_hours,
                tax_amount=tax_amount,
                shop_supplies=shop_supplies,
                misc_fees=misc_fees,
            )
            # The API allows a visit with no category, so None stays None.
            service_category = _in_vocabulary(
                _blank_to_none(visit_data.get("service_category")),
                "service_category",
                _SERVICE_CATEGORIES,
            )
            raw_items = visit_data.get("line_items")
            if not isinstance(raw_items, list):
                raise _RowError("line_items must be a list")
            line_items = cast(list[Any], raw_items)
            items = [
                _line_item_from_json(position, item, len(line_items))
                for position, item in enumerate(line_items)
            ]
            total_cost = _visit_total(
                (columns["cost"] for columns, _link in items), tax_amount, shop_supplies, misc_fees
            )
            vendor_name = _json_text(visit_data, "vendor_name")
            insurance_claim_number = _json_text(visit_data, "insurance_claim_number")
            notes = _json_text(visit_data, "notes")

            # R5's service key. The visit's own amounts and claim number are in
            # it, so two visits that differ only there can't both match one
            # stored visit (Codex R2); each only when the entry has it (T-16).
            fee_key = [
                condition
                for key, condition in (
                    ("tax_amount", _money_matches(ServiceVisit.tax_amount, tax_amount)),
                    ("shop_supplies", _money_matches(ServiceVisit.shop_supplies, shop_supplies)),
                    ("misc_fees", _money_matches(ServiceVisit.misc_fees, misc_fees)),
                    (
                        "insurance_claim_number",
                        _matches(ServiceVisit.insurance_claim_number, insurance_claim_number),
                    ),
                )
                if key in visit_data  # T-16: a v9 export writes all four
            ]
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    ServiceVisit,
                    ServiceVisit.vin == vin,
                    ServiceVisit.date == date,
                    _odometer_matches(
                        ServiceVisit,
                        odometer_km,
                        converted=is_legacy_v2,
                        last_id_before_import=matcher.last_id(ServiceVisit),
                    ),
                    *fee_key,
                    options=_VISIT_MATCH_LOADS,
                    same=lambda visit: _same_visit(
                        visit,
                        vendor_name=vendor_name,
                        check_vendor=True,
                        items=_item_counts(
                            (columns["description"], columns["cost"]) for columns, _link in items
                        ),
                    ),
                )
                is not None
            ):
                results["service_records"]["skipped"] += 1
                continue

            # One savepoint for the visit, its items and their links, so a row
            # the database rejects rolls back whole and alone.
            async with db.begin_nested():
                visit = ServiceVisit(
                    vin=vin,
                    date=date,
                    odometer_km=odometer_km,
                    engine_hours=engine_hours,
                    service_category=service_category,
                    vendor_id=await _vendor_id_for(db, vendor_name),
                    tax_amount=tax_amount,
                    shop_supplies=shop_supplies,
                    misc_fees=misc_fees,
                    insurance_claim_number=insurance_claim_number,
                    notes=notes,
                    total_cost=total_cost,
                )
                db.add(visit)
                await db.flush()
                written = [
                    ServiceLineItem(visit_id=visit.id, **columns) for columns, _link in items
                ]
                db.add_all(written)
                await db.flush()
                # An item's link is an index into this visit's items, so it's
                # set once every item has its id.
                for line_item, (_columns, link) in zip(written, items, strict=True):
                    if link is not None:
                        line_item.triggered_by_inspection_id = written[link].id
                await db.flush()
            readings.add(
                "service_visit",
                visit.id,
                visit.date,
                odometer_km=visit.odometer_km,
                engine_hours=visit.engine_hours,
            )
            results["service_records"]["success"] += 1
        except _RowError as e:
            results["service_records"]["errors"] += 1
            errors.append(f"Service visit {idx}: {e.reason}")
        except Exception as e:
            results["service_records"]["errors"] += 1
            logger.warning("Import: service visit %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Service visit {idx}: could not be imported")

    # Import fuel records. Every column the export writes is read back (R2); a
    # v<=8 row lacks the newer keys, which read as None or the model default.
    for idx, record_data in enumerate(sections["fuel_records"]):
        try:
            date = _json_row_date(record_data)
            # v3 uses "odometer_km"/"liters"; legacy v2 uses "mileage"/"gallons"
            # in imperial, converted by the helpers above. A 0 is a figure.
            record = _fuel_record_from_json(
                vin,
                date,
                record_data,
                idx=idx,
                odometer_km=_maybe_mi_to_km(_first_present(record_data, "odometer_km", "mileage")),
                liters=_maybe_gal_to_l(_first_present(record_data, "liters", "gallons")),
                price_per_unit=_maybe_per_gal_to_per_l(record_data.get("price_per_unit")),
            )
            # The links are checked against this instance after the duplicate
            # check; the station's name is the resolved one a v9 export writes.
            station_id = _json_int(record_data, "station_address_book_id")
            station_name = _json_text(record_data, "station_name") or _json_text(
                record_data, "station_name_freetext"
            )
            driver_id = _json_int(record_data, "driver_user_id")
            driver_username = _json_text(record_data, "driver_username")
            driver_freetext = _json_text(record_data, "driver_name_freetext")

            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    FuelRecord,
                    FuelRecord.vin == vin,
                    *_json_fuel_key(
                        record_data,
                        record,
                        converted=is_legacy_v2,
                        last_id=matcher.last_id(FuelRecord),
                        zero_was_null=zero_was_null,
                    ),
                )
                is not None
            ):
                results["fuel_records"]["skipped"] += 1
                continue

            (
                record.station_address_book_id,
                record.station_name_freetext,
                station_dropped,
            ) = await _portable_station(db, station_id, station_name)
            (
                record.driver_user_id,
                record.driver_name_freetext,
                driver_dropped,
            ) = await _portable_driver(db, driver_id, driver_username, driver_freetext)
            # A savepoint per row, flushed inside it so the end-of-import sync
            # has the record's id, and a row the database rejects rolls back
            # alone instead of failing the whole upload at the final commit.
            async with db.begin_nested():
                db.add(record)
                await db.flush()
            readings.add(
                "fuel",
                record.id,
                record.date,
                odometer_km=record.odometer_km,
                engine_hours=record.engine_hours,
            )
            results["fuel_records"]["success"] += 1
            if station_dropped:
                warnings.append(f"Fuel record {idx}: {_STATION_KEPT_AS_TEXT}")
            if driver_dropped:
                warnings.append(f"Fuel record {idx}: {_DRIVER_KEPT_AS_TEXT}")
        except _RowError as e:
            results["fuel_records"]["errors"] += 1
            errors.append(f"Fuel record {idx}: {e.reason}")
        except Exception as e:
            results["fuel_records"]["errors"] += 1
            logger.warning("Import: fuel record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Fuel record {idx}: could not be imported")

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
            date = _json_row_date(record_data)
            # v3 uses "odometer_km"/"liters"; legacy v2 uses "mileage"/"gallons".
            # A 0 is a figure (G3a-75).
            record = _def_record_from_json(
                vin,
                date,
                record_data,
                odometer_km=_maybe_mi_to_km(_first_present(record_data, "odometer_km", "mileage")),
                liters=_maybe_gal_to_l(_first_present(record_data, "liters", "gallons")),
                price_per_unit=_maybe_per_gal_to_per_l(record_data.get("price_per_unit")),
            )

            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    DEFRecord,
                    DEFRecord.vin == vin,
                    *_json_def_key(
                        record_data,
                        record,
                        converted=is_legacy_v2,
                        last_id=matcher.last_id(DEFRecord),
                        zero_was_null=zero_was_null,
                    ),
                )
                is not None
            ):
                results["def_records"]["skipped"] += 1
                continue

            # A savepoint per row, flushed inside it so the end-of-import sync
            # has the record's id, and a row the database rejects rolls back
            # alone instead of failing the whole upload at the final commit.
            async with db.begin_nested():
                db.add(record)
                await db.flush()
            readings.add("def", record.id, record.date, odometer_km=record.odometer_km)
            results["def_records"]["success"] += 1
        except _RowError as e:
            results["def_records"]["errors"] += 1
            errors.append(f"DEF record {idx}: {e.reason}")
        except Exception as e:
            results["def_records"]["errors"] += 1
            logger.warning("Import: DEF record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"DEF record {idx}: could not be imported")

    # Import odometer records
    for idx, record_data in enumerate(sections["odometer_records"]):
        try:
            date = _json_row_date(record_data)

            # v2 used "reading" (miles), v3 uses "odometer_km".
            imported_odometer_km = _maybe_mi_to_km(
                _first_present(record_data, "odometer_km", "reading")
            )
            # The column is NOT NULL: refused here, not by the database (T-6).
            if imported_odometer_km is None:
                raise _RowError("odometer_km is missing")
            _within_api_bounds(OdometerRecordCreate, odometer_km=imported_odometer_km)

            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    OdometerRecord,
                    OdometerRecord.vin == vin,
                    OdometerRecord.date == date,
                    _odometer_matches(
                        OdometerRecord,
                        imported_odometer_km,
                        converted=is_legacy_v2,
                        last_id_before_import=matcher.last_id(OdometerRecord),
                    ),
                )
                is not None
            ):
                results["odometer_records"]["skipped"] += 1
                continue

            # No copied sync marker and a portable source (R4, N-2): a v8 file
            # has no source, so its rows read as manual.
            record = OdometerRecord(
                vin=vin,
                date=date,
                odometer_km=imported_odometer_km,
                notes=_without_sync_marker(record_data.get("notes")),
                source=_portable_odometer_source(record_data.get("source")),
            )
            # A savepoint per row. Leaving it flushes the insert, so a row the
            # database rejects rolls back alone instead of failing the whole
            # upload at the final commit (production sessions do not autoflush).
            async with db.begin_nested():
                db.add(record)
            results["odometer_records"]["success"] += 1
        except _RowError as e:
            results["odometer_records"]["errors"] += 1
            errors.append(f"Odometer record {idx}: {e.reason}")
        except Exception as e:
            results["odometer_records"]["errors"] += 1
            logger.warning("Import: odometer record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Odometer record {idx}: could not be imported")

    # Import engine-hours readings. Always manual rows with no FKs, like the
    # CSV importer: a file can't carry a live link to this vehicle's fuel or
    # service rows. Dimensionless, so no legacy-v2 conversion.
    for idx, record_data in enumerate(sections["hours_records"]):
        try:
            date = _json_row_date(record_data)
            raw_hours = record_data.get("engine_hours")
            if raw_hours is None or raw_hours == "":
                results["hours_records"]["errors"] += 1
                errors.append(f"Hours record {idx}: engine hours are required")
                continue
            engine_hours = Decimal(str(raw_hours))
            _within_api_bounds(HoursRecordCreate, engine_hours=engine_hours)

            # NUMERIC(10,1); no source in the key (T-19).
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    HoursRecord,
                    HoursRecord.vin == vin,
                    HoursRecord.date == date,
                    _same_figure(HoursRecord.engine_hours, engine_hours, Decimal("0.1")),
                )
                is not None
            ):
                results["hours_records"]["skipped"] += 1
                continue

            record = HoursRecord(
                vin=vin,
                date=date,
                engine_hours=engine_hours,
                notes=_without_sync_marker(record_data.get("notes")),
                source="manual",
            )
            async with db.begin_nested():
                db.add(record)
            results["hours_records"]["success"] += 1
        except _RowError as e:
            results["hours_records"]["errors"] += 1
            errors.append(f"Hours record {idx}: {e.reason}")
        except Exception as e:
            results["hours_records"]["errors"] += 1
            logger.warning("Import: hours record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Hours record {idx}: could not be imported")

    # Before the reminders, which count from the current reading (T-2).
    await readings.apply(db, vin, claim=False)

    # Read once, here: the odometer and hours sections have flushed by now
    # (each row leaves a savepoint), and no reminder row writes a reading.
    start_km, start_hours = await start_readings(db, vin)

    def _exported_due_point(
        reminder_data: dict[str, Any],
    ) -> tuple[date_type | None, Decimal | None]:
        """The due date and odometer the row was exported with, mileage in km."""
        due_date = (
            None
            if _is_blank(reminder_data.get("due_date"))
            else _json_row_date(reminder_data, "due_date")
        )
        due_km = _maybe_mi_to_km(reminder_data.get("due_mileage"))
        # v2 saved 0 for no mileage.
        if due_km == 0:
            due_km = None
        # Rounded first so the message shows the figure we'd store. Infinity
        # can't round; the bounds check refuses it next.
        if due_km is not None and due_km.is_finite():
            due_km = due_km.quantize(Decimal("0.01"))
        _within_api_bounds(ReminderCreate, due_mileage_km=due_km)
        return due_date, due_km

    # Import reminders → map to vehicle_reminders
    for idx, reminder_data in enumerate(sections["reminders"]):
        try:
            is_completed = bool(reminder_data.get("is_completed"))
            completed_at: datetime | None = None
            if is_completed:
                # Comes back as done, due where it was. Not logged as a
                # service visit: the same import may already carry that work.
                completed_at = _json_row_datetime(reminder_data, "completed_at")
                due_date, due_km = _exported_due_point(reminder_data)
            else:
                is_recurring = reminder_data.get("is_recurring", False)
                recurrence_days = reminder_data.get("recurrence_days", 0)
                recurrence_miles = reminder_data.get("recurrence_miles")

                has_date = bool(is_recurring and recurrence_days)
                has_miles = bool(is_recurring and recurrence_miles)

                # A negative interval would import already overdue; the bounds check stops it.
                # It also runs first so a quiet NaN gets its message instead of raising in
                # the <= 0 below.
                if has_miles:
                    _within_api_bounds(
                        ReminderCreate, due_mileage_km=Decimal(str(recurrence_miles))
                    )
                if has_miles and Decimal(str(recurrence_miles)) <= 0:
                    results["reminders"]["errors"] += 1
                    errors.append(f"Reminder {idx}: recurrence_miles must be positive")
                    continue

                if not is_recurring:
                    # A one-time reminder keeps the due point it was exported with.
                    due_date, due_km = _exported_due_point(reminder_data)
                else:
                    due_date = None
                    due_km = None
                    interval_km = _maybe_mi_to_km(recurrence_miles) if has_miles else None
                    if interval_km is not None:
                        # The interval counts from the odometer after the import.
                        # With no reading, a date side carries the row on its own
                        # and the miles half drops; a miles-only row can't import.
                        if start_km is not None:
                            due_km = (start_km + interval_km).quantize(Decimal("0.01"))
                            _within_api_bounds(ReminderCreate, due_mileage_km=due_km)
                        elif not has_date:
                            raise _RowError("no odometer reading to count from")

                    # Calculate due_date from recurrence_days
                    if has_date and recurrence_days:
                        # A date object, in the household zone. The previous code
                        # assigned .isoformat() -- a str the Date column rejects at
                        # flush -- so every recurring-days row errored out of the
                        # import; the per-row savepoint made it look like bad data.
                        due_date = household_today() + timedelta(days=recurrence_days)

                # A pending reminder with nothing to come due on would never fire.
                if due_date is None and due_km is None:
                    raise _RowError("no due date or mileage to import")

            if due_date is not None and due_km is not None:
                reminder_type = "both"
            elif due_km is not None:
                reminder_type = "mileage"
            else:
                reminder_type = "date"

            reminder = Reminder(
                vin=vin,
                title=reminder_data["description"],
                reminder_type=reminder_type,
                due_date=due_date,
                due_mileage_km=due_km,
                start_odometer_km=start_km,
                start_hours=start_hours,
                status="done" if is_completed else "pending",
                completed_at=completed_at,
                completed_date=household_date(completed_at) if completed_at is not None else None,
                notes=reminder_data.get("notes"),
                maintenance_type=classify(reminder_data["description"]),
            )
            # A savepoint per row. A row the database still rejects rolls
            # back alone here, instead of poisoning the session for every
            # row and loop still to come.
            async with db.begin_nested():
                db.add(reminder)
            results["reminders"]["success"] += 1
        except _RowError as e:
            results["reminders"]["errors"] += 1
            errors.append(f"Reminder {idx}: {e.reason}")
        except Exception as e:
            results["reminders"]["errors"] += 1
            logger.warning("Import: reminder %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Reminder {idx}: could not be imported")

    # Import notes
    for idx, note_data in enumerate(sections["notes"]):
        try:
            date = _json_row_date(note_data)

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
        except _RowError as e:
            results["notes"]["errors"] += 1
            errors.append(f"Note {idx}: {e.reason}")
        except Exception as e:
            results["notes"]["errors"] += 1
            logger.warning("Import: note %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Note {idx}: could not be imported")

    # Import insurance: each entry is THIS vehicle's place on a household policy.
    insurance_access = await InsuranceService(db).access_for(current_user)
    for idx, entry in enumerate(sections["insurance_policies"]):
        try:
            premium = entry.get("premium_share")
            deductible = entry.get("deductible")
            record = {
                "provider": entry["provider"],
                "policy_number": entry["policy_number"],
                "policy_type": entry.get("policy_type"),
                "start_date": datetime.fromisoformat(entry["start_date"]).date(),
                "end_date": datetime.fromisoformat(entry["end_date"]).date(),
                "premium": Decimal(str(premium)) if premium is not None else None,
                "premium_frequency": entry.get("premium_frequency"),
                "deductible": Decimal(str(deductible)) if deductible is not None else None,
                "coverages": _coverages_from_rows(entry.get("coverages") or []),
                "notes": entry.get("notes"),
                "fields": entry.get("fields") or [],
                "policy_fields": entry.get("policy_fields") or [],
                "policy_notes": entry.get("policy_notes"),
                "effective_to": (
                    datetime.fromisoformat(entry["effective_to"]).date()
                    if entry.get("effective_to")
                    else None
                ),
            }
            # Schema 7 and older carried one coverage text box instead. It is
            # converted whole, so a restored old backup lands what an in-place
            # upgrade would have: the rows, the named fields AND the prose.
            if entry.get("coverages") is None:
                _merge_converted(record, entry.get("coverage_limits"))
            imported = await _import_insurance_row(
                db,
                insurance_access,
                vin,
                record,
                skip_duplicates=True,
            )
            results["insurance_policies"]["success" if imported else "skipped"] += 1
        except (_InsuranceRowError, _ImportBoundError) as e:
            results["insurance_policies"]["errors"] += 1
            errors.append(f"Insurance policy {idx}: {e.reason}")
        except Exception as e:
            results["insurance_policies"]["errors"] += 1
            logger.warning("Import: insurance policy %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Insurance policy {idx}: could not be imported")

    # Import financing. The lender travels by name and is looked up or made in
    # the row's savepoint, as a service visit's vendor is (R6).
    for idx, row in enumerate(sections["financing_records"]):
        try:
            record = _financing_record_from_json(vin, row)
            lender = _json_text(row, "vendor_name", max_length=100)
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    FinancingRecord,
                    FinancingRecord.vin == vin,
                    *_json_financing_key(record),
                    options=(selectinload(FinancingRecord.vendor),),
                    same=(
                        (lambda f: (f.vendor.name if f.vendor else None) == lender)
                        if "vendor_name" in row
                        else None
                    ),
                )
                is not None
            ):
                results["financing_records"]["skipped"] += 1
                continue

            async with db.begin_nested():
                record.vendor_id = await _vendor_id_for(db, lender)
                db.add(record)
            results["financing_records"]["success"] += 1
        except _RowError as e:
            results["financing_records"]["errors"] += 1
            errors.append(f"Financing record {idx}: {e.reason}")
        except Exception as e:
            results["financing_records"]["errors"] += 1
            logger.warning("Import: financing record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Financing record {idx}: could not be imported")

    # Import tax records
    for idx, row in enumerate(sections["tax_records"]):
        try:
            record = _tax_record_from_json(vin, row)
            if (
                skip_duplicates
                and await matcher.take(
                    db, TaxRecord, TaxRecord.vin == vin, *_json_tax_key(row, record)
                )
                is not None
            ):
                results["tax_records"]["skipped"] += 1
                continue

            async with db.begin_nested():
                db.add(record)
            results["tax_records"]["success"] += 1
        except _RowError as e:
            results["tax_records"]["errors"] += 1
            errors.append(f"Tax record {idx}: {e.reason}")
        except Exception as e:
            results["tax_records"]["errors"] += 1
            logger.warning("Import: tax record %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Tax record {idx}: could not be imported")

    # Import toll tags. A transaction names its tag by the tag's index in this
    # file (R6), so each tag written or matched is kept by that index, with
    # its key; a tag that failed has neither, and its transactions are stored,
    # and keyed, untagged (Fable F-3).
    tag_ids: dict[int, int] = {}
    tag_keys: dict[int, tuple[str, str]] = {}
    for idx, row in enumerate(sections["toll_tags"]):
        try:
            tag = _toll_tag_from_json(vin, row)
            stored = (
                await matcher.take(
                    db,
                    TollTag,
                    TollTag.vin == vin,
                    TollTag.toll_system == tag.toll_system,
                    TollTag.tag_number == tag.tag_number,
                )
                if skip_duplicates
                else None
            )
            if stored is not None:
                tag_ids[idx] = stored.id
                tag_keys[idx] = (stored.toll_system, stored.tag_number)
                results["toll_tags"]["skipped"] += 1
                continue

            async with db.begin_nested():
                db.add(tag)
                await db.flush()
            tag_ids[idx] = tag.id
            tag_keys[idx] = (tag.toll_system, tag.tag_number)
            results["toll_tags"]["success"] += 1
        except _RowError as e:
            results["toll_tags"]["errors"] += 1
            errors.append(f"Toll tag {idx}: {e.reason}")
        except Exception as e:
            results["toll_tags"]["errors"] += 1
            logger.warning("Import: toll tag %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Toll tag {idx}: could not be imported")

    # Import toll transactions. Two same-day charges at one plaza are two rows,
    # and a re-import matches each to one stored charge (R1-H1).
    for idx, row in enumerate(sections["toll_transactions"]):
        try:
            record, tag_index = _toll_transaction_from_json(vin, row, len(sections["toll_tags"]))
            tag_key = tag_keys.get(tag_index) if tag_index is not None else None
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    TollTransaction,
                    TollTransaction.vin == vin,
                    *_json_toll_transaction_key(record),
                    options=(selectinload(TollTransaction.toll_tag),),
                    same=(
                        (lambda t: _toll_tag_key(t.toll_tag) == tag_key)
                        if "toll_tag_index" in row
                        else None
                    ),
                )
                is not None
            ):
                results["toll_transactions"]["skipped"] += 1
                continue

            record.toll_tag_id = tag_ids.get(tag_index) if tag_index is not None else None
            async with db.begin_nested():
                db.add(record)
            results["toll_transactions"]["success"] += 1
            if tag_index is not None and record.toll_tag_id is None:
                warnings.append(
                    f"Toll transaction {idx}: its toll tag was not imported, saved without one"
                )
        except _RowError as e:
            results["toll_transactions"]["errors"] += 1
            errors.append(f"Toll transaction {idx}: {e.reason}")
        except Exception as e:
            results["toll_transactions"]["errors"] += 1
            logger.warning("Import: toll transaction %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Toll transaction {idx}: could not be imported")

    # Import warranties
    for idx, row in enumerate(sections["warranties"]):
        try:
            record = _warranty_from_json(vin, row)
            if (
                skip_duplicates
                and await matcher.take(
                    db, WarrantyRecord, WarrantyRecord.vin == vin, *_json_warranty_key(row, record)
                )
                is not None
            ):
                results["warranties"]["skipped"] += 1
                continue

            async with db.begin_nested():
                db.add(record)
            results["warranties"]["success"] += 1
        except _RowError as e:
            results["warranties"]["errors"] += 1
            errors.append(f"Warranty {idx}: {e.reason}")
        except Exception as e:
            results["warranties"]["errors"] += 1
            logger.warning("Import: warranty %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Warranty {idx}: could not be imported")

    # Import spot rentals with their bills. A rental skipped as a duplicate
    # skips its bills; one written writes them in its savepoint.
    for idx, row in enumerate(sections["spot_rentals"]):
        try:
            rental, bills = _spot_rental_from_json(vin, row)
            bill_counts = _bill_counts((bill.billing_date, bill.total) for bill in bills)
            if (
                skip_duplicates
                and await matcher.take(
                    db,
                    SpotRental,
                    SpotRental.vin == vin,
                    *_json_spot_rental_key(row, rental),
                    options=(selectinload(SpotRental.billings),),
                    same=lambda r: (
                        _bill_counts((b.billing_date, b.total) for b in r.billings) == bill_counts
                    ),
                )
                is not None
            ):
                results["spot_rentals"]["skipped"] += 1
                continue

            async with db.begin_nested():
                db.add(rental)
                await db.flush()
                for bill in bills:
                    bill.spot_rental_id = rental.id
                db.add_all(bills)
                await db.flush()
            results["spot_rentals"]["success"] += 1
        except _RowError as e:
            results["spot_rentals"]["errors"] += 1
            errors.append(f"Spot rental {idx}: {e.reason}")
        except Exception as e:
            results["spot_rentals"]["errors"] += 1
            logger.warning("Import: spot rental %s failed: %s", idx, sanitize_for_log(e))
            errors.append(f"Spot rental {idx}: could not be imported")

    await db.commit()
    # Imported services may be the newest of a rule's type: reconcile once.
    await maintenance_service.reconcile_vehicle(db, vin)
    await invalidate_cache_for_vehicle(vin)

    metric_keys = (
        "service_records",
        "fuel_records",
        "def_records",
        "odometer_records",
        "hours_records",
        "reminders",
        "notes",
        "insurance_policies",
        "financing_records",
        "tax_records",
        "toll_tags",
        "toll_transactions",
        "warranties",
        "spot_rentals",
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
    # Odometer sync matches on (vin, date) and overwrites, so syncing every row
    # would let CSV order decide the stored value and reassign the cascade FK.
    # Sync once per date with the highest reading, which is the only choice
    # that survives reordering the file.
    readings = _ImportReadings()
    # Callers take the vehicle write lock first; see `_converted_value_matches`.
    last_id = await _last_id_before_import(db, FuelRecord)
    for row_num, row in enumerate(parsed, start=2):
        try:
            date = row.get("date")
            if not date:
                import_result.add_error(row_num, "Date is required")
                continue
            odometer_km = row.get("odometer_km")
            _within_api_bounds(
                FuelRecordCreate,
                odometer_km=odometer_km,
                liters=row.get("liters"),
                kwh=row.get("kwh"),
                cost=row.get("cost"),
                price_per_unit=row.get("price_per_unit"),
                soc_start_pct=row.get("soc_start_pct"),
                soc_end_pct=row.get("soc_end_pct"),
                battery_soh_pct=row.get("battery_soh_pct"),
            )
            price_basis = _in_vocabulary(row.get("price_basis"), "price_basis", PRICE_BASIS_VALUES)
            charge_level = _in_vocabulary(
                row.get("charge_level"), "charge_level", CHARGE_LEVEL_VALUES
            )
            charge_location = _in_vocabulary(
                row.get("charge_location"), "charge_location", CHARGE_LOCATION_VALUES
            )
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
                price_basis=price_basis,
                is_full_tank=bool(row.get("is_full_tank", True)),
                notes=row.get("notes"),
                # v4-and-older backups carry the retired free-text "fuel_type"
                # instead, so fall back to it through the normalizer rather
                # than restoring those records with no fuel type at all.
                fuel_type_used=row.get("fuel_type_used")
                or _normalized_fuel_type(row.get("fuel_type")),
                soc_start_pct=row.get("soc_start_pct"),
                soc_end_pct=row.get("soc_end_pct"),
                charge_level=charge_level,
                charge_location=charge_location,
                battery_soh_pct=row.get("battery_soh_pct"),
            )
            # Savepoint per row: the flush below populates record.id, and a bare
            # flush failure would poison the session for every remaining row.
            async with db.begin_nested():
                db.add(record)
                await db.flush()
            readings.add("fuel", record.id, record.date, odometer_km=record.odometer_km)
            import_result.add_success()
        except _RowError as e:
            import_result.add_error(row_num, e.reason)
        except Exception as e:
            logger.error("External fuel import row %d failed: %s", row_num, e)
            import_result.add_error(row_num, "Invalid fuel record data")

    # The create path's claiming sync: a third-party export is no backup, so a
    # same-day automatic or LiveLink row is taken over as before (T-15, T-17).
    await readings.apply(db, vin, claim=True)

    await db.commit()
    await invalidate_cache_for_vehicle(vin)
    return import_result.to_dict()
