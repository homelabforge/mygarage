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
from app.services.attachment_cleanup import purge_record_attachments, remove_attachment_files
from app.services.supply_service import SupplyService, usage_cost_subject
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.hours_sync import remove_synced_hours, sync_hours_from_record
from app.utils.logging_utils import sanitize_for_log
from app.utils.maintenance_types import resolve_type
from app.utils.money_fits import ensure_fits
from app.utils.odometer_sync import remove_synced_odometer, sync_odometer_from_record

logger = logging.getLogger(__name__)

# An update leaves these alone on an existing line item unless it sends them
# (Ruling 11): omitted keeps the value, null clears it. The form sends null
# for every blank field. triggered_by_inspection_id follows the same rule but
# is resolved in pass 2, once new items have ids.
_KEPT_WHEN_OMITTED = (
    "category",
    "cost",
    "notes",
    "is_inspection",
    "inspection_result",
    "inspection_severity",
)


def drop_stray_links(items: Sequence[ServiceLineItem]) -> None:
    """Null every link that doesn't name another inspection in ``items`` (S1d-04, D1).

    ``items`` is the visit's whole item list as it'll be saved. A link to an
    item that's not an inspection is dropped rather than refused. Missing and
    self targets go too, for rows from before the API refused them.
    """
    by_id = {item.id: item for item in items}
    for item in items:
        ref = item.triggered_by_inspection_id
        if ref is None:
            continue
        target = by_id.get(ref)
        if target is None or target is item or not target.is_inspection:
            item.triggered_by_inspection_id = None


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

            # The visit, its odometer/hours sync and the reminder reconcile all
            # land in one commit (G5a-07), so a failed sync or reconcile takes
            # the visit down with it instead of leaving it half-done.
            visit, _items = await self.persist_visit_rows(vin, visit_data, sync_readings=True)
            await maintenance_service.reconcile_vehicle_unlocked(self.db, vin)
            visit_id = visit.id

            await self.db.commit()

            logger.info("Created service visit %s for %s", visit_id, sanitize_for_log(vin))

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
        composed in as well (``commit=False``). Both callers pass it, so a
        failed sync fails the whole write.

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
                # Every item here is new, so only a temp id can link; a
                # positive id would point outside this visit.
                line_item.triggered_by_inspection_id = temp_id_map.get(
                    item_data.triggered_by_inspection_id
                )

            if item_data.reminder:
                # Anchored on THIS visit, never on the client's cached odometer.
                await maintenance_service.create_reminder_for_line_item(
                    self.db, vin, line_item, visit, item_data.reminder
                )

        # A link has to land on an inspection; anything else just goes.
        drop_stray_links([line_item for _data, line_item in created_items])

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

                # Reject unknown IDs, self-links and links to items outside this
                # visit, before anything is written. A link to an item this PUT
                # drops is fine: deleting that item clears the link.
                for item_data in submitted:
                    if item_data.id is not None and item_data.id not in existing:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Line item {item_data.id} does not belong to this service visit",
                        )
                    # None when omitted, so an existing item's link is only
                    # checked when it's sent. Negative refs are temp ids.
                    ref = item_data.triggered_by_inspection_id
                    if ref is not None and ref == item_data.id:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Line item {ref} cannot link to itself",
                        )
                    if ref is not None and ref > 0 and ref not in existing:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Line item {ref} does not belong to this service visit",
                        )

                # Delete removed items (ON DELETE SET NULL detaches reminders)
                for item_id, item in existing.items():
                    if item_id not in submitted_ids:
                        await self.db.delete(item)
                # Flushed now: deleting an item nulls the links to it, and left
                # to the final flush that would wipe a link pass 2 just set.
                await self.db.flush()

                # Pass 1: Update existing, create new — build temp_id map
                temp_id_map: dict[int, int] = {}
                effective_cats: list[str] = []
                new_items: list[tuple[ServiceLineItemUpdate, ServiceLineItem]] = []
                # Every link the request sends, set in pass 2.
                links: list[tuple[ServiceLineItem, int | None]] = []

                for item_data in submitted:
                    if item_data.id and item_data.id in existing:
                        row = existing[item_data.id]
                        row.description = item_data.description
                        sent = item_data.model_fields_set
                        for field in _KEPT_WHEN_OMITTED:
                            if field in sent:
                                setattr(row, field, getattr(item_data, field))
                        if "triggered_by_inspection_id" in sent:
                            links.append((row, item_data.triggered_by_inspection_id))
                        if "maintenance_type" in sent:
                            row.maintenance_type = item_data.maintenance_type
                        elif row.maintenance_type is None:
                            row.maintenance_type = resolve_type(None, item_data.description)
                        # Omitted = keep (G1-D5): an API client that leaves the
                        # field out must not delete the item's usages. [] clears.
                        if "supplies_used" in sent:
                            await self._sync_line_item_supplies(row, item_data.supplies_used, vin)
                        if row.category:
                            effective_cats.append(row.category)
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
                        links.append((line_item, item_data.triggered_by_inspection_id))
                        if line_item.category:
                            effective_cats.append(line_item.category)

                # Pass 2: a temp id names a new item; a real id (checked above)
                # keeps the link only if this PUT keeps that item.
                for linked, ref in links:
                    if ref is None:
                        linked.triggered_by_inspection_id = None
                    elif ref < 0:
                        linked.triggered_by_inspection_id = temp_id_map.get(ref)
                    else:
                        linked.triggered_by_inspection_id = ref if ref in submitted_ids else None

                # Over every item the visit keeps, so unticking an inspection
                # drops the links to it even from repairs that didn't send one.
                # Not visit.line_items: that still holds the deleted rows and
                # never got the new ones.
                drop_stray_links(
                    [existing[i] for i in submitted_ids if i in existing]
                    + [li for _, li in new_items]
                )

                for item_data, line_item in new_items:
                    await self._sync_line_item_supplies(line_item, item_data.supplies_used, vin)
                    if item_data.reminder:
                        await maintenance_service.create_reminder_for_line_item(
                            self.db, vin, line_item, visit, item_data.reminder
                        )

                # From the items' categories as they are now, kept or sent.
                if effective_cats:
                    visit.service_category = effective_cats[0]

            # Always recompute total_cost from line items + supplies + fees (denormalized cache)
            await self.db.flush()
            await self._recompute_visit_total(visit_id)

            # Odometer + engine-hours sync, then the reminder reconcile, in the
            # same transaction as the edit (G5a-07). Hours sync runs even when
            # the reading is gone so clearing engine_hours deletes its row.
            if visit.date:
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
                else:
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

            # An edited date, odometer or line item type moves anchors.
            await maintenance_service.reconcile_vehicle_unlocked(self.db, vin)

            await self.db.commit()

            logger.info("Updated service visit %s for %s", visit_id, sanitize_for_log(vin))

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
            # The reconcile below rewrites reminders: serialise with every
            # other rule writer before the first read.
            await lock_vehicle_for_write(self.db, vin)
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

            # Attachments have no FK to the visit, so nothing cascades to them.
            attachment_paths = await purge_record_attachments(self.db, "service_visit", visit_id)

            await self.db.delete(visit)
            # Sessions don't autoflush and the reconcile reads history first,
            # so the delete has to be in the database before it runs.
            await self.db.flush()
            # The deleted visit may have anchored a reminder (the FK is SET
            # NULL; the snapshot stays). Reconcile so a rule whose newest
            # service just vanished still has exactly one pending reminder.
            # Same commit as the delete (G5a-07).
            await maintenance_service.reconcile_vehicle_unlocked(self.db, vin)
            await self.db.commit()
            # Files only after the commit, so a rollback never strands a live row.
            remove_attachment_files(attachment_paths)

            logger.info(
                "Deleted service visit %s for %s", sanitize_for_log(visit_id), sanitize_for_log(vin)
            )

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

            # The link must name an item already on this visit (no temp ids here).
            ref = item_data.triggered_by_inspection_id
            if ref is not None and ref not in {item.id for item in visit.line_items}:
                raise HTTPException(
                    status_code=400,
                    detail=f"Line item {ref} does not belong to this service visit",
                )

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
            # A link to an item that isn't an inspection just goes.
            drop_stray_links([*visit.line_items, line_item])

            if item_data.reminder:
                await maintenance_service.create_reminder_for_line_item(
                    self.db, vin, line_item, visit, item_data.reminder
                )

            if item_data.supplies_used:
                await self._sync_line_item_supplies(line_item, item_data.supplies_used, vin)

            # Recompute total_cost (denormalized cache)
            await self._recompute_visit_total(visit.id)

            # Same commit as the item (G5a-07).
            await maintenance_service.reconcile_vehicle_unlocked(self.db, vin)
            await self.db.commit()

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
            # The reconcile below rewrites reminders: serialise with every
            # other rule writer before the first read.
            await lock_vehicle_for_write(self.db, vin)
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
            # Flushed before the reconcile reads history: sessions don't autoflush.
            await self.db.flush()

            # Recompute total_cost (denormalized cache)
            await self._recompute_visit_total(visit_id)

            # Same commit as the delete (G5a-07).
            await maintenance_service.reconcile_vehicle_unlocked(self.db, vin)
            await self.db.commit()

            logger.info(
                "Deleted line item %s from visit %s for %s",
                line_item_id,
                visit_id,
                sanitize_for_log(vin),
            )

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
        visit reflects its new usages (R1-F1). It also reverts any attribute
        set since the last flush, since sessions don't autoflush, so it flushes
        first.
        """
        # populate_existing overwrites loaded objects with the database's
        # values, and sessions don't autoflush: flush first, or an attribute set
        # since the last flush (a new item's temp-id link) silently reverts.
        await self.db.flush()
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
