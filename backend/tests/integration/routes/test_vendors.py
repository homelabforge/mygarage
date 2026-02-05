"""
Integration tests for vendor routes.

Tests vendor CRUD operations and search functionality.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestVendorRoutes:
    """Test vendor API endpoints."""

    async def test_list_vendors(self, client: AsyncClient, auth_headers):
        """Test listing vendors."""
        response = await client.get(
            "/api/vendors",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "vendors" in data
        assert "total" in data
        assert isinstance(data["vendors"], list)

    async def test_get_vendor_by_id(self, client: AsyncClient, auth_headers):
        """Test retrieving a specific vendor."""
        # First create a vendor
        create_response = await client.post(
            "/api/vendors",
            json={
                "name": "Test Garage",
                "address": "123 Main St",
                "city": "Austin",
                "state": "TX",
                "zip_code": "78701",
                "phone": "(512) 555-1234",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        vendor = create_response.json()

        # Get the vendor
        response = await client.get(
            f"/api/vendors/{vendor['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == vendor["id"]
        assert data["name"] == "Test Garage"
        assert data["city"] == "Austin"

    async def test_create_vendor(self, client: AsyncClient, auth_headers):
        """Test creating a new vendor."""
        payload = {
            "name": "New Auto Shop",
            "address": "456 Oak Ave",
            "city": "Dallas",
            "state": "TX",
            "zip_code": "75201",
            "phone": "(214) 555-5678",
        }
        response = await client.post(
            "/api/vendors",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == payload["name"]
        assert data["city"] == payload["city"]
        assert "id" in data
        assert "created_at" in data
        assert "full_address" in data

    async def test_update_vendor(self, client: AsyncClient, auth_headers):
        """Test updating a vendor."""
        # Create a vendor
        create_response = await client.post(
            "/api/vendors",
            json={
                "name": "Update Test Vendor",
                "city": "Houston",
                "state": "TX",
            },
            headers=auth_headers,
        )
        vendor = create_response.json()

        # Update the vendor
        update_data = {
            "phone": "(713) 555-9999",
            "address": "789 Updated St",
        }

        response = await client.put(
            f"/api/vendors/{vendor['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["phone"] == "(713) 555-9999"
        assert data["address"] == "789 Updated St"

    async def test_delete_vendor(self, client: AsyncClient, auth_headers):
        """Test deleting a vendor."""
        # Create a vendor
        create_response = await client.post(
            "/api/vendors",
            json={
                "name": "Vendor To Delete",
                "city": "San Antonio",
                "state": "TX",
            },
            headers=auth_headers,
        )
        vendor = create_response.json()

        # Delete the vendor
        response = await client.delete(
            f"/api/vendors/{vendor['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vendors/{vendor['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_vendor_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot access vendors."""
        response = await client.get("/api/vendors")

        assert response.status_code == 401

    async def test_create_vendor_validation(self, client: AsyncClient, auth_headers):
        """Test that invalid vendors are rejected."""
        # Name is required and min length 1
        invalid_payload = {
            "name": "",  # Empty name should fail
            "city": "Test City",
        }

        response = await client.post(
            "/api/vendors",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_vendor_not_found(self, client: AsyncClient, auth_headers):
        """Test get vendor with non-existent ID."""
        response = await client.get(
            "/api/vendors/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_create_vendor_minimal(self, client: AsyncClient, auth_headers):
        """Test creating a vendor with minimal required fields."""
        payload = {
            "name": "Minimal Vendor",
        }
        response = await client.post(
            "/api/vendors",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Minimal Vendor"
        assert data["address"] is None
        assert data["city"] is None
        assert data["phone"] is None

    async def test_vendor_search(self, client: AsyncClient, auth_headers):
        """Test vendor search functionality."""
        # Create vendors with distinct names
        await client.post(
            "/api/vendors",
            json={"name": "Searchable Auto Shop"},
            headers=auth_headers,
        )
        await client.post(
            "/api/vendors",
            json={"name": "Another Place"},
            headers=auth_headers,
        )

        # Search for "Searchable"
        response = await client.get(
            "/api/vendors?search=Searchable",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All results should contain "Searchable" in name
        for vendor in data["vendors"]:
            assert "searchable" in vendor["name"].lower()

    async def test_vendor_pagination(self, client: AsyncClient, auth_headers):
        """Test vendor pagination."""
        # Create multiple vendors
        for i in range(10):
            await client.post(
                "/api/vendors",
                json={"name": f"Pagination Test Vendor {i}"},
                headers=auth_headers,
            )

        # Test pagination with limit
        response = await client.get(
            "/api/vendors?skip=0&limit=5",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["vendors"]) <= 5

    async def test_update_vendor_partial(self, client: AsyncClient, auth_headers):
        """Test partial update of vendor."""
        # Create a vendor
        create_response = await client.post(
            "/api/vendors",
            json={
                "name": "Partial Update Vendor",
                "city": "El Paso",
                "state": "TX",
                "phone": "(915) 555-1111",
            },
            headers=auth_headers,
        )
        vendor = create_response.json()

        # Update only city
        response = await client.put(
            f"/api/vendors/{vendor['id']}",
            json={"city": "Fort Worth"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Original name unchanged
        assert data["name"] == "Partial Update Vendor"
        # Phone unchanged
        assert data["phone"] == "(915) 555-1111"
        # City updated
        assert data["city"] == "Fort Worth"

    async def test_vendor_full_address(self, client: AsyncClient, auth_headers):
        """Test that full_address is computed correctly."""
        payload = {
            "name": "Full Address Test",
            "address": "100 Commerce St",
            "city": "Dallas",
            "state": "TX",
            "zip_code": "75202",
        }
        response = await client.post(
            "/api/vendors",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["full_address"] is not None
        # Full address should contain the components
        assert "100 Commerce St" in data["full_address"]
        assert "Dallas" in data["full_address"]

    async def test_vendor_price_history_empty(self, client: AsyncClient, auth_headers):
        """Test getting price history for vendor with no history."""
        # Create a vendor
        create_response = await client.post(
            "/api/vendors",
            json={"name": "No History Vendor"},
            headers=auth_headers,
        )
        vendor = create_response.json()

        # Get price history
        response = await client.get(
            f"/api/vendors/{vendor['id']}/price-history",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vendor_id"] == vendor["id"]
        assert data["vendor_name"] == "No History Vendor"
        assert data["history"] == []
        assert data["average_cost"] is None

    async def test_create_duplicate_vendor_name(self, client: AsyncClient, auth_headers):
        """Test that duplicate vendor names are rejected."""
        # Create first vendor
        await client.post(
            "/api/vendors",
            json={"name": "Unique Vendor Name"},
            headers=auth_headers,
        )

        # Try to create another with same name
        response = await client.post(
            "/api/vendors",
            json={"name": "Unique Vendor Name"},
            headers=auth_headers,
        )

        assert response.status_code == 409  # Conflict
