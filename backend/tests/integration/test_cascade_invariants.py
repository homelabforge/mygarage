"""Cascade-invariant tests using the ``_cascade`` helper.

This is the framework smoke. Real rc2 scenarios land here as Phase 2.5
(fuel→odometer via migration 055) and Phase 4.2 (broader matrix:
vehicle→{service, drive_session, dtc, photo, document}) ship.

Runs on both engines since v2.30.1: SQLite connections now set
``PRAGMA foreign_keys=ON`` (production and tests alike), so declared
cascades fire there too. The broader vehicle-delete matrix lives in
``test_vehicle_delete_integrity.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord
from app.models.vehicle import Vehicle
from tests.integration._cascade import CascadeScenario, assert_cascade_clean

# Smoke scenario — uses the existing vehicles.vin → fuel_records.vin FK
# (declared with ``ondelete="CASCADE"`` in the model) to prove the
# helper machinery works end-to-end before Phase 2.5 wires up the
# fuel→odometer scenario.
VEHICLE_TO_FUEL = CascadeScenario(
    name="vehicle→fuel",
    child_model=FuelRecord,
    fk_attr_name="vin",
    on_delete="cascade",
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vehicle_delete_cascades_fuel_records(
    db_session: AsyncSession, test_user: dict[str, object]
) -> None:
    """Smoke: deleting a vehicle removes its fuel records.

    Rolls a throwaway vehicle so we don't trash the shared test_vehicle
    that other tests depend on. Runs on both engines — SQLite enforces
    FKs since v2.30.1 (PRAGMA foreign_keys=ON).
    """
    throwaway_vin = "CASCADESMOKE12345"
    vehicle = Vehicle(
        vin=throwaway_vin,
        user_id=test_user["id"],
        nickname="Cascade Smoke",
        vehicle_type="Car",
        year=2024,
        make="Test",
        model="Vehicle",
    )
    db_session.add(vehicle)
    await db_session.flush()

    # Two fuel records so count_children's pre-check is non-trivial.
    for i in range(2):
        db_session.add(
            FuelRecord(
                vin=throwaway_vin,
                date=(datetime.now() - timedelta(days=i)).date(),
                liters=Decimal("40.0"),
                cost=Decimal("60.0"),
            )
        )
    await db_session.commit()

    async def _delete_vehicle() -> None:
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == throwaway_vin))

    await assert_cascade_clean(
        session=db_session,
        scenario=VEHICLE_TO_FUEL,
        parent_value=throwaway_vin,
        delete_parent=_delete_vehicle,
        expected_pre_count_min=2,
    )

    # Sanity: vehicle row itself is gone.
    result = await db_session.execute(select(Vehicle).where(Vehicle.vin == throwaway_vin))
    assert result.scalar_one_or_none() is None
