"""A visit update keeps the line-item fields it leaves out (Ruling 11).

On an existing line item, omitted keeps the stored value and null clears it.
Links between items stay inside the visit, and a new visit keeps the repair
links it made through temp ids.
"""

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _visit(client: AsyncClient, headers: dict[str, str], vin: str) -> tuple[int, int, int]:
    """A visit with an inspection (needs attention) and the repair it triggered."""
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-03-01",
            "line_items": [
                {
                    "temp_id": -1,
                    "description": "Brake inspection",
                    "category": "Inspection",
                    "cost": "45.50",
                    "notes": "Front pads 4 mm",
                    "is_inspection": True,
                    "inspection_result": "needs_attention",
                    "inspection_severity": "yellow",
                },
                {
                    "description": "Front pads",
                    "category": "Maintenance",
                    "cost": "180.00",
                    "notes": "OEM pads",
                    "triggered_by_inspection_id": -1,
                },
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
    assert r.status_code == 200
    return {li["id"]: li for li in r.json()["line_items"]}


def _cost(item: dict[str, Any]) -> Decimal | None:
    """A line item's cost as a Decimal (the API sends money as a string)."""
    return None if item["cost"] is None else Decimal(str(item["cost"]))


async def test_omitted_fields_keep_their_values(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """An item sent with only its id and description keeps everything else."""
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={
            "line_items": [
                {"id": insp, "description": "Brake inspection"},
                {"id": repair, "description": "Front pads"},
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    items = await _items(client, auth_headers, vin, visit_id)
    i, p = items[insp], items[repair]
    assert i["category"] == "Inspection"
    assert _cost(i) == Decimal("45.50")
    assert i["notes"] == "Front pads 4 mm"
    assert i["is_inspection"] is True
    assert i["inspection_result"] == "needs_attention"
    assert i["inspection_severity"] == "yellow"
    assert p["category"] == "Maintenance"
    assert _cost(p) == Decimal("180.00")
    assert p["notes"] == "OEM pads"
    assert p["triggered_by_inspection_id"] == insp


async def test_explicit_nulls_clear(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """null clears a field, and is_inspection takes false."""
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)
    cleared: dict[str, Any] = {
        "category": None,
        "cost": None,
        "notes": None,
        "is_inspection": False,
        "inspection_result": None,
        "inspection_severity": None,
        "triggered_by_inspection_id": None,
    }

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={
            "line_items": [
                {"id": insp, "description": "Brake inspection", **cleared},
                {"id": repair, "description": "Front pads", **cleared},
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    items = await _items(client, auth_headers, vin, visit_id)
    for item in (items[insp], items[repair]):
        assert item["category"] is None
        assert item["cost"] is None
        assert item["notes"] is None
        assert item["is_inspection"] is False
        assert item["inspection_result"] is None
        assert item["inspection_severity"] is None
        assert item["triggered_by_inspection_id"] is None


async def test_sent_values_overwrite(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """A sent value replaces the stored one."""
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)
    new_values: dict[str, Any] = {"category": "Detailing", "cost": "10.00", "notes": "x"}

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={
            "line_items": [
                {
                    "id": insp,
                    "description": "Brake inspection",
                    **new_values,
                    "inspection_result": "passed",
                    "inspection_severity": "green",
                },
                {"id": repair, "description": "Front pads", **new_values},
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    items = await _items(client, auth_headers, vin, visit_id)
    for item in (items[insp], items[repair]):
        assert item["category"] == "Detailing"
        assert _cost(item) == Decimal("10.00")
        assert item["notes"] == "x"
    assert items[insp]["inspection_result"] == "passed"
    assert items[insp]["inspection_severity"] == "green"


async def test_null_is_inspection_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """is_inspection takes false, not null: a 422 and nothing changes."""
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={
            "line_items": [
                {"id": insp, "description": "Brake inspection", "is_inspection": None},
                {"id": repair, "description": "Front pads"},
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 422

    items = await _items(client, auth_headers, vin, visit_id)
    assert items[insp]["is_inspection"] is True
    assert items[insp]["inspection_result"] == "needs_attention"
    assert items[repair]["triggered_by_inspection_id"] == insp


async def test_dropping_the_inspection_clears_its_repairs_link(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """A kept repair whose inspection is dropped can't keep a dangling link."""
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={"line_items": [{"id": repair, "description": "Front pads"}]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    items = await _items(client, auth_headers, vin, visit_id)
    assert insp not in items
    assert items[repair]["triggered_by_inspection_id"] is None


async def test_dropping_the_inspection_clears_a_link_sent_unchanged(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """The form keeps sending the repair's link after the inspection is removed.

    The link names an item this PUT drops: that's allowed, and it ends up null.
    """
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={
            "line_items": [
                {
                    "id": repair,
                    "description": "Front pads",
                    "category": "Maintenance",
                    "maintenance_type": None,
                    "cost": "180.00",
                    "notes": "OEM pads",
                    "is_inspection": False,
                    "inspection_result": None,
                    "inspection_severity": None,
                    "triggered_by_inspection_id": insp,
                    "supplies_used": [],
                }
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    items = await _items(client, auth_headers, vin, visit_id)
    assert insp not in items
    assert items[repair]["triggered_by_inspection_id"] is None


async def test_create_ignores_a_positive_link(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """Every item on a create is new, so only a temp id can link."""
    vin = str(test_vehicle["vin"])
    other = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-03-02",
            "line_items": [
                {
                    "description": "Other inspection",
                    "is_inspection": True,
                    "inspection_result": "failed",
                }
            ],
        },
        headers=auth_headers,
    )
    assert other.status_code == 201, other.text
    other_insp = other.json()["line_items"][0]["id"]

    for ref in (999999, other_insp):
        r = await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={
                "date": "2026-03-03",
                "line_items": [{"description": "Wipers", "triggered_by_inspection_id": ref}],
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["line_items"][0]["triggered_by_inspection_id"] is None
        items = await _items(client, auth_headers, vin, body["id"])
        assert [li["triggered_by_inspection_id"] for li in items.values()] == [None]


async def test_update_refuses_a_link_to_another_visits_item(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """A new item can't link to an item on another visit; its own visit's is fine."""
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)
    _other_visit, other_insp, _other_repair = await _visit(client, auth_headers, vin)

    def payload(ref: int) -> dict[str, Any]:
        return {
            "line_items": [
                {"id": insp, "description": "Brake inspection"},
                {"id": repair, "description": "Front pads"},
                {"description": "Rotors", "triggered_by_inspection_id": ref},
            ]
        }

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json=payload(other_insp),
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == f"Line item {other_insp} does not belong to this service visit"
    assert set(await _items(client, auth_headers, vin, visit_id)) == {insp, repair}

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json=payload(insp),
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    items = await _items(client, auth_headers, vin, visit_id)
    (rotors,) = [li for li in items.values() if li["description"] == "Rotors"]
    assert rotors["triggered_by_inspection_id"] == insp


async def test_update_refuses_to_link_an_existing_item_to_another_visit(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """An existing item's link is checked the same way, before anything is written."""
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)
    _other_visit, other_insp, _other_repair = await _visit(client, auth_headers, vin)

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={
            "notes": "Should not stick",
            "line_items": [
                {"id": insp, "description": "Brake inspection", "notes": "Should not stick"},
                {
                    "id": repair,
                    "description": "Front pads",
                    "triggered_by_inspection_id": other_insp,
                },
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == f"Line item {other_insp} does not belong to this service visit"

    visit = await client.get(f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=auth_headers)
    assert visit.json()["notes"] is None
    items = await _items(client, auth_headers, vin, visit_id)
    assert items[insp]["notes"] == "Front pads 4 mm"
    assert items[repair]["triggered_by_inspection_id"] == insp


async def test_update_links_new_items_by_temp_id(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """A temp id isn't a foreign item: new items added on edit can still link."""
    vin = str(test_vehicle["vin"])
    visit_id, insp, repair = await _visit(client, auth_headers, vin)

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={
            "line_items": [
                {"id": insp, "description": "Brake inspection"},
                {"id": repair, "description": "Front pads"},
                {
                    "temp_id": -1,
                    "description": "Tire inspection",
                    "is_inspection": True,
                    "inspection_result": "failed",
                },
                {"description": "Tires", "triggered_by_inspection_id": -1},
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    items = await _items(client, auth_headers, vin, visit_id)
    by_name = {li["description"]: li for li in items.values()}
    assert by_name["Tires"]["triggered_by_inspection_id"] == by_name["Tire inspection"]["id"]


async def test_a_new_visit_keeps_its_temp_id_link(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """A repair linked to its inspection by temp id stays linked once saved."""
    vin = str(test_vehicle["vin"])
    # _visit checks the link on the POST response itself.
    visit_id, insp, repair = await _visit(client, auth_headers, vin)

    items = await _items(client, auth_headers, vin, visit_id)
    assert items[repair]["triggered_by_inspection_id"] == insp


async def test_service_category_follows_effective_categories(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """The visit's category comes from the items' categories as stored after the PUT."""
    vin = str(test_vehicle["vin"])
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-03-04",
            "line_items": [
                {"description": "Bumper repair", "category": "Collision"},
                {"description": "Oil change", "category": "Maintenance"},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["service_category"] == "Collision"
    first, second = (li["id"] for li in body["line_items"])

    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{body['id']}",
        json={
            "line_items": [
                {"id": first, "description": "Bumper repair"},
                {"id": second, "description": "Oil change", "category": "Detailing"},
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["service_category"] == "Collision"

    # Cleared on both, so a new item's category is the first one left.
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{body['id']}",
        json={
            "line_items": [
                {"id": first, "description": "Bumper repair", "category": None},
                {"id": second, "description": "Oil change", "category": None},
                {"description": "Wax", "category": "Detailing"},
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["service_category"] == "Detailing"
