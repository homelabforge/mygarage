"""Insurance API routes.

Authorization model
-------------------
A policy is a HOUSEHOLD record, not a vehicle-owned row, so `router` is keyed on
the policy id and its access derives from the vehicles the policy covers. Every
rule lives in `InsuranceService` (see its module docstring); the handlers here
only pass the caller through. The `vin` query parameter on the list is a filter
that the service ALSO gates with `get_vehicle_or_403`.

`vehicle_insurance_router` is the vin-scoped view used by a vehicle's Insurance
tab, gated on the vehicle like any other child collection.
"""

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.insurance import (
    InsurancePolicyCreate,
    InsurancePolicyRenew,
    InsurancePolicyReplace,
    InsurancePolicyResponse,
    InsurancePolicyUpdate,
    PolicyHistoryEntry,
    PolicyVehicleCreate,
    PolicyVehicleUpdate,
)
from app.services.auth import get_current_admin_user, require_auth
from app.services.document_ocr import document_ocr_service
from app.services.insurance_service import InsuranceService
from app.utils.logging_utils import sanitize_for_log

router = APIRouter(prefix="/api/insurance", tags=["Insurance"])
vehicle_insurance_router = APIRouter(prefix="/api/vehicles", tags=["Insurance"])
logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


@router.get("/policies", response_model=list[InsurancePolicyResponse])
async def list_policies(
    vin: str | None = Query(None, description="Only policies covering this vehicle"),
    status: Literal["current", "active", "upcoming", "expired", "all"] = Query(
        "current", description="current = active + upcoming"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> list[InsurancePolicyResponse]:
    """Household policies the caller may see, each with its vehicles beneath it."""
    return await InsuranceService(db).list_policies(current_user, vin=vin, status=status)


@router.post("/policies", response_model=InsurancePolicyResponse, status_code=201)
async def create_policy(
    data: InsurancePolicyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> InsurancePolicyResponse:
    """Create a policy, optionally with the vehicles it covers."""
    return await InsuranceService(db).create_policy(data, current_user)


@router.get("/policies/{policy_id}", response_model=InsurancePolicyResponse)
async def read_policy(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> InsurancePolicyResponse:
    return await InsuranceService(db).read_policy(policy_id, current_user)


@router.put("/policies/{policy_id}", response_model=InsurancePolicyResponse)
async def update_policy(
    policy_id: int,
    data: InsurancePolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> InsurancePolicyResponse:
    return await InsuranceService(db).update_policy(policy_id, data, current_user)


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> None:
    await InsuranceService(db).delete_policy(policy_id, current_user)


@router.get("/policies/{policy_id}/history", response_model=list[PolicyHistoryEntry])
async def policy_history(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> list[PolicyHistoryEntry]:
    """Every term and insurer in this policy's chain, oldest first."""
    return await InsuranceService(db).history(policy_id, current_user)


@router.post("/policies/{policy_id}/renew", response_model=InsurancePolicyResponse, status_code=201)
async def renew_policy(
    policy_id: int,
    data: InsurancePolicyRenew,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> InsurancePolicyResponse:
    """Enter the next term. Allowed before the current one ends."""
    return await InsuranceService(db).renew(policy_id, data, current_user)


@router.post(
    "/policies/{policy_id}/replace", response_model=InsurancePolicyResponse, status_code=201
)
async def replace_policy(
    policy_id: int,
    data: InsurancePolicyReplace,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> InsurancePolicyResponse:
    """Switch insurers: a new policy takes over this one's vehicles."""
    return await InsuranceService(db).replace(policy_id, data, current_user)


# ---------------------------------------------------------------------------
# Vehicles on a policy
# ---------------------------------------------------------------------------


@router.post(
    "/policies/{policy_id}/vehicles", response_model=InsurancePolicyResponse, status_code=201
)
async def attach_vehicle(
    policy_id: int,
    data: PolicyVehicleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> InsurancePolicyResponse:
    return await InsuranceService(db).attach_vehicle(policy_id, data, current_user)


@router.patch("/policies/{policy_id}/vehicles/{link_id}", response_model=InsurancePolicyResponse)
async def update_policy_vehicle(
    policy_id: int,
    link_id: int,
    data: PolicyVehicleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> InsurancePolicyResponse:
    return await InsuranceService(db).update_link(policy_id, link_id, data, current_user)


@router.delete("/policies/{policy_id}/vehicles/{link_id}", response_model=InsurancePolicyResponse)
async def detach_vehicle(
    policy_id: int,
    link_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> InsurancePolicyResponse:
    return await InsuranceService(db).detach_vehicle(policy_id, link_id, current_user)


@vehicle_insurance_router.get("/{vin}/insurance", response_model=list[InsurancePolicyResponse])
async def list_vehicle_insurance(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> list[InsurancePolicyResponse]:
    """Every policy, past and present, covering one vehicle."""
    return await InsuranceService(db).list_policies_for_vin(vin, current_user)


# ---------------------------------------------------------------------------
# Document parsing (dry runs: nothing is persisted)
# ---------------------------------------------------------------------------


async def _read_upload(file: UploadFile) -> bytes:
    extension = (
        "." + file.filename.lower().split(".")[-1] if file.filename and "." in file.filename else ""
    )
    if extension not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, detail=f"File must be PDF or image (jpg, png). Got: {extension}"
        )
    # Size BEFORE reading into memory, to prevent a memory DoS.
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File size exceeds 25MB limit")
    return await file.read()


@router.post("/parse-pdf")
async def parse_insurance_pdf(
    file: UploadFile = File(...),
    provider: str | None = Query(
        None, description="Optional provider hint (progressive, statefarm, geico, allstate)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> dict[str, Any]:
    """Read a declarations page and return what it says, persisting nothing.

    `vehicles` lists every VIN on the document with its own premium and
    deductible where the parser finds a per-vehicle section. `matched` marks
    the ones the caller has WRITE access to, which is what attaching one takes.
    """
    contents = await _read_upload(file)
    try:
        parsed = await document_ocr_service.extract_insurance_data(
            file_bytes=contents, provider_hint=provider
        )
        if not parsed.get("success"):
            raise ValueError(parsed.get("error", "Failed to extract data"))

        # Only plain, user-facing warnings: never anything resembling a trace.
        warnings = [
            str(w)
            for w in parsed.get("validation_warnings", [])
            if not any(
                marker in str(w).lower()
                for marker in ("traceback", "exception", "error:", "line ", "file ")
            )
        ]

        attachable = await InsuranceService(db).attachable_vehicles(current_user)
        details = parsed.get("vehicle_details", {})
        vehicles = []
        for found in parsed.get("vehicles_found", []):
            vin = found.upper()
            figures = details.get(vin, {})
            vehicles.append(
                {
                    "vin": vin,
                    "matched": vin in attachable,
                    "vehicle_name": attachable.get(vin),
                    "premium_share": figures.get("premium_amount"),
                    "deductible": figures.get("deductible"),
                }
            )

        logger.info(
            "Parsed insurance document with %s: %d vehicle(s), confidence %.0f%%",
            sanitize_for_log(str(parsed.get("parser_name"))),
            len(vehicles),
            parsed.get("confidence_score", 0),
        )
        return {
            "success": True,
            "data": {
                "provider": parsed.get("provider"),
                "policy_number": parsed.get("policy_number"),
                "policy_type": parsed.get("policy_type"),
                "start_date": parsed.get("start_date"),
                "end_date": parsed.get("end_date"),
                "premium_amount": parsed.get("premium_amount"),
                "premium_frequency": parsed.get("premium_frequency"),
                "deductible": parsed.get("deductible"),
                "coverage_limits": parsed.get("coverage_limits"),
                "notes": parsed.get("notes"),
            },
            "vehicles": vehicles,
            "confidence": parsed.get("field_confidence", {}),
            "confidence_score": parsed.get("confidence_score", 0),
            "parser_used": parsed.get("parser_name"),
            "warnings": warnings,
        }
    except ValueError as e:
        logger.error("Document parsing error: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=400, detail="Invalid insurance document format")
    except OSError as e:
        logger.error("File system error parsing document: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=500, detail="Error reading uploaded document")


@router.get("/parsers")
async def list_insurance_parsers(
    current_user: User | None = Depends(require_auth),
) -> dict[str, Any]:
    """List available insurance document parsers."""
    return {
        "parsers": document_ocr_service.list_available_insurance_parsers(),
        "ocr_status": document_ocr_service.get_ocr_status(),
    }


@router.post("/test-parse")
async def test_parse_insurance_pdf(
    file: UploadFile = File(...),
    provider: str | None = Query(None, description="Optional provider hint"),
    current_user: User | None = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Debug parse, returning the document's full raw text.

    ADMIN only: a declarations page names every driver, address and VIN in the
    household, and this endpoint returns all of it verbatim.
    """
    contents = await _read_upload(file)
    return await document_ocr_service.test_insurance_extraction(
        file_bytes=contents, provider_hint=provider
    )
