"""Every engine-hours write rounds to the tenth its column keeps.

The columns are NUMERIC(10, 1) and `ScaledNumeric` rounds on the way in, so an
unrounded 812.45 was checked as 812.45 and saved as 812.5. Tires and brakes
already round as they parse; these are the rest of the hours writes, plus the
anchor and interval a reminder's due hours are summed from.

Guard: the bounds still refuse what they refused before (no new 422s), and a
value just past a bound is refused, not rounded back inside it.
Mutant killed: drop the AfterValidator from any one field below.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Literal, NamedTuple

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import Column, inspect

from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder import Reminder
from app.models.service_visit import ServiceVisit
from app.schemas._figures import to_stored_tenth
from app.schemas.fuel import FuelRecordCreate, FuelRecordUpdate
from app.schemas.hours import HoursRecordCreate, HoursRecordUpdate
from app.schemas.maintenance import (
    AnchorSpec,
    IntervalOverride,
    MaintenanceRuleCreate,
    RecurrenceSpec,
    ReminderCompleteRequest,
)
from app.schemas.service_visit import ServiceVisitCreate, ServiceVisitUpdate
from app.schemas.vehicle import VehicleCreate, VehicleUpdate

VIN = "1HGBH41JXMN109186"
DAY = date(2026, 5, 5)


def _column(model: type[Any], name: str) -> Column[Any]:
    return inspect(model).columns[name]


class Case(NamedTuple):
    """One hours field and what a valid payload around it needs."""

    schema: type[BaseModel]
    field: str
    others: dict[str, Any]
    #: Where the figure lands, or what it's summed into.
    column: Column[Any]
    #: The field's own floor: `ge=0`, or `gt=0` for an interval.
    floor: Literal["ge", "gt"]
    #: The field's own `le`; None where it has none.
    le: Decimal | None
    #: Whether the schema takes a null (current_hours does, though its row can't).
    nullable: bool

    def read(self, value: object) -> Any:
        return getattr(self.schema.model_validate({**self.others, self.field: value}), self.field)


_HOURS = _column(HoursRecord, "engine_hours")
_INTERVAL = _column(MaintenanceRule, "interval_hours")
_LOG_MAX = Decimal("999999999.9")
_READING_MAX = Decimal("9999999.9")

# The completion's hours land on its visit and on the reminder's completed_hours.
# current_hours goes to the hours log (set_manual_current_hours). An anchor lands
# in anchor_hours and is summed with the interval into due_hours.
CASES = [
    Case(
        HoursRecordCreate, "engine_hours", {"vin": VIN, "date": DAY}, _HOURS, "ge", _LOG_MAX, False
    ),
    Case(HoursRecordUpdate, "engine_hours", {}, _HOURS, "ge", _LOG_MAX, False),
    Case(
        FuelRecordCreate,
        "engine_hours",
        {"vin": VIN, "date": DAY, "odometer_km": "100", "liters": "40.0"},
        _column(FuelRecord, "engine_hours"),
        "ge",
        _READING_MAX,
        True,
    ),
    Case(
        FuelRecordUpdate,
        "engine_hours",
        {},
        _column(FuelRecord, "engine_hours"),
        "ge",
        _READING_MAX,
        True,
    ),
    Case(
        ServiceVisitCreate,
        "engine_hours",
        {"date": DAY, "line_items": [{"description": "Oil change"}]},
        _column(ServiceVisit, "engine_hours"),
        "ge",
        _READING_MAX,
        True,
    ),
    Case(
        ServiceVisitUpdate,
        "engine_hours",
        {},
        _column(ServiceVisit, "engine_hours"),
        "ge",
        _READING_MAX,
        True,
    ),
    Case(
        ReminderCompleteRequest,
        "engine_hours",
        {"completed_date": DAY},
        _column(Reminder, "completed_hours"),
        "ge",
        _READING_MAX,
        True,
    ),
    Case(
        VehicleCreate,
        "current_hours",
        {"vin": VIN, "nickname": "Tractor", "vehicle_type": "Car"},
        _HOURS,
        "ge",
        None,
        True,
    ),
    Case(VehicleUpdate, "current_hours", {}, _HOURS, "ge", None, True),
    Case(AnchorSpec, "hours", {}, _column(Reminder, "anchor_hours"), "ge", _READING_MAX, True),
    # An interval needs a second one beside it for its null case to be a valid rule.
    Case(RecurrenceSpec, "interval_hours", {"interval_months": 6}, _INTERVAL, "gt", _LOG_MAX, True),
    Case(
        MaintenanceRuleCreate,
        "interval_hours",
        {"title": "Oil", "interval_months": 6},
        _INTERVAL,
        "gt",
        _LOG_MAX,
        True,
    ),
    Case(
        IntervalOverride, "interval_hours", {"interval_months": 6}, _INTERVAL, "gt", _LOG_MAX, True
    ),
]
IDS = [f"{case.schema.__name__}.{case.field}" for case in CASES]


@pytest.mark.parametrize("case", CASES, ids=IDS)
@pytest.mark.parametrize(
    ("given", "reads"),
    [
        ("812.45", Decimal("812.5")),
        (0.1 + 0.2, Decimal("0.3")),
        ("812.40", Decimal("812.4")),
    ],
)
def test_engine_hours_read_as_the_stored_tenth(case: Case, given: object, reads: Decimal) -> None:
    hours = case.read(given)
    assert hours == reads
    # The exponent too: 812.40 == 812.4 already, so equality alone can't see it.
    assert hours.as_tuple().exponent == -case.column.type.scale


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_column_keeps_a_tenth(case: Case) -> None:
    # Rounding to 0.1 is only right while the column keeps exactly one place.
    assert case.column.type.scale == 1


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_bounds_still_refuse(case: Case) -> None:
    # -0.04 and le + 0.04 would round back inside the bounds; they're checked first.
    refused = ["-0.1", "-0.04"] if case.floor == "ge" else ["0", "-0.04"]
    if case.le is not None:
        assert case.read(str(case.le)) == case.le
        refused += [str(case.le + Decimal("0.1")), str(case.le + Decimal("0.04"))]
    for value in refused:
        with pytest.raises(ValidationError, match=case.field):
            case.read(value)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_a_null_never_reaches_the_rounding(case: Case) -> None:
    # A nullable field keeps its null; the hours log's NOT NULL fields 422 it.
    if case.nullable:
        assert case.read(None) is None
    else:
        with pytest.raises(ValidationError, match=case.field):
            case.read(None)


def test_a_figure_too_long_to_round_is_left_for_the_database() -> None:
    # current_hours has no `le`, so a huge figure gets this far. Quantize can't fit
    # it in 28 digits; leave it as is and the database refuses it, as it did before.
    huge = Decimal("1E+30")
    assert to_stored_tenth(huge) == huge
    assert VehicleUpdate.model_validate({"current_hours": "1E+30"}).current_hours == huge
