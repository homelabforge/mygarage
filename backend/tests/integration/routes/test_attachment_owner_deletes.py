"""Deleting a record that owns attachments takes the rows and the files with it.

Attachments are polymorphic (record_type/record_id, no FK), so no cascade
reaches them. Only two types are ever created: service-visit attachments and
supply-purchase receipts. Each delete path that can remove one of those owners
is pinned here; the vehicle delete's visit case lives in
tests/integration/test_vehicle_delete_integrity.py.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.attachment import Attachment
from app.models.service_visit import ServiceVisit
from app.models.supply import Supply, SupplyPurchase
from app.models.user import User
from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# A fixed past day keeps these rows out of every "today" and far-future guard.
_DAY = date(2024, 3, 1)


@pytest.fixture
def attachments_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Attachment files land in tmp, inside the root the cleanup is allowed to touch."""
    root = tmp_path / "attachments"
    monkeypatch.setattr(settings, "attachments_dir", root)
    return root


async def _attach(
    db: AsyncSession, root: Path, record_type: str, record_id: int
) -> tuple[int, Path]:
    """One attachment row plus its file on disk, laid out like an upload."""
    path = root / record_type / str(record_id) / "receipt.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"pdf")
    row = Attachment(
        record_type=record_type,
        record_id=record_id,
        file_path=str(path),
        file_type="application/pdf",
        file_size=3,
    )
    db.add(row)
    await db.commit()
    return row.id, path


async def _attachment_exists(db: AsyncSession, attachment_id: int) -> bool:
    count = await db.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.id == attachment_id)
    )
    return bool(count)


async def _visit(db: AsyncSession, vin: str) -> int:
    visit = ServiceVisit(vin=vin, date=_DAY, service_category="Maintenance")
    db.add(visit)
    await db.commit()
    return visit.id


async def _pinned_purchase(db: AsyncSession, vin: str) -> int:
    """A purchase on a supply pinned to this vehicle, so the vehicle's delete cascades it."""
    supply = Supply(name="Owner delete oil", unit_type="volume", vin=vin)
    db.add(supply)
    await db.flush()
    purchase = SupplyPurchase(supply_id=supply.id, date=_DAY, quantity=Decimal("1"))
    db.add(purchase)
    await db.commit()
    return purchase.id


@pytest_asyncio.fixture
async def stray_attachments(db_session: AsyncSession) -> AsyncIterator[list[int]]:
    """Attachment ids a test makes; whatever a failed run leaves gets deleted."""
    ids: list[int] = []
    yield ids
    await db_session.rollback()
    await db_session.execute(delete(Attachment).where(Attachment.id.in_(ids)))
    await db_session.commit()


async def test_deleting_a_service_visit_removes_its_attachments(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    own_vehicle: Vehicle,
    attachments_dir: Path,
    stray_attachments: list[int],
) -> None:
    vin = own_vehicle.vin
    visit_id = await _visit(db_session, vin)
    attachment_id, path = await _attach(db_session, attachments_dir, "service_visit", visit_id)
    stray_attachments.append(attachment_id)

    response = await client.delete(
        f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=auth_headers
    )

    assert response.status_code == 204, response.text
    assert not await _attachment_exists(db_session, attachment_id), "attachment row orphaned"
    assert not path.exists(), "attachment file orphaned"


async def test_deleting_a_vehicle_removes_its_pinned_supplies_receipts(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    own_vehicle: Vehicle,
    attachments_dir: Path,
    stray_attachments: list[int],
) -> None:
    """A supply pinned to the vehicle cascades away with it, and so must its receipts."""
    vin = own_vehicle.vin
    purchase_id = await _pinned_purchase(db_session, vin)
    attachment_id, path = await _attach(db_session, attachments_dir, "supply_purchase", purchase_id)
    stray_attachments.append(attachment_id)

    response = await client.delete(f"/api/vehicles/{vin}", headers=auth_headers)

    assert response.status_code == 204, response.text
    assert await db_session.get(SupplyPurchase, purchase_id) is None, "control: cascade ran"
    assert not await _attachment_exists(db_session, attachment_id), "receipt row orphaned"
    assert not path.exists(), "receipt file orphaned"


async def test_deleting_a_user_removes_their_vehicles_attachments(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    attachments_dir: Path,
    made_users: list[str],
    stray_attachments: list[int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user's vehicles go by FK cascade, which never sees the attachment table
    or the vehicle's own upload directory."""
    leaver = User(
        username="att_leaver_" + uuid.uuid4().hex[:6],
        email=f"att-leaver-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(leaver)
    made_users.append(leaver.username)
    await db_session.flush()
    vin = "ATT" + uuid.uuid4().hex[:14].upper()
    db_session.add(
        Vehicle(vin=vin, user_id=leaver.id, nickname="Leaver", vehicle_type="Car", year=2015)
    )
    await db_session.commit()
    leaver_id = leaver.id

    visit_att, visit_path = await _attach(
        db_session, attachments_dir, "service_visit", await _visit(db_session, vin)
    )
    receipt_att, receipt_path = await _attach(
        db_session, attachments_dir, "supply_purchase", await _pinned_purchase(db_session, vin)
    )
    stray_attachments += [visit_att, receipt_att]
    photos_dir = tmp_path / "photos"
    monkeypatch.setattr(settings, "photos_dir", photos_dir)
    photo = photos_dir / vin / "front.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"jpg")

    response = await client.delete(f"/api/auth/users/{leaver_id}", headers=auth_headers)

    assert response.status_code == 204, response.text
    assert await db_session.get(Vehicle, vin) is None, "control: the vehicle cascade ran"
    assert not await _attachment_exists(db_session, visit_att), "visit attachment row orphaned"
    assert not await _attachment_exists(db_session, receipt_att), "receipt row orphaned"
    assert not visit_path.exists(), "visit attachment file orphaned"
    assert not receipt_path.exists(), "receipt file orphaned"
    assert not photo.parent.exists(), "the vehicle's photo directory orphaned"
