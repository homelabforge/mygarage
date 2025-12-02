"""File attachment API routes for service records and other entities."""

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError, OperationalError

from app.database import get_db
from app.models.attachment import Attachment
from app.models.service import ServiceRecord
from app.models.user import User
from app.schemas.attachment import AttachmentResponse, AttachmentListResponse, AttachmentCreate
from app.services.auth import require_auth
from app.config import settings
from app.services.file_upload_service import FileUploadService, ATTACHMENT_UPLOAD_CONFIG

router = APIRouter(prefix="/api", tags=["Attachments"])
logger = logging.getLogger(__name__)

# Configuration
UPLOAD_DIR = settings.attachments_dir


def get_file_extension(filename: str) -> str:
    """Get file extension from filename."""
    return Path(filename).suffix.lower()


@router.post("/service/{record_id}/attachments", response_model=AttachmentResponse, status_code=status.HTTP_201_CREATED)
async def upload_service_attachment(
    record_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """
    Upload a file attachment to a service record.

    Supported file types: JPG, PNG, GIF, PDF
    Max file size: 10MB
    """
    try:
        # Verify service record exists
        result = await db.execute(
            select(ServiceRecord).where(ServiceRecord.id == record_id)
        )
        service_record = result.scalar_one_or_none()
        if not service_record:
            raise HTTPException(status_code=404, detail=f"Service record {record_id} not found")

        # Upload using shared service
        upload_result = await FileUploadService.upload_file(
            file,
            ATTACHMENT_UPLOAD_CONFIG,
            subdirectory=f"service/{record_id}"
        )

        # Create database record
        attachment = Attachment(
            record_type="service",
            record_id=record_id,
            file_path=str(upload_result.file_path),
            file_type=upload_result.content_type,
            file_size=upload_result.file_size
        )

        db.add(attachment)
        await db.commit()
        await db.refresh(attachment)

        logger.info(f"Uploaded attachment {attachment.id} for service record {record_id}")

        return AttachmentResponse(
            id=attachment.id,
            record_type=attachment.record_type,
            record_id=attachment.record_id,
            file_name=file.filename,
            file_type=attachment.file_type,
            file_size=attachment.file_size,
            uploaded_at=attachment.uploaded_at,
            download_url=f"/api/attachments/{attachment.id}/download",
            view_url=f"/api/attachments/{attachment.id}/view"
        )

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database constraint violation uploading attachment: {e}")
        raise HTTPException(status_code=409, detail="Attachment record already exists")
    except OperationalError as e:
        await db.rollback()
        logger.error(f"Database connection error uploading attachment: {e}")
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
    except (OSError, IOError) as e:
        await db.rollback()
        logger.error(f"File system error uploading attachment: {e}")
        raise HTTPException(status_code=500, detail="Failed to save attachment file")


@router.get("/service/{record_id}/attachments", response_model=AttachmentListResponse)
async def list_service_attachments(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """Get all attachments for a service record."""
    try:
        # Verify service record exists
        result = await db.execute(
            select(ServiceRecord).where(ServiceRecord.id == record_id)
        )
        service_record = result.scalar_one_or_none()
        if not service_record:
            raise HTTPException(status_code=404, detail=f"Service record {record_id} not found")

        # Get attachments
        result = await db.execute(
            select(Attachment)
            .where(Attachment.record_type == "service")
            .where(Attachment.record_id == record_id)
            .order_by(Attachment.uploaded_at.desc())
        )
        attachments = result.scalars().all()

        # Get total count
        count_result = await db.execute(
            select(func.count())
            .select_from(Attachment)
            .where(Attachment.record_type == "service")
            .where(Attachment.record_id == record_id)
        )
        total = count_result.scalar()

        # Build response
        attachment_responses = []
        for att in attachments:
            # Extract original filename from path
            filename = Path(att.file_path).name
            # Remove timestamp prefix if present
            if '_' in filename:
                parts = filename.split('_', 2)
                if len(parts) >= 3:
                    filename = parts[2]  # Get part after timestamp

            attachment_responses.append(
                AttachmentResponse(
                    id=att.id,
                    record_type=att.record_type,
                    record_id=att.record_id,
                    file_name=filename,
                    file_type=att.file_type,
                    file_size=att.file_size,
                    uploaded_at=att.uploaded_at,
                    download_url=f"/api/attachments/{att.id}/download",
                    view_url=f"/api/attachments/{att.id}/view"
                )
            )

        return AttachmentListResponse(
            attachments=attachment_responses,
            total=total or 0
        )

    except HTTPException:
        raise
    except OperationalError as e:
        logger.error(f"Database connection error listing attachments: {e}")
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.get("/attachments/{attachment_id}/view")
async def view_attachment(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """View an attachment file inline (for preview)."""
    try:
        # Get attachment
        result = await db.execute(
            select(Attachment).where(Attachment.id == attachment_id)
        )
        attachment = result.scalar_one_or_none()
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

        # Check if file exists
        file_path = Path(attachment.file_path)
        if not file_path.exists():
            logger.error(f"Attachment file not found: {attachment.file_path}")
            raise HTTPException(status_code=404, detail="Attachment file not found on disk")

        # Return file for inline viewing (no Content-Disposition header)
        return FileResponse(
            path=str(file_path),
            media_type=attachment.file_type or 'application/octet-stream'
        )

    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Attachment file not found")
    except PermissionError as e:
        logger.error(f"Permission denied viewing attachment: {e}")
        raise HTTPException(status_code=403, detail="Permission denied")
    except (OSError, IOError) as e:
        logger.error(f"File system error viewing attachment: {e}")
        raise HTTPException(status_code=500, detail="Error reading attachment file")


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """Download an attachment file."""
    try:
        # Get attachment
        result = await db.execute(
            select(Attachment).where(Attachment.id == attachment_id)
        )
        attachment = result.scalar_one_or_none()
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

        # Check if file exists
        file_path = Path(attachment.file_path)
        if not file_path.exists():
            logger.error(f"Attachment file not found: {attachment.file_path}")
            raise HTTPException(status_code=404, detail="Attachment file not found on disk")

        # Extract original filename
        filename = file_path.name
        if '_' in filename:
            parts = filename.split('_', 2)
            if len(parts) >= 3:
                filename = parts[2]

        # Return file
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type=attachment.file_type or 'application/octet-stream'
        )

    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Attachment file not found")
    except PermissionError as e:
        logger.error(f"Permission denied downloading attachment: {e}")
        raise HTTPException(status_code=403, detail="Permission denied")
    except (OSError, IOError) as e:
        logger.error(f"File system error downloading attachment: {e}")
        raise HTTPException(status_code=500, detail="Error reading attachment file")


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth)
):
    """Delete an attachment."""
    try:
        # Get attachment
        result = await db.execute(
            select(Attachment).where(Attachment.id == attachment_id)
        )
        attachment = result.scalar_one_or_none()
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

        # Delete file from disk
        file_path = Path(attachment.file_path)
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted file: {attachment.file_path}")

        # Delete database record
        await db.execute(
            delete(Attachment).where(Attachment.id == attachment_id)
        )
        await db.commit()

        logger.info(f"Deleted attachment {attachment_id}")
        return None

    except HTTPException:
        raise
    except OperationalError as e:
        await db.rollback()
        logger.error(f"Database connection error deleting attachment: {e}")
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
    except (OSError, IOError) as e:
        await db.rollback()
        logger.error(f"File system error deleting attachment: {e}")
        raise HTTPException(status_code=500, detail="Error deleting attachment file")
