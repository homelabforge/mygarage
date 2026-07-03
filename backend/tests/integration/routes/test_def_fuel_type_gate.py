"""Integration tests for the fuel-type gate on DEF record create/update.

Task 5 of the fuel-type hardening plan wires `ensure_def_capable`
(`app/utils/def_sync.py`, added in Task 4) into `create_def_record` /
`update_def_record` only. List, get, analytics, and delete stay
ungated on purpose (Jamey's decision, see task-5-brief.md): legacy
non-diesel DEF data must remain readable, and delete must remain
possible so junk data can be cleaned up.

Tasks 6-8 extend this file with further fuel-type-hardening gate cases.
"""

import json
import uuid
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.def_record import DEFRecord
from app.models.fuel import FuelRecord
from app.models.vehicle import Vehicle

GATE_DETAIL = "DEF tracking applies only to diesel vehicles"


def _fuel_payload(
    *, def_fill_level: float | None = None, odometer_km: float = 50000.0
) -> dict[str, object]:
    payload: dict[str, object] = {
        "date": "2024-01-15",
        "odometer_km": odometer_km,
        "liters": 45.0,
    }
    if def_fill_level is not None:
        payload["def_fill_level"] = def_fill_level
    return payload


# Task 6: vehicle-level `def_tank_capacity_liters` create/update gate.
# Hand-typed literals ON PURPOSE (not imported from vehicle_service): the
# assertions must pin the user-facing text, so a regression in the service
# constants (blank/garbled message) fails these tests instead of passing
# tautologically.
NON_DIESEL_CAPACITY_DETAIL = "DEF tank capacity applies only to diesel vehicles"
CAPACITY_CLEAR_FIRST_DETAIL = (
    "Changing fuel type away from diesel requires clearing the DEF tank capacity first"
)


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
        assert response.json()["detail"] == NON_DIESEL_CAPACITY_DETAIL

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
        assert response.json()["detail"] == NON_DIESEL_CAPACITY_DETAIL

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


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
class TestFuelRecordDEFFillLevelGate:
    """Task 7: gate `def_fill_level` on fuel record create/update.

    This is the last interactive bypass surface for DEF auto-sync — a
    non-diesel vehicle could otherwise get a DEF observation row written
    via `sync_def_from_fuel_record` just by including `def_fill_level` on
    a fuel record. A fuel record WITHOUT `def_fill_level` must be
    completely unaffected by this gate, on any vehicle.
    """

    async def test_create_fuel_with_def_fill_level_on_gasoline_rejected(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        gasoline_vehicle: Vehicle,
    ):
        response = await client.post(
            f"/api/vehicles/{gasoline_vehicle.vin}/fuel",
            json={"vin": gasoline_vehicle.vin, **_fuel_payload(def_fill_level=0.75)},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == GATE_DETAIL

        # The gate must fire BEFORE any DB insert — no orphaned fuel record.
        count_result = await db_session.execute(
            select(func.count())
            .select_from(FuelRecord)
            .where(FuelRecord.vin == gasoline_vehicle.vin)
        )
        assert count_result.scalar() == 0

    async def test_create_fuel_with_def_fill_level_on_diesel_allowed_and_syncs_def(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        test_user: dict[str, object],
    ):
        vehicle = await _make_vehicle(db_session, test_user["id"], fuel_type="diesel")

        response = await client.post(
            f"/api/vehicles/{vehicle.vin}/fuel",
            json={"vin": vehicle.vin, **_fuel_payload(def_fill_level=0.75)},
            headers=auth_headers,
        )

        assert response.status_code == 201
        record_id = response.json()["id"]

        def_result = await db_session.execute(
            select(DEFRecord).where(DEFRecord.origin_fuel_record_id == record_id)
        )
        def_record = def_result.scalar_one()
        assert def_record.entry_type == "auto_fuel_sync"

    async def test_create_fuel_without_def_fill_level_on_gasoline_allowed(
        self,
        client: AsyncClient,
        auth_headers,
        gasoline_vehicle: Vehicle,
    ):
        response = await client.post(
            f"/api/vehicles/{gasoline_vehicle.vin}/fuel",
            json={"vin": gasoline_vehicle.vin, **_fuel_payload()},
            headers=auth_headers,
        )

        assert response.status_code == 201

    async def test_update_fuel_add_def_fill_level_on_gasoline_rejected(
        self,
        client: AsyncClient,
        auth_headers,
        gasoline_vehicle: Vehicle,
    ):
        create_response = await client.post(
            f"/api/vehicles/{gasoline_vehicle.vin}/fuel",
            json={"vin": gasoline_vehicle.vin, **_fuel_payload()},
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record_id = create_response.json()["id"]

        response = await client.put(
            f"/api/vehicles/{gasoline_vehicle.vin}/fuel/{record_id}",
            json={"def_fill_level": 0.5},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == GATE_DETAIL

    async def test_update_fuel_clear_def_fill_level_on_gasoline_allowed(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        gasoline_vehicle: Vehicle,
    ):
        """Explicit `def_fill_level: null` stays ungated on non-diesel ON PURPOSE.

        Locked product decision: clearing DEF data is a delete, and deletes
        are always allowed so legacy/junk data can be cleaned up (same rule
        as the ungated DEF-record delete route above). The update-path guard
        is deliberately `def_fill_level is not None` — this test pins that
        asymmetry so a future "consistency fix" goes red in CI.
        """
        # Seed the fuel record + its auto-synced DEF row directly via the DB,
        # since the API now refuses to create this state on a gasoline vehicle.
        fuel_record = FuelRecord(
            vin=gasoline_vehicle.vin,
            date=date(2024, 1, 15),
            odometer_km=Decimal("50000.00"),
            liters=Decimal("45.000"),
        )
        db_session.add(fuel_record)
        await db_session.commit()
        await db_session.refresh(fuel_record)

        def_record = DEFRecord(
            vin=gasoline_vehicle.vin,
            date=date(2024, 1, 15),
            odometer_km=Decimal("50000.00"),
            fill_level=Decimal("0.75"),
            entry_type="auto_fuel_sync",
            origin_fuel_record_id=fuel_record.id,
        )
        db_session.add(def_record)
        await db_session.commit()

        response = await client.put(
            f"/api/vehicles/{gasoline_vehicle.vin}/fuel/{fuel_record.id}",
            json={"def_fill_level": None},
            headers=auth_headers,
        )

        assert response.status_code == 200

        # The clear path deletes the linked auto-synced DEF row.
        def_result = await db_session.execute(
            select(DEFRecord).where(DEFRecord.origin_fuel_record_id == fuel_record.id)
        )
        assert def_result.scalar_one_or_none() is None

    async def test_update_fuel_add_def_fill_level_on_diesel_allowed(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        test_user: dict[str, object],
    ):
        vehicle = await _make_vehicle(db_session, test_user["id"], fuel_type="diesel")

        create_response = await client.post(
            f"/api/vehicles/{vehicle.vin}/fuel",
            json={"vin": vehicle.vin, **_fuel_payload()},
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record_id = create_response.json()["id"]

        response = await client.put(
            f"/api/vehicles/{vehicle.vin}/fuel/{record_id}",
            json={"def_fill_level": 0.6},
            headers=auth_headers,
        )

        assert response.status_code == 200

        def_result = await db_session.execute(
            select(DEFRecord).where(DEFRecord.origin_fuel_record_id == record_id)
        )
        def_record = def_result.scalar_one()
        assert def_record.entry_type == "auto_fuel_sync"


def _def_csv_content() -> str:
    return (
        "Date,Odometer (km),Liters,Price Per Unit,Total Cost,Fill Level,Source,Brand,Notes\n"
        "2024-01-10,49500,9.464,1.10,10.41,0.60,dealer,BlueDEF,First fill\n"
        "2024-02-10,50500,9.464,1.15,10.88,0.55,dealer,BlueDEF,Second fill\n"
    )


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
class TestDEFCsvImportGate:
    """Task 8: gate the `/def/csv` importer to diesel-capable vehicles only.

    This closes the last gated surface — `import_def_csv` previously
    constructed `DEFRecord` rows directly with no fuel-type check.
    """

    async def test_import_def_csv_on_gasoline_vehicle_rejected(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        gasoline_vehicle: Vehicle,
    ):
        response = await client.post(
            f"/api/import/vehicles/{gasoline_vehicle.vin}/def/csv",
            headers=auth_headers,
            files={
                "file": ("def.csv", BytesIO(_def_csv_content().encode()), "text/csv"),
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == GATE_DETAIL

        # The gate must fire BEFORE any row is processed — no partial import.
        count_result = await db_session.execute(
            select(func.count()).select_from(DEFRecord).where(DEFRecord.vin == gasoline_vehicle.vin)
        )
        assert count_result.scalar() == 0

    async def test_import_def_csv_on_diesel_vehicle_allowed(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        test_user: dict[str, object],
    ):
        vehicle = await _make_vehicle(db_session, test_user["id"], fuel_type="diesel")

        response = await client.post(
            f"/api/import/vehicles/{vehicle.vin}/def/csv",
            headers=auth_headers,
            files={
                "file": ("def.csv", BytesIO(_def_csv_content().encode()), "text/csv"),
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success_count"] == 2
        assert data["error_count"] == 0

        count_result = await db_session.execute(
            select(func.count()).select_from(DEFRecord).where(DEFRecord.vin == vehicle.vin)
        )
        assert count_result.scalar() == 2


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
class TestBulkRestoreDEFStaysUngated:
    """Task 8: the bulk-restore JSON path is deliberately NOT gated.

    Backup fidelity: a user's own archive must always restore in full,
    even if it contains DEF rows for a vehicle that is no longer (or
    never was, per current fuel-type data) diesel. Unlike the CSV
    importer and the interactive create/update routes, this is a
    round-trip of the user's own prior data, not a new write.
    """

    async def test_restore_json_with_def_records_on_gasoline_vehicle_restores_fully(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        gasoline_vehicle: Vehicle,
    ):
        payload = {
            "def_records": [
                {
                    "date": "2024-01-10",
                    "odometer_km": 49500,
                    "liters": 9.464,
                    "price_per_unit": 1.10,
                    "cost": 10.41,
                    "fill_level": 0.60,
                    "source": "dealer",
                    "brand": "BlueDEF",
                    "notes": "Restored from backup",
                }
            ],
        }

        response = await client.post(
            f"/api/import/vehicles/{gasoline_vehicle.vin}/json",
            headers=auth_headers,
            files={
                "file": (
                    "backup.json",
                    BytesIO(json.dumps(payload).encode()),
                    "application/json",
                )
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["def_records"]["success_count"] == 1
        assert data["def_records"]["error_count"] == 0

        def_result = await db_session.execute(
            select(DEFRecord).where(DEFRecord.vin == gasoline_vehicle.vin)
        )
        restored = def_result.scalar_one()
        assert restored.source == "dealer"
        assert restored.fill_level == Decimal("0.60")
