"""Note schemas for MyGarage API."""

from datetime import date as date_type, datetime as datetime_type
from typing import Optional

from pydantic import BaseModel, Field


class NoteBase(BaseModel):
    """Base note schema."""

    date: date_type
    title: Optional[str] = Field(None, max_length=100)
    content: str = Field(..., min_length=1)


class NoteCreate(NoteBase):
    """Schema for creating a note."""

    vin: str = Field(..., max_length=17)


class NoteUpdate(BaseModel):
    """Schema for updating a note."""

    date: Optional[date_type] = None
    title: Optional[str] = Field(None, max_length=100)
    content: Optional[str] = Field(None, min_length=1)


class NoteResponse(NoteBase):
    """Schema for note response."""

    id: int
    vin: str
    created_at: datetime_type
    updated_at: Optional[datetime_type] = None

    class Config:
        """Pydantic config."""

        from_attributes = True


class NoteListResponse(BaseModel):
    """Schema for list of notes."""

    notes: list[NoteResponse]
    total: int
