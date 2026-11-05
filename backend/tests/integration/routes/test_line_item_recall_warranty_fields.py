"""The recall and warranty fields on a line item, and the read shapes around them.

Task 5 only: the API stores the flags and links it's sent and reads them back
with a summary of what they point at. Resolving the recall and checking the
link against the visit's VIN come with recall_links (Task 6).
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recall import Recall

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_LINE = {"description": "Oil change", "category": "Maintenance", "cost": "50.00"}


async def _recall(
    client: AsyncClient, headers: dict[str, str], vin: str, campaign: str = "24V123000"
) -> dict[str, Any]:
    r = await client.post(
        f"/api/vehicles/{vin}/recalls",
        json={
            "vin": vin,
            "nhtsa_campaign_number": campaign,
            "component": "AIR BAGS",
            "summary": "The inflator may rupture.",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _warranty(client: AsyncClient, headers: dict[str, str], vin: str) -> dict[str, Any]:
    r = await client.post(
        f"/api/vehicles/{vin}/warranties",
        json={"warranty_type": "Powertrain", "provider": "Acme Cover", "start_date": "2025-01-01"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _visit(
    client: AsyncClient, headers: dict[str, str], vin: str, items: list[dict[str, Any]]
) -> dict[str, Any]:
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={"date": "2026-03-01", "line_items": items},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _get_visit(
    client: AsyncClient, headers: dict[str, str], vin: str, visit_id: int
) -> dict[str, Any]:
    r = await client.get(f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_post_line_item_carries_the_links_and_matches_a_get(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    vin = str(test_vehicle["vin"])
    recall = await _recall(client, auth_headers, vin)
    warranty = await _warranty(client, auth_headers, vin)
    visit = await _visit(client, auth_headers, vin, [_LINE])

    r = await client.post(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}/line-items",
        json={
            "description": "Replace driver air bag inflator",
            "is_recall": True,
            "recall_id": recall["id"],
            "is_warranty": True,
            "warranty_id": warranty["id"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    posted = r.json()
    assert posted["is_recall"] is True
    assert posted["recall_id"] == recall["id"]
    assert posted["is_warranty"] is True
    assert posted["warranty_id"] == warranty["id"]
    assert posted["recall_summary"] == {
        "id": recall["id"],
        "campaign": "24V123000",
        "component": "AIR BAGS",
    }
    assert posted["warranty_summary"] == {
        "id": warranty["id"],
        "warranty_type": "Powertrain",
        "provider": "Acme Cover",
    }

    got = await _get_visit(client, auth_headers, vin, visit["id"])
    listed = next(i for i in got["line_items"] if i["id"] == posted["id"])
    assert listed == posted


async def test_a_visit_create_stores_the_links_and_lists_them(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    vin = str(test_vehicle["vin"])
    recall = await _recall(client, auth_headers, vin, campaign="24V555000")
    warranty = await _warranty(client, auth_headers, vin)
    visit = await _visit(
        client,
        auth_headers,
        vin,
        [
            {**_LINE, "is_recall": True, "recall_id": recall["id"]},
            {**_LINE, "description": "Tie rod", "is_warranty": True, "warranty_id": warranty["id"]},
            {**_LINE, "description": "Wipers"},
        ],
    )
    by_desc = {i["description"]: i for i in visit["line_items"]}
    assert by_desc["Oil change"]["recall_summary"]["campaign"] == "24V555000"
    assert by_desc["Oil change"]["warranty_summary"] is None
    assert by_desc["Tie rod"]["warranty_summary"]["provider"] == "Acme Cover"
    assert by_desc["Tie rod"]["recall_summary"] is None
    plain = by_desc["Wipers"]
    assert (plain["is_recall"], plain["recall_id"], plain["is_warranty"], plain["warranty_id"]) == (
        False,
        None,
        False,
        None,
    )

    r = await client.get(f"/api/vehicles/{vin}/service-visits", headers=auth_headers)
    assert r.status_code == 200, r.text
    listed = next(v for v in r.json()["visits"] if v["id"] == visit["id"])
    assert listed["line_items"] == visit["line_items"]


async def test_a_flag_without_a_link_is_allowed(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """A recall that isn't in MyGarage still makes recall work (D8)."""
    vin = str(test_vehicle["vin"])
    visit = await _visit(client, auth_headers, vin, [{**_LINE, "is_recall": True}])
    item = visit["line_items"][0]
    assert item["is_recall"] is True
    assert item["recall_id"] is None
    assert item["recall_summary"] is None


async def test_the_campaign_falls_back_to_the_providers_id(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_vehicle: dict[str, object],
    db_session: AsyncSession,
) -> None:
    vin = str(test_vehicle["vin"])
    recall = Recall(
        vin=vin,
        source="rappelconso",
        external_id="RC-2026-0042",
        component="Freinage",
        summary="Les plaquettes peuvent se détacher.",
    )
    db_session.add(recall)
    await db_session.commit()
    visit = await _visit(
        client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": recall.id}]
    )
    assert visit["line_items"][0]["recall_summary"] == {
        "id": recall.id,
        "campaign": "RC-2026-0042",
        "component": "Freinage",
    }


async def test_a_link_without_its_flag_is_a_422(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    vin = str(test_vehicle["vin"])
    recall = await _recall(client, auth_headers, vin, campaign="24V777000")
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={"date": "2026-03-01", "line_items": [{**_LINE, "recall_id": recall["id"]}]},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text


async def test_recall_and_warranty_reads_carry_the_new_fields(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    """Nothing fills them yet (Task 7), but every read carries them."""
    vin = str(test_vehicle["vin"])
    recall = await _recall(client, auth_headers, vin, campaign="24V888000")
    assert recall["resolved_via"] is None
    assert recall["linked_visit"] is None
    r = await client.get(f"/api/vehicles/{vin}/recalls", headers=auth_headers)
    assert r.status_code == 200, r.text
    listed = next(x for x in r.json()["recalls"] if x["id"] == recall["id"])
    assert listed["resolved_via"] is None
    assert listed["linked_visit"] is None

    warranty = await _warranty(client, auth_headers, vin)
    assert warranty["linked_items"] == []
    r = await client.get(f"/api/vehicles/{vin}/warranties", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert next(w for w in r.json() if w["id"] == warranty["id"])["linked_items"] == []
