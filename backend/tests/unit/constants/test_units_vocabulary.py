"""Vocabulary, preset, and column-name integrity for the custom unit system.

These are ties, not round-trips: each test fails if two things that must agree
stop agreeing. See the spec's Testing section.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.constants.units import (
    IMPERIAL_PRESET,
    MAX_UNIT_VALUE_LENGTH,
    METRIC_PRESET,
    UNIT_COLUMN_NAMES,
    UnitSet,
    field_to_column,
)

# The number of quantities every `default_unit_prefs` settings row in the wild
# was written with. Hand-written on purpose: this pins what is ALREADY STORED,
# so it must not be derived from UnitSet, which is what changes.
STORED_UNIT_SET_FIELD_COUNT = 11


class TestUnitSetShape:
    """UnitSet is the single definition of what a unit set contains."""

    def test_unit_set_shape_matches_what_stored_default_unit_prefs_rows_carry(self) -> None:
        assert len(UnitSet.model_fields) == STORED_UNIT_SET_FIELD_COUNT, (
            "UnitSet has changed shape. Changing it obliges you to ship a "
            "migration that REWRITES every existing `default_unit_prefs` "
            "settings row, and to update STORED_UNIT_SET_FIELD_COUNT above.\n\n"
            "Why: migration 093 and initialize_default_settings store that row "
            "as a full dump of UnitSet, so rows already written carry exactly "
            f"{STORED_UNIT_SET_FIELD_COUNT} keys. UnitSet is all-required with "
            "extra='forbid', so those rows stop validating the moment a field "
            "is added or removed, and parse_default_unit_prefs falls back to "
            "IMPERIAL_PRESET as a WHOLE SET (deliberately: patching gaps from "
            "the imperial preset would hand a metric instance imperial "
            "pressure).\n\n"
            "The failure mode that produces, behind a single WARNING log: on a "
            "UK instance every anonymous client and every NEW ACCOUNT silently "
            "reverts to US gallons. default_unit_prefs_for_instance cannot "
            "repair it, because it only fires when the row is absent, and the "
            "row is present-but-stale."
        )

    def test_every_field_is_required(self) -> None:
        """A default would let a partially-specified set masquerade as complete."""
        optional = [n for n, f in UnitSet.model_fields.items() if not f.is_required()]
        assert optional == []


class TestPresets:
    """The two preset rows, enumerated verbatim from the spec's Phase 1 table."""

    def test_metric_preset_values(self) -> None:
        assert METRIC_PRESET.model_dump() == {
            "distance": "km",
            "speed": "kmh",
            "length": "m",
            "volume": "L",
            "consumption": "l_100km",
            "pressure": "kpa",
            "temperature": "c",
            "mass": "kg",
            "torque": "nm",
            "tread": "mm",
            "secondary_gallon": "us",
        }

    def test_imperial_preset_values(self) -> None:
        assert IMPERIAL_PRESET.model_dump() == {
            "distance": "mi",
            "speed": "mph",
            "length": "ft",
            "volume": "gal_us",
            "consumption": "mpg_us",
            "pressure": "psi",
            "temperature": "f",
            "mass": "lb",
            "torque": "lbft",
            "tread": "in32",
            "secondary_gallon": "us",
        }

    def test_presets_differ_in_every_field_except_secondary_gallon(self) -> None:
        """D4b: secondary_gallon is the one field the presets agree on, which is
        why the UK migration and default_unit_prefs can move it independently."""
        metric = METRIC_PRESET.model_dump()
        imperial = IMPERIAL_PRESET.model_dump()
        agreeing = [k for k in metric if metric[k] == imperial[k]]
        assert agreeing == ["secondary_gallon"]

    def test_presets_are_frozen_instances(self) -> None:
        """A mutable module-level preset is process-global state, which is the
        exact defect phase 0 spent fifteen commits removing."""
        with pytest.raises(ValidationError):
            METRIC_PRESET.distance = "mi"  # type: ignore[misc]


class TestColumnNameMapping:
    """users columns carry a unit_ prefix; UnitSet fields do not."""

    def test_the_ten_quantity_columns_carry_the_unit_prefix(self) -> None:
        """The secondary_gallon exception below still passes if the prefix
        vanishes from every other field, because it only checks the one field
        that never carries it. Task 2's migration adds columns by these exact
        names, so the prefix is a contract and needs its own guard."""
        prefixed = [name for name in UNIT_COLUMN_NAMES if name.startswith("unit_")]

        assert len(prefixed) == 10
        assert set(UNIT_COLUMN_NAMES) - set(prefixed) == {"secondary_gallon"}

    def test_secondary_gallon_column_is_unprefixed(self) -> None:
        """The spec names this column secondary_gallon, not unit_secondary_gallon."""
        assert field_to_column("secondary_gallon") == "secondary_gallon"
        assert "secondary_gallon" in UNIT_COLUMN_NAMES
        assert "unit_secondary_gallon" not in UNIT_COLUMN_NAMES

    def test_every_column_fits_varchar_12(self) -> None:
        """PostgreSQL enforces VARCHAR length; SQLite does not, so an over-long
        vocabulary value only fails in CI. Guard it here instead."""
        from typing import get_args

        for field_name, field in UnitSet.model_fields.items():
            values = get_args(field.annotation)
            assert values, f"{field_name} is not a Literal; the width check sees nothing"
            for value in values:
                assert len(value) <= 12, f"{field_name}={value!r} exceeds VARCHAR(12)"

        # Task 2's PostgreSQL test asserts a VARCHAR(12) column against this
        # constant, so the constant itself has to fit. (An assertion that
        # MAX_UNIT_VALUE_LENGTH equals the max of the same generator that
        # defines it used to sit here; it recomputed the definition and could
        # not fail. The loop above is what has teeth.)
        assert MAX_UNIT_VALUE_LENGTH <= 12

    def test_unit_set_rejects_unknown_keys(self) -> None:
        """A stored set carrying an extra key means writer and reader disagree
        about the shape. Silently ignoring it surfaces later as a wrong number."""
        with pytest.raises(ValidationError):
            UnitSet.model_validate(METRIC_PRESET.model_dump() | {"unit_pressure": "kpa"})
