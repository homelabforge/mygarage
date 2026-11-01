"""Attachments go with the record that owns them.

They're polymorphic (record_type/record_id, no FK), so no cascade reaches
them. A delete that removes an owner drops the attachment rows in its own
transaction and unlinks the files only after that commits, so a rollback
never loses a file a live row still points at.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable
from pathlib import Path

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.attachment import Attachment
from app.models.fuel import FuelRecord
from app.models.note import Note
from app.models.service_visit import ServiceVisit
from app.models.supply import Supply, SupplyPurchase
from app.models.tax import TaxRecord
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


async def purge_record_attachments(db: AsyncSession, record_type: str, record_id: int) -> list[str]:
    """Delete one record's attachment rows (not committed); return their file paths."""
    rows = (
        await db.execute(
            select(Attachment.id, Attachment.file_path).where(
                Attachment.record_type == record_type, Attachment.record_id == record_id
            )
        )
    ).all()
    if rows:
        await db.execute(delete(Attachment).where(Attachment.id.in_([r.id for r in rows])))
    return [r.file_path for r in rows]


async def purge_vehicle_attachments(db: AsyncSession, vins: Collection[str]) -> list[str]:
    """Delete the attachment rows of every record on these vehicles (not committed).

    Run it before the vehicles go, while the parent rows can still be resolved.
    Legacy types whose parent tables were dropped (service, upgrade, collision)
    can't be tied to a VIN and are left alone.
    """
    if not vins:
        return []
    parent_ids = {
        "service_visit": select(ServiceVisit.id).where(ServiceVisit.vin.in_(vins)),
        "fuel": select(FuelRecord.id).where(FuelRecord.vin.in_(vins)),
        "tax": select(TaxRecord.id).where(TaxRecord.vin.in_(vins)),
        "note": select(Note.id).where(Note.vin.in_(vins)),
        # A supply pinned to a vehicle cascades away with it, purchases and all.
        "supply_purchase": select(SupplyPurchase.id)
        .join(Supply, SupplyPurchase.supply_id == Supply.id)
        .where(Supply.vin.in_(vins)),
    }
    rows = (
        await db.execute(
            select(Attachment.id, Attachment.file_path).where(
                or_(
                    *(
                        and_(Attachment.record_type == kind, Attachment.record_id.in_(ids))
                        for kind, ids in parent_ids.items()
                    )
                )
            )
        )
    ).all()
    if rows:
        await db.execute(delete(Attachment).where(Attachment.id.in_([r.id for r in rows])))
    return [r.file_path for r in rows]


def unlink_contained(paths: Iterable[str | None]) -> None:
    """Unlink each file that resolves inside one of the app's data roots.

    Anything outside them is skipped: a stored path is data, not a licence to
    delete wherever it points. Raises OSError; callers decide how to degrade.
    """
    allowed_roots = [
        settings.data_dir.resolve(),
        settings.photos_dir.resolve(),
        settings.documents_dir.resolve(),
        settings.attachments_dir.resolve(),
    ]
    for raw in paths:
        if not raw:
            continue
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = settings.data_dir / candidate
        resolved = candidate.resolve()
        if resolved.is_file() and any(resolved.is_relative_to(root) for root in allowed_roots):
            resolved.unlink(missing_ok=True)


def remove_attachment_files(paths: Iterable[str]) -> None:
    """Best-effort unlink after the owner's delete has committed. Never raises."""
    try:
        unlink_contained(paths)
    except OSError as e:
        logger.warning(
            "Attachment file cleanup left orphans (the delete itself succeeded): %s",
            sanitize_for_log(e),
        )
