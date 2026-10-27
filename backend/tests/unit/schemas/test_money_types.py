"""The shared money constants and field types in `app.schemas._money`.

The importers check imported numbers with `_within_api_bounds`, which reads the
bounds off `model_fields[name].metadata`. If the alias types ever leave their
bounds nested inside the Optional instead of on the FieldInfo, pydantic still
enforces them on the API but the importers silently enforce nothing. A PEP 695
`type Money = ...` alias does exactly that, so these tests pin the metadata, not
just the validation.

The per-importer-schema check (every money field of a schema an importer passes
to `_within_api_bounds` carries `le == MONEY_MAX`) is in
test_money_input_bounds.py, with the input schemas that use these types.
"""

from decimal import Decimal

import pytest
from pydantic import BaseModel, Field, ValidationError

from app.routes.import_data import _ImportBoundError, _within_api_bounds
from app.schemas._money import (
    MONEY_MAX,
    UNIT_COST_MAX,
    UNIT_PRICE_MAX,
    Money,
    OptionalMoney,
    OptionalUnitPrice,
    UnitPrice,
)

CENT = Decimal("0.01")
MIL = Decimal("0.001")


class _Sample(BaseModel):
    """Every way a schema is expected to use the types."""

    optional: OptionalMoney = None
    optional_with_field: OptionalMoney = Field(
        None, decimal_places=2, description="Payment or fee amount"
    )
    required: Money
    required_with_field: Money = Field(..., decimal_places=2, description="Nightly rate")
    optional_price: OptionalUnitPrice = None
    required_price: UnitPrice


_BASELINE = {"required": 0, "required_with_field": 0, "required_price": 0}

_MONEY_FIELDS = ("optional", "optional_with_field", "required", "required_with_field")
_PRICE_FIELDS = ("optional_price", "required_price")


def _bound(name: str, attr: str) -> object:
    """The bound `_within_api_bounds` would find, read the same way it reads it."""
    found = [
        getattr(item, attr)
        for item in _Sample.model_fields[name].metadata
        if getattr(item, attr, None) is not None
    ]
    assert len(found) == 1, f"{name} carries {len(found)} {attr} bounds on its FieldInfo"
    return found[0]


@pytest.mark.parametrize(
    ("value", "precision", "scale"),
    [(MONEY_MAX, 12, 2), (UNIT_PRICE_MAX, 13, 4), (UNIT_COST_MAX, 15, 4)],
    ids=["money", "unit_price", "unit_cost"],
)
def test_each_max_is_the_largest_its_column_holds(value: Decimal, precision: int, scale: int):
    assert isinstance(value, Decimal)
    # Every digit a 9, exactly `precision` of them, `scale` after the point.
    sign, digits, exponent = value.as_tuple()
    assert sign == 0
    assert digits == (9,) * precision
    assert exponent == -scale


def test_the_maxima_are_the_policy_values():
    assert Decimal("9999999999.99") == MONEY_MAX
    assert Decimal("999999999.9999") == UNIT_PRICE_MAX
    assert Decimal("99999999999.9999") == UNIT_COST_MAX


@pytest.mark.parametrize("name", _MONEY_FIELDS)
def test_money_bounds_sit_on_the_field_info(name: str):
    assert _bound(name, "ge") == 0
    assert _bound(name, "le") == MONEY_MAX


@pytest.mark.parametrize("name", _PRICE_FIELDS)
def test_unit_price_bounds_sit_on_the_field_info(name: str):
    assert _bound(name, "ge") == 0
    assert _bound(name, "le") == UNIT_PRICE_MAX


def test_an_assigned_field_keeps_its_own_settings():
    for name, description in (
        ("optional_with_field", "Payment or fee amount"),
        ("required_with_field", "Nightly rate"),
    ):
        info = _Sample.model_fields[name]
        assert info.description == description
        places = [getattr(m, "decimal_places", None) for m in info.metadata]
        assert 2 in places, f"{name} lost decimal_places=2: {info.metadata}"


def test_requiredness_follows_the_declaration():
    fields = _Sample.model_fields
    assert not fields["optional"].is_required()
    assert fields["optional"].default is None
    assert not fields["optional_with_field"].is_required()
    assert fields["required"].is_required()
    assert fields["required_with_field"].is_required()
    assert fields["required_price"].is_required()


@pytest.mark.parametrize("name", _MONEY_FIELDS)
def test_pydantic_holds_money_to_the_bounds(name: str):
    _Sample.model_validate({**_BASELINE, name: MONEY_MAX})
    _Sample.model_validate({**_BASELINE, name: Decimal(0)})
    for bad in (MONEY_MAX + CENT, -CENT):
        with pytest.raises(ValidationError):
            _Sample.model_validate({**_BASELINE, name: bad})


@pytest.mark.parametrize("name", _PRICE_FIELDS)
def test_pydantic_holds_unit_prices_to_the_bounds(name: str):
    _Sample.model_validate({**_BASELINE, name: UNIT_PRICE_MAX})
    for bad in (UNIT_PRICE_MAX + MIL, -MIL):
        with pytest.raises(ValidationError):
            _Sample.model_validate({**_BASELINE, name: bad})


def test_optional_types_accept_null():
    sample = _Sample.model_validate({**_BASELINE, "optional": None, "optional_price": None})
    assert sample.optional is None
    assert sample.optional_price is None


@pytest.mark.parametrize("name", _MONEY_FIELDS)
def test_the_importer_check_holds_money_to_the_bounds(name: str):
    _within_api_bounds(_Sample, **{name: MONEY_MAX})
    _within_api_bounds(_Sample, **{name: None})
    with pytest.raises(_ImportBoundError, match="at most 9999999999.99"):
        _within_api_bounds(_Sample, **{name: MONEY_MAX + CENT})
    with pytest.raises(_ImportBoundError, match="at least 0"):
        _within_api_bounds(_Sample, **{name: -CENT})


@pytest.mark.parametrize("name", _PRICE_FIELDS)
def test_the_importer_check_holds_unit_prices_to_the_bounds(name: str):
    _within_api_bounds(_Sample, **{name: UNIT_PRICE_MAX})
    with pytest.raises(_ImportBoundError, match=r"at most 999999999\.9999,"):
        _within_api_bounds(_Sample, **{name: UNIT_PRICE_MAX + MIL})
    with pytest.raises(_ImportBoundError, match="at least 0"):
        _within_api_bounds(_Sample, **{name: -MIL})
