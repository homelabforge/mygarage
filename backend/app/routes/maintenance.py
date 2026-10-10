"""Maintenance types and per-vehicle maintenance rules.

The rules endpoints are the EXPLICIT path: `POST` creates a rule even when
the vehicle already has one of the type (a twin-engine boat, a severe-service
schedule beside the normal one). Every ordinary path (packs, the reminder
form, a line item's recurrence) reuses the vehicle's rule of the type instead.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.maintenance import (
    MaintenanceRuleCreate,
    MaintenanceRuleResponse,
    MaintenanceRuleUpdate,
    MaintenanceTypeResponse,
)
from app.services import maintenance_service
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.logging_utils import sanitize_for_log
from app.utils.maintenance_types import all_types

logger = logging.getLogger(__name__)

types_router = APIRouter(prefix="/api/maintenance-types", tags=["Maintenance"])
rules_router = APIRouter(prefix="/api/vehicles/{vin}/maintenance-rules", tags=["Maintenance"])


@types_router.get("", response_model=list[MaintenanceTypeResponse])
async def list_maintenance_types(current_user: User | None = Depends(require_auth)):
    """The canonical maintenance types, in registry order, for pickers."""
    return [
        MaintenanceTypeResponse(code=t.code, label=t.label, category=t.category)
        for t in all_types()
    ]


@rules_router.get("", response_model=list[MaintenanceRuleResponse])
async def list_rules(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Every maintenance rule on the vehicle, active first."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db)
    return await maintenance_service.list_rules(db, vin)


@rules_router.post("", response_model=MaintenanceRuleResponse, status_code=201)
async def create_rule(
    vin: str,
    data: MaintenanceRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Create a rule explicitly (a second rule of a type is allowed here)."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    await lock_vehicle_for_write(db, vin)
    rule = await maintenance_service.create_rule(db, vin, data)
    await db.commit()
    await db.refresh(rule)
    return rule


@rules_router.put("/{rule_id}", response_model=MaintenanceRuleResponse)
async def update_rule(
    vin: str,
    rule_id: int,
    data: MaintenanceRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Edit a rule's intervals, title, type or activity; its pending reminder follows."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    await lock_vehicle_for_write(db, vin)
    rule = await maintenance_service.get_rule_or_404(db, vin, rule_id)
    await maintenance_service.update_rule(db, rule, data)
    await db.commit()
    await db.refresh(rule)
    return rule


@rules_router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    vin: str,
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Remove a rule nothing references; deactivate one with history."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    await lock_vehicle_for_write(db, vin)
    rule = await maintenance_service.get_rule_or_404(db, vin, rule_id)
    outcome = await maintenance_service.delete_rule(db, rule)
    await db.commit()
    logger.info(
        "Maintenance rule %s on %s: %s", sanitize_for_log(rule_id), sanitize_for_log(vin), outcome
    )
    return None
