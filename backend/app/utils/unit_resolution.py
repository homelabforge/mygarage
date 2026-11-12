"""Resolve a user's effective unit set, and seed a new user's columns.

D3: ``unit_preference`` is the BASE preset; any non-null override column beats
it, regardless of which preset is set. ``custom`` is a UI affordance meaning
"show me the ten selects", not a distinct resolution mode, so it resolves the
same way everything else does.

``resolve_units`` is deliberately PURE and synchronous: ``UserResponse`` calls it
from a Pydantic computed field, which cannot await. If resolution ever needs the
database, that computed field has to change with it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Final, Protocol, cast

from pydantic import BeforeValidator, ValidationError, ValidationInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import (
    IMPERIAL_PRESET,
    METRIC_PRESET,
    UNIT_FIELD_NAMES,
    DistanceUnit,
    SpeedUnit,
    UnitSet,
    field_to_column,
)
from app.utils.default_unit_prefs import load_default_unit_prefs
from app.utils.lenient_vocab import LenientVocab
from app.utils.logging_utils import sanitize_for_log

if TYPE_CHECKING:
    from app.models.user import User

logger = logging.getLogger(__name__)


class UnitPreferenceShape(Protocol):
    """The twelve attributes `resolve_units` reads.

    A Protocol rather than the ORM `User`, for two reasons. `UserResponse` calls
    `resolve_units(self)` from a computed field and is not a `User`, so a
    concrete model annotation would be a type error at that call site. And
    importing `app.models.user` here while `app.schemas.user` imports this
    module is a cycle waiting to happen. The response schema satisfies this
    structurally; the ORM model needs the `UnitPreferenceSource` union below,
    because pyright won't read its Mapped columns as these properties.

    Read-only properties, not mutable attributes: a mutable protocol member is
    invariant, which would reject `UserResponse`'s narrower `Literal` fields.
    """

    @property
    def unit_preference(self) -> str | None: ...
    @property
    def unit_distance(self) -> str | None: ...
    @property
    def unit_speed(self) -> str | None: ...
    @property
    def unit_length(self) -> str | None: ...
    @property
    def unit_volume(self) -> str | None: ...
    @property
    def unit_consumption(self) -> str | None: ...
    @property
    def unit_pressure(self) -> str | None: ...
    @property
    def unit_temperature(self) -> str | None: ...
    @property
    def unit_mass(self) -> str | None: ...
    @property
    def unit_torque(self) -> str | None: ...
    @property
    def unit_tread(self) -> str | None: ...
    @property
    def secondary_gallon(self) -> str | None: ...


# Pyright never applies a descriptor's __get__ when it matches a protocol, so an
# ORM model fails a protocol on its Mapped columns. The model goes in the union
# by name; it's a typing-only import, and the alias is only ever read by pyright.
type UnitPreferenceSource = User | UnitPreferenceShape


_PRESETS: dict[str, UnitSet] = {
    "metric": METRIC_PRESET,
    "imperial": IMPERIAL_PRESET,
}


def base_preset_for(unit_preference: str | None) -> UnitSet:
    """Return the base preset for a stored ``unit_preference`` value.

    Anything that is not ``metric`` resolves to the imperial preset, including
    ``custom``, NULL, and any unrecognised value. A materialised ``custom`` user
    never reaches the base because every field is overridden; the fallback
    matters only for a half-written row, where imperial keeps behaviour
    identical to the historical default instead of silently flipping to metric.
    """
    return _PRESETS.get(unit_preference or "", IMPERIAL_PRESET)


def resolve_units(user: UnitPreferenceSource) -> UnitSet:
    """Return the user's effective unit set: preset base, overrides on top.

    An override that is not in its quantity's vocabulary is discarded and the
    preset value kept. The columns carry no database CHECK, so a hand-edited
    value would otherwise produce an invalid ``UnitSet`` that every downstream
    formatter has to defend against.
    """
    values = base_preset_for(user.unit_preference).model_dump()
    overrides = {field: getattr(user, field_to_column(field), None) for field in UNIT_FIELD_NAMES}
    candidate = values | {f: v for f, v in overrides.items() if v is not None}
    try:
        return UnitSet.model_validate(candidate)
    except ValidationError:
        pass

    # One bad column must not discard the other ten. Re-apply field by field.
    resolved = values
    for field, value in overrides.items():
        if value is None:
            continue
        try:
            resolved = UnitSet.model_validate(resolved | {field: value}).model_dump()
        except ValidationError:
            logger.warning(
                "Discarding out-of-vocabulary unit override %s=%r for user id=%s",
                field_to_column(field),
                value,
                getattr(user, "id", None),
            )
    return UnitSet.model_validate(resolved)


def initial_unit_columns(default_set: UnitSet) -> dict[str, str | None]:
    """Return the ``User`` unit columns for a new account.

    When the instance default matches a preset exactly, store that preset with
    eleven null overrides, so ordinary instances keep clean preset accounts.
    Otherwise store ``custom`` with all eleven materialised: a new account on a
    formerly UK-default instance that inherited only ``unit_preference`` would
    silently get US gallons, which is the same class of bug being fixed here.
    """
    for name, preset in _PRESETS.items():
        if default_set == preset:
            return {"unit_preference": name} | {
                field_to_column(field): None for field in UNIT_FIELD_NAMES
            }
    return {"unit_preference": "custom"} | {
        field_to_column(field): value for field, value in default_set.model_dump().items()
    }


async def new_user_unit_kwargs(db: AsyncSession) -> dict[str, str | None]:
    """Return ``User(...)`` keyword arguments seeding a new account's units.

    Every user-creation path calls this: local registration, admin creation, and
    OIDC provisioning. Splat it into the ``User(...)`` constructor rather than
    assigning afterwards, so no path can half-apply it.
    """
    return initial_unit_columns(await load_default_unit_prefs(db))


SPEED_FOR_DISTANCE: Final[dict[str, SpeedUnit]] = {"km": "kmh", "mi": "mph"}
"""The speed that goes with an odometer unit: one cluster, one unit (#172 D3)."""

# (vin, value) pairs already warned about, so a bad row logs once per process
# rather than once per serialisation (every dashboard load would repeat it),
# and a second vehicle with the same bad value still gets its own line.
_warned_distance_units: set[tuple[str | None, str]] = set()


def normalise_distance_unit(value: object, *, vin: str | None = None) -> DistanceUnit | None:
    """A vehicle's stored odometer unit, or None for unset or unusable.

    `vehicles.distance_unit` has no CHECK, like the eleven user unit columns,
    so a hand-edited row can hold anything. Anything outside the vocabulary is
    treated as unset ("Account default") rather than failing a response.
    """
    if value is None:
        return None
    if isinstance(value, str) and value in SPEED_FOR_DISTANCE:
        return cast(DistanceUnit, value)
    key = (vin, repr(value))
    if key not in _warned_distance_units:
        _warned_distance_units.add(key)
        logger.warning(
            "Ignoring out-of-vocabulary vehicles.distance_unit %s (vin=%s)",
            sanitize_for_log(key[1]),
            sanitize_for_log(vin),
        )
    return None


def apply_vehicle_units(
    units: UnitSet, distance_unit: object, *, vin: str | None = None
) -> UnitSet:
    """The units one vehicle's numbers render in (#172).

    The viewer's set with the vehicle's odometer unit, and the speed that goes
    with it, laid on top. Every other quantity, rates with a distance in the
    denominator included, stays the viewer's. Returns `units` itself when the
    vehicle has no usable unit, so an Account-default vehicle is untouched.
    """
    unit = normalise_distance_unit(distance_unit, vin=vin)
    if unit is None:
        return units
    return UnitSet.model_validate(
        units.model_dump() | {"distance": unit, "speed": SPEED_FOR_DISTANCE[unit]}
    )


def _lenient_distance_unit(value: object, info: ValidationInfo) -> DistanceUnit | None:
    """Field validator for a response's `distance_unit`, naming the vehicle.

    A FIELD validator, not a model validator: a model validator handed an ORM
    row (`from_attributes`) could only normalise by writing to the row, which
    the session would then persist. `info.data` holds the fields validated so
    far, so the payloads that declare `vin` / `vehicle_vin` first get it;
    `VehicleResponse` declares `vin` after `VehicleBase`'s fields and logs
    `vin=<none>` once, while its render-context and payload paths name it.
    """
    vin = info.data.get("vin") or info.data.get("vehicle_vin")
    return normalise_distance_unit(value, vin=vin if isinstance(vin, str) else None)


# Keeps its own validator rather than lenient_reader's, because this one names
# the VIN. The marker is what the response contract test looks for.
LenientDistanceUnit = Annotated[
    DistanceUnit | None, BeforeValidator(_lenient_distance_unit), LenientVocab(None)
]
"""A response field carrying a vehicle's `distance_unit`: bad stored values serve as null."""
