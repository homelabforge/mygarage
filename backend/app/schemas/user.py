"""User schemas for authentication."""

# pyright: reportArgumentType=error
# Project-wide reportArgumentType is "none" (184 FastAPI Depends() hits,
# see pyproject.toml). That suppression would also hide a broken
# UnitPreferenceSource conformance at the resolve_units(self) call below,
# so it is re-enabled for this one file, where that call site lives.

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

from app.constants.accents import SUPPORTED_ACCENTS
from app.constants.fuel import PAYMENT_METHOD_VALUES, TRIP_TYPE_VALUES
from app.constants.i18n import SUPPORTED_CURRENCIES, SUPPORTED_LANGUAGES
from app.constants.theme import SUPPORTED_THEMES
from app.constants.units import (
    UNIT_COLUMN_NAMES,
    ConsumptionUnit,
    DistanceUnit,
    GallonFlavourPref,
    LengthUnit,
    MassUnit,
    PressureUnit,
    SpeedUnit,
    TemperatureUnit,
    TorqueUnit,
    TreadUnit,
    UnitPreference,
    UnitSet,
    VolumeUnit,
    field_to_column,
)
from app.utils.unit_resolution import resolve_units

# The vocabulary each raw unit column accepts, keyed by column name (which is
# also the UserResponse field name). Derived from UnitSet so a twelfth quantity
# is covered without touching this file.
_UNIT_VOCABULARIES: dict[str, frozenset[str]] = {
    field_to_column(name): frozenset(get_args(field.annotation))
    for name, field in UnitSet.model_fields.items()
}

# unit_preference's own vocabulary. Not part of _UNIT_VOCABULARIES above: that
# dict is keyed by UnitSet's quantities (distance, pressure, ...), and
# unit_preference is not a quantity UnitSet resolves, it is the base preset
# selector that picks which UnitSet to start from.
_UNIT_PREFERENCE_VALUES: frozenset[str] = frozenset(get_args(UnitPreference))

# Relationship type presets for family system
RELATIONSHIP_PRESETS: list[dict[str, str]] = [
    {"value": "spouse", "label": "Spouse/Partner"},
    {"value": "child", "label": "Child"},
    {"value": "parent", "label": "Parent"},
    {"value": "sibling", "label": "Sibling"},
    {"value": "grandparent", "label": "Grandparent"},
    {"value": "grandchild", "label": "Grandchild"},
    {"value": "in_law", "label": "In-Law"},
    {"value": "friend", "label": "Friend"},
    {"value": "other", "label": "Other"},
]

# Valid relationship values for validation
VALID_RELATIONSHIPS = {preset["value"] for preset in RELATIONSHIP_PRESETS}

RelationshipType = Literal[
    "spouse",
    "child",
    "parent",
    "sibling",
    "grandparent",
    "grandchild",
    "in_law",
    "friend",
    "other",
    None,
]


class UserBase(BaseModel):
    """Base user schema."""

    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr = Field(..., max_length=255)
    full_name: str | None = Field(None, max_length=255)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: Any) -> Any:
        """Validate username format."""
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Username can only contain letters, numbers, underscores, and hyphens")
        return v


class UserCreate(UserBase):
    """Schema for creating a new user."""

    password: str = Field(..., min_length=8, max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: Any) -> Any:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class UserSelfUpdate(BaseModel):
    """Schema for users updating their own profile. Rejects privileged fields."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = Field(None, max_length=255)
    full_name: str | None = Field(None, max_length=255)
    unit_preference: str | None = Field(None, pattern="^(imperial|metric)$")
    show_both_units: bool | None = None
    time_format: str | None = Field(None, pattern="^(12h|24h)$")
    mobile_quick_entry_enabled: bool | None = None
    # i18n preferences
    language: str | None = Field(None, max_length=10)
    currency_code: str | None = Field(None, max_length=3)
    # UI theme accent
    accent_color: str | None = Field(None, max_length=20)
    # UI light/dark theme
    theme: str | None = Field(None, max_length=10)
    # Fuel-tracking form defaults (issue #69)
    default_payment_method: str | None = Field(None, max_length=20)
    default_trip_type: str | None = Field(None, max_length=20)

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: Any) -> Any:
        """Validate language against supported allowlist."""
        if v is not None and v not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {v}. Supported: {sorted(SUPPORTED_LANGUAGES)}")
        return v

    @field_validator("currency_code")
    @classmethod
    def validate_currency_code(cls, v: Any) -> Any:
        """Validate currency code against supported allowlist."""
        if v is not None and v not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Unsupported currency: {v}. Supported: {sorted(SUPPORTED_CURRENCIES)}"
            )
        return v

    @field_validator("accent_color")
    @classmethod
    def validate_accent_color(cls, v: Any) -> Any:
        """Validate accent against the six-key allowlist."""
        if v is not None and v not in SUPPORTED_ACCENTS:
            raise ValueError(f"Unsupported accent: {v}. Supported: {sorted(SUPPORTED_ACCENTS)}")
        return v

    @field_validator("theme")
    @classmethod
    def validate_theme(cls, v: Any) -> Any:
        """Validate theme against the light/dark allowlist."""
        if v is not None and v not in SUPPORTED_THEMES:
            raise ValueError(f"Unsupported theme: {v}. Supported: {sorted(SUPPORTED_THEMES)}")
        return v

    @field_validator("default_payment_method")
    @classmethod
    def validate_default_payment_method(cls, v: Any) -> Any:
        """Validate against the canonical PaymentMethod enum."""
        if v is not None and v not in PAYMENT_METHOD_VALUES:
            raise ValueError(
                f"default_payment_method must be one of {PAYMENT_METHOD_VALUES}, got {v!r}"
            )
        return v

    @field_validator("default_trip_type")
    @classmethod
    def validate_default_trip_type(cls, v: Any) -> Any:
        """Validate against the canonical TripType enum."""
        if v is not None and v not in TRIP_TYPE_VALUES:
            raise ValueError(f"default_trip_type must be one of {TRIP_TYPE_VALUES}, got {v!r}")
        return v


class AdminUserUpdate(BaseModel):
    """Schema for admin updating any user. Includes privileged fields."""

    email: EmailStr | None = Field(None, max_length=255)
    full_name: str | None = Field(None, max_length=255)
    is_active: bool | None = None
    is_admin: bool | None = None
    unit_preference: str | None = Field(None, pattern="^(imperial|metric)$")
    show_both_units: bool | None = None
    time_format: str | None = Field(None, pattern="^(12h|24h)$")
    mobile_quick_entry_enabled: bool | None = None
    # i18n preferences
    language: str | None = Field(None, max_length=10)
    currency_code: str | None = Field(None, max_length=3)
    # UI theme accent
    accent_color: str | None = Field(None, max_length=20)
    # UI light/dark theme
    theme: str | None = Field(None, max_length=10)
    # Family/relationship fields
    relationship: RelationshipType = None
    relationship_custom: str | None = Field(None, max_length=100)
    show_on_family_dashboard: bool | None = None
    family_dashboard_order: int | None = Field(None, ge=0)

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: Any) -> Any:
        """Validate language against supported allowlist."""
        if v is not None and v not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {v}. Supported: {sorted(SUPPORTED_LANGUAGES)}")
        return v

    @field_validator("currency_code")
    @classmethod
    def validate_currency_code(cls, v: Any) -> Any:
        """Validate currency code against supported allowlist."""
        if v is not None and v not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Unsupported currency: {v}. Supported: {sorted(SUPPORTED_CURRENCIES)}"
            )
        return v

    @field_validator("accent_color")
    @classmethod
    def validate_accent_color(cls, v: Any) -> Any:
        """Validate accent against the six-key allowlist."""
        if v is not None and v not in SUPPORTED_ACCENTS:
            raise ValueError(f"Unsupported accent: {v}. Supported: {sorted(SUPPORTED_ACCENTS)}")
        return v

    @field_validator("theme")
    @classmethod
    def validate_theme(cls, v: Any) -> Any:
        """Validate theme against the light/dark allowlist."""
        if v is not None and v not in SUPPORTED_THEMES:
            raise ValueError(f"Unsupported theme: {v}. Supported: {sorted(SUPPORTED_THEMES)}")
        return v

    @model_validator(mode="after")
    def validate_relationship_custom(self) -> AdminUserUpdate:
        """Validate that relationship_custom is only set when relationship is 'other'."""
        if self.relationship_custom and self.relationship != "other":
            raise ValueError("relationship_custom can only be set when relationship is 'other'")
        return self


class AdminUserCreate(UserCreate):
    """Schema for admin creating a new user with additional fields."""

    relationship: RelationshipType = None
    relationship_custom: str | None = Field(None, max_length=100)
    show_on_family_dashboard: bool = False

    @model_validator(mode="after")
    def validate_relationship_custom(self) -> AdminUserCreate:
        """Validate that relationship_custom is only set when relationship is 'other'."""
        if self.relationship_custom and self.relationship != "other":
            raise ValueError("relationship_custom can only be set when relationship is 'other'")
        return self


class UserPasswordUpdate(BaseModel):
    """Schema for updating user password."""

    current_password: str = Field(..., min_length=1, max_length=100)
    new_password: str = Field(..., min_length=8, max_length=100)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: Any) -> Any:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class AdminPasswordReset(BaseModel):
    """Schema for admin password reset."""

    new_password: str = Field(..., min_length=8, max_length=100)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: Any) -> Any:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class UserResponse(UserBase):
    """Schema for user response."""

    id: int
    is_active: bool
    is_admin: bool
    unit_preference: UnitPreference = "imperial"
    show_both_units: bool = False
    # Raw per-quantity overrides. NULL means "no override" (spec D3); the
    # resolved set below is what callers should format with.
    unit_distance: DistanceUnit | None = None
    unit_speed: SpeedUnit | None = None
    unit_length: LengthUnit | None = None
    unit_volume: VolumeUnit | None = None
    unit_consumption: ConsumptionUnit | None = None
    unit_pressure: PressureUnit | None = None
    unit_temperature: TemperatureUnit | None = None
    unit_mass: MassUnit | None = None
    unit_torque: TorqueUnit | None = None
    unit_tread: TreadUnit | None = None
    secondary_gallon: GallonFlavourPref | None = None
    time_format: str = "12h"
    mobile_quick_entry_enabled: bool = True
    # i18n preferences
    language: str = "en"
    currency_code: str = "USD"
    # UI theme accent — None when the user has never explicitly picked one.
    accent_color: str | None = None
    # UI light/dark theme — None when the user has never explicitly picked one.
    theme: str | None = None
    # Fuel-tracking form defaults (issue #69)
    default_payment_method: str | None = None
    default_trip_type: str | None = None
    # Family/relationship fields
    relationship: str | None = None
    relationship_custom: str | None = None
    show_on_family_dashboard: bool = False
    family_dashboard_order: int = 0
    # Timestamps
    created_at: datetime
    updated_at: datetime
    last_login: datetime | None

    @field_validator(*UNIT_COLUMN_NAMES, mode="before", check_fields=False)
    @classmethod
    def discard_out_of_vocabulary_unit(cls, value: Any, info: ValidationInfo) -> Any:
        """Read a raw unit column outside its vocabulary as "no override".

        These columns carry no database CHECK, so a hand-edited row can hold
        anything. Without this, the strict `Literal | None` annotations below
        would raise before `resolve_units` ever ran, and FastAPI would turn that
        into a 500 on `/auth/me`, locking the account out of the frontend
        entirely. `None` already means "no override" (spec D3), so degrading to
        it is how the rest of the system answers this question: the field
        reports nothing stored, and `resolved_units` supplies the preset value
        for that quantity.

        `mode="before"` on purpose: coercing ahead of the Literal keeps the
        annotations strict, so the generated TypeScript still gets the narrow
        unions the frontend branches on.

        `check_fields=False` because this list is derived from UNIT_COLUMN_NAMES,
        so it can only name a field this model lacks when someone adds a twelfth
        quantity to `UnitSet` and has not yet added the matching column here.
        Pydantic would otherwise raise at class-definition time, which fails the
        whole suite at import and hides every guard written for exactly that
        moment (the arity tripwire in tests/unit/constants/test_units_vocabulary.py
        and the schema-parity tests). The reconciliation itself stays guarded by
        `test_response_exposes_all_eleven_raw_columns`.
        """
        # field_name is always one of UNIT_COLUMN_NAMES here; the default only
        # satisfies the type checker, which types it as `str | None`.
        vocabulary = _UNIT_VOCABULARIES.get(info.field_name or "", frozenset())
        return value if isinstance(value, str) and value in vocabulary else None

    @field_validator("unit_preference", mode="before")
    @classmethod
    def discard_out_of_vocabulary_unit_preference(cls, value: Any) -> Any:
        """Read an unrecognised ``unit_preference`` the way `base_preset_for`
        already does: fall back to "imperial" instead of raising.

        `unit_preference` is the twelfth field alongside the eleven raw unit
        columns above, and it sits over the same kind of unconstrained column
        (`String(20)`, no CHECK). But unlike the eleven, it has no `None`
        state to degrade to (the field is a bare `Literal`, always required),
        so it cannot reuse `discard_out_of_vocabulary_unit`'s "coerce to None"
        behaviour. `base_preset_for` (app.utils.unit_resolution) already
        answers the equivalent question for the resolver: anything that is not
        "metric" resolves to the imperial preset, including a half-written or
        hand-edited row, because imperial keeps behaviour identical to the
        historical default rather than silently flipping someone to metric.
        This validator makes the API response agree, so a corrupt column
        degrades the same way instead of 500ing `/auth/me`.

        A second, separate `field_validator` rather than folding this into
        `discard_out_of_vocabulary_unit` above: that one is deliberately
        `check_fields=False` because its field list (`UNIT_COLUMN_NAMES`) is
        derived and could, in principle, name a field this model has not
        grown yet. `"unit_preference"` is a literal, always-present field
        name with no such arity hazard, so a strict validator here is exactly
        what should catch a real typo instead of silently no-op-ing.

        `mode="before"`, matching the other validator, so the annotation
        stays the strict `Literal["imperial", "metric", "custom"]` the
        generated TypeScript needs, rather than widening to `str`.
        """
        return value if value in _UNIT_PREFERENCE_VALUES else "imperial"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_units(self) -> UnitSet:
        """The unit set that actually applies: preset base with overrides on top.

        Derived rather than stored so it cannot drift from the raw columns above.
        `resolve_units` is pure and synchronous for exactly this reason; if it
        ever needs the database, this field has to move to the route.

        This call is the only place a `UserResponse` is checked against the
        `UnitPreferenceSource` Protocol. That check only runs because of this
        file's `reportArgumentType=error` pragma: the project-wide setting is
        "none" (FastAPI `Depends()` noise), which would silently accept a
        broken Protocol conformance here too. Do not remove the pragma without
        another way to catch that.
        """
        return resolve_units(self)

    class Config:
        from_attributes = True


class Token(BaseModel):
    """Token response schema."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    csrf_token: str | None = None


class TokenData(BaseModel):
    """Token data schema."""

    user_id: int | None = None
    username: str | None = None


class LoginRequest(BaseModel):
    """Login request schema."""

    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=100)
