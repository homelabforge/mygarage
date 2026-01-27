"""Address book schemas for validation."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator


class AddressBookEntryBase(BaseModel):
    """Base address book entry schema."""

    business_name: str = Field(..., max_length=150)
    name: str | None = Field(None, max_length=100)
    address: str | None = None
    city: str | None = Field(None, max_length=100)
    state: str | None = Field(None, max_length=50)
    zip_code: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=20)
    email: EmailStr | None = None
    website: str | None = Field(None, max_length=200)
    category: str | None = Field(None, max_length=50)
    notes: str | None = None

    # Geolocation fields for shop discovery
    latitude: Decimal | None = None
    longitude: Decimal | None = None

    # Shop discovery metadata
    source: str | None = Field(default="manual", max_length=20)
    external_id: str | None = Field(None, max_length=100)

    # Ratings
    rating: Decimal | None = None
    user_rating: int | None = None

    @field_validator("email", "website", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: str) -> str | None:
        """Convert empty strings to None for optional fields."""
        if v == "":
            return None
        return v


class AddressBookEntryCreate(AddressBookEntryBase):
    """Schema for creating an address book entry."""

    pass


class AddressBookEntryUpdate(BaseModel):
    """Schema for updating an address book entry."""

    business_name: str | None = Field(None, max_length=150)
    name: str | None = Field(None, max_length=100)
    address: str | None = None
    city: str | None = Field(None, max_length=100)
    state: str | None = Field(None, max_length=50)
    zip_code: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=20)
    email: EmailStr | None = None
    website: str | None = Field(None, max_length=200)
    category: str | None = Field(None, max_length=50)
    notes: str | None = None

    # Geolocation fields for shop discovery
    latitude: Decimal | None = None
    longitude: Decimal | None = None

    # Shop discovery metadata
    source: str | None = Field(None, max_length=20)
    external_id: str | None = Field(None, max_length=100)

    # Ratings
    rating: Decimal | None = None
    user_rating: int | None = None

    @field_validator("email", "website", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: str) -> str | None:
        """Convert empty strings to None for optional fields."""
        if v == "":
            return None
        return v


class AddressBookEntryResponse(AddressBookEntryBase):
    """Schema for address book entry response."""

    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AddressBookListResponse(BaseModel):
    """Schema for list of address book entries."""

    entries: list[AddressBookEntryResponse]
    total: int
