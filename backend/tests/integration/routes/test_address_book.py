"""
Integration tests for address book routes.

Tests address book CRUD operations.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestAddressBookRoutes:
    """Test address book API endpoints."""

    async def test_list_entries(self, client: AsyncClient, auth_headers):
        """Test listing address book entries."""
        response = await client.get("/api/address-book", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert "total" in data
        assert isinstance(data["entries"], list)

    async def test_create_entry(self, client: AsyncClient, auth_headers):
        """Test creating a new address book entry."""
        payload = {
            "name": "John Smith",
            "business_name": "Smith Auto Repair",
            "address": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip_code": "62701",
            "phone": "555-123-4567",
            "email": "john@smithauto.com",
            "website": "https://smithauto.com",
            "category": "service",
            "notes": "Great service, reasonable prices.",
        }
        response = await client.post(
            "/api/address-book",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == payload["name"]
        assert data["business_name"] == payload["business_name"]
        assert data["city"] == payload["city"]
        assert "id" in data

    async def test_get_entry_by_id(self, client: AsyncClient, auth_headers):
        """Test retrieving a specific address book entry."""
        # Create an entry
        create_response = await client.post(
            "/api/address-book",
            json={
                "business_name": "Test Shop",
                "city": "Test City",
                "category": "service",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        # Get the entry
        response = await client.get(
            f"/api/address-book/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        assert data["business_name"] == "Test Shop"

    async def test_update_entry(self, client: AsyncClient, auth_headers):
        """Test updating an address book entry."""
        # Create an entry
        create_response = await client.post(
            "/api/address-book",
            json={
                "business_name": "Original Name",
                "city": "Original City",
                "category": "parts",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update the entry
        update_data = {
            "business_name": "Updated Name",
            "city": "Updated City",
            "phone": "555-999-8888",
        }

        response = await client.put(
            f"/api/address-book/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["business_name"] == "Updated Name"
        assert data["city"] == "Updated City"
        assert data["phone"] == "555-999-8888"
        # Category unchanged
        assert data["category"] == "parts"

    async def test_delete_entry(self, client: AsyncClient, auth_headers):
        """Test deleting an address book entry."""
        # Create an entry
        create_response = await client.post(
            "/api/address-book",
            json={
                "business_name": "To Be Deleted",
                "city": "Deleteville",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Delete the entry
        response = await client.delete(
            f"/api/address-book/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/address-book/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_entry_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot access address book."""
        response = await client.get("/api/address-book")

        assert response.status_code == 401

    async def test_entry_not_found(self, client: AsyncClient, auth_headers):
        """Test get entry with non-existent ID."""
        response = await client.get(
            "/api/address-book/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_search_entries(self, client: AsyncClient, auth_headers):
        """Test searching address book entries."""
        # Create entries with different names
        await client.post(
            "/api/address-book",
            json={"business_name": "Acme Auto Parts", "city": "Chicago"},
            headers=auth_headers,
        )
        await client.post(
            "/api/address-book",
            json={"business_name": "Best Tire Shop", "city": "Chicago"},
            headers=auth_headers,
        )

        # Search for "Acme"
        response = await client.get(
            "/api/address-book",
            params={"search": "Acme"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Should find the Acme entry
        matching = [e for e in data["entries"] if "Acme" in e.get("business_name", "")]
        assert len(matching) >= 1

    async def test_filter_by_category(self, client: AsyncClient, auth_headers):
        """Test filtering entries by category."""
        # Create entries with different categories
        await client.post(
            "/api/address-book",
            json={"business_name": "Service Shop A", "category": "service"},
            headers=auth_headers,
        )
        await client.post(
            "/api/address-book",
            json={"business_name": "Parts Store B", "category": "parts"},
            headers=auth_headers,
        )

        # Filter by category
        response = await client.get(
            "/api/address-book",
            params={"category": "service"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All results should have category "service"
        for entry in data["entries"]:
            assert entry.get("category") == "service"

    async def test_create_minimal_entry(self, client: AsyncClient, auth_headers):
        """Test creating entry with minimal fields."""
        payload = {
            "business_name": "Minimal Entry",
        }
        response = await client.post(
            "/api/address-book",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["business_name"] == "Minimal Entry"
        assert data["name"] is None
        assert data["city"] is None

    async def test_update_partial(self, client: AsyncClient, auth_headers):
        """Test partial update of entry."""
        # Create an entry
        create_response = await client.post(
            "/api/address-book",
            json={
                "business_name": "Full Entry",
                "city": "Full City",
                "state": "FC",
                "phone": "111-222-3333",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update only phone
        response = await client.put(
            f"/api/address-book/{record['id']}",
            json={"phone": "999-888-7777"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Only phone changed
        assert data["phone"] == "999-888-7777"
        # Others unchanged
        assert data["business_name"] == "Full Entry"
        assert data["city"] == "Full City"
        assert data["state"] == "FC"

    async def test_delete_not_found(self, client: AsyncClient, auth_headers):
        """Test deleting non-existent entry."""
        response = await client.delete(
            "/api/address-book/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_update_not_found(self, client: AsyncClient, auth_headers):
        """Test updating non-existent entry."""
        response = await client.put(
            "/api/address-book/99999",
            json={"business_name": "Does Not Exist"},
            headers=auth_headers,
        )

        assert response.status_code == 404
