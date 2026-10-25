"""Rules a declared wire unit carries: the class it names (R5) and mph (R4).

Pure helpers. The per-device store and the resolution step that applies them
live in `app.services.device_units`.
"""

from __future__ import annotations

from decimal import Decimal

from app.utils.units import UnitConverter

#: The unit every speed reading is stored in.
CANONICAL_SPEED_UNIT = "km/h"

#: Lowercased unit -> the class it names. Upstream WiCAN declares
#: `0C-EngineRPM` as class `speed`, so a unit that names a class wins over
#: the declared one, or the speed range rejects every RPM above 350.
_UNIT_CLASSES: dict[str, str] = {
    "rpm": "frequency",
    "km/h": "speed",
    "mph": "speed",
    "mi/h": "speed",
    "°c": "temperature",
    "c": "temperature",
    "kpa": "pressure",
    "v": "voltage",
    "%": "percentage",
    "km": "distance",
    "mi": "distance",
}

_MPH_UNITS = frozenset({"mph", "mi/h"})


def class_for_unit(unit: str | None) -> str | None:
    """The class a unit names, or None when it names none."""
    if not unit:
        return None
    return _UNIT_CLASSES.get(unit.strip().lower())


def is_mph(unit: str | None) -> bool:
    """Whether a unit is miles per hour, any case."""
    return unit is not None and unit.strip().lower() in _MPH_UNITS


def mph_to_kmh(value: float) -> float:
    """Miles per hour to km/h, Decimal-precise and unrounded (a write path)."""
    return float(Decimal(str(value)) * UnitConverter.MILES_TO_KM)
