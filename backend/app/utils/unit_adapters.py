"""Conversion layer: one adapter per unit-preference token.

Metric-canonical storage: every stored value is metric (see `UnitConverter`'s
module docstring for the full table). This module converts at the boundary
only and never changes a stored value.

R3: two adapter shapes cover the ten `UnitSet` quantities.
- `LinearUnitAdapter` covers proportional relationships
  (`canonical = (typed - offset) * factor`) and, with a non-zero `offset`,
  affine ones. Fahrenheit is the only affine token; every other linear token
  uses the default `offset=0`, including the metric tokens whose typed unit
  IS the canonical unit (factor 1).
- `InverseUnitAdapter` covers reciprocal relationships (MPG, km/L), where
  `canonical = numerator / typed` in both directions: a reciprocal relation
  is its own inverse.

Deliberately primitive (R4). `format()` renders exactly one representation:
no `RenderContext`, no counterpart, no show-both grammar. Context-aware
formatting (`RenderContext`, `format_quantity`, show-both) lives in
`unit_formatting.py` (Task 3), not here.

Two token vocabularies exist in this codebase. `UnitConverter.to_canonical_decimal`
(`app/utils/units.py`) accepts the legacy set (`km/mi/L/gal/kg/lb/.../MPG`) and
remains a live API surface used elsewhere; it is not touched or routed through
here. `ADAPTERS` below is keyed on phase 1's lowercase, flavour-explicit
vocabulary (`app.constants.units.UnitSet`) instead, and the two are not unified.

`window_sticker_ocr.py` is left alone: it is out of scope for this task and
this module does not touch it.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Protocol

from app.constants.units import UnitSet
from app.utils.units import UnitConverter

# 1/32 inch, expressed in millimetres, for the tire-tread `in32` adapter.
# Exact: 25.4 mm per inch / 32.
_IN32_TO_MM = Decimal("25.4") / Decimal("32")

# L/100km per (km/L), i.e. the definition of "litres per hundred kilometres".
# Not an app-specific conversion factor, so it has no name in `units.py`.
_KM_L_NUMERATOR = Decimal("100")

# 1 bar = 100 kPa exactly, by SI definition (not derived from PSI_TO_BAR).
_BAR_TO_KPA = Decimal("100")


class UnitAdapter(Protocol):
    """One typed unit's round trip to and from its canonical representation."""

    unit: str
    label: str
    precision: int

    def to_display(self, canonical: Decimal | None) -> Decimal | None:
        """Convert a canonical value into this adapter's typed unit."""
        ...

    def to_canonical(self, typed: Decimal | None) -> Decimal | None:
        """Convert a value in this adapter's typed unit into canonical."""
        ...

    def format(self, canonical: Decimal | None, *, with_label: bool = True) -> str:
        """Render a canonical value in this adapter's typed unit.

        Primitive: one representation, no counterpart. Returns `"N/A"` for a
        `None` input, and for a reciprocal adapter, for an undefined zero.
        """
        ...


def _format_or_na(display: Decimal | None, label: str, precision: int, *, with_label: bool) -> str:
    """Shared rendering: `"N/A"` for an undefined value, else grouped number
    plus label, with the separating space suppressed for a label starting
    with `"/"` (tire tread, e.g. `"9/32 in"`)."""
    if display is None:
        return "N/A"
    number = f"{display:,.{precision}f}"
    if not with_label:
        return number
    if label.startswith("/"):
        return f"{number}{label}"
    return f"{number} {label}"


class LinearUnitAdapter:
    """Proportional or affine adapter: `canonical = (typed - offset) * factor`.

    `offset` defaults to `Decimal("0")`, covering every proportional token
    (including the identity adapters, factor 1, for metric tokens whose typed
    unit is already canonical). Fahrenheit is the only token with a non-zero
    `offset`. Zero is a real, well-defined value in both directions here.
    """

    def __init__(
        self,
        unit: str,
        label: str,
        precision: int,
        factor: Decimal,
        offset: Decimal = Decimal("0"),
    ) -> None:
        self.unit = unit
        self.label = label
        self.precision = precision
        self._factor = factor
        self._offset = offset

    def to_canonical(self, typed: Decimal | None) -> Decimal | None:
        """Typed unit -> canonical: `(typed - offset) * factor`."""
        if typed is None:
            return None
        return (typed - self._offset) * self._factor

    def to_display(self, canonical: Decimal | None) -> Decimal | None:
        """Canonical -> typed unit: `canonical / factor + offset`."""
        if canonical is None:
            return None
        return canonical / self._factor + self._offset

    def format(self, canonical: Decimal | None, *, with_label: bool = True) -> str:
        """Render a canonical value in this adapter's typed unit."""
        return _format_or_na(
            self.to_display(canonical), self.label, self.precision, with_label=with_label
        )


class InverseUnitAdapter:
    """Reciprocal adapter: `canonical = numerator / typed`, both directions.

    Self-inverse, since a reciprocal relationship inverts itself: the same
    formula converts typed -> canonical and canonical -> typed. Zero is
    undefined (division by zero) in both directions, unlike the linear
    adapters, where zero is a real value.
    """

    def __init__(self, unit: str, label: str, precision: int, numerator: Decimal) -> None:
        self.unit = unit
        self.label = label
        self.precision = precision
        self._numerator = numerator

    def to_canonical(self, typed: Decimal | None) -> Decimal | None:
        """Typed unit -> canonical: `numerator / typed`, `None` if zero."""
        if typed is None or typed == 0:
            return None
        return self._numerator / typed

    def to_display(self, canonical: Decimal | None) -> Decimal | None:
        """Canonical -> typed unit: `numerator / canonical`, `None` if zero."""
        if canonical is None or canonical == 0:
            return None
        return self._numerator / canonical

    def format(self, canonical: Decimal | None, *, with_label: bool = True) -> str:
        """Render a canonical value in this adapter's typed unit."""
        return _format_or_na(
            self.to_display(canonical), self.label, self.precision, with_label=with_label
        )


ADAPTERS: Mapping[str, UnitAdapter] = {
    # Distance
    "km": LinearUnitAdapter("km", "km", 0, Decimal("1")),
    "mi": LinearUnitAdapter("mi", "mi", 0, UnitConverter.MILES_TO_KM),
    # Speed (same factor as distance, distinct token)
    "kmh": LinearUnitAdapter("kmh", "km/h", 0, Decimal("1")),
    "mph": LinearUnitAdapter("mph", "mph", 0, UnitConverter.MILES_TO_KM),
    # Length
    "m": LinearUnitAdapter("m", "m", 2, Decimal("1")),
    "ft": LinearUnitAdapter("ft", "ft", 2, UnitConverter.FEET_TO_METERS),
    # Volume
    "L": LinearUnitAdapter("L", "L", 2, Decimal("1")),
    "gal_us": LinearUnitAdapter("gal_us", "gal", 2, UnitConverter.US_GALLONS_TO_LITERS),
    "gal_uk": LinearUnitAdapter("gal_uk", "gal", 2, UnitConverter.UK_GALLONS_TO_LITERS),
    # Consumption
    "l_100km": LinearUnitAdapter("l_100km", "L/100km", 2, Decimal("1")),
    "km_l": InverseUnitAdapter("km_l", "km/L", 2, _KM_L_NUMERATOR),
    "mpg_us": InverseUnitAdapter("mpg_us", "MPG", 1, UnitConverter.US_MPG_TO_L100KM_NUMERATOR),
    "mpg_uk": InverseUnitAdapter("mpg_uk", "MPG", 1, UnitConverter.UK_MPG_TO_L100KM_NUMERATOR),
    # Pressure
    "kpa": LinearUnitAdapter("kpa", "kPa", 0, Decimal("1")),
    "bar": LinearUnitAdapter("bar", "bar", 2, _BAR_TO_KPA),
    "psi": LinearUnitAdapter("psi", "PSI", 1, UnitConverter.PSI_TO_KPA),
    # Temperature
    "c": LinearUnitAdapter("c", "C", 1, Decimal("1")),
    "f": LinearUnitAdapter("f", "F", 1, Decimal("5") / Decimal("9"), offset=Decimal("32")),
    # Mass
    "kg": LinearUnitAdapter("kg", "kg", 2, Decimal("1")),
    "lb": LinearUnitAdapter("lb", "lb", 2, UnitConverter.LBS_TO_KG),
    # Torque
    "nm": LinearUnitAdapter("nm", "Nm", 1, Decimal("1")),
    "lbft": LinearUnitAdapter("lbft", "lb-ft", 1, UnitConverter.LBFT_TO_NM),
    # Tread
    "mm": LinearUnitAdapter("mm", "mm", 2, Decimal("1")),
    "in32": LinearUnitAdapter("in32", "/32 in", 0, _IN32_TO_MM),
}


def adapter_for(unit_set: UnitSet, quantity: str) -> UnitAdapter:
    """Resolve the adapter for one of `unit_set`'s quantities.

    `quantity` is a `UnitSet` field name (`"distance"`, `"pressure"`, ...).
    Raises `KeyError` for a name that is not a `UnitSet` field at all -
    including `"hours"`, which is dimensionless and outside the unit system
    (R6), so it deliberately has no adapter.
    """
    if quantity not in UnitSet.model_fields:
        raise KeyError(quantity)
    token = getattr(unit_set, quantity)
    return ADAPTERS[token]
