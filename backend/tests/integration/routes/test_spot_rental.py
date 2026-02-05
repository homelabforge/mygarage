"""
Integration tests for spot rental routes.

Tests spot rental CRUD operations and billing management for RV/Fifth Wheel vehicles.
"""

import uuid

import pytest
from httpx import AsyncClient


def generate_vin(prefix: str = "RV") -> str:
    """Generate a unique 17-character VIN for testing."""
    # Use UUID to generate unique suffix - need exactly 17 chars
    unique_id = uuid.uuid4().hex[:12].upper()  # 12 chars from UUID
    return f"1HG{prefix}{unique_id}"[:17]  # 1HG (3) + prefix (2) + 12 = 17


@pytest.fixture
async def rv_vehicle(client: AsyncClient, auth_headers):
    """Create an RV vehicle for spot rental tests."""
    vin = generate_vin("RV")
    payload = {
        "vin": vin,
        "nickname": "Test RV",
        "vehicle_type": "RV",  # Case-sensitive: must match enum
        "year": 2022,
        "make": "Winnebago",
        "model": "View",
    }
    response = await client.post(
        "/api/vehicles",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 201, f"Failed to create RV: {response.json()}"
    return response.json()


@pytest.fixture
async def fifth_wheel_vehicle(client: AsyncClient, auth_headers):
    """Create a Fifth Wheel vehicle for spot rental tests."""
    vin = generate_vin("FW")
    payload = {
        "vin": vin,
        "nickname": "Test Fifth Wheel",
        "vehicle_type": "FifthWheel",  # Case-sensitive: must match enum
        "year": 2021,
        "make": "Grand Design",
        "model": "Solitude",
    }
    response = await client.post(
        "/api/vehicles",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 201, f"Failed to create Fifth Wheel: {response.json()}"
    return response.json()


@pytest.mark.integration
@pytest.mark.asyncio
class TestSpotRentalRoutes:
    """Test spot rental API endpoints."""

    async def test_list_spot_rentals(self, client: AsyncClient, auth_headers, rv_vehicle):
        """Test listing spot rentals for an RV vehicle."""
        response = await client.get(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "spot_rentals" in data
        assert "total" in data
        assert isinstance(data["spot_rentals"], list)

    async def test_create_spot_rental(self, client: AsyncClient, auth_headers, rv_vehicle):
        """Test creating a new spot rental."""
        payload = {
            "location_name": "Sunny RV Park",
            "location_address": "123 Sunny Road, Austin, TX",
            "check_in_date": "2024-06-01",
            "check_out_date": "2024-06-30",
            "monthly_rate": 750.00,
            "electric": 50.00,
            "water": 25.00,
            "waste": 15.00,
            "amenities": "Pool, WiFi, Laundry",
            "notes": "Site #42",
        }
        response = await client.post(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["location_name"] == "Sunny RV Park"
        assert data["location_address"] == "123 Sunny Road, Austin, TX"
        assert float(data["monthly_rate"]) == 750.00
        assert float(data["electric"]) == 50.00
        assert "id" in data
        assert "created_at" in data
        # Should auto-create a billing entry when monthly_rate is provided
        assert len(data["billings"]) == 1

    async def test_create_spot_rental_fifth_wheel(
        self, client: AsyncClient, auth_headers, fifth_wheel_vehicle
    ):
        """Test creating a spot rental for a Fifth Wheel vehicle."""
        payload = {
            "location_name": "Mountain View RV Resort",
            "check_in_date": "2024-07-01",
            "nightly_rate": 45.00,
        }
        response = await client.post(
            f"/api/vehicles/{fifth_wheel_vehicle['vin']}/spot-rentals",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["location_name"] == "Mountain View RV Resort"
        assert float(data["nightly_rate"]) == 45.00

    async def test_create_spot_rental_non_rv_fails(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that creating a spot rental fails for non-RV vehicles."""
        payload = {
            "location_name": "Test Park",
            "check_in_date": "2024-06-01",
            "monthly_rate": 500.00,
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/spot-rentals",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "only available for RVs and Fifth Wheels" in response.json()["detail"]

    async def test_get_spot_rental_by_id(self, client: AsyncClient, auth_headers, rv_vehicle):
        """Test retrieving a specific spot rental."""
        # Create a rental first
        create_response = await client.post(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals",
            json={
                "location_name": "Lake View Park",
                "check_in_date": "2024-08-01",
                "weekly_rate": 300.00,
            },
            headers=auth_headers,
        )
        rental = create_response.json()

        # Get the rental
        response = await client.get(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{rental['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == rental["id"]
        assert data["location_name"] == "Lake View Park"

    async def test_update_spot_rental(self, client: AsyncClient, auth_headers, rv_vehicle):
        """Test updating a spot rental."""
        # Create a rental
        create_response = await client.post(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals",
            json={
                "location_name": "Original Park",
                "check_in_date": "2024-09-01",
                "monthly_rate": 600.00,
            },
            headers=auth_headers,
        )
        rental = create_response.json()

        # Update the rental
        response = await client.put(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{rental['id']}",
            json={
                "location_name": "Updated Park",
                "check_out_date": "2024-09-30",
                "notes": "Extended stay",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["location_name"] == "Updated Park"
        assert data["check_out_date"] == "2024-09-30"
        assert data["notes"] == "Extended stay"
        assert float(data["monthly_rate"]) == 600.00  # Unchanged

    async def test_delete_spot_rental(self, client: AsyncClient, auth_headers, rv_vehicle):
        """Test deleting a spot rental."""
        # Create a rental
        create_response = await client.post(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals",
            json={
                "location_name": "Delete Test Park",
                "check_in_date": "2024-10-01",
                "nightly_rate": 35.00,
            },
            headers=auth_headers,
        )
        rental = create_response.json()

        # Delete the rental
        response = await client.delete(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{rental['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{rental['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_spot_rental_not_found(self, client: AsyncClient, auth_headers, rv_vehicle):
        """Test getting non-existent spot rental."""
        response = await client.get(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_spot_rental_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test spot rental with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/1HGBH000000000000/spot-rentals",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_spot_rental_unauthorized(self, client: AsyncClient, rv_vehicle):
        """Test that unauthenticated users cannot access spot rentals."""
        response = await client.get(f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals")

        assert response.status_code == 401

    async def test_create_spot_rental_no_auto_billing(
        self, client: AsyncClient, auth_headers, rv_vehicle
    ):
        """Test creating spot rental without monthly rate doesn't auto-create billing."""
        payload = {
            "location_name": "Daily Rate Park",
            "check_in_date": "2024-11-01",
            "nightly_rate": 40.00,  # No monthly_rate
        }
        response = await client.post(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        # Should not auto-create billing without monthly_rate
        assert len(data["billings"]) == 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestSpotRentalBillingRoutes:
    """Test spot rental billing API endpoints."""

    @pytest.fixture
    async def spot_rental(self, client: AsyncClient, auth_headers, rv_vehicle):
        """Create a spot rental for billing tests."""
        response = await client.post(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals",
            json={
                "location_name": "Billing Test Park",
                "check_in_date": "2024-01-01",
                "check_out_date": "2024-12-31",
                "nightly_rate": 50.00,  # No monthly_rate to avoid auto-billing
            },
            headers=auth_headers,
        )
        return response.json()

    async def test_list_billings(self, client: AsyncClient, auth_headers, rv_vehicle, spot_rental):
        """Test listing billing entries for a spot rental."""
        response = await client.get(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "billings" in data
        assert "total" in data
        assert isinstance(data["billings"], list)

    async def test_create_billing(self, client: AsyncClient, auth_headers, rv_vehicle, spot_rental):
        """Test creating a new billing entry."""
        payload = {
            "billing_date": "2024-02-01",
            "monthly_rate": 800.00,
            "electric": 75.50,
            "water": 30.00,
            "waste": 20.00,
            "total": 925.50,
            "notes": "February billing",
        }
        response = await client.post(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["billing_date"] == "2024-02-01"
        assert float(data["monthly_rate"]) == 800.00
        assert float(data["electric"]) == 75.50
        assert float(data["total"]) == 925.50
        assert data["notes"] == "February billing"
        assert "id" in data

    async def test_create_billing_before_check_in_fails(
        self, client: AsyncClient, auth_headers, rv_vehicle, spot_rental
    ):
        """Test that creating billing before check-in date fails."""
        payload = {
            "billing_date": "2023-12-01",  # Before check_in_date of 2024-01-01
            "monthly_rate": 750.00,
            "total": 750.00,
        }
        response = await client.post(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "before check-in date" in response.json()["detail"]

    async def test_create_billing_after_check_out_fails(
        self, client: AsyncClient, auth_headers, rv_vehicle, spot_rental
    ):
        """Test that creating billing after check-out date fails."""
        payload = {
            "billing_date": "2025-01-15",  # After check_out_date of 2024-12-31
            "monthly_rate": 750.00,
            "total": 750.00,
        }
        response = await client.post(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "after check-out date" in response.json()["detail"]

    async def test_update_billing(self, client: AsyncClient, auth_headers, rv_vehicle, spot_rental):
        """Test updating a billing entry."""
        # Create a billing entry first
        create_response = await client.post(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings",
            json={
                "billing_date": "2024-03-01",
                "monthly_rate": 700.00,
                "total": 700.00,
            },
            headers=auth_headers,
        )
        billing = create_response.json()

        # Update the billing
        response = await client.put(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings/{billing['id']}",
            json={
                "electric": 60.00,
                "total": 760.00,
                "notes": "Updated with electric",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert float(data["electric"]) == 60.00
        assert float(data["total"]) == 760.00
        assert data["notes"] == "Updated with electric"
        assert float(data["monthly_rate"]) == 700.00  # Unchanged

    async def test_delete_billing(self, client: AsyncClient, auth_headers, rv_vehicle, spot_rental):
        """Test deleting a billing entry."""
        # Create a billing entry
        create_response = await client.post(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings",
            json={
                "billing_date": "2024-04-01",
                "monthly_rate": 650.00,
                "total": 650.00,
            },
            headers=auth_headers,
        )
        billing = create_response.json()

        # Delete the billing
        response = await client.delete(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings/{billing['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted (list should not contain this billing)
        list_response = await client.get(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings",
            headers=auth_headers,
        )
        assert list_response.status_code == 200
        billings = list_response.json()["billings"]
        billing_ids = [b["id"] for b in billings]
        assert billing["id"] not in billing_ids

    async def test_billing_not_found(
        self, client: AsyncClient, auth_headers, rv_vehicle, spot_rental
    ):
        """Test getting non-existent billing entry."""
        response = await client.put(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings/99999",
            json={"notes": "test"},
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_billing_rental_not_found(self, client: AsyncClient, auth_headers, rv_vehicle):
        """Test billing with non-existent spot rental."""
        response = await client.get(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/99999/billings",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_billing_unauthorized(self, client: AsyncClient, rv_vehicle, spot_rental):
        """Test that unauthenticated users cannot access billings."""
        response = await client.get(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings"
        )

        assert response.status_code == 401

    async def test_multiple_billings(
        self, client: AsyncClient, auth_headers, rv_vehicle, spot_rental
    ):
        """Test creating multiple billing entries for a rental."""
        # Create multiple billing entries
        for month in range(5, 8):  # May, June, July
            await client.post(
                f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings",
                json={
                    "billing_date": f"2024-0{month}-01",
                    "monthly_rate": 700.00,
                    "total": 700.00,
                    "notes": f"Month {month} billing",
                },
                headers=auth_headers,
            )

        # List all billings
        response = await client.get(
            f"/api/vehicles/{rv_vehicle['vin']}/spot-rentals/{spot_rental['id']}/billings",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 3
        # Should be ordered by date descending (newest first)
        if len(data["billings"]) >= 2:
            assert data["billings"][0]["billing_date"] >= data["billings"][1]["billing_date"]
