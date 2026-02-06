"""Family dashboard service for aggregating family member vehicle data."""

# pyright: reportOptionalOperand=false, reportReturnType=false

from __future__ import annotations

import logging
from datetime import date

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminder import Reminder
from app.models.service import ServiceRecord
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.family import (
    FamilyDashboardResponse,
    FamilyMemberData,
    FamilyMemberUpdateRequest,
    FamilyVehicleSummary,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class FamilyDashboardService:
    """Service for managing the family dashboard."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_family_dashboard(
        self,
        current_user: User,
    ) -> FamilyDashboardResponse:
        """
        Get family dashboard data.

        Returns data for all users marked for family dashboard display,
        plus the admin's own vehicles.

        Args:
            current_user: Admin user requesting the dashboard

        Returns:
            FamilyDashboardResponse with aggregated family data

        Raises:
            HTTPException 403: If user is not admin
        """
        if not current_user.is_admin:
            raise HTTPException(
                status_code=403,
                detail="Admin privileges required for family dashboard",
            )

        try:
            # Get users marked for family dashboard, ordered by display order
            result = await self.db.execute(
                select(User)
                .where(
                    User.is_active == True,  # noqa: E712
                    User.show_on_family_dashboard == True,  # noqa: E712
                )
                .order_by(User.family_dashboard_order, User.username)
            )
            dashboard_users = list(result.scalars().all())

            # Ensure admin is always included (at position 0 if not already in list)
            admin_in_list = any(u.id == current_user.id for u in dashboard_users)
            if not admin_in_list:
                # Prepend admin to the list
                dashboard_users.insert(0, current_user)

            # Build member data for each user
            members: list[FamilyMemberData] = []
            total_vehicles = 0
            total_overdue = 0
            total_upcoming = 0

            for user in dashboard_users:
                member_data = await self._build_member_data(user)
                members.append(member_data)
                total_vehicles += member_data.vehicle_count
                total_overdue += member_data.overdue_reminders
                total_upcoming += member_data.upcoming_reminders

            return FamilyDashboardResponse(
                members=members,
                total_members=len(members),
                total_vehicles=total_vehicles,
                total_overdue_reminders=total_overdue,
                total_upcoming_reminders=total_upcoming,
            )

        except OperationalError as e:
            logger.error("Database error getting family dashboard: %s", sanitize_for_log(e))
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            )

    async def _build_member_data(self, user: User) -> FamilyMemberData:
        """Build member data with vehicles and reminder counts."""
        # Get vehicles owned by this user (not archived)
        result = await self.db.execute(
            select(Vehicle)
            .where(
                Vehicle.user_id == user.id,
                Vehicle.archived_at.is_(None),
            )
            .order_by(Vehicle.nickname)
        )
        vehicles = result.scalars().all()

        vehicle_summaries: list[FamilyVehicleSummary] = []
        member_overdue = 0
        member_upcoming = 0

        for vehicle in vehicles:
            summary = await self._build_vehicle_summary(vehicle)
            vehicle_summaries.append(summary)
            member_overdue += summary.overdue_reminders
            # Count upcoming reminders (not overdue)
            if summary.next_reminder_due is not None:
                member_upcoming += 1

        return FamilyMemberData(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            relationship=user.relationship,
            relationship_custom=user.relationship_custom,
            vehicle_count=len(vehicle_summaries),
            vehicles=vehicle_summaries,
            overdue_reminders=member_overdue,
            upcoming_reminders=member_upcoming,
            show_on_family_dashboard=user.show_on_family_dashboard,
            family_dashboard_order=user.family_dashboard_order,
        )

    async def _build_vehicle_summary(self, vehicle: Vehicle) -> FamilyVehicleSummary:
        """Build a vehicle summary with service and reminder info."""
        today = date.today()

        # Get last service record
        last_service_result = await self.db.execute(
            select(ServiceRecord)
            .where(ServiceRecord.vin == vehicle.vin)
            .order_by(ServiceRecord.date.desc())
            .limit(1)
        )
        last_service = last_service_result.scalar_one_or_none()

        # Get overdue reminders count (due_date in the past, not completed)
        overdue_result = await self.db.execute(
            select(func.count())
            .select_from(Reminder)
            .where(
                Reminder.vin == vehicle.vin,
                Reminder.is_completed == False,  # noqa: E712
                Reminder.due_date.isnot(None),
                Reminder.due_date < today,
            )
        )
        overdue_count = overdue_result.scalar() or 0

        # Get next upcoming reminder (not completed, due_date >= today, ordered by due_date)
        next_reminder_result = await self.db.execute(
            select(Reminder)
            .where(
                Reminder.vin == vehicle.vin,
                Reminder.is_completed == False,  # noqa: E712
                Reminder.due_date.isnot(None),
                Reminder.due_date >= today,
            )
            .order_by(Reminder.due_date)
            .limit(1)
        )
        next_reminder = next_reminder_result.scalar_one_or_none()

        # Format next reminder due info
        next_reminder_description = None
        next_reminder_due = None
        if next_reminder:
            next_reminder_description = next_reminder.description
            if next_reminder.due_date:
                next_reminder_due = next_reminder.due_date.isoformat()
            elif next_reminder.due_mileage:
                next_reminder_due = f"{next_reminder.due_mileage:,} miles"

        return FamilyVehicleSummary(
            vin=vehicle.vin,
            nickname=vehicle.nickname,
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            main_photo=vehicle.main_photo,
            last_service_date=last_service.date if last_service else None,
            last_service_description=last_service.service_type if last_service else None,
            next_reminder_description=next_reminder_description,
            next_reminder_due=next_reminder_due,
            overdue_reminders=overdue_count,
        )

    async def update_member_display(
        self,
        user_id: int,
        update_request: FamilyMemberUpdateRequest,
        current_user: User,
    ) -> FamilyMemberData:
        """
        Update a user's family dashboard display settings.

        Args:
            user_id: User ID to update
            update_request: New display settings
            current_user: Admin user making the update

        Returns:
            Updated FamilyMemberData

        Raises:
            HTTPException 403: If user is not admin
            HTTPException 404: If user not found
        """
        if not current_user.is_admin:
            raise HTTPException(
                status_code=403,
                detail="Admin privileges required to update dashboard settings",
            )

        try:
            # Get the user
            result = await self.db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            # Update display settings
            user.show_on_family_dashboard = update_request.show_on_family_dashboard

            if update_request.family_dashboard_order is not None:
                user.family_dashboard_order = update_request.family_dashboard_order

            await self.db.commit()
            await self.db.refresh(user)

            logger.info(
                "Updated family dashboard settings for user %s (show=%s, order=%s) by admin %s",
                user.username,
                update_request.show_on_family_dashboard,
                update_request.family_dashboard_order,
                current_user.username,
            )

            # Return updated member data
            return await self._build_member_data(user)

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error("Database error updating member display: %s", sanitize_for_log(e))
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            )

    async def get_all_users_for_dashboard_management(
        self,
        current_user: User,
    ) -> list[FamilyMemberData]:
        """
        Get all active users for dashboard management.

        Returns all active users with their current dashboard settings,
        allowing admin to toggle visibility and set order.

        Args:
            current_user: Admin user requesting the list

        Returns:
            List of FamilyMemberData for all active users

        Raises:
            HTTPException 403: If user is not admin
        """
        if not current_user.is_admin:
            raise HTTPException(
                status_code=403,
                detail="Admin privileges required for dashboard management",
            )

        try:
            result = await self.db.execute(
                select(User)
                .where(User.is_active == True)  # noqa: E712
                .order_by(User.family_dashboard_order, User.username)
            )
            users = result.scalars().all()

            members: list[FamilyMemberData] = []
            for user in users:
                member_data = await self._build_member_data(user)
                members.append(member_data)

            return members

        except OperationalError as e:
            logger.error(
                "Database error getting users for dashboard management: %s", sanitize_for_log(e)
            )
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            )
