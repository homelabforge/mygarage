"""What every importer shares: the router, the limiter, the row errors and the cell readers."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import csv
import io
import operator
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from datetime import date as date_type
from decimal import Decimal, InvalidOperation
from typing import Any, get_args

from fastapi import APIRouter
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.schemas.financing import FinancingCategory
from app.schemas.service_visit import (
    InspectionResult,
    InspectionSeverity,
    ServiceCategory,
)
from app.schemas.tax import TaxType
from app.utils.csv_safe import unquote_csv_cell
from app.utils.csv_units import (
    CsvUnitContext,
    QuantitySpec,
    build_csv_unit_context,
)

router = APIRouter(prefix="/api/import", tags=["import"])


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


def _json_row_datetime(record_data: Mapping[str, Any], key: str) -> datetime | None:
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
        if value is not None:
            _check_bounds(name, value, metadata)


def _check_bounds(name: str, value: Decimal | int, metadata: Iterable[Any]) -> None:
    """Refuse `value` when it isn't a number or breaks a bound in `metadata`.

    `metadata` is a FieldInfo's, so a schema field and an Annotated figure
    read the same way and say the same thing.
    """
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    # Before the bounds: comparing a NaN raises InvalidOperation, not a row error.
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


#: What a row PostgreSQL refused for a value too long for its column says
#: (SQLite stores any length). No per-column bounds: SQLite writes are unbounded (NB-1).
_TOO_LONG = "a value is longer than its column allows"
#: PostgreSQL's string_data_right_truncation.
_STRING_TOO_LONG = "22001"


def _unexpected_reason(e: Exception, generic: str = "could not be imported") -> str:
    """What a row that failed unexpectedly says: too long for its column, or `generic`.

    Judged on the driver's SQLSTATE, not the wrapper class: asyncpg's 22001
    comes through as a plain DBAPIError, and a DataError can be a number too.
    asyncpg and psycopg set `sqlstate`, psycopg2 `pgcode`.
    """
    orig = getattr(e, "orig", None)
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return _TOO_LONG if code == _STRING_TOO_LONG else generic


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
    return _within_length(value, key, max_length)


def _within_length(value: str | None, key: str, max_length: int | None) -> str | None:
    """The text, or a row error past the Create schema's `max_length`."""
    if value is not None and max_length is not None and len(value) > max_length:
        raise _RowError(f"{key} must be at most {max_length} characters")
    return value


def _json_first_decimal(row: Mapping[str, Any], *keys: str) -> Decimal | None:
    """The number under the first of `keys` that holds one: a v3+ name before its v2 alias.

    `row.get("odometer_km") or row.get("mileage")` read a 0 as missing (G3a-75).
    Read as `_json_decimal` reads it, so a word names its field (F-4).
    """
    for key in keys:
        if not _is_blank(row.get(key)):
            return _json_decimal(row, key)
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


def _json_bool(row: Mapping[str, Any], key: str, *, default: bool) -> bool:
    """The flag under `key`, `default` when it's missing or null, a row error otherwise.

    Checked as a bool, not an int: bool subclasses int, so the other way round
    would let a 1 through. A backup writes true and false, nothing else.
    """
    raw = row.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    raise _RowError(f"{key} must be true or false")


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


def _read_mygarage_csv(csv_data: str) -> tuple[list[dict[str, Any]], Sequence[str] | None]:
    """A MyGarage CSV's rows, each text cell with the export's formula quote taken off once.

    Done here and nowhere else (P-2): a pair that skipped it stored the quote
    and grew another one every round trip, and a second unquote eats a typed one.
    """
    reader = csv.DictReader(io.StringIO(csv_data))
    rows = [
        {
            key: unquote_csv_cell(value) if isinstance(value, str) else value
            for key, value in row.items()
        }
        for row in reader
    ]
    return rows, reader.fieldnames


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
    rows, fieldnames = _read_mygarage_csv(csv_data)
    return rows, build_csv_unit_context(fieldnames, rows, specs)
