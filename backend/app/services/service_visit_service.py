"""Service visit business logic service layer."""

# pyright: reportReturnType=false

import logging
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.supply import SupplyUsage
from app.models.user import User
from app.schemas.service_visit import (
    ServiceLineItemCreate,
    ServiceLineItemResponse,
    ServiceLineItemUpdate,
    ServiceVisitCreate,
    ServiceVisitResponse,
    ServiceVisitUpdate,
    VendorSummary,
)
from app.schemas.supply import SupplyUsageInput
from app.services import maintenance_service
from app.services.supply_service import SupplyService, usage_cost_subject
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.cache import invalidate_cache_for_vehicle
from app.utils.hours_sync import remove_synced_hours, sync_hours_from_record
from app.utils.logging_utils import sanitize_for_log
from app.utils.maintenance_types import resolve_type
from app.utils.money_fits import ensure_fits
from app.utils.odometer_sync import remove_synced_odometer, sync_odometer_from_record

logger = logging.getLogger(__name__)


def service_visit_full_load_options():
    """Loader options for building a full ServiceVisitResponse: line_items →
    supply_usages → supply (needed for SupplyUsageResponse.supply_name) + vendor.

    Required before any read of calculated_total_cost / parts_supplies_cost —
    async SQLAlchemy raises MissingGreenlet on an unloaded relationship rather
    than lazy-loading it.
    """
    return (
        selectinload(ServiceVisit.line_items)
        .selectinload(ServiceLineItem.supply_usages)
        .selectinload(SupplyUsage.supply),
        selectinload(ServiceVisit.vendor),
    )


def service_visit_cost_load_options():
    """Loader options sufficient to read calculated_total_cost /
    parts_supplies_cost without building a full response: line_items →
    supply_usages (the supply row itself isn't needed for the cost math) +
    vendor. Shared by analytics/export/reports routes, which read visit-level
    costs but never a usage's supply_name.
    """
    return (
        selectinload(ServiceVisit.line_items).selectinload(ServiceLineItem.supply_usages),
        selectinload(ServiceVisit.vendor),
    )


class ServiceVisitService:
    """Service for managing service visit business logic."""

    def __init__(self, db: AsyncSession):
        """Initialize service visit service with database session."""
        self.db = db

    async def list_service_visits(
        self, vin: str, current_user: User | None, skip: int = 0, limit: int = 100
    ) -> tuple[list[ServiceVisitResponse], int]:
        """
        Get all service visits for a vehicle.

        Args:
            vin: Vehicle VIN
            current_user: The authenticated user
            skip: Number of records to skip (pagination)
            limit: Maximum number of records to return

        Returns:
            Tuple of (service visit responses, total count)

        Raises:
            HTTPException: 404 if vehicle not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            # Check vehicle ownership
            await get_vehicle_or_403(vin, current_user, self.db)

            # Get visits with line items, supply usages, and vendor
            result = await self.db.execute(
                select(ServiceVisit)
                .options(*service_visit_full_load_options())
                .where(ServiceVisit.vin == vin)
                .order_by(ServiceVisit.date.desc())
                .offset(skip)
                .limit(limit)
            )
            visits = result.scalars().all()

            # Get total count
            count_result = await self.db.execute(
                select(func.count()).select_from(ServiceVisit).where(ServiceVisit.vin == vin)
            )
            total = count_result.scalar() or 0

            visit_responses = [self._visit_to_response(v) for v in visits]
            return visit_responses, total

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing service visits for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_service_visit(
        self, vin: str, visit_id: int, current_user: User | None
    ) -> ServiceVisit:
        """
        Get a specific service visit by ID.

        Args:
            vin: Vehicle VIN
            visit_id: Service visit ID
            current_user: The authenticated user

        Returns:
            ServiceVisit object

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)

        result = await self.db.execute(
            select(ServiceVisit)
            .options(*service_visit_full_load_options())
            .where(ServiceVisit.id == visit_id)
            .where(ServiceVisit.vin == vin)
        )
        visit = result.scalar_one_or_none()

        if not visit:
            raise HTTPException(status_code=404, detail=f"Service visit {visit_id} not found")

        return visit

    async def create_service_visit(
        self, vin: str, visit_data: ServiceVisitCreate, current_user: User | None
    ) -> ServiceVisit:
        """
        Create a new service visit with line items.

        Args:
            vin: Vehicle VIN
            visit_data: Service visit creation data
            current_user: The authenticated user

        Returns:
            Created ServiceVisit object

        Raises:
            HTTPException: 404 if vehicle not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            # Line items may carry recurring reminders, which create or reuse a
            # rule: serialise with every other rule writer before the first read.
            await lock_vehicle_for_write(self.db, vin)

            visit, _items = await self.persist_visit_rows(vin, visit_data)

            await self.db.commit()
            await self.db.refresh(visit)

            logger.info("Created service visit %s for %s", visit.id, sanitize_for_log(vin))

            # Auto-sync odometer + engine-hours, composed into one transaction:
            # commit=False on each sync call, single commit closes it out
            # (mirrors fuel_service.add_fuel_record's pattern). Best-effort,
            # like the odometer-only sync this replaces: on failure, log and
            # continue rather than fail the whole request. Deliberately does
            # NOT roll back on failure -- Session.rollback() expires every
            # object in the identity map, not just `visit`, which would also
            # expire `current_user` (loaded earlier by the auth layer on this
            # same session) and crash the get_service_visit reload right
            # below with an async lazy-load (MissingGreenlet). visit_id is
            # captured as a plain int so nothing here depends on `visit`
            # staying unexpired either way.
            visit_id = visit.id
            if visit.date:
                try:
                    if visit.odometer_km:
                        await sync_odometer_from_record(
                            db=self.db,
                            vin=vin,
                            date=visit.date,
                            odometer_km=visit.odometer_km,
                            source_type="service_visit",
                            source_id=visit_id,
                            commit=False,
                        )
                    await sync_hours_from_record(
                        db=self.db,
                        vin=vin,
                        date=visit.date,
                        engine_hours=visit.engine_hours,
                        source_type="service_visit",
                        source_id=visit_id,
                        commit=False,
                    )
                    await self.db.commit()
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer/hours for visit %s: %s",
                        visit_id,
                        sanitize_for_log(e),
                    )

            # Maintenance lifecycle: a typed line item may be the newest service
            # of a rule's type, which completes that rule's pending reminder and
            # starts the next cycle. Runs after the sync commit so "current"
            # readings include this visit. Own lock, own commit, logs on failure.
            await maintenance_service.reconcile_vehicle(self.db, vin)

            await invalidate_cache_for_vehicle(vin)

            # Reload with relationships
            return await self.get_service_visit(vin, visit_id, current_user)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating service visit for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Invalid service visit data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating service visit for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def persist_visit_rows(
        self, vin: str, visit_data: ServiceVisitCreate, *, sync_readings: bool = False
    ) -> tuple[ServiceVisit, list[ServiceLineItem]]:
        """Write a visit, its line items, their reminders and supplies. No commit.

        The body ``create_service_visit`` runs inside its transaction, shared
        with ``maintenance_service.complete_reminder`` so a completion can
        persist the visit and close the reminder in ONE transaction under the
        vehicle lock. With ``sync_readings`` the odometer/hours sync is
        composed in as well (``commit=False``); ``create_service_visit`` keeps
        its own best-effort sync after its commit instead.

        Every line item gets a ``maintenance_type``: the one given, else the
        classifier's (which declines rather than guesses).
        """
        # Auto-derive service_category from first line item's category
        first_cat = next((i.category for i in visit_data.line_items if i.category), None)

        visit = ServiceVisit(
            vin=vin,
            vendor_id=visit_data.vendor_id,
            date=visit_data.date,
            odometer_km=visit_data.odometer_km,
            engine_hours=visit_data.engine_hours,
            # No total_cost: the client's is ignored. The recompute below
            # writes the real one before anything reads it.
            tax_amount=visit_data.tax_amount,
            shop_supplies=visit_data.shop_supplies,
            misc_fees=visit_data.misc_fees,
            notes=visit_data.notes,
            service_category=first_cat or visit_data.service_category,
            insurance_claim_number=visit_data.insurance_claim_number,
        )
        self.db.add(visit)
        await self.db.flush()  # Get visit ID

        # Pass 1: Create all line items, build temp_id → real_id map
        temp_id_map: dict[int, int] = {}
        created_items: list[tuple[ServiceLineItemCreate, ServiceLineItem]] = []

        for item_data in visit_data.line_items:
            line_item = ServiceLineItem(
                visit_id=visit.id,
                category=item_data.category,
                description=item_data.description,
                maintenance_type=resolve_type(item_data.maintenance_type, item_data.description),
                cost=item_data.cost,
                notes=item_data.notes,
                is_inspection=item_data.is_inspection,
                inspection_result=item_data.inspection_result,
                inspection_severity=item_data.inspection_severity,
                triggered_by_inspection_id=None,  # resolved in Pass 2
            )
            self.db.add(line_item)
            await self.db.flush()
            if item_data.temp_id is not None:
                temp_id_map[item_data.temp_id] = line_item.id
            created_items.append((item_data, line_item))

        # Pass 2: Resolve triggered_by_inspection_id and create reminders
        for item_data, line_item in created_items:
            if item_data.triggered_by_inspection_id is not None:
                ref = item_data.triggered_by_inspection_id
                line_item.triggered_by_inspection_id = temp_id_map.get(
                    ref, ref if ref > 0 else None
                )

            if item_data.reminder:
                # Anchored on THIS visit, never on the client's cached odometer.
                await maintenance_service.create_reminder_for_line_item(
                    self.db, vin, line_item, visit, item_data.reminder
                )

        # Pass 3: sync supply usages for each created line item
        for item_data, line_item in created_items:
            if item_data.supplies_used:
                await self._sync_line_item_supplies(line_item, item_data.supplies_used, vin)

        # Always recompute total_cost from line items + supplies + fees (denormalized cache)
        await self._recompute_visit_total(visit.id)

        if sync_readings and visit.date:
            if visit.odometer_km:
                await sync_odometer_from_record(
                    db=self.db,
                    vin=vin,
                    date=visit.date,
                    odometer_km=visit.odometer_km,
                    source_type="service_visit",
                    source_id=visit.id,
                    commit=False,
                )
            await sync_hours_from_record(
                db=self.db,
                vin=vin,
                date=visit.date,
                engine_hours=visit.engine_hours,
                source_type="service_visit",
                source_id=visit.id,
                commit=False,
            )

        return visit, [line_item for _data, line_item in created_items]

    async def recompute_visit_total(self, visit_id: int) -> ServiceVisit:
        """Public name for the denormalised total recompute (no commit)."""
        return await self._recompute_visit_total(visit_id)

    async def update_service_visit(
        self,
        vin: str,
        visit_id: int,
        visit_data: ServiceVisitUpdate,
        current_user: User | None,
    ) -> ServiceVisit:
        """
        Update an existing service visit.

        Args:
            vin: Vehicle VIN
            visit_id: Service visit ID
            visit_data: Service visit update data
            current_user: The authenticated user

        Returns:
            Updated ServiceVisit object

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            # Line items may carry recurring reminders, which create or reuse a
            # rule: serialise with every other rule writer before the first read.
            await lock_vehicle_for_write(self.db, vin)
            visit = await self.get_service_visit(vin, visit_id, current_user)

            update_data = visit_data.model_dump(exclude_unset=True)

            # Handle line_items separately - diff-based update
            new_line_items = update_data.pop("line_items", None)
            # The total is always recomputed below, so the client's is ignored.
            update_data.pop("total_cost", None)

            for field, value in update_data.items():
                setattr(visit, field, value)

            # Diff-based line item update
            if new_line_items is not None:
                submitted = visit_data.line_items or []
                existing = {item.id: item for item in visit.line_items}
                submitted_ids = {item.id for item in submitted if item.id}

                # Reject unknown IDs — fail fast
                for item_data in submitted:
                    if item_data.id is not None and item_data.id not in existing:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Line item {item_data.id} does not belong to this service visit",
                        )

                # Delete removed items (ON DELETE SET NULL detaches reminders)
                for item_id, item in existing.items():
                    if item_id not in submitted_ids:
                        await self.db.delete(item)

                # Pass 1: Update existing, create new — build temp_id map
                temp_id_map: dict[int, int] = {}
                new_items: list[tuple[ServiceLineItemUpdate, ServiceLineItem]] = []

                for item_data in submitted:
                    if item_data.id and item_data.id in existing:
                        # Update in place
                        row = existing[item_data.id]
                        row.category = item_data.category
                        row.description = item_data.description
                        if "maintenance_type" in item_data.model_fields_set:
                            row.maintenance_type = item_data.maintenance_type
                        elif row.maintenance_type is None:
                            row.maintenance_type = resolve_type(None, item_data.description)
                        row.cost = item_data.cost
                        row.notes = item_data.notes
                        row.is_inspection = item_data.is_inspection
                        row.inspection_result = item_data.inspection_result
                        row.inspection_severity = item_data.inspection_severity
                        row.triggered_by_inspection_id = item_data.triggered_by_inspection_id
                        await self._sync_line_item_supplies(row, item_data.supplies_used, vin)
                        # reminder ignored for existing items
                    else:
                        # New item added during edit
                        line_item = ServiceLineItem(
                            visit_id=visit.id,
                            category=item_data.category,
                            description=item_data.description,
                            maintenance_type=resolve_type(
                                item_data.maintenance_type, item_data.description
                            ),
                            cost=item_data.cost,
                            notes=item_data.notes,
                            is_inspection=item_data.is_inspection,
                            inspection_result=item_data.inspection_result,
                            inspection_severity=item_data.inspection_severity,
                            triggered_by_inspection_id=None,  # resolved in Pass 2
                        )
                        self.db.add(line_item)
                        await self.db.flush()
                        if item_data.temp_id is not None:
                            temp_id_map[item_data.temp_id] = line_item.id
                        new_items.append((item_data, line_item))

                # Pass 2: Resolve triggered_by_inspection_id for new items
                for item_data, line_item in new_items:
                    if item_data.triggered_by_inspection_id is not None:
                        ref = item_data.triggered_by_inspection_id
                        line_item.triggered_by_inspection_id = temp_id_map.get(
                            ref, ref if ref > 0 else None
                        )
                    await self._sync_line_item_supplies(line_item, item_data.supplies_used, vin)
                    if item_data.reminder:
                        await maintenance_service.create_reminder_for_line_item(
                            self.db, vin, line_item, visit, item_data.reminder
                        )

                # Auto-derive service_category from submitted items
                submitted_cats = [i.category for i in submitted if i.category]
                if submitted_cats:
                    visit.service_category = submitted_cats[0]

            # Always recompute total_cost from line items + supplies + fees (denormalized cache)
            await self.db.flush()
            await self._recompute_visit_total(visit_id)

            await self.db.commit()
            await self.db.refresh(visit)

            logger.info("Updated service visit %s for %s", visit_id, sanitize_for_log(vin))

            # Auto-sync odometer + engine-hours, composed into one transaction:
            # commit=False on each sync call, single commit closes it out
            # (mirrors fuel_service.update_fuel_record's pattern). Hours sync
            # runs unconditionally (not gated on a non-null reading) so
            # clearing engine_hours to None deletes the synced row.
            # Best-effort, like the odometer-only sync this replaces: on
            # failure, log and continue rather than fail the whole request.
            # Deliberately does NOT roll back on failure -- see the matching
            # comment in create_service_visit (Session.rollback() would
            # expire `current_user` too, crashing the reload right below).
            if visit.date:
                try:
                    if visit.odometer_km:
                        await sync_odometer_from_record(
                            db=self.db,
                            vin=vin,
                            date=visit.date,
                            odometer_km=visit.odometer_km,
                            source_type="service_visit",
                            source_id=visit_id,
                            commit=False,
                            operation="update",
                        )
                    elif not visit.odometer_km:
                        # Cleared on edit (or set to 0, which a create never
                        # syncs): take the reading it synced with it, the way
                        # the hours sync below deletes its row.
                        await remove_synced_odometer(self.db, vin, "service_visit", visit_id)
                    await sync_hours_from_record(
                        db=self.db,
                        vin=vin,
                        date=visit.date,
                        engine_hours=visit.engine_hours,
                        source_type="service_visit",
                        source_id=visit_id,
                        commit=False,
                    )
                    await self.db.commit()
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer/hours for visit %s: %s",
                        sanitize_for_log(visit_id),
                        sanitize_for_log(e),
                    )

            # Maintenance lifecycle: an edited date, odometer or line item type
            # moves anchors. Own lock, own commit, logs on failure.
            await maintenance_service.reconcile_vehicle(self.db, vin)

            await invalidate_cache_for_vehicle(vin)

            # Reload with the FULL eager chain (line_items -> supply_usages -> supply,
            # + vendor) before returning. `_recompute_visit_total`'s reload deliberately
            # loads only as deep as `supply_usages` (cost math doesn't need `.supply`'s
            # name/`.line_item`'s visit — see its docstring), and `populate_existing=True`
            # there expires whatever WAS loaded on those rows outside that path (R1-H1
            # sync may also have introduced brand-new SupplyUsage rows that never had
            # `.supply` loaded at all). Once expired, the identity map holds those targets
            # only by weak reference — with nothing else pinning a strong ref, they can be
            # garbage-collected before this returns, so even the `supply_id`-is-a-PK-match
            # ("use_get") lazy-load shortcut has nothing to find and falls through to an
            # actual query, which can't run synchronously from `_visit_to_response`
            # (MissingGreenlet). A full re-fetch — the same pattern `create_service_visit`
            # already uses — eagerly restores every relationship the response needs.
            return await self.get_service_visit(vin, visit_id, current_user)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating visit %s for %s: %s",
                visit_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating visit %s for %s: %s",
                visit_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_service_visit(
        self, vin: str, visit_id: int, current_user: User | None
    ) -> None:
        """
        Delete a service visit.

        Also cleans up records this visit auto-synced:
        - the auto-synced ``odometer_records`` row(s) for this visit —
          marker-guarded (``[AUTO-SYNC from service_visit #{id}]``, or the
          legacy ``[AUTO-SYNC from service #{id}]`` marker) so a manual
          odometer reading is NEVER deleted, even one sharing the exact
          same ``(vin, date)``. Matches on ``vin`` + marker only, NOT
          ``date`` — the marker already uniquely identifies the row(s) this
          visit synced, and if the visit's date was edited after the sync,
          the synced row lives at the OLD date while ``visit.date`` now
          reflects the NEW one; a ``date == visit.date`` predicate would
          miss it and orphan it forever. Service-sourced odometer rows
          carry no FK (unlike fuel-sourced ones via ``fuel_record_id``), so
          nothing cascades them away on their own — this fixes the
          pre-existing distance-track orphan bug, bringing it to parity
          with the hours track's real FK cascade.
        - the synced ``hours_records`` row via ``remove_synced_hours``.
          Belt-and-suspenders: ``hours_records.service_visit_id`` is an
          ON DELETE CASCADE FK, so the row is already removed once the
          visit delete below commits (PG enforced; SQLite via
          ``PRAGMA foreign_keys=ON``, active in prod) — called explicitly
          too for SQLite-without-the-pragma parity.

        Args:
            vin: Vehicle VIN
            visit_id: Service visit ID
            current_user: The authenticated user

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.models.odometer import OdometerRecord
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            visit = await self.get_service_visit(vin, visit_id, current_user)

            # Phase 4b: delete the auto-synced odometer row(s) for this visit
            # -- ONLY rows that still carry THIS visit's AUTO-SYNC marker.
            # No date predicate: the marker alone uniquely identifies the
            # row(s) this visit synced (regardless of which date they sit
            # at), so it can't over-delete, and it also catches a synced row
            # left behind at an OLD date after the visit's date was edited
            # (a date == visit.date filter would miss that row and orphan
            # it). Never touches a manual row.
            from app.utils.odometer_sync import auto_sync_marker, legacy_service_marker

            auto_sync_markers = (
                auto_sync_marker("service_visit", visit_id),
                legacy_service_marker(visit_id),
            )
            await self.db.execute(
                delete(OdometerRecord)
                .where(OdometerRecord.vin == vin)
                .where(OdometerRecord.notes.in_(auto_sync_markers))
            )

            # Belt-and-suspenders hours cleanup (see docstring) -- composed
            # into the same transaction as the visit delete below.
            await remove_synced_hours(self.db, "service_visit", visit_id, commit=False)

            await self.db.delete(visit)
            await self.db.commit()

            logger.info(
                "Deleted service visit %s for %s", sanitize_for_log(visit_id), sanitize_for_log(vin)
            )
            # The deleted visit may have anchored a reminder (the FK is SET
            # NULL; the snapshot stays). Reconcile so a rule whose newest
            # service just vanished still has exactly one pending reminder.
            await maintenance_service.reconcile_vehicle(self.db, vin)
            await invalidate_cache_for_vehicle(vin)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting visit %s for %s: %s",
                visit_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete visit with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting visit %s for %s: %s",
                visit_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def add_line_item(
        self,
        vin: str,
        visit_id: int,
        item_data: ServiceLineItemCreate,
        current_user: User | None,
    ) -> ServiceLineItem:
        """
        Add a line item to an existing service visit.

        Args:
            vin: Vehicle VIN
            visit_id: Service visit ID
            item_data: Line item creation data
            current_user: The authenticated user

        Returns:
            Created ServiceLineItem object
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            # Line items may carry recurring reminders, which create or reuse a
            # rule: serialise with every other rule writer before the first read.
            await lock_vehicle_for_write(self.db, vin)
            visit = await self.get_service_visit(vin, visit_id, current_user)

            line_item = ServiceLineItem(
                visit_id=visit.id,
                category=item_data.category,
                description=item_data.description,
                maintenance_type=resolve_type(item_data.maintenance_type, item_data.description),
                cost=item_data.cost,
                notes=item_data.notes,
                is_inspection=item_data.is_inspection,
                inspection_result=item_data.inspection_result,
                inspection_severity=item_data.inspection_severity,
                triggered_by_inspection_id=item_data.triggered_by_inspection_id,
            )
            self.db.add(line_item)
            await self.db.flush()

            if item_data.reminder:
                await maintenance_service.create_reminder_for_line_item(
                    self.db, vin, line_item, visit, item_data.reminder
                )

            if item_data.supplies_used:
                await self._sync_line_item_supplies(line_item, item_data.supplies_used, vin)

            # Recompute total_cost (denormalized cache)
            await self._recompute_visit_total(visit.id)

            await self.db.commit()
            await maintenance_service.reconcile_vehicle(self.db, vin)

            # Reload with supply usages + supply + owning visit eager-loaded so the
            # response can carry supply_usages (to_usage_response reads usage.supply.name
            # and, for job usages, usage.line_item.visit.date — both must be loaded).
            reloaded = await self.db.execute(
                select(ServiceLineItem)
                .options(
                    selectinload(ServiceLineItem.supply_usages).selectinload(SupplyUsage.supply),
                    joinedload(ServiceLineItem.visit),
                )
                .where(ServiceLineItem.id == line_item.id)
            )
            line_item = reloaded.scalar_one()

            logger.info(
                "Added line item %s to visit %s for %s",
                line_item.id,
                visit_id,
                sanitize_for_log(vin),
            )
            await invalidate_cache_for_vehicle(vin)

            return line_item

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation adding line item to visit %s: %s",
                visit_id,
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Invalid line item data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error adding line item to visit %s: %s",
                visit_id,
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_line_item(
        self, vin: str, visit_id: int, line_item_id: int, current_user: User | None
    ) -> None:
        """
        Delete a line item from a service visit.

        Args:
            vin: Vehicle VIN
            visit_id: Service visit ID
            line_item_id: Line item ID
            current_user: The authenticated user
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            await self.get_service_visit(vin, visit_id, current_user)

            result = await self.db.execute(
                select(ServiceLineItem)
                .where(ServiceLineItem.id == line_item_id)
                .where(ServiceLineItem.visit_id == visit_id)
            )
            line_item = result.scalar_one_or_none()

            if not line_item:
                raise HTTPException(status_code=404, detail=f"Line item {line_item_id} not found")

            await self.db.delete(line_item)
            await self.db.flush()

            # Recompute total_cost (denormalized cache)
            await self._recompute_visit_total(visit_id)

            await self.db.commit()
            await maintenance_service.reconcile_vehicle(self.db, vin)

            logger.info(
                "Deleted line item %s from visit %s for %s",
                line_item_id,
                visit_id,
                sanitize_for_log(vin),
            )
            await invalidate_cache_for_vehicle(vin)

        except HTTPException:
            raise
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting line item %s: %s",
                line_item_id,
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def _reload_visit_full(self, visit_id: int) -> ServiceVisit:
        """Reload a visit with line_items → supply_usages eager-loaded — just
        enough to compute calculated_total_cost / parts_supplies_cost, which
        only reads cost_snapshot off each usage (not the usage's Supply row,
        not vendor).

        Required before any read of those properties (async: unloaded
        relationships raise, they never lazy-load). populate_existing=True
        overwrites already-loaded identity-map collections so a just-mutated
        visit reflects its new usages (R1-F1).
        """
        result = await self.db.execute(
            select(ServiceVisit)
            .options(
                selectinload(ServiceVisit.line_items).selectinload(ServiceLineItem.supply_usages)
            )
            .where(ServiceVisit.id == visit_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one()

    async def _recompute_visit_total(self, visit_id: int) -> ServiceVisit:
        """Reload the full chain, set the denormalized total_cost cache, return the visit.

        Every part fits its column but the sum may not, so a total past it is a
        422 before it is written.
        """
        visit = await self._reload_visit_full(visit_id)
        total = visit.calculated_total_cost
        ensure_fits(total, "The visit total")
        visit.total_cost = total
        await self.db.flush()
        return visit

    async def _sync_line_item_supplies(
        self,
        line_item: ServiceLineItem,
        supplies_used: Sequence[SupplyUsageInput] | None,
        vin: str,
    ) -> None:
        """Diff a line item's supply usages by supply_id — PRESERVE frozen snapshots.

        R1-H1: a blanket delete+recreate would re-snapshot untouched consumption at
        today's average cost, reset created_at, and fail when a supply was later
        archived/repinned — even on an edit that never touched supplies. Instead:
          - supply_id present before AND now → keep the row (id, created_at). If only
            the quantity changed, RETAIN the original unit_cost_snapshot and recompute
            cost_snapshot = unit_cost_snapshot × new_quantity (cost stays frozen).
          - supply_id newly added → validate active/pinned NOW + snapshot current avg.
          - supply_id removed → delete the row.
        Only NEW associations are validated, so editing an unrelated field on a
        historical visit never fails because a supply was archived/repinned since.
        """
        supply_service = SupplyService(self.db)
        submitted = supplies_used or []

        # Reject duplicate supply_id within one line item (ambiguous quantities).
        seen: set[int] = set()
        for u in submitted:
            if u.supply_id in seen:
                raise HTTPException(
                    status_code=400,
                    detail=f"Supply {u.supply_id} listed more than once on one line item",
                )
            seen.add(u.supply_id)

        existing_rows = (
            (
                await self.db.execute(
                    select(SupplyUsage).where(SupplyUsage.service_line_item_id == line_item.id)
                )
            )
            .scalars()
            .all()
        )
        existing = {row.supply_id: row for row in existing_rows}
        submitted_ids = {u.supply_id for u in submitted}

        # Removed associations → delete.
        for supply_id, row in existing.items():
            if supply_id not in submitted_ids:
                await self.db.delete(row)

        for u in submitted:
            prior = existing.get(u.supply_id)
            if prior is not None:
                # Unchanged association: keep frozen unit cost; recompute cost only if qty moved.
                if prior.quantity != u.quantity:
                    cost = (
                        (prior.unit_cost_snapshot * u.quantity).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                        if prior.unit_cost_snapshot is not None
                        else None
                    )
                    # Checked before the row changes: this bypasses SupplyService.
                    ensure_fits(cost, usage_cost_subject(u.supply_id))
                    prior.quantity = u.quantity
                    prior.cost_snapshot = cost
                # fully unchanged → leave the row (and its created_at) untouched
            else:
                # New association: validate + snapshot at current average cost.
                await supply_service.get_supply_for_use(u.supply_id, vin)  # 400 if not usable
                unit_cost, cost = await supply_service.create_usage_snapshot(
                    u.supply_id, u.quantity
                )
                self.db.add(
                    SupplyUsage(
                        supply_id=u.supply_id,
                        quantity=u.quantity,
                        unit_cost_snapshot=unit_cost,
                        cost_snapshot=cost,
                        service_line_item_id=line_item.id,
                    )
                )
        await self.db.flush()

    def _visit_to_response(self, visit: ServiceVisit) -> ServiceVisitResponse:
        """Convert ServiceVisit model to response schema."""
        vendor_summary = None
        if visit.vendor:
            vendor_summary = VendorSummary(
                id=visit.vendor.id,
                name=visit.vendor.name,
                city=visit.vendor.city,
                state=visit.vendor.state,
            )

        # Reuse SupplyService's usage->response mapping rather than duplicating
        # it here (it also fills in service_visit_id/service_visit_date via
        # usage.line_item.visit, both back_populates-populated for free by the
        # line_items/supply_usages eager-load above — no extra query).
        supply_service = SupplyService(self.db)

        line_item_responses = [
            ServiceLineItemResponse(  # type: ignore[arg-type]
                id=item.id,
                visit_id=item.visit_id,
                description=item.description,
                category=item.category,
                maintenance_type=item.maintenance_type,
                cost=item.cost,
                notes=item.notes,
                is_inspection=item.is_inspection,
                inspection_result=item.inspection_result,
                inspection_severity=item.inspection_severity,
                triggered_by_inspection_id=item.triggered_by_inspection_id,
                created_at=item.created_at,
                is_failed_inspection=item.is_failed_inspection,
                needs_followup=item.needs_followup,
                supply_usages=[supply_service.to_usage_response(u) for u in item.supply_usages],
            )
            for item in visit.line_items
        ]

        return ServiceVisitResponse(  # type: ignore[arg-type]
            id=visit.id,
            vin=visit.vin,
            vendor_id=visit.vendor_id,
            date=visit.date,
            odometer_km=visit.odometer_km,
            engine_hours=visit.engine_hours,
            total_cost=visit.total_cost,
            tax_amount=visit.tax_amount,
            shop_supplies=visit.shop_supplies,
            misc_fees=visit.misc_fees,
            subtotal=visit.subtotal,
            calculated_total_cost=visit.calculated_total_cost,
            parts_supplies_cost=visit.parts_supplies_cost,
            notes=visit.notes,
            service_category=visit.service_category,
            insurance_claim_number=visit.insurance_claim_number,
            line_item_count=visit.line_item_count,
            has_failed_inspections=visit.has_failed_inspections,
            created_at=visit.created_at,
            updated_at=visit.updated_at,
            line_items=line_item_responses,
            vendor=vendor_summary,
        )
