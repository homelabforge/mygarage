"""Toll tag and transaction business logic service layer."""

import datetime as dt
import logging
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import is_sqlite
from app.models.toll import TollTag, TollTransaction
from app.models.user import User
from app.schemas.toll import (
    TollTagCreate,
    TollTagListResponse,
    TollTagResponse,
    TollTagUpdate,
    TollTransactionCreate,
    TollTransactionListResponse,
    TollTransactionResponse,
    TollTransactionSummary,
    TollTransactionUpdate,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class TollService:
    """Service for managing toll tag and transaction business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Toll Tags ──────────────────────────────────────────────────────

    async def list_tags(
        self,
        vin: str,
        current_user: User,
    ) -> TollTagListResponse:
        """Get all toll tags for a vehicle."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(TollTag).where(TollTag.vin == vin).order_by(TollTag.created_at.desc())
            )
            toll_tags = result.scalars().all()

            return TollTagListResponse(
                toll_tags=[TollTagResponse.model_validate(tag) for tag in toll_tags],
                total=len(toll_tags),
            )

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing toll tags for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_tag(
        self,
        vin: str,
        tag_id: int,
        current_user: User,
    ) -> TollTagResponse:
        """Get a specific toll tag by ID."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(TollTag).where(TollTag.id == tag_id, TollTag.vin == vin)
            )
            toll_tag = result.scalar_one_or_none()
            if not toll_tag:
                raise HTTPException(status_code=404, detail="Toll tag not found")

            return TollTagResponse.model_validate(toll_tag)

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error getting toll tag %s for %s: %s",
                tag_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def create_tag(
        self,
        vin: str,
        data: TollTagCreate,
        current_user: User,
    ) -> TollTagResponse:
        """Create a new toll tag for a vehicle."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            db_toll_tag = TollTag(
                vin=vin,
                toll_system=data.toll_system,
                tag_number=data.tag_number,
                status=data.status,
                notes=data.notes,
            )
            self.db.add(db_toll_tag)
            await self.db.commit()
            await self.db.refresh(db_toll_tag)

            logger.info(
                "Created toll tag %s for %s",
                db_toll_tag.id,
                sanitize_for_log(vin),
            )

            return TollTagResponse.model_validate(db_toll_tag)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating toll tag for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid toll tag")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating toll tag for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_tag(
        self,
        vin: str,
        tag_id: int,
        data: TollTagUpdate,
        current_user: User,
    ) -> TollTagResponse:
        """Update an existing toll tag."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(TollTag).where(TollTag.id == tag_id, TollTag.vin == vin)
            )
            toll_tag = result.scalar_one_or_none()
            if not toll_tag:
                raise HTTPException(status_code=404, detail="Toll tag not found")

            update_data = data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(toll_tag, field, value)

            await self.db.commit()
            await self.db.refresh(toll_tag)

            logger.info(
                "Updated toll tag %s for %s",
                tag_id,
                sanitize_for_log(vin),
            )

            return TollTagResponse.model_validate(toll_tag)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating toll tag %s for %s: %s",
                tag_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating toll tag %s for %s: %s",
                tag_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_tag(
        self,
        vin: str,
        tag_id: int,
        current_user: User,
    ) -> None:
        """Delete a toll tag."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(TollTag).where(TollTag.id == tag_id, TollTag.vin == vin)
            )
            toll_tag = result.scalar_one_or_none()
            if not toll_tag:
                raise HTTPException(status_code=404, detail="Toll tag not found")

            await self.db.execute(delete(TollTag).where(TollTag.id == tag_id, TollTag.vin == vin))
            await self.db.commit()

            logger.info(
                "Deleted toll tag %s for %s",
                tag_id,
                sanitize_for_log(vin),
            )

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting toll tag %s for %s: %s",
                tag_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=409, detail="Cannot delete tag with dependent transactions"
            )
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting toll tag %s for %s: %s",
                tag_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    # ── Toll Transactions ──────────────────────────────────────────────

    async def list_transactions(
        self,
        vin: str,
        current_user: User,
        start_date: dt.date | None = None,
        end_date: dt.date | None = None,
        toll_tag_id: int | None = None,
    ) -> TollTransactionListResponse:
        """Get all toll transactions for a vehicle with optional filtering."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            query = select(TollTransaction).where(TollTransaction.vin == vin)

            if start_date:
                query = query.where(TollTransaction.date >= start_date)
            if end_date:
                query = query.where(TollTransaction.date <= end_date)
            if toll_tag_id:
                query = query.where(TollTransaction.toll_tag_id == toll_tag_id)

            query = query.order_by(TollTransaction.date.desc())

            result = await self.db.execute(query)
            transactions = result.scalars().all()

            return TollTransactionListResponse(
                transactions=[TollTransactionResponse.model_validate(txn) for txn in transactions],
                total=len(transactions),
            )

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing toll transactions for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_transaction(
        self,
        vin: str,
        transaction_id: int,
        current_user: User,
    ) -> TollTransactionResponse:
        """Get a specific toll transaction by ID."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(TollTransaction).where(
                    TollTransaction.id == transaction_id, TollTransaction.vin == vin
                )
            )
            transaction = result.scalar_one_or_none()
            if not transaction:
                raise HTTPException(status_code=404, detail="Toll transaction not found")

            return TollTransactionResponse.model_validate(transaction)

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error getting toll transaction %s for %s: %s",
                transaction_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def create_transaction(
        self,
        vin: str,
        data: TollTransactionCreate,
        current_user: User,
    ) -> TollTransactionResponse:
        """Create a new toll transaction for a vehicle."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            # Verify toll tag exists if provided
            if data.toll_tag_id:
                tag_result = await self.db.execute(
                    select(TollTag).where(TollTag.id == data.toll_tag_id, TollTag.vin == vin)
                )
                toll_tag = tag_result.scalar_one_or_none()
                if not toll_tag:
                    raise HTTPException(status_code=404, detail="Toll tag not found")

            db_transaction = TollTransaction(
                vin=vin,
                toll_tag_id=data.toll_tag_id,
                date=data.transaction_date,
                amount=data.amount,
                location=data.location,
                notes=data.notes,
            )
            self.db.add(db_transaction)
            await self.db.commit()
            await self.db.refresh(db_transaction)

            logger.info(
                "Created toll transaction %s for %s",
                db_transaction.id,
                sanitize_for_log(vin),
            )

            return TollTransactionResponse.model_validate(db_transaction)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating toll transaction for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid toll transaction")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating toll transaction for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_transaction(
        self,
        vin: str,
        transaction_id: int,
        data: TollTransactionUpdate,
        current_user: User,
    ) -> TollTransactionResponse:
        """Update an existing toll transaction."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(TollTransaction).where(
                    TollTransaction.id == transaction_id, TollTransaction.vin == vin
                )
            )
            transaction = result.scalar_one_or_none()
            if not transaction:
                raise HTTPException(status_code=404, detail="Toll transaction not found")

            # Verify toll tag exists if being updated
            if data.toll_tag_id:
                tag_result = await self.db.execute(
                    select(TollTag).where(TollTag.id == data.toll_tag_id, TollTag.vin == vin)
                )
                toll_tag = tag_result.scalar_one_or_none()
                if not toll_tag:
                    raise HTTPException(status_code=404, detail="Toll tag not found")

            update_data = data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(transaction, field, value)

            await self.db.commit()
            await self.db.refresh(transaction)

            logger.info(
                "Updated toll transaction %s for %s",
                transaction_id,
                sanitize_for_log(vin),
            )

            return TollTransactionResponse.model_validate(transaction)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating toll transaction %s for %s: %s",
                transaction_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating toll transaction %s for %s: %s",
                transaction_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_transaction(
        self,
        vin: str,
        transaction_id: int,
        current_user: User,
    ) -> None:
        """Delete a toll transaction."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(TollTransaction).where(
                    TollTransaction.id == transaction_id, TollTransaction.vin == vin
                )
            )
            transaction = result.scalar_one_or_none()
            if not transaction:
                raise HTTPException(status_code=404, detail="Toll transaction not found")

            await self.db.execute(
                delete(TollTransaction).where(
                    TollTransaction.id == transaction_id, TollTransaction.vin == vin
                )
            )
            await self.db.commit()

            logger.info(
                "Deleted toll transaction %s for %s",
                transaction_id,
                sanitize_for_log(vin),
            )

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting toll transaction %s for %s: %s",
                transaction_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=409, detail="Cannot delete transaction with dependent data"
            )
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting toll transaction %s for %s: %s",
                transaction_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_summary(
        self,
        vin: str,
        current_user: User,
    ) -> TollTransactionSummary:
        """Get toll transaction summary and monthly statistics."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            # Get total count and amount
            result = await self.db.execute(
                select(func.count(TollTransaction.id), func.sum(TollTransaction.amount)).where(
                    TollTransaction.vin == vin
                )
            )
            total_count, total_amount = result.one()

            # Get monthly totals (dialect-aware date formatting)
            if is_sqlite:
                month_col = func.strftime("%Y-%m", TollTransaction.date).label("month")
            else:
                month_col = func.to_char(TollTransaction.date, "YYYY-MM").label("month")
            result = await self.db.execute(
                select(
                    month_col,
                    func.count(TollTransaction.id).label("count"),
                    func.sum(TollTransaction.amount).label("amount"),
                )
                .where(TollTransaction.vin == vin)
                .group_by(month_col)
                .order_by(month_col.desc())
            )
            monthly_data = result.all()

            monthly_totals = [
                {
                    "month": row.month,
                    "count": row.count,
                    "amount": float(row.amount) if row.amount else 0.0,
                }
                for row in monthly_data
            ]

            return TollTransactionSummary(
                total_transactions=total_count or 0,
                total_amount=total_amount or Decimal("0.00"),
                monthly_totals=monthly_totals,
            )

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error getting toll summary for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")
