"""When two stored figures are the same reading.

v3.4.0 moved every unit conversion onto the exact definitions. A figure saved
before that was converted with a truncated factor and rounded to the column's
step, so the same odometer typed again today can land a few parts per million
away from its stored self: 89,044 mi saved as 143,302.07 km, retyped as
143,302.43 km. Anything that orders two odometers (a mount below a dismount, a
reading behind a period) would read that as the odometer running backwards.

One band, used by every odometer ordering comparison in tire history and tire
distance, so the two cannot disagree about what counts as the same figure. The
import duplicate check uses it too, but only where the drift can exist: a value
converted from miles or gallons in that import, against a row stored before it
(`app.routes.import_data._matching._converted_value_matches`). Everywhere else in an
import, two figures inside the band are two different readings.
"""

from __future__ import annotations

from decimal import Decimal

#: The widest relative gap between a figure converted with the exact factors
#: and the same figure converted before v3.4.0: the old mile (1.60934 km) sat
#: 2.49 parts per million below the exact one, the old US gallon 0.47 below.
FACTOR_DRIFT = Decimal("3e-6")
#: Odometer columns are NUMERIC(10, 2); volume columns NUMERIC(9, 3).
KM_STEP = Decimal("0.01")
LITRE_STEP = Decimal("0.001")


def conversion_tolerance(value: Decimal, step: Decimal) -> Decimal:
    """How far a stored figure can sit from `value` and still be the same one.

    The factor drift scaled to the figure's size, plus the column's rounding
    step, since both apply to a row saved before the exact factors.

    Args:
        value: The figure, in canonical units.
        step: The storage column's rounding step for that quantity.

    Returns:
        The half-width of the band around `value`, never negative.
    """
    return abs(value) * FACTOR_DRIFT + step


def odometer_tolerance(a: Decimal, b: Decimal) -> Decimal:
    """The band within which two odometers, in km, are the same reading.

    Scaled by the larger magnitude of the two, so the relation is symmetric:
    `odometer_below(a, b)` is always `odometer_above(b, a)`.
    """
    return conversion_tolerance(max(abs(a), abs(b)), KM_STEP)


def odometer_below(a: Decimal, b: Decimal) -> bool:
    """Whether odometer `a` is below `b` by more than the band: `a < b - tol`."""
    return a < b - odometer_tolerance(a, b)


def odometer_above(a: Decimal, b: Decimal) -> bool:
    """Whether odometer `a` is above `b` by more than the band: `a > b + tol`."""
    return a > b + odometer_tolerance(a, b)
