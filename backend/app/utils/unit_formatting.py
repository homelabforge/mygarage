"""Formatting layer: turn a canonical `Decimal` into a human-readable string.

R4 (revised): this module, together with `render_context.py`, is the
formatting layer. It sits on top of the conversion layer
(`unit_adapters.py`'s `adapter_for`, `unit_counterparts.py`'s
`counterpart_for`) and is the first place the show-both grammar (a primary
representation, optionally followed by its counterpart in parentheses) is
actually assembled and rendered as a string. `unit_adapters.UnitAdapter.format`
is deliberately primitive -- one representation, no context -- specifically so
that composition lives here instead.

Every function below takes a `RenderContext` rather than a bare `UnitSet`,
because `show_both` is a per-render decision (whose it is depends on which of
`render_context_for_request` / `render_context_for_vehicle` /
`render_context_default` produced the context), not a property of the unit
set itself.

`format_quantity` and `format_rate` share one rule: **null short-circuits
before the counterpart**. When the canonical value is `None`, or the primary
conversion is undefined (a reciprocal adapter's zero), the result is exactly
`"N/A"` with no counterpart appended, `show_both` notwithstanding --
naively formatting both sides independently would otherwise produce
`"N/A (N/A)"`. The check is the primary adapter's own `to_display(canonical)`,
not a string comparison against `"N/A"`, so it cannot be fooled by a
coincidentally N/A-shaped label.

`format_forced_volume_pair` is not `format_quantity` with a flag: DEF
notifications (`app/services/notifications/dispatcher.py`) emit litres and
gallons **always**, independent of `show_both`, in a fixed litres-then-gallons
order, with the gallon flavour chosen by D4b precedence
(`_forced_gallon_token`) rather than `show_both`'s counterpart lookup.
"""

from __future__ import annotations

from decimal import Decimal

from app.constants.units import UnitSet
from app.utils.render_context import RenderContext
from app.utils.unit_adapters import ADAPTERS, adapter_for
from app.utils.unit_counterparts import counterpart_for


def _format_with_optional_counterpart(
    canonical: Decimal | None, ctx: RenderContext, quantity: str, suffix: str
) -> str:
    """Shared body of `format_quantity` and `format_rate`: format the
    primary, short-circuiting to `"N/A"` before any counterpart is
    considered, then append `" (counterpart)"` when `ctx.show_both` and a
    counterpart exists. `suffix` (empty for `format_quantity`) is appended to
    each representation independently, never to a completed composed string.
    """
    primary_adapter = adapter_for(ctx.units, quantity)
    if primary_adapter.to_display(canonical) is None:
        return "N/A"
    primary = f"{primary_adapter.format(canonical)}{suffix}"
    if not ctx.show_both:
        return primary
    counterpart_adapter = counterpart_for(ctx.units, quantity)
    if counterpart_adapter is None:
        return primary
    return f"{primary} ({counterpart_adapter.format(canonical)}{suffix})"


def format_quantity(canonical: Decimal | None, ctx: RenderContext, quantity: str) -> str:
    """Render `canonical` as one of `ctx.units`'s quantities.

    `quantity` is a `UnitSet` field name (`"distance"`, `"pressure"`, ...),
    exactly as `adapter_for` expects it -- never `"hours"`, which is
    dimensionless and has no adapter (R6).

    Returns `"N/A"` when `canonical` is `None` or the primary conversion is
    undefined, with no counterpart. Otherwise returns the primary
    representation, followed by `" (counterpart)"` when `ctx.show_both` is
    `True` and a counterpart exists for this quantity.
    """
    return _format_with_optional_counterpart(canonical, ctx, quantity, suffix="")


def format_rate(canonical: Decimal | None, ctx: RenderContext, quantity: str, suffix: str) -> str:
    """Render `canonical` as a rate: `quantity` per `suffix`.

    `suffix` is appended to **each** representation independently
    (`"1,000 km/mo (621 mi/mo)"`), never to a completed show-both string
    (`"1,000 km (621 mi)/mo"`, which states neither rate correctly).

    Same null/undefined short-circuit as `format_quantity`: `"N/A"`, with no
    suffix and no counterpart, when the primary conversion is undefined.
    """
    return _format_with_optional_counterpart(canonical, ctx, quantity, suffix=suffix)


def format_label(ctx: RenderContext, quantity: str) -> str:
    """Return `ctx.units`'s primary adapter label for `quantity`, alone.

    Never parenthesised or composed with a counterpart, and unaffected by
    `ctx.show_both`: a table header names one column
    (`f"Odometer ({format_label(ctx, 'distance')})"`), and a header stating
    two units for one column would be a defect, not a feature.
    """
    return adapter_for(ctx.units, quantity).label


def _forced_gallon_token(units: UnitSet) -> str:
    """The gallon flavour a forced dual volume representation uses (D4b).

    A `gal_us`/`gal_uk` primary states its own flavour and wins outright,
    even when `secondary_gallon` disagrees. Only a litre primary, which has
    no gallon flavour of its own, defers to `secondary_gallon`.
    """
    if units.volume in ("gal_us", "gal_uk"):
        return units.volume
    return "gal_us" if units.secondary_gallon == "us" else "gal_uk"


def format_forced_volume_pair(canonical_l: Decimal | None, ctx: RenderContext) -> str:
    """Render `canonical_l` as a forced litres/gallons pair, e.g. `"2.50 L / 0.66 gal"`.

    Unlike `format_quantity`, this is unconditional on `ctx.show_both` and
    fixed-order (litres first): DEF notifications always emit both units.
    The gallon flavour follows D4b precedence (`_forced_gallon_token`), not
    `ctx.units`'s counterpart table. Returns `"N/A"` for a `None` input, with
    no pair, preserving the null short-circuit the other formatters use.
    """
    liters_adapter = ADAPTERS["L"]
    if liters_adapter.to_display(canonical_l) is None:
        return "N/A"
    gallons_adapter = ADAPTERS[_forced_gallon_token(ctx.units)]
    return f"{liters_adapter.format(canonical_l)} / {gallons_adapter.format(canonical_l)}"
