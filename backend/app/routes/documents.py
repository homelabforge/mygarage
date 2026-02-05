"""Document routes for MyGarage API."""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Document
from app.models.user import User
from app.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUpdate,
)
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.file_upload_service import DOCUMENT_UPLOAD_CONFIG, FileUploadService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles", tags=["documents"])

# Document storage configuration
DOCUMENT_STORAGE_PATH = settings.documents_dir


def get_mime_type(filename: str) -> str:
    """Get MIME type based on file extension."""
    ext = Path(filename).suffix.lower()
    mime_types = {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "text/csv",
    }
    return mime_types.get(ext, "application/octet-stream")


@router.get("/{vin}/documents", response_model=DocumentListResponse)
async def list_documents(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> DocumentListResponse:
    """List all documents for a vehicle."""
    # Verify vehicle exists and user has access
    _ = await get_vehicle_or_403(vin, current_user, db)

    # Get documents
    result = await db.execute(
        select(Document).where(Document.vin == vin).order_by(Document.uploaded_at.desc())
    )
    documents = result.scalars().all()

    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(doc) for doc in documents],
        total=len(documents),
    )


@router.post("/{vin}/documents", response_model=DocumentResponse, status_code=201)
async def upload_document(
    vin: str,
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str, Form()],
    document_type: Annotated[str | None, Form()] = None,
    description: Annotated[str | None, Form()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> DocumentResponse:
    """Upload a new document for a vehicle."""
    # Verify vehicle exists and user has write access
    _ = await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Upload using shared service
    upload_result = await FileUploadService.upload_file(
        file, DOCUMENT_UPLOAD_CONFIG, subdirectory=vin
    )

    # Create document record
    document = Document(
        vin=vin,
        file_path=str(upload_result.file_path),
        file_name=file.filename,
        file_size=upload_result.file_size,
        mime_type=get_mime_type(file.filename),
        document_type=document_type,
        title=title,
        description=description,
    )

    db.add(document)
    await db.commit()
    await db.refresh(document)

    return DocumentResponse.model_validate(document)


@router.put("/{vin}/documents/{document_id}", response_model=DocumentResponse)
async def update_document(
    vin: str,
    document_id: int,
    update_data: DocumentUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> DocumentResponse:
    """Update document metadata."""
    # Verify vehicle exists and user has write access
    _ = await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Get document
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.vin == vin)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Update fields
    if update_data.document_type is not None:
        document.document_type = update_data.document_type
    if update_data.title is not None:
        document.title = update_data.title
    if update_data.description is not None:
        document.description = update_data.description

    await db.commit()
    await db.refresh(document)

    return DocumentResponse.model_validate(document)


@router.delete("/{vin}/documents/{document_id}", status_code=204)
async def delete_document(
    vin: str,
    document_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> None:
    """Delete a document."""
    try:
        # Verify vehicle exists and user has write access
        _ = await get_vehicle_or_403(vin, current_user, db, require_write=True)

        # Get document
        result = await db.execute(
            select(Document).where(Document.id == document_id, Document.vin == vin)
        )
        document = result.scalar_one_or_none()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Delete file from disk first
        file_path = Path(document.file_path)
        if file_path.exists():
            file_path.unlink()
            logger.info("Deleted document file: %s", file_path)

        # Delete from database
        await db.execute(delete(Document).where(Document.id == document_id))
        await db.commit()

        logger.info("Deleted document %s for vehicle %s", document_id, vin)
        return None

    except HTTPException:
        raise
    except OperationalError as e:
        await db.rollback()
        logger.error("Database error deleting document: %s", e)
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
    except OSError as e:
        await db.rollback()
        logger.error("File system error deleting document: %s", e)
        raise HTTPException(status_code=500, detail="Error deleting document file")


@router.get("/{vin}/documents/{document_id}/download")
async def download_document(
    vin: str,
    document_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> FileResponse:
    """Download a document file."""
    # Verify vehicle exists and user has access
    _ = await get_vehicle_or_403(vin, current_user, db)

    # Get document
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.vin == vin)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check if file exists
    file_path = Path(document.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document file not found on disk")

    # Return file
    return FileResponse(
        path=file_path,
        filename=document.file_name,
        media_type=document.mime_type,
    )
