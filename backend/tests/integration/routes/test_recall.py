"""
Integration tests for recall routes.

Tests recall CRUD operations and NHTSA integration endpoints.
"""

import datetime as dt
import os
import time
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.services.settings_service import SettingsService


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallRoutes:
    """Test recall API endpoints."""

    async def test_list_recalls(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing recalls for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "recalls" in data
        assert "total" in data
        assert "active_count" in data
        assert "resolved_count" in data
        assert isinstance(data["recalls"], list)

    async def test_get_recall_by_id(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific recall."""
        # First create a recall
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Airbag",
                "summary": "Potential airbag deployment issue",
                "nhtsa_campaign_number": "24V001",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        recall = create_response.json()

        # Get the recall
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == recall["id"]
        assert data["component"] == "Airbag"
        assert data["nhtsa_campaign_number"] == "24V001"

    async def test_create_recall(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a new recall manually."""
        payload = {
            "vin": test_vehicle["vin"],
            "component": "Brakes",
            "summary": "Brake fluid leak detected under certain conditions",
            "consequence": "Loss of braking ability",
            "remedy": "Replace brake lines",
            "nhtsa_campaign_number": "24V002",
            "date_announced": "2024-01-15",
            "is_resolved": False,
            "notes": "Dealer scheduled for repair",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["component"] == payload["component"]
        assert data["summary"] == payload["summary"]
        assert data["consequence"] == payload["consequence"]
        assert data["remedy"] == payload["remedy"]
        assert data["nhtsa_campaign_number"] == payload["nhtsa_campaign_number"]
        assert data["is_resolved"] is False
        assert "id" in data
        assert "created_at" in data

    async def test_update_recall(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating a recall."""
        # Create a recall
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Transmission",
                "summary": "Transmission hesitation issue",
            },
            headers=auth_headers,
        )
        recall = create_response.json()

        # Update the recall
        update_data = {
            "notes": "Repair completed at dealership",
            "is_resolved": True,
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["notes"] == "Repair completed at dealership"
        assert data["is_resolved"] is True
        assert data["resolved_at"] is not None

    async def test_delete_recall(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting a recall."""
        # Create a recall
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Fuel System",
                "summary": "Fuel pump may fail",
            },
            headers=auth_headers,
        )
        recall = create_response.json()

        # Delete the recall
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_recall_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access recalls."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/recalls")

        assert response.status_code == 401

    async def test_recall_forbidden_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Test that non-owner users cannot access another user's recalls."""
        vin = test_vehicle["vin"]
        response = await client.get(
            f"/api/vehicles/{vin}/recalls",
            headers=non_admin_headers,
        )
        assert response.status_code == 403

    async def test_recall_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test recalls with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/1HGBH000000000000/recalls",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_recall_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test get recall with non-existent ID."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_create_resolved_recall(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating an already-resolved recall."""
        payload = {
            "vin": test_vehicle["vin"],
            "component": "Electrical",
            "summary": "Battery drain issue",
            "is_resolved": True,
            "notes": "Already fixed by previous owner",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["is_resolved"] is True
        assert data["resolved_at"] is not None

    async def test_mark_recall_unresolved(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test marking a resolved recall as unresolved."""
        # Create a resolved recall
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Cooling System",
                "summary": "Coolant leak",
                "is_resolved": True,
            },
            headers=auth_headers,
        )
        recall = create_response.json()
        assert recall["resolved_at"] is not None

        # Mark as unresolved
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            json={"is_resolved": False},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_resolved"] is False
        assert data["resolved_at"] is None

    async def test_list_recalls_filter_active(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test filtering recalls by active status."""
        # Create an active recall
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Steering",
                "summary": "Steering wheel vibration",
                "is_resolved": False,
            },
            headers=auth_headers,
        )

        # Create a resolved recall
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Suspension",
                "summary": "Suspension noise",
                "is_resolved": True,
            },
            headers=auth_headers,
        )

        # Filter by active only
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls?status=active",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All returned recalls should be active (not resolved)
        for recall in data["recalls"]:
            assert recall["is_resolved"] is False

    async def test_list_recalls_filter_resolved(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test filtering recalls by resolved status."""
        # Create a resolved recall
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Exhaust",
                "summary": "Exhaust leak",
                "is_resolved": True,
            },
            headers=auth_headers,
        )

        # Filter by resolved only
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls?status=resolved",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All returned recalls should be resolved
        for recall in data["recalls"]:
            assert recall["is_resolved"] is True

    async def test_recall_counts(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that recall counts are calculated correctly."""
        # Create multiple recalls with different statuses
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Active1",
                "summary": "Test1",
                "is_resolved": False,
            },
            headers=auth_headers,
        )
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Active2",
                "summary": "Test2",
                "is_resolved": False,
            },
            headers=auth_headers,
        )
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Resolved1",
                "summary": "Test3",
                "is_resolved": True,
            },
            headers=auth_headers,
        )

        # Get all recalls
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Verify counts make sense
        assert data["total"] == data["active_count"] + data["resolved_count"]
        assert data["active_count"] >= 2
        assert data["resolved_count"] >= 1

    async def test_partial_update_recall(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test partial update of recall."""
        # Create a recall
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Tires",
                "summary": "Tire tread separation risk",
                "notes": "Original notes",
            },
            headers=auth_headers,
        )
        recall = create_response.json()

        # Update only summary
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            json={"summary": "Updated summary with more details"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Original component unchanged
        assert data["component"] == "Tires"
        # Original notes unchanged
        assert data["notes"] == "Original notes"
        # Summary updated
        assert data["summary"] == "Updated summary with more details"

    async def test_recall_with_all_fields(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a recall with all possible fields."""
        payload = {
            "vin": test_vehicle["vin"],
            "component": "Engine - Software",
            "summary": "Engine control module software update required",
            "consequence": "Unexpected engine stall while driving",
            "remedy": "Software reflash at dealer",
            "nhtsa_campaign_number": "24V003",
            "date_announced": "2024-02-01",
            "is_resolved": False,
            "notes": "Appointment scheduled for March 15th",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["component"] == payload["component"]
        assert data["summary"] == payload["summary"]
        assert data["consequence"] == payload["consequence"]
        assert data["remedy"] == payload["remedy"]
        assert data["nhtsa_campaign_number"] == payload["nhtsa_campaign_number"]
        assert data["date_announced"] == payload["date_announced"]
        assert data["notes"] == payload["notes"]

    async def test_create_recall_minimal(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a recall with minimal required fields."""
        payload = {
            "vin": test_vehicle["vin"],
            "component": "Body",
            "summary": "Paint defect",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["component"] == "Body"
        assert data["summary"] == "Paint defect"
        assert data["is_resolved"] is False  # Default
        assert data["consequence"] is None
        assert data["remedy"] is None
        assert data["nhtsa_campaign_number"] is None

    async def test_check_nhtsa_recalls_endpoint(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test the check-nhtsa endpoint exists and handles requests.

        The endpoint properly handles VIN decode failures by catching ValueError
        and returning a 422 response with a descriptive error message.
        """
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/check-nhtsa",
            headers=auth_headers,
        )

        # Valid status codes:
        # 200: Success with recalls data
        # 400/422: VIN could not be decoded (make/model/year not determinable)
        # 500: Internal error
        # 503: NHTSA unavailable
        # 504: NHTSA timeout
        assert response.status_code in [200, 400, 422, 500, 503, 504]
        if response.status_code == 200:
            data = response.json()
            assert "recalls" in data
            assert "total" in data


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallResolvedTimestamp:
    """resolved_at is written in UTC like every other timestamp."""

    async def test_resolved_at_is_utc_regardless_of_process_timezone(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """A container with TZ set must not stamp resolved_at in local time.

        The frontend treats naive timestamps as UTC, so a local-time stamp
        shifts the displayed day by the container's offset. A POSIX TZ string
        needs no tzdata, so this fails on a bare image too.
        """
        previous = os.environ.get("TZ")
        os.environ["TZ"] = "TEST-10"  # POSIX sign: ten hours EAST of UTC
        time.tzset()
        try:
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/recalls",
                json={
                    "vin": test_vehicle["vin"],
                    "component": "Fuel Pump",
                    "summary": "Pump may fail",
                    "is_resolved": True,
                },
                headers=auth_headers,
            )
            assert response.status_code == 201
            resolved_at = dt.datetime.fromisoformat(response.json()["resolved_at"])
            now_utc = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        finally:
            if previous is None:
                del os.environ["TZ"]
            else:
                os.environ["TZ"] = previous
            time.tzset()

        assert abs((now_utc - resolved_at).total_seconds()) < 60


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallCampaignNumberWidth:
    """The column is VARCHAR(20). SQLite ignores the width and PostgreSQL
    refuses the insert, so the schema has to say no first."""

    @pytest.mark.parametrize(("width", "expected"), [(20, 201), (21, 422)])
    async def test_create(
        self, client: AsyncClient, auth_headers, test_vehicle, width: int, expected: int
    ):
        """21 characters is a 422 instead of a save that fails on PostgreSQL.

        The 20 case is a guard; mutant: `max_length=19` on RecallBase.
        """
        vin = test_vehicle["vin"]
        response = await client.post(
            f"/api/vehicles/{vin}/recalls",
            json={
                "vin": vin,
                "component": "Airbag",
                "summary": "Inflator may rupture",
                "nhtsa_campaign_number": "2" * width,
            },
            headers=auth_headers,
        )
        try:
            assert response.status_code == expected, response.text
        finally:
            if response.status_code == 201:
                await client.delete(
                    f"/api/vehicles/{vin}/recalls/{response.json()['id']}",
                    headers=auth_headers,
                )

    @pytest.mark.parametrize(("width", "expected"), [(20, 200), (21, 422)])
    async def test_update(
        self, client: AsyncClient, auth_headers, test_vehicle, width: int, expected: int
    ):
        """Same width on an edit.

        The 20 case is a guard; mutant: `max_length=19` on RecallUpdate.
        """
        vin = test_vehicle["vin"]
        created = await client.post(
            f"/api/vehicles/{vin}/recalls",
            json={"vin": vin, "component": "Airbag", "summary": "Inflator may rupture"},
            headers=auth_headers,
        )
        assert created.status_code == 201
        recall_id = created.json()["id"]
        try:
            response = await client.put(
                f"/api/vehicles/{vin}/recalls/{recall_id}",
                json={"nhtsa_campaign_number": "2" * width},
                headers=auth_headers,
            )
            assert response.status_code == expected, response.text
        finally:
            await client.delete(f"/api/vehicles/{vin}/recalls/{recall_id}", headers=auth_headers)


@pytest.mark.integration
@pytest.mark.asyncio
class TestCheckNhtsaSwitch:
    """The manual check honours `nhtsa_enabled`, after the vehicle access check."""

    @pytest.mark.parametrize(("enabled", "expected"), [("false", 409), ("yes", 200)])
    async def test_the_switch_gates_the_manual_check(
        self,
        client: AsyncClient,
        auth_headers,
        test_vehicle,
        db_session,
        keep_rows,
        monkeypatch,
        enabled: str,
        expected: int,
    ):
        """Switched off is a 409 that names where to switch it back on, and
        NHTSA is not asked. Red as a whole on main, which ignored the switch;
        the "yes" row alone is a guard (any on word still checks)."""
        await keep_rows("nhtsa_enabled")
        await SettingsService.set(db_session, "nhtsa_enabled", enabled)
        await db_session.commit()
        fetch = AsyncMock(return_value=[])
        monkeypatch.setattr("app.services.nhtsa.NHTSAService.get_vehicle_recalls", fetch)

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/check-nhtsa",
            headers=auth_headers,
        )

        assert response.status_code == expected, response.text
        if expected == 409:
            assert response.json()["detail"] == (
                "NHTSA recalls are switched off in Settings > Integrations"
            )
            fetch.assert_not_awaited()
        else:
            fetch.assert_awaited_once()

    async def test_a_non_owner_still_gets_403_with_the_switch_off(
        self,
        client: AsyncClient,
        non_admin_headers,
        test_vehicle,
        db_session,
        keep_rows,
    ):
        """The switch state isn't disclosed for a vehicle the caller can't write.

        Regression guard (main answered 403 too); mutant: check the switch
        before `get_vehicle_or_403`.
        """
        await keep_rows("nhtsa_enabled")
        await SettingsService.set(db_session, "nhtsa_enabled", "false")
        await db_session.commit()

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/check-nhtsa",
            headers=non_admin_headers,
        )

        assert response.status_code == 403, response.text
