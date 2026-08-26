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
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import (
    IMPERIAL_PRESET,
    METRIC_PRESET,
    UNIT_FIELD_NAMES,
    UnitSet,
    field_to_column,
)
from app.utils.default_unit_prefs import load_default_unit_prefs

logger = logging.getLogger(__name__)


class UnitPreferenceSource(Protocol):
    """The twelve attributes `resolve_units` reads.

    A Protocol rather than the ORM `User`, for two reasons. `UserResponse` calls
    `resolve_units(self)` from a computed field and is not a `User`, so a
    concrete model annotation would be a type error at that call site. And
    importing `app.models.user` here while `app.schemas.user` imports this
    module is a cycle waiting to happen. Both the ORM model and the response
    schema satisfy this structurally, with no import in either direction.

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
