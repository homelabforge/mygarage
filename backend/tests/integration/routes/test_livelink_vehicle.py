"""
Integration tests for vehicle-specific LiveLink routes.

Tests status, telemetry, sessions, DTCs, and export endpoints.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.models.vehicle_dtc import VehicleDTC
from app.utils.datetime_utils import utc_now


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleLiveLinkStatus:
    """Test vehicle LiveLink status endpoint."""

    async def test_get_status_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test getting status without authentication."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/livelink/status")
        assert response.status_code == 401

    async def test_get_status_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test getting status for non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/status",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_livelink_forbidden_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Test that non-owner users cannot access another user's livelink data."""
        vin = test_vehicle["vin"]
        response = await client.get(
            f"/api/vehicles/{vin}/livelink/status",
            headers=non_admin_headers,
        )
        assert response.status_code == 403

    async def test_get_status_no_device(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test getting status when no device is linked."""
        with (
            patch("app.routes.livelink_vehicle.LiveLinkService") as mock_livelink_class,
            patch("app.routes.livelink_vehicle.TelemetryService") as mock_telemetry_class,
            patch("app.routes.livelink_vehicle.SessionService") as mock_session_class,
        ):
            mock_livelink = MagicMock()
            mock_livelink.list_devices_by_vin = AsyncMock(return_value=[])
            mock_livelink_class.return_value = mock_livelink

            mock_telemetry = MagicMock()
            mock_telemetry.get_latest_values = AsyncMock(return_value=[])
            mock_telemetry.get_all_parameters = AsyncMock(return_value={})
            mock_telemetry_class.return_value = mock_telemetry

            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            response = await client.get(
                f"/api/vehicles/{test_vehicle['vin']}/livelink/status",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == test_vehicle["vin"]
        assert data["device_id"] is None
        assert data["device_status"] == "offline"


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleTelemetry:
    """Test vehicle telemetry query endpoint."""

    async def test_get_telemetry_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test getting telemetry without authentication."""
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/livelink/telemetry",
            params={"start": start.isoformat(), "end": now.isoformat()},
        )
        assert response.status_code == 401

    async def test_get_telemetry_missing_params(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test getting telemetry without required parameters."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/livelink/telemetry",
            headers=auth_headers,
        )
        # Missing start/end parameters
        assert response.status_code == 422

    async def test_get_telemetry_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test getting telemetry for non-existent vehicle."""
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/telemetry",
            headers=auth_headers,
            params={"start": start.isoformat(), "end": now.isoformat()},
        )
        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleSessions:
    """Test vehicle drive session endpoints."""

    async def test_list_sessions_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test listing sessions without authentication."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/livelink/sessions")
        assert response.status_code == 401

    async def test_list_sessions_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test listing sessions for non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/sessions",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_list_sessions_empty(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing sessions when none exist."""
        with patch("app.routes.livelink_vehicle.SessionService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_vehicle_sessions = AsyncMock(return_value=[])
            mock_service.get_session_count = AsyncMock(return_value=0)
            # Reported alongside every list so a filtered view can say how many
            # motionless sessions it is holding back. Stubbed because the whole
            # service is replaced here; the counts themselves are covered in
            # tests/unit/services/test_session_stationary_filter.py.
            mock_service.get_stationary_session_count = AsyncMock(return_value=0)
            mock_service_class.return_value = mock_service

            response = await client.get(
                f"/api/vehicles/{test_vehicle['vin']}/livelink/sessions",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []
        assert data["total"] == 0

    async def test_get_session_detail_not_found(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test getting non-existent session."""
        with patch("app.routes.livelink_vehicle.SessionService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_session = AsyncMock(return_value=None)
            mock_service_class.return_value = mock_service

            response = await client.get(
                f"/api/vehicles/{test_vehicle['vin']}/livelink/sessions/99999",
                headers=auth_headers,
            )

        assert response.status_code == 404


async def _dtc_vehicle(
    db_session: AsyncSession,
    test_user: dict[str, object],
    rows: list[tuple[str, bool, datetime, datetime | None]],
) -> str:
    """A vehicle of the test user's with these DTC rows: (code, active, seen, cleared)."""
    vin = "DTC" + uuid.uuid4().hex[:14].upper()
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="DTC Filter Test",
            vehicle_type="Car",
            year=2020,
            make="Honda",
            model="Civic",
        )
    )
    await db_session.flush()
    for code, active, seen, cleared in rows:
        db_session.add(
            VehicleDTC(
                vin=vin,
                device_id="dtc-filter-dev",
                code=code,
                severity="warning",
                first_seen=seen,
                last_seen=seen,
                is_active=active,
                cleared_at=cleared,
            )
        )
    await db_session.commit()
    return vin


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleDTCs:
    """Test vehicle DTC endpoints."""

    async def test_list_dtcs_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test listing DTCs without authentication."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/livelink/dtcs")
        assert response.status_code == 401

    async def test_list_dtcs_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test listing DTCs for non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/dtcs",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_list_dtcs_empty(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing DTCs when none exist."""
        with patch("app.routes.livelink_vehicle.DTCService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_active_dtcs = AsyncMock(return_value=[])
            mock_service.get_dtc_counts = AsyncMock(return_value={"active": 0, "critical": 0})
            mock_service_class.return_value = mock_service

            response = await client.get(
                f"/api/vehicles/{test_vehicle['vin']}/livelink/dtcs",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["dtcs"] == []
        assert data["active_count"] == 0

    async def test_cleared_only_filters_before_the_limit(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        test_user: dict[str, object],
    ):
        """cleared_only returns cleared codes even when newer active ones fill the limit."""
        now = utc_now()
        vin = await _dtc_vehicle(
            db_session,
            test_user,
            [
                ("P0300", True, now - timedelta(minutes=5), None),
                ("P0171", True, now, None),
                ("P0420", False, now - timedelta(days=2), now - timedelta(days=1)),
            ],
        )
        url = f"/api/vehicles/{vin}/livelink/dtcs"

        cleared = await client.get(
            url, params={"cleared_only": "true", "limit": 1}, headers=auth_headers
        )
        assert cleared.status_code == 200, cleared.text
        assert [(d["code"], d["is_active"]) for d in cleared.json()["dtcs"]] == [("P0420", False)]

        # Today's history order: newest last_seen first, active or not.
        history = await client.get(
            url, params={"include_cleared": "true", "limit": 1}, headers=auth_headers
        )
        assert history.status_code == 200, history.text
        assert [d["code"] for d in history.json()["dtcs"]] == ["P0171"]

    async def test_active_view_honours_the_limit(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        test_user: dict[str, object],
    ):
        """The default (active) view stops at limit too, newest first seen first."""
        now = utc_now()
        vin = await _dtc_vehicle(
            db_session,
            test_user,
            [
                ("P0300", True, now - timedelta(minutes=10), None),
                ("P0171", True, now, None),
                ("P0128", True, now - timedelta(minutes=5), None),
            ],
        )

        r = await client.get(
            f"/api/vehicles/{vin}/livelink/dtcs", params={"limit": 2}, headers=auth_headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert [d["code"] for d in body["dtcs"]] == ["P0171", "P0128"]
        # The counts still cover every active code.
        assert body["active_count"] == 3


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleExport:
    """Test vehicle data export endpoints."""

    async def test_export_telemetry_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test exporting telemetry without authentication."""
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/livelink/export/telemetry",
            params={"start": start.isoformat(), "end": now.isoformat()},
        )
        assert response.status_code == 401

    async def test_export_telemetry_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test exporting telemetry for non-existent vehicle."""
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/export/telemetry",
            headers=auth_headers,
            params={"start": start.isoformat(), "end": now.isoformat()},
        )
        assert response.status_code == 404

    async def test_export_sessions_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test exporting sessions without authentication."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/livelink/export/sessions")
        assert response.status_code == 401

    async def test_export_sessions_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test exporting sessions for non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/export/sessions",
            headers=auth_headers,
        )
        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_session_csv_keeps_zeros(
    client: AsyncClient, auth_headers, db_session, test_user
):
    """G4-05: `x or ""` wrote a parked session's 0 s, 0.0 km and 0.0 km/h as
    blanks, which read as "not recorded". Only None is blank."""
    import csv
    import io

    from app.models.drive_session import DriveSession

    vin = f"CS{uuid.uuid4().hex[:15].upper()}"
    db_session.add(Vehicle(vin=vin, user_id=test_user["id"], nickname="Csv", vehicle_type="Car"))
    started = utc_now() - timedelta(hours=1)
    db_session.add(
        DriveSession(
            vin=vin,
            device_id="csvzeros01",
            started_at=started,
            ended_at=started,
            duration_seconds=0,
            distance_km=0.0,
            avg_speed=0.0,
            max_speed=0.0,
            avg_rpm=None,
            max_rpm=0.0,
        )
    )
    await db_session.commit()

    resp = await client.get(f"/api/vehicles/{vin}/livelink/export/sessions", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 1
    row = rows[0]
    assert row["duration_seconds"] == "0"
    assert row["distance_km"] == "0.0"
    assert row["avg_speed"] == "0.0"
    assert row["max_speed"] == "0.0"
    assert row["max_rpm"] == "0.0"
    assert row["avg_rpm"] == ""
