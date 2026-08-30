"""Counterpart table: asymmetric by design, D4b-flavoured, no self-reference.

Every literal expected value below traces to the `| Primary | Counterpart |`
table in `2026-08-25-custom-units-design.md` under "Phase 2", read directly
(not reconstructed from what looks symmetric, and not assumed from what a
prior round guessed).
"""

from __future__ import annotations

from typing import get_args

import pytest

from app.constants.units import METRIC_PRESET, UnitSet
from app.utils.unit_counterparts import counterpart_for


def _build_unit_set(quantity: str, token: str, *, secondary_gallon: str = "us") -> UnitSet:
    """A `UnitSet` with `quantity` set to `token`, every other field at the
    metric preset. `UnitSet` fields have no cross-field constraint, so this
    is a valid combination for any quantity/token/flavour triple."""
    overrides = {quantity: token, "secondary_gallon": secondary_gallon}
    return UnitSet.model_validate(METRIC_PRESET.model_dump() | overrides)


# One literal case per primary token whose counterpart does NOT depend on
# `secondary_gallon` -- 21 of the 24 vocabulary tokens. Asymmetric rows
# included on purpose: `kpa` and `bar` both point at `psi`, but `psi` points
# back at `kpa`, never `bar`.
FIXED_CASES: list[tuple[str, str, str]] = [
    ("distance", "km", "mi"),
    ("distance", "mi", "km"),
    ("speed", "kmh", "mph"),
    ("speed", "mph", "kmh"),
    ("length", "m", "ft"),
    ("length", "ft", "m"),
    ("volume", "gal_us", "L"),
    ("volume", "gal_uk", "L"),
    ("consumption", "mpg_us", "l_100km"),
    ("consumption", "mpg_uk", "l_100km"),
    ("pressure", "kpa", "psi"),
    ("pressure", "bar", "psi"),
    ("pressure", "psi", "kpa"),
    ("temperature", "c", "f"),
    ("temperature", "f", "c"),
    ("mass", "kg", "lb"),
    ("mass", "lb", "kg"),
    ("torque", "nm", "lbft"),
    ("torque", "lbft", "nm"),
    ("tread", "mm", "in32"),
    ("tread", "in32", "mm"),
]

# The three primary tokens whose counterpart is chosen by `secondary_gallon`
# (D4b): one literal case per (token, flavour) pair. `km_l` counterparts to
# an MPG flavour just like `l_100km` does; only the reverse direction
# (`mpg_us`/`mpg_uk` -> `l_100km`, in FIXED_CASES) is fixed.
GALLON_FLAVOURED_CASES: list[tuple[str, str, str, str]] = [
    ("volume", "L", "us", "gal_us"),
    ("volume", "L", "uk", "gal_uk"),
    ("consumption", "l_100km", "us", "mpg_us"),
    ("consumption", "l_100km", "uk", "mpg_uk"),
    ("consumption", "km_l", "us", "mpg_us"),
    ("consumption", "km_l", "uk", "mpg_uk"),
]


class TestTableCoverage:
    def test_every_vocabulary_token_appears_exactly_once_as_a_primary(self) -> None:
        """FIXED_CASES plus GALLON_FLAVOURED_CASES's distinct primary tokens
        must equal exactly the 24-token vocabulary, with none repeated and
        none missing -- guards against silently dropping an asymmetric row."""
        fixed_tokens = [token for _, token, _ in FIXED_CASES]
        flavoured_tokens = {token for _, token, _, _ in GALLON_FLAVOURED_CASES}
        all_tokens = fixed_tokens + sorted(flavoured_tokens)
        assert len(fixed_tokens) == len(set(fixed_tokens)), "a fixed-case token is duplicated"
        assert len(all_tokens) == 24, f"expected 24 distinct primary tokens, got {len(all_tokens)}"

        vocabulary: set[str] = set()
        for name, field in UnitSet.model_fields.items():
            if name == "secondary_gallon":
                continue
            vocabulary.update(get_args(field.annotation))
        assert set(all_tokens) == vocabulary


class TestFixedCounterparts:
    """21 of the 24 vocabulary tokens: fixed counterpart, independent of
    `secondary_gallon`."""

    @pytest.mark.parametrize(("quantity", "token", "expected"), FIXED_CASES)
    def test_fixed_case(self, quantity: str, token: str, expected: str) -> None:
        unit_set = _build_unit_set(quantity, token)
        result = counterpart_for(unit_set, quantity)
        assert result is not None
        assert result.unit == expected


class TestGallonFlavouredCounterparts:
    """D4b: `L`, `l_100km` and `km_l` consult `unit_set.secondary_gallon`."""

    @pytest.mark.parametrize(
        ("quantity", "token", "secondary_gallon", "expected"), GALLON_FLAVOURED_CASES
    )
    def test_flavoured_case(
        self, quantity: str, token: str, secondary_gallon: str, expected: str
    ) -> None:
        unit_set = _build_unit_set(quantity, token, secondary_gallon=secondary_gallon)
        result = counterpart_for(unit_set, quantity)
        assert result is not None
        assert result.unit == expected


class TestSecondaryGallonDoesNotAffectAFlavouredPrimary:
    """A primary that already states its own gallon flavour must ignore
    `secondary_gallon` entirely. Both conflict directions are tested --
    two settings that happen to agree would prove nothing."""

    @pytest.mark.parametrize("secondary_gallon", ["us", "uk"])
    def test_gal_us_primary_counterpart_is_always_l(self, secondary_gallon: str) -> None:
        unit_set = _build_unit_set("volume", "gal_us", secondary_gallon=secondary_gallon)
        result = counterpart_for(unit_set, "volume")
        assert result is not None
        assert result.unit == "L"

    @pytest.mark.parametrize("secondary_gallon", ["us", "uk"])
    def test_gal_uk_primary_counterpart_is_always_l(self, secondary_gallon: str) -> None:
        unit_set = _build_unit_set("volume", "gal_uk", secondary_gallon=secondary_gallon)
        result = counterpart_for(unit_set, "volume")
        assert result is not None
        assert result.unit == "L"

    @pytest.mark.parametrize("secondary_gallon", ["us", "uk"])
    def test_mpg_us_primary_counterpart_is_always_l100km(self, secondary_gallon: str) -> None:
        unit_set = _build_unit_set("consumption", "mpg_us", secondary_gallon=secondary_gallon)
        result = counterpart_for(unit_set, "consumption")
        assert result is not None
        assert result.unit == "l_100km"

    @pytest.mark.parametrize("secondary_gallon", ["us", "uk"])
    def test_mpg_uk_primary_counterpart_is_always_l100km(self, secondary_gallon: str) -> None:
        unit_set = _build_unit_set("consumption", "mpg_uk", secondary_gallon=secondary_gallon)
        result = counterpart_for(unit_set, "consumption")
        assert result is not None
        assert result.unit == "l_100km"


class TestNoSelfReference:
    def test_no_counterpart_equals_its_own_primary(self) -> None:
        """Every valid (quantity, token, secondary_gallon) combination, not a
        sample: a self-referencing entry would render the same number twice
        under show-both and look like a working display."""
        offenders: list[str] = []
        checked = 0
        for quantity, field in UnitSet.model_fields.items():
            if quantity == "secondary_gallon":
                continue
            for token in get_args(field.annotation):
                for secondary_gallon in ("us", "uk"):
                    checked += 1
                    unit_set = _build_unit_set(quantity, token, secondary_gallon=secondary_gallon)
                    result = counterpart_for(unit_set, quantity)
                    assert result is not None
                    if result.unit == token:
                        offenders.append(
                            f"{quantity}={token} (secondary_gallon={secondary_gallon})"
                        )
        assert checked == 48, (
            f"expected 24 tokens x 2 flavours = 48 combinations, checked {checked}"
        )
        assert offenders == []


class TestUnknownQuantity:
    def test_unknown_quantity_raises(self) -> None:
        with pytest.raises(KeyError):
            counterpart_for(METRIC_PRESET, "not_a_quantity")

    def test_hours_is_not_a_unit_quantity(self) -> None:
        """R6 parity with `adapter_for`: `due_hours` is dimensionless and has
        no adapter, so it has no counterpart either."""
        with pytest.raises(KeyError):
            counterpart_for(METRIC_PRESET, "hours")


class TestUnitSetPrecedenceOverBareToken:
    """`counterpart_for` takes the whole `UnitSet`, never a bare token (D4b):
    the same primary token (`L`) resolves to a different counterpart purely
    because of a field elsewhere on the set."""

    def test_same_primary_token_different_secondary_gallon_different_counterpart(self) -> None:
        us_set = _build_unit_set("volume", "L", secondary_gallon="us")
        uk_set = _build_unit_set("volume", "L", secondary_gallon="uk")
        us_result = counterpart_for(us_set, "volume")
        uk_result = counterpart_for(uk_set, "volume")
        assert us_result is not None
        assert uk_result is not None
        assert us_result.unit == "gal_us"
        assert uk_result.unit == "gal_uk"
        assert us_result.unit != uk_result.unit
