"""Line item links to recalls and warranties (D1, D8-D13).

A link to an open recall resolves it on the visit's date; losing the link
reopens it, but only when the link was what resolved it. Nothing here commits:
the visit writers own the transaction and call these under the vehicle lock.
"""

import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recall import Recall
from app.models.service_line_item import ServiceLineItem
from app.models.warranty import WarrantyRecord
from app.utils.household_time import household_wall_clock_to_utc

logger = logging.getLogger(__name__)

#: resolved_via for a recall a line item resolved (D10).
RESOLVED_BY_VISIT = "service_visit"

#: (item, recall_id, warranty_id): the links an item should end up with.
WantedLinks = tuple[ServiceLineItem, int | None, int | None]


def resolved_at_for(visit_date: date) -> datetime:
    """Household noon on the visit's date, as naive UTC (D13)."""
    return household_wall_clock_to_utc(datetime.combine(visit_date, time(12)))


#: Each link column and the table it points at.
_LINK_TARGETS: dict[str, type[Recall] | type[WarrantyRecord]] = {
    "recall_id": Recall,
    "warranty_id": WarrantyRecord,
}
#: A new item's answer for an id that isn't this vehicle's. No id in it, so a
#: missing id and another garage's read exactly the same.
_NOT_OURS = {
    "recall_id": "The linked recall is not on this vehicle",
    "warranty_id": "The linked warranty is not on this vehicle",
}


async def _own_ids(db: AsyncSession, vin: str, link: str, ids: set[int]) -> set[int]:
    """The ids in `ids` that point at this vehicle's rows."""
    if not ids:
        return set()
    model = _LINK_TARGETS[link]
    query = select(model.id).where(model.id.in_(ids), model.vin == vin)
    return set((await db.scalars(query)).all())


async def known_ids(
    db: AsyncSession, vin: str, sent: Mapping[str, Iterable[int]]
) -> dict[str, set[int]]:
    """Of the ids sent per link column, the ones that are this vehicle's.

    An existing item treats anything else as cleared, whether it was deleted
    since the form loaded or never was ours, so the two can't be told apart.
    """
    return {link: await _own_ids(db, vin, link, set(sent.get(link, ()))) for link in _LINK_TARGETS}


async def validate_links(db: AsyncSession, vin: str, items: Sequence[ServiceLineItem]) -> None:
    """422 when a recall or warranty belongs to another VIN or doesn't exist; 409 when a
    recall is already linked by an item outside `items`.

    `items` is every item the visit keeps, links set but not flushed. Missing and
    other-VIN ids get the same 422, word for word, so it can't probe another garage.
    """
    for link in _LINK_TARGETS:
        wanted = {v for v in (getattr(i, link) for i in items) if v is not None}
        if wanted - await _own_ids(db, vin, link, wanted):
            raise HTTPException(status_code=422, detail=_NOT_OURS[link])

    recall_ids = [i.recall_id for i in items if i.recall_id is not None]
    if recall_ids:
        seen: set[int] = set()
        for rid in recall_ids:
            if rid in seen:
                raise HTTPException(
                    status_code=409, detail=f"Recall {rid} is already linked to another line item"
                )
            seen.add(rid)
        query = select(ServiceLineItem.recall_id).where(ServiceLineItem.recall_id.in_(seen))
        # Only items with a row: an unflushed one's NULL id in NOT IN would
        # match nothing and let a second link through.
        ours = [i.id for i in items if sa_inspect(i).has_identity]
        if ours:
            query = query.where(ServiceLineItem.id.not_in(ours))
        # IN never matches NULL; the filter only narrows the type.
        taken = sorted({int(rid) for rid in (await db.scalars(query)).all() if rid is not None})
        if taken:
            raise HTTPException(
                status_code=409,
                detail=f"Recall {taken[0]} is already linked to another line item",
            )


async def unlink_recalls(db: AsyncSession, recall_ids: Iterable[int | None]) -> None:
    """Reopen each recall whose resolved_via is 'service_visit'; leave manual ones resolved.

    Call it once the link is gone (or about to go with its item). Flushes.
    """
    ids = {rid for rid in recall_ids if rid is not None}
    if not ids:
        return
    # The filter runs in SQL and every field gets overwritten, so a stale copy
    # in the session can't skew this one.
    rows = (
        await db.scalars(
            select(Recall).where(Recall.id.in_(ids), Recall.resolved_via == RESOLVED_BY_VISIT)
        )
    ).all()
    for recall in rows:
        recall.is_resolved = False
        recall.resolved_at = None
        recall.resolved_via = None
        logger.info("Reopened recall %s: its line item link is gone", recall.id)
    await db.flush()


async def link_recalls(db: AsyncSession, links: Iterable[tuple[int, date]]) -> None:
    """Unresolved: resolve with resolved_via='service_visit' and resolved_at=noon(date).
    Already resolved: keep resolved_via, move resolved_at to noon(date) (D10, D12).

    Flushes.
    """
    by_id = dict(links)
    if not by_id:
        return
    # populate_existing: the branch below reads is_resolved, and the session may
    # hold a copy from before someone resolved it by hand.
    rows = (
        await db.scalars(
            select(Recall).where(Recall.id.in_(by_id)).execution_options(populate_existing=True)
        )
    ).all()
    for recall in rows:
        if not recall.is_resolved:
            recall.is_resolved = True
            recall.resolved_via = RESOLVED_BY_VISIT
        recall.resolved_at = resolved_at_for(by_id[recall.id])
    await db.flush()


async def apply_links(
    db: AsyncSession,
    vin: str,
    visit_date: date,
    items: Sequence[ServiceLineItem],
    wanted: Sequence[WantedLinks],
    before: Iterable[int | None],
    *,
    restamp: bool = False,
) -> None:
    """Give each item in `wanted` its links, and resolve or reopen recalls to match.

    `items` is every item the visit keeps after this write (dropped ones are
    already deleted), `before` the recall ids the visit linked before it, and
    `restamp` says the visit's date moved (D12). Detaches first and flushes, so
    a recall moving or swapping between items never holds the unique index twice.
    """
    before_ids = {rid for rid in before if rid is not None}

    # 1. Detach every link that changes, and flush before anything is set.
    detached = False
    for item, recall_id, _warranty_id in wanted:
        if item.recall_id is not None and item.recall_id != recall_id:
            item.recall_id = None
            detached = True
    if detached:
        await db.flush()
    after_ids = {rid for _item, rid, _wid in wanted if rid is not None} | {
        i.recall_id for i in items if i.recall_id is not None
    }
    await unlink_recalls(db, before_ids - after_ids)

    # 2. Set the new links, check them, flush. The relationships are expired so
    # the response reloads what the ids now point at (expire_on_commit is off).
    for item, recall_id, warranty_id in wanted:
        item.recall_id = recall_id
        item.warranty_id = warranty_id
        db.expire(item, ["recall", "warranty"])
    await validate_links(db, vin, items)
    await db.flush()

    # 3. Resolve, or move the date of, every recall the visit links now.
    linked = {i.recall_id for i in items if i.recall_id is not None}
    if linked != before_ids or restamp:
        await link_recalls(db, [(rid, visit_date) for rid in linked])
