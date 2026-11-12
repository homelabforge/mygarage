"""Pydantic schemas for built-in reminder packs.

Pack format v2 (v3.5.0): an item declares a canonical ``maintenance_type``
and INTERVALS (``interval_km``, ``interval_months``, ``interval_days``,
``interval_hours``); applying a pack creates a per-vehicle rule from them.
The v1 keys (``due_mileage_km``, ``due_date_offset_days``, ``due_hours``,
``reminder_type``) are still accepted: the first three as aliases of the
interval fields, the last ignored, so a pack written for v3.4 still loads.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated

from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas._figures import to_stored_positive_tenth
from app.schemas.maintenance import (
    AnchorChoice,
    IntervalOverride,
    validate_maintenance_type,
)
from app.schemas.vehicle import VehicleType

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """A key for a pack item that declares none: 'Oil & Filter Change' -> 'oil_filter_change'."""
    slug = _SLUG_RE.sub("_", title.lower()).strip("_")
    return slug[:64] or "item"


#: Every saved pack's id starts with this. A built-in pack's id is its filename,
#: so the prefix makes a collision impossible rather than something to check, and
#: it tells `get_pack` which side to look on without a fallthrough.
CUSTOM_PREFIX = "custom-"

#: `vehicle_maintenance_rules.source_pack_id` is VARCHAR(64), and a truncated id
#: there would break the "which pack did this rule come from" link, so the slug
#: has to leave room for the prefix.
CUSTOM_SLUG_MAX = 64 - len(CUSTOM_PREFIX)


def pack_slug(name: str) -> str:
    """The slug part of a saved pack's id, or "" when the name has no letters.

    Hyphens rather than the underscores `slugify` uses, because this is an id in
    a URL path, and trimmed to `CUSTOM_SLUG_MAX` so `custom-` plus this fits the
    column that records it on a rule. An empty result is the caller's problem to
    report: a name of pure punctuation must be a 422, not a pack whose id is
    `custom-`.
    """
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-")[:CUSTOM_SLUG_MAX].strip("-")


def custom_pack_id(name: str) -> str:
    """The full `custom-<slug>` id for a name, or "" when the name has no slug."""
    slug = pack_slug(name)
    return f"{CUSTOM_PREFIX}{slug}" if slug else ""


def is_custom_pack_id(pack_id: str) -> bool:
    """Whether this id names a saved pack rather than a shipped file."""
    return pack_id.startswith(CUSTOM_PREFIX)


def usable_pack_name(value: str) -> str:
    """A pack name that survives stripping AND slugifying.

    The second half is the one worth a validator: "???" strips to something and
    slugifies to nothing, so its id would be bare `custom-`, which collides with
    the next such name and cannot be reached by id.

    A plain function attached per schema, the way the reminder and insurance
    schemas share their validators, so save and rename cannot drift apart.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("name must not be blank")
    if not pack_slug(stripped):
        raise ValueError("name must contain at least one letter or digit")
    return stripped


class ReminderPackItem(BaseModel):
    """A single maintenance rule template inside a pack."""

    title: str
    key: str | None = Field(default=None, max_length=64)
    maintenance_type: str | None = Field(default=None, max_length=50)
    interval_km: Decimal | None = Field(
        default=None, gt=0, validation_alias=AliasChoices("interval_km", "due_mileage_km")
    )
    interval_months: int | None = Field(default=None, gt=0)
    interval_days: int | None = Field(
        default=None, gt=0, validation_alias=AliasChoices("interval_days", "due_date_offset_days")
    )
    interval_hours: Annotated[Decimal | None, AfterValidator(to_stored_positive_tenth)] = Field(
        default=None, gt=0, validation_alias=AliasChoices("interval_hours", "due_hours")
    )
    #: v1 field, accepted and ignored: the type is derived from the intervals.
    reminder_type: str | None = None
    notes: str | None = None

    _validate_type = field_validator("maintenance_type")(validate_maintenance_type)

    @model_validator(mode="after")
    def fill_key_and_check_intervals(self) -> ReminderPackItem:
        """Every item has a key and at least one interval."""
        if self.key is None:
            self.key = self.maintenance_type or slugify(self.title)
        if (
            self.interval_km is None
            and self.interval_months is None
            and self.interval_days is None
            and self.interval_hours is None
        ):
            raise ValueError(f"pack item '{self.title}' declares no interval")
        if self.interval_km is not None and self.interval_hours is not None:
            raise ValueError(f"pack item '{self.title}' mixes distance and hours intervals")
        return self


class ReminderPackSummary(BaseModel):
    """Pack metadata returned by list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    reminder_count: int = Field(..., description="Number of reminders created when applied")
    vehicle_types: list[str] = Field(
        default_factory=list,
        description="Applicable vehicle types; empty means all types",
    )
    is_custom: bool = Field(
        default=False, description="Saved on this instance rather than shipped with the app"
    )
    can_edit: bool = Field(
        default=False,
        description="This caller may rename, overwrite or delete it; always false for built-ins",
    )


class ReminderPackDetail(BaseModel):
    """Full pack definition including reminder templates."""

    id: str
    name: str
    description: str
    reminders: list[ReminderPackItem]
    vehicle_types: list[str] = Field(
        default_factory=list,
        description="Applicable vehicle types; empty means all types",
    )


class ApplyReminderPackRequest(BaseModel):
    """Request body for applying (or previewing) a reminder pack on a vehicle.

    ``anchors`` maps a pack item key to the caller's anchor choice; an item
    not named keeps the preview's proposal.

    ``overrides`` maps a pack item key to intervals the caller typed, keyed the
    same way. An item not named keeps the pack's own intervals, so an untouched
    form sends nothing. An unknown key is a 422, the same answer ``anchors``
    gives.
    """

    pack_id: str = Field(..., min_length=1, max_length=100)
    anchors: dict[str, AnchorChoice | None] | None = None
    overrides: dict[str, IntervalOverride | None] | None = None


class SaveReminderPackRequest(BaseModel):
    """Save (or overwrite) a pack from one vehicle's maintenance rules.

    The rules named must be active and on `vin`, and each must be savable: the
    service refuses a typeless rule and the second rule of a repeated type,
    because the apply pipeline resolves an item to a rule by `maintenance_type`
    and would silently retype or collapse them. That check needs the database,
    so it lives in `reminder_pack_service`, not here.
    """

    vin: str = Field(
        ..., description="Vehicle to read the rules from", min_length=17, max_length=17
    )
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    vehicle_types: list[VehicleType] = Field(
        default_factory=list,
        description="Applicable vehicle types; empty means all types",
    )
    rule_ids: list[int] = Field(..., min_length=1, description="Maintenance rules to include")

    _validate_name = field_validator("name")(usable_pack_name)

    @field_validator("vehicle_types", "rule_ids")
    @classmethod
    def no_repeats(cls, value: list) -> list:
        """De-duplicate, keeping order. A repeated rule id would try to write the
        same item key twice and hit the UNIQUE mid-transaction."""
        return list(dict.fromkeys(value))


class RenameReminderPackRequest(BaseModel):
    """Rename a saved pack.

    Only the name. `pack_id` is deliberately immutable: rules record it in
    `source_pack_id`, so changing it would orphan the link from a rule back to
    the pack that made it.
    """

    name: str = Field(..., min_length=1, max_length=100)

    _validate_name = field_validator("name")(usable_pack_name)
