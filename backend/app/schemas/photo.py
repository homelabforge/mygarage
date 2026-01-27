"""
Photo schemas for Pydantic validation
"""

from datetime import datetime as datetime_type

from pydantic import BaseModel, Field


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

    class Config:
        from_attributes = True


class PhotoListResponse(BaseModel):
    """Response model for photo list"""

    photos: list[PhotoResponse]
    total: int
    main_photo: PhotoResponse | None = None


class PhotoUpdate(BaseModel):
    """Schema for updating photo"""

    caption: str | None = Field(None, max_length=200)
    is_main: bool | None = None
