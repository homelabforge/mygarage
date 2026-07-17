"""Integration tests for service-visit total integration with parts/supplies
(Task 9) and the consume-picker WRITE path (Task 10).

Task 9 wires ``ServiceVisit.calculated_total_cost`` to include supply-usage cost
snapshots and makes every read of that property async-safe (deep eager-load +
``_recompute_visit_total``). Task 9's tests here cover:

(a) a no-supplies visit still returns ``parts_supplies_cost == 0`` and empty
    ``supply_usages`` on every line item (proves the property/response wiring
    is a no-op when there's nothing to add — the existing suite stays green).
(b) manually inserting a ``SupplyUsage`` (with a ``cost_snapshot``) against a
    visit's line item, then reading the visit back via the API, proves the
    deep eager-load chain avoids ``MissingGreenlet`` and that
    ``calculated_total_cost`` correctly folds in the supply cost.

Task 10 adds the actual write path — ``_sync_line_item_supplies`` persists
``supplies_used`` from create/update/add-line-item payloads as ``SupplyUsage``
rows, diffed by ``supply_id`` so untouched associations keep their frozen
``cost_snapshot`` (R1-H1). Those tests cover the diff algorithm end to end:
DIY total math, edit-reduces-quantity, delete-cascades-stock-back,
pinned-to-another-vehicle rejection, duplicate-supply_id rejection, and the
two "must NOT re-snapshot / re-validate" edge cases (a later pricier purchase,
and a supply archived after the fact).
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supply import Supply, SupplyUsage
from app.models.vendor import Vendor

pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.supplies]


async def _supply(
    client: AsyncClient, auth_headers, unit: str = "volume", vin: str | None = None
) -> int:
    """Create a supply (optionally pinned to `vin`) with a purchase establishing
    on_hand=10 @ avg_unit_cost=8.00/unit.

    ``Supply.vin`` is a real FK to ``vehicles.vin`` and SQLite's
    ``foreign_keys=ON`` pragma is mirrored in tests (see `conftest.py`), so
    pinning to a vehicle that doesn't exist yet would raise an IntegrityError
    on insert — idempotently create it first (ignore the result: 201 if new,
    400 if it's already registered, e.g. the shared `test_vehicle` fixture).
    """
    if vin:
        await client.post(
            "/api/vehicles",
            json={"vin": vin, "nickname": "Other Vehicle", "vehicle_type": "Car"},
            headers=auth_headers,
        )
    body: dict[str, str] = {"name": "Oil", "unit_type": unit}
    if vin:
        body["vin"] = vin
    sid = (await client.post("/api/supplies", json=body, headers=auth_headers)).json()["id"]
    await client.post(
        f"/api/supplies/{sid}/purchases",
        json={"date": "2026-01-01", "quantity": "10", "total_cost": "80.00"},
        headers=auth_headers,
    )
    return sid  # avg cost 8.00/unit


async def test_visit_with_no_supplies_has_zero_parts_cost(
    client: AsyncClient, auth_headers, test_vehicle
):
    """A visit with no supply usages returns parts_supplies_cost == 0 and every
    line item's supply_usages == [] — the existing total-cost math is unaffected."""
    vin = test_vehicle["vin"]

    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-02-01",
            "service_category": "Maintenance",
            "tax_amount": "10.00",
            "line_items": [
                {"description": "Tire Rotation", "cost": "50.00"},
                {"description": "Multi-point Inspection", "cost": "0"},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201
    body = r.json()

    assert float(body["parts_supplies_cost"]) == 0.0
    assert float(body["subtotal"]) == 50.0
    assert float(body["calculated_total_cost"]) == 60.0  # subtotal + tax, no supplies
    assert body["line_items"]
    for li in body["line_items"]:
        assert li["supply_usages"] == []

    # GET reads back the same shape (exercises get_service_visit's eager chain)
    gr = await client.get(f"/api/vehicles/{vin}/service-visits/{body['id']}", headers=auth_headers)
    assert gr.status_code == 200
    get_body = gr.json()
    assert float(get_body["parts_supplies_cost"]) == 0.0
    assert float(get_body["calculated_total_cost"]) == 60.0

    # LIST also carries the field without crashing (exercises the deep chain there too)
    lr = await client.get(f"/api/vehicles/{vin}/service-visits", headers=auth_headers)
    assert lr.status_code == 200
    listed = next(v for v in lr.json()["visits"] if v["id"] == body["id"])
    assert float(listed["parts_supplies_cost"]) == 0.0


async def test_get_visit_reads_manually_inserted_supply_usage_async_safely(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    """After inserting a SupplyUsage directly against a line item (bypassing the
    not-yet-built Task 10 persistence path), get_service_visit must read
    calculated_total_cost without MissingGreenlet, and the total must equal
    subtotal + fees + that usage's cost_snapshot."""
    vin = test_vehicle["vin"]

    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-02-01",
            "service_category": "Maintenance",
            "tax_amount": "5.00",
            "misc_fees": "2.50",
            "line_items": [{"description": "DIY Oil Change", "cost": "0"}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201
    visit_body = r.json()
    visit_id = visit_body["id"]
    line_item_id = visit_body["line_items"][0]["id"]

    # Manually insert a Supply + SupplyUsage — same db_session the client uses.
    supply = Supply(name="Oil", unit_type="volume")
    db_session.add(supply)
    await db_session.flush()

    usage = SupplyUsage(
        supply_id=supply.id,
        quantity=Decimal("5"),
        unit_cost_snapshot=Decimal("8.00"),
        cost_snapshot=Decimal("40.00"),
        service_line_item_id=line_item_id,
    )
    db_session.add(usage)
    await db_session.commit()

    # Reading the visit back must not raise MissingGreenlet (deep eager-load chain).
    gr = await client.get(f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=auth_headers)
    assert gr.status_code == 200
    body = gr.json()

    assert float(body["parts_supplies_cost"]) == 40.0
    expected_total = (
        float(body["subtotal"]) + float(body["tax_amount"]) + float(body["misc_fees"]) + 40.0
    )
    assert float(body["calculated_total_cost"]) == expected_total

    li = body["line_items"][0]
    assert len(li["supply_usages"]) == 1
    assert float(li["supply_usages"][0]["cost_snapshot"]) == 40.0
    assert li["supply_usages"][0]["supply_name"] == "Oil"


async def test_update_visit_with_vendor_and_supply_usage_response_stays_intact(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    """update_service_visit returns the mutated `visit` object directly (no
    extra re-fetch) — it relies on the vendor + supply_usages relationships
    still being populated from the earlier get_service_visit call in the same
    request, since the mid-function recompute reload only re-loads
    line_items -> supply_usages (not vendor / usage.supply). This pins that
    a PUT on a visit that has BOTH a vendor and an existing supply usage
    still returns a complete response — vendor name and supply_name present,
    no MissingGreenlet — after that update."""
    vin = test_vehicle["vin"]

    vendor = Vendor(name="QuickLube Test Shop")
    db_session.add(vendor)
    await db_session.flush()

    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-02-01",
            "service_category": "Maintenance",
            "vendor_id": vendor.id,
            "line_items": [{"description": "DIY Oil Change", "cost": "0"}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201
    visit_body = r.json()
    visit_id = visit_body["id"]
    line_item_id = visit_body["line_items"][0]["id"]

    supply = Supply(name="Oil", unit_type="volume")
    db_session.add(supply)
    await db_session.flush()

    usage = SupplyUsage(
        supply_id=supply.id,
        quantity=Decimal("5"),
        unit_cost_snapshot=Decimal("8.00"),
        cost_snapshot=Decimal("40.00"),
        service_line_item_id=line_item_id,
    )
    db_session.add(usage)
    await db_session.commit()

    # PUT a no-op notes update — exercises update_service_visit's mutation
    # path (recompute + `return visit`) without touching the supply usage.
    ur = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={"notes": "reviewed"},
        headers=auth_headers,
    )
    assert ur.status_code == 200
    body = ur.json()

    assert body["vendor"] is not None
    assert body["vendor"]["name"] == "QuickLube Test Shop"
    assert float(body["parts_supplies_cost"]) == 40.0
    li = body["line_items"][0]
    assert len(li["supply_usages"]) == 1
    assert li["supply_usages"][0]["supply_name"] == "Oil"


# ---------------------------------------------------------------------------
# Task 10: consume-picker WRITE path (_sync_line_item_supplies diff-by-supply_id)
# ---------------------------------------------------------------------------


async def test_visit_total_includes_supply_cost(client: AsyncClient, auth_headers, test_vehicle):
    """DIY zero-labor oil change: the visit total is entirely the oil cost,
    and the usage row/snapshot are created by the create-visit write path."""
    vin = test_vehicle["vin"]
    sid = await _supply(client, auth_headers)
    # DIY oil change: zero-labor line item, only cost is the oil (5 units * 8.00 = 40.00)
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-02-01",
            "service_category": "Maintenance",
            "line_items": [
                {
                    "description": "DIY Oil Change",
                    "cost": 0,
                    "supplies_used": [{"supply_id": sid, "quantity": "5"}],
                }
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert float(body["parts_supplies_cost"]) == 40.0
    assert float(body["calculated_total_cost"]) == 40.0
    li = body["line_items"][0]
    assert len(li["supply_usages"]) == 1
    assert float(li["supply_usages"][0]["cost_snapshot"]) == 40.0
    # and the supply drew down
    supply = (await client.get(f"/api/supplies/{sid}", headers=auth_headers)).json()
    assert float(supply["on_hand"]) == 5.0


async def test_edit_replaces_supply_usages(client, auth_headers, test_vehicle):
    """Editing a line item's supplies_used replaces the usage in place (same
    diff row, quantity + cost_snapshot updated) and on_hand reflects the new
    quantity, not a stacked old+new usage."""
    vin = test_vehicle["vin"]
    sid = await _supply(client, auth_headers)
    created = (
        await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={
                "date": "2026-02-01",
                "line_items": [
                    {
                        "description": "Oil Change",
                        "cost": 0,
                        "supplies_used": [{"supply_id": sid, "quantity": "5"}],
                    }
                ],
            },
            headers=auth_headers,
        )
    ).json()
    li_id = created["line_items"][0]["id"]
    # Edit: reduce to 3 units.
    updated = (
        await client.put(
            f"/api/vehicles/{vin}/service-visits/{created['id']}",
            json={
                "line_items": [
                    {
                        "id": li_id,
                        "description": "Oil Change",
                        "cost": 0,
                        "supplies_used": [{"supply_id": sid, "quantity": "3"}],
                    }
                ]
            },
            headers=auth_headers,
        )
    ).json()
    assert float(updated["parts_supplies_cost"]) == 24.0  # 3 * 8.00
    supply = (await client.get(f"/api/supplies/{sid}", headers=auth_headers)).json()
    assert float(supply["on_hand"]) == 7.0  # 10 − 3 (old 5-unit usage was replaced)


async def test_delete_line_item_returns_supply_to_stock(client, auth_headers, test_vehicle):
    """Deleting a line item cascade-deletes its supply usages — no explicit
    supply logic needed in delete_line_item, FK/ORM cascade handles it."""
    vin = test_vehicle["vin"]
    sid = await _supply(client, auth_headers)
    created = (
        await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={
                "date": "2026-02-01",
                "line_items": [
                    {
                        "description": "Oil Change",
                        "cost": 0,
                        "supplies_used": [{"supply_id": sid, "quantity": "5"}],
                    }
                ],
            },
            headers=auth_headers,
        )
    ).json()
    li_id = created["line_items"][0]["id"]
    r = await client.delete(
        f"/api/vehicles/{vin}/service-visits/{created['id']}/line-items/{li_id}",
        headers=auth_headers,
    )
    assert r.status_code == 204
    supply = (await client.get(f"/api/supplies/{sid}", headers=auth_headers)).json()
    assert float(supply["on_hand"]) == 10.0  # cascade-deleted usage restored stock


async def test_pinned_supply_rejected_on_other_vehicle(client, auth_headers, test_vehicle):
    """A supply pinned to a different vehicle is rejected (400) when consumed
    as a NEW association on this vehicle's visit."""
    vin = test_vehicle["vin"]
    other = "WAUZZZ8K9AA000099"
    sid = await _supply(client, auth_headers, vin=other)  # pinned elsewhere
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-02-01",
            "line_items": [
                {
                    "description": "x",
                    "cost": 0,
                    "supplies_used": [{"supply_id": sid, "quantity": "1"}],
                }
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 400


async def test_duplicate_supply_id_rejected_in_one_line_item(client, auth_headers, test_vehicle):
    """Two supplies_used entries with the same supply_id on one line item are
    ambiguous (which quantity wins?) — rejected with 400."""
    vin = test_vehicle["vin"]
    sid = await _supply(client, auth_headers)
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-02-01",
            "line_items": [
                {
                    "description": "Oil Change",
                    "cost": 0,
                    "supplies_used": [
                        {"supply_id": sid, "quantity": "2"},
                        {"supply_id": sid, "quantity": "3"},
                    ],
                }
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 400


async def test_unrelated_edit_preserves_frozen_snapshot(client, auth_headers, test_vehicle):
    """R1-H1: a later higher-cost purchase + an unrelated edit must NOT re-snapshot."""
    vin = test_vehicle["vin"]
    sid = await _supply(client, auth_headers)  # avg 8.00/unit
    created = (
        await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={
                "date": "2026-02-01",
                "line_items": [
                    {
                        "description": "Oil Change",
                        "cost": 0,
                        "supplies_used": [{"supply_id": sid, "quantity": "5"}],
                    }
                ],
            },
            headers=auth_headers,
        )
    ).json()
    li = created["line_items"][0]
    usage_id = li["supply_usages"][0]["id"]
    assert float(li["supply_usages"][0]["cost_snapshot"]) == 40.0  # 5 * 8.00
    # A later, pricier purchase raises the average cost.
    await client.post(
        f"/api/supplies/{sid}/purchases",
        json={"date": "2026-03-01", "quantity": "10", "total_cost": "200.00"},
        headers=auth_headers,
    )
    # Edit ONLY the description, resubmitting the same supplies_used.
    updated = (
        await client.put(
            f"/api/vehicles/{vin}/service-visits/{created['id']}",
            json={
                "line_items": [
                    {
                        "id": li["id"],
                        "description": "Oil Change (annual)",
                        "cost": 0,
                        "supplies_used": [{"supply_id": sid, "quantity": "5"}],
                    }
                ]
            },
            headers=auth_headers,
        )
    ).json()
    u = updated["line_items"][0]["supply_usages"][0]
    assert u["id"] == usage_id  # same row, not recreated
    assert float(u["cost_snapshot"]) == 40.0  # snapshot frozen despite avg now higher
    assert float(updated["parts_supplies_cost"]) == 40.0


async def test_edit_succeeds_after_supply_archived(client, auth_headers, test_vehicle):
    """R1-H1: editing an unrelated field on a historical visit must not fail
    because a consumed supply was later archived."""
    vin = test_vehicle["vin"]
    sid = await _supply(client, auth_headers)
    created = (
        await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={
                "date": "2026-02-01",
                "line_items": [
                    {
                        "description": "Oil Change",
                        "cost": 0,
                        "supplies_used": [{"supply_id": sid, "quantity": "5"}],
                    }
                ],
            },
            headers=auth_headers,
        )
    ).json()
    li = created["line_items"][0]
    # Archive the supply (it now has usage history → soft-archived).
    await client.delete(f"/api/supplies/{sid}", headers=auth_headers)
    # Edit only the description; resubmit the same (now-archived) supply unchanged.
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{created['id']}",
        json={
            "line_items": [
                {
                    "id": li["id"],
                    "description": "Oil Change (rev)",
                    "cost": 0,
                    "supplies_used": [{"supply_id": sid, "quantity": "5"}],
                }
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200  # unchanged association is not re-validated


async def test_add_line_item_route_serializes_supply_usages(
    client: AsyncClient, auth_headers, test_vehicle
):
    """The nested add-line-item route must return the persisted supply_usages,
    not a silent empty list (review R10 — the route built the response manually
    and omitted the mapping)."""
    vin = test_vehicle["vin"]
    sid = await _supply(client, auth_headers)  # avg 8.00/unit
    created = (
        await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={"date": "2026-02-01", "line_items": [{"description": "Base", "cost": 0}]},
            headers=auth_headers,
        )
    ).json()
    visit_id = created["id"]

    r = await client.post(
        f"/api/vehicles/{vin}/service-visits/{visit_id}/line-items",
        json={
            "description": "Oil Change",
            "cost": 0,
            "supplies_used": [{"supply_id": sid, "quantity": "5"}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert len(body["supply_usages"]) == 1
    u = body["supply_usages"][0]
    assert u["supply_id"] == sid
    assert float(u["cost_snapshot"]) == 40.0  # 5 * 8.00
    assert u["service_visit_id"] == visit_id
    assert u["service_visit_date"] == "2026-02-01"
