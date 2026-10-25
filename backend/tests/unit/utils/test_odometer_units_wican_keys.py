"""WiCAN odometer units follow upstream's vocabulary (D6a, N-1).

Upstream WiCAN names a kilometre odometer `ODOMETER` and a miles one
`ODOMETER_MI`. Main guessed miles for every bare key, so a profile-based
WiCAN with no unit set stored its odometer 1.609x high.
"""

from __future__ import annotations

from app.utils.odometer_units import (
    is_odometer_param_key,
    odometer_value_to_km,
    resolve_odometer_unit,
)


def test_bare_odometer_on_a_wican_with_no_unit_is_km() -> None:
    """Upstream's `ODOMETER` is kilometres."""
    assert resolve_odometer_unit("ODOMETER", None, "wican") == "km"
    assert odometer_value_to_km(1000.0, "ODOMETER", None, "wican") == 1000.0


def test_odometer_mi_is_miles_and_an_odometer_key() -> None:
    """Upstream's `ODOMETER_MI` is miles, and it is an odometer."""
    assert is_odometer_param_key("ODOMETER_MI") is True
    assert resolve_odometer_unit("ODOMETER_MI", None, "wican") == "mi"
    assert odometer_value_to_km(1000.0, "ODOMETER_MI", None, "wican") == 1609.34


def test_other_bare_keys_keep_the_miles_guess() -> None:
    """Regression guard: `MILEAGE`, `ODO` and friends are still user autopids."""
    for key in ("MILEAGE", "ODO", "TOTAL_DISTANCE", "DISTANCE_TOTAL"):
        assert resolve_odometer_unit(key, None, "wican") == "mi", key


def test_a_pid_key_is_km() -> None:
    """Regression guard: the SAE J1979 PID is metric."""
    assert resolve_odometer_unit("A6-ODOMETER", None, "wican") == "km"


def test_the_device_unit_still_wins() -> None:
    """Regression guard: a unit set on the device beats every key rule."""
    assert resolve_odometer_unit("ODOMETER", "mi", "wican") == "mi"
    assert resolve_odometer_unit("ODOMETER_MI", "km", "wican") == "km"
    assert resolve_odometer_unit("A6-ODOMETER", "mi", "wican") == "mi"


def test_the_device_unit_beats_a_declared_key_unit() -> None:
    """The order is device unit > the key's resolved unit > key rules."""
    assert resolve_odometer_unit("ODOMETER", "mi", "wican", key_unit="km") == "mi"


def test_a_declared_config_unit_beats_the_key_rule() -> None:
    """A unit the device declared for the key (its `config`, or its R12 row)
    beats the guess from the key's shape."""
    assert resolve_odometer_unit("MILEAGE", None, "wican", key_unit="km") == "km"
    assert resolve_odometer_unit("ODOMETER", None, "wican", key_unit="mi") == "mi"
    assert resolve_odometer_unit("ODOMETER", None, "wican", key_unit=" MI ") == "mi"
    assert odometer_value_to_km(1000.0, "MILEAGE", None, "wican", key_unit="km") == 1000.0


def test_a_key_unit_that_is_not_a_distance_falls_back_to_the_key_rule() -> None:
    """A declared `mph` (or junk) says nothing about the odometer's unit."""
    assert resolve_odometer_unit("MILEAGE", None, "wican", key_unit="mph") == "mi"
    assert resolve_odometer_unit("ODOMETER", None, "wican", key_unit="") == "km"


def test_non_wican_is_unchanged() -> None:
    """Regression guard: any other device kind gets the metric default whatever
    the key, and its own unit when one is set."""
    assert resolve_odometer_unit("ODOMETER", None, "torque") == "km"
    assert resolve_odometer_unit("ODOMETER_MI", None, "torque") == "km"
    assert resolve_odometer_unit("MILEAGE", "mi", "torque") == "mi"


def test_a_declared_key_unit_is_wican_only() -> None:
    """Torque's units come from TORQUE_DEFAULT_UNITS, and whether the phone
    sends display units is B6-8's question, so a declared unit changes nothing
    for it."""
    assert resolve_odometer_unit("MILEAGE", None, "torque", key_unit="mi") == "km"
