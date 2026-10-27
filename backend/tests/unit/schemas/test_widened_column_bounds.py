"""An input bound that mirrors a widened column takes the column's own max.

Batch 7 widened consumption to Numeric(7,4) and the propane tank size to
Numeric(7,3). A bound left at the old Numeric(5,2) or (6,2) top would refuse
values the column now holds.

Guard: it held before the widening too, when bound and column were both old.
Mutant killed: the column widened with the bound left at 999.99 / 9999.99.
"""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import Column

from app.models.fuel import FuelRecord
from app.models.vehicle import Vehicle
from app.routes.window_sticker import WindowStickerDataUpdate
from app.schemas.fuel import FuelRecordCreate, FuelRecordUpdate


def _column_max(column: Column[Any]) -> Decimal:
    numeric = column.type.impl_instance
    return Decimal(10) ** (numeric.precision - numeric.scale) - Decimal(10) ** -numeric.scale


def _le(schema: type[BaseModel], field: str) -> Decimal:
    found = [
        m.le for m in schema.model_fields[field].metadata if getattr(m, "le", None) is not None
    ]
    assert len(found) == 1, f"{schema.__name__}.{field} has {len(found)} le bounds"
    return Decimal(str(found[0]))


@pytest.mark.parametrize(
    ("schema", "field", "column"),
    [
        (FuelRecordCreate, "obc_l_per_100km", FuelRecord.__table__.c.obc_l_per_100km),
        (FuelRecordUpdate, "obc_l_per_100km", FuelRecord.__table__.c.obc_l_per_100km),
        (FuelRecordCreate, "tank_size_kg", FuelRecord.__table__.c.tank_size_kg),
        (FuelRecordUpdate, "tank_size_kg", FuelRecord.__table__.c.tank_size_kg),
        *(
            (WindowStickerDataUpdate, name, Vehicle.__table__.c[name])
            for name in (
                "fuel_economy_city_l_per_100km",
                "fuel_economy_highway_l_per_100km",
                "fuel_economy_combined_l_per_100km",
            )
        ),
    ],
)
def test_the_bound_is_the_column_max(
    schema: type[BaseModel], field: str, column: Column[Any]
) -> None:
    assert _le(schema, field) == _column_max(column)
