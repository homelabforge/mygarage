"""When two engine-hours figures are the same reading.

The hour meter's `odometer_tolerance`, and narrower. Hours are never
converted, so there's no conversion drift to absorb. Tire writes round to
the stored tenth as they're parsed, so this is a backstop for any figure
that reaches a comparison unrounded.
"""

from __future__ import annotations

from decimal import Decimal

#: Half the stored tenth.
HOURS_TOLERANCE = Decimal("0.05")


def hours_below(a: Decimal, b: Decimal) -> bool:
    """Whether hours `a` are below `b` by more than the band."""
    return a < b - HOURS_TOLERANCE


def hours_above(a: Decimal, b: Decimal) -> bool:
    """Whether hours `a` are above `b` by more than the band."""
    return a > b + HOURS_TOLERANCE
