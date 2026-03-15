"""
Integration tests for vehicle routes.

Tests vehicle CRUD operations, access control, and archive workflows.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.vehicle
@pytest.mark.asyncio
class TestVehicleRoutes:
    """Test vehicle API endpoints."""

    async def test_list_vehicles(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing user's vehicles."""
        response = await client.get("/api/vehicles", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        # API returns {"vehicles": [...], "total": N}
        assert "vehicles" in data
        assert "total" in data
        assert isinstance(data["vehicles"], list)
        assert len(data["vehicles"]) >= 1
        # Should include our test vehicle (identified by VIN, not id)
        vehicle_vins = [v["vin"] for v in data["vehicles"]]
        assert test_vehicle["vin"] in vehicle_vins

    async def test_get_vehicle_by_vin(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific vehicle by VIN."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == test_vehicle["vin"]
        assert data["year"] == test_vehicle["year"]
        assert data["make"] == test_vehicle["make"]

    async def test_create_vehicle(self, client: AsyncClient, auth_headers, sample_vehicle_payload):
        """Test creating a new vehicle."""
        response = await client.post(
            "/api/vehicles",
            json=sample_vehicle_payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["vin"] == sample_vehicle_payload["vin"]
        assert data["year"] == sample_vehicle_payload["year"]
        assert data["nickname"] == sample_vehicle_payload["nickname"]

    async def test_update_vehicle(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating a vehicle."""
        update_data = {
            "license_plate": "UPDATED-123",
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["license_plate"] == "UPDATED-123"

    async def test_delete_vehicle(self, client: AsyncClient, auth_headers, db_session):
        """Test deleting a vehicle."""
        from app.models.vehicle import Vehicle

        # Create a vehicle specifically for deletion
        delete_vehicle = Vehicle(
            vin="1HGCM82633A999999",
            user_id=1,  # test user
            nickname="Delete Test Vehicle",
            vehicle_type="Car",
            year=2020,
            make="Test",
            model="Delete",
        )
        db_session.add(delete_vehicle)
        await db_session.commit()

        response = await client.delete(
            f"/api/vehicles/{delete_vehicle.vin}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{delete_vehicle.vin}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_get_vehicle_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access vehicles."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}")

        assert response.status_code == 401

    async def test_create_vehicle_invalid_vin(self, client: AsyncClient, auth_headers):
        """Test that invalid VINs are rejected."""
        invalid_payload = {
            "vin": "INVALID",  # Too short (must be 17 chars)
            "nickname": "Test Vehicle",
            "vehicle_type": "Car",
            "year": 2023,
            "make": "Test",
            "model": "Car",
        }

        response = await client.post(
            "/api/vehicles",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error


@pytest.mark.integration
@pytest.mark.vehicle
@pytest.mark.asyncio
class TestVehicleArchiveRoutes:
    """Test vehicle archive/unarchive/visibility endpoints."""

    async def _create_archivable_vehicle(self, db_session, user_id: int, vin: str) -> None:
        """Helper: create a fresh vehicle for archive tests."""
        from sqlalchemy import select

        from app.models.vehicle import Vehicle

        result = await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))
        existing = result.scalar_one_or_none()
        if existing:
            await db_session.delete(existing)
            await db_session.commit()

        vehicle = Vehicle(
            vin=vin,
            user_id=user_id,
            nickname="Archive Test Vehicle",
            vehicle_type="Car",
            year=2021,
            make="Toyota",
            model="Camry",
        )
        db_session.add(vehicle)
        await db_session.commit()

    async def test_archive_vehicle(self, client: AsyncClient, auth_headers, db_session, test_user):
        """Archive a vehicle and verify archived_at is set."""
        vin = "1HGCM82633A888801"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        archive_payload = {"reason": "Sold"}
        response = await client.post(
            f"/api/vehicles/{vin}/archive",
            json=archive_payload,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["archived_at"] is not None
        assert data["archive_reason"] == "Sold"
        assert data["archived_visible"] is True  # default

    async def test_archive_vehicle_with_sale_data(
        self, client: AsyncClient, auth_headers, db_session, test_user
    ):
        """Archive with reason, sale price, sale date, and notes."""
        vin = "1HGCM82633A888802"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        archive_payload = {
            "reason": "Sold",
            "sale_price": 25000.00,
            "sale_date": "2026-01-15",
            "notes": "Sold to private buyer",
            "visible": False,
        }
        response = await client.post(
            f"/api/vehicles/{vin}/archive",
            json=archive_payload,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["archived_at"] is not None
        assert data["archive_reason"] == "Sold"
        assert float(data["archive_sale_price"]) == 25000.00
        assert data["archive_sale_date"] == "2026-01-15"
        assert data["archive_notes"] == "Sold to private buyer"
        assert data["archived_visible"] is False

    async def test_archive_vehicle_nonexistent_vin(self, client: AsyncClient, auth_headers):
        """Archive a vehicle that does not exist returns 404."""
        response = await client.post(
            "/api/vehicles/00000000000000000/archive",
            json={"reason": "Sold"},
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_archive_already_archived_vehicle(
        self, client: AsyncClient, auth_headers, db_session, test_user
    ):
        """Archiving an already-archived vehicle overwrites the archive metadata."""
        vin = "1HGCM82633A888803"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        # Archive first time
        response1 = await client.post(
            f"/api/vehicles/{vin}/archive",
            json={"reason": "Sold", "notes": "First archive"},
            headers=auth_headers,
        )
        assert response1.status_code == 200

        # Archive again with different data
        response2 = await client.post(
            f"/api/vehicles/{vin}/archive",
            json={"reason": "Trade-in", "notes": "Changed mind"},
            headers=auth_headers,
        )
        assert response2.status_code == 200
        data = response2.json()
        assert data["archive_reason"] == "Trade-in"
        assert data["archive_notes"] == "Changed mind"

    async def test_archive_vehicle_non_owner_forbidden(
        self, client: AsyncClient, non_admin_headers, db_session, test_user
    ):
        """Non-owner attempting to archive another user's vehicle gets 403."""
        vin = "1HGCM82633A888804"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        response = await client.post(
            f"/api/vehicles/{vin}/archive",
            json={"reason": "Sold"},
            headers=non_admin_headers,
        )

        assert response.status_code == 403

    async def test_list_archived_vehicles(
        self, client: AsyncClient, auth_headers, db_session, test_user
    ):
        """Archived vehicles appear in the archived list."""
        vin = "1HGCM82633A888805"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        # Archive it
        await client.post(
            f"/api/vehicles/{vin}/archive",
            json={"reason": "Totaled"},
            headers=auth_headers,
        )

        # Fetch archived list
        response = await client.get(
            "/api/vehicles/archived/list",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "vehicles" in data
        assert "total" in data
        archived_vins = [v["vin"] for v in data["vehicles"]]
        assert vin in archived_vins

    async def test_unarchive_vehicle(
        self, client: AsyncClient, auth_headers, db_session, test_user
    ):
        """Unarchiving clears all archive fields."""
        vin = "1HGCM82633A888806"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        # Archive first
        await client.post(
            f"/api/vehicles/{vin}/archive",
            json={"reason": "Gifted", "notes": "Gave to sibling"},
            headers=auth_headers,
        )

        # Unarchive
        response = await client.post(
            f"/api/vehicles/{vin}/unarchive",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["archived_at"] is None
        assert data["archive_reason"] is None
        assert data["archive_sale_price"] is None
        assert data["archive_sale_date"] is None
        assert data["archive_notes"] is None
        assert data["archived_visible"] is True

    async def test_unarchive_non_archived_vehicle(
        self, client: AsyncClient, auth_headers, db_session, test_user
    ):
        """Unarchiving a vehicle that is not archived returns 400."""
        vin = "1HGCM82633A888807"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        response = await client.post(
            f"/api/vehicles/{vin}/unarchive",
            headers=auth_headers,
        )

        assert response.status_code == 400

    async def test_unarchive_nonexistent_vin(self, client: AsyncClient, auth_headers):
        """Unarchiving a nonexistent vehicle returns 404."""
        response = await client.post(
            "/api/vehicles/00000000000000000/unarchive",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_unarchive_vehicle_non_owner_forbidden(
        self, client: AsyncClient, non_admin_headers, auth_headers, db_session, test_user
    ):
        """Non-owner cannot unarchive another user's vehicle."""
        vin = "1HGCM82633A888808"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        # Archive as owner
        await client.post(
            f"/api/vehicles/{vin}/archive",
            json={"reason": "Sold"},
            headers=auth_headers,
        )

        # Attempt unarchive as non-owner
        response = await client.post(
            f"/api/vehicles/{vin}/unarchive",
            headers=non_admin_headers,
        )

        assert response.status_code == 403

    async def test_toggle_archive_visibility_hidden(
        self, client: AsyncClient, auth_headers, db_session, test_user
    ):
        """Toggle archived vehicle visibility to hidden."""
        vin = "1HGCM82633A888809"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        # Archive first
        await client.post(
            f"/api/vehicles/{vin}/archive",
            json={"reason": "Sold"},
            headers=auth_headers,
        )

        # Set visibility to false
        response = await client.patch(
            f"/api/vehicles/{vin}/archive/visibility",
            params={"visible": False},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["archived_visible"] is False

    async def test_toggle_archive_visibility_visible(
        self, client: AsyncClient, auth_headers, db_session, test_user
    ):
        """Toggle archived vehicle visibility back to visible."""
        vin = "1HGCM82633A888810"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        # Archive with visible=False
        await client.post(
            f"/api/vehicles/{vin}/archive",
            json={"reason": "Sold", "visible": False},
            headers=auth_headers,
        )

        # Set visibility to true
        response = await client.patch(
            f"/api/vehicles/{vin}/archive/visibility",
            params={"visible": True},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["archived_visible"] is True

    async def test_toggle_visibility_non_archived_vehicle(
        self, client: AsyncClient, auth_headers, db_session, test_user
    ):
        """Toggling visibility on a non-archived vehicle returns 400."""
        vin = "1HGCM82633A888811"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        response = await client.patch(
            f"/api/vehicles/{vin}/archive/visibility",
            params={"visible": False},
            headers=auth_headers,
        )

        assert response.status_code == 400

    async def test_toggle_visibility_nonexistent_vin(self, client: AsyncClient, auth_headers):
        """Toggling visibility on a nonexistent vehicle returns 404."""
        response = await client.patch(
            "/api/vehicles/00000000000000000/archive/visibility",
            params={"visible": False},
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_toggle_visibility_non_owner_forbidden(
        self, client: AsyncClient, non_admin_headers, auth_headers, db_session, test_user
    ):
        """Non-owner cannot toggle archive visibility on another user's vehicle."""
        vin = "1HGCM82633A888812"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        # Archive as owner
        await client.post(
            f"/api/vehicles/{vin}/archive",
            json={"reason": "Sold"},
            headers=auth_headers,
        )

        # Attempt visibility toggle as non-owner
        response = await client.patch(
            f"/api/vehicles/{vin}/archive/visibility",
            params={"visible": False},
            headers=non_admin_headers,
        )

        assert response.status_code == 403

    async def test_archive_invalid_reason(
        self, client: AsyncClient, auth_headers, db_session, test_user
    ):
        """Archive with an invalid reason is rejected with 422."""
        vin = "1HGCM82633A888813"
        await self._create_archivable_vehicle(db_session, test_user["id"], vin)

        response = await client.post(
            f"/api/vehicles/{vin}/archive",
            json={"reason": "Stolen"},  # Not in valid reasons list
            headers=auth_headers,
        )

        assert response.status_code == 422
