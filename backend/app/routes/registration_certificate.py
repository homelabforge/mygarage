"""Registration certificate import (#211).

``POST /api/registration-certificate/parse`` reads a certificate without
touching anything (the wizard uses it before the vehicle exists);
``POST /api/vehicles/{vin}/registration-certificate`` stores the file as a
document of the vehicle, fills its empty fields and records the last
inspection. Both relay the document reader's 409
``ai_reading_not_configured`` as is: the form then says to configure AI
document reading, or to type the values.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.document import Document
from app.models.user import User
from app.schemas.document import DocumentResponse
from app.schemas.registration_certificate import (
    RegistrationImportResponse,
    RegistrationParseResponse,
    SuggestedTaxRecord,
)
from app.services import registration_certificate_service as certificates
from app.services.auth import get_vehicle_for_owner_or_403, require_auth
from app.utils.file_validation import verify_file_content_type
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["registration-certificate"])

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif"}
ALLOWED_MIMES = {"application/pdf", "image/jpeg", "image/png", "image/heic", "image/heif"}
HEIC_MIMES = {"image/heic", "image/heif"}
#: A phone photo of a certificate is a few megabytes; a scan can be more.
MAX_FILE_SIZE = 25 * 1024 * 1024


async def _read_certificate(file: UploadFile) -> bytes:
    """The upload's bytes once its name, type, size and header agree."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")
    extension = Path(file.filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_MIMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid content type. Allowed: {', '.join(sorted(ALLOWED_MIMES))}",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )
    if content_type in HEIC_MIMES:
        genuine = len(content) > 12 and content[4:8] == b"ftyp"
    else:
        genuine = verify_file_content_type(content[:16], content_type)
    if not genuine:
        raise HTTPException(status_code=400, detail="File content does not match its declared type")
    return content


def _to_response(result: certificates.RegistrationParseResult) -> RegistrationParseResponse:
    return RegistrationParseResponse(
        source=result.source,  # type: ignore[arg-type]  # "text" | "llm" from the reader
        country=result.data.country,
        confidence=result.confidence,
        fields=result.fields(),
        field_confidence=dict(result.data.field_confidence),
        vehicle_patch=result.vehicle_patch,
        last_inspection_date=result.last_inspection_date,
        suggested_tax_records=[
            SuggestedTaxRecord(
                code=s["code"],
                tax_type=s["tax_type"],
                amount=Decimal(str(s["amount"])),
                date=s["date"],
            )
            for s in result.suggested_tax_records
        ],
        warnings=list(result.warnings),
        model=result.model,
        pages=result.pages,
    )


@router.post("/registration-certificate/parse", response_model=RegistrationParseResponse)
async def parse_registration_certificate(
    file: Annotated[UploadFile, File(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
    country: str | None = Query(
        None,
        description="A hint for the plate format and the energy codes; the document wins",
        max_length=2,
    ),
) -> RegistrationParseResponse:
    """Read a certificate and return what it would fill. Writes nothing."""
    content = await _read_certificate(file)
    result = await certificates.parse_upload(
        db,
        file_bytes=content,
        filename=file.filename,
        content_type=file.content_type,
        country=country,
    )
    return _to_response(result)


@router.post(
    "/vehicles/{vin}/registration-certificate",
    response_model=RegistrationImportResponse,
    status_code=201,
)
async def import_registration_certificate(
    vin: str,
    file: Annotated[UploadFile, File(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
    overwrite: bool = Query(
        False, description="Replace values already set on the vehicle (never the VIN)"
    ),
) -> RegistrationImportResponse:
    """Store the certificate as a document, fill the vehicle, record X.1.

    Owner only: it writes the vehicle row. The file is kept under the
    vehicle's documents whatever the read found, so a certificate a model
    could not read is still filed.
    """
    vin = vin.upper().strip()
    vehicle = await get_vehicle_for_owner_or_403(vin, current_user, db)
    content = await _read_certificate(file)
    assert file.filename is not None  # _read_certificate refused a nameless upload
    result = await certificates.parse_upload(
        db,
        file_bytes=content,
        filename=file.filename,
        content_type=file.content_type,
        country=vehicle.registration_country,
    )

    destination_dir = Path(settings.documents_dir) / vin
    destination_dir.mkdir(parents=True, exist_ok=True)
    extension = Path(file.filename).suffix.lower()
    destination = destination_dir / f"registration-certificate-{uuid.uuid4().hex[:12]}{extension}"
    try:
        destination.write_bytes(content)
    except OSError as exc:
        logger.error("Failed to save registration certificate: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save file") from exc

    plate = result.data.plate
    title = f"Registration certificate ({plate})" if plate else "Registration certificate"
    document = Document(
        vin=vin,
        file_path=str(destination),
        file_name=file.filename[:255],
        file_size=len(content),
        mime_type=(file.content_type or "application/octet-stream")[:100],
        document_type=certificates.DOCUMENT_TYPE,
        title=title[:200],
        description=f"Imported {datetime.now().date().isoformat()} ({result.source})",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    # Serialised now: applying the patch commits (and may roll back) again,
    # which expires the row, and an expired attribute cannot be loaded
    # outside the session's greenlet.
    document_response = DocumentResponse.model_validate(document)

    outcome = await certificates.apply_to_vehicle(
        db, vehicle, result, overwrite=overwrite, current_user=current_user
    )
    logger.info(
        "Registration certificate imported for %s: applied=%s skipped=%s inspection=%s",
        sanitize_for_log(vin),
        ",".join(outcome.applied) or "-",
        ",".join(outcome.skipped) or "-",
        outcome.inspection_recorded,
    )
    return RegistrationImportResponse(
        document=document_response,
        applied=outcome.applied,
        skipped=outcome.skipped,
        inspection_recorded=outcome.inspection_recorded,
        parse=_to_response(result),
    )
