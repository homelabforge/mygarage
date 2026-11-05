"""
Integration tests for warranty record routes.

Tests warranty record CRUD operations.

Every test writes on its own vehicle: warranties end years out, and on the
shared test_vehicle they'd outlive the run (the far-future leak guard).
"""

import datetime as dt
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.vehicle import Vehicle
from app.models.warranty import WarrantyRecord as WarrantyRecordModel
from app.schemas.service_visit import ServiceLineItemCreate, ServiceVisitCreate
from app.schemas.warranty import WarrantyRecordCreate
from app.services.service_visit_service import ServiceVisitService
from app.services.warranty_service import WarrantyService


@pytest.mark.integration
@pytest.mark.asyncio
class TestWarrantyRecordRoutes:
    """Test warranty record API endpoints."""

    async def test_list_warranties(self, client: AsyncClient, auth_headers, own_vehicle: Vehicle):
        """Test listing warranty records for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{own_vehicle.vin}/warranties",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_get_warranty_by_id(
        self, client: AsyncClient, auth_headers, own_vehicle: Vehicle
    ):
        """Test retrieving a specific warranty record."""
        # First create a warranty record
        create_response = await client.post(
            f"/api/vehicles/{own_vehicle.vin}/warranties",
            json={
                "warranty_type": "Powertrain",
                "provider": "Honda",
                "start_date": "2024-01-01",
                "end_date": "2029-01-01",
                "mileage_limit_km": 96560.4,
                "coverage_details": "Engine, transmission, drivetrain",
                "policy_number": "HND-PT-12345",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        # Get the warranty record
        response = await client.get(
            f"/api/vehicles/{own_vehicle.vin}/warranties/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        assert data["warranty_type"] == "Powertrain"
        assert float(data["mileage_limit_km"]) == 96560.4

    async def test_create_warranty(self, client: AsyncClient, auth_headers, own_vehicle: Vehicle):
        """Test creating a new warranty record."""
        payload = {
            "warranty_type": "Bumper-to-Bumper",
            "provider": "Honda",
            "start_date": datetime.now().date().isoformat(),
            "end_date": (datetime.now() + timedelta(days=365 * 3)).date().isoformat(),
            "mileage_limit_km": 57936.24,
            "coverage_details": "Comprehensive coverage excluding wear items",
            "notes": "Factory warranty",
        }
        response = await client.post(
            f"/api/vehicles/{own_vehicle.vin}/warranties",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["warranty_type"] == payload["warranty_type"]
        assert data["provider"] == payload["provider"]
        assert float(data["mileage_limit_km"]) == payload["mileage_limit_km"]
        assert "id" in data
        assert "created_at" in data

    async def test_update_warranty(self, client: AsyncClient, auth_headers, own_vehicle: Vehicle):
        """Test updating a warranty record."""
        # Create a warranty record
        create_response = await client.post(
            f"/api/vehicles/{own_vehicle.vin}/warranties",
            json={
                "warranty_type": "Extended",
                "start_date": "2024-01-01",
                "end_date": "2027-01-01",
                "mileage_limit_km": 160934.0,
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update the record
        update_data = {
            "mileage_limit_km": 201167.5,
            "notes": "Extended coverage purchased",
            "policy_number": "EXT-12345",
        }

        response = await client.put(
            f"/api/vehicles/{own_vehicle.vin}/warranties/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert float(data["mileage_limit_km"]) == 201167.5
        assert data["notes"] == "Extended coverage purchased"
        assert data["policy_number"] == "EXT-12345"

    async def test_delete_warranty(self, client: AsyncClient, auth_headers, own_vehicle: Vehicle):
        """Test deleting a warranty record."""
        # Create a warranty record
        create_response = await client.post(
            f"/api/vehicles/{own_vehicle.vin}/warranties",
            json={
                "warranty_type": "Corrosion",
                "start_date": "2024-01-01",
                "end_date": "2031-01-01",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Delete the record
        response = await client.delete(
            f"/api/vehicles/{own_vehicle.vin}/warranties/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{own_vehicle.vin}/warranties/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_warranty_unauthorized(self, client: AsyncClient, own_vehicle: Vehicle):
        """Test that unauthenticated users cannot access warranty records."""
        response = await client.get(f"/api/vehicles/{own_vehicle.vin}/warranties")

        assert response.status_code == 401

    async def test_create_warranty_validation(
        self, client: AsyncClient, auth_headers, own_vehicle: Vehicle
    ):
        """Test that invalid warranty records are rejected."""
        invalid_payload = {
            "warranty_type": "Test",
            "start_date": "2024-01-01",
            "mileage_limit_km": -1609.34,  # Negative mileage should fail
        }

        response = await client.post(
            f"/api/vehicles/{own_vehicle.vin}/warranties",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_warranty_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test warranty with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/warranties",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_warranty_record_not_found(
        self, client: AsyncClient, auth_headers, own_vehicle: Vehicle
    ):
        """Test get warranty with non-existent record ID."""
        response = await client.get(
            f"/api/vehicles/{own_vehicle.vin}/warranties/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_warranty_forbidden_non_owner(
        self, client: AsyncClient, non_admin_headers, own_vehicle: Vehicle
    ):
        """Test that non-owner users cannot access another user's warranties."""
        vin = own_vehicle.vin
        response = await client.get(
            f"/api/vehicles/{vin}/warranties",
            headers=non_admin_headers,
        )
        assert response.status_code == 403

    async def test_create_warranty_minimal(
        self, client: AsyncClient, auth_headers, own_vehicle: Vehicle
    ):
        """Test creating a warranty with minimal required fields."""
        payload = {
            "warranty_type": "Other",  # Must be valid: Manufacturer, Powertrain, Extended, Bumper-to-Bumper, Emissions, Corrosion, Other
            "start_date": "2024-06-01",
        }
        response = await client.post(
            f"/api/vehicles/{own_vehicle.vin}/warranties",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["warranty_type"] == "Other"
        assert data["provider"] is None
        assert data["end_date"] is None
        assert data["mileage_limit_km"] is None

    async def test_warranty_ordering(self, client: AsyncClient, auth_headers, own_vehicle: Vehicle):
        """Test that warranties are ordered by start_date descending."""
        # Create warranties out of order using valid types
        warranty_data = [
            ("2022-01-01", "Manufacturer"),
            ("2024-01-01", "Powertrain"),
            ("2023-01-01", "Emissions"),
        ]

        for date, warranty_type in warranty_data:
            await client.post(
                f"/api/vehicles/{own_vehicle.vin}/warranties",
                json={
                    "warranty_type": warranty_type,
                    "start_date": date,
                },
                headers=auth_headers,
            )

        # Get list
        response = await client.get(
            f"/api/vehicles/{own_vehicle.vin}/warranties",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Should be ordered by start_date descending
        if len(data) >= 2:
            for i in range(len(data) - 1):
                assert data[i]["start_date"] >= data[i + 1]["start_date"]

    async def test_update_warranty_partial(
        self, client: AsyncClient, auth_headers, own_vehicle: Vehicle
    ):
        """Test partial update of warranty record."""
        # Create a warranty record using a valid type
        create_response = await client.post(
            f"/api/vehicles/{own_vehicle.vin}/warranties",
            json={
                "warranty_type": "Extended",
                "provider": "Original Provider",
                "start_date": "2024-01-01",
                "end_date": "2027-01-01",
                "coverage_details": "Full coverage",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201, f"Create failed: {create_response.json()}"
        record = create_response.json()

        # Update only one field
        response = await client.put(
            f"/api/vehicles/{own_vehicle.vin}/warranties/{record['id']}",
            json={"notes": "Transferred from previous owner"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Original fields unchanged
        assert data["warranty_type"] == "Extended"
        assert data["provider"] == "Original Provider"
        assert data["coverage_details"] == "Full coverage"
        # New field added
        assert data["notes"] == "Transferred from previous owner"

    async def test_warranty_with_all_fields(
        self, client: AsyncClient, auth_headers, own_vehicle: Vehicle
    ):
        """Test creating a warranty with all optional fields populated."""
        payload = {
            "warranty_type": "Extended",  # Must be valid type
            "provider": "Third Party Warranty Co",
            "start_date": "2024-01-01",
            "end_date": "2030-01-01",
            "mileage_limit_km": 241401.0,
            "coverage_details": "Covers engine, transmission, drivetrain, electronics, A/C",
            "policy_number": "TPW-2024-12345-EXT",
            "notes": "Purchased at time of sale, transferable to new owner",
        }
        response = await client.post(
            f"/api/vehicles/{own_vehicle.vin}/warranties",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        for key, value in payload.items():
            if key == "mileage_limit_km":
                assert float(data[key]) == value
            else:
                assert data[key] == value


@pytest.mark.integration
@pytest.mark.asyncio
class TestWarrantyLinkedItems:
    async def test_list_get_and_update_carry_linked_items_newest_first(
        self, client: AsyncClient, auth_headers, own_vehicle: Vehicle
    ):
        vin = own_vehicle.vin
        r = await client.post(
            f"/api/vehicles/{vin}/warranties",
            json={"warranty_type": "Powertrain", "start_date": "2025-01-01"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        wid = r.json()["id"]
        assert r.json()["linked_items"] == []

        made: dict[str, tuple[int, int]] = {}
        for day, description, cost in (
            ("2026-10-01", "Water pump", "120.00"),
            ("2026-11-03", "Thermostat", "80.50"),
        ):
            r = await client.post(
                f"/api/vehicles/{vin}/service-visits",
                json={
                    "date": day,
                    "line_items": [
                        {
                            "description": description,
                            "cost": cost,
                            "is_warranty": True,
                            "warranty_id": wid,
                        },
                        {"description": f"{description} gasket", "cost": "5.00"},
                    ],
                },
                headers=auth_headers,
            )
            assert r.status_code == 201, r.text
            item = next(i for i in r.json()["line_items"] if i["description"] == description)
            made[description] = (r.json()["id"], item["id"])

        expected = [
            {
                "visit_id": made["Thermostat"][0],
                "line_item_id": made["Thermostat"][1],
                "date": "2026-11-03",
                "description": "Thermostat",
                "cost": "80.50",
            },
            {
                "visit_id": made["Water pump"][0],
                "line_item_id": made["Water pump"][1],
                "date": "2026-10-01",
                "description": "Water pump",
                "cost": "120.00",
            },
        ]

        r = await client.get(f"/api/vehicles/{vin}/warranties", headers=auth_headers)
        assert r.status_code == 200, r.text
        (listed,) = [w for w in r.json() if w["id"] == wid]
        assert listed["linked_items"] == expected

        r = await client.get(f"/api/vehicles/{vin}/warranties/{wid}", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["linked_items"] == expected

        r = await client.put(
            f"/api/vehicles/{vin}/warranties/{wid}",
            json={"notes": "Claim filed"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["linked_items"] == expected

    async def test_a_session_that_read_the_warranty_before_the_link_sees_it(
        self, db_session, test_sessionmaker, own_vehicle: Vehicle
    ):
        """Its copy was read with no links; another request linked an item since."""
        vin = own_vehicle.vin
        service = WarrantyService(db_session)
        made = await service.create_warranty(
            vin,
            WarrantyRecordCreate(warranty_type="Powertrain", start_date=dt.date(2025, 1, 1)),
            None,
        )
        # Hold the ORM copy, no links loaded, so the identity map keeps it.
        held = (
            await db_session.execute(
                select(WarrantyRecordModel)
                .options(selectinload(WarrantyRecordModel.linked_line_items))
                .where(WarrantyRecordModel.id == made.id)
            )
        ).scalar_one()
        assert held.linked_line_items == []
        async with test_sessionmaker() as other:
            visit = await ServiceVisitService(other).create_service_visit(
                vin,
                ServiceVisitCreate(
                    date=dt.date(2026, 11, 3),
                    line_items=[
                        ServiceLineItemCreate(
                            description="Thermostat", is_warranty=True, warranty_id=made.id
                        )
                    ],
                ),
                None,
            )
        got = await service.get_warranty(vin, made.id, None)
        assert [i.line_item_id for i in got.linked_items] == [visit.line_items[0].id]
