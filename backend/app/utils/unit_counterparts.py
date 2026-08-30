"""Counterpart table: which adapter accompanies a primary when showing both.

`show_both_units` (D-series decisions, custom-units design spec, "Phase 2")
pairs a user's primary unit for a quantity with one counterpart unit. This
module is a static lookup, not a rule: the binding table lives in
`2026-08-25-custom-units-design.md` under "Phase 2" (the `| Primary |
Counterpart |` table) and is encoded here verbatim.

**Not symmetric.** `bar` and `kpa` both counterpart to `psi`, but `psi`
counterparts to `kpa`, never `bar`. `l_100km` and `km_l` both counterpart to
an MPG flavour, but `mpg_us`/`mpg_uk` counterpart to `l_100km`, never `km_l`.
Do not "fix" this into a symmetric table; the asymmetry is the spec.

**D4b: two rows consult `unit_set.secondary_gallon`.** A litre primary's
counterpart gallon, and a metric-consumption primary's counterpart MPG, both
have no flavour of their own, so `secondary_gallon` supplies one. Every other
row is fixed and ignores `secondary_gallon` entirely, including the reverse
direction: a `gal_us`/`gal_uk` primary's counterpart is always `L`, and an
`mpg_us`/`mpg_uk` primary's counterpart is always `l_100km`, regardless of
`secondary_gallon`, because those primaries already state their own flavour.
This is why `counterpart_for` takes the whole `UnitSet` rather than a bare
token: the counterpart of `L` cannot be derived from `L` alone.

No entry in this table points a token at itself; a self-referencing entry
would render the same number twice under show-both and look correct while
being useless.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.constants.units import GallonFlavourPref, UnitSet
from app.utils.unit_adapters import ADAPTERS, UnitAdapter

# Every primary token whose counterpart is fixed regardless of
# `secondary_gallon`. Covers all 24 vocabulary tokens except `L`, `l_100km`
# and `km_l`, which are resolved separately below because their counterpart's
# gallon flavour is not derivable from the token itself (D4b).
_FIXED_COUNTERPARTS: Mapping[str, str] = {
    "km": "mi",
    "mi": "km",
    "kmh": "mph",
    "mph": "kmh",
    "m": "ft",
    "ft": "m",
    "gal_us": "L",
    "gal_uk": "L",
    "mpg_us": "l_100km",
    "mpg_uk": "l_100km",
    "kpa": "psi",
    "bar": "psi",
    "psi": "kpa",
    "c": "f",
    "f": "c",
    "kg": "lb",
    "lb": "kg",
    "nm": "lbft",
    "lbft": "nm",
    "mm": "in32",
    "in32": "mm",
}

# D4b: `L`'s counterpart gallon, chosen by `secondary_gallon`.
_VOLUME_COUNTERPART_BY_FLAVOUR: Mapping[GallonFlavourPref, str] = {
    "us": "gal_us",
    "uk": "gal_uk",
}

# D4b: `l_100km` and `km_l` share the same counterpart resolution, chosen by
# `secondary_gallon`. `mpg_us`/`mpg_uk` are NOT in this set: their counterpart
# is the fixed `l_100km` row above, not each other.
_CONSUMPTION_TOKENS_NEEDING_FLAVOUR = frozenset({"l_100km", "km_l"})
_CONSUMPTION_COUNTERPART_BY_FLAVOUR: Mapping[GallonFlavourPref, str] = {
    "us": "mpg_us",
    "uk": "mpg_uk",
}

# The flavour-explicit MPG tokens, derived from the table above rather than
# written out again, so a third gallon flavour cannot be added to one and
# forgotten in the other.
_MPG_TOKENS = frozenset(_CONSUMPTION_COUNTERPART_BY_FLAVOUR.values())


def counterpart_for(unit_set: UnitSet, quantity: str) -> UnitAdapter | None:
    """Resolve the show-both counterpart adapter for one of `unit_set`'s quantities.

    `quantity` is a `UnitSet` field name (`"distance"`, `"pressure"`, ...),
    exactly as `adapter_for` (`app.utils.unit_adapters`) expects it. Raises
    `KeyError` for a name that is not a `UnitSet` field at all, matching
    `adapter_for`'s behaviour so the two entry points fail the same way.

    The counterpart of a litre primary depends on `unit_set.secondary_gallon`
    (D4b), so the whole `UnitSet` is required, never a bare token.
    """
    if quantity not in UnitSet.model_fields:
        raise KeyError(quantity)
    token = getattr(unit_set, quantity)
    if token == "L":
        counterpart_token = _VOLUME_COUNTERPART_BY_FLAVOUR[unit_set.secondary_gallon]
    elif token in _CONSUMPTION_TOKENS_NEEDING_FLAVOUR:
        counterpart_token = _CONSUMPTION_COUNTERPART_BY_FLAVOUR[unit_set.secondary_gallon]
    else:
        counterpart_token = _FIXED_COUNTERPARTS[token]
    return ADAPTERS.get(counterpart_token)


def forced_mpg_adapter(unit_set: UnitSet) -> UnitAdapter:
    """Resolve the MPG adapter for a surface whose field is MPG by contract.

    Some response fields name their unit and cannot change it. Widget v1/v2
    expose `recent_mpg`/`average_mpg`, frozen by D7, so the quantity stays MPG
    whatever the owner's `consumption` primary is; only the gallon FLAVOUR is
    a preference. That makes this a different question from `counterpart_for`,
    which would hand an `mpg_us` primary its `l_100km` counterpart.

    D4b precedence, the same rule `unit_formatting._forced_gallon_token`
    applies to a forced volume pair: an `mpg_us`/`mpg_uk` primary states its
    own flavour and wins outright even when `secondary_gallon` disagrees, and
    only a flavourless metric primary (`l_100km`, `km_l`) defers to
    `secondary_gallon`.

    Conversion layer, not formatting (R4): this returns an adapter, so the
    caller keeps a `Decimal` and its numeric schema.
    """
    if unit_set.consumption in _MPG_TOKENS:
        return ADAPTERS[unit_set.consumption]
    return ADAPTERS[_CONSUMPTION_COUNTERPART_BY_FLAVOUR[unit_set.secondary_gallon]]
