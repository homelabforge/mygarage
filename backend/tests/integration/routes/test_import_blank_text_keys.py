"""A blank text field the app stored as '' still matches its own backup (P-1).

The forms send '' for an empty optional text box and the services store it.
The importers read a blank cell as None, so an exact-NULL key part never met
the stored '' and a re-import wrote the row again. Every record here is made
through its real create route, then exported and imported back.
"""

import json
from io import BytesIO
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _vehicle(db_session: AsyncSession, owner_id: Any, vin: str) -> str:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname=vin,
            # An RV, so the spot rental routes take it.
            vehicle_type="RV",
            year=2024,
            make="Test",
            model="Blank",
        )
    )
    await db_session.commit()
    return vin


async def _create(client: AsyncClient, headers: dict, path: str, body: dict) -> None:
    r = await client.post(path, headers=headers, json=body)
    assert r.status_code == 201, r.text


async def _reimport_json(client: AsyncClient, headers: dict, vin: str) -> dict:
    exported = await client.get(f"/api/export/vehicles/{vin}/json", headers=headers)
    assert exported.status_code == 200, exported.text
    r = await client.post(
        f"/api/import/vehicles/{vin}/json",
        headers=headers,
        files={"file": ("vehicle.json", json.dumps(exported.json()).encode(), "application/json")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _reimport_csv(client: AsyncClient, headers: dict, vin: str, pair: str) -> dict:
    exported = await client.get(f"/api/export/vehicles/{vin}/{pair}/csv", headers=headers)
    assert exported.status_code == 200, exported.text
    r = await client.post(
        f"/api/import/vehicles/{vin}/{pair}/csv",
        headers=headers,
        files={"file": (f"{pair}.csv", BytesIO(exported.content), "text/csv")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_a_warranty_with_blank_provider_and_policy_number_matches_its_backups(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTBLANKWARRANT1")
    await _create(
        client,
        auth_headers,
        f"/api/vehicles/{vin}/warranties",
        {
            "warranty_type": "Extended",
            "provider": "",
            "policy_number": "",
            "start_date": "2026-01-01",
        },
    )
    data = await _reimport_json(client, auth_headers, vin)
    # 4844e2f7: (1, 0), the stored '' never met the file's NULL
    assert (data["warranties"]["success_count"], data["warranties"]["skipped_count"]) == (
        0,
        1,
    ), data
    csv_data = await _reimport_csv(client, auth_headers, vin, "warranties")
    assert (csv_data["success_count"], csv_data["skipped_count"]) == (0, 1), csv_data


async def test_a_rental_with_a_blank_location_name_matches_its_backup(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTBLANKRENTAL01")
    await _create(
        client,
        auth_headers,
        f"/api/vehicles/{vin}/spot-rentals",
        {"location_name": "", "check_in_date": "2026-02-01"},
    )
    data = await _reimport_json(client, auth_headers, vin)
    # 4844e2f7: (1, 0)
    assert (data["spot_rentals"]["success_count"], data["spot_rentals"]["skipped_count"]) == (
        0,
        1,
    ), data


async def test_a_visit_with_a_blank_claim_number_matches_its_backups(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTBLANKCLAIM001")
    await _create(
        client,
        auth_headers,
        f"/api/vehicles/{vin}/service-visits",
        {
            "date": "2026-03-01",
            "odometer_km": 1000,
            "insurance_claim_number": "",
            "line_items": [{"description": "Oil", "cost": 40}],
        },
    )
    data = await _reimport_json(client, auth_headers, vin)
    # 4844e2f7: (1, 0)
    assert (
        data["service_records"]["success_count"],
        data["service_records"]["skipped_count"],
    ) == (0, 1), data
    csv_data = await _reimport_csv(client, auth_headers, vin, "service")
    assert (csv_data["success_count"], csv_data["skipped_count"]) == (0, 1), csv_data


async def test_a_note_with_a_blank_title_matches_its_backups(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTBLANKNOTE0001")
    await _create(
        client,
        auth_headers,
        f"/api/vehicles/{vin}/notes",
        {"vin": vin, "date": "2026-04-01", "title": "", "content": "Washed"},
    )
    data = await _reimport_json(client, auth_headers, vin)
    # 4844e2f7: (1, 0)
    assert (data["notes"]["success_count"], data["notes"]["skipped_count"]) == (0, 1), data
    csv_data = await _reimport_csv(client, auth_headers, vin, "notes")
    assert (csv_data["success_count"], csv_data["skipped_count"]) == (0, 1), csv_data
