"""Vehicle business logic service layer."""

# pyright: reportOptionalOperand=false, reportReturnType=false

import logging
import shutil
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.fuel import has_def_capacity, is_diesel_vehicle
from app.models.attachment import Attachment
from app.models.fuel import FuelRecord
from app.models.note import Note
from app.models.service_visit import ServiceVisit
from app.models.tax import TaxRecord
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.schemas.vehicle import VehicleCreate, VehicleUpdate
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

DEF_CAPACITY_NON_DIESEL_DETAIL = "DEF tank capacity applies only to diesel vehicles"
DEF_CAPACITY_CLEAR_FIRST_DETAIL = (
    "Changing fuel type away from diesel requires clearing the DEF tank capacity first"
)


def _check_def_capacity_gate(
    *,
    fuel_type: str | None,
    fuel_type_secondary: str | None,
    def_tank_capacity_liters: Decimal | float | int | None,
    capacity_was_explicitly_set: bool,
) -> None:
    """Reject 400 when the resulting state has DEF capacity on a non-diesel vehicle.

    Evaluates the *prospective* (post-write) combination of fuel type and
    capacity. Setting capacity to None/0 is always allowed regardless of
    fuel type. When capacity is left as-is (not part of this write) but the
    resulting fuel type is non-diesel, the message tells the caller to
    clear the capacity explicitly rather than silently nulling a value the
    user set.
    """
    if not has_def_capacity(def_tank_capacity_liters):
        return
    if is_diesel_vehicle(fuel_type, fuel_type_secondary):
        return
    if capacity_was_explicitly_set:
        raise HTTPException(status_code=400, detail=DEF_CAPACITY_NON_DIESEL_DETAIL)
    raise HTTPException(status_code=400, detail=DEF_CAPACITY_CLEAR_FIRST_DETAIL)


class VehicleService:
    """Service for managing vehicle business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_vehicles(
        self, current_user: User | None, skip: int = 0, limit: int = 100
    ) -> tuple[list[Vehicle], int]:
        """
        Get list of vehicles for the current user.

        Includes both owned vehicles and vehicles shared with the user.

        Args:
            current_user: The authenticated user (None if auth_mode='none')
            skip: Number of records to skip (pagination)
            limit: Maximum number of records to return

        Returns:
            Tuple of (vehicles list, total count)
        """
        try:
            # Build ownership filter (shared across results + count queries)
            # If auth is disabled, show all vehicles
            # Admin users see all vehicles
            # Non-admin users see their own vehicles + shared vehicles
            ownership_filter = None
            if current_user is not None and not current_user.is_admin:
                shared_vins_subquery = (
                    select(VehicleShare.vehicle_vin)
                    .where(VehicleShare.user_id == current_user.id)
                    .scalar_subquery()
                )
                ownership_filter = or_(
                    Vehicle.user_id == current_user.id,
                    Vehicle.vin.in_(shared_vins_subquery),
                )

            # Get vehicles with pagination
            query = select(Vehicle).order_by(Vehicle.created_at.desc())
            if ownership_filter is not None:
                query = query.where(ownership_filter)
            result = await self.db.execute(query.offset(skip).limit(limit))
            vehicles = list(result.scalars().all())

            # Get total count with same filter
            count_query = select(func.count()).select_from(Vehicle)
            if ownership_filter is not None:
                count_query = count_query.where(ownership_filter)
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            return vehicles, total

        except OperationalError as e:
            logger.error("Database connection error listing vehicles: %s", sanitize_for_log(e))
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_vehicle(self, vin: str, current_user: User | None) -> Vehicle:
        """
        Get a specific vehicle by VIN with ownership check.

        Args:
            vin: Vehicle VIN
            current_user: The authenticated user

        Returns:
            Vehicle object

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        vehicle = await get_vehicle_or_403(vin, current_user, self.db)
        return vehicle

    async def create_vehicle(
        self, vehicle_data: VehicleCreate, current_user: User | None
    ) -> Vehicle:
        """
        Create a new vehicle.

        Args:
            vehicle_data: Vehicle creation data
            current_user: The authenticated user (will be assigned as owner, None if auth_mode='none')

        Returns:
            Created Vehicle object

        Raises:
            HTTPException: 400 if VIN already exists
        """
        try:
            # Check if VIN already exists
            result = await self.db.execute(select(Vehicle).where(Vehicle.vin == vehicle_data.vin))
            existing = result.scalar_one_or_none()

            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Vehicle with VIN {vehicle_data.vin} already exists",
                )

            # Create vehicle with ownership assigned to current user
            vehicle_dict = vehicle_data.model_dump()
            _check_def_capacity_gate(
                fuel_type=vehicle_dict.get("fuel_type"),
                fuel_type_secondary=vehicle_dict.get("fuel_type_secondary"),
                def_tank_capacity_liters=vehicle_dict.get("def_tank_capacity_liters"),
                capacity_was_explicitly_set=True,
            )
            if current_user is not None:
                vehicle_dict["user_id"] = current_user.id  # Assign ownership
                username = current_user.username
            else:
                username = "guest"

            vehicle = Vehicle(**vehicle_dict)
            self.db.add(vehicle)
            await self.db.commit()
            await self.db.refresh(vehicle)

            logger.info(
                "Created vehicle: %s (%s) for user %s",
                sanitize_for_log(vehicle.vin),
                sanitize_for_log(vehicle.nickname),
                sanitize_for_log(username),
            )

            return vehicle

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating vehicle: %s",
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=409,
                detail=f"Vehicle with VIN {vehicle_data.vin} already exists",
            )
        except OperationalError as e:
            await self.db.rollback()
            logger.error("Database connection error creating vehicle: %s", sanitize_for_log(e))
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_vehicle(
        self, vin: str, vehicle_data: VehicleUpdate, current_user: User
    ) -> Vehicle:
        """
        Update an existing vehicle.

        Args:
            vin: Vehicle VIN
            vehicle_data: Vehicle update data
            current_user: The authenticated user

        Returns:
            Updated Vehicle object

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_for_owner_or_403

        vin = vin.upper().strip()

        try:
            # Editing identity metadata (make/model/VIN/nickname/color) is
            # OWNER-only (D-2): a write-share may add child records but must not
            # mutate the vehicle row itself.
            vehicle = await get_vehicle_for_owner_or_403(vin, current_user, self.db)

            # Update fields (only fields explicitly present in the payload)
            update_data = vehicle_data.model_dump(exclude_unset=True)
            _check_def_capacity_gate(
                fuel_type=update_data.get("fuel_type", vehicle.fuel_type),
                fuel_type_secondary=update_data.get(
                    "fuel_type_secondary", vehicle.fuel_type_secondary
                ),
                def_tank_capacity_liters=update_data.get(
                    "def_tank_capacity_liters", vehicle.def_tank_capacity_liters
                ),
                capacity_was_explicitly_set="def_tank_capacity_liters" in update_data,
            )
            for field, value in update_data.items():
                setattr(vehicle, field, value)

            await self.db.commit()
            await self.db.refresh(vehicle)

            logger.info("Updated vehicle: %s", sanitize_for_log(vehicle.vin))

            return vehicle

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating vehicle %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating vehicle %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_vehicle(self, vin: str, current_user: User) -> None:
        """
        Delete a vehicle.

        Args:
            vin: Vehicle VIN
            current_user: The authenticated user

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_for_owner_or_403

        vin = vin.upper().strip()

        try:
            # Vehicle delete is OWNER-only (D-3): even a write-share must not be
            # able to delete the vehicle and cascade its records.
            vehicle = await get_vehicle_for_owner_or_403(vin, current_user, self.db)
            sticker_path = vehicle.window_sticker_file_path

            # Attachments are polymorphic (record_type/record_id, no vehicle
            # FK), so no cascade reaches them. Resolve rows + file paths for
            # this vehicle's records before the parent rows disappear.
            attachment_ids, attachment_paths = await self._collect_vehicle_attachments(vin)
            if attachment_ids:
                await self.db.execute(delete(Attachment).where(Attachment.id.in_(attachment_ids)))

            # ORM delete, not a bulk DELETE statement: bulk deletes bypass ORM
            # relationship cascades, and on SQLite the DB-level ON DELETE
            # CASCADE clauses only fire because the engine now enforces FKs
            # (PRAGMA foreign_keys=ON). Both layers together cover every child
            # table on both engines.
            await self.db.delete(vehicle)
            await self.db.commit()

            # Filesystem cleanup only after a successful commit — a rolled-back
            # delete must not lose files.
            self._remove_vehicle_files(vin, attachment_paths, sticker_path)

            logger.info("Deleted vehicle: %s", sanitize_for_log(vin))

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting vehicle %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=409, detail="Cannot delete vehicle with dependent records"
            )
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting vehicle %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def _collect_vehicle_attachments(self, vin: str) -> tuple[list[int], list[str]]:
        """Attachment row ids + file paths belonging to a vehicle's records.

        Covers the record types that still have live parent tables
        (service_visit, fuel, tax, note). Legacy types whose parent tables
        were dropped (service, upgrade, collision) cannot be resolved to a
        VIN and are left alone.
        """
        parent_id_queries = {
            "service_visit": select(ServiceVisit.id).where(ServiceVisit.vin == vin),
            "fuel": select(FuelRecord.id).where(FuelRecord.vin == vin),
            "tax": select(TaxRecord.id).where(TaxRecord.vin == vin),
            "note": select(Note.id).where(Note.vin == vin),
        }
        conditions = [
            and_(Attachment.record_type == record_type, Attachment.record_id.in_(id_query))
            for record_type, id_query in parent_id_queries.items()
        ]
        result = await self.db.execute(
            select(Attachment.id, Attachment.file_path).where(or_(*conditions))
        )
        rows = result.all()
        return [row.id for row in rows], [row.file_path for row in rows]

    def _remove_vehicle_files(
        self, vin: str, attachment_paths: list[str], sticker_path: str | None
    ) -> None:
        """Best-effort filesystem cleanup for a deleted vehicle.

        Removes VIN-keyed upload directories plus resolved attachment files.
        Every path is containment-checked against the data directory; the VIN
        is a validated primary key by the time we get here, but stays guarded
        anyway since it becomes a path component.

        MUST NOT raise: it runs after the delete has committed, so a
        filesystem error here must degrade to a logged orphan-file warning —
        never a failed API response for a delete that already happened.
        """
        try:
            if not vin.isalnum():
                logger.warning("Skipping file cleanup for non-alphanumeric VIN")
                return

            allowed_roots = [
                settings.data_dir.resolve(),
                settings.photos_dir.resolve(),
                settings.documents_dir.resolve(),
                settings.attachments_dir.resolve(),
            ]
            for raw in [*attachment_paths, sticker_path]:
                if not raw:
                    continue
                candidate = Path(raw)
                if not candidate.is_absolute():
                    candidate = settings.data_dir / candidate
                resolved = candidate.resolve()
                if resolved.is_file() and any(
                    resolved.is_relative_to(root) for root in allowed_roots
                ):
                    resolved.unlink(missing_ok=True)

            for base in (settings.photos_dir, settings.documents_dir, settings.attachments_dir):
                vin_dir = (base / vin).resolve()
                if vin_dir.is_relative_to(base.resolve()) and vin_dir.is_dir():
                    shutil.rmtree(vin_dir, ignore_errors=True)
        except OSError as e:
            logger.warning(
                "File cleanup after deleting vehicle %s left orphans (delete itself succeeded): %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
