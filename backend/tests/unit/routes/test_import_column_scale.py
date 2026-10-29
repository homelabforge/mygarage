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
    HoursRecord,
    OdometerRecord,
    Reminder,
    ServiceVisit,
    WarrantyRecord,
)
from app.models._types import ScaledNumeric
from app.routes.import_data import _COLUMN_SCALE, _column_step, _same_figure
from app.utils.csv_units import (
    CONSUMPTION,
    DISTANCE,
    MASS,
    PRICE_PER_VOLUME,
    PROPANE_VOLUME,
    SPEED,
    TEMPERATURE,
    VOLUME,
)
from app.utils.odometer_tolerance import KM_STEP, LITRE_STEP

#: Every column each converted quantity is written to by a CSV import.
_LANDS_IN: dict[str, tuple[InstrumentedAttribute[Any], ...]] = {
    DISTANCE: (
        ServiceVisit.odometer_km,
        FuelRecord.odometer_km,
        DEFRecord.odometer_km,
        OdometerRecord.odometer_km,
        WarrantyRecord.mileage_limit_km,
        Reminder.due_mileage_km,
    ),
    VOLUME: (FuelRecord.liters, DEFRecord.liters),
    PRICE_PER_VOLUME: (FuelRecord.price_per_unit, DEFRecord.price_per_unit),
    TEMPERATURE: (FuelRecord.outside_temp_c,),
    CONSUMPTION: (FuelRecord.obc_l_per_100km,),
    SPEED: (FuelRecord.obc_avg_speed_kmh,),
    # The fuel CSV's Propane Volume and Tank Size columns (batch 3b, B3-3).
    PROPANE_VOLUME: (FuelRecord.propane_liters,),
    MASS: (FuelRecord.tank_size_kg,),
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


@pytest.mark.parametrize(
    ("column", "value", "low", "high"),
    [
        (FuelRecord.kwh, "12.345", "12.3445", "12.3455"),
        (FuelRecord.propane_liters, "20.000", "19.9995", "20.0005"),
        (DEFRecord.fill_level, "0.50", "0.495", "0.505"),
        (WarrantyRecord.mileage_limit_km, "57936.38", "57936.375", "57936.385"),
        (HoursRecord.engine_hours, "120.5", "120.45", "120.55"),
        (Reminder.due_mileage_km, "16093.44", "16093.435", "16093.445"),
    ],
    ids=lambda value: value if isinstance(value, str) else str(value),
)
def test_a_key_band_is_half_the_columns_own_step(
    column: InstrumentedAttribute[Any], value: str, low: str, high: str
) -> None:
    """T-20's band, read off the column, so a widened column narrows its band too (R-2)."""
    condition = _same_figure(column, Decimal(value))
    compiled = str(condition.compile(compile_kwargs={"literal_binds": True}))
    assert compiled.endswith(f"BETWEEN {low} AND {high}"), compiled


def test_the_shared_odometer_and_litre_steps_are_the_columns_own() -> None:
    assert KM_STEP == _column_step(OdometerRecord.odometer_km)
    assert LITRE_STEP == _column_step(FuelRecord.liters)
