"""Pydantic schemas for Family Multi-User System operations.

Includes schemas for:
- Vehicle transfers (ownership changes)
- Vehicle sharing (read/write permissions)
- Shareable users list
- Family dashboard
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# =============================================================================
# User Minimal Schemas (for embedding in other responses)
# =============================================================================


class UserMinimal(BaseModel):
    """Minimal user info for embedding in responses."""

    id: int
    username: str
    full_name: str | None = None
    relationship: str | None = None

    model_config = {"from_attributes": True}


class ShareableUser(BaseModel):
    """User info for sharing dropdowns (minimal, privacy-focused)."""

    id: int
    display_name: str  # full_name or username
    relationship: str | None = None


# =============================================================================
# Vehicle Transfer Schemas
# =============================================================================


class VehicleTransferRequest(BaseModel):
    """Request to transfer vehicle ownership."""

    to_user_id: int = Field(..., description="User ID of the new owner")
    transfer_notes: str | None = Field(
        None,
        max_length=1000,
        description="Optional notes about the transfer",
    )
    data_included: dict[str, bool] = Field(
        default_factory=lambda: {
            "service_records": True,
            "fuel_logs": True,
            "documents": True,
            "reminders": True,
            "notes": True,
            "expenses": True,
            "photos": True,
        },
        description="Which data categories to include in transfer (for audit)",
    )


class VehicleTransferResponse(BaseModel):
    """Response after a vehicle transfer."""

    id: int
    vehicle_vin: str
    from_user: UserMinimal
    to_user: UserMinimal
    transferred_at: datetime
    transferred_by: UserMinimal
    transfer_notes: str | None
    data_included: dict[str, bool] | None = None

    model_config = {"from_attributes": True}


class EligibleRecipient(BaseModel):
    """User eligible to receive a vehicle transfer."""

    id: int
    username: str
    full_name: str | None = None
    relationship: str | None = None

    model_config = {"from_attributes": True}


class TransferHistoryResponse(BaseModel):
    """Transfer history for a vehicle."""

    transfers: list[VehicleTransferResponse]
    total: int


# =============================================================================
# Vehicle Sharing Schemas
# =============================================================================


PermissionType = Literal["read", "write"]


class VehicleShareCreate(BaseModel):
    """Request to share a vehicle with another user."""

    user_id: int = Field(..., description="User ID to share with")
    permission: PermissionType = Field(
        default="read",
        description="Permission level: 'read' for view-only, 'write' for add records",
    )


class VehicleShareUpdate(BaseModel):
    """Request to update share permission."""

    permission: PermissionType = Field(
        ...,
        description="New permission level",
    )


class VehicleShareResponse(BaseModel):
    """Response for a vehicle share."""

    id: int
    vehicle_vin: str
    user: UserMinimal
    permission: str
    shared_by: UserMinimal
    shared_at: datetime

    model_config = {"from_attributes": True}


class VehicleSharesListResponse(BaseModel):
    """List of shares for a vehicle."""

    shares: list[VehicleShareResponse]
    total: int


class ShareableUsersResponse(BaseModel):
    """List of users available for sharing."""

    users: list[ShareableUser]


# =============================================================================
# Family Dashboard Schemas (for Phase 5)
# =============================================================================


class FamilyVehicleSummary(BaseModel):
    """Vehicle summary for family dashboard."""

    vin: str
    nickname: str
    year: int | None = None
    make: str | None = None
    model: str | None = None
    main_photo: str | None = None
    last_service_date: datetime | None = None
    last_service_description: str | None = None
    next_reminder_description: str | None = None
    next_reminder_due: str | None = None  # Could be date or mileage
    overdue_reminders: int = 0


class FamilyMemberData(BaseModel):
    """Family member data for dashboard."""

    id: int
    username: str
    full_name: str | None = None
    relationship: str | None = None
    relationship_custom: str | None = None
    vehicle_count: int = 0
    vehicles: list[FamilyVehicleSummary] = Field(default_factory=list)
    overdue_reminders: int = 0
    upcoming_reminders: int = 0
    # Dashboard management fields
    show_on_family_dashboard: bool = True
    family_dashboard_order: int = 0


class FamilyDashboardResponse(BaseModel):
    """Family dashboard response."""

    members: list[FamilyMemberData]
    total_members: int
    total_vehicles: int
    total_overdue_reminders: int
    total_upcoming_reminders: int


class FamilyMemberUpdateRequest(BaseModel):
    """Update family dashboard membership."""

    show_on_family_dashboard: bool = Field(
        ...,
        description="Whether to show this user on the family dashboard",
    )
    family_dashboard_order: int | None = Field(
        None,
        ge=0,
        description="Display order on family dashboard",
    )
