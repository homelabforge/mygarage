"""A repair's link only targets an inspection on its own visit (S1d-04, D1).

A link to a real item on the same visit that isn't an inspection is dropped,
not refused: the repair saves with no link. Unknown ids, other visits' items
and self-links are still refused (R10); those live in
test_service_visit_line_item_keep.py.
"""

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.service_line_item import ServiceLineItem
from app.models.supply import SupplyUsage

# Not asyncio module-wide: the drop_stray_links test at the bottom is sync.
pytestmark = [pytest.mark.integration]


async def _visit(client: AsyncClient, headers: dict[str, str], vin: str) -> tuple[int, int, int]:
    """A visit with a failed inspection and the repair it set off, linked by temp id."""
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-03-01",
            "line_items": [
                {
                    "temp_id": -1,
                    "description": "Brake inspection",
                    "is_inspection": True,
                    "inspection_result": "failed",
                    "inspection_severity": "red",
                },
                {"description": "Front pads", "triggered_by_inspection_id": -1},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    insp, repair = body["line_items"]
    assert repair["triggered_by_inspection_id"] == insp["id"]
    return body["id"], insp["id"], repair["id"]


async def _items(
    client: AsyncClient, headers: dict[str, str], vin: str, visit_id: int
) -> dict[int, dict[str, Any]]:
    """The visit's line items by id, read back through GET."""
    r = await client.get(f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=headers)
    assert r.status_code == 200, r.text
    return {li["id"]: li for li in r.json()["line_items"]}


@pytest.mark.asyncio
async def test_create_drops_a_link_to_an_item_that_isnt_an_inspection(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    vin = str(test_vehicle["vin"])
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-03-02",
            "line_items": [
                {"temp_id": -1, "description": "Wipers"},
                {"description": "Front pads", "triggered_by_inspection_id": -1},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    # main: the pads point at the wipers
    assert [li["triggered_by_inspection_id"] for li in r.json()["line_items"]] == [None, None]
    items = await _items(client, auth_headers, vin, r.json()["id"])
    assert [li["triggered_by_inspection_id"] for li in items.values()] == [None, None]


@pytest.mark.asyncio
async def test_unticking_an_inspection_drops_its_repairs_link(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """The repair's payload leaves the link out, and it still goes."""
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={
            "line_items": [
                {
                    "id": insp,
                    "description": "Brake inspection",
                    "is_inspection": False,
                    "inspection_result": None,
                    "inspection_severity": None,
                },
                {"id": repair, "description": "Front pads"},
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    items = await _items(client, auth_headers, vin, visit_id)
    assert items[insp]["is_inspection"] is False
    # main: the pads still point at an item that's no longer an inspection
    assert items[repair]["triggered_by_inspection_id"] is None


@pytest.mark.asyncio
async def test_update_drops_a_sent_link_to_a_kept_item_that_isnt_an_inspection(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={
            "line_items": [
                {"id": insp, "description": "Brake inspection"},
                {"id": repair, "description": "Front pads"},
                {"description": "Rotors", "triggered_by_inspection_id": repair},
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    items = await _items(client, auth_headers, vin, visit_id)
    (rotors,) = [li for li in items.values() if li["description"] == "Rotors"]
    # main: the rotors point at the pads
    assert rotors["triggered_by_inspection_id"] is None
    assert items[repair]["triggered_by_inspection_id"] == insp


@pytest.mark.asyncio
async def test_add_line_item_drops_a_link_to_an_item_that_isnt_an_inspection(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)

    r = await client.post(
        f"/api/vehicles/{vin}/service-visits/{visit_id}/line-items",
        json={"description": "Rotors", "triggered_by_inspection_id": repair},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    # main: the rotors point at the pads
    assert r.json()["triggered_by_inspection_id"] is None
    items = await _items(client, auth_headers, vin, visit_id)
    assert items[r.json()["id"]]["triggered_by_inspection_id"] is None
    assert items[repair]["triggered_by_inspection_id"] == insp


@pytest.mark.asyncio
async def test_a_link_to_an_inspection_survives_create_update_and_add(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    # guard: main keeps all three. It kills a drop that's too eager, like one
    # run over a list missing the new items, which would read a temp-id link
    # to a new inspection as a link to nothing (F1-9).
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={
            "line_items": [
                {"id": insp, "description": "Brake inspection"},
                {"id": repair, "description": "Front pads", "triggered_by_inspection_id": -1},
                {
                    "temp_id": -1,
                    "description": "Rotor inspection",
                    "is_inspection": True,
                    "inspection_result": "failed",
                },
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    items = await _items(client, auth_headers, vin, visit_id)
    (rotor_insp,) = [li for li in items.values() if li["description"] == "Rotor inspection"]
    assert items[repair]["triggered_by_inspection_id"] == rotor_insp["id"]

    r = await client.post(
        f"/api/vehicles/{vin}/service-visits/{visit_id}/line-items",
        json={"description": "Rotors", "triggered_by_inspection_id": rotor_insp["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["triggered_by_inspection_id"] == rotor_insp["id"]
    items = await _items(client, auth_headers, vin, visit_id)
    assert items[r.json()["id"]]["triggered_by_inspection_id"] == rotor_insp["id"]
    assert items[repair]["triggered_by_inspection_id"] == rotor_insp["id"]


async def _supply(client: AsyncClient, headers: dict[str, str]) -> int:
    """A supply with ten on hand."""
    r = await client.post(
        "/api/supplies", json={"name": "Brake grease", "unit_type": "volume"}, headers=headers
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = await client.post(
        f"/api/supplies/{sid}/purchases",
        json={"date": "2026-01-01", "quantity": "10", "total_cost": "80.00"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return sid


async def _saved(
    maker: async_sessionmaker[AsyncSession], visit_id: int
) -> dict[str, tuple[int | None, list[Decimal]]]:
    """Each item's link and supply quantities by description, read in a fresh session."""
    async with maker() as read:
        items = (
            (
                await read.execute(
                    select(ServiceLineItem).where(ServiceLineItem.visit_id == visit_id)
                )
            )
            .scalars()
            .all()
        )
        usages = (
            await read.execute(
                select(SupplyUsage.service_line_item_id, SupplyUsage.quantity).where(
                    SupplyUsage.service_line_item_id.in_([i.id for i in items])
                )
            )
        ).all()
    return {
        i.description: (
            i.triggered_by_inspection_id,
            [q for item_id, q in usages if item_id == i.id],
        )
        for i in items
    }


@pytest.mark.asyncio
async def test_create_with_supplies_and_a_dropped_link_keeps_both(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_vehicle: dict[str, object],
    test_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Coverage: the supplies land and the stray link still goes.

    Mutation: leave items with supplies_used out of create's drop_stray_links and this goes red.
    """
    vin = str(test_vehicle["vin"])
    sid = await _supply(client, auth_headers)
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-03-03",
            "line_items": [
                {"temp_id": -1, "description": "Wipers"},
                {
                    "description": "Front pads",
                    "triggered_by_inspection_id": -1,
                    "supplies_used": [{"supply_id": sid, "quantity": "2"}],
                },
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    saved = await _saved(test_sessionmaker, r.json()["id"])
    assert saved["Front pads"] == (None, [Decimal("2")])
    assert saved["Wipers"] == (None, [])


@pytest.mark.asyncio
async def test_update_with_supplies_and_dropped_links_keeps_both(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_vehicle: dict[str, object],
    test_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Coverage: kept and new items both get their supplies, and both lose their stray link.

    Mutation: a populate_existing reload of the visit's items at the top of
    _sync_line_item_supplies brings the pads' old link back, and this goes red.
    """
    vin = str(test_vehicle["vin"])
    sid = await _supply(client, auth_headers)
    visit_id, insp, repair = await _visit(client, auth_headers, vin)

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={
            "line_items": [
                {
                    "id": insp,
                    "description": "Brake inspection",
                    "is_inspection": False,
                    "inspection_result": None,
                    "inspection_severity": None,
                },
                {
                    "id": repair,
                    "description": "Front pads",
                    "supplies_used": [{"supply_id": sid, "quantity": "2"}],
                },
                {
                    "description": "Rotors",
                    "triggered_by_inspection_id": repair,
                    "supplies_used": [{"supply_id": sid, "quantity": "3"}],
                },
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    saved = await _saved(test_sessionmaker, visit_id)
    assert saved["Front pads"] == (None, [Decimal("2")])
    assert saved["Rotors"] == (None, [Decimal("3")])


def _item(item_id: int, *, inspection: bool = False, link: int | None = None) -> ServiceLineItem:
    return ServiceLineItem(
        id=item_id,
        description=f"item {item_id}",
        is_inspection=inspection,
        triggered_by_inspection_id=link,
    )


def test_drop_stray_links_clears_missing_and_self_targets_too() -> None:
    """The API refuses these, so this is the backstop for rows from before the gates."""
    # Imported here so main's missing helper fails this test, not the module.
    from app.services.service_visit_service import drop_stray_links

    insp = _item(1, inspection=True)
    kept = _item(2, link=1)
    missing = _item(3, link=99)
    self_link = _item(4, inspection=True, link=4)
    plain = _item(5, link=2)

    drop_stray_links([insp, kept, missing, self_link, plain])

    assert [i.triggered_by_inspection_id for i in (insp, kept, missing, self_link, plain)] == [
        None,
        1,
        None,
        None,
        None,
    ]
