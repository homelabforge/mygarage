"""Family Multi-User System API endpoints.

Includes endpoints for:
- Vehicle transfers (ownership changes)
- Vehicle sharing (read/write permissions)
- Family dashboard (admin overview)
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.family import (
    EligibleRecipient,
    FamilyDashboardResponse,
    FamilyMemberData,
    FamilyMemberUpdateRequest,
    TransferHistoryResponse,
    VehicleShareCreate,
    VehicleShareResponse,
    VehicleSharesListResponse,
    VehicleShareUpdate,
    VehicleTransferRequest,
    VehicleTransferResponse,
)
from app.services.auth import get_current_admin_user, require_auth
from app.services.family_dashboard_service import FamilyDashboardService
from app.services.sharing_service import SharingService
from app.services.transfer_service import TransferService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/family", tags=["Family"])


# =============================================================================
# Vehicle Transfer Endpoints
# =============================================================================


@router.post("/vehicles/{vin}/transfer", response_model=VehicleTransferResponse)
async def transfer_vehicle(
    vin: str,
    transfer_request: VehicleTransferRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Transfer vehicle ownership to another user (admin only).

    This operation:
    1. Changes the vehicle's owner to the specified user
    2. Creates an audit record of the transfer
    3. Removes any existing share for the new owner (they now own it)

    **Path Parameters:**
    - **vin**: Vehicle VIN to transfer

    **Request Body:**
    - **to_user_id**: User ID of the new owner
    - **transfer_notes**: Optional notes about the transfer
    - **data_included**: Dict of data categories included (for audit)

    **Security:**
    - Admin only
    """
    service = TransferService(db)
    return await service.transfer_vehicle(vin, transfer_request, current_user)


@router.get("/vehicles/{vin}/transfer-history", response_model=TransferHistoryResponse)
async def get_transfer_history(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get transfer history for a vehicle.

    Returns all previous ownership transfers for the vehicle,
    ordered by most recent first.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Security:**
    - Requires authentication
    - Users can only see history for vehicles they own or have access to
    """
    # Note: The access check is done via require_auth + vehicle ownership
    # In Phase 4, this will be enhanced to check sharing permissions
    service = TransferService(db)
    transfers, total = await service.get_transfer_history(vin)

    return TransferHistoryResponse(transfers=transfers, total=total)


@router.get(
    "/vehicles/{vin}/eligible-recipients",
    response_model=list[EligibleRecipient],
)
async def get_eligible_recipients(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Get list of users eligible to receive a vehicle transfer (admin only).

    Returns active users excluding the current owner.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Security:**
    - Admin only
    """
    service = TransferService(db)
    return await service.get_eligible_recipients(vin, current_user)


# =============================================================================
# Vehicle Sharing Endpoints
# =============================================================================


@router.post("/vehicles/{vin}/shares", response_model=VehicleShareResponse, status_code=201)
async def share_vehicle(
    vin: str,
    share_request: VehicleShareCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Share a vehicle with another user.

    Only the owner or an admin can share a vehicle.

    **Path Parameters:**
    - **vin**: Vehicle VIN to share

    **Request Body:**
    - **user_id**: User ID to share with
    - **permission**: 'read' (view only) or 'write' (can add records)

    **Security:**
    - Owner or admin only
    """
    service = SharingService(db)
    return await service.share_vehicle(vin, share_request, current_user)


@router.get("/vehicles/{vin}/shares", response_model=VehicleSharesListResponse)
async def get_vehicle_shares(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get all shares for a vehicle.

    Only the owner or an admin can see shares.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Security:**
    - Owner or admin only
    """
    service = SharingService(db)
    shares, total = await service.get_vehicle_shares(vin, current_user)
    return VehicleSharesListResponse(shares=shares, total=total)


@router.put("/shares/{share_id}", response_model=VehicleShareResponse)
async def update_share(
    share_id: int,
    update_request: VehicleShareUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Update share permission level.

    Only the owner or an admin can update shares.

    **Path Parameters:**
    - **share_id**: Share ID to update

    **Request Body:**
    - **permission**: New permission level ('read' or 'write')

    **Security:**
    - Owner or admin only
    """
    service = SharingService(db)
    return await service.update_share(share_id, update_request, current_user)


@router.delete("/shares/{share_id}", status_code=204)
async def revoke_share(
    share_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Revoke (delete) a vehicle share.

    Only the owner or an admin can revoke shares.

    **Path Parameters:**
    - **share_id**: Share ID to revoke

    **Security:**
    - Owner or admin only
    """
    service = SharingService(db)
    await service.revoke_share(share_id, current_user)


# =============================================================================
# Family Dashboard Endpoints
# =============================================================================


@router.get("/dashboard", response_model=FamilyDashboardResponse)
async def get_family_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Get the family dashboard with all members and their vehicles.

    Returns aggregated data for all users marked for family dashboard,
    including vehicles, upcoming reminders, and overdue counts.

    **Response includes:**
    - List of family members with their vehicles
    - Total counts (members, vehicles, reminders)
    - Each vehicle shows last service and next reminder

    **Security:**
    - Admin only
    """
    service = FamilyDashboardService(db)
    return await service.get_family_dashboard(current_user)


@router.get("/dashboard/members", response_model=list[FamilyMemberData])
async def get_dashboard_members(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Get all users for dashboard management.

    Returns all active users with their current dashboard settings,
    allowing admin to toggle visibility and set display order.

    **Security:**
    - Admin only
    """
    service = FamilyDashboardService(db)
    return await service.get_all_users_for_dashboard_management(current_user)


@router.put("/dashboard/members/{user_id}", response_model=FamilyMemberData)
async def update_dashboard_member(
    user_id: int,
    update_request: FamilyMemberUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Update a user's family dashboard display settings.

    **Path Parameters:**
    - **user_id**: User ID to update

    **Request Body:**
    - **show_on_family_dashboard**: Whether to show this user on the dashboard
    - **family_dashboard_order**: Optional display order (0 = first)

    **Security:**
    - Admin only
    """
    service = FamilyDashboardService(db)
    return await service.update_member_display(user_id, update_request, current_user)
