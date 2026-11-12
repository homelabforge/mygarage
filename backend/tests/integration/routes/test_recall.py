"""
Integration tests for recall routes.

Tests recall CRUD operations and NHTSA integration endpoints.
"""

import asyncio
import datetime as dt
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models.recall import Recall
from app.models.service_visit import ServiceVisit
from app.models.vendor import Vendor
from app.schemas.recall import RecallUpdate
from app.schemas.service_visit import ServiceLineItemCreate, ServiceVisitCreate
from app.services import recall_links
from app.services import recall_service as recall_service_module
from app.services.nhtsa import NHTSAService
from app.services.recall_links import resolved_at_for
from app.services.recall_service import RecallService
from app.services.service_visit_service import ServiceVisitService
from app.services.settings_service import SettingsService
from app.utils.datetime_utils import utc_now


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
        # 502: NHTSA unavailable
        assert response.status_code in [200, 400, 422, 500, 502]
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
        # The switch is read before the client is even built, not just before the fetch.
        built: list[NHTSAService] = []
        real_init = NHTSAService.__init__

        def recording_init(self: NHTSAService) -> None:
            built.append(self)
            real_init(self)

        monkeypatch.setattr(NHTSAService, "__init__", recording_init)

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/check-nhtsa",
            headers=auth_headers,
        )

        assert response.status_code == expected, response.text
        if expected == 409:
            assert response.json()["detail"] == (
                "NHTSA recalls are switched off in Settings > Integrations"
            )
            assert built == []
            fetch.assert_not_awaited()
        else:
            assert len(built) == 1
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


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallsWithoutAVin:
    """#226: NHTSA works from the VIN, so a vehicle without one gets a
    clear 409 from the NHTSA check and the generic check skips NHTSA."""

    @pytest.mark.parametrize("nhtsa_enabled", ["true", "false"])
    async def test_the_nhtsa_check_refuses_a_vehicle_without_a_vin(
        self,
        client: AsyncClient,
        auth_headers,
        db_session,
        keep_rows,
        monkeypatch,
        nhtsa_enabled: str,
    ):
        await keep_rows("nhtsa_enabled")
        await SettingsService.set(db_session, "nhtsa_enabled", nhtsa_enabled)
        await db_session.commit()
        fetch = AsyncMock(return_value=[])
        monkeypatch.setattr("app.services.nhtsa.NHTSAService.get_vehicle_recalls", fetch)
        created = await client.post(
            "/api/vehicles",
            headers=auth_headers,
            json={
                "nickname": "Kubota",
                "vehicle_type": "Tractor",
                "identifier_type": "serial",
                "identifier": "BX23S-77",
            },
        )
        assert created.status_code == 201, created.text
        key = created.json()["vin"]
        try:
            response = await client.post(
                f"/api/vehicles/{key}/recalls/check-nhtsa", headers=auth_headers
            )
            assert response.status_code == 409, response.text
            assert response.json()["detail"] == (
                "NHTSA looks recalls up by VIN, and this vehicle has none"
            )
            fetch.assert_not_awaited()
        finally:
            await client.delete(f"/api/vehicles/{key}", headers=auth_headers)

    @pytest.mark.parametrize("nhtsa_enabled", ["true", "false"])
    async def test_a_french_vehicle_without_a_vin_gets_rappelconso_only(
        self,
        client: AsyncClient,
        auth_headers,
        db_session,
        keep_rows,
        monkeypatch,
        nhtsa_enabled: str,
    ):
        await keep_rows("nhtsa_enabled")
        await SettingsService.set(db_session, "nhtsa_enabled", nhtsa_enabled)
        await db_session.commit()
        nhtsa_fetch = AsyncMock(return_value=[])
        monkeypatch.setattr("app.services.nhtsa.NHTSAService.get_vehicle_recalls", nhtsa_fetch)
        rappel = AsyncMock(return_value=[])
        monkeypatch.setattr("app.services.recalls.rappelconso.RappelConsoProvider.fetch", rappel)
        created = await client.post(
            "/api/vehicles",
            headers=auth_headers,
            json={
                "nickname": "4L",
                "vehicle_type": "Car",
                "identifier_type": "chassis",
                "identifier": "R1121234567",
                "make": "Renault",
                "model": "4",
                "registration_country": "FR",
            },
        )
        assert created.status_code == 201, created.text
        key = created.json()["vin"]
        try:
            response = await client.post(f"/api/vehicles/{key}/recalls/check", headers=auth_headers)
            assert response.status_code == 200, response.text
            assert response.json()["providers_checked"] == ["rappelconso"]
            rappel.assert_awaited_once()
            nhtsa_fetch.assert_not_awaited()
        finally:
            await client.delete(f"/api/vehicles/{key}", headers=auth_headers)


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallSources:
    """Where a recall came from (#211): the generic check, the sources that
    cover a country, and the rows they store."""

    async def test_manual_entry_is_marked_manual(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Seat belt",
                "summary": "Typed by hand",
                "external_url": "https://example.org/notice/1",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["source"] == "manual"
        assert data["external_url"] == "https://example.org/notice/1"
        assert data["external_id"] is None
        assert data["match_confidence"] is None

    async def test_check_asks_rappelconso_for_a_french_vehicle_once(
        self, client: AsyncClient, auth_headers
    ):

        from app.services.recalls.base import RecallHit

        vin = "VF1AG000X" + "66" + uuid_tail()
        created = await client.post(
            "/api/vehicles",
            headers=auth_headers,
            json={
                "vin": vin,
                "nickname": "Zoé",
                "vehicle_type": "Car",
                "make": "Renault",
                "model": "Zoe",
                "registration_country": "FR",
                "first_registration_date": "2019-09-02",
            },
        )
        assert created.status_code == 201, created.text
        hit = RecallHit(
            source="rappelconso",
            external_id="2024-03-0123",
            external_url="https://rappel.conso.gouv.fr/fiche-rappel/12345/Interne",
            component="Automobiles",
            summary="Rappel de véhicules Renault ZOE",
            consequence="Risque d'incendie",
            remedy="Prendre rendez-vous",
            date_announced=dt.date(2024, 3, 14),
            match_confidence=95,
        )
        try:
            with patch(
                "app.services.recalls.rappelconso.RappelConsoProvider.fetch",
                new=AsyncMock(return_value=[hit]),
            ) as fetch:
                first = await client.post(
                    f"/api/vehicles/{vin}/recalls/check", headers=auth_headers
                )
                assert first.status_code == 200, first.text
                body = first.json()
                assert body["providers_checked"] == ["rappelconso"]
                assert body["new_count"] == 1
                assert body["warnings"] == []
                assert body["total"] == 1
                stored = body["recalls"][0]
                assert stored["source"] == "rappelconso"
                assert stored["external_id"] == "2024-03-0123"
                assert stored["external_url"].startswith("https://rappel.conso.gouv.fr/")
                assert stored["match_confidence"] == 95
                assert stored["nhtsa_campaign_number"] is None
                assert stored["date_announced"] == "2024-03-14"
                assert stored["is_resolved"] is False

                again = await client.post(
                    f"/api/vehicles/{vin}/recalls/check", headers=auth_headers
                )
                assert again.json()["new_count"] == 0
                assert again.json()["total"] == 1
                assert fetch.await_count == 2
        finally:
            await client.delete(f"/api/vehicles/{vin}", headers=auth_headers)

    async def test_check_reports_a_source_that_fails(self, client: AsyncClient, auth_headers):

        vin = "VF1AG000X" + "77" + uuid_tail()
        created = await client.post(
            "/api/vehicles",
            headers=auth_headers,
            json={
                "vin": vin,
                "nickname": "Clio",
                "vehicle_type": "Car",
                "make": "Renault",
                "model": "Clio",
                "registration_country": "FR",
            },
        )
        assert created.status_code == 201, created.text
        try:
            with patch(
                "app.services.recalls.rappelconso.RappelConsoProvider.fetch",
                new=AsyncMock(side_effect=RuntimeError("down")),
            ):
                response = await client.post(
                    f"/api/vehicles/{vin}/recalls/check", headers=auth_headers
                )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["providers_checked"] == ["rappelconso"]
            assert body["warnings"] == ["rappelconso: check failed"]
            assert body["new_count"] == 0
        finally:
            await client.delete(f"/api/vehicles/{vin}", headers=auth_headers)

    async def test_check_without_a_country_asks_nhtsa(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):

        from app.services.recalls.base import RecallHit

        hit = RecallHit(
            source="nhtsa",
            external_id="24V999",
            external_url="https://www.nhtsa.gov/recalls?nhtsaId=24V999",
            component="AIR BAGS",
            summary="Inflator",
        )
        with patch(
            "app.services.recalls.nhtsa.NHTSARecallProvider.fetch",
            new=AsyncMock(return_value=[hit]),
        ):
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/recalls/check", headers=auth_headers
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["providers_checked"] == ["nhtsa"]
        stored = [r for r in body["recalls"] if r["external_id"] == "24V999"]
        assert len(stored) == 1
        assert stored[0]["source"] == "nhtsa"
        assert stored[0]["nhtsa_campaign_number"] == "24V999"
        assert stored[0]["match_confidence"] == 100

    async def test_check_needs_a_write_share(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/check", headers=non_admin_headers
        )
        assert response.status_code in (403, 404)

    async def test_check_works_with_auth_off(
        self,
        client: AsyncClient,
        test_vehicle: dict[str, object],
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        """auth_mode 'none' has no user at all, and the check still stores what's new."""
        from app.services.recalls.base import RecallHit

        vin = test_vehicle["vin"]
        url = f"/api/vehicles/{vin}/recalls/check"
        assert (await client.post(url)).status_code == 401
        campaign = "24V" + uuid_tail()
        hit = RecallHit(
            source="nhtsa",
            external_id=campaign,
            external_url=f"https://www.nhtsa.gov/recalls?nhtsaId={campaign}",
            component="SERVICE BRAKES",
            summary="Caliper",
        )
        await set_auth_mode("none")
        with patch(
            "app.services.recalls.nhtsa.NHTSARecallProvider.fetch",
            new=AsyncMock(return_value=[hit]),
        ):
            response = await client.post(url)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["new_count"] == 1
        assert [r["external_id"] for r in body["recalls"] if r["external_id"] == campaign] == [
            campaign
        ]


def uuid_tail() -> str:
    """Six VIN-safe characters."""
    import uuid

    return uuid.uuid4().hex.upper().replace("O", "P").replace("I", "J").replace("Q", "R")[:6]


# ============================================================================
#  Recalls tab vs line item links
# ============================================================================

Sessions = async_sessionmaker[AsyncSession]

_REOPEN_REFUSED = "Fixed on the service visit on 2026-11-03. Unlink it there to reopen."


async def _stored_recall(db: AsyncSession, vin: str, **fields: Any) -> int:
    """A recall written straight to the table, the way a sync or an import would."""
    values: dict[str, Any] = {"component": "AIR BAGS", "summary": "The inflator may rupture."}
    values.update(fields)
    recall = Recall(vin=vin, **values)
    db.add(recall)
    await db.commit()
    return recall.id


async def _state(sessions: Sessions, recall_id: int) -> tuple[bool, dt.datetime | None, str | None]:
    """A recall's (is_resolved, resolved_at, resolved_via), read fresh."""
    async with sessions() as s:
        recall = await s.get(Recall, recall_id)
        assert recall is not None
        return bool(recall.is_resolved), recall.resolved_at, recall.resolved_via


async def _link_by_visit(
    client: AsyncClient,
    headers: dict[str, str],
    vin: str,
    recall_id: int,
    *,
    vendor_id: int | None = None,
) -> tuple[int, int]:
    """A visit on 2026-11-03 whose one item links the recall: (visit id, item id)."""
    body: dict[str, Any] = {
        "date": "2026-11-03",
        "line_items": [
            {
                "description": "Inflator swap",
                "cost": "0.00",
                "is_recall": True,
                "recall_id": recall_id,
            }
        ],
    }
    if vendor_id is not None:
        body["vendor_id"] = vendor_id
    r = await client.post(f"/api/vehicles/{vin}/service-visits", json=body, headers=headers)
    assert r.status_code == 201, r.text
    visit = r.json()
    return visit["id"], visit["line_items"][0]["id"]


async def _put_recall(
    client: AsyncClient, headers: dict[str, str], vin: str, recall_id: int, body: dict[str, Any]
) -> Any:
    return await client.put(f"/api/vehicles/{vin}/recalls/{recall_id}", json=body, headers=headers)


@pytest_asyncio.fixture
async def shop(db_session: AsyncSession) -> AsyncIterator[tuple[int, str]]:
    """A throwaway shop as (id, name); visits still pointing at it are let go first."""
    name = f"Recall Shop {uuid_tail()}"
    vendor = Vendor(name=name)
    db_session.add(vendor)
    await db_session.commit()
    vid = vendor.id
    yield vid, name
    await db_session.rollback()
    await db_session.execute(
        update(ServiceVisit).where(ServiceVisit.vendor_id == vid).values(vendor_id=None)
    )
    await db_session.execute(delete(Vendor).where(Vendor.id == vid))
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallsTabAndVisitLinks:
    """The client shares the test's session, so state is read from a fresh one."""

    async def test_reopening_a_linked_manual_recall_is_a_409(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        new_vehicle: Callable[..., Awaitable[str]],
        db_session: AsyncSession,
        test_sessionmaker: Sessions,
    ) -> None:
        """Keyed on the link, not on resolved_via."""
        vin = await new_vehicle()
        rid = await _stored_recall(db_session, vin)
        r = await _put_recall(client, auth_headers, vin, rid, {"is_resolved": True})
        assert r.status_code == 200, r.text
        await _link_by_visit(client, auth_headers, vin, rid)
        before = await _state(test_sessionmaker, rid)
        assert before[0] is True and before[2] == "manual"

        r = await _put_recall(client, auth_headers, vin, rid, {"is_resolved": False})
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == _REOPEN_REFUSED
        assert await _state(test_sessionmaker, rid) == before

    async def test_reopening_a_linked_visit_recall_is_a_409_and_changes_nothing(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        new_vehicle: Callable[..., Awaitable[str]],
        db_session: AsyncSession,
        test_sessionmaker: Sessions,
    ) -> None:
        vin = await new_vehicle()
        rid = await _stored_recall(db_session, vin, notes="before")
        await _link_by_visit(client, auth_headers, vin, rid)
        before = await _state(test_sessionmaker, rid)
        assert before[0] is True and before[2] == "service_visit"

        r = await _put_recall(
            client, auth_headers, vin, rid, {"is_resolved": False, "notes": "after"}
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == _REOPEN_REFUSED
        assert await _state(test_sessionmaker, rid) == before
        async with test_sessionmaker() as s:
            stored = await s.get(Recall, rid)
            assert stored is not None and stored.notes == "before"

    async def test_an_unlinked_visit_recall_reopens(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        new_vehicle: Callable[..., Awaitable[str]],
        db_session: AsyncSession,
        test_sessionmaker: Sessions,
    ) -> None:
        """Only an import leaves one of these; it reads as manual."""
        vin = await new_vehicle()
        rid = await _stored_recall(
            db_session,
            vin,
            is_resolved=True,
            resolved_at=dt.datetime(2026, 10, 1, 17, 0),
            resolved_via="service_visit",
        )
        r = await _put_recall(client, auth_headers, vin, rid, {"is_resolved": False})
        assert r.status_code == 200, r.text
        assert await _state(test_sessionmaker, rid) == (False, None, None)
        assert r.json()["resolved_via"] is None

    async def test_resolving_by_hand_is_manual_and_reopening_clears_it(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        new_vehicle: Callable[..., Awaitable[str]],
        db_session: AsyncSession,
        test_sessionmaker: Sessions,
    ) -> None:
        vin = await new_vehicle()
        rid = await _stored_recall(db_session, vin)
        start = utc_now() - dt.timedelta(seconds=1)
        r = await _put_recall(client, auth_headers, vin, rid, {"is_resolved": True})
        assert r.status_code == 200, r.text
        resolved, at, via = await _state(test_sessionmaker, rid)
        assert resolved is True and via == "manual"
        assert at is not None and start <= at <= utc_now()
        assert r.json()["resolved_via"] == "manual"
        assert r.json()["linked_visit"] is None

        r = await _put_recall(client, auth_headers, vin, rid, {"is_resolved": False})
        assert r.status_code == 200, r.text
        assert await _state(test_sessionmaker, rid) == (False, None, None)

    async def test_resending_is_resolved_keeps_a_visit_resolved_recall_as_it_is(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        new_vehicle: Callable[..., Awaitable[str]],
        db_session: AsyncSession,
        test_sessionmaker: Sessions,
    ) -> None:
        """RecallForm always sends is_resolved, so a notes edit resends true."""
        vin = await new_vehicle()
        rid = await _stored_recall(db_session, vin)
        visit_id, item_id = await _link_by_visit(client, auth_headers, vin, rid)
        before = await _state(test_sessionmaker, rid)

        r = await _put_recall(
            client, auth_headers, vin, rid, {"is_resolved": True, "notes": "Dealer did it"}
        )
        assert r.status_code == 200, r.text
        assert await _state(test_sessionmaker, rid) == before
        body = r.json()
        assert body["notes"] == "Dealer did it"
        assert body["resolved_via"] == "service_visit"
        assert body["linked_visit"] == {
            "visit_id": visit_id,
            "line_item_id": item_id,
            "date": "2026-11-03",
            "vendor_name": None,
        }

    async def test_creating_a_resolved_recall_is_manual(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        new_vehicle: Callable[..., Awaitable[str]],
        test_sessionmaker: Sessions,
    ) -> None:
        vin = await new_vehicle()
        r = await client.post(
            f"/api/vehicles/{vin}/recalls",
            json={"vin": vin, "component": "Brakes", "summary": "Leak", "is_resolved": True},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        assert r.json()["resolved_via"] == "manual"
        resolved, at, via = await _state(test_sessionmaker, r.json()["id"])
        assert (resolved, via) == (True, "manual") and at is not None

        r = await client.post(
            f"/api/vehicles/{vin}/recalls",
            json={"vin": vin, "component": "Brakes", "summary": "Leak 2"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        assert await _state(test_sessionmaker, r.json()["id"]) == (False, None, None)

    async def test_list_and_get_carry_the_linked_visit(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        new_vehicle: Callable[..., Awaitable[str]],
        db_session: AsyncSession,
        shop: tuple[int, str],
    ) -> None:
        vin = await new_vehicle()
        linked = await _stored_recall(db_session, vin, nhtsa_campaign_number="24V000001")
        loose = await _stored_recall(db_session, vin, nhtsa_campaign_number="24V000002")
        visit_id, item_id = await _link_by_visit(
            client, auth_headers, vin, linked, vendor_id=shop[0]
        )
        expected = {
            "visit_id": visit_id,
            "line_item_id": item_id,
            "date": "2026-11-03",
            "vendor_name": shop[1],
        }

        r = await client.get(f"/api/vehicles/{vin}/recalls", headers=auth_headers)
        assert r.status_code == 200, r.text
        by_id = {x["id"]: x for x in r.json()["recalls"]}
        assert by_id[linked]["linked_visit"] == expected
        assert by_id[linked]["resolved_via"] == "service_visit"
        assert by_id[loose]["linked_visit"] is None

        r = await client.get(f"/api/vehicles/{vin}/recalls/{linked}", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["linked_visit"] == expected

    async def test_a_recall_with_no_summary_or_component_still_lists(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        new_vehicle: Callable[..., Awaitable[str]],
        db_session: AsyncSession,
    ) -> None:
        """Both columns are nullable; a NULL one used to 500 the whole list."""
        vin = await new_vehicle()
        rid = await _stored_recall(db_session, vin, summary=None, component=None)

        r = await client.get(f"/api/vehicles/{vin}/recalls", headers=auth_headers)
        assert r.status_code == 200, r.text
        (row,) = r.json()["recalls"]
        assert (row["id"], row["summary"], row["component"]) == (rid, None, None)

        r = await client.get(f"/api/vehicles/{vin}/recalls/{rid}", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["summary"] is None

    async def test_a_session_that_read_the_recall_before_the_link_still_refuses_a_reopen(
        self,
        new_vehicle: Callable[..., Awaitable[str]],
        db_session: AsyncSession,
        test_sessionmaker: Sessions,
    ) -> None:
        """The session's copy says unlinked; another request linked it since.
        The 409 has to see the link, or the linked recall gets reopened."""
        vin = await new_vehicle()
        rid = await _stored_recall(db_session, vin)
        # Hold the ORM copy, link loaded as None, so the identity map keeps it.
        held = (
            await db_session.execute(
                select(Recall)
                .options(selectinload(Recall.linked_line_item))
                .where(Recall.id == rid)
            )
        ).scalar_one()
        assert held.linked_line_item is None
        async with test_sessionmaker() as other:
            await ServiceVisitService(other).create_service_visit(
                vin,
                ServiceVisitCreate(
                    date=dt.date(2026, 11, 3),
                    line_items=[
                        ServiceLineItemCreate(
                            description="Inflator swap", is_recall=True, recall_id=rid
                        )
                    ],
                ),
                None,
            )
        before = await _state(test_sessionmaker, rid)

        with pytest.raises(HTTPException) as refused:
            await RecallService(db_session).update_recall(
                vin, rid, RecallUpdate(is_resolved=False), None
            )
        await db_session.rollback()
        assert refused.value.status_code == 409
        assert await _state(test_sessionmaker, rid) == before

    async def test_update_recall_locks_before_it_reads_the_recall(
        self,
        new_vehicle: Callable[..., Awaitable[str]],
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        vin = await new_vehicle()
        rid = await _stored_recall(db_session, vin)
        order: list[str] = []
        real_lock = recall_service_module.lock_vehicle_for_write

        async def recording_lock(db: AsyncSession, lock_vin: str) -> None:
            order.append("lock")
            await real_lock(db, lock_vin)

        real_execute = db_session.execute

        async def recording_execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
            descriptions: list[dict[str, Any]] = (
                getattr(statement, "column_descriptions", None) or []
            )
            if descriptions and descriptions[0].get("entity") is Recall:
                order.append("recall_read")
            return await real_execute(statement, *args, **kwargs)

        monkeypatch.setattr(recall_service_module, "lock_vehicle_for_write", recording_lock)
        monkeypatch.setattr(db_session, "execute", recording_execute)
        await RecallService(db_session).update_recall(vin, rid, RecallUpdate(notes="x"), None)
        assert order[:2] == ["lock", "recall_read"]
        assert order.count("lock") == 1

    async def test_delete_recall_locks_before_it_reads_the_recall(
        self,
        new_vehicle: Callable[..., Awaitable[str]],
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without the lock a delete can commit between a visit PUT's link check
        and its flush, and the PUT gets a bogus 409 on PG."""
        vin = await new_vehicle()
        rid = await _stored_recall(db_session, vin)
        order: list[str] = []
        real_lock = recall_service_module.lock_vehicle_for_write

        async def recording_lock(db: AsyncSession, lock_vin: str) -> None:
            order.append("lock")
            await real_lock(db, lock_vin)

        real_execute = db_session.execute

        async def recording_execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
            descriptions: list[dict[str, Any]] = (
                getattr(statement, "column_descriptions", None) or []
            )
            if descriptions and descriptions[0].get("entity") is Recall:
                order.append("recall_read")
            return await real_execute(statement, *args, **kwargs)

        monkeypatch.setattr(recall_service_module, "lock_vehicle_for_write", recording_lock)
        monkeypatch.setattr(db_session, "execute", recording_execute)
        await RecallService(db_session).delete_recall(vin, rid, None)
        assert order[:2] == ["lock", "recall_read"]
        assert order.count("lock") == 1
        gone = await db_session.execute(select(Recall.id).where(Recall.id == rid))
        assert gone.scalar_one_or_none() is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallPutRacesAVisitLink:
    async def test_a_waiting_resolve_sees_the_visit_link_and_keeps_it(
        self,
        new_vehicle: Callable[..., Awaitable[str]],
        db_session: AsyncSession,
        test_sessionmaker: Sessions,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Session A links the recall through a visit and holds the lock; B's
        Recalls PUT, sent while the recall was open, waits and then finds it
        resolved, so service_visit and the visit's date stay."""
        vin = await new_vehicle()
        rid = await _stored_recall(db_session, vin)
        linked = asyncio.Event()
        real_link = recall_links.link_recalls

        async def link_then_hold(db: AsyncSession, links: Any) -> None:
            await real_link(db, links)
            linked.set()
            # A hold, not a barrier: B blocks inside the driver once it's locked.
            await asyncio.sleep(1.0)

        monkeypatch.setattr(recall_links, "link_recalls", link_then_hold)

        async def visit_write() -> None:
            async with test_sessionmaker() as a:
                await ServiceVisitService(a).create_service_visit(
                    vin,
                    ServiceVisitCreate(
                        date=dt.date(2026, 11, 3),
                        line_items=[
                            ServiceLineItemCreate(
                                description="Inflator swap", is_recall=True, recall_id=rid
                            )
                        ],
                    ),
                    None,
                )

        async def recalls_put() -> None:
            await asyncio.wait_for(linked.wait(), 5)
            async with test_sessionmaker() as b:
                await RecallService(b).update_recall(
                    vin, rid, RecallUpdate(is_resolved=True, notes="from the tab"), None
                )

        results = await asyncio.gather(visit_write(), recalls_put(), return_exceptions=True)
        assert [r for r in results if isinstance(r, BaseException)] == []

        resolved, at, via = await _state(test_sessionmaker, rid)
        assert (resolved, via) == (True, "service_visit")
        assert at == resolved_at_for(dt.date(2026, 11, 3))
        async with test_sessionmaker() as s:
            stored = await s.get(Recall, rid)
            assert stored is not None and stored.notes == "from the tab"


@pytest.mark.integration
@pytest.mark.asyncio
class TestManualCheckOutage:
    """The manual check never reads an NHTSA outage as "no new recalls"."""

    @pytest.mark.parametrize(
        "error",
        [
            httpx.ReadTimeout("timed out"),
            httpx.ConnectError("refused"),
            httpx.DecodingError("bad gzip stream"),
            httpx.TooManyRedirects("redirect loop"),
        ],
    )
    async def test_an_outage_is_a_502(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_vehicle: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        error: Exception,
    ) -> None:
        """Every request error is a 502, never a 500, a 504 or a 422 "Could
        not decode VIN"; the scheduled check already read them as an outage."""
        monkeypatch.setattr("app.utils.url_validation.resolve_hostname", lambda hostname: None)

        async def fake_get(self: object, url: str, **kwargs: object) -> httpx.Response:
            raise error

        monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/check-nhtsa",
            headers=auth_headers,
        )

        assert response.status_code == 502, response.text
        assert response.json()["detail"] == "NHTSA isn't answering right now. Try again later."

    async def test_a_failed_recalls_fetch_is_not_no_new_recalls(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_vehicle: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """vPIC decodes, then the recalls API times out: a 502, not a 200 with
        nothing new. Red before the outage fix, which answered 200."""
        monkeypatch.setattr("app.utils.url_validation.resolve_hostname", lambda hostname: None)

        async def fake_get(self: object, url: str, **kwargs: object) -> httpx.Response:
            request = httpx.Request("GET", url)
            if "DecodeVinValues" in url:
                result = {"Make": "HONDA", "Model": "Accord", "ModelYear": "2020", "ErrorCode": "0"}
                return httpx.Response(200, request=request, json={"Results": [result]})
            raise httpx.ReadTimeout("timed out", request=request)

        monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/check-nhtsa",
            headers=auth_headers,
        )

        assert response.status_code == 502, response.text
