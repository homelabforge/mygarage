"""User schemas for authentication."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.constants.fuel import PAYMENT_METHOD_VALUES, TRIP_TYPE_VALUES
from app.constants.i18n import SUPPORTED_CURRENCIES, SUPPORTED_LANGUAGES

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
    unit_preference: str = "imperial"
    show_both_units: bool = False
    time_format: str = "12h"
    mobile_quick_entry_enabled: bool = True
    # i18n preferences
    language: str = "en"
    currency_code: str = "USD"
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
