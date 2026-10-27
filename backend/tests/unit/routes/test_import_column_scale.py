"""The import rounds a converted figure to the scale of every column it lands in.

#245 widened three fuel columns and `_COLUMN_SCALE` kept the old scales, so an
imperial round trip lost a place on each (F-1). This walks every column a
converted quantity is written to, so the next widening fails here.
"""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import InstrumentedAttribute

from app.models import (
    DEFRecord,
    FuelRecord,
    OdometerRecord,
    ServiceVisit,
    WarrantyRecord,
)
from app.models._types import ScaledNumeric
from app.routes.import_data import _COLUMN_SCALE
from app.utils.csv_units import (
    CONSUMPTION,
    DISTANCE,
    PRICE_PER_VOLUME,
    SPEED,
    TEMPERATURE,
    VOLUME,
)

#: Every column each converted quantity is written to by a CSV import.
_LANDS_IN: dict[str, tuple[InstrumentedAttribute[Any], ...]] = {
    DISTANCE: (
        ServiceVisit.odometer_km,
        FuelRecord.odometer_km,
        DEFRecord.odometer_km,
        OdometerRecord.odometer_km,
        WarrantyRecord.mileage_limit_km,
    ),
    VOLUME: (FuelRecord.liters, DEFRecord.liters),
    PRICE_PER_VOLUME: (FuelRecord.price_per_unit, DEFRecord.price_per_unit),
    TEMPERATURE: (FuelRecord.outside_temp_c,),
    CONSUMPTION: (FuelRecord.obc_l_per_100km,),
    SPEED: (FuelRecord.obc_avg_speed_kmh,),
}


def test_every_converted_quantity_is_listed() -> None:
    assert set(_COLUMN_SCALE) == set(_LANDS_IN)


@pytest.mark.parametrize(
    ("quantity", "column"),
    [(quantity, column) for quantity, columns in _LANDS_IN.items() for column in columns],
    ids=lambda value: value if isinstance(value, str) else str(value),
)
def test_the_scale_is_the_columns_own(quantity: str, column: InstrumentedAttribute[Any]) -> None:
    column_type = column.type
    assert isinstance(column_type, ScaledNumeric)
    assert _COLUMN_SCALE[quantity] == Decimal(1).scaleb(-column_type.scale)
