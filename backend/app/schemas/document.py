"""Document schemas for MyGarage API."""

from datetime import datetime as datetime_type

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas._nullability import reject_null


class DocumentBase(BaseModel):
    """Base document schema."""

    document_type: str | None = Field(default=None, max_length=50)
    title: str = Field(..., max_length=200)
    description: str | None = None


def usable_title(value: str | None) -> str | None:
    """Strip a document title and refuse one that is blank.

    Lives on Create and Update only: the Response inherits DocumentBase and
    must still read a blank title saved before this check existed.
    """
    if value is None:
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("title cannot be blank")
    return stripped


class DocumentCreate(DocumentBase):
    """Schema for creating a document."""

    vin: str = Field(..., max_length=17)

    _title = field_validator("title")(usable_title)


class DocumentUpdate(BaseModel):
    """Schema for updating a document."""

    document_type: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=200)
    description: str | None = None

    _no_null = reject_null("title")
    _title = field_validator("title")(usable_title)


class DocumentResponse(DocumentBase):
    """Schema for document response."""

    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    document_type: str | None = None
    title: str
    id: int
    vin: str
    file_path: str
    file_name: str
    file_size: int
    mime_type: str
    uploaded_at: datetime_type

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    """Schema for list of documents."""

    documents: list[DocumentResponse]
    total: int
