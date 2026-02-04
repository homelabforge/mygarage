"""User schemas for authentication."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

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


class UserUpdate(BaseModel):
    """Schema for updating a user."""

    email: EmailStr | None = Field(None, max_length=255)
    full_name: str | None = Field(None, max_length=255)
    is_active: bool | None = None
    is_admin: bool | None = None
    unit_preference: str | None = Field(None, pattern="^(imperial|metric)$")
    show_both_units: bool | None = None
    # Family/relationship fields
    relationship: RelationshipType = None
    relationship_custom: str | None = Field(None, max_length=100)
    show_on_family_dashboard: bool | None = None
    family_dashboard_order: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_relationship_custom(self) -> UserUpdate:
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


class UserResponse(UserBase):
    """Schema for user response."""

    id: int
    is_active: bool
    is_admin: bool
    unit_preference: str = "imperial"
    show_both_units: bool = False
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
