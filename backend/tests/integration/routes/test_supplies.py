"""Integration tests for the global supplies catalog router (`/api/supplies`).

Catalog CRUD (Task 6), purchase/adjustment/history routes (Task 7), and
purchase-receipt attachment routes (Task 8).
"""

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.supply import SupplyPurchase

pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.supplies]


async def test_create_and_list_supply(client: AsyncClient, auth_headers):
    """A freshly created supply appears in the list with a zero balance."""
    r = await client.post(
        "/api/supplies",
        json={"name": "Mobil 1 5W-30", "unit_type": "volume"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    body = r.json()
    sid = body["id"]
    assert body["name"] == "Mobil 1 5W-30"
    assert body["unit_type"] == "volume"
    assert body["is_active"] is True
    assert float(body["on_hand"]) == 0.0
    assert body["is_negative"] is False

    lr = await client.get("/api/supplies", headers=auth_headers)
    assert lr.status_code == 200
    lbody = lr.json()
    item = next(s for s in lbody["supplies"] if s["id"] == sid)
    assert float(item["on_hand"]) == 0.0
    assert item["is_negative"] is False
    assert item["avg_unit_cost"] is None


async def test_list_requires_auth(client: AsyncClient):
    assert (await client.get("/api/supplies")).status_code == 401


async def test_get_supply(client: AsyncClient, auth_headers):
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Air Filter", "unit_type": "count"},
            headers=auth_headers,
        )
    ).json()["id"]

    gr = await client.get(f"/api/supplies/{sid}", headers=auth_headers)
    assert gr.status_code == 200
    body = gr.json()
    assert body["id"] == sid
    assert body["name"] == "Air Filter"
    assert body["unit_type"] == "count"


async def test_get_supply_not_found(client: AsyncClient, auth_headers):
    assert (await client.get("/api/supplies/999999", headers=auth_headers)).status_code == 404


async def test_update_supply(client: AsyncClient, auth_headers):
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Old Name", "unit_type": "count"},
            headers=auth_headers,
        )
    ).json()["id"]

    pr = await client.patch(
        f"/api/supplies/{sid}",
        json={"name": "New Name"},
        headers=auth_headers,
    )
    assert pr.status_code == 200
    body = pr.json()
    assert body["name"] == "New Name"
    # unit_type unaffected — immutable, not part of SupplyUpdate
    assert body["unit_type"] == "count"


async def test_delete_hard_deletes_supply_without_history(client: AsyncClient, auth_headers):
    """A supply with no purchase/usage history is hard-deleted, not archived."""
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Unused Widget", "unit_type": "count"},
            headers=auth_headers,
        )
    ).json()["id"]

    dr = await client.delete(f"/api/supplies/{sid}", headers=auth_headers)
    assert dr.status_code == 204

    gr = await client.get(f"/api/supplies/{sid}", headers=auth_headers)
    assert gr.status_code == 404


async def test_delete_archives_supply_with_history(
    client: AsyncClient, auth_headers, db_session: AsyncSession
):
    """A supply with ledger history is soft-archived: excluded from the default
    list, still visible with ?include_archived=true, and is_active=False."""
    sid = (
        await client.post(
            "/api/supplies", json={"name": "Filter", "unit_type": "count"}, headers=auth_headers
        )
    ).json()["id"]

    # Seed history directly (Task 7's purchase route doesn't exist yet).
    purchase = SupplyPurchase(supply_id=sid, date=date(2026, 1, 1), quantity=Decimal("3"))
    db_session.add(purchase)
    await db_session.flush()

    dr = await client.delete(f"/api/supplies/{sid}", headers=auth_headers)
    assert dr.status_code == 204

    default = (await client.get("/api/supplies", headers=auth_headers)).json()
    assert all(s["id"] != sid for s in default["supplies"])

    archived = (
        await client.get("/api/supplies?include_archived=true", headers=auth_headers)
    ).json()
    match = next(s for s in archived["supplies"] if s["id"] == sid)
    assert match["is_active"] is False


# ---- purchases (Task 7) -----------------------------------------------------


async def test_add_purchase(client: AsyncClient, auth_headers):
    """A purchase raises on_hand and is returned with a null receipt."""
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Oil Filter", "unit_type": "count"},
            headers=auth_headers,
        )
    ).json()["id"]

    pr = await client.post(
        f"/api/supplies/{sid}/purchases",
        json={"date": "2026-01-05", "quantity": "3", "total_cost": "15.00"},
        headers=auth_headers,
    )
    assert pr.status_code == 201
    body = pr.json()
    assert body["supply_id"] == sid
    assert body["date"] == "2026-01-05"
    assert float(body["quantity"]) == 3.0
    assert float(body["total_cost"]) == 15.0
    assert body["receipt"] is None

    gr = await client.get(f"/api/supplies/{sid}", headers=auth_headers)
    gbody = gr.json()
    assert float(gbody["on_hand"]) == 3.0
    assert float(gbody["avg_unit_cost"]) == 5.0


async def test_add_purchase_supply_not_found(client: AsyncClient, auth_headers):
    r = await client.post(
        "/api/supplies/999999/purchases",
        json={"date": "2026-01-05", "quantity": "1"},
        headers=auth_headers,
    )
    assert r.status_code == 404


async def test_add_purchase_requires_auth(client: AsyncClient):
    r = await client.post("/api/supplies/1/purchases", json={"date": "2026-01-05", "quantity": "1"})
    assert r.status_code == 401


async def test_delete_purchase(client: AsyncClient, auth_headers):
    """Deleting a purchase removes it from the ledger and restores on_hand."""
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Wiper Blade", "unit_type": "count"},
            headers=auth_headers,
        )
    ).json()["id"]
    purchase = (
        await client.post(
            f"/api/supplies/{sid}/purchases",
            json={"date": "2026-01-05", "quantity": "2"},
            headers=auth_headers,
        )
    ).json()

    dr = await client.delete(
        f"/api/supplies/{sid}/purchases/{purchase['id']}", headers=auth_headers
    )
    assert dr.status_code == 204

    gbody = (await client.get(f"/api/supplies/{sid}", headers=auth_headers)).json()
    assert float(gbody["on_hand"]) == 0.0

    hist = (await client.get(f"/api/supplies/{sid}/history", headers=auth_headers)).json()
    assert hist["entries"] == []


async def test_delete_purchase_not_found(client: AsyncClient, auth_headers):
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Coolant", "unit_type": "volume"},
            headers=auth_headers,
        )
    ).json()["id"]
    r = await client.delete(f"/api/supplies/{sid}/purchases/999999", headers=auth_headers)
    assert r.status_code == 404


# ---- adjustments (Task 7) ---------------------------------------------------


async def test_adjustment_draws_down_on_hand(client, auth_headers):
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Brake Fluid", "unit_type": "volume"},
            headers=auth_headers,
        )
    ).json()["id"]
    await client.post(
        f"/api/supplies/{sid}/purchases",
        json={"date": "2026-01-01", "quantity": "2", "total_cost": "10.00"},
        headers=auth_headers,
    )
    a = await client.post(
        f"/api/supplies/{sid}/adjustments", json={"quantity": "0.5"}, headers=auth_headers
    )
    assert a.status_code == 201
    hist = (await client.get(f"/api/supplies/{sid}/history", headers=auth_headers)).json()
    assert float(hist["on_hand"]) == 1.5
    assert [e["entry_type"] for e in hist["entries"]] == ["purchase", "usage"]


async def test_add_adjustment_response_shape(client: AsyncClient, auth_headers):
    """The adjustment response resolves supply_name and carries a cost snapshot."""
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Air Filter", "unit_type": "count"},
            headers=auth_headers,
        )
    ).json()["id"]
    await client.post(
        f"/api/supplies/{sid}/purchases",
        json={"date": "2026-01-01", "quantity": "4", "total_cost": "40.00"},
        headers=auth_headers,
    )

    a = await client.post(
        f"/api/supplies/{sid}/adjustments", json={"quantity": "1"}, headers=auth_headers
    )
    body = a.json()
    assert body["supply_id"] == sid
    assert body["supply_name"] == "Air Filter"
    assert float(body["quantity"]) == 1.0
    assert float(body["unit_cost_snapshot"]) == 10.0
    assert float(body["cost_snapshot"]) == 10.0
    assert body["service_line_item_id"] is None
    assert body["service_visit_id"] is None


async def test_add_adjustment_supply_not_found(client: AsyncClient, auth_headers):
    r = await client.post(
        "/api/supplies/999999/adjustments", json={"quantity": "1"}, headers=auth_headers
    )
    assert r.status_code == 404


async def test_add_adjustment_requires_auth(client: AsyncClient):
    r = await client.post("/api/supplies/1/adjustments", json={"quantity": "1"})
    assert r.status_code == 401


async def test_delete_adjustment(client: AsyncClient, auth_headers):
    """Deleting a standalone adjustment restores on_hand."""
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Cabin Filter", "unit_type": "count"},
            headers=auth_headers,
        )
    ).json()["id"]
    await client.post(
        f"/api/supplies/{sid}/purchases",
        json={"date": "2026-01-01", "quantity": "5"},
        headers=auth_headers,
    )
    usage = (
        await client.post(
            f"/api/supplies/{sid}/adjustments", json={"quantity": "2"}, headers=auth_headers
        )
    ).json()

    dr = await client.delete(f"/api/supplies/{sid}/adjustments/{usage['id']}", headers=auth_headers)
    assert dr.status_code == 204

    gbody = (await client.get(f"/api/supplies/{sid}", headers=auth_headers)).json()
    assert float(gbody["on_hand"]) == 5.0


async def test_delete_adjustment_not_found(client: AsyncClient, auth_headers):
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Spark Plug", "unit_type": "count"},
            headers=auth_headers,
        )
    ).json()["id"]
    r = await client.delete(f"/api/supplies/{sid}/adjustments/999999", headers=auth_headers)
    assert r.status_code == 404


# ---- history (Task 7) -------------------------------------------------------


async def test_history_empty_supply(client: AsyncClient, auth_headers):
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Fresh Item", "unit_type": "count"},
            headers=auth_headers,
        )
    ).json()["id"]
    hist = (await client.get(f"/api/supplies/{sid}/history", headers=auth_headers)).json()
    assert hist["supply_id"] == sid
    assert float(hist["on_hand"]) == 0.0
    assert hist["avg_unit_cost"] is None
    assert hist["entries"] == []


async def test_history_entry_running_balance_and_cost(client: AsyncClient, auth_headers):
    sid = (
        await client.post(
            "/api/supplies",
            json={"name": "Trans Fluid", "unit_type": "volume"},
            headers=auth_headers,
        )
    ).json()["id"]
    await client.post(
        f"/api/supplies/{sid}/purchases",
        json={"date": "2026-01-01", "quantity": "4", "total_cost": "20.00"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/supplies/{sid}/adjustments", json={"quantity": "1"}, headers=auth_headers
    )

    hist = (await client.get(f"/api/supplies/{sid}/history", headers=auth_headers)).json()
    purchase_entry, usage_entry = hist["entries"]
    assert purchase_entry["entry_type"] == "purchase"
    assert float(purchase_entry["quantity"]) == 4.0
    assert float(purchase_entry["running_balance"]) == 4.0
    assert float(purchase_entry["cost"]) == 20.0
    assert usage_entry["entry_type"] == "usage"
    assert float(usage_entry["quantity"]) == -1.0
    assert float(usage_entry["running_balance"]) == 3.0
    assert float(usage_entry["cost"]) == 5.0


async def test_history_not_found(client: AsyncClient, auth_headers):
    r = await client.get("/api/supplies/999999/history", headers=auth_headers)
    assert r.status_code == 404


async def test_history_requires_auth(client: AsyncClient):
    assert (await client.get("/api/supplies/1/history")).status_code == 401


# ---- purchase receipts (Task 8) ----------------------------------------------


async def _create_supply_and_purchase(
    client: AsyncClient, auth_headers, name: str
) -> tuple[int, int]:
    """Helper: create a supply + one purchase on it, return (supply_id, purchase_id)."""
    sid = (
        await client.post(
            "/api/supplies", json={"name": name, "unit_type": "volume"}, headers=auth_headers
        )
    ).json()["id"]
    pid = (
        await client.post(
            f"/api/supplies/{sid}/purchases",
            json={"date": "2026-01-01", "quantity": "5", "total_cost": "40"},
            headers=auth_headers,
        )
    ).json()["id"]
    return sid, pid


async def test_receipt_upload_and_reflected_in_purchase(client: AsyncClient, auth_headers):
    sid, pid = await _create_supply_and_purchase(client, auth_headers, "Oil")
    files = {"file": ("receipt.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    up = await client.post(
        f"/api/supplies/{sid}/purchases/{pid}/receipt", files=files, headers=auth_headers
    )
    assert up.status_code == 201
    assert up.json()["file_type"] == "application/pdf"

    dl = await client.get(f"/api/supplies/{sid}/purchases/{pid}/receipt", headers=auth_headers)
    assert dl.status_code == 200
    assert dl.content == b"%PDF-1.4 fake"

    hist = (await client.get(f"/api/supplies/{sid}/history", headers=auth_headers)).json()
    entry = next(e for e in hist["entries"] if e["entry_type"] == "purchase" and e["id"] == pid)
    assert entry["receipt"] is not None
    assert entry["receipt"]["id"] == up.json()["id"]


async def test_receipt_upload_requires_auth(client: AsyncClient):
    files = {"file": ("receipt.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    r = await client.post("/api/supplies/1/purchases/1/receipt", files=files)
    assert r.status_code == 401


async def test_receipt_upload_purchase_not_found(client: AsyncClient, auth_headers):
    sid = (
        await client.post(
            "/api/supplies", json={"name": "Grease", "unit_type": "count"}, headers=auth_headers
        )
    ).json()["id"]
    files = {"file": ("receipt.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    r = await client.post(
        f"/api/supplies/{sid}/purchases/999999/receipt", files=files, headers=auth_headers
    )
    assert r.status_code == 404


async def test_receipt_upload_wrong_supply_id_404s(client: AsyncClient, auth_headers):
    """A purchase must belong to the supply_id in the path, not just exist."""
    sid, pid = await _create_supply_and_purchase(client, auth_headers, "Antifreeze")
    other_sid = (
        await client.post(
            "/api/supplies", json={"name": "Other", "unit_type": "count"}, headers=auth_headers
        )
    ).json()["id"]
    files = {"file": ("receipt.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    r = await client.post(
        f"/api/supplies/{other_sid}/purchases/{pid}/receipt", files=files, headers=auth_headers
    )
    assert r.status_code == 404


async def test_receipt_upload_replaces_existing(
    client: AsyncClient, auth_headers, db_session: AsyncSession
):
    """Uploading a second receipt for the same purchase REPLACES the first —
    exactly one supply_purchase attachment row survives (one-per-purchase, R1-H4)."""
    sid, pid = await _create_supply_and_purchase(client, auth_headers, "Coolant")

    files1 = {"file": ("first.pdf", io.BytesIO(b"%PDF-1.4 first"), "application/pdf")}
    up1 = await client.post(
        f"/api/supplies/{sid}/purchases/{pid}/receipt", files=files1, headers=auth_headers
    )
    assert up1.status_code == 201
    first_id = up1.json()["id"]
    first_row = (
        await db_session.execute(select(Attachment).where(Attachment.id == first_id))
    ).scalar_one()
    first_path = Path(first_row.file_path)
    assert first_path.exists()

    files2 = {"file": ("second.pdf", io.BytesIO(b"%PDF-1.4 second"), "application/pdf")}
    up2 = await client.post(
        f"/api/supplies/{sid}/purchases/{pid}/receipt", files=files2, headers=auth_headers
    )
    assert up2.status_code == 201
    second_id = up2.json()["id"]
    # NOTE: second_id can equal first_id — SQLite reuses a freed rowid when the
    # deleted row held the table's current max id, so id-inequality isn't a valid
    # invariant here. The row-count + file-identity assertions below are what
    # actually prove replacement happened.

    # The old file is gone; the new one exists.
    assert not first_path.exists()
    rows = (
        (
            await db_session.execute(
                select(Attachment)
                .where(Attachment.record_type == "supply_purchase")
                .where(Attachment.record_id == pid)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].id == second_id

    dl = await client.get(f"/api/supplies/{sid}/purchases/{pid}/receipt", headers=auth_headers)
    assert dl.content == b"%PDF-1.4 second"


async def test_delete_receipt_removes_row_and_file(
    client: AsyncClient, auth_headers, db_session: AsyncSession
):
    sid, pid = await _create_supply_and_purchase(client, auth_headers, "Wiper Fluid")
    files = {"file": ("receipt.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    up = await client.post(
        f"/api/supplies/{sid}/purchases/{pid}/receipt", files=files, headers=auth_headers
    )
    attachment_id = up.json()["id"]
    row = (
        await db_session.execute(select(Attachment).where(Attachment.id == attachment_id))
    ).scalar_one()
    file_path = Path(row.file_path)
    assert file_path.exists()

    dr = await client.delete(f"/api/supplies/{sid}/purchases/{pid}/receipt", headers=auth_headers)
    assert dr.status_code == 204

    assert not file_path.exists()
    remaining = (
        (
            await db_session.execute(
                select(Attachment)
                .where(Attachment.record_type == "supply_purchase")
                .where(Attachment.record_id == pid)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []

    dl = await client.get(f"/api/supplies/{sid}/purchases/{pid}/receipt", headers=auth_headers)
    assert dl.status_code == 404


async def test_delete_receipt_not_found(client: AsyncClient, auth_headers):
    sid, pid = await _create_supply_and_purchase(client, auth_headers, "Screenwash")
    r = await client.delete(f"/api/supplies/{sid}/purchases/{pid}/receipt", headers=auth_headers)
    assert r.status_code == 404


async def test_delete_purchase_removes_receipt_row_and_file(
    client: AsyncClient, auth_headers, db_session: AsyncSession
):
    """Deleting the purchase (not just the receipt) also removes its receipt row + file."""
    sid, pid = await _create_supply_and_purchase(client, auth_headers, "ATF")
    files = {"file": ("receipt.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    up = await client.post(
        f"/api/supplies/{sid}/purchases/{pid}/receipt", files=files, headers=auth_headers
    )
    attachment_id = up.json()["id"]
    row = (
        await db_session.execute(select(Attachment).where(Attachment.id == attachment_id))
    ).scalar_one()
    file_path = Path(row.file_path)
    assert file_path.exists()

    dr = await client.delete(f"/api/supplies/{sid}/purchases/{pid}", headers=auth_headers)
    assert dr.status_code == 204

    assert not file_path.exists()
    remaining = (
        (
            await db_session.execute(
                select(Attachment)
                .where(Attachment.record_type == "supply_purchase")
                .where(Attachment.record_id == pid)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []
