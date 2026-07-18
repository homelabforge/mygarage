from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.supply import SupplyAdjustmentCreate, SupplyCreate, SupplyUpdate, SupplyUsageInput


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
