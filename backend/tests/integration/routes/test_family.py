"""
Integration tests for family routes.

Tests vehicle transfers, sharing, and family dashboard endpoints.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.models.vehicle_transfer import VehicleTransfer  # noqa: F401


@pytest_asyncio.fixture
async def family_admin(db_session) -> dict:
    """Create or get an admin user for family tests."""
    from app.services.auth import create_access_token

    result = await db_session.execute(select(User).where(User.username == "family_admin"))
    user = result.scalar_one_or_none()

    if not user:
        test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
        user = User(
            username="family_admin",
            email="family_admin@example.com",
            hashed_password=test_password_hash,
            is_active=True,
            is_admin=True,
            show_on_family_dashboard=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return {
        "id": user.id,
        "username": user.username,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest_asyncio.fixture
async def family_member(db_session) -> dict:
    """Create or get a family member user."""
    from app.services.auth import create_access_token

    result = await db_session.execute(select(User).where(User.username == "family_member"))
    user = result.scalar_one_or_none()

    if not user:
        test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
        user = User(
            username="family_member",
            email="family_member@example.com",
            hashed_password=test_password_hash,
            is_active=True,
            is_admin=False,
            relationship="spouse",
            full_name="Family Member",
            show_on_family_dashboard=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return {
        "id": user.id,
        "username": user.username,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest_asyncio.fixture
async def family_vehicle(db_session, family_admin) -> dict:
    """Create or get a vehicle for family tests."""
    test_vin = "FAMILYTEST1234567"

    result = await db_session.execute(select(Vehicle).where(Vehicle.vin == test_vin))
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        vehicle = Vehicle(
            vin=test_vin,
            user_id=family_admin["id"],
            nickname="Family Test Vehicle",
            vehicle_type="Car",
            year=2022,
            make="Ford",
            model="Mustang",
        )
        db_session.add(vehicle)
        await db_session.commit()
        await db_session.refresh(vehicle)

    # Ensure vehicle belongs to admin and clear any shares
    vehicle.user_id = family_admin["id"]
    await db_session.execute(delete(VehicleShare).where(VehicleShare.vehicle_vin == test_vin))
    await db_session.commit()

    return {
        "vin": vehicle.vin,
        "user_id": vehicle.user_id,
        "nickname": vehicle.nickname,
    }


@pytest.mark.integration
@pytest.mark.family
@pytest.mark.asyncio
class TestVehicleTransfer:
    """Test vehicle transfer endpoints."""

    async def test_get_eligible_recipients(self, client: AsyncClient, family_admin, family_vehicle):
        """Test getting eligible recipients for transfer."""
        response = await client.get(
            f"/api/family/vehicles/{family_vehicle['vin']}/eligible-recipients",
            headers=family_admin["headers"],
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_get_eligible_recipients_non_admin(
        self, client: AsyncClient, family_member, family_vehicle
    ):
        """Test that non-admin cannot get eligible recipients."""
        response = await client.get(
            f"/api/family/vehicles/{family_vehicle['vin']}/eligible-recipients",
            headers=family_member["headers"],
        )

        assert response.status_code == 403

    async def test_transfer_vehicle(
        self, client: AsyncClient, family_admin, family_member, family_vehicle, db_session
    ):
        """Test transferring a vehicle."""
        response = await client.post(
            f"/api/family/vehicles/{family_vehicle['vin']}/transfer",
            headers=family_admin["headers"],
            json={
                "to_user_id": family_member["id"],
                "transfer_notes": "Integration test transfer",
                "data_included": {"service_records": True},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vehicle_vin"] == family_vehicle["vin"]
        assert data["to_user"]["id"] == family_member["id"]
        assert data["transfer_notes"] == "Integration test transfer"

        # Verify vehicle ownership changed
        result = await db_session.execute(
            select(Vehicle).where(Vehicle.vin == family_vehicle["vin"])
        )
        vehicle = result.scalar_one()
        assert vehicle.user_id == family_member["id"]

    async def test_transfer_vehicle_non_admin(
        self, client: AsyncClient, family_member, family_admin, family_vehicle
    ):
        """Test that non-admin cannot transfer vehicles."""
        response = await client.post(
            f"/api/family/vehicles/{family_vehicle['vin']}/transfer",
            headers=family_member["headers"],
            json={
                "to_user_id": family_admin["id"],
            },
        )

        assert response.status_code == 403

    async def test_get_transfer_history(self, client: AsyncClient, family_admin, family_vehicle):
        """Test getting transfer history."""
        response = await client.get(
            f"/api/family/vehicles/{family_vehicle['vin']}/transfer-history",
            headers=family_admin["headers"],
        )

        assert response.status_code == 200
        data = response.json()
        assert "transfers" in data
        assert "total" in data


@pytest.mark.integration
@pytest.mark.family
@pytest.mark.asyncio
class TestVehicleSharing:
    """Test vehicle sharing endpoints."""

    async def test_share_vehicle(
        self, client: AsyncClient, family_admin, family_member, family_vehicle, db_session
    ):
        """Test sharing a vehicle."""
        # Clear any existing shares first
        await db_session.execute(
            delete(VehicleShare).where(VehicleShare.vehicle_vin == family_vehicle["vin"])
        )
        await db_session.commit()

        response = await client.post(
            f"/api/family/vehicles/{family_vehicle['vin']}/shares",
            headers=family_admin["headers"],
            json={
                "user_id": family_member["id"],
                "permission": "read",
            },
        )

        assert response.status_code == 201  # Created
        data = response.json()
        assert data["vehicle_vin"] == family_vehicle["vin"]
        assert data["user"]["id"] == family_member["id"]
        assert data["permission"] == "read"

    async def test_get_vehicle_shares(self, client: AsyncClient, family_admin, family_vehicle):
        """Test getting vehicle shares."""
        response = await client.get(
            f"/api/family/vehicles/{family_vehicle['vin']}/shares",
            headers=family_admin["headers"],
        )

        assert response.status_code == 200
        data = response.json()
        assert "shares" in data
        assert "total" in data

    async def test_update_share_permission(
        self, client: AsyncClient, family_admin, family_member, family_vehicle, db_session
    ):
        """Test updating share permission."""
        # Clear existing shares and create new one
        await db_session.execute(
            delete(VehicleShare).where(VehicleShare.vehicle_vin == family_vehicle["vin"])
        )
        await db_session.commit()

        # Create share
        create_response = await client.post(
            f"/api/family/vehicles/{family_vehicle['vin']}/shares",
            headers=family_admin["headers"],
            json={
                "user_id": family_member["id"],
                "permission": "read",
            },
        )
        share_id = create_response.json()["id"]

        # Update permission
        response = await client.put(
            f"/api/family/shares/{share_id}",
            headers=family_admin["headers"],
            json={"permission": "write"},
        )

        assert response.status_code == 200
        assert response.json()["permission"] == "write"

    async def test_revoke_share(
        self, client: AsyncClient, family_admin, family_member, family_vehicle, db_session
    ):
        """Test revoking a share."""
        # Clear existing shares and create new one
        await db_session.execute(
            delete(VehicleShare).where(VehicleShare.vehicle_vin == family_vehicle["vin"])
        )
        await db_session.commit()

        # Create share
        create_response = await client.post(
            f"/api/family/vehicles/{family_vehicle['vin']}/shares",
            headers=family_admin["headers"],
            json={
                "user_id": family_member["id"],
                "permission": "read",
            },
        )
        share_id = create_response.json()["id"]

        # Revoke share
        response = await client.delete(
            f"/api/family/shares/{share_id}",
            headers=family_admin["headers"],
        )

        assert response.status_code == 204

    async def test_get_shareable_users(self, client: AsyncClient, family_admin):
        """Test getting shareable users."""
        response = await client.get(
            "/api/auth/users/shareable",
            headers=family_admin["headers"],
        )

        assert response.status_code == 200
        data = response.json()
        # API returns {"users": [...]}
        assert "users" in data
        assert isinstance(data["users"], list)


@pytest.mark.integration
@pytest.mark.family
@pytest.mark.asyncio
class TestFamilyDashboard:
    """Test family dashboard endpoints."""

    async def test_get_family_dashboard(self, client: AsyncClient, family_admin):
        """Test getting family dashboard."""
        response = await client.get(
            "/api/family/dashboard",
            headers=family_admin["headers"],
        )

        assert response.status_code == 200
        data = response.json()
        assert "members" in data
        assert "total_members" in data
        assert "total_vehicles" in data
        assert "total_upcoming_reminders" in data
        assert "total_overdue_reminders" in data

    async def test_get_family_dashboard_non_admin(self, client: AsyncClient, family_member):
        """Test that non-admin cannot access family dashboard."""
        response = await client.get(
            "/api/family/dashboard",
            headers=family_member["headers"],
        )

        assert response.status_code == 403

    async def test_get_dashboard_members(self, client: AsyncClient, family_admin):
        """Test getting dashboard members for management."""
        response = await client.get(
            "/api/family/dashboard/members",
            headers=family_admin["headers"],
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_update_member_display(
        self, client: AsyncClient, family_admin, family_member, db_session
    ):
        """Test updating member dashboard display settings."""
        response = await client.put(
            f"/api/family/dashboard/members/{family_member['id']}",
            headers=family_admin["headers"],
            json={
                "show_on_family_dashboard": True,
                "family_dashboard_order": 1,
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Response is FamilyMemberData (id, username, etc.)
        assert data["id"] == family_member["id"]

        # Verify in database
        result = await db_session.execute(select(User).where(User.id == family_member["id"]))
        user = result.scalar_one()
        assert user.show_on_family_dashboard is True
        assert user.family_dashboard_order == 1


@pytest.mark.integration
@pytest.mark.family
@pytest.mark.asyncio
class TestRelationshipPresets:
    """Test relationship presets endpoint."""

    async def test_get_relationship_presets(self, client: AsyncClient, family_admin):
        """Test getting relationship preset values."""
        response = await client.get(
            "/api/auth/relationship-presets",
            headers=family_admin["headers"],
        )

        assert response.status_code == 200
        data = response.json()
        # API returns {"presets": [...]}
        assert "presets" in data
        presets = data["presets"]
        assert isinstance(presets, list)
        # Should include common relationships
        values = [r["value"] for r in presets]
        assert "spouse" in values
        assert "child" in values
        assert "parent" in values
