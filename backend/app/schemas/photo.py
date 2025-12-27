"""
Photo schemas for Pydantic validation
"""

from datetime import datetime as datetime_type
from typing import Optional
from pydantic import BaseModel, Field


class PhotoResponse(BaseModel):
    """Response model for photo"""

    id: int
    vin: str
    file_path: str
    thumbnail_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    is_main: bool
    caption: Optional[str] = None
    uploaded_at: datetime_type

    class Config:
        from_attributes = True


class PhotoListResponse(BaseModel):
    """Response model for photo list"""

    photos: list[PhotoResponse]
    total: int
    main_photo: Optional[PhotoResponse] = None


class PhotoUpdate(BaseModel):
    """Schema for updating photo"""

    caption: Optional[str] = Field(None, max_length=200)
    is_main: Optional[bool] = None
