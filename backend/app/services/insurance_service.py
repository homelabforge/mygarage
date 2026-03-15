"""Insurance policy business logic service layer."""

import logging

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InsurancePolicy as InsurancePolicyModel
from app.models.user import User
from app.schemas.insurance import (
    InsurancePolicy,
    InsurancePolicyCreate,
    InsurancePolicyUpdate,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class InsuranceService:
    """Service for managing insurance policy business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_policies(
        self,
        vin: str,
        current_user: User,
    ) -> list[InsurancePolicy]:
        """Get all insurance policies for a vehicle.

        Returns:
            List of insurance policy responses.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(InsurancePolicyModel)
                .where(InsurancePolicyModel.vin == vin)
                .order_by(InsurancePolicyModel.end_date.desc())
            )
            policies = result.scalars().all()

            return [InsurancePolicy.model_validate(p) for p in policies]

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing insurance policies for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_policy(self, vin: str, policy_id: int, current_user: User) -> InsurancePolicy:
        """Get a specific insurance policy by ID."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)

        result = await self.db.execute(
            select(InsurancePolicyModel).where(
                InsurancePolicyModel.vin == vin, InsurancePolicyModel.id == policy_id
            )
        )
        policy = result.scalar_one_or_none()

        if not policy:
            raise HTTPException(status_code=404, detail=f"Insurance policy {policy_id} not found")

        return InsurancePolicy.model_validate(policy)

    async def create_policy(
        self, vin: str, data: InsurancePolicyCreate, current_user: User
    ) -> InsurancePolicy:
        """Create a new insurance policy."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            policy_dict = data.model_dump()
            policy_dict["vin"] = vin

            policy = InsurancePolicyModel(**policy_dict)
            self.db.add(policy)
            await self.db.commit()
            await self.db.refresh(policy)

            logger.info(
                "Created insurance policy %s for %s",
                policy.id,
                sanitize_for_log(vin),
            )

            return InsurancePolicy.model_validate(policy)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating insurance policy for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid insurance policy")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating insurance policy for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_policy(
        self,
        vin: str,
        policy_id: int,
        data: InsurancePolicyUpdate,
        current_user: User,
    ) -> InsurancePolicy:
        """Update an existing insurance policy."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(InsurancePolicyModel).where(
                    InsurancePolicyModel.vin == vin, InsurancePolicyModel.id == policy_id
                )
            )
            policy = result.scalar_one_or_none()

            if not policy:
                raise HTTPException(
                    status_code=404, detail=f"Insurance policy {policy_id} not found"
                )

            update_data = data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(policy, field, value)

            await self.db.commit()
            await self.db.refresh(policy)

            logger.info(
                "Updated insurance policy %s for %s",
                policy_id,
                sanitize_for_log(vin),
            )

            return InsurancePolicy.model_validate(policy)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating insurance policy %s for %s: %s",
                policy_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating insurance policy %s for %s: %s",
                policy_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_policy(self, vin: str, policy_id: int, current_user: User) -> None:
        """Delete an insurance policy."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(InsurancePolicyModel).where(
                    InsurancePolicyModel.vin == vin, InsurancePolicyModel.id == policy_id
                )
            )
            policy = result.scalar_one_or_none()

            if not policy:
                raise HTTPException(
                    status_code=404, detail=f"Insurance policy {policy_id} not found"
                )

            await self.db.execute(
                delete(InsurancePolicyModel).where(
                    InsurancePolicyModel.vin == vin, InsurancePolicyModel.id == policy_id
                )
            )
            await self.db.commit()

            logger.info(
                "Deleted insurance policy %s for %s",
                policy_id,
                sanitize_for_log(vin),
            )

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting insurance policy %s for %s: %s",
                policy_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete policy with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting insurance policy %s for %s: %s",
                policy_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")
