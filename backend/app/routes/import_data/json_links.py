"""Line item links to recalls and warranties in a JSON backup (Task 8).

An item names its recall and warranty by their place in the file's lists. They
land once both lists are written, onto the rows those places became, stored
ones included when they matched. A restore keeps each recall's own resolution,
with two exceptions that hold I1 and I2 (Review Focus 3): a link onto an open
recall resolves it, and a recall this import wrote with resolved_via
'service_visit' that nothing links goes back to NULL.
"""

# pyright: reportPrivateUsage=false

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recall import Recall
from app.models.service_line_item import ServiceLineItem
from app.models.warranty import WarrantyRecord
from app.routes.import_data._service import _LINK_DROPPED
from app.services.recall_links import RESOLVED_BY_VISIT, link_recalls
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingLink:
    """An imported item and the places in the file its links point at."""

    # Only ever written after a failed savepoint: that expires it, and a read
    # would lazy-load outside the greenlet.
    item: ServiceLineItem
    visit_date: date
    recall: int | None
    warranty: int | None
    label: str  # "Service visit 2: line item 0"


async def _ours(
    db: AsyncSession, vin: str, model: type[Recall] | type[WarrantyRecord], ids: Mapping[int, int]
) -> dict[int, int]:
    """The entries of `ids` whose row is this vehicle's. The maps are built from this
    VIN's rows, but a link onto another garage must be impossible, not just unlikely."""
    if not ids:
        return {}
    query = select(model.id).where(model.id.in_(set(ids.values())), model.vin == vin)
    own = set((await db.scalars(query)).all())
    stray = {index for index, row_id in ids.items() if row_id not in own}
    if stray:
        logger.warning(
            "Import for vin=%s: dropped %d %s link(s) to another vehicle",
            sanitize_for_log(vin),
            len(stray),
            model.__tablename__,
        )
    return {index: row_id for index, row_id in ids.items() if row_id in own}


async def _taken_recalls(db: AsyncSession, ids: set[int]) -> set[int]:
    """The recalls in `ids` some line item links already."""
    if not ids:
        return set()
    query = select(ServiceLineItem.recall_id).where(ServiceLineItem.recall_id.in_(ids))
    return {int(rid) for rid in (await db.scalars(query)).all() if rid is not None}


async def _set_warranty(
    db: AsyncSession, link: PendingLink, warranty_id: int, warnings: list[str]
) -> None:
    try:
        async with db.begin_nested():
            link.item.warranty_id = warranty_id
            await db.flush()
    except Exception as e:
        logger.warning("Import: %s warranty link failed: %s", link.label, sanitize_for_log(e))
        warnings.append(f"{link.label}: its warranty couldn't be linked, {_LINK_DROPPED}")


async def _set_recall(
    db: AsyncSession, link: PendingLink, recall_id: int, warnings: list[str]
) -> bool:
    """Link the recall in its own savepoint; True when it held."""
    try:
        async with db.begin_nested():
            link.item.recall_id = recall_id
            await db.flush()
            # I1: a link onto an open recall resolves it on the visit date. A
            # resolved one keeps the resolution the file or this instance gave it.
            is_resolved = await db.scalar(select(Recall.is_resolved).where(Recall.id == recall_id))
            if not is_resolved:
                await link_recalls(db, [(recall_id, link.visit_date)])
    except Exception as e:
        logger.warning("Import: %s recall link failed: %s", link.label, sanitize_for_log(e))
        warnings.append(f"{link.label}: its recall couldn't be linked, {_LINK_DROPPED}")
        return False
    return True


async def _clear_unlinked(db: AsyncSession, recall_ids: set[int]) -> None:
    """I2: a recall this import wrote that says a visit resolved it, but no item links,
    reads as resolved by hand (NULL), so the Recalls tab can reopen it."""
    if not recall_ids:
        return
    linked = exists().where(ServiceLineItem.recall_id == Recall.id)
    rows = (
        await db.scalars(
            select(Recall)
            .where(Recall.id.in_(recall_ids), Recall.resolved_via == RESOLVED_BY_VISIT, ~linked)
            .execution_options(populate_existing=True)
        )
    ).all()
    for recall in rows:
        recall.resolved_via = None
    await db.flush()


async def restore_links(
    db: AsyncSession,
    vin: str,
    pending: Sequence[PendingLink],
    *,
    recall_ids: Mapping[int, int],
    warranty_ids: Mapping[int, int],
    written_recalls: Iterable[int],
    warnings: list[str],
) -> None:
    """Set each pending item's links, then hold I2 over the recalls this import wrote.

    `recall_ids` and `warranty_ids` map a place in the file to its row. A link
    with nothing there, or onto a recall something links already (in the database
    or earlier in this file), is dropped with a warning, never an error. Each one
    goes in its own savepoint, so a refused link can't take the import with it.
    """
    recalls = await _ours(db, vin, Recall, recall_ids)
    warranties = await _ours(db, vin, WarrantyRecord, warranty_ids)
    taken = await _taken_recalls(db, set(recalls.values()))

    for link in pending:
        # Warranty first: a refused recall link expires the item.
        if link.warranty is not None:
            warranty_id = warranties.get(link.warranty)
            if warranty_id is None:
                warnings.append(f"{link.label}: its warranty wasn't imported, {_LINK_DROPPED}")
            else:
                await _set_warranty(db, link, warranty_id, warnings)
        if link.recall is not None:
            recall_id = recalls.get(link.recall)
            if recall_id is None:
                warnings.append(f"{link.label}: its recall wasn't imported, {_LINK_DROPPED}")
            elif recall_id in taken:
                warnings.append(
                    f"{link.label}: its recall is already linked to another line item, "
                    f"{_LINK_DROPPED}"
                )
            elif await _set_recall(db, link, recall_id, warnings):
                taken.add(recall_id)

    # No savepoint: if this fails the import should too, not leave a recall stuck.
    await _clear_unlinked(db, set(written_recalls))
