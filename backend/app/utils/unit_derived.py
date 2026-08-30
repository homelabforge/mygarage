"""Derived-quantity formatting: compound values where two units compose.

Task 4 of the custom-units phase 2a plan (R4/R5). Sits on top of the
conversion layer (`unit_adapters.adapter_for`, `unit_counterparts.counterpart_for`)
and the formatting layer (`unit_formatting.format_rate`), the same way
`unit_formatting.py` sits on top of `unit_adapters.py`.

A derived quantity composes two of `UnitSet`'s ten quantities (a rate's
numerator and denominator) rather than converting a single one, so it needs
its own show-both grammar: which side of the composition a counterpart
flips is not the same for all four derived quantities (D4c):

- **Fuel rate** (canonical L/hr) flips volume only, and holds the
  dimensionless `"/hr"` suffix fixed (R6: hours have no adapter). That is
  exactly what `unit_formatting.format_rate(..., quantity="volume",
  suffix="/hr")` already does, so `format_fuel_rate` is a thin, named
  wrapper rather than a reimplementation.
- **Cost per volume** flips volume only.
- **Cost per distance** flips distance AND its presentation scale
  together: a km reader always gets `"/100 km"`, a mile reader always gets
  `"/1,000 mi"`, never a mismatched pairing between the two.
- **Volume per distance** flips BOTH numerator and denominator, composing
  each counterpart's adapter independently -- not "flip one side, hold the
  other".

**Presentation scales, not conversion factors (R5).** `PER_100_KM`,
`PER_1000_KM` and `PER_1000_MI` do not convert one unit into another; they
choose the denominator size a rate is displayed against ("dollars per WHAT
multiple of km/mi", "litres per WHAT multiple of km/mi") so the printed
number is a normal magnitude instead of e.g. `$0.012/km`. `PER_1000_KM` and
`PER_1000_MI` share the numeric value 1000 -- they are declared and tested
separately because they name two different presentation conventions (a
km-based rate's scale, a mile-based rate's scale), not because the numbers
themselves differ. `PER_100_KM` is unrelated to either: cost-per-distance
and volume-per-distance do not share a scale convention for km (100 vs
1000), which is why cost-per-distance's km side does not reuse
`PER_1000_KM`.

**No new conversion-factor literal appears in this module.** Where a
derived quantity's numerator or denominator needs converting, this module
calls the existing adapter's own public API -- `adapter.to_display(...)`
for a numerator (identical to how `unit_formatting.py` converts a simple
quantity) and `adapter.to_canonical(Decimal("1"))` for a denominator
(recovering that adapter's own linear factor -- "how much canonical
[km|L] is 1 of this typed unit" -- without duplicating a constant that
already lives in `unit_adapters.ADAPTERS`). Every distance and volume
adapter in `ADAPTERS` is a `LinearUnitAdapter` with `offset=0`, so
`to_canonical(Decimal("1"))` is exactly that adapter's factor; none of the
four functions below touches a reciprocal (`InverseUnitAdapter`) quantity,
so the local `is None` checks below are pyright-required narrowing for the
`UnitAdapter` Protocol's declared `Decimal | None` return, not a reachable
runtime path -- the same shape `unit_formatting._format_with_optional_counterpart`
already uses for `counterpart_for`'s declared-but-currently-unreachable `None`.
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
PER_1000_KM = Decimal("1000")
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

# Volume-per-distance's presentation scale, keyed the same way. A separate
# mapping from the one above: cost-per-distance and volume-per-distance do
# not share a scale convention for km (100 vs 1000).
_VOLUME_PER_DISTANCE_SCALE: Mapping[str, Decimal] = {"km": PER_1000_KM, "mi": PER_1000_MI}


def format_fuel_rate(l_per_hr: Decimal | None, ctx: RenderContext) -> str:
    """Render a fuel-consumption rate (canonical litres per hour).

    D4c: fuel rate flips volume only. Delegates to `format_rate` with
    `quantity="volume"` and a fixed `"/hr"` suffix -- that call already is
    "flip volume, hold the suffix fixed", so there is nothing left for this
    function to add beyond naming the derived quantity. Returns `"N/A"` for
    a `None` input, with no counterpart.
    """
    return format_rate(l_per_hr, ctx, "volume", "/hr")


def _format_cost_per_volume_side(cost_per_l: Decimal, adapter: UnitAdapter, symbol: str) -> str:
    """One side (primary or counterpart) of a cost-per-volume representation.

    `adapter.to_canonical(Decimal("1"))` is "how many canonical litres is 1
    of this adapter's typed unit" -- exactly the linear factor a cost needs
    to go from cost-per-canonical-litre to cost-per-typed-unit:
    `cost_per_typed = cost_per_l * (litres per typed unit)`.
    """
    factor = adapter.to_canonical(Decimal("1"))
    if factor is None:
        return "N/A"
    cost_per_typed = cost_per_l * factor
    return f"{symbol}{cost_per_typed:,.{_CURRENCY_PRECISION}f}/{adapter.label}"


def format_cost_per_volume(
    cost_per_l: Decimal | None,
    ctx: RenderContext,
    currency_code: str | None,
    locale: str | None = "en-US",
) -> str:
    """Render a cost-per-volume rate (canonical currency units per litre).

    D4c: flips volume only, with no presentation scale. `currency_code` and
    `locale` are resolved through `get_currency_symbol` -- never pass a
    pre-resolved symbol, which would drop the locale-aware contract.
    Returns `"N/A"` for a `None` input, with no counterpart.

    NOT DEAD CODE: no `app/` caller yet. D4c enumerates all four derived
    quantities and part B (CSV v6 plus the two report CSV endpoints, deferred
    out of phase 2a) is the first consumer. The backend has no reachability
    gate, so nothing else will tell you that.
    """
    if cost_per_l is None:
        return "N/A"
    symbol = get_currency_symbol(currency_code, locale)
    primary_adapter = adapter_for(ctx.units, "volume")
    primary = _format_cost_per_volume_side(cost_per_l, primary_adapter, symbol)
    if not ctx.show_both:
        return primary
    counterpart_adapter = counterpart_for(ctx.units, "volume")
    if counterpart_adapter is None:
        return primary
    counterpart = _format_cost_per_volume_side(cost_per_l, counterpart_adapter, symbol)
    return f"{primary} ({counterpart})"


def _format_cost_per_distance_side(cost_per_km: Decimal, adapter: UnitAdapter, symbol: str) -> str:
    """One side of a cost-per-distance representation, scaled per D4c.

    Composes two independent operations on `cost_per_km`:
    `to_canonical(1)` converts the per-canonical-km rate to
    per-typed-distance-unit (the same factor recovery
    `_format_cost_per_volume_side` uses), then the adapter's own
    presentation scale (`_COST_PER_DISTANCE_SCALE`) re-expands that from
    "per 1 [km|mi]" to "per 100 km" or "per 1,000 mi" so the printed number
    is a normal magnitude instead of a fraction of a cent.
    """
    factor = adapter.to_canonical(Decimal("1"))
    if factor is None:
        return "N/A"
    scale = _COST_PER_DISTANCE_SCALE[adapter.unit]
    cost_per_scale = cost_per_km * factor * scale
    return f"{symbol}{cost_per_scale:,.{_CURRENCY_PRECISION}f}/{scale:,.0f} {adapter.label}"


def format_cost_per_distance(
    cost_per_km: Decimal | None,
    ctx: RenderContext,
    currency_code: str | None,
    locale: str | None = "en-US",
) -> str:
    """Render a cost-per-distance rate (canonical currency units per km).

    D4c: flips distance and its presentation scale together -- a km reader
    always gets `"/100 km"`, a mile reader always gets `"/1,000 mi"`, never
    a mismatched pairing. Returns `"N/A"` for a `None` input, with no
    counterpart.
    """
    if cost_per_km is None:
        return "N/A"
    symbol = get_currency_symbol(currency_code, locale)
    primary_adapter = adapter_for(ctx.units, "distance")
    primary = _format_cost_per_distance_side(cost_per_km, primary_adapter, symbol)
    if not ctx.show_both:
        return primary
    counterpart_adapter = counterpart_for(ctx.units, "distance")
    if counterpart_adapter is None:
        return primary
    counterpart = _format_cost_per_distance_side(cost_per_km, counterpart_adapter, symbol)
    return f"{primary} ({counterpart})"


def _format_volume_per_distance_side(
    l_per_1000_km: Decimal, volume_adapter: UnitAdapter, distance_adapter: UnitAdapter
) -> str:
    """One side of a volume-per-distance representation, scaled per D4c.

    `l_per_1000_km` is already "canonical litres per 1,000 canonical km"
    (R5: the function this feeds is named for that scale on purpose -- a
    bare `l_per_km` signature invites a 1,000x error at every call site).
    Dividing by `PER_1000_KM` first recovers the per-single-canonical-km
    rate; that divisor is `PER_1000_KM` regardless of which distance unit
    ends up being *displayed*, because the CANONICAL denominator is always
    km. From there, `volume_adapter.to_display` converts the numerator the
    same way `unit_formatting.py` converts a simple quantity;
    `distance_adapter.to_canonical(1)` recovers that adapter's own factor
    exactly as the cost functions above do for their denominator; and the
    distance adapter's own presentation scale
    (`_VOLUME_PER_DISTANCE_SCALE`) re-expands the result to "per 1,000
    [km|mi]" for display.
    """
    per_canonical_km = l_per_1000_km / PER_1000_KM
    per_typed_numerator = volume_adapter.to_display(per_canonical_km)
    if per_typed_numerator is None:
        return "N/A"
    denominator_factor = distance_adapter.to_canonical(Decimal("1"))
    if denominator_factor is None:
        return "N/A"
    scale = _VOLUME_PER_DISTANCE_SCALE[distance_adapter.unit]
    displayed = per_typed_numerator * denominator_factor * scale
    precision = volume_adapter.precision
    return (
        f"{displayed:,.{precision}f} {volume_adapter.label}/{scale:,.0f} {distance_adapter.label}"
    )


def format_volume_per_1000_distance(l_per_1000_km: Decimal | None, ctx: RenderContext) -> str:
    """Render a volume-per-distance rate: canonical litres per 1,000 canonical km.

    R5: named for its input scale on purpose -- the live presentation is
    per 1,000 km or 1,000 mi, and a bare `l_per_km` signature invites a
    1,000x error. D4c: flips BOTH numerator and denominator, composing each
    counterpart's adapter independently -- not "flip one side, hold the
    other". Returns `"N/A"` for a `None` input, with no counterpart.

    NOT DEAD CODE: no `app/` caller yet. R5's per-1,000 presentation lives in
    the frontend today (`frontend/src/utils/units.ts`); part B and the phase-3
    frontend work, both deferred out of phase 2a, are what move it onto this
    API. The backend has no reachability gate, so nothing else will tell you
    that.
    """
    if l_per_1000_km is None:
        return "N/A"
    primary_volume = adapter_for(ctx.units, "volume")
    primary_distance = adapter_for(ctx.units, "distance")
    primary = _format_volume_per_distance_side(l_per_1000_km, primary_volume, primary_distance)
    if not ctx.show_both:
        return primary
    counterpart_volume = counterpart_for(ctx.units, "volume")
    counterpart_distance = counterpart_for(ctx.units, "distance")
    if counterpart_volume is None or counterpart_distance is None:
        return primary
    counterpart = _format_volume_per_distance_side(
        l_per_1000_km, counterpart_volume, counterpart_distance
    )
    return f"{primary} ({counterpart})"
