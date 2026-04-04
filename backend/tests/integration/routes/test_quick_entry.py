"""Integration tests for the Quick Entry feature.

Covers:
- PUT /auth/me: preference updates (unit, show_both, mobile_quick_entry)
- PUT /auth/me: rejects is_active and is_admin self-escalation
- GET /quick-entry/vehicles: returns owned and write-shared vehicles
- Service visit write: 403 for read-only shared vehicle
- Odometer write: 403 for read-only shared vehicle
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare


@pytest.mark.integration
@pytest.mark.asyncio
class TestUpdateCurrentUserPreferences:
    """Test PUT /auth/me preference updates."""

    async def test_update_unit_preference(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Test that unit_preference can be updated."""
        response = await client.put(
            "/api/auth/me",
            json={"unit_preference": "metric"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["unit_preference"] == "metric"

        # Verify persisted
        user = await db_session.get(User, test_user["id"])
        await db_session.refresh(user)
        assert user.unit_preference == "metric"

        # Restore
        await client.put(
            "/api/auth/me",
            json={"unit_preference": "imperial"},
            headers=auth_headers,
        )

    async def test_update_show_both_units(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Test that show_both_units can be updated."""
        response = await client.put(
            "/api/auth/me",
            json={"show_both_units": True},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["show_both_units"] is True

        user = await db_session.get(User, test_user["id"])
        await db_session.refresh(user)
        assert user.show_both_units is True

        # Restore
        await client.put(
            "/api/auth/me",
            json={"show_both_units": False},
            headers=auth_headers,
        )

    async def test_update_mobile_quick_entry_enabled(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Test that mobile_quick_entry_enabled can be toggled."""
        response = await client.put(
            "/api/auth/me",
            json={"mobile_quick_entry_enabled": False},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["mobile_quick_entry_enabled"] is False

        user = await db_session.get(User, test_user["id"])
        await db_session.refresh(user)
        assert user.mobile_quick_entry_enabled is False

        # Restore
        await client.put(
            "/api/auth/me",
            json={"mobile_quick_entry_enabled": True},
            headers=auth_headers,
        )

    async def test_cannot_self_escalate_is_admin(self, client: AsyncClient, auth_headers):
        """Test that users cannot send is_admin via self-update (rejected by schema)."""
        response = await client.put(
            "/api/auth/me",
            json={"is_admin": True},
            headers=auth_headers,
        )
        # UserSelfUpdate has extra="forbid" — privileged fields get 422
        assert response.status_code == 422

    async def test_cannot_self_escalate_is_active(self, client: AsyncClient, auth_headers):
        """Test that users cannot send is_active via self-update (rejected by schema)."""
        response = await client.put(
            "/api/auth/me",
            json={"is_active": False},
            headers=auth_headers,
        )
        # UserSelfUpdate has extra="forbid" — privileged fields get 422
        assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
class TestQuickEntryVehicles:
    """Test GET /quick-entry/vehicles."""

    async def test_returns_owned_vehicles(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that owned vehicles are returned."""
        response = await client.get(
            "/api/quick-entry/vehicles",
            headers=auth_headers,
        )
        assert response.status_code == 200
        vins = [v["vin"] for v in response.json()["vehicles"]]
        assert test_vehicle["vin"] in vins

    async def test_excludes_archived_vehicles(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Test that archived vehicles are not returned."""
        from datetime import UTC, datetime

        # Create an archived vehicle
        archived_vehicle = Vehicle(
            vin="ARCHIVEDVIN000001",
            user_id=test_user["id"],
            nickname="Archived Car",
            vehicle_type="Car",
            year=2000,
            make="Old",
            model="Car",
            archived_at=datetime.now(UTC),
        )
        db_session.add(archived_vehicle)
        await db_session.commit()

        response = await client.get(
            "/api/quick-entry/vehicles",
            headers=auth_headers,
        )
        assert response.status_code == 200
        vins = [v["vin"] for v in response.json()["vehicles"]]
        assert "ARCHIVEDVIN000001" not in vins

        # Cleanup
        await db_session.delete(archived_vehicle)
        await db_session.commit()

    async def test_includes_write_shared_vehicles(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Test that write-shared vehicles are included."""
        # Create a second user and vehicle
        other_user = User(
            username="otheruser_qe",
            email="otheruser_qe@example.com",
            hashed_password="x",
            is_active=True,
        )
        db_session.add(other_user)
        await db_session.flush()

        shared_vehicle = Vehicle(
            vin="SHAREDWRITEVIN001",
            user_id=other_user.id,
            nickname="Shared Write Vehicle",
            vehicle_type="Car",
            year=2021,
            make="Toyota",
            model="Camry",
        )
        db_session.add(shared_vehicle)
        await db_session.flush()

        share = VehicleShare(
            vehicle_vin="SHAREDWRITEVIN001",
            user_id=test_user["id"],
            permission="write",
            shared_by=other_user.id,
        )
        db_session.add(share)
        await db_session.commit()

        response = await client.get(
            "/api/quick-entry/vehicles",
            headers=auth_headers,
        )
        assert response.status_code == 200
        vins = [v["vin"] for v in response.json()["vehicles"]]
        assert "SHAREDWRITEVIN001" in vins

        # Cleanup
        await db_session.delete(share)
        await db_session.delete(shared_vehicle)
        await db_session.delete(other_user)
        await db_session.commit()

    async def test_excludes_read_only_shared_vehicles(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Test that read-only shared vehicles are not returned."""
        other_user = User(
            username="otheruser_ro",
            email="otheruser_ro@example.com",
            hashed_password="x",
            is_active=True,
        )
        db_session.add(other_user)
        await db_session.flush()

        readonly_vehicle = Vehicle(
            vin="SHAREDREADVIN0001",
            user_id=other_user.id,
            nickname="Read-Only Vehicle",
            vehicle_type="Car",
            year=2020,
            make="Honda",
            model="Civic",
        )
        db_session.add(readonly_vehicle)
        await db_session.flush()

        share = VehicleShare(
            vehicle_vin="SHAREDREADVIN0001",
            user_id=test_user["id"],
            permission="read",
            shared_by=other_user.id,
        )
        db_session.add(share)
        await db_session.commit()

        response = await client.get(
            "/api/quick-entry/vehicles",
            headers=auth_headers,
        )
        assert response.status_code == 200
        vins = [v["vin"] for v in response.json()["vehicles"]]
        assert "SHAREDREADVIN0001" not in vins

        # Cleanup
        await db_session.delete(share)
        await db_session.delete(readonly_vehicle)
        await db_session.delete(other_user)
        await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestWriteAuthEnforcement:
    """Test that write operations enforce ownership/share permission.

    Uses a dedicated non-admin user as the requester so that get_vehicle_or_403
    actually enforces permissions (admin users bypass permission checks by design).
    """

    async def _setup_read_only_share(self, db_session):
        """Create a vehicle owner, a non-admin requester, and a read-only share.

        Returns (vehicle_owner, vehicle, share, nonadmin_requester, nonadmin_headers).
        """
        from app.services.auth import create_access_token

        vehicle_owner = User(
            username="writeauth_owner",
            email="writeauth_owner@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        db_session.add(vehicle_owner)
        await db_session.flush()

        vehicle = Vehicle(
            vin="READONLYSHARE0001",
            user_id=vehicle_owner.id,
            nickname="Read-Only Shared",
            vehicle_type="Car",
            year=2022,
            make="Ford",
            model="F-150",
        )
        db_session.add(vehicle)
        await db_session.flush()

        nonadmin_requester = User(
            username="writeauth_requester",
            email="writeauth_requester@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        db_session.add(nonadmin_requester)
        await db_session.flush()

        share = VehicleShare(
            vehicle_vin="READONLYSHARE0001",
            user_id=nonadmin_requester.id,
            permission="read",
            shared_by=vehicle_owner.id,
        )
        db_session.add(share)
        await db_session.commit()

        token = create_access_token(
            data={"sub": str(nonadmin_requester.id), "username": nonadmin_requester.username}
        )
        nonadmin_headers = {"Authorization": f"Bearer {token}"}

        return vehicle_owner, vehicle, share, nonadmin_requester, nonadmin_headers

    async def _cleanup(self, db_session, share, vehicle, *users):
        """Remove test data created by _setup_read_only_share."""
        result = await db_session.execute(select(VehicleShare).where(VehicleShare.id == share.id))
        s = result.scalar_one_or_none()
        if s:
            await db_session.delete(s)

        result = await db_session.execute(select(Vehicle).where(Vehicle.vin == vehicle.vin))
        v = result.scalar_one_or_none()
        if v:
            await db_session.delete(v)

        for user in users:
            result = await db_session.execute(select(User).where(User.id == user.id))
            u = result.scalar_one_or_none()
            if u:
                await db_session.delete(u)
        await db_session.commit()

    async def test_odometer_create_forbidden_for_read_share(self, client: AsyncClient, db_session):
        """Test that creating an odometer record on a read-only shared vehicle returns 403."""
        (
            vehicle_owner,
            vehicle,
            share,
            nonadmin_requester,
            nonadmin_headers,
        ) = await self._setup_read_only_share(db_session)
        try:
            response = await client.post(
                f"/api/vehicles/{vehicle.vin}/odometer",
                json={"vin": vehicle.vin, "date": "2024-01-01", "mileage": 10000},
                headers=nonadmin_headers,
            )
            assert response.status_code == 403
        finally:
            await self._cleanup(db_session, share, vehicle, vehicle_owner, nonadmin_requester)

    async def test_odometer_update_forbidden_for_read_share(self, client: AsyncClient, db_session):
        """Test that updating an odometer record on a read-only shared vehicle returns 403."""
        (
            vehicle_owner,
            vehicle,
            share,
            nonadmin_requester,
            nonadmin_headers,
        ) = await self._setup_read_only_share(db_session)
        try:
            response = await client.put(
                f"/api/vehicles/{vehicle.vin}/odometer/9999",
                json={"date": "2024-01-01", "mileage": 10001},
                headers=nonadmin_headers,
            )
            assert response.status_code == 403
        finally:
            await self._cleanup(db_session, share, vehicle, vehicle_owner, nonadmin_requester)

    async def test_odometer_delete_forbidden_for_read_share(self, client: AsyncClient, db_session):
        """Test that deleting an odometer record on a read-only shared vehicle returns 403."""
        (
            vehicle_owner,
            vehicle,
            share,
            nonadmin_requester,
            nonadmin_headers,
        ) = await self._setup_read_only_share(db_session)
        try:
            response = await client.delete(
                f"/api/vehicles/{vehicle.vin}/odometer/9999",
                headers=nonadmin_headers,
            )
            assert response.status_code == 403
        finally:
            await self._cleanup(db_session, share, vehicle, vehicle_owner, nonadmin_requester)
