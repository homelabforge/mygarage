from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import selectinload
from starlette.datastructures import Headers

from app.models.attachment import Attachment
from app.models.supply import Supply, SupplyPurchase, SupplyUsage
from app.schemas.supply import (
    SupplyAdjustmentCreate,
    SupplyCreate,
    SupplyPurchaseCreate,
    SupplyUpdate,
)
from app.services.file_upload_service import ATTACHMENT_UPLOAD_CONFIG
from app.services.supply_service import SupplyService

pytestmark = [pytest.mark.asyncio, pytest.mark.supplies]


async def _make_supply(db, **kw):
    s = Supply(
        name=kw.get("name", "Oil"),
        unit_type=kw.get("unit_type", "volume"),
        volume_unit=kw.get("volume_unit"),
    )
    db.add(s)
    await db.flush()
    return s


async def test_on_hand_and_avg_cost(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    db_session.add_all(
        [
            SupplyPurchase(
                supply_id=s.id,
                date=date.today(),
                quantity=Decimal("5"),
                total_cost=Decimal("40.00"),
            ),
            SupplyPurchase(
                supply_id=s.id,
                date=date.today(),
                quantity=Decimal("5"),
                total_cost=Decimal("50.00"),
            ),
            SupplyUsage(supply_id=s.id, quantity=Decimal("4")),
        ]
    )
    await db_session.flush()
    balances = await svc._compute_balances([s.id])
    on_hand, avg = balances[s.id]
    assert on_hand == Decimal("6.000")  # 10 purchased − 4 used
    assert avg == Decimal("9.0000")  # 90.00 / 10


async def test_avg_cost_ignores_costless_opening_stock(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    db_session.add_all(
        [
            SupplyPurchase(
                supply_id=s.id, date=date.today(), quantity=Decimal("2"), total_cost=None
            ),  # opening stock, no cost
            SupplyPurchase(
                supply_id=s.id, date=date.today(), quantity=Decimal("1"), total_cost=Decimal("8.00")
            ),
        ]
    )
    await db_session.flush()
    on_hand, avg = (await svc._compute_balances([s.id]))[s.id]
    assert on_hand == Decimal("3.000")  # both count toward on-hand
    assert avg == Decimal("8.0000")  # only the costed 1 unit divides the cost


async def test_negative_on_hand_allowed(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    db_session.add(SupplyUsage(supply_id=s.id, quantity=Decimal("2")))
    await db_session.flush()
    on_hand, avg = (await svc._compute_balances([s.id]))[s.id]
    assert on_hand == Decimal("-2.000")
    assert avg is None


async def test_delete_archives_when_history_exists(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    db_session.add(SupplyPurchase(supply_id=s.id, date=date.today(), quantity=Decimal("1")))
    await db_session.flush()
    archived = await svc.delete_supply(s.id, None)
    assert archived is True
    refetched = await svc.get_supply(s.id)
    assert refetched.is_active is False


async def test_delete_hard_deletes_when_no_history(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    archived = await svc.delete_supply(s.id, None)
    assert archived is False
    with pytest.raises(HTTPException):
        await svc.get_supply(s.id)


async def test_create_and_response_carry_the_unit(db_session):
    svc = SupplyService(db_session)
    created = await svc.create_supply(
        SupplyCreate(name="Brake fluid", unit_type="volume", volume_unit="fl_oz_us"), None
    )
    assert created.volume_unit == "fl_oz_us"


async def test_patch_sets_and_clears_the_unit(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    updated = await svc.update_supply(s.id, SupplyUpdate(volume_unit="qt_uk"), None)
    assert updated.volume_unit == "qt_uk"
    cleared = await svc.update_supply(s.id, SupplyUpdate(volume_unit=None), None)
    assert cleared.volume_unit is None


async def test_patch_unit_onto_a_count_supply_is_422(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session, unit_type="count")
    with pytest.raises(HTTPException) as e:
        await svc.update_supply(s.id, SupplyUpdate(name="Renamed", volume_unit="qt_us"), None)
    assert e.value.status_code == 422
    assert e.value.detail == "A count supply cannot carry a volume unit"
    # The check runs before anything is set, so the refused patch leaves nothing behind.
    assert s.name == "Oil"
    assert s not in db_session.dirty


async def test_patch_clearing_the_unit_on_a_count_supply_is_allowed(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session, unit_type="count")
    updated = await svc.update_supply(s.id, SupplyUpdate(volume_unit=None), None)
    assert updated.volume_unit is None


async def test_usage_response_carries_the_owning_supplys_unit(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session, volume_unit="mL")
    db_session.add(SupplyUsage(supply_id=s.id, quantity=Decimal("2")))
    await db_session.flush()
    usage = (
        await db_session.execute(
            select(SupplyUsage)
            .where(SupplyUsage.supply_id == s.id)
            .options(selectinload(SupplyUsage.supply))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert svc.to_usage_response(usage).volume_unit == "mL"


# S-frac: a counted supply takes whole numbers. Old rows aren't touched.
_WHOLE = "A count supply takes whole numbers"


async def _purchases_of(db, supply_id: int) -> list[SupplyPurchase]:
    rows = await db.execute(select(SupplyPurchase).where(SupplyPurchase.supply_id == supply_id))
    return list(rows.scalars().all())


async def test_purchase_of_a_fractional_count_is_422(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session, unit_type="count")
    with pytest.raises(HTTPException) as e:
        await svc.add_purchase(
            s.id, SupplyPurchaseCreate(date=date(2026, 5, 1), quantity=Decimal("2.5")), None
        )
    assert e.value.status_code == 422
    assert e.value.detail == _WHOLE
    assert await _purchases_of(db_session, s.id) == []


async def test_purchase_of_a_whole_count_with_trailing_zeros_saves(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session, unit_type="count")
    await svc.add_purchase(
        s.id,
        SupplyPurchaseCreate(date=date(2026, 5, 1), quantity=Decimal("2.0000000000000")),
        None,
    )
    [row] = await _purchases_of(db_session, s.id)
    assert row.quantity == 2


async def test_purchase_of_a_fractional_volume_saves(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    await svc.add_purchase(
        s.id, SupplyPurchaseCreate(date=date(2026, 5, 1), quantity=Decimal("2.5")), None
    )
    [row] = await _purchases_of(db_session, s.id)
    assert row.quantity == Decimal("2.5")


async def test_adjustment_of_a_fractional_count_is_422(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session, unit_type="count")
    with pytest.raises(HTTPException) as e:
        await svc.add_adjustment(s.id, SupplyAdjustmentCreate(quantity=Decimal("1.5")), None)
    assert e.value.status_code == 422
    assert e.value.detail == _WHOLE
    rows = await db_session.execute(select(SupplyUsage).where(SupplyUsage.supply_id == s.id))
    assert rows.scalars().all() == []


# ---- purchase receipts ------------------------------------------------------


def _pdf(name: str, body: bytes) -> UploadFile:
    return UploadFile(
        file=BytesIO(body), filename=name, headers=Headers({"content-type": "application/pdf"})
    )


@pytest.fixture
def receipts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ATTACHMENT_UPLOAD_CONFIG, "base_dir", tmp_path)
    return tmp_path


def _files(root: Path) -> list[Path]:
    return sorted(f for f in root.rglob("*") if f.is_file())


async def _purchase(db) -> tuple[int, int]:
    s = await _make_supply(db)
    p = SupplyPurchase(supply_id=s.id, date=date.today(), quantity=Decimal("1"))
    db.add(p)
    await db.commit()
    return s.id, p.id


async def _receipt_ids(db, purchase_id: int) -> list[int]:
    rows = await db.execute(
        select(Attachment.id)
        .where(Attachment.record_type == "supply_purchase")
        .where(Attachment.record_id == purchase_id)
    )
    return list(rows.scalars().all())


async def test_replace_receipt_swaps_the_old_file_for_the_new(db_session, receipts_dir):
    svc = SupplyService(db_session)
    sid, pid = await _purchase(db_session)
    first = await svc.replace_receipt(sid, pid, _pdf("first.pdf", b"%PDF-1.4 first"))
    first_path = Path(first.file_path)
    assert first_path.read_bytes() == b"%PDF-1.4 first"

    second = await svc.replace_receipt(sid, pid, _pdf("second.pdf", b"%PDF-1.4 second"))
    assert second.file_type == "application/pdf"
    assert _files(receipts_dir) == [Path(second.file_path)]
    assert Path(second.file_path).read_bytes() == b"%PDF-1.4 second"
    assert await _receipt_ids(db_session, pid) == [second.id]


async def test_replace_receipt_404s_a_purchase_on_another_supply(db_session, receipts_dir):
    svc = SupplyService(db_session)
    _, pid = await _purchase(db_session)
    other = await _make_supply(db_session, name="Other")
    with pytest.raises(HTTPException) as e:
        await svc.replace_receipt(other.id, pid, _pdf("r.pdf", b"%PDF-1.4 r"))
    assert e.value.status_code == 404
    assert _files(receipts_dir) == []


async def test_losing_the_receipt_race_is_a_409_and_keeps_the_old_one(
    db_session, receipts_dir, monkeypatch: pytest.MonkeyPatch
):
    svc = SupplyService(db_session)
    sid, pid = await _purchase(db_session)
    old = await svc.replace_receipt(sid, pid, _pdf("old.pdf", b"%PDF-1.4 old"))
    old_id, old_path = old.id, Path(old.file_path)

    async def lost_the_race() -> None:
        raise IntegrityError("INSERT INTO attachments", {}, Exception("UNIQUE constraint failed"))

    monkeypatch.setattr(db_session, "commit", lost_the_race)
    with pytest.raises(HTTPException) as e:
        await svc.replace_receipt(sid, pid, _pdf("new.pdf", b"%PDF-1.4 new"))
    assert e.value.status_code == 409
    assert e.value.detail == "A receipt for this purchase already exists"
    # The new file is cleaned up, and the old row and file are untouched.
    assert _files(receipts_dir) == [old_path]
    assert await _receipt_ids(db_session, pid) == [old_id]


async def test_any_other_commit_failure_leaves_no_new_file(
    db_session, receipts_dir, monkeypatch: pytest.MonkeyPatch
):
    svc = SupplyService(db_session)
    sid, pid = await _purchase(db_session)
    old = await svc.replace_receipt(sid, pid, _pdf("old.pdf", b"%PDF-1.4 old"))
    old_id, old_path = old.id, Path(old.file_path)

    async def disk_gone() -> None:
        raise OperationalError("COMMIT", {}, Exception("disk I/O error"))

    monkeypatch.setattr(db_session, "commit", disk_gone)
    with pytest.raises(OperationalError):
        await svc.replace_receipt(sid, pid, _pdf("new.pdf", b"%PDF-1.4 new"))
    assert _files(receipts_dir) == [old_path]
    assert await _receipt_ids(db_session, pid) == [old_id]
