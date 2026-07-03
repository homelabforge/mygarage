"""Integration tests for the fuel-type gate on DEF record create/update.

Task 5 of the fuel-type hardening plan wires `ensure_def_capable`
(`app/utils/def_sync.py`, added in Task 4) into `create_def_record` /
`update_def_record` only. List, get, analytics, and delete stay
ungated on purpose (Jamey's decision, see task-5-brief.md): legacy
non-diesel DEF data must remain readable, and delete must remain
possible so junk data can be cleaned up.

Tasks 6-8 extend this file with further fuel-type-hardening gate cases.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.def_record import DEFRecord
from app.models.vehicle import Vehicle
from app.services.vehicle_service import (
    DEF_CAPACITY_CLEAR_FIRST_DETAIL as CAPACITY_CLEAR_FIRST_DETAIL,
)
from app.services.vehicle_service import (
    DEF_CAPACITY_NON_DIESEL_DETAIL as CAPACITY_GATE_DETAIL,
)

GATE_DETAIL = "DEF tracking applies only to diesel vehicles"


def _unique_vin() -> str:
    """17-char VIN, unique per call."""
    return ("GATE" + uuid.uuid4().hex)[:17].upper()


async def _make_vehicle(
    db_session: AsyncSession,
    user_id: int,
    *,
    fuel_type: str | None = None,
    fuel_type_secondary: str | None = None,
    def_tank_capacity_liters: Decimal | None = None,
) -> Vehicle:
    vehicle = Vehicle(
        vin=_unique_vin(),
        user_id=user_id,
        nickname="Gate Test Vehicle",
        vehicle_type="Car",
        year=2020,
        make="Test",
        model="Model",
        fuel_type=fuel_type,
        fuel_type_secondary=fuel_type_secondary,
        def_tank_capacity_liters=def_tank_capacity_liters,
    )
    db_session.add(vehicle)
    await db_session.commit()
    await db_session.refresh(vehicle)
    return vehicle


async def _seed_def_record(db_session: AsyncSession, vin: str) -> DEFRecord:
    """Insert a DEF record directly via the DB, bypassing the (now-gated) API."""
    record = DEFRecord(
        vin=vin,
        date=date(2024, 1, 1),
        liters=Decimal("9.464"),
        fill_level=Decimal("0.50"),
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


@pytest_asyncio.fixture
async def gasoline_vehicle(db_session: AsyncSession, test_user: dict[str, object]) -> Vehicle:
    return await _make_vehicle(db_session, test_user["id"], fuel_type="gasoline")


@pytest_asyncio.fixture
async def diesel_vehicle_with_capacity(
    db_session: AsyncSession, test_user: dict[str, object]
) -> Vehicle:
    """Diesel vehicle with an existing DEF tank capacity set (Task 6 gate cases)."""
    return await _make_vehicle(
        db_session,
        test_user["id"],
        fuel_type="diesel",
        def_tank_capacity_liters=Decimal("75.0"),
    )


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
class TestDEFFuelTypeGate:
    """Gate DEF record create/update to diesel-capable vehicles only."""

    async def test_create_def_record_on_gasoline_vehicle_rejected(
        self, client: AsyncClient, auth_headers, gasoline_vehicle: Vehicle
    ):
        response = await client.post(
            f"/api/vehicles/{gasoline_vehicle.vin}/def",
            json={"vin": gasoline_vehicle.vin, "date": "2024-01-15", "liters": 9.464},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == GATE_DETAIL

    async def test_update_def_record_on_gasoline_vehicle_rejected(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        gasoline_vehicle: Vehicle,
    ):
        # Seed via DB directly since the API now refuses create on this vehicle.
        record = await _seed_def_record(db_session, gasoline_vehicle.vin)

        response = await client.put(
            f"/api/vehicles/{gasoline_vehicle.vin}/def/{record.id}",
            json={"cost": 25.00},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == GATE_DETAIL

    async def test_list_def_records_on_gasoline_vehicle_stays_ungated(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        gasoline_vehicle: Vehicle,
    ):
        await _seed_def_record(db_session, gasoline_vehicle.vin)

        response = await client.get(
            f"/api/vehicles/{gasoline_vehicle.vin}/def",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_analytics_on_gasoline_vehicle_stays_ungated(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        gasoline_vehicle: Vehicle,
    ):
        await _seed_def_record(db_session, gasoline_vehicle.vin)

        response = await client.get(
            f"/api/vehicles/{gasoline_vehicle.vin}/def/analytics",
            headers=auth_headers,
        )

        assert response.status_code == 200

    async def test_delete_def_record_on_gasoline_vehicle_stays_ungated(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        gasoline_vehicle: Vehicle,
    ):
        record = await _seed_def_record(db_session, gasoline_vehicle.vin)

        response = await client.delete(
            f"/api/vehicles/{gasoline_vehicle.vin}/def/{record.id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

    async def test_create_def_record_on_diesel_vehicle_allowed(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        test_user: dict[str, object],
    ):
        vehicle = await _make_vehicle(db_session, test_user["id"], fuel_type="diesel")

        response = await client.post(
            f"/api/vehicles/{vehicle.vin}/def",
            json={"vin": vehicle.vin, "date": "2024-01-15", "liters": 9.464},
            headers=auth_headers,
        )

        assert response.status_code == 201

    async def test_create_def_record_on_gasoline_primary_diesel_secondary_allowed(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        test_user: dict[str, object],
    ):
        vehicle = await _make_vehicle(
            db_session,
            test_user["id"],
            fuel_type="gasoline",
            fuel_type_secondary="diesel",
        )

        response = await client.post(
            f"/api/vehicles/{vehicle.vin}/def",
            json={"vin": vehicle.vin, "date": "2024-01-15", "liters": 9.464},
            headers=auth_headers,
        )

        assert response.status_code == 201


def _vehicle_create_payload(
    *,
    fuel_type: str | None = None,
    def_tank_capacity_liters: float | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "vin": _unique_vin(),
        "nickname": "Capacity Gate Vehicle",
        "vehicle_type": "Car",
    }
    if fuel_type is not None:
        payload["fuel_type"] = fuel_type
    if def_tank_capacity_liters is not None:
        payload["def_tank_capacity_liters"] = def_tank_capacity_liters
    return payload


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
class TestVehicleDEFCapacityGate:
    """Task 6: gate `def_tank_capacity_liters` on vehicle create/update.

    The rule evaluates the *resulting* (post-update) state: capacity > 0
    is only allowed when the resulting fuel_type/fuel_type_secondary is
    diesel-capable. Setting capacity to None/0 is always allowed.
    """

    async def test_create_gasoline_with_capacity_rejected(self, client: AsyncClient, auth_headers):
        payload = _vehicle_create_payload(fuel_type="gasoline", def_tank_capacity_liters=75.0)

        response = await client.post("/api/vehicles", json=payload, headers=auth_headers)

        assert response.status_code == 400
        assert response.json()["detail"] == CAPACITY_GATE_DETAIL

    async def test_create_diesel_with_capacity_allowed(self, client: AsyncClient, auth_headers):
        payload = _vehicle_create_payload(fuel_type="diesel", def_tank_capacity_liters=75.0)

        response = await client.post("/api/vehicles", json=payload, headers=auth_headers)

        assert response.status_code == 201

    async def test_update_gasoline_set_capacity_rejected(
        self, client: AsyncClient, auth_headers, gasoline_vehicle: Vehicle
    ):
        response = await client.put(
            f"/api/vehicles/{gasoline_vehicle.vin}",
            json={"def_tank_capacity_liters": 75.0},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == CAPACITY_GATE_DETAIL

    async def test_update_diesel_to_gasoline_without_clearing_capacity_rejected(
        self,
        client: AsyncClient,
        auth_headers,
        diesel_vehicle_with_capacity: Vehicle,
    ):
        response = await client.put(
            f"/api/vehicles/{diesel_vehicle_with_capacity.vin}",
            json={"fuel_type": "gasoline"},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == CAPACITY_CLEAR_FIRST_DETAIL

    async def test_update_diesel_to_gasoline_with_capacity_cleared_allowed(
        self,
        client: AsyncClient,
        auth_headers,
        diesel_vehicle_with_capacity: Vehicle,
    ):
        response = await client.put(
            f"/api/vehicles/{diesel_vehicle_with_capacity.vin}",
            json={"fuel_type": "gasoline", "def_tank_capacity_liters": None},
            headers=auth_headers,
        )

        assert response.status_code == 200

    async def test_update_capacity_on_diesel_allowed(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        test_user: dict[str, object],
    ):
        vehicle = await _make_vehicle(db_session, test_user["id"], fuel_type="diesel")

        response = await client.put(
            f"/api/vehicles/{vehicle.vin}",
            json={"def_tank_capacity_liters": 80.0},
            headers=auth_headers,
        )

        assert response.status_code == 200
