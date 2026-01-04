"""Address book schemas for validation."""

from pydantic import BaseModel, Field, EmailStr, field_validator
from datetime import datetime
from typing import Optional
from decimal import Decimal


class AddressBookEntryBase(BaseModel):
    """Base address book entry schema."""

    business_name: str = Field(..., max_length=150)
    name: Optional[str] = Field(None, max_length=100)
    address: Optional[str] = None
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=50)
    zip_code: Optional[str] = Field(None, max_length=20)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    website: Optional[str] = Field(None, max_length=200)
    category: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None

    # Geolocation fields for shop discovery
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None

    # Shop discovery metadata
    source: Optional[str] = Field(default="manual", max_length=20)
    external_id: Optional[str] = Field(None, max_length=100)

    # Ratings
    rating: Optional[Decimal] = None
    user_rating: Optional[int] = None

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

    business_name: Optional[str] = Field(None, max_length=150)
    name: Optional[str] = Field(None, max_length=100)
    address: Optional[str] = None
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=50)
    zip_code: Optional[str] = Field(None, max_length=20)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    website: Optional[str] = Field(None, max_length=200)
    category: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None

    # Geolocation fields for shop discovery
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None

    # Shop discovery metadata
    source: Optional[str] = Field(None, max_length=20)
    external_id: Optional[str] = Field(None, max_length=100)

    # Ratings
    rating: Optional[Decimal] = None
    user_rating: Optional[int] = None

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
