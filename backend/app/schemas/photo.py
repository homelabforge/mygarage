"""
Photo schemas for Pydantic validation
"""

from datetime import datetime as datetime_type

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._nullability import reject_null


class PhotoResponse(BaseModel):
    """Response model for photo"""

    id: int
    vin: str
    file_path: str
    thumbnail_path: str | None = None
    thumbnail_url: str | None = None
    is_main: bool
    caption: str | None = None
    uploaded_at: datetime_type

    model_config = ConfigDict(from_attributes=True)


class PhotoListResponse(BaseModel):
    """Response model for photo list"""

    photos: list[PhotoResponse]
    total: int
    main_photo: PhotoResponse | None = None


class PhotoUpdate(BaseModel):
    """Schema for updating photo"""

    caption: str | None = Field(None, max_length=200)
    is_main: bool | None = None

    # NOT NULL column: omitted leaves it alone, null is a 422.
    _no_null = reject_null("is_main")
