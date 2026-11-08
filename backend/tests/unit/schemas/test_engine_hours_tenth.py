"""Every engine-hours write rounds to the tenth its column keeps.

The columns are NUMERIC(10, 1) and `ScaledNumeric` rounds on the way in, so an
unrounded 812.45 was checked as 812.45 and saved as 812.5. Tires and brakes
already round as they parse; these are the rest of the hours writes.

Guard: the bounds still refuse what they refused before (no new 422s), and a
value just past a bound is refused, not rounded back inside it.
Mutant killed: drop the AfterValidator from any one field below.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import Column, inspect

from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.reminder import Reminder
from app.models.service_visit import ServiceVisit
from app.schemas.fuel import FuelRecordCreate, FuelRecordUpdate
from app.schemas.hours import HoursRecordCreate, HoursRecordUpdate
from app.schemas.maintenance import ReminderCompleteRequest
from app.schemas.service_visit import ServiceVisitCreate, ServiceVisitUpdate

VIN = "1HGBH41JXMN109186"
DAY = date(2026, 5, 5)


def _column(model: type[Any], name: str) -> Column[Any]:
    return inspect(model).columns[name]


#: (schema, the other fields a valid payload needs, the column the hours land in,
#: the field's own `le`). The completion's hours land on its visit and on the
#: reminder's completed_hours; both are NUMERIC(10, 1).
CASES: list[tuple[type[BaseModel], dict[str, Any], Column[Any], Decimal]] = [
    (
        HoursRecordCreate,
        {"vin": VIN, "date": DAY},
        _column(HoursRecord, "engine_hours"),
        Decimal("999999999.9"),
    ),
    (HoursRecordUpdate, {}, _column(HoursRecord, "engine_hours"), Decimal("999999999.9")),
    (
        FuelRecordCreate,
        {"vin": VIN, "date": DAY, "odometer_km": "100", "liters": "40.0"},
        _column(FuelRecord, "engine_hours"),
        Decimal("9999999.9"),
    ),
    (FuelRecordUpdate, {}, _column(FuelRecord, "engine_hours"), Decimal("9999999.9")),
    (
        ServiceVisitCreate,
        {"date": DAY, "line_items": [{"description": "Oil change"}]},
        _column(ServiceVisit, "engine_hours"),
        Decimal("9999999.9"),
    ),
    (ServiceVisitUpdate, {}, _column(ServiceVisit, "engine_hours"), Decimal("9999999.9")),
    (
        ReminderCompleteRequest,
        {"completed_date": DAY},
        _column(Reminder, "completed_hours"),
        Decimal("9999999.9"),
    ),
]
IDS = [schema.__name__ for schema, *_ in CASES]


def _hours(schema: type[BaseModel], others: dict[str, Any], value: object) -> Any:
    return getattr(schema.model_validate({**others, "engine_hours": value}), "engine_hours")


@pytest.mark.parametrize(("schema", "others", "column", "le"), CASES, ids=IDS)
@pytest.mark.parametrize(
    ("given", "reads"),
    [
        ("812.45", Decimal("812.5")),
        (0.1 + 0.2, Decimal("0.3")),
        ("812.40", Decimal("812.4")),
    ],
)
def test_engine_hours_read_as_the_stored_tenth(
    schema: type[BaseModel],
    others: dict[str, Any],
    column: Column[Any],
    le: Decimal,
    given: object,
    reads: Decimal,
) -> None:
    hours = _hours(schema, others, given)
    assert hours == reads
    # The exponent too: 812.40 == 812.4 already, so equality alone can't see it.
    assert hours.as_tuple().exponent == -column.type.scale


@pytest.mark.parametrize(("schema", "others", "column", "le"), CASES, ids=IDS)
def test_the_column_keeps_a_tenth(
    schema: type[BaseModel], others: dict[str, Any], column: Column[Any], le: Decimal
) -> None:
    # Rounding to 0.1 is only right while the column keeps exactly one place.
    assert column.type.scale == 1


@pytest.mark.parametrize(("schema", "others", "column", "le"), CASES, ids=IDS)
def test_the_bounds_still_refuse(
    schema: type[BaseModel], others: dict[str, Any], column: Column[Any], le: Decimal
) -> None:
    assert _hours(schema, others, str(le)) == le
    # -0.04 and le + 0.04 would round back inside the bounds; they're checked first.
    for refused in ("-0.1", "-0.04", str(le + Decimal("0.1")), str(le + Decimal("0.04"))):
        with pytest.raises(ValidationError, match="engine_hours"):
            _hours(schema, others, refused)


@pytest.mark.parametrize(("schema", "others", "column", "le"), CASES, ids=IDS)
def test_a_null_never_reaches_the_rounding(
    schema: type[BaseModel], others: dict[str, Any], column: Column[Any], le: Decimal
) -> None:
    # A nullable field keeps its null; the hours log's NOT NULL fields 422 it.
    if column.nullable:
        assert _hours(schema, others, None) is None
    else:
        with pytest.raises(ValidationError, match="engine_hours"):
            _hours(schema, others, None)
