"""Settings Pydantic schemas for validation and serialization."""

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas._nullability import reject_null


class SettingBase(BaseModel):
    """Base setting schema."""

    value: str | None = Field(None, description="Setting value")
    category: str = Field("general", description="Setting category")
    description: str | None = Field(None, description="Setting description")
    encrypted: bool = Field(
        False,
        description=(
            "Whether the value is a secret: encrypted at rest and masked as "
            "'********' in API responses."
        ),
    )


class SettingCreate(SettingBase):
    """Schema for creating a setting."""

    key: str = Field(..., description="Setting key", min_length=1, max_length=50)


class SettingUpdate(BaseModel):
    """Schema for updating a setting."""

    value: str | None = Field(None, description="Setting value")
    category: str | None = Field(None, description="Setting category")
    description: str | None = Field(None, description="Setting description")
    encrypted: bool | None = Field(
        None, description="Whether the value is sensitive (masked in API responses)"
    )

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("category", "encrypted")


class SettingResponse(SettingBase):
    """Schema for setting response."""

    key: str
    unreadable: bool = Field(
        False,
        description=(
            "True for a secret that is configured but can't be decrypted with the "
            "current settings key. Its value shows as '********'; saving that "
            "placeholder keeps the stored value, so restoring the right key "
            "recovers it. Re-enter the secret to replace it."
        ),
    )
    created_at: dt.datetime
    updated_at: dt.datetime

    class Config:
        from_attributes = True


class SettingsListResponse(BaseModel):
    """Schema for list of settings."""

    settings: list[SettingResponse]
    total: int


#: A setting key, as wide as the `settings.key` column (and `SettingCreate.key`).
SettingKey = Annotated[str, StringConstraints(min_length=1, max_length=50)]


class SettingsBatchUpdate(BaseModel):
    """Schema for batch updating settings."""

    settings: dict[SettingKey, str] = Field(
        ..., description="Dictionary of key-value pairs to update"
    )


class POIProviderCreate(BaseModel):
    """Adding a POI provider. The route keeps its own 400s for the name and key."""

    name: str = ""
    api_key: str = ""
    enabled: bool = True


class POIProviderUpdate(BaseModel):
    """Editing a POI provider: an omitted field keeps its stored value."""

    api_key: str | None = None
    enabled: bool | None = None

    # Both write settings rows a null has no meaning for.
    _no_null = reject_null("api_key", "enabled")


class SystemInfoResponse(BaseModel):
    """Schema for system information."""

    app_name: str
    app_version: str
    python_version: str
    database_url: str
    data_directory: str
    total_vehicles: int
    database_size_mb: float
    uptime_seconds: float


class SecretsStatusResponse(BaseModel):
    """Whether the secret settings can be read, for the Settings page banner.

    Computed live on each request, not from the startup sweep. Names setting
    keys only, never values.
    """

    keyring: Literal["ok", "unavailable"] = Field(
        ...,
        description=(
            "'unavailable' when no usable settings encryption key is configured: secret "
            "settings can't be saved, and encrypted ones can't be read."
        ),
    )
    unreadable_keys: list[str] = Field(
        ...,
        description=(
            "Secret setting keys, sorted, whose stored value can't be decrypted with the "
            "current keyring. Each reads as unset until its key is restored or it is re-entered."
        ),
    )
