"""Document schemas for MyGarage API."""

from datetime import datetime as datetime_type
from typing import Optional

from pydantic import BaseModel, Field


class DocumentBase(BaseModel):
    """Base document schema."""

    document_type: Optional[str] = Field(None, max_length=50)
    title: str = Field(..., max_length=200)
    description: Optional[str] = None


class DocumentCreate(DocumentBase):
    """Schema for creating a document."""

    vin: str = Field(..., max_length=17)


class DocumentUpdate(BaseModel):
    """Schema for updating a document."""

    document_type: Optional[str] = Field(None, max_length=50)
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None


class DocumentResponse(DocumentBase):
    """Schema for document response."""

    id: int
    vin: str
    file_path: str
    file_name: str
    file_size: int
    mime_type: str
    uploaded_at: datetime_type

    class Config:
        """Pydantic config."""

        from_attributes = True


class DocumentListResponse(BaseModel):
    """Schema for list of documents."""

    documents: list[DocumentResponse]
    total: int
