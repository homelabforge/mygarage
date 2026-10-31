"""A repair's link only targets an inspection on its own visit (S1d-04, D1).

A link to a real item on the same visit that isn't an inspection is dropped,
not refused: the repair saves with no link. Unknown ids, other visits' items
and self-links are still refused (R10); those live in
test_service_visit_line_item_keep.py.
"""

from typing import Any

import pytest
from httpx import AsyncClient

from app.models.service_line_item import ServiceLineItem

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


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


def _item(item_id: int, *, inspection: bool = False, link: int | None = None) -> ServiceLineItem:
    return ServiceLineItem(
        id=item_id,
        description=f"item {item_id}",
        is_inspection=inspection,
        triggered_by_inspection_id=link,
    )


async def test_drop_stray_links_clears_missing_and_self_targets_too() -> None:
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
