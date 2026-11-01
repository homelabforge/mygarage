"""The session-end leak guard in tests/conftest.py, held to what it promises.

It only ever runs once, at the end of a run, so a guard that broke would stay
quiet and every run would look clean. These pin what it reports, that its
teardown fails the run and still drops the tables, and that `init_test_db`
still calls it.
"""

import ast
import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

import tests.conftest as root_conftest
from app.database import Base
from app.models.def_record import DEFRecord
from app.models.financing import FinancingRecord
from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.service_visit import ServiceVisit
from app.models.tax import TaxRecord
from app.models.vehicle import Vehicle
from app.models.warranty import WarrantyRecord
from tests.conftest import far_future_horizon, far_future_survivors, finish_test_db

CONFTEST = Path(__file__).resolve().parents[1] / "conftest.py"

GuardedRow = (
    DEFRecord
    | FinancingRecord
    | FuelRecord
    | HoursRecord
    | OdometerRecord
    | Reminder
    | ServiceVisit
    | TaxRecord
    | WarrantyRecord
)


def _one_of_each(vin: str, day: date) -> list[tuple[GuardedRow, str]]:
    """A row on every guarded table dated `day`, with the column that dates it."""
    return [
        (DEFRecord(vin=vin, date=day, fill_level=Decimal("0.50")), "date"),
        (
            FinancingRecord(vin=vin, date=day, amount=Decimal("1.00"), category="loan_payment"),
            "date",
        ),
        (FuelRecord(vin=vin, date=day), "date"),
        (HoursRecord(vin=vin, date=day, engine_hours=Decimal("1.0")), "date"),
        (OdometerRecord(vin=vin, date=day, odometer_km=Decimal("1.00")), "date"),
        (Reminder(vin=vin, title="Leak", reminder_type="date", due_date=day), "due_date"),
        (ServiceVisit(vin=vin, date=day), "date"),
        (TaxRecord(vin=vin, date=day, amount=Decimal("1.00")), "date"),
        (
            WarrantyRecord(
                vin=vin,
                warranty_type="Powertrain",
                start_date=date(2024, 1, 1),
                end_date=day,
            ),
            "end_date",
        ),
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_it_lists_each_guarded_table_past_the_horizon_and_not_one_on_it(
    db_session: AsyncSession, test_engine: AsyncEngine, test_user: dict[str, object]
) -> None:
    vin = "LKG" + uuid.uuid4().hex[:14].upper()
    # Read once and handed to the guard, so a run crossing UTC midnight can't
    # move the horizon between here and its query.
    horizon = far_future_horizon()
    late = horizon + timedelta(days=1)
    db_session.add(Vehicle(vin=vin, user_id=test_user["id"], nickname="Leak", vehicle_type="Car"))
    await db_session.flush()
    past = _one_of_each(vin, late)
    # Exactly a year out isn't "more than" a year.
    on_horizon = [row for row, _ in _one_of_each(vin, horizon)]
    db_session.add_all([row for row, _ in past] + on_horizon)
    await db_session.commit()
    expected = sorted(
        f"{row.__tablename__} id={row.id} vin={vin} {column}={late}" for row, column in past
    )
    try:
        found = sorted(
            line
            for line in await far_future_survivors(test_engine, horizon)
            if f"vin={vin} " in line
        )
        # The guard really reads the horizon it's handed: a day later, nothing's past it.
        found_a_day_later = [
            line for line in await far_future_survivors(test_engine, late) if f"vin={vin} " in line
        ]
    finally:
        await db_session.rollback()
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
        await db_session.commit()

    assert found == expected
    assert found_a_day_later == []


@pytest_asyncio.fixture
async def private_engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """A throwaway SQLite file with the full schema, so dropping it is harmless."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'guard.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def _tables(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(lambda sync: inspect(sync).get_table_names())


async def _leak_one_row(engine: AsyncEngine) -> None:
    async with AsyncSession(engine) as session:
        session.add(Vehicle(vin="LKGPRIVATE0000001", nickname="Leak", vehicle_type="Car"))
        await session.flush()
        session.add(FuelRecord(vin="LKGPRIVATE0000001", date=far_future_horizon() + timedelta(1)))
        await session.commit()


@pytest.mark.asyncio
class TestTheTeardown:
    async def test_a_survivor_fails_the_run_and_the_tables_still_go(
        self, private_engine: AsyncEngine
    ) -> None:
        await _leak_one_row(private_engine)

        with pytest.raises(pytest.fail.Exception, match="fuel_records id=1 vin=LKGPRIVATE0000001"):
            await finish_test_db(private_engine)

        assert await _tables(private_engine) == []

    async def test_a_guard_that_blows_up_still_drops_the_tables(
        self, private_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _broken(engine: AsyncEngine, horizon: date | None = None) -> list[str]:
            raise RuntimeError("guard query failed")

        monkeypatch.setattr(root_conftest, "far_future_survivors", _broken)

        with pytest.raises(RuntimeError, match="guard query failed"):
            await finish_test_db(private_engine)

        assert await _tables(private_engine) == []

    async def test_a_clean_run_passes_and_drops_the_tables(
        self, private_engine: AsyncEngine
    ) -> None:
        assert await _tables(private_engine) != []  # control: there was something to drop

        await finish_test_db(private_engine)

        assert await _tables(private_engine) == []


def test_init_test_db_runs_the_guard_and_fails_on_survivors() -> None:
    """Without these calls nothing would ever report a leak."""
    tree = ast.parse(CONFTEST.read_text(), filename=str(CONFTEST))

    def calls(name: str) -> set[str]:
        fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == name
        )
        return {ast.unparse(node.func) for node in ast.walk(fn) if isinstance(node, ast.Call)}

    assert "finish_test_db" in calls("init_test_db")
    assert {"far_future_survivors", "pytest.fail"} <= calls("finish_test_db")
