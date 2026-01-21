"""Insurance policy API routes."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict, Any, Optional
import logging

from app.database import get_db
from app.models import InsurancePolicy as InsurancePolicyModel, Vehicle
from app.models.user import User
from app.schemas.insurance import (
    InsurancePolicy,
    InsurancePolicyCreate,
    InsurancePolicyUpdate,
)
from app.services.auth import require_auth
from app.services.document_ocr import document_ocr_service
from app.utils.logging_utils import sanitize_for_log

router = APIRouter(prefix="/api", tags=["Insurance"])
logger = logging.getLogger(__name__)


@router.get("/vehicles/{vin}/insurance", response_model=List[InsurancePolicy])
async def get_insurance_policies(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get all insurance policies for a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get insurance policies
    result = await db.execute(
        select(InsurancePolicyModel)
        .where(InsurancePolicyModel.vin == vin)
        .order_by(InsurancePolicyModel.end_date.desc())
    )
    policies = result.scalars().all()
    return policies


@router.post(
    "/vehicles/{vin}/insurance", response_model=InsurancePolicy, status_code=201
)
async def create_insurance_policy(
    vin: str,
    policy: InsurancePolicyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Create a new insurance policy."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Create insurance policy
    db_policy = InsurancePolicyModel(vin=vin, **policy.model_dump())
    db.add(db_policy)
    await db.commit()
    await db.refresh(db_policy)
    return db_policy


@router.get("/vehicles/{vin}/insurance/{policy_id}", response_model=InsurancePolicy)
async def get_insurance_policy(
    vin: str,
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get a specific insurance policy."""
    result = await db.execute(
        select(InsurancePolicyModel).where(
            InsurancePolicyModel.vin == vin, InsurancePolicyModel.id == policy_id
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Insurance policy not found")
    return policy


@router.put("/vehicles/{vin}/insurance/{policy_id}", response_model=InsurancePolicy)
async def update_insurance_policy(
    vin: str,
    policy_id: int,
    policy_update: InsurancePolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Update an insurance policy."""
    result = await db.execute(
        select(InsurancePolicyModel).where(
            InsurancePolicyModel.vin == vin, InsurancePolicyModel.id == policy_id
        )
    )
    db_policy = result.scalar_one_or_none()
    if not db_policy:
        raise HTTPException(status_code=404, detail="Insurance policy not found")

    # Update fields
    update_data = policy_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_policy, field, value)

    await db.commit()
    await db.refresh(db_policy)
    return db_policy


@router.delete("/vehicles/{vin}/insurance/{policy_id}", status_code=204)
async def delete_insurance_policy(
    vin: str,
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Delete an insurance policy."""
    result = await db.execute(
        select(InsurancePolicyModel).where(
            InsurancePolicyModel.vin == vin, InsurancePolicyModel.id == policy_id
        )
    )
    db_policy = result.scalar_one_or_none()
    if not db_policy:
        raise HTTPException(status_code=404, detail="Insurance policy not found")

    await db.delete(db_policy)
    await db.commit()
    return None


@router.post("/vehicles/{vin}/insurance/parse-pdf")
async def parse_insurance_pdf(
    vin: str,
    file: UploadFile = File(...),
    provider: Optional[str] = Query(
        None,
        description="Optional provider hint (progressive, statefarm, geico, allstate)",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
) -> Dict[str, Any]:
    """
    Parse an insurance PDF and extract policy data.

    Uses OCR and auto-detection to identify the insurance provider and extract
    relevant policy information. Supports Progressive, State Farm, GEICO, Allstate,
    and other providers via generic parsing.

    Returns extracted data without saving to database.
    User can review and edit before creating the policy.
    """
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Validate file type - now supports images too
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png"}
    file_ext = (
        "." + file.filename.lower().split(".")[-1]
        if file.filename and "." in file.filename
        else ""
    )
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File must be PDF or image (jpg, png). Got: {file_ext}",
        )

    # Check file size BEFORE reading into memory to prevent DoS
    MAX_SIZE = 25 * 1024 * 1024
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Seek back to beginning

    if file_size > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 25MB limit")

    # Read file content
    contents = await file.read()

    try:
        # Parse using unified document OCR service
        logger.info(
            "Parsing insurance document for VIN %s (provider hint: %s)",
            sanitize_for_log(vin),
            sanitize_for_log(str(provider)),
        )

        parsed_data = await document_ocr_service.extract_insurance_data(
            file_bytes=contents,
            target_vin=vin,
            provider_hint=provider,
        )

        if not parsed_data.get("success"):
            raise ValueError(parsed_data.get("error", "Failed to extract data"))

        # Sanitize validation warnings to prevent stack trace exposure
        # Only include safe, user-friendly warning messages
        raw_warnings = parsed_data.get("validation_warnings", [])
        safe_warnings = []
        for warning in raw_warnings:
            # Filter out any warnings that look like stack traces or internal errors
            warning_str = str(warning)
            if not any(
                indicator in warning_str.lower()
                for indicator in ["traceback", "exception", "error:", "line ", "file "]
            ):
                safe_warnings.append(warning_str)

        # Format response (maintaining backward compatibility)
        response = {
            "success": True,
            "data": {
                "provider": parsed_data.get("provider"),
                "policy_number": parsed_data.get("policy_number"),
                "policy_type": parsed_data.get("policy_type"),
                "start_date": parsed_data.get("start_date"),
                "end_date": parsed_data.get("end_date"),
                "premium_amount": parsed_data.get("premium_amount"),
                "premium_frequency": parsed_data.get("premium_frequency"),
                "deductible": parsed_data.get("deductible"),
                "coverage_limits": parsed_data.get("coverage_limits"),
                "notes": parsed_data.get("notes"),
            },
            "confidence": parsed_data.get("field_confidence", {}),
            "confidence_score": parsed_data.get("confidence_score", 0),
            "parser_used": parsed_data.get("parser_name"),
            "vehicles_found": parsed_data.get("vehicles_found", []),
            "warnings": safe_warnings,
        }

        # Add warning if target VIN not found
        if vin.upper() not in [
            v.upper() for v in parsed_data.get("vehicles_found", [])
        ]:
            response["warnings"].append(
                f"VIN {vin} not found in PDF - using policy-level data"
            )

        logger.info(
            "Successfully parsed document using %s - found %d vehicles, confidence: %.0f%%",
            sanitize_for_log(str(parsed_data.get("parser_name"))),
            len(parsed_data.get("vehicles_found", [])),
            parsed_data.get("confidence_score", 0),
        )
        return response

    except ValueError as e:
        logger.error("Document parsing error: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=400, detail="Invalid insurance document format")
    except (OSError, IOError) as e:
        logger.error("File system error parsing document: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=500, detail="Error reading uploaded document")


@router.get("/insurance/parsers")
async def list_insurance_parsers(
    current_user: Optional[User] = Depends(require_auth),
) -> Dict[str, Any]:
    """List available insurance document parsers."""
    return {
        "parsers": document_ocr_service.list_available_insurance_parsers(),
        "ocr_status": document_ocr_service.get_ocr_status(),
    }


@router.post("/vehicles/{vin}/insurance/test-parse")
async def test_parse_insurance_pdf(
    vin: str,
    file: UploadFile = File(...),
    provider: Optional[str] = Query(None, description="Optional provider hint"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
) -> Dict[str, Any]:
    """
    Test parse an insurance document - returns full debug info including raw text.

    Useful for troubleshooting parsing issues.
    """
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Validate file
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png"}
    file_ext = (
        "." + file.filename.lower().split(".")[-1]
        if file.filename and "." in file.filename
        else ""
    )
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="File must be PDF or image")

    MAX_SIZE = 25 * 1024 * 1024
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 25MB limit")

    contents = await file.read()

    # Run test extraction
    result = await document_ocr_service.test_insurance_extraction(
        file_bytes=contents,
        target_vin=vin,
        provider_hint=provider,
    )

    return result
