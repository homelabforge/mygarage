"""Invoice, PO and work order numbers on a service visit (migration 157).

Omitted on a PUT keeps the stored value, null clears it, and blank or
whitespace-only is stored as null, insurance claim # included.
"""

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_REFS = ("invoice_number", "po_number", "work_order_number")
_LINE = [{"description": "Oil change", "category": "Maintenance", "cost": "50.00"}]


async def _create(
    client: AsyncClient, headers: dict[str, str], vin: str, **fields: Any
) -> dict[str, Any]:
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={"date": "2026-03-01", "line_items": _LINE, **fields},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _get(client: AsyncClient, headers: dict[str, str], vin: str, visit_id: int) -> Any:
    r = await client.get(f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _put(
    client: AsyncClient, headers: dict[str, str], vin: str, visit_id: int, body: dict[str, Any]
) -> Any:
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}", json=body, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


_ALL = {"invoice_number": "INV-1001", "po_number": "PO-77", "work_order_number": "WO-5"}


async def test_create_with_all_three_reads_back(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    vin = str(test_vehicle["vin"])
    created = await _create(client, auth_headers, vin, **_ALL)
    for key, value in _ALL.items():
        assert created[key] == value
    got = await _get(client, auth_headers, vin, created["id"])
    for key, value in _ALL.items():
        assert got[key] == value
    # And the list endpoint carries them too.
    r = await client.get(f"/api/vehicles/{vin}/service-visits", headers=auth_headers)
    assert r.status_code == 200, r.text
    listed = next(v for v in r.json()["visits"] if v["id"] == created["id"])
    for key, value in _ALL.items():
        assert listed[key] == value


async def test_put_changing_one_leaves_the_others(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    vin = str(test_vehicle["vin"])
    visit_id = (await _create(client, auth_headers, vin, **_ALL))["id"]
    await _put(client, auth_headers, vin, visit_id, {"po_number": "PO-78"})
    got = await _get(client, auth_headers, vin, visit_id)
    assert got["po_number"] == "PO-78"
    assert got["invoice_number"] == "INV-1001"
    assert got["work_order_number"] == "WO-5"


async def test_put_omitting_them_keeps_them(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    vin = str(test_vehicle["vin"])
    visit_id = (await _create(client, auth_headers, vin, **_ALL))["id"]
    await _put(client, auth_headers, vin, visit_id, {"notes": "Topped up coolant"})
    got = await _get(client, auth_headers, vin, visit_id)
    assert got["notes"] == "Topped up coolant"
    for key, value in _ALL.items():
        assert got[key] == value


async def test_put_null_clears_one(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    vin = str(test_vehicle["vin"])
    visit_id = (await _create(client, auth_headers, vin, **_ALL))["id"]
    await _put(client, auth_headers, vin, visit_id, {"work_order_number": None})
    got = await _get(client, auth_headers, vin, visit_id)
    assert got["work_order_number"] is None
    assert got["invoice_number"] == "INV-1001"
    assert got["po_number"] == "PO-77"


@pytest.mark.parametrize("field", (*_REFS, "insurance_claim_number"))
async def test_51_chars_is_a_422(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_vehicle: dict[str, object],
    field: str,
) -> None:
    vin = str(test_vehicle["vin"])
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={"date": "2026-03-01", "line_items": _LINE, field: "X" * 51},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text
    visit_id = (await _create(client, auth_headers, vin, **{field: "X" * 50}))["id"]
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}",
        json={field: "Y" * 51},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text
    assert (await _get(client, auth_headers, vin, visit_id))[field] == "X" * 50


@pytest.mark.parametrize("field", (*_REFS, "insurance_claim_number"))
async def test_blank_or_whitespace_is_stored_as_null(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_vehicle: dict[str, object],
    field: str,
) -> None:
    vin = str(test_vehicle["vin"])
    created = await _create(client, auth_headers, vin, **{field: "   "})
    assert created[field] is None
    await _put(client, auth_headers, vin, created["id"], {field: "REF-9"})
    await _put(client, auth_headers, vin, created["id"], {field: ""})
    assert (await _get(client, auth_headers, vin, created["id"]))[field] is None


async def test_surrounding_whitespace_is_trimmed(
    client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, object]
) -> None:
    vin = str(test_vehicle["vin"])
    created = await _create(client, auth_headers, vin, invoice_number="  INV-1  ")
    assert created["invoice_number"] == "INV-1"
