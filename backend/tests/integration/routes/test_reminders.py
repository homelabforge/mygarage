"""
Integration tests for vehicle reminder routes — hours-based reminders
(Phase 5 of the hours-usage-model feature).

Adds `due_hours` threading through create/update/response and the new
`'hours'` reminder type, plus the redefined `'smart'` type (date + exactly
one of {due_mileage_km, due_hours}). The critical assertion is backward
compatibility: an existing-style smart reminder (due_date + due_mileage_km,
due_hours null) must still create/update/persist exactly as before.
"""

from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestReminderRoutesBackwardCompat:
    """Existing date/mileage/both/smart reminder shapes are unaffected."""

    async def test_create_date_reminder_unaffected(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Registration renewal",
                "reminder_type": "date",
                "due_date": (date.today() + timedelta(days=30)).isoformat(),
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["reminder_type"] == "date"
        assert data["due_hours"] is None

    async def test_create_mileage_reminder_unaffected(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Tire rotation",
                "reminder_type": "mileage",
                "due_mileage_km": 60000,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["reminder_type"] == "mileage"
        assert float(data["due_mileage_km"]) == 60000
        assert data["due_hours"] is None

    async def test_create_both_reminder_unaffected(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Annual service",
                "reminder_type": "both",
                "due_date": (date.today() + timedelta(days=365)).isoformat(),
                "due_mileage_km": 70000,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["reminder_type"] == "both"
        assert data["due_hours"] is None

    async def test_create_smart_date_and_mileage_only_unaffected(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """CRITICAL backward-compat case at the HTTP boundary: today's
        existing smart-reminder shape (date + mileage, no hours) must still
        create successfully under the redefined 'smart' validation."""
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Oil change",
                "reminder_type": "smart",
                "due_date": (date.today() + timedelta(days=365)).isoformat(),
                "due_mileage_km": 65000,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["reminder_type"] == "smart"
        assert float(data["due_mileage_km"]) == 65000
        assert data["due_hours"] is None

    async def test_update_smart_date_and_mileage_only_unaffected(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        create_resp = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Oil change",
                "reminder_type": "smart",
                "due_date": (date.today() + timedelta(days=365)).isoformat(),
                "due_mileage_km": 65000,
            },
            headers=auth_headers,
        )
        reminder_id = create_resp.json()["id"]

        update_resp = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/reminders/{reminder_id}",
            json={"due_mileage_km": 68000},
            headers=auth_headers,
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert float(data["due_mileage_km"]) == 68000
        assert data["due_hours"] is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestReminderRoutesHours:
    """New 'hours' type + smart+hours, threaded through create/update/response."""

    async def test_create_hours_reminder(self, client: AsyncClient, auth_headers, test_vehicle):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Hydraulic fluid change",
                "reminder_type": "hours",
                "due_hours": 500.0,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["reminder_type"] == "hours"
        assert float(data["due_hours"]) == 500.0
        assert data["due_mileage_km"] is None

    async def test_create_hours_reminder_missing_due_hours_rejected(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={"title": "Hydraulic fluid change", "reminder_type": "hours"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_update_hours_reminder_persists(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        create_resp = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Hydraulic fluid change",
                "reminder_type": "hours",
                "due_hours": 500.0,
            },
            headers=auth_headers,
        )
        reminder_id = create_resp.json()["id"]

        update_resp = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/reminders/{reminder_id}",
            json={"due_hours": 550.0},
            headers=auth_headers,
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert float(data["due_hours"]) == 550.0

    async def test_create_smart_date_and_hours_only(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Engine service",
                "reminder_type": "smart",
                "due_date": (date.today() + timedelta(days=180)).isoformat(),
                "due_hours": 750.0,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["reminder_type"] == "smart"
        assert float(data["due_hours"]) == 750.0
        assert data["due_mileage_km"] is None

    async def test_create_smart_rejects_date_plus_both_metrics(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Engine service",
                "reminder_type": "smart",
                "due_date": (date.today() + timedelta(days=180)).isoformat(),
                "due_mileage_km": 65000,
                "due_hours": 750.0,
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_create_smart_rejects_date_plus_neither_metric(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Engine service",
                "reminder_type": "smart",
                "due_date": (date.today() + timedelta(days=180)).isoformat(),
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_list_reminders_includes_due_hours_field(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Hydraulic fluid change",
                "reminder_type": "hours",
                "due_hours": 500.0,
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reminders?status=all",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert any(r["reminder_type"] == "hours" for r in data)


@pytest.mark.integration
@pytest.mark.asyncio
class TestReminderResponseShape:
    """Fields the reminder response no longer carries."""

    async def test_responses_carry_no_duplicate_of(
        self, client: AsyncClient, auth_headers: dict[str, str], test_vehicle: dict[str, Any]
    ) -> None:
        """G5a-11: duplicates come from GET /duplicates; the row field is gone."""
        vin: str = test_vehicle["vin"]
        created: list[dict[str, Any]] = []
        for _ in range(2):
            response = await client.post(
                f"/api/vehicles/{vin}/reminders",
                json={
                    "title": "Oil & Filter Change",
                    "reminder_type": "date",
                    "due_date": (date.today() + timedelta(days=30)).isoformat(),
                },
                headers=auth_headers,
            )
            assert response.status_code == 201
            created.append(response.json())
        assert all("duplicate_of" not in r for r in created)

        ids = {r["id"] for r in created}
        response = await client.get(f"/api/vehicles/{vin}/reminders", headers=auth_headers)
        rows: list[dict[str, Any]] = response.json()
        listed = [r for r in rows if r["id"] in ids]
        assert len(listed) == 2
        assert all("duplicate_of" not in r for r in listed)


_STORED_FIELDS = ("title", "reminder_type", "due_date", "due_mileage_km", "due_hours")


async def _stored(
    client: AsyncClient, auth_headers: dict[str, str], vin: str, reminder_id: int
) -> dict[str, Any]:
    """The reminder's due fields as the list endpoint reads them back."""
    response = await client.get(f"/api/vehicles/{vin}/reminders?status=all", headers=auth_headers)
    assert response.status_code == 200
    (row,) = [r for r in response.json() if r["id"] == reminder_id]
    return {field: row[field] for field in _STORED_FIELDS}


@pytest.mark.integration
@pytest.mark.asyncio
class TestReminderUpdateRejections:
    """G2c-91: PUT checks the merged state, so a patch that leaves a smart
    reminder with both usage targets, neither, or no date is a 422 and the
    row stays as it was.

    Control tests: each passes on main by design, since the update path
    already refuses these. Proved by mutation: drop the
    ``validate_reminder_state`` call from ``update_reminder`` and every one
    fails.
    """

    async def _create(
        self, client: AsyncClient, auth_headers: dict[str, str], vin: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        response = await client.post(
            f"/api/vehicles/{vin}/reminders", json=body, headers=auth_headers
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def _smart(
        self, client: AsyncClient, auth_headers: dict[str, str], vin: str
    ) -> dict[str, Any]:
        return await self._create(
            client,
            auth_headers,
            vin,
            {
                "title": "Oil change",
                "reminder_type": "smart",
                "due_date": (date.today() + timedelta(days=180)).isoformat(),
                "due_mileage_km": 65000,
            },
        )

    async def _assert_rejected(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        vin: str,
        reminder_id: int,
        patch: dict[str, Any],
    ) -> None:
        before = await _stored(client, auth_headers, vin, reminder_id)

        response = await client.put(
            f"/api/vehicles/{vin}/reminders/{reminder_id}", json=patch, headers=auth_headers
        )

        assert response.status_code == 422, response.text
        assert await _stored(client, auth_headers, vin, reminder_id) == before

    async def test_adding_hours_to_a_smart_mileage_reminder_is_rejected(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_vehicle: dict[str, object],
    ) -> None:
        """Control (passes on main by design): smart with both metrics."""
        vin = str(test_vehicle["vin"])
        reminder = await self._smart(client, auth_headers, vin)

        await self._assert_rejected(
            client, auth_headers, vin, int(reminder["id"]), {"due_hours": 500.0}
        )

    async def test_clearing_mileage_on_a_smart_reminder_is_rejected(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_vehicle: dict[str, object],
    ) -> None:
        """Control (passes on main by design): smart with neither metric."""
        vin = str(test_vehicle["vin"])
        reminder = await self._smart(client, auth_headers, vin)

        await self._assert_rejected(
            client, auth_headers, vin, int(reminder["id"]), {"due_mileage_km": None}
        )

    async def test_clearing_the_date_on_a_smart_reminder_is_rejected(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_vehicle: dict[str, object],
    ) -> None:
        """Control (passes on main by design): smart needs its date."""
        vin = str(test_vehicle["vin"])
        reminder = await self._smart(client, auth_headers, vin)

        await self._assert_rejected(
            client, auth_headers, vin, int(reminder["id"]), {"due_date": None}
        )

    async def test_retyping_a_date_reminder_to_smart_without_a_usage_target_is_rejected(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_vehicle: dict[str, object],
    ) -> None:
        """Control (passes on main by design): a date reminder turned smart
        with no mileage or hours."""
        vin = str(test_vehicle["vin"])
        reminder = await self._create(
            client,
            auth_headers,
            vin,
            {
                "title": "Registration renewal",
                "reminder_type": "date",
                "due_date": (date.today() + timedelta(days=30)).isoformat(),
            },
        )

        await self._assert_rejected(
            client, auth_headers, vin, int(reminder["id"]), {"reminder_type": "smart"}
        )
