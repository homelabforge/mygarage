"""The session-end leak guard in tests/conftest.py, held to what it promises.

It only ever runs once, at the end of a run, so a guard that broke would stay
quiet and every run would look clean. These pin what it reports and that
`init_test_db` still calls it.
"""

import ast
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models.financing import FinancingRecord
from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.service_visit import ServiceVisit
from app.models.vehicle import Vehicle
from tests.conftest import far_future_horizon, far_future_survivors

CONFTEST = Path(__file__).resolve().parents[1] / "conftest.py"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_it_lists_each_guarded_table_past_the_horizon_and_not_one_on_it(
    db_session: AsyncSession, test_engine: AsyncEngine, test_user: dict[str, object]
) -> None:
    vin = "LKG" + uuid.uuid4().hex[:14].upper()
    horizon = far_future_horizon()
    late = horizon + timedelta(days=1)
    db_session.add(Vehicle(vin=vin, user_id=test_user["id"], nickname="Leak", vehicle_type="Car"))
    await db_session.flush()
    past: list[FinancingRecord | FuelRecord | HoursRecord | OdometerRecord | ServiceVisit] = [
        FinancingRecord(vin=vin, date=late, amount=Decimal("1.00"), category="loan_payment"),
        FuelRecord(vin=vin, date=late),
        HoursRecord(vin=vin, date=late, engine_hours=Decimal("1.0")),
        OdometerRecord(vin=vin, date=late, odometer_km=Decimal("1.00")),
        ServiceVisit(vin=vin, date=late),
    ]
    # Exactly a year out isn't "more than" a year.
    on_horizon = FuelRecord(vin=vin, date=horizon)
    db_session.add_all([*past, on_horizon])
    await db_session.commit()
    expected = [f"{row.__tablename__} id={row.id} vin={vin} date={late}" for row in past]
    try:
        found = [line for line in await far_future_survivors(test_engine) if f"vin={vin} " in line]
    finally:
        await db_session.rollback()
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
        await db_session.commit()

    assert found == expected


def test_init_test_db_runs_the_guard_and_fails_on_survivors() -> None:
    """Without the call, or the fail, nothing would ever report a leak."""
    tree = ast.parse(CONFTEST.read_text(), filename=str(CONFTEST))
    fixture = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "init_test_db"
    )
    called = {ast.unparse(node.func) for node in ast.walk(fixture) if isinstance(node, ast.Call)}
    assert {"far_future_survivors", "pytest.fail"} <= called
