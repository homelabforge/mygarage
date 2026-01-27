"""File attachment API routes for service records and other entities."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.attachment import Attachment
from app.models.service import ServiceRecord
from app.models.service_visit import ServiceVisit
from app.models.user import User
from app.schemas.attachment import AttachmentListResponse, AttachmentResponse
from app.services.auth import require_auth
from app.services.file_upload_service import ATTACHMENT_UPLOAD_CONFIG, FileUploadService
from app.utils.logging_utils import sanitize_for_log

router = APIRouter(prefix="/api", tags=["Attachments"])
logger = logging.getLogger(__name__)

# Configuration
UPLOAD_DIR = settings.attachments_dir


def get_file_extension(filename: str) -> str:
    """Get file extension from filename."""
    return Path(filename).suffix.lower()


@router.post(
    "/service/{record_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_service_attachment(
    record_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Upload a file attachment to a service record.

    Supported file types: JPG, PNG, GIF, PDF
    Max file size: 10MB
    """
    try:
        # Verify service record exists
        result = await db.execute(select(ServiceRecord).where(ServiceRecord.id == record_id))
        service_record = result.scalar_one_or_none()
        if not service_record:
            raise HTTPException(status_code=404, detail=f"Service record {record_id} not found")

        # Upload using shared service
        upload_result = await FileUploadService.upload_file(
            file, ATTACHMENT_UPLOAD_CONFIG, subdirectory=f"service/{record_id}"
        )

        # Create database record
        attachment = Attachment(
            record_type="service",
            record_id=record_id,
            file_path=str(upload_result.file_path),
            file_type=upload_result.content_type,
            file_size=upload_result.file_size,
        )

        db.add(attachment)
        await db.commit()
        await db.refresh(attachment)

        logger.info("Uploaded attachment %s for service record %s", attachment.id, record_id)

        return AttachmentResponse(
            id=attachment.id,
            record_type=attachment.record_type,
            record_id=attachment.record_id,
            file_name=file.filename,
            file_type=attachment.file_type,
            file_size=attachment.file_size,
            uploaded_at=attachment.uploaded_at,
            download_url=f"/api/attachments/{attachment.id}/download",
            view_url=f"/api/attachments/{attachment.id}/view",
        )

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation uploading attachment: %s",
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=409, detail="Attachment record already exists")
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error uploading attachment: %s",
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
    except OSError as e:
        await db.rollback()
        logger.error("File system error uploading attachment: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=500, detail="Failed to save attachment file")


@router.get("/service/{record_id}/attachments", response_model=AttachmentListResponse)
async def list_service_attachments(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Get all attachments for a service record."""
    try:
        # Verify service record exists
        result = await db.execute(select(ServiceRecord).where(ServiceRecord.id == record_id))
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
            if "_" in filename:
                parts = filename.split("_", 2)
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
                    view_url=f"/api/attachments/{att.id}/view",
                )
            )

        return AttachmentListResponse(attachments=attachment_responses, total=total or 0)

    except HTTPException:
        raise
    except OperationalError as e:
        logger.error(
            "Database connection error listing attachments: %s",
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.get("/attachments/{attachment_id}/view")
async def view_attachment(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """View an attachment file inline (for preview)."""
    try:
        # Get attachment
        result = await db.execute(select(Attachment).where(Attachment.id == attachment_id))
        attachment = result.scalar_one_or_none()
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

        # Check if file exists
        file_path = Path(attachment.file_path)
        if not file_path.exists():
            logger.error(
                "Attachment file not found: %s",
                sanitize_for_log(str(attachment.file_path)),
            )
            raise HTTPException(status_code=404, detail="Attachment file not found on disk")

        # Return file for inline viewing (no Content-Disposition header)
        return FileResponse(
            path=str(file_path),
            media_type=attachment.file_type or "application/octet-stream",
        )

    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Attachment file not found")
    except PermissionError as e:
        logger.error("Permission denied viewing attachment: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=403, detail="Permission denied")
    except OSError as e:
        logger.error("File system error viewing attachment: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=500, detail="Error reading attachment file")


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Download an attachment file."""
    try:
        # Get attachment
        result = await db.execute(select(Attachment).where(Attachment.id == attachment_id))
        attachment = result.scalar_one_or_none()
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

        # Check if file exists
        file_path = Path(attachment.file_path)
        if not file_path.exists():
            logger.error(
                "Attachment file not found: %s",
                sanitize_for_log(str(attachment.file_path)),
            )
            raise HTTPException(status_code=404, detail="Attachment file not found on disk")

        # Extract original filename
        filename = file_path.name
        if "_" in filename:
            parts = filename.split("_", 2)
            if len(parts) >= 3:
                filename = parts[2]

        # Return file
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type=attachment.file_type or "application/octet-stream",
        )

    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Attachment file not found")
    except PermissionError as e:
        logger.error("Permission denied downloading attachment: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=403, detail="Permission denied")
    except OSError as e:
        logger.error("File system error downloading attachment: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=500, detail="Error reading attachment file")


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Delete an attachment."""
    try:
        # Get attachment
        result = await db.execute(select(Attachment).where(Attachment.id == attachment_id))
        attachment = result.scalar_one_or_none()
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")

        # Delete file from disk
        file_path = Path(attachment.file_path)
        if file_path.exists():
            file_path.unlink()
            logger.info("Deleted file: %s", sanitize_for_log(str(attachment.file_path)))

        # Delete database record
        await db.execute(delete(Attachment).where(Attachment.id == attachment_id))
        await db.commit()

        logger.info("Deleted attachment %s", attachment_id)
        return None

    except HTTPException:
        raise
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error deleting attachment: %s",
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
    except OSError as e:
        await db.rollback()
        logger.error("File system error deleting attachment: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=500, detail="Error deleting attachment file")


# ============================================================================
# Service Visit Attachment Endpoints
# ============================================================================


@router.post(
    "/service-visits/{visit_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_service_visit_attachment(
    visit_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _current_user: User | None = Depends(require_auth),
):
    """
    Upload a file attachment to a service visit.

    Supported file types: JPG, PNG, GIF, PDF
    Max file size: 10MB
    """
    try:
        # Verify service visit exists
        result = await db.execute(select(ServiceVisit).where(ServiceVisit.id == visit_id))
        service_visit = result.scalar_one_or_none()
        if not service_visit:
            raise HTTPException(status_code=404, detail=f"Service visit {visit_id} not found")

        # Upload using shared service
        upload_result = await FileUploadService.upload_file(
            file, ATTACHMENT_UPLOAD_CONFIG, subdirectory=f"service_visit/{visit_id}"
        )

        # Create database record
        attachment = Attachment(
            record_type="service_visit",
            record_id=visit_id,
            file_path=str(upload_result.file_path),
            file_type=upload_result.content_type,
            file_size=upload_result.file_size,
        )

        db.add(attachment)
        await db.commit()
        await db.refresh(attachment)

        logger.info("Uploaded attachment %s for service visit %s", attachment.id, visit_id)

        return AttachmentResponse(
            id=attachment.id,
            record_type=attachment.record_type,
            record_id=attachment.record_id,
            file_name=file.filename or "attachment",
            file_type=attachment.file_type,
            file_size=attachment.file_size,
            uploaded_at=attachment.uploaded_at,
            download_url=f"/api/attachments/{attachment.id}/download",
            view_url=f"/api/attachments/{attachment.id}/view",
        )

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation uploading attachment: %s",
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=409, detail="Attachment record already exists")
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error uploading attachment: %s",
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
    except OSError as e:
        await db.rollback()
        logger.error("File system error uploading attachment: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=500, detail="Failed to save attachment file")


@router.get("/service-visits/{visit_id}/attachments", response_model=AttachmentListResponse)
async def list_service_visit_attachments(
    visit_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User | None = Depends(require_auth),
):
    """Get all attachments for a service visit."""
    try:
        # Verify service visit exists
        result = await db.execute(select(ServiceVisit).where(ServiceVisit.id == visit_id))
        service_visit = result.scalar_one_or_none()
        if not service_visit:
            raise HTTPException(status_code=404, detail=f"Service visit {visit_id} not found")

        # Get attachments
        result = await db.execute(
            select(Attachment)
            .where(Attachment.record_type == "service_visit")
            .where(Attachment.record_id == visit_id)
            .order_by(Attachment.uploaded_at.desc())
        )
        attachments = result.scalars().all()

        # Get total count
        count_result = await db.execute(
            select(func.count())
            .select_from(Attachment)
            .where(Attachment.record_type == "service_visit")
            .where(Attachment.record_id == visit_id)
        )
        total = count_result.scalar()

        # Build response
        attachment_responses = []
        for att in attachments:
            # Extract original filename from path
            filename = Path(att.file_path).name
            # Remove timestamp prefix if present
            if "_" in filename:
                parts = filename.split("_", 2)
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
                    view_url=f"/api/attachments/{att.id}/view",
                )
            )

        return AttachmentListResponse(attachments=attachment_responses, total=total or 0)

    except HTTPException:
        raise
    except OperationalError as e:
        logger.error(
            "Database connection error listing attachments: %s",
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
