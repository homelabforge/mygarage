"""
Integration tests for toll routes.

Tests toll tag and toll transaction CRUD operations, filtering, summary, and CSV export.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestTollTagRoutes:
    """Test toll tag API endpoints."""

    async def test_list_toll_tags(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing toll tags for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "toll_tags" in data
        assert "total" in data
        assert isinstance(data["toll_tags"], list)

    async def test_create_toll_tag(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a new toll tag."""
        payload = {
            "vin": test_vehicle["vin"],
            "toll_system": "EZ TAG",
            "tag_number": "0012345678",
            "status": "active",
            "notes": "Primary toll tag",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["toll_system"] == "EZ TAG"
        assert data["tag_number"] == "0012345678"
        assert data["status"] == "active"
        assert data["notes"] == "Primary toll tag"
        assert "id" in data
        assert "created_at" in data

    async def test_create_toll_tag_normalize_system(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that toll system names are normalized."""
        payload = {
            "vin": test_vehicle["vin"],
            "toll_system": "eztag",  # lowercase, no space
            "tag_number": "0012345679",
            "status": "active",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["toll_system"] == "EZ TAG"  # Should be normalized

    async def test_get_toll_tag_by_id(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific toll tag."""
        # Create a toll tag first
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags",
            json={
                "vin": test_vehicle["vin"],
                "toll_system": "TxTag",
                "tag_number": "TX12345",
                "status": "active",
            },
            headers=auth_headers,
        )
        tag = create_response.json()

        # Get the toll tag
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags/{tag['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == tag["id"]
        assert data["toll_system"] == "TxTag"
        assert data["tag_number"] == "TX12345"

    async def test_update_toll_tag(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating a toll tag."""
        # Create a toll tag
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags",
            json={
                "vin": test_vehicle["vin"],
                "toll_system": "E-ZPass",
                "tag_number": "EZ001",
                "status": "active",
            },
            headers=auth_headers,
        )
        tag = create_response.json()

        # Update the toll tag
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags/{tag['id']}",
            json={"status": "inactive", "notes": "Deactivated - lost tag"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "inactive"
        assert data["notes"] == "Deactivated - lost tag"
        assert data["toll_system"] == "E-ZPass"  # Unchanged

    async def test_delete_toll_tag(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting a toll tag."""
        # Create a toll tag
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags",
            json={
                "vin": test_vehicle["vin"],
                "toll_system": "SunPass",
                "tag_number": "SP12345",
                "status": "active",
            },
            headers=auth_headers,
        )
        tag = create_response.json()

        # Delete the toll tag
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags/{tag['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags/{tag['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_toll_tag_invalid_status(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating toll tag with invalid status."""
        payload = {
            "vin": test_vehicle["vin"],
            "toll_system": "EZ TAG",
            "tag_number": "0012345680",
            "status": "invalid_status",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 422

    async def test_toll_tag_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test getting non-existent toll tag."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_toll_tag_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test toll tag with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/1HGBH000000000000/toll-tags",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_toll_tag_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access toll tags."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/toll-tags")

        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
class TestTollTransactionRoutes:
    """Test toll transaction API endpoints."""

    async def test_list_toll_transactions(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing toll transactions for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "transactions" in data
        assert "total" in data
        assert isinstance(data["transactions"], list)

    async def test_create_toll_transaction(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a new toll transaction."""
        payload = {
            "vin": test_vehicle["vin"],
            "transaction_date": "2024-06-15",
            "amount": 2.50,
            "location": "Hardy Toll Road - Spring",
            "notes": "Morning commute",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert float(data["amount"]) == 2.50
        assert data["location"] == "Hardy Toll Road - Spring"
        assert data["notes"] == "Morning commute"
        assert "id" in data
        assert "created_at" in data

    async def test_create_toll_transaction_with_tag(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test creating a toll transaction with associated toll tag."""
        # Create a toll tag first
        tag_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags",
            json={
                "vin": test_vehicle["vin"],
                "toll_system": "EZ TAG",
                "tag_number": "TAG001",
                "status": "active",
            },
            headers=auth_headers,
        )
        tag = tag_response.json()

        # Create a transaction linked to the tag
        payload = {
            "vin": test_vehicle["vin"],
            "transaction_date": "2024-06-15",
            "amount": 3.75,
            "location": "Beltway 8 - West",
            "toll_tag_id": tag["id"],
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["toll_tag_id"] == tag["id"]

    async def test_create_toll_transaction_invalid_tag(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test creating a toll transaction with non-existent toll tag."""
        payload = {
            "vin": test_vehicle["vin"],
            "transaction_date": "2024-06-15",
            "amount": 2.00,
            "location": "Test Plaza",
            "toll_tag_id": 99999,
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 404
        assert "Toll tag not found" in response.json()["detail"]

    async def test_get_toll_transaction_by_id(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test retrieving a specific toll transaction."""
        # Create a transaction first
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-06-16",
                "amount": 1.50,
                "location": "Sam Houston Tollway",
            },
            headers=auth_headers,
        )
        transaction = create_response.json()

        # Get the transaction
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions/{transaction['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == transaction["id"]
        assert float(data["amount"]) == 1.50
        assert data["location"] == "Sam Houston Tollway"

    async def test_update_toll_transaction(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating a toll transaction."""
        # Create a transaction
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-06-17",
                "amount": 2.00,
                "location": "I-10 Katy Tollway",
            },
            headers=auth_headers,
        )
        transaction = create_response.json()

        # Update the transaction
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions/{transaction['id']}",
            json={"amount": 2.50, "notes": "Updated amount"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert float(data["amount"]) == 2.50
        assert data["notes"] == "Updated amount"
        assert data["location"] == "I-10 Katy Tollway"  # Unchanged

    async def test_delete_toll_transaction(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting a toll transaction."""
        # Create a transaction
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-06-18",
                "amount": 1.75,
                "location": "Westpark Tollway",
            },
            headers=auth_headers,
        )
        transaction = create_response.json()

        # Delete the transaction
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions/{transaction['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions/{transaction['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_list_toll_transactions_with_date_filter(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test listing toll transactions with date filters."""
        # Create transactions with different dates
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-01-15",
                "amount": 2.00,
                "location": "Plaza A",
            },
            headers=auth_headers,
        )
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-06-15",
                "amount": 3.00,
                "location": "Plaza B",
            },
            headers=auth_headers,
        )

        # Filter by date range
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            params={"start_date": "2024-06-01", "end_date": "2024-06-30"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All returned transactions should be in June
        # The response uses 'date' key (from model field name via alias)
        for txn in data["transactions"]:
            assert txn["date"].startswith("2024-06")

    async def test_list_toll_transactions_with_tag_filter(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test listing toll transactions filtered by toll tag."""
        # Create a toll tag
        tag_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags",
            json={
                "vin": test_vehicle["vin"],
                "toll_system": "EZ TAG",
                "tag_number": "FILTER001",
                "status": "active",
            },
            headers=auth_headers,
        )
        tag = tag_response.json()

        # Create transactions with and without tag
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-07-01",
                "amount": 2.50,
                "location": "Plaza With Tag",
                "toll_tag_id": tag["id"],
            },
            headers=auth_headers,
        )
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-07-02",
                "amount": 5.00,
                "location": "Plaza Without Tag",
            },
            headers=auth_headers,
        )

        # Filter by toll tag
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            params={"toll_tag_id": tag["id"]},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All returned transactions should have the specified tag
        for txn in data["transactions"]:
            assert txn["toll_tag_id"] == tag["id"]

    async def test_toll_transaction_summary(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test getting toll transaction summary statistics."""
        # Create some transactions
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-08-01",
                "amount": 5.00,
                "location": "Plaza 1",
            },
            headers=auth_headers,
        )
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-08-15",
                "amount": 7.50,
                "location": "Plaza 2",
            },
            headers=auth_headers,
        )

        # Get summary
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions/summary/statistics",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "total_transactions" in data
        assert "total_amount" in data
        assert "monthly_totals" in data
        assert data["total_transactions"] >= 2
        assert float(data["total_amount"]) >= 12.50

    async def test_toll_transaction_csv_export(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test exporting toll transactions as CSV."""
        # Create some transactions
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-09-01",
                "amount": 3.25,
                "location": "Export Test Plaza",
            },
            headers=auth_headers,
        )

        # Export to CSV
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions/export/csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")
        content_disp = response.headers.get("content-disposition", "")
        assert "attachment" in content_disp
        assert ".csv" in content_disp

        # Verify CSV content
        content = response.content.decode("utf-8")
        assert "Date" in content
        assert "Amount" in content
        assert "Location" in content

    async def test_toll_transaction_csv_export_with_date_filter(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test exporting toll transactions CSV with date filters."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions/export/csv",
            params={"start_date": "2024-01-01", "end_date": "2024-12-31"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    async def test_toll_transaction_not_found(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test getting non-existent toll transaction."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_toll_transaction_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test toll transaction with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/1HGBH000000000000/toll-transactions",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_toll_transaction_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access toll transactions."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/toll-transactions")

        assert response.status_code == 401

    async def test_toll_transaction_negative_amount(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test creating toll transaction with negative amount."""
        payload = {
            "vin": test_vehicle["vin"],
            "transaction_date": "2024-06-20",
            "amount": -5.00,
            "location": "Test Plaza",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_toll_transaction_summary_empty(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test summary statistics with no transactions."""
        # Get summary (vehicle has various transactions from other tests,
        # but this tests the structure is valid)
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions/summary/statistics",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "total_transactions" in data
        assert "total_amount" in data
        assert "monthly_totals" in data
        assert isinstance(data["monthly_totals"], list)

    async def test_update_toll_transaction_with_new_tag(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test updating toll transaction to link to a different tag."""
        # Create two toll tags
        tag1_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags",
            json={
                "vin": test_vehicle["vin"],
                "toll_system": "EZ TAG",
                "tag_number": "TAG_A",
                "status": "active",
            },
            headers=auth_headers,
        )
        tag1 = tag1_response.json()

        tag2_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-tags",
            json={
                "vin": test_vehicle["vin"],
                "toll_system": "EZ TAG",
                "tag_number": "TAG_B",
                "status": "active",
            },
            headers=auth_headers,
        )
        tag2 = tag2_response.json()

        # Create transaction with first tag
        txn_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-10-01",
                "amount": 2.00,
                "location": "Update Tag Test",
                "toll_tag_id": tag1["id"],
            },
            headers=auth_headers,
        )
        txn = txn_response.json()

        # Update to second tag
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions/{txn['id']}",
            json={"toll_tag_id": tag2["id"]},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["toll_tag_id"] == tag2["id"]

    async def test_update_toll_transaction_invalid_tag(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test updating toll transaction with non-existent tag."""
        # Create a transaction
        txn_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions",
            json={
                "vin": test_vehicle["vin"],
                "transaction_date": "2024-10-02",
                "amount": 3.00,
                "location": "Invalid Tag Update Test",
            },
            headers=auth_headers,
        )
        txn = txn_response.json()

        # Try to update with non-existent tag
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/toll-transactions/{txn['id']}",
            json={"toll_tag_id": 99999},
            headers=auth_headers,
        )

        assert response.status_code == 404
        assert "Toll tag not found" in response.json()["detail"]
