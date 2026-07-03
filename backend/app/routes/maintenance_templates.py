"""Maintenance Template API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.maintenance_template import MaintenanceTemplate
from app.models.user import User
from app.schemas.maintenance_template import (
    MaintenanceTemplateListResponse,
    MaintenanceTemplateResponse,
    TemplateApplyRequest,
    TemplateSearchResponse,
)
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.maintenance_template_service import MaintenanceTemplateService
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

maintenance_templates_router = APIRouter(
    prefix="/api/maintenance-templates", tags=["Maintenance Templates"]
)


@maintenance_templates_router.get("/search", response_model=TemplateSearchResponse)
async def search_template(
    year: int,
    make: str,
    model: str,
    duty_type: str = "normal",
    fuel_type: str | None = None,
    current_user: User | None = Depends(require_auth),
):
    """
    Search for a maintenance template for a specific vehicle.

    Query parameters:
    - year: Vehicle year
    - make: Vehicle manufacturer
    - model: Vehicle model
    - duty_type: "normal" or "severe" (default: "normal")
    - fuel_type: Optional fuel type ("Diesel", "Gasoline", etc.)

    Returns template metadata if found, 404 status if not available.
    """
    service = MaintenanceTemplateService()

    try:
        result = await service.find_template_for_vehicle(
            year=year, make=make, model=model, duty_type=duty_type, fuel_type=fuel_type
        )

        if result is None:
            return TemplateSearchResponse(
                found=False,
                error=f"No template found for {year} {make} {model} ({duty_type} duty, {fuel_type})",
            )

        template_path, template_data = result
        template_url = f"{service.github_base_url}/{template_path}"

        return TemplateSearchResponse(
            found=True,
            template_url=template_url,
            template_path=template_path,
            template_data=template_data,
        )

    except Exception as e:
        logger.error("Error searching for template: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=500, detail="Failed to search for template")


@maintenance_templates_router.post(
    "/apply",
    status_code=410,
    responses={
        410: {
            "description": (
                "Gone — template application was removed with the schedule "
                "system. Use the Reminders system instead."
            )
        }
    },
)
async def apply_template(
    request: TemplateApplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Deprecated: template application was removed with the schedule system.

    The maintenance-schedule tables this created rows in were dropped in the
    maintenance overhaul (migration 049 era); since then the service was a
    silent no-op that recorded a template row and created zero reminders
    while this endpoint reported success. Fail loudly instead.

    Auth and vehicle access are still checked first so 401/403/404 semantics
    are unchanged for clients.
    """
    # Same gate the working endpoint had (write-share, D-4) — keeps
    # unauthorized/unknown-VIN responses identical to the pre-410 behavior.
    await get_vehicle_or_403(request.vin, current_user, db, require_write=True)

    raise HTTPException(
        status_code=410,
        detail=(
            "Maintenance-template application was removed along with the "
            "schedule system. Create service reminders instead (vehicle "
            "Tracking -> Reminders); template search remains available for "
            "reference."
        ),
    )


@maintenance_templates_router.get("/vehicles/{vin}", response_model=MaintenanceTemplateListResponse)
async def get_vehicle_templates(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Get all templates that have been applied to a vehicle."""
    await get_vehicle_or_403(vin, current_user, db)

    # Get applied templates
    service = MaintenanceTemplateService()
    templates = await service.get_applied_templates(db, vin)

    return MaintenanceTemplateListResponse(
        templates=[MaintenanceTemplateResponse.model_validate(t) for t in templates],
        total=len(templates),
    )


@maintenance_templates_router.delete("/vehicles/{vin}/{template_id}", status_code=204)
async def delete_template_record(
    vin: str,
    template_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Delete a maintenance template application record.

    Note: This does NOT delete the reminders that were created from the template.
    It only removes the record of the template being applied.
    """
    # Child-record delete -> write-share required (D-4).
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    result = await db.execute(
        select(MaintenanceTemplate).where(
            MaintenanceTemplate.id == template_id, MaintenanceTemplate.vin == vin
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template record not found")

    await db.execute(delete(MaintenanceTemplate).where(MaintenanceTemplate.id == template_id))
    await db.commit()

    logger.info("Deleted template record %s for vehicle %s", template_id, sanitize_for_log(vin))
    return None
