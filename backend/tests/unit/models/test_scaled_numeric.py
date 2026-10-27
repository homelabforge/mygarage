"""ScaledNumeric rounds a bind to its column's scale the way PostgreSQL does.

The type on its own, no database: what each kind of input becomes, and what it
leaves alone. The database side (raw stored values, comparisons, the economy
window, imports) is in `tests/integration/routes/test_numeric_binds_scaled.py`.
"""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.models._types import ScaledNumeric
from app.models.fuel import FuelRecord

ODOMETER = ScaledNumeric(10, 2)


def _bind(value: Any, kind: ScaledNumeric = ODOMETER) -> Any:
    return kind.process_bind_param(value, sqlite.dialect())


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(Decimal("19867.35168"), Decimal("19867.35"), id="miles-to-km"),
        # PG rounds a tie away from zero, both ways. Half-even would give 1.02.
        pytest.param(Decimal("1.025"), Decimal("1.03"), id="tie-up"),
        pytest.param(Decimal("-1.025"), Decimal("-1.03"), id="negative-tie"),
        # The double nearest 1.005 is 1.00499..., so Decimal(x) would round it
        # down. repr gives back the 1.005 that was typed.
        pytest.param(1.005, Decimal("1.01"), id="float-through-repr"),
        pytest.param(7, Decimal("7.00"), id="int"),
        pytest.param("19867.35168", Decimal("19867.35"), id="text"),
    ],
)
def test_a_bind_rounds_to_the_column_scale(value: Any, expected: Decimal):
    bound = _bind(value)
    assert isinstance(bound, Decimal)
    assert bound == expected
    assert bound.as_tuple().exponent == -2


def test_each_column_rounds_to_its_own_scale():
    assert _bind(Decimal("40.0005"), ScaledNumeric(9, 3)) == Decimal("40.001")
    assert _bind(Decimal("812.45"), ScaledNumeric(10, 1)) == Decimal("812.5")
    assert _bind(Decimal("2.5"), ScaledNumeric(4, 0)) == Decimal("3")


def test_none_stays_none():
    assert _bind(None) is None


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(float("nan"), id="float-nan"),
        pytest.param(float("inf"), id="float-inf"),
        pytest.param(Decimal("NaN"), id="decimal-nan"),
        pytest.param(Decimal("-Infinity"), id="decimal-inf"),
    ],
)
def test_a_non_finite_value_passes_through_as_itself(value: Any):
    assert _bind(value) is value


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(Decimal("1e30"), id="decimal"),
        pytest.param(10**40, id="int"),
    ],
)
def test_a_number_too_big_to_round_goes_to_the_database_as_is(value: Any):
    # Past the decimal context's 28 digits quantize raises. Handing the value
    # on lets PG refuse it with its own overflow, which is a 422, not a 500.
    assert _bind(value) is value


def test_both_dialects_get_the_same_rounding():
    assert ODOMETER.process_bind_param(Decimal("1.005"), postgresql.dialect()) == Decimal("1.01")


def test_a_comparison_bind_takes_the_column_type():
    # So `WHERE odometer_km > :x` binds the number both dialects store.
    right = (FuelRecord.odometer_km > Decimal("19867.35168")).right
    assert isinstance(right.type, ScaledNumeric)
    assert right.type.impl.scale == 2


def test_the_cache_key_carries_precision_and_scale():
    # A cached statement reuses its bind processors and asyncpg's
    # ::NUMERIC(p, s) cast, so two scales can't share a key.
    assert ScaledNumeric(10, 2)._static_cache_key != ScaledNumeric(9, 3)._static_cache_key
    assert ScaledNumeric(10, 2)._static_cache_key == ScaledNumeric(10, 2)._static_cache_key


def test_the_ddl_is_the_plain_numeric():
    assert str(ODOMETER.compile(dialect=postgresql.dialect())) == "NUMERIC(10, 2)"
    assert str(ODOMETER.compile(dialect=sqlite.dialect())) == "NUMERIC(10, 2)"
