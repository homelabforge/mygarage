"""Pydantic schemas for file attachments."""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional


class AttachmentBase(BaseModel):
    """Base attachment schema."""

    file_name: str = Field(..., description="Original filename")
    file_type: Optional[str] = Field(None, description="MIME type or file extension")
    file_size: Optional[int] = Field(None, description="File size in bytes", ge=0)


class AttachmentCreate(AttachmentBase):
    """Schema for creating an attachment (used internally)."""

    record_type: str = Field(..., description="Type of record (service, fuel, etc.)")
    record_id: int = Field(..., description="ID of the associated record")
    file_path: str = Field(..., description="Path to file in storage")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "record_type": "service",
                    "record_id": 123,
                    "file_name": "oil_change_receipt.pdf",
                    "file_type": "application/pdf",
                    "file_size": 245678,
                    "file_path": "/data/attachments/service/123/20250106_120000_oil_change_receipt.pdf",
                }
            ]
        }
    }


class AttachmentResponse(AttachmentBase):
    """Schema for attachment response."""

    id: int
    record_type: str
    record_id: int
    uploaded_at: datetime
    download_url: str = Field(..., description="URL to download the file")
    view_url: str = Field(..., description="URL to view the file inline")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "record_type": "service",
                    "record_id": 123,
                    "file_name": "oil_change_receipt.pdf",
                    "file_type": "application/pdf",
                    "file_size": 245678,
                    "uploaded_at": "2025-01-06T12:00:00",
                    "download_url": "/api/attachments/1/download",
                }
            ]
        },
    }


class AttachmentListResponse(BaseModel):
    """Schema for list of attachments."""

    attachments: list[AttachmentResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "attachments": [
                        {
                            "id": 1,
                            "record_type": "service",
                            "record_id": 123,
                            "file_name": "receipt.pdf",
                            "file_type": "application/pdf",
                            "file_size": 245678,
                            "uploaded_at": "2025-01-06T12:00:00",
                            "download_url": "/api/attachments/1/download",
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }
