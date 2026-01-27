"""Maintenance Template API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.maintenance_template import MaintenanceTemplate
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.maintenance_template import (
    MaintenanceTemplateListResponse,
    MaintenanceTemplateResponse,
    TemplateApplyRequest,
    TemplateApplyResponse,
    TemplateSearchResponse,
)
from app.services.auth import require_auth
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
        raise HTTPException(
            status_code=500, detail=f"Failed to search for template: {str(e)}"
        )


@maintenance_templates_router.post("/apply", response_model=TemplateApplyResponse)
async def apply_template(
    request: TemplateApplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Apply a maintenance template to a vehicle.

    This will:
    1. Find the appropriate template based on vehicle year/make/model
    2. Create reminders for all maintenance items in the template
    3. Record which template was applied

    Body:
    - vin: Vehicle VIN
    - duty_type: "normal" or "severe" (default: "normal")
    - current_mileage: Current vehicle mileage (optional, for mileage-based reminders)
    """
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == request.vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Check if template already applied
    result = await db.execute(
        select(MaintenanceTemplate).where(MaintenanceTemplate.vin == request.vin)
    )
    existing_templates = result.scalars().all()

    if existing_templates:
        logger.warning(
            "Template already applied to %s, applying additional template",
            sanitize_for_log(request.vin),
        )

    # Find template
    service = MaintenanceTemplateService()

    try:
        result = await service.find_template_for_vehicle(
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            duty_type=request.duty_type,
            fuel_type=vehicle.fuel_type,
        )

        if result is None:
            return TemplateApplyResponse(
                success=False,
                reminders_created=0,
                template_source="",
                error=f"No template found for {vehicle.year} {vehicle.make} {vehicle.model} ({request.duty_type} duty, {vehicle.fuel_type})",
            )

        template_path, template_data = result

        # Apply template
        reminders_created = await service.apply_template_to_vehicle(
            db=db,
            vin=request.vin,
            template_path=template_path,
            template_data=template_data,
            current_mileage=request.current_mileage,
            created_by="manual",
        )

        return TemplateApplyResponse(
            success=True,
            reminders_created=reminders_created,
            template_source=f"github:{template_path}",
            template_version=template_data.get("metadata", {}).get("version"),
        )

    except Exception as e:
        logger.error(
            "Error applying template to %s: %s",
            sanitize_for_log(request.vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to apply template: {str(e)}"
        )


@maintenance_templates_router.get(
    "/vehicles/{vin}", response_model=MaintenanceTemplateListResponse
)
async def get_vehicle_templates(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Get all templates that have been applied to a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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
    result = await db.execute(
        select(MaintenanceTemplate).where(
            MaintenanceTemplate.id == template_id, MaintenanceTemplate.vin == vin
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template record not found")

    await db.execute(
        delete(MaintenanceTemplate).where(MaintenanceTemplate.id == template_id)
    )
    await db.commit()

    logger.info(
        "Deleted template record %s for vehicle %s", template_id, sanitize_for_log(vin)
    )
    return None
