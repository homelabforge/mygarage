"""Recall business logic service layer."""

import json
import logging
from dataclasses import dataclass, field

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recall import Recall
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.recall import (
    RecallCheckResponse,
    RecallCreate,
    RecallListResponse,
    RecallResponse,
    RecallUpdate,
)
from app.services.country_profile_service import profile_for_vehicle
from app.services.nhtsa import NHTSAService, NHTSAUnavailableError
from app.services.recalls.base import SOURCE_MANUAL, SOURCE_NHTSA, RecallHit, RecallProvider
from app.services.recalls.nhtsa import NHTSA_RECALL_URL
from app.services.recalls.registry import providers_for
from app.services.settings_service import SettingsService
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log
from app.utils.vehicle_key import has_real_vin

logger = logging.getLogger(__name__)

#: ``recalls.component`` is VARCHAR(200) since migration 137 (K10).
_COMPONENT_WIDTH = 200


@dataclass
class RecallSyncOutcome:
    """What one pass over a vehicle's providers did."""

    new_count: int = 0
    providers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: The providers that failed this pass, so the scheduler leaves their
    #: last-check stamp alone and the next run retries.
    failed: list[str] = field(default_factory=list)
    #: NHTSA didn't answer usably (`NHTSAUnavailableError`): an outage, not a
    #: VIN it can't resolve, which counts as checked.
    nhtsa_unavailable: bool = False


def _row_from_hit(vin: str, hit: RecallHit) -> Recall:
    return Recall(
        vin=vin,
        source=hit.source,
        external_id=hit.external_id,
        external_url=hit.external_url,
        nhtsa_campaign_number=hit.external_id[:20] if hit.source == SOURCE_NHTSA else None,
        component=hit.component[:_COMPONENT_WIDTH],
        summary=hit.summary,
        consequence=hit.consequence,
        remedy=hit.remedy,
        date_announced=hit.date_announced,
        match_confidence=hit.match_confidence,
        is_resolved=False,
    )


def _warning_for(provider: RecallProvider, exc: Exception) -> str:
    if isinstance(exc, NHTSAUnavailableError):
        return f"{provider.name}: unavailable"
    if isinstance(exc, ValueError):
        return f"{provider.name}: {exc}"
    if isinstance(exc, httpx.HTTPError):
        return f"{provider.name}: request failed"
    return f"{provider.name}: check failed"


async def sync_vehicle_recalls(
    db: AsyncSession,
    vehicle: Vehicle,
    *,
    providers: list[RecallProvider] | None = None,
    skip: frozenset[str] = frozenset(),
) -> RecallSyncOutcome:
    """Ask every provider that covers the vehicle and store what is new (#211).

    A recall is new when no row carries its ``(source, external_id)``; an
    NHTSA campaign number already stored before sources existed counts too.
    A provider that fails is a warning, never the end of the pass: the
    others still run. ``skip`` names sources left out of this pass (the
    scheduled check drops NHTSA when its auto-check is off). Commits.
    """
    outcome = RecallSyncOutcome()
    if providers is None:
        profile = await profile_for_vehicle(db, vehicle)
        providers = await providers_for(db, vehicle, profile)
    providers = [provider for provider in providers if provider.name not in skip]
    rows = (
        await db.execute(
            select(Recall.source, Recall.external_id, Recall.nhtsa_campaign_number).where(
                Recall.vin == vehicle.vin
            )
        )
    ).all()
    seen = {(source, external_id) for source, external_id, _ in rows if external_id}
    legacy_campaigns = {campaign for _, _, campaign in rows if campaign}
    for provider in providers:
        outcome.providers.append(provider.name)
        try:
            hits = await provider.fetch(db, vehicle)
        except Exception as exc:  # noqa: BLE001 - one source down must not hide the others
            logger.warning(
                "Recall provider %s failed for %s: %s",
                provider.name,
                sanitize_for_log(vehicle.vin),
                sanitize_for_log(exc),
            )
            outcome.warnings.append(_warning_for(provider, exc))
            if isinstance(exc, NHTSAUnavailableError):
                outcome.nhtsa_unavailable = True
            # A ValueError is a vehicle the source can't check, which no retry
            # fixes; a body that isn't JSON (a maintenance page) is the
            # source not answering, though JSONDecodeError is a ValueError.
            if not isinstance(exc, ValueError) or isinstance(exc, json.JSONDecodeError):
                outcome.failed.append(provider.name)
            continue
        for hit in hits:
            key = (hit.source, hit.external_id)
            if key in seen:
                continue
            if hit.source == SOURCE_NHTSA and hit.external_id in legacy_campaigns:
                continue
            db.add(_row_from_hit(vehicle.vin, hit))
            seen.add(key)
            outcome.new_count += 1
    if outcome.new_count:
        await db.commit()
    logger.info(
        "Recall check for %s: %d new from %s",
        sanitize_for_log(vehicle.vin),
        outcome.new_count,
        ",".join(outcome.providers) or "no provider",
    )
    return outcome


class RecallService:
    """Service for managing recall business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_recalls(
        self,
        vin: str,
        current_user: User | None,
        status: str | None = None,
    ) -> RecallListResponse:
        """Get all recalls for a vehicle with optional status filtering.

        Args:
            vin: Vehicle identification number.
            current_user: Authenticated user.
            status: Optional filter - 'active', 'resolved', or None for all.

        Returns:
            RecallListResponse with recalls, total, active_count, resolved_count.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            query = select(Recall).where(Recall.vin == vin)

            if status == "active":
                query = query.where(Recall.is_resolved.is_(False))
            elif status == "resolved":
                query = query.where(Recall.is_resolved.is_(True))

            query = query.order_by(Recall.is_resolved.asc(), Recall.date_announced.desc())

            result = await self.db.execute(query)
            recalls = result.scalars().all()

            active_count = sum(1 for r in recalls if not r.is_resolved)
            resolved_count = sum(1 for r in recalls if r.is_resolved)

            return RecallListResponse(
                recalls=[RecallResponse.model_validate(r) for r in recalls],
                total=len(recalls),
                active_count=active_count,
                resolved_count=resolved_count,
            )

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing recalls for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def check_nhtsa(
        self,
        vin: str,
        current_user: User | None,
    ) -> RecallListResponse:
        """Fetch recalls from NHTSA API, store new ones, and return updated list.

        Args:
            vin: Vehicle identification number.
            current_user: Authenticated user.

        Returns:
            RecallListResponse with all recalls including newly fetched ones.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            vehicle = await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            # NHTSA works from the VIN; a vehicle without one (#226) would
            # send its generated key. The generic check still covers it.
            if not has_real_vin(vehicle):
                raise HTTPException(
                    status_code=409,
                    detail="NHTSA looks recalls up by VIN, and this vehicle has none",
                )

            # After the access check, so a caller who can't write the vehicle
            # learns nothing about the switch.
            if not await SettingsService.get_bool(self.db, "nhtsa_enabled", True):
                raise HTTPException(
                    status_code=409,
                    detail="NHTSA recalls are switched off in Settings > Integrations",
                )

            # Fetch recalls from NHTSA
            nhtsa_service = NHTSAService()
            nhtsa_recalls = await nhtsa_service.get_vehicle_recalls(vin, self.db)

            # Get existing recalls
            result = await self.db.execute(select(Recall).where(Recall.vin == vin))
            existing_recalls = result.scalars().all()
            existing_campaign_numbers = {
                r.nhtsa_campaign_number for r in existing_recalls if r.nhtsa_campaign_number
            }

            # Add new recalls
            new_recalls_added = 0
            for nhtsa_recall in nhtsa_recalls:
                campaign_number = nhtsa_recall.get("NHTSACampaignNumber")

                if campaign_number and campaign_number in existing_campaign_numbers:
                    continue

                db_recall = Recall(
                    vin=vin,
                    source=SOURCE_NHTSA,
                    external_id=campaign_number,
                    external_url=(
                        NHTSA_RECALL_URL.format(campaign=campaign_number)
                        if campaign_number
                        else None
                    ),
                    nhtsa_campaign_number=campaign_number,
                    component=nhtsa_recall.get("Component", "Unknown Component")[:_COMPONENT_WIDTH],
                    summary=nhtsa_recall.get("Summary", "No summary available"),
                    consequence=nhtsa_recall.get("Consequence"),
                    remedy=nhtsa_recall.get("Remedy"),
                    date_announced=None,
                    match_confidence=100,
                    is_resolved=False,
                )
                self.db.add(db_recall)
                new_recalls_added += 1

            await self.db.commit()

            logger.info(
                "Added %s new recalls for vehicle %s from NHTSA",
                new_recalls_added,
                sanitize_for_log(vin),
            )

            # Return updated list
            result = await self.db.execute(
                select(Recall)
                .where(Recall.vin == vin)
                .order_by(Recall.is_resolved.asc(), Recall.created_at.desc())
            )
            recalls = result.scalars().all()

            active_count = sum(1 for r in recalls if not r.is_resolved)
            resolved_count = sum(1 for r in recalls if r.is_resolved)

            return RecallListResponse(
                recalls=[RecallResponse.model_validate(r) for r in recalls],
                total=len(recalls),
                active_count=active_count,
                resolved_count=resolved_count,
            )

        except HTTPException:
            raise
        except ValueError as e:
            logger.warning(
                "VIN decode failure for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(str(e)),
            )
            raise HTTPException(
                status_code=422,
                detail=f"Could not decode VIN to fetch recalls: {e!s}",
            )
        except httpx.TimeoutException:
            logger.error(
                "NHTSA API timeout fetching recalls for VIN %s",
                sanitize_for_log(vin),
            )
            raise HTTPException(status_code=504, detail="NHTSA API request timed out")
        except httpx.ConnectError:
            logger.error(
                "Cannot connect to NHTSA API for VIN %s",
                sanitize_for_log(vin),
            )
            raise HTTPException(status_code=503, detail="Cannot connect to NHTSA API")
        except httpx.HTTPStatusError as e:
            logger.error(
                "NHTSA API error fetching recalls for VIN %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(str(e)),
            )
            raise HTTPException(status_code=e.response.status_code, detail="NHTSA API error")
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation storing NHTSA recalls for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate recall data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database error fetching recalls for VIN %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(str(e)),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def check_all(self, vin: str, current_user: User) -> RecallCheckResponse:
        """Ask every source that covers the vehicle's country and store what
        is new (#211); a source that fails is a warning in the answer."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        try:
            vehicle = await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            outcome = await sync_vehicle_recalls(self.db, vehicle)
            listed = await self.list_recalls(vin, current_user)
            return RecallCheckResponse(
                recalls=listed.recalls,
                total=listed.total,
                active_count=listed.active_count,
                resolved_count=listed.resolved_count,
                providers_checked=outcome.providers,
                new_count=outcome.new_count,
                warnings=outcome.warnings,
            )
        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation storing recalls for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate recall data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database error checking recalls for VIN %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(str(e)),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def create_recall(
        self,
        vin: str,
        data: RecallCreate,
        current_user: User | None,
    ) -> RecallResponse:
        """Create a new recall manually.

        Args:
            vin: Vehicle identification number.
            data: Recall creation data.
            current_user: Authenticated user.

        Returns:
            RecallResponse for the newly created recall.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            db_recall = Recall(
                vin=vin,
                source=SOURCE_MANUAL,
                external_id=data.nhtsa_campaign_number or None,
                external_url=data.external_url,
                nhtsa_campaign_number=data.nhtsa_campaign_number,
                component=data.component,
                summary=data.summary,
                consequence=data.consequence,
                remedy=data.remedy,
                date_announced=data.date_announced,
                is_resolved=data.is_resolved,
                notes=data.notes,
            )

            if data.is_resolved:
                db_recall.resolved_at = utc_now()

            self.db.add(db_recall)
            await self.db.commit()
            await self.db.refresh(db_recall)

            logger.info(
                "Created recall %s for vehicle %s",
                db_recall.id,
                sanitize_for_log(vin),
            )

            return RecallResponse.model_validate(db_recall)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating recall for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid recall")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating recall for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_recall(
        self,
        vin: str,
        recall_id: int,
        current_user: User | None,
    ) -> RecallResponse:
        """Get a specific recall by ID.

        Args:
            vin: Vehicle identification number.
            recall_id: Recall record ID.
            current_user: Authenticated user.

        Returns:
            RecallResponse for the requested recall.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(Recall).where(Recall.id == recall_id, Recall.vin == vin)
            )
            recall = result.scalar_one_or_none()

            if not recall:
                raise HTTPException(status_code=404, detail="Recall not found")

            return RecallResponse.model_validate(recall)

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error getting recall %s for %s: %s",
                sanitize_for_log(recall_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_recall(
        self,
        vin: str,
        recall_id: int,
        data: RecallUpdate,
        current_user: User | None,
    ) -> RecallResponse:
        """Update an existing recall.

        Args:
            vin: Vehicle identification number.
            recall_id: Recall record ID.
            data: Recall update data.
            current_user: Authenticated user.

        Returns:
            RecallResponse for the updated recall.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(Recall).where(Recall.id == recall_id, Recall.vin == vin)
            )
            recall = result.scalar_one_or_none()

            if not recall:
                raise HTTPException(status_code=404, detail="Recall not found")

            update_data = data.model_dump(exclude_unset=True)

            # Handle is_resolved field specially
            if "is_resolved" in update_data:
                new_resolved_status = update_data["is_resolved"]
                old_resolved_status = recall.is_resolved

                if new_resolved_status and not old_resolved_status:
                    recall.resolved_at = utc_now()
                elif not new_resolved_status and old_resolved_status:
                    recall.resolved_at = None

            for field, value in update_data.items():
                setattr(recall, field, value)

            await self.db.commit()
            await self.db.refresh(recall)

            logger.info(
                "Updated recall %s for vehicle %s",
                sanitize_for_log(recall_id),
                sanitize_for_log(vin),
            )

            return RecallResponse.model_validate(recall)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating recall %s for %s: %s",
                sanitize_for_log(recall_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating recall %s for %s: %s",
                sanitize_for_log(recall_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_recall(
        self,
        vin: str,
        recall_id: int,
        current_user: User | None,
    ) -> None:
        """Delete a recall.

        Args:
            vin: Vehicle identification number.
            recall_id: Recall record ID.
            current_user: Authenticated user.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(Recall).where(Recall.id == recall_id, Recall.vin == vin)
            )
            recall = result.scalar_one_or_none()

            if not recall:
                raise HTTPException(status_code=404, detail="Recall not found")

            await self.db.execute(delete(Recall).where(Recall.id == recall_id))
            await self.db.commit()

            logger.info(
                "Deleted recall %s for vehicle %s",
                sanitize_for_log(recall_id),
                sanitize_for_log(vin),
            )

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting recall %s for %s: %s",
                sanitize_for_log(recall_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete recall with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting recall %s for %s: %s",
                sanitize_for_log(recall_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")
