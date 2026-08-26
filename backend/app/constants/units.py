"""Unit vocabularies, presets, and the UnitSet model.

Data only. Nothing here reads a database, converts a value, or depends on a
request. The ten quantities are D1 of the custom-units spec; the eleventh field,
`secondary_gallon`, is D4b: it resolves which gallon a forced gallon-based
representation uses when the user's own primary unit does not say.

Column naming: the `users` table prefixes the ten quantity columns with `unit_`
so the table stays readable next to `unit_preference`. `secondary_gallon` is
unprefixed, matching the spec. `field_to_column` owns that asymmetry so no
caller has to remember it.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

DistanceUnit = Literal["km", "mi"]
SpeedUnit = Literal["kmh", "mph"]
LengthUnit = Literal["m", "ft"]
VolumeUnit = Literal["L", "gal_us", "gal_uk"]
ConsumptionUnit = Literal["l_100km", "km_l", "mpg_us", "mpg_uk"]
PressureUnit = Literal["kpa", "bar", "psi"]
TemperatureUnit = Literal["c", "f"]
MassUnit = Literal["kg", "lb"]
TorqueUnit = Literal["nm", "lbft"]
TreadUnit = Literal["mm", "in32"]

# D4b. Distinct from app.utils.units.GallonFlavour, which is the converter's
# argument type. This one is a stored preference.
GallonFlavourPref = Literal["us", "uk"]

# The base preset a user carries in users.unit_preference. `custom` is a UI
# affordance meaning "show me the ten selects" (D3), not a third preset: it
# resolves against the imperial base with all overrides materialised.
UnitPreference = Literal["imperial", "metric", "custom"]


class UnitSet(BaseModel):
    """A fully resolved set of unit choices. Every field is required.

    Frozen: a module-level preset that could be mutated in place would be
    process-global state, which is what phase 0 removed from the converter.

    extra="forbid": a stored default unit set carrying an unknown key means the
    writer and the reader disagree about the shape, and Pydantic's default of
    silently ignoring extras would hide that until something formatted a number
    wrongly. `default_unit_prefs` parsing depends on this.

    OBLIGATION: adding or removing a field must ship alongside a migration that
    rewrites every stored `default_unit_prefs` row, which holds a full dump of
    this model and stops validating the moment the arity changes. See
    `app.utils.default_unit_prefs.parse_default_unit_prefs` for what that
    silently costs a UK instance, and
    `test_unit_set_shape_matches_what_stored_default_unit_prefs_rows_carry`,
    which fails until the migration lands.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    distance: DistanceUnit
    speed: SpeedUnit
    length: LengthUnit
    volume: VolumeUnit
    consumption: ConsumptionUnit
    pressure: PressureUnit
    temperature: TemperatureUnit
    mass: MassUnit
    torque: TorqueUnit
    tread: TreadUnit
    secondary_gallon: GallonFlavourPref


METRIC_PRESET = UnitSet(
    distance="km",
    speed="kmh",
    length="m",
    volume="L",
    consumption="l_100km",
    pressure="kpa",
    temperature="c",
    mass="kg",
    torque="nm",
    tread="mm",
    secondary_gallon="us",
)

IMPERIAL_PRESET = UnitSet(
    distance="mi",
    speed="mph",
    length="ft",
    volume="gal_us",
    consumption="mpg_us",
    pressure="psi",
    temperature="f",
    mass="lb",
    torque="lbft",
    tread="in32",
    secondary_gallon="us",
)

# Derived from UnitSet, never hand-written: a literal tuple here could drift
# from the model, and no test could catch the drift without duplicating the
# list a third time. Adding a quantity to UnitSet updates this automatically.
UNIT_FIELD_NAMES: tuple[str, ...] = tuple(UnitSet.model_fields)

_UNPREFIXED_FIELDS = frozenset({"secondary_gallon"})


def field_to_column(field: str) -> str:
    """Map a UnitSet field name to its `users` column name."""
    if field in _UNPREFIXED_FIELDS:
        return field
    return f"unit_{field}"


UNIT_COLUMN_NAMES: tuple[str, ...] = tuple(field_to_column(f) for f in UNIT_FIELD_NAMES)

# Longest vocabulary value across all eleven quantities, used to justify the
# VARCHAR(12) column width. Asserted by the test suite rather than trusted.
MAX_UNIT_VALUE_LENGTH = max(
    len(value) for field in UnitSet.model_fields.values() for value in get_args(field.annotation)
)
