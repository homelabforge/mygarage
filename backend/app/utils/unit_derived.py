"""Derived-quantity formatting: compound values where two units compose.

Task 4 of the custom-units phase 2a plan (R4/R5). Sits on top of the
conversion layer (`unit_adapters.adapter_for`, `unit_counterparts.counterpart_for`)
and the formatting layer (`unit_formatting.format_rate`), the same way
`unit_formatting.py` sits on top of `unit_adapters.py`.

A derived quantity composes two of `UnitSet`'s ten quantities (a rate's
numerator and denominator) rather than converting a single one, so it needs
its own show-both grammar: which side of the composition a counterpart
flips depends on the quantity (D4c):

- **Fuel rate** (canonical L/hr) flips volume only, and holds the
  dimensionless `"/hr"` suffix fixed (R6: hours have no adapter). That is
  exactly what `unit_formatting.format_rate(..., quantity="volume",
  suffix="/hr")` already does, so `format_fuel_rate` is a thin, named
  wrapper rather than a reimplementation.
- **Cost per distance** flips distance AND its presentation scale
  together: a km reader is always quoted per 100 km, a mile reader per
  1,000 mi, never a mismatched pairing between the two. The primary's
  scale goes in the label (`cost_per_distance_unit_label`), the
  counterpart's stays on its value.

Cost per volume and volume per distance had formatters here too, waiting on
a CSV consumer that shipped without them, so they went.

**Presentation scales, not conversion factors (R5).** `PER_100_KM` and
`PER_1000_MI` do not convert one unit into another; they choose the
denominator size a rate is displayed against ("dollars per WHAT multiple of
km/mi") so the printed number is a normal magnitude instead of e.g.
`$0.012/km`.

**No new conversion-factor literal appears in this module.** Where a
derived quantity's denominator needs converting, this module calls the
existing adapter's own public API -- `adapter.to_canonical(Decimal("1"))`
(recovering that adapter's own linear factor -- "how much canonical km is 1
of this typed unit" -- without duplicating a constant that already lives in
`unit_adapters.ADAPTERS`). Every distance adapter in `ADAPTERS` is a
`LinearUnitAdapter` with `offset=0`, so `to_canonical(Decimal("1"))` is
exactly that adapter's factor; nothing below touches a reciprocal
(`InverseUnitAdapter`) quantity, so the local `is None` check below is
pyright-required narrowing for the `UnitAdapter` Protocol's declared
`Decimal | None` return, not a reachable runtime path -- the same shape
`unit_formatting._format_with_optional_counterpart` already uses for
`counterpart_for`'s declared-but-currently-unreachable `None`.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from app.utils.currency import get_currency_symbol
from app.utils.render_context import RenderContext
from app.utils.unit_adapters import UnitAdapter, adapter_for
from app.utils.unit_counterparts import counterpart_for
from app.utils.unit_formatting import format_rate

# Presentation scales (R5): NOT conversion factors -- see the module
# docstring. Each is asserted by its own test.
PER_100_KM = Decimal("100")
PER_1000_MI = Decimal("1000")

# Currency amounts are always rendered to 2 decimal places -- a display
# convention (like every volume adapter's own `precision=2` in
# `unit_adapters.ADAPTERS`), not a conversion factor, so it lives here as a
# plain constant rather than a lookup into unit_adapters.py.
_CURRENCY_PRECISION = 2

# Cost-per-distance's presentation scale, keyed by the *distance* adapter's
# own `.unit` token. D4c: the scale flips together with the distance side,
# so whichever adapter a caller resolves for a given render (primary or
# counterpart) carries its own scale with it.
_COST_PER_DISTANCE_SCALE: Mapping[str, Decimal] = {"km": PER_100_KM, "mi": PER_1000_MI}


def format_fuel_rate(l_per_hr: Decimal | None, ctx: RenderContext) -> str:
    """Render a fuel-consumption rate (canonical litres per hour).

    D4c: fuel rate flips volume only. Delegates to `format_rate` with
    `quantity="volume"` and a fixed `"/hr"` suffix -- that call already is
    "flip volume, hold the suffix fixed", so there is nothing left for this
    function to add beyond naming the derived quantity. Returns `"N/A"` for
    a `None` input, with no counterpart.
    """
    return format_rate(l_per_hr, ctx, "volume", "/hr")


def _cost_per_distance_scale_label(adapter: UnitAdapter) -> str:
    """The denominator one side is quoted against: "100 km" or "1,000 mi"."""
    scale = _COST_PER_DISTANCE_SCALE[adapter.unit]
    return f"{scale:,.0f} {adapter.label}"


def _format_cost_per_distance_side(
    cost_per_km: Decimal, adapter: UnitAdapter, symbol: str, *, with_scale: bool
) -> str:
    """One side of a cost-per-distance representation, scaled per D4c.

    Composes two independent operations on `cost_per_km`:
    `to_canonical(1)` converts the per-canonical-km rate to
    per-typed-distance-unit, then the adapter's own
    presentation scale (`_COST_PER_DISTANCE_SCALE`) re-expands that from
    "per 1 [km|mi]" to "per 100 km" or "per 1,000 mi" so the printed number
    is a normal magnitude instead of a fraction of a cent.

    `with_scale` appends the "/100 km" denominator. The primary leaves it
    off because its label already says it; a counterpart keeps it.
    """
    factor = adapter.to_canonical(Decimal("1"))
    if factor is None:
        return "N/A"
    scale = _COST_PER_DISTANCE_SCALE[adapter.unit]
    cost_per_scale = cost_per_km * factor * scale
    figure = f"{symbol}{cost_per_scale:,.{_CURRENCY_PRECISION}f}"
    if not with_scale:
        return figure
    return f"{figure}/{_cost_per_distance_scale_label(adapter)}"


def cost_per_distance_unit_label(ctx: RenderContext) -> str:
    """The denominator `format_cost_per_distance`'s primary figure is quoted against.

    "100 km" for a km reader, "1,000 mi" for a mile reader. Callers put it in
    the label ("Cost Per 100 km"), the way the screen does. It reads the same
    adapter and scale table as the value, so the two can't disagree.
    """
    return _cost_per_distance_scale_label(adapter_for(ctx.units, "distance"))


def format_cost_per_distance(
    cost_per_km: Decimal | None,
    ctx: RenderContext,
    currency_code: str | None,
    locale: str | None = "en-US",
) -> str:
    """Render a cost-per-distance rate (canonical currency units per km).

    D4c: flips distance and its presentation scale together -- a km reader
    is quoted per 100 km, a mile reader per 1,000 mi, never a mismatched
    pairing. The primary is the plain currency figure ("$42.00"); its scale
    belongs in the label, from `cost_per_distance_unit_label`. A show-both
    counterpart keeps its own scale, since no label names it:
    "$675.92 ($42.00/100 km)". Returns `"N/A"` for a `None` input, with no
    counterpart.
    """
    if cost_per_km is None:
        return "N/A"
    symbol = get_currency_symbol(currency_code, locale)
    primary_adapter = adapter_for(ctx.units, "distance")
    primary = _format_cost_per_distance_side(cost_per_km, primary_adapter, symbol, with_scale=False)
    if not ctx.show_both:
        return primary
    counterpart_adapter = counterpart_for(ctx.units, "distance")
    if counterpart_adapter is None:
        return primary
    counterpart = _format_cost_per_distance_side(
        cost_per_km, counterpart_adapter, symbol, with_scale=True
    )
    return f"{primary} ({counterpart})"
