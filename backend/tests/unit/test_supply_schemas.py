from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import Column, Numeric

from app.models.supply import SupplyPurchase, SupplyUsage
from app.schemas.supply import (
    SupplyAdjustmentCreate,
    SupplyCreate,
    SupplyPurchaseCreate,
    SupplyResponse,
    SupplyUpdate,
    SupplyUsageInput,
    SupplyUsageResponse,
)


def test_supply_create_requires_valid_unit_type():
    ok = SupplyCreate(name="Mobil 1 5W-30", unit_type="volume")
    assert ok.unit_type == "volume"
    with pytest.raises(ValidationError):
        SupplyCreate(name="x", unit_type="gallons")


def test_supply_update_has_no_unit_type_field():
    # unit_type is immutable after creation.
    assert "unit_type" not in SupplyUpdate.model_fields


def test_usage_input_quantity_must_be_positive():
    SupplyUsageInput(supply_id=1, quantity=Decimal("0.5"))
    with pytest.raises(ValidationError):
        SupplyUsageInput(supply_id=1, quantity=Decimal("0"))


def test_adjustment_quantity_positive():
    SupplyAdjustmentCreate(quantity=Decimal("1"))
    with pytest.raises(ValidationError):
        SupplyAdjustmentCreate(quantity=Decimal("-1"))


def _column_max(column: Column) -> Decimal:
    """The largest value a Numeric(p, s) column holds."""
    numeric = column.type
    assert isinstance(numeric, Numeric) and numeric.precision and numeric.scale is not None
    return Decimal(10) ** (numeric.precision - numeric.scale) - Decimal(10) ** -numeric.scale


# A quantity is bounded by what its column holds, and no tighter: a household
# product cap would be invented. Past it, PostgreSQL refuses the row with a 500.
@pytest.mark.parametrize(
    ("build", "column"),
    [
        pytest.param(
            lambda q: SupplyUsageInput(supply_id=1, quantity=q),
            SupplyUsage.__table__.c.quantity,
            id="usage-on-a-line-item",
        ),
        pytest.param(
            lambda q: SupplyAdjustmentCreate(quantity=q),
            SupplyUsage.__table__.c.quantity,
            id="adjustment",
        ),
        pytest.param(
            lambda q: SupplyPurchaseCreate(date=date(2026, 1, 1), quantity=q),
            SupplyPurchase.__table__.c.quantity,
            id="purchase",
        ),
    ],
)
def test_a_quantity_takes_what_its_column_holds(
    build: Callable[[Decimal], BaseModel], column: Column
):
    top = _column_max(column)
    assert top == Decimal("999999999.999")
    assert build(top).model_dump()["quantity"] == top

    with pytest.raises(ValidationError) as refused:
        build(top + Decimal("0.001"))
    assert [e["type"] for e in refused.value.errors()] == ["less_than_equal"]


def test_supply_create_accepts_a_volume_unit():
    s = SupplyCreate(name="Brake fluid", unit_type="volume", volume_unit="fl_oz_us")
    assert s.volume_unit == "fl_oz_us"


def test_supply_create_rejects_an_unknown_token():
    with pytest.raises(ValidationError):
        SupplyCreate(name="x", unit_type="volume", volume_unit="pt_us")


def test_count_supply_with_a_volume_unit_is_a_422():
    with pytest.raises(ValidationError):
        SupplyCreate(name="Filters", unit_type="count", volume_unit="qt_us")


def test_supply_update_distinguishes_clear_from_omit():
    assert "volume_unit" not in SupplyUpdate().model_dump(exclude_unset=True)
    cleared = SupplyUpdate(volume_unit=None).model_dump(exclude_unset=True)
    assert cleared["volume_unit"] is None


def test_supply_response_reads_an_unknown_stored_token_as_null():
    r = SupplyResponse(
        id=1,
        name="Oil",
        unit_type="volume",
        is_active=True,
        on_hand=Decimal("1.000"),
        is_negative=False,
        created_at=datetime(2026, 1, 1),
        volume_unit="pt_us",
    )
    assert r.volume_unit is None


def test_supply_usage_response_reads_leniently_too():
    r = SupplyUsageResponse(
        id=1,
        supply_id=1,
        supply_name="Oil",
        unit_type="volume",
        quantity=Decimal("0.250"),
        created_at=datetime(2026, 1, 1),
        volume_unit="bogus",
    )
    assert r.volume_unit is None


_QUANTITY_SCHEMAS = [
    pytest.param(lambda q: SupplyUsageInput(supply_id=1, quantity=q), id="usage-on-a-line-item"),
    pytest.param(lambda q: SupplyAdjustmentCreate(quantity=q), id="adjustment"),
    pytest.param(lambda q: SupplyPurchaseCreate(date=date(2026, 1, 1), quantity=q), id="purchase"),
]


@pytest.mark.parametrize("build", _QUANTITY_SCHEMAS)
def test_a_quantity_below_the_storable_grain_is_refused(build: Callable[[Decimal], BaseModel]):
    with pytest.raises(ValidationError):
        build(Decimal("0.0004"))


@pytest.mark.parametrize("build", _QUANTITY_SCHEMAS)
@pytest.mark.parametrize(
    ("given", "stored"),
    [
        (Decimal("0.0005"), Decimal("0.001")),
        (Decimal("0.35488235475"), Decimal("0.355")),
        (Decimal("1"), Decimal("1")),
    ],
)
def test_a_quantity_normalizes_to_three_decimals(
    build: Callable[[Decimal], BaseModel], given: Decimal, stored: Decimal
):
    got = build(given).model_dump()["quantity"]
    assert got == stored
    assert got.as_tuple().exponent == -3
