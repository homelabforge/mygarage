"""
Integration tests for tax/registration record routes.

Tests tax record CRUD operations.
"""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestTaxRecordRoutes:
    """Test tax record API endpoints."""

    async def test_list_tax_records(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing tax records for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "total" in data
        assert isinstance(data["records"], list)

    async def test_get_tax_record_by_id(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific tax record."""
        # First create a tax record
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-01-15",
                "tax_type": "Registration",
                "amount": 85.50,
                "renewal_date": "2025-01-15",
                "notes": "Annual registration",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        # Get the tax record
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        assert data["tax_type"] == "Registration"
        assert float(data["amount"]) == 85.50

    async def test_create_tax_record(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a new tax record."""
        payload = {
            "vin": test_vehicle["vin"],
            "date": datetime.now().date().isoformat(),
            "tax_type": "Inspection",
            "amount": 35.00,
            "notes": "Annual state inspection",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["tax_type"] == payload["tax_type"]
        assert float(data["amount"]) == payload["amount"]
        assert "id" in data
        assert "created_at" in data

    async def test_update_tax_record(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating a tax record."""
        # Create a tax record
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-02-01",
                "tax_type": "Property Tax",
                "amount": 150.00,
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update the record
        update_data = {
            "amount": 175.50,
            "notes": "Updated amount after assessment",
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert float(data["amount"]) == 175.50
        assert data["notes"] == "Updated amount after assessment"

    async def test_delete_tax_record(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting a tax record."""
        # Create a tax record
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-03-01",
                "tax_type": "Tolls",
                "amount": 25.00,
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Delete the record
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_tax_record_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access tax records."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/tax-records")

        assert response.status_code == 401

    async def test_create_tax_record_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that invalid tax records are rejected."""
        invalid_payload = {
            "vin": test_vehicle["vin"],
            "date": "2024-01-15",
            "tax_type": "Registration",
            "amount": -50.00,  # Negative amount should fail
        }

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_tax_record_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test tax records with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/tax-records",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_tax_record_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test get tax record with non-existent record ID."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_create_tax_record_with_renewal_date(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test creating a tax record with renewal date."""
        next_year = (datetime.now() + timedelta(days=365)).date().isoformat()
        payload = {
            "vin": test_vehicle["vin"],
            "date": datetime.now().date().isoformat(),
            "tax_type": "Registration",
            "amount": 95.00,
            "renewal_date": next_year,
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["renewal_date"] == next_year

    async def test_tax_record_ordering(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that tax records are ordered by date descending."""
        # Create records out of order
        dates = ["2022-01-01", "2024-01-01", "2023-01-01"]

        for date in dates:
            await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/tax-records",
                json={
                    "vin": test_vehicle["vin"],
                    "date": date,
                    "tax_type": "Registration",
                    "amount": 85.00,
                },
                headers=auth_headers,
            )

        # Get list
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        records = data["records"]

        # Should be ordered by date descending
        if len(records) >= 2:
            for i in range(len(records) - 1):
                assert records[i]["date"] >= records[i + 1]["date"]

    async def test_update_tax_record_partial(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test partial update of tax record."""
        # Create a tax record
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-04-01",
                "tax_type": "Inspection",
                "amount": 40.00,
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update only notes
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records/{record['id']}",
            json={"notes": "Passed inspection"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Original fields unchanged
        assert data["tax_type"] == "Inspection"
        assert float(data["amount"]) == 40.00
        # New field added
        assert data["notes"] == "Passed inspection"

    async def test_create_tax_record_vin_mismatch(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test creating tax record with mismatched VIN in body."""
        payload = {
            "vin": "DIFFERENTVIN12345",  # Different VIN than URL
            "date": "2024-05-01",
            "tax_type": "Registration",
            "amount": 100.00,
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/tax-records",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 400

    async def test_tax_type_options(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating tax records with all valid tax types."""
        tax_types = ["Registration", "Inspection", "Property Tax", "Tolls"]

        for i, tax_type in enumerate(tax_types):
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/tax-records",
                json={
                    "vin": test_vehicle["vin"],
                    "date": f"2024-0{i + 1}-01",
                    "tax_type": tax_type,
                    "amount": 50.00 + i * 10,
                },
                headers=auth_headers,
            )
            assert response.status_code == 201, f"Failed for tax_type: {tax_type}"
            data = response.json()
            assert data["tax_type"] == tax_type
