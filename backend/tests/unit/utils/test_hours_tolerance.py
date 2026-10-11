"""The hours band: half the 0.1 step NUMERIC(10, 1) stores."""

from decimal import Decimal

import pytest

from app.utils.hours_tolerance import HOURS_TOLERANCE, hours_above, hours_below


def test_the_band_is_half_a_tenth():
    assert HOURS_TOLERANCE == Decimal("0.05")


@pytest.mark.parametrize(
    ("a", "b", "below"),
    [
        ("100.0", "100.1", True),  # a full tenth apart: two readings
        ("99.9", "100.0", True),
        ("100.04", "100.0", False),  # rounds to the same stored tenth
        ("99.96", "100.0", False),
        ("100.0", "100.0", False),
    ],
)
def test_below(a, b, below):
    assert hours_below(Decimal(a), Decimal(b)) is below


def test_above_mirrors_below():
    grid = [Decimal(x) for x in ("0.0", "99.94", "99.96", "100.0", "100.04", "100.06", "100.1")]
    for a in grid:
        for b in grid:
            assert hours_below(a, b) is hours_above(b, a)
