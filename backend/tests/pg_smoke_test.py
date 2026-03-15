"""PostgreSQL-specific smoke tests for dialect-aware code paths.

Run with:
    TEST_DATABASE_URL="postgresql+asyncpg://..." PYTHONPATH=. pytest tests/pg_smoke_test.py -v
"""

import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import Base

PG_URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif("asyncpg" not in PG_URL, reason="PostgreSQL-only tests")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pg_engine():
    """Create a PostgreSQL engine for smoke tests."""
    engine = create_async_engine(PG_URL, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def pg_session(pg_engine):
    """Provide a PostgreSQL session."""
    session_factory = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        try:
            await session.rollback()
        except Exception:
            pass  # Suppress event loop teardown errors with asyncpg


class TestTollSummaryDialect:
    """Verify toll summary uses to_char() on PostgreSQL (#48)."""

    async def test_to_char_monthly_grouping(self, pg_session: AsyncSession):
        """Verify to_char() works for monthly grouping on PostgreSQL."""
        from datetime import date
        from decimal import Decimal

        from app.models.toll import TollTransaction
        from app.models.user import User
        from app.models.vehicle import Vehicle

        # Create test user
        user = User(
            username="pg_toll_test",
            email="pg_toll@test.com",
            hashed_password="fake",
            is_active=True,
            is_admin=True,
        )
        pg_session.add(user)
        await pg_session.flush()

        # Create test vehicle
        vehicle = Vehicle(
            vin="PGTOLL0000000TEST",
            user_id=user.id,
            nickname="PG Toll Test",
            vehicle_type="Car",
        )
        pg_session.add(vehicle)
        await pg_session.flush()

        # Create toll transactions in different months
        for month, amount in [(1, "5.00"), (1, "3.00"), (2, "7.50")]:
            pg_session.add(
                TollTransaction(
                    vin=vehicle.vin,
                    date=date(2026, month, 15),
                    amount=Decimal(amount),
                    location="Test Plaza",
                )
            )
        await pg_session.flush()

        # Run the actual dialect-aware query from toll_service
        from sqlalchemy import func, select

        from app.database import is_sqlite
        from app.models.toll import TollTransaction as TT

        if is_sqlite:
            month_col = func.strftime("%Y-%m", TT.date).label("month")
        else:
            month_col = func.to_char(TT.date, "YYYY-MM").label("month")

        result = await pg_session.execute(
            select(
                month_col,
                func.count(TT.id).label("count"),
                func.sum(TT.amount).label("amount"),
            )
            .where(TT.vin == vehicle.vin)
            .group_by(month_col)
            .order_by(month_col.desc())
        )
        rows = result.all()

        assert len(rows) == 2
        assert rows[0].month == "2026-02"
        assert rows[0].count == 1
        assert rows[1].month == "2026-01"
        assert rows[1].count == 2


class TestTelemetryUpsert:
    """Verify telemetry upsert uses PostgreSQL dialect (#telemetry fix)."""

    async def test_dialect_insert_upsert(self, pg_session: AsyncSession):
        """Verify dialect_insert works for upsert on PostgreSQL."""
        from datetime import datetime

        from app.database import is_sqlite
        from app.models.vehicle_telemetry import VehicleTelemetryLatest

        if is_sqlite:
            from sqlalchemy.dialects.sqlite import insert as dialect_insert
        else:
            from sqlalchemy.dialects.postgresql import insert as dialect_insert

        from app.models.user import User
        from app.models.vehicle import Vehicle

        # Create test user + vehicle
        user = User(
            username="pg_telem_test",
            email="pg_telem@test.com",
            hashed_password="fake",
            is_active=True,
            is_admin=True,
        )
        pg_session.add(user)
        await pg_session.flush()

        vehicle = Vehicle(
            vin="PGTELEM000000TEST",
            user_id=user.id,
            nickname="PG Telemetry Test",
            vehicle_type="Car",
        )
        pg_session.add(vehicle)
        await pg_session.flush()

        now = datetime.now()

        # Initial insert
        stmt = dialect_insert(VehicleTelemetryLatest).values(
            vin=vehicle.vin,
            param_key="0D-VehicleSpeed",
            value=65.0,
            timestamp=now,
            received_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["vin", "param_key"],
            set_={"value": 65.0, "timestamp": now, "received_at": now},
        )
        await pg_session.execute(stmt)
        await pg_session.flush()

        # Upsert (update existing)
        stmt = dialect_insert(VehicleTelemetryLatest).values(
            vin=vehicle.vin,
            param_key="0D-VehicleSpeed",
            value=72.0,
            timestamp=now,
            received_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["vin", "param_key"],
            set_={"value": 72.0, "timestamp": now, "received_at": now},
        )
        await pg_session.execute(stmt)
        await pg_session.flush()

        # Verify upsert worked
        result = await pg_session.execute(
            text(
                "SELECT value FROM vehicle_telemetry_latest WHERE vin = :vin AND param_key = :key"
            ),
            {"vin": vehicle.vin, "key": "0D-VehicleSpeed"},
        )
        row = result.one()
        assert float(row[0]) == 72.0


class TestSystemInfoPgSize:
    """Verify pg_database_size() works on PostgreSQL (#system-info fix)."""

    async def test_pg_database_size_query(self, pg_session: AsyncSession):
        """Verify pg_database_size(current_database()) returns a positive integer."""
        result = await pg_session.execute(text("SELECT pg_database_size(current_database())"))
        size_bytes = result.scalar()
        assert size_bytes is not None
        assert size_bytes > 0


class TestBackupPgDump:
    """Verify pg_dump URL parsing works (#backup fix)."""

    def test_parse_pg_url(self):
        """Verify PostgreSQL URL is parsed correctly for pg_dump."""
        from pathlib import Path

        from app.services.backup_service import BackupService

        service = BackupService(
            backup_dir=Path("/tmp"),
            database_path=None,
            data_dir=Path("/tmp"),
            database_url="postgresql+asyncpg://myuser:mypass%40word@dbhost:5433/mydb",
            is_sqlite=False,
        )
        pg = service._parse_pg_url()

        assert pg["host"] == "dbhost"
        assert pg["port"] == "5433"
        assert pg["user"] == "myuser"
        assert pg["password"] == "mypass@word"  # URL-decoded
        assert pg["dbname"] == "mydb"


class TestUserModelTimestamps:
    """Verify user model timestamps work on PostgreSQL (timezone fix)."""

    async def test_create_user_with_server_default(self, pg_session: AsyncSession):
        """Verify user creation uses server_default=func.now() without timezone errors."""
        from app.models.user import User

        user = User(
            username="pg_timestamp_test",
            email="pg_ts@test.com",
            hashed_password="fake",
            is_active=True,
            is_admin=False,
        )
        pg_session.add(user)
        await pg_session.flush()
        await pg_session.refresh(user)

        assert user.created_at is not None
        assert user.updated_at is not None
        assert user.id is not None
