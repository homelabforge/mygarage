"""The unit rules a declared unit carries (R4, R5)."""

import pytest


@pytest.mark.parametrize(
    "unit,expected",
    [
        ("rpm", "frequency"),
        ("RPM", "frequency"),
        ("km/h", "speed"),
        ("mph", "speed"),
        ("mi/h", "speed"),
        ("°C", "temperature"),
        ("C", "temperature"),
        ("kPa", "pressure"),
        ("V", "voltage"),
        ("%", "percentage"),
        ("km", "distance"),
        ("mi", "distance"),
        (" mph ", "speed"),
        ("°F", None),
        ("psi", None),
        ("", None),
        (None, None),
    ],
)
def test_a_unit_names_its_class(unit, expected):
    from app.utils.wire_units import class_for_unit

    assert class_for_unit(unit) == expected


@pytest.mark.parametrize(
    "unit,expected",
    [("mph", True), ("MPH", True), ("mi/h", True), ("Mi/H", True), ("km/h", False), ("mi", False)],
)
def test_mph_any_case(unit, expected):
    from app.utils.wire_units import is_mph

    assert is_mph(unit) is expected


def test_mph_to_kmh_keeps_full_precision():
    from app.utils.wire_units import mph_to_kmh

    assert mph_to_kmh(50) == 80.4672
    assert mph_to_kmh(80.0) == 128.74752
