"""Price the usages a supply had before it had a cost, once it has one (#301).

A usage freezes its price when it's logged, at the supply's average over costed
purchases. Logged before any costed purchase, it has no price (``cost_snapshot``
NULL), and a visit counted it as nothing. When a costed purchase lands, this
prices those usages on every vehicle the buyer can write. A vehicle they can't
write waits for one of its own writers to touch the visit
(``ServiceVisitService.price_unpriced_on_visit``).

The purchase is committed before this runs and its answer has to say so, so
nothing here fails the request: a vehicle that can't be priced is logged and
skipped, and the next opportunity prices it.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.supply import Supply, SupplyUsage
from app.models.user import User
from app.services.auth import get_vehicle_or_403
from app.services.service_visit_service import ServiceVisitService
from app.services.supply_service import SupplyService, usage_price
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


async def price_after_purchase(
    request_db: AsyncSession, supply_id: int, user_id: int | None
) -> None:
    """Price the supply's unpriced usages after a costed purchase. Never raises.

    `user_id` is the buyer's id, or None when auth is off; an id, since the
    request's user can be expired by then (see ``_own_session``). Call it with
    the request's transaction ended, so the request never holds two pool
    connections.
    """
    try:
        async with _own_session(request_db) as db:
            await _price_supply(db, supply_id, user_id)
    except Exception:
        logger.exception("Pricing usages of supply %s after a purchase failed", supply_id)


async def price_after_import(request_db: AsyncSession, vin: str, user_id: int | None) -> None:
    """Price what a vehicle import left with no cost. Never raises.

    Imported usages keep the file's snapshots, and a file from before #301 can
    carry usages with no cost whose supply has one now. The import wrote those
    visits, and a visit write prices them, so each supply with an unpriced usage
    on the vehicle (on its visits, or a supply pinned to it) goes through what a
    costed purchase of it does. That reaches as far as a purchase would: the
    supply's unpriced usages on every vehicle the importer can write, and its
    standalone adjustments. Call it after the import commits.
    """
    try:
        async with _own_session(request_db) as db:
            supply_ids = (
                (
                    await db.execute(
                        select(SupplyUsage.supply_id)
                        .join(Supply, Supply.id == SupplyUsage.supply_id)
                        .outerjoin(
                            ServiceLineItem, ServiceLineItem.id == SupplyUsage.service_line_item_id
                        )
                        .outerjoin(ServiceVisit, ServiceVisit.id == ServiceLineItem.visit_id)
                        .where(
                            SupplyUsage.cost_snapshot.is_(None),
                            or_(ServiceVisit.vin == vin, Supply.vin == vin),
                        )
                        .distinct()
                        .order_by(SupplyUsage.supply_id)
                    )
                )
                .scalars()
                .all()
            )
    except Exception:
        logger.exception(
            "Finding unpriced supplies after importing %s failed", sanitize_for_log(vin)
        )
        return
    for supply_id in supply_ids:
        await price_after_purchase(request_db, supply_id, user_id)


def _own_session(request_db: AsyncSession) -> AsyncSession:
    """A session of its own on the request's engine.

    A vehicle that fails is rolled back, and a rollback expires every object in
    its session, the flags notwithstanding: in the request's session that would
    be what the route still has to answer with, and the user.
    """
    engine = request_db.bind
    if not isinstance(engine, AsyncEngine):
        # Every session in the app is bound to the one engine; see post_commit.
        raise TypeError("supply pricing needs a session bound to an AsyncEngine")
    return AsyncSession(engine, expire_on_commit=False, autoflush=False)


async def _price_supply(db: AsyncSession, supply_id: int, user_id: int | None) -> None:
    vins = (
        (
            await db.execute(
                select(ServiceVisit.vin)
                .join(ServiceLineItem, ServiceLineItem.visit_id == ServiceVisit.id)
                .join(SupplyUsage, SupplyUsage.service_line_item_id == ServiceLineItem.id)
                .where(SupplyUsage.supply_id == supply_id, SupplyUsage.cost_snapshot.is_(None))
                .distinct()
                .order_by(ServiceVisit.vin)
            )
        )
        .scalars()
        .all()
    )
    allowed, _user = await _buyer(db, user_id)
    if not allowed:
        return
    # No commit before the first lock: on SQLite a bare SELECT leaves the driver
    # outside a transaction, which the lock's BEGIN IMMEDIATE needs.
    for vin in vins:
        allowed, user = await _buyer(db, user_id)
        if not allowed:
            return
        try:
            await get_vehicle_or_403(vin, user, db, require_write=True)
        except HTTPException:
            continue  # not theirs to write; it waits for one of its writers
        try:
            # The same lock every visit writer takes, so a visit edit can't
            # interleave with the re-read and recompute below.
            await lock_vehicle_for_write(db, vin)
            await _price_vehicle(db, vin, supply_id)
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.warning(
                "Could not price supply %s usages on %s: %s",
                supply_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
    await _price_adjustments(db, supply_id)


async def _buyer(db: AsyncSession, user_id: int | None) -> tuple[bool, User | None]:
    """(whether pricing may go on, the buyer), the buyer loaded fresh.

    Fresh: a failed vehicle's rollback expires it (see ``_own_session``). A buyer who is gone or
    inactive stops it: passing None on would read as auth off and every vehicle
    would pass. None for `user_id` is auth off.
    """
    if user_id is None:
        return True, None
    user = await db.get(User, user_id, populate_existing=True)
    if user is not None and user.is_active:
        return True, user
    logger.warning("Buyer %s is gone or inactive; pricing stopped", user_id)
    return False, None


async def _price_vehicle(db: AsyncSession, vin: str, supply_id: int) -> None:
    """Price the visits on one vehicle that have the supply unpriced. Holds its lock.

    Each visit goes through the same pricer a visit write uses, so it reads the
    averages again under the lock and also prices the visit's other unpriced
    supplies, which any edit of that visit would do anyway.
    """
    visit_ids = (
        (
            await db.execute(
                select(ServiceLineItem.visit_id)
                .join(SupplyUsage, SupplyUsage.service_line_item_id == ServiceLineItem.id)
                .join(ServiceVisit, ServiceVisit.id == ServiceLineItem.visit_id)
                .where(
                    ServiceVisit.vin == vin,
                    SupplyUsage.supply_id == supply_id,
                    SupplyUsage.cost_snapshot.is_(None),
                )
                .distinct()
                .order_by(ServiceLineItem.visit_id)
            )
        )
        .scalars()
        .all()
    )
    visits = ServiceVisitService(db)
    for visit_id in visit_ids:
        await visits.price_unpriced_on_visit(visit_id)


async def _price_adjustments(db: AsyncSession, supply_id: int) -> None:
    """Price the supply's unpriced standalone adjustments. No vehicle, no visit total."""
    rows = (
        await db.execute(
            select(SupplyUsage.id, SupplyUsage.unit_cost_snapshot, SupplyUsage.quantity)
            .where(
                SupplyUsage.supply_id == supply_id,
                SupplyUsage.service_line_item_id.is_(None),
                SupplyUsage.cost_snapshot.is_(None),
            )
            # One order for every pricer, so two can't deadlock updating them.
            .order_by(SupplyUsage.id)
        )
    ).all()
    if not rows:
        return
    avg = await SupplyService(db).compute_avg_unit_cost(supply_id)
    for usage_id, unit_snapshot, quantity in rows:
        price = usage_price(unit_snapshot, quantity, avg)
        if price is None:
            continue
        unit, cost = price
        # Only if still unpriced, so a racing pricer can't price it twice.
        await db.execute(
            update(SupplyUsage)
            .where(SupplyUsage.id == usage_id, SupplyUsage.cost_snapshot.is_(None))
            .values(unit_cost_snapshot=unit, cost_snapshot=cost)
        )
    await db.commit()
