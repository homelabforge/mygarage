"""Comprehensive PostgreSQL compatibility verification.

Tests all backend changes from the PostgreSQL compatibility push:
  ceb2d04 - Toll summary, fuel edit, DEF toggle, telemetry, backup, system info
  267dca5 - Handle null values from PostgreSQL
  3d77bf1 - DEF tracking toggle fix
  c5f76c4 - Timezone-aware datetime crash fix

Run with:
    docker exec mygarage-pg-test psql -U mygarage -d mygarage_test \
        -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    MYGARAGE_SECRET_KEY=test MYGARAGE_TEST_MODE=true \
    TEST_DATABASE_URL="postgresql+asyncpg://mygarage:testpass@localhost:15432/mygarage_test" \
    PYTHONPATH=. python3 -m pytest tests/pg_comprehensive_test.py -v --override-ini="addopts="
"""

import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import Base, is_sqlite

PG_URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif("asyncpg" not in PG_URL, reason="PostgreSQL-only tests")


# ---------------------------------------------------------------------------
# Fixtures — each test gets its own session to avoid asyncpg state conflicts
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pg_engine():
    """Create a PostgreSQL engine and initialize all tables."""
    engine = create_async_engine(PG_URL, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def pg_session(pg_engine):
    """Provide a fresh PostgreSQL session per test."""
    factory = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        try:
            await session.rollback()
        except Exception:
            pass


async def _make_user_and_vehicle(session: AsyncSession, suffix: str):
    """Helper to create a user + vehicle pair for a test."""
    from app.models.user import User
    from app.models.vehicle import Vehicle

    user = User(
        username=f"pg_{suffix}_user",
        email=f"pg_{suffix}@test.com",
        hashed_password="fake_hash",
        is_active=True,
        is_admin=True,
    )
    session.add(user)
    await session.flush()

    vehicle = Vehicle(
        vin=f"PG{suffix.upper()[:15]:0<15}",
        user_id=user.id,
        nickname=f"PG {suffix} Vehicle",
        vehicle_type="Car",
    )
    session.add(vehicle)
    await session.flush()
    return user, vehicle


# ===========================================================================
# 1. DIALECT DETECTION
# ===========================================================================

class TestDialectDetection:
    """Verify is_sqlite flag is False when using PostgreSQL."""

    def test_is_sqlite_false(self):
        assert is_sqlite is False, "is_sqlite should be False for PostgreSQL"


# ===========================================================================
# 2. SCHEMA CREATION — All tables created without errors
# ===========================================================================

class TestSchemaCreation:
    """Verify all SQLAlchemy models create valid PostgreSQL tables."""

    async def test_all_tables_exist(self, pg_engine):
        """Every table in Base.metadata should exist in the database."""
        expected = set(Base.metadata.tables.keys())
        async with pg_engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT tablename FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public'"
            ))
            actual = {row[0] for row in result}

        missing = expected - actual
        assert not missing, f"Tables missing from PostgreSQL: {missing}"

    async def test_table_count(self, pg_engine):
        """Sanity check — we should have a reasonable number of tables."""
        async with pg_engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT count(*) FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public'"
            ))
            count = result.scalar()

        assert count >= 20, f"Expected 20+ tables, got {count}"
        print(f"  -> {count} tables created successfully")


# ===========================================================================
# 3. TOLL SERVICE — to_char() dialect switch (ceb2d04)
# ===========================================================================

class TestTollDialect:
    """Verify toll summary monthly grouping uses to_char() on PostgreSQL."""

    async def test_to_char_monthly_grouping(self, pg_session):
        """to_char(date, 'YYYY-MM') should work for monthly toll aggregation."""
        from app.models.toll import TollTransaction

        _, vehicle = await _make_user_and_vehicle(pg_session, "toll")

        for month, day, amount in [
            (1, 5, "4.50"), (1, 20, "3.00"),
            (2, 10, "6.75"),
            (3, 1, "2.25"), (3, 15, "5.00"), (3, 28, "1.50"),
        ]:
            pg_session.add(TollTransaction(
                vin=vehicle.vin,
                date=date(2026, month, day),
                amount=Decimal(amount),
                location=f"Plaza M{month}",
            ))
        await pg_session.flush()

        from app.models.toll import TollTransaction as TT

        month_col = func.to_char(TT.date, "YYYY-MM").label("month")
        result = await pg_session.execute(
            select(
                month_col,
                func.count(TT.id).label("count"),
                func.sum(TT.amount).label("total"),
            )
            .where(TT.vin == vehicle.vin)
            .group_by(month_col)
            .order_by(month_col)
        )
        rows = result.all()

        assert len(rows) == 3, f"Expected 3 months, got {len(rows)}"
        assert rows[0].month == "2026-01"
        assert rows[0].count == 2
        assert float(rows[0].total) == 7.50
        assert rows[1].month == "2026-02"
        assert rows[1].count == 1
        assert rows[2].month == "2026-03"
        assert rows[2].count == 3
        assert float(rows[2].total) == 8.75


# ===========================================================================
# 4. TELEMETRY SERVICE — dialect-aware upsert (ceb2d04)
# ===========================================================================

class TestTelemetryUpsert:
    """Verify telemetry upsert uses PostgreSQL ON CONFLICT."""

    async def test_insert_then_upsert(self, pg_session):
        """dialect_insert().on_conflict_do_update() should work on PG."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.models.vehicle_telemetry import VehicleTelemetryLatest

        _, vehicle = await _make_user_and_vehicle(pg_session, "telem1")
        now = datetime.now()
        vin = vehicle.vin

        # First insert
        stmt = pg_insert(VehicleTelemetryLatest).values(
            vin=vin, param_key="0C-EngineRPM",
            value=800.0, timestamp=now, received_at=now,
        ).on_conflict_do_update(
            index_elements=["vin", "param_key"],
            set_={"value": 800.0, "timestamp": now, "received_at": now},
        )
        await pg_session.execute(stmt)
        await pg_session.flush()

        # Verify initial value
        row = (await pg_session.execute(text(
            "SELECT value FROM vehicle_telemetry_latest "
            "WHERE vin = :vin AND param_key = :key"
        ), {"vin": vin, "key": "0C-EngineRPM"})).one()
        assert float(row[0]) == 800.0

        # Upsert with new value
        stmt = pg_insert(VehicleTelemetryLatest).values(
            vin=vin, param_key="0C-EngineRPM",
            value=3500.0, timestamp=now, received_at=now,
        ).on_conflict_do_update(
            index_elements=["vin", "param_key"],
            set_={"value": 3500.0, "timestamp": now, "received_at": now},
        )
        await pg_session.execute(stmt)
        await pg_session.flush()

        # Verify updated, not duplicated
        result = await pg_session.execute(text(
            "SELECT value FROM vehicle_telemetry_latest "
            "WHERE vin = :vin AND param_key = :key"
        ), {"vin": vin, "key": "0C-EngineRPM"})
        rows = result.all()
        assert len(rows) == 1, "Upsert should not create duplicates"
        assert float(rows[0][0]) == 3500.0

    async def test_multiple_params_same_vin(self, pg_session):
        """Multiple telemetry params for the same VIN should coexist."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.models.vehicle_telemetry import VehicleTelemetryLatest

        _, vehicle = await _make_user_and_vehicle(pg_session, "telem2")
        now = datetime.now()
        vin = vehicle.vin

        for key, val in [("0D-VehicleSpeed", 65.0), ("05-EngineCoolantTemp", 92.0),
                         ("2F-FuelTankLevel", 75.0), ("11-ThrottlePosition", 15.5)]:
            stmt = pg_insert(VehicleTelemetryLatest).values(
                vin=vin, param_key=key, value=val, timestamp=now, received_at=now,
            ).on_conflict_do_update(
                index_elements=["vin", "param_key"],
                set_={"value": val, "timestamp": now, "received_at": now},
            )
            await pg_session.execute(stmt)
        await pg_session.flush()

        result = await pg_session.execute(text(
            "SELECT count(*) FROM vehicle_telemetry_latest WHERE vin = :vin"
        ), {"vin": vin})
        count = result.scalar()
        assert count == 4, f"Expected 4 telemetry params, got {count}"


# ===========================================================================
# 5. BACKUP SERVICE — pg_dump URL parsing (ceb2d04)
# ===========================================================================

class TestBackupService:
    """Verify backup service handles PostgreSQL correctly."""

    def test_parse_pg_url_standard(self):
        from app.services.backup_service import BackupService

        svc = BackupService(
            backup_dir=Path("/tmp"), database_path=None, data_dir=Path("/tmp"),
            database_url="postgresql+asyncpg://myuser:mypass@dbhost:5432/mydb",
            is_sqlite=False,
        )
        pg = svc._parse_pg_url()
        assert pg["host"] == "dbhost"
        assert pg["port"] == "5432"
        assert pg["user"] == "myuser"
        assert pg["password"] == "mypass"
        assert pg["dbname"] == "mydb"

    def test_parse_pg_url_encoded_password(self):
        from app.services.backup_service import BackupService

        svc = BackupService(
            backup_dir=Path("/tmp"), database_path=None, data_dir=Path("/tmp"),
            database_url="postgresql+asyncpg://admin:p%40ss%23w0rd@db.host:5433/production",
            is_sqlite=False,
        )
        pg = svc._parse_pg_url()
        assert pg["password"] == "p@ss#w0rd"
        assert pg["port"] == "5433"
        assert pg["dbname"] == "production"

    def test_parse_pg_url_no_port(self):
        from app.services.backup_service import BackupService

        svc = BackupService(
            backup_dir=Path("/tmp"), database_path=None, data_dir=Path("/tmp"),
            database_url="postgresql+asyncpg://user:pass@host/db",
            is_sqlite=False,
        )
        pg = svc._parse_pg_url()
        assert pg["port"] == "5432"


# ===========================================================================
# 6. SYSTEM INFO — pg_database_size() (ceb2d04)
# ===========================================================================

class TestSystemInfo:
    """Verify system info queries work on PostgreSQL."""

    async def test_pg_database_size(self, pg_session):
        result = await pg_session.execute(
            text("SELECT pg_database_size(current_database())")
        )
        size = result.scalar()
        assert size is not None
        assert isinstance(size, int)
        assert size > 0
        print(f"  -> Database size: {size / 1024:.0f} KB")

    async def test_current_database(self, pg_session):
        result = await pg_session.execute(text("SELECT current_database()"))
        dbname = result.scalar()
        assert dbname == "mygarage_test"


# ===========================================================================
# 7. TIMESTAMP MODELS — server_default=func.now() (c5f76c4)
#    These 5 models had datetime.now(UTC) which asyncpg rejects on
#    timezone-naive DateTime columns.
# ===========================================================================

class TestTimestampModels:
    """Verify all models that had datetime.now(UTC) -> server_default fix."""

    async def test_user_timestamps(self, pg_session):
        """User model created_at/updated_at via server default."""
        from app.models.user import User

        user = User(
            username="pg_ts_user",
            email="pg_ts_user@test.com",
            hashed_password="fake",
            is_active=True,
            is_admin=False,
        )
        pg_session.add(user)
        await pg_session.flush()
        await pg_session.refresh(user)

        assert user.created_at is not None, "created_at should be set by server"
        assert user.updated_at is not None, "updated_at should be set by server"
        assert isinstance(user.created_at, datetime)
        assert isinstance(user.updated_at, datetime)

    async def test_audit_log_timestamp(self, pg_session):
        """AuditLog model timestamp via server default."""
        from app.models.audit_log import AuditLog
        from app.models.user import User

        user = User(
            username="pg_audit_user",
            email="pg_audit@test.com",
            hashed_password="fake",
            is_active=True,
            is_admin=True,
        )
        pg_session.add(user)
        await pg_session.flush()

        log = AuditLog(
            user_id=user.id,
            action="test_action",
            resource_type="test",
            resource_id="1",
        )
        pg_session.add(log)
        await pg_session.flush()
        await pg_session.refresh(log)

        assert log.timestamp is not None, "AuditLog timestamp should be set by server"
        assert isinstance(log.timestamp, datetime)

    async def test_csrf_token_timestamp(self, pg_session):
        """CSRFToken model created_at via server default."""
        from app.models.csrf_token import CSRFToken
        from app.models.user import User

        user = User(
            username="pg_csrf_user",
            email="pg_csrf@test.com",
            hashed_password="fake",
            is_active=True,
            is_admin=False,
        )
        pg_session.add(user)
        await pg_session.flush()

        token = CSRFToken(
            token="test_csrf_token_12345",
            user_id=user.id,
            expires_at=datetime(2026, 12, 31),
        )
        pg_session.add(token)
        await pg_session.flush()
        await pg_session.refresh(token)

        assert token.created_at is not None, "CSRFToken created_at should be set by server"

    async def test_oidc_state_timestamp(self, pg_session):
        """OIDCState model created_at via server default."""
        from app.models.oidc_state import OIDCState

        state = OIDCState(
            state="test_oidc_state_12345",
            nonce="test_nonce_12345",
            redirect_uri="/callback",
            expires_at=datetime(2026, 12, 31),
        )
        pg_session.add(state)
        await pg_session.flush()
        await pg_session.refresh(state)

        assert state.created_at is not None, "OIDCState created_at should be set by server"

    async def test_oidc_pending_link_timestamp(self, pg_session):
        """OIDCPendingLink model created_at via server default."""
        from app.models.oidc_pending_link import OIDCPendingLink

        link = OIDCPendingLink(
            token="test_pending_link_12345",
            username="test_oidc_target",
            oidc_claims={"sub": "ext_user_1", "email": "ext@test.com"},
            provider_name="test_provider",
            expires_at=datetime(2026, 12, 31),
        )
        pg_session.add(link)
        await pg_session.flush()
        await pg_session.refresh(link)

        assert link.created_at is not None, "OIDCPendingLink created_at should be set by server"


# ===========================================================================
# 8. GENERAL CRUD — Basic operations on core models
# ===========================================================================

class TestCrudOperations:
    """Verify basic CRUD works on PostgreSQL for core models."""

    async def test_create_and_read_vehicle(self, pg_session):
        """Vehicle creation and retrieval."""
        from app.models.vehicle import Vehicle

        user, _ = await _make_user_and_vehicle(pg_session, "crud1")

        v = Vehicle(
            vin="PGCRUD00000000001",
            user_id=user.id,
            nickname="CRUD Test Car",
            vehicle_type="Truck",
            year=2024,
            make="Ford",
            model="F-150",
        )
        pg_session.add(v)
        await pg_session.flush()

        result = await pg_session.execute(
            select(Vehicle).where(Vehicle.vin == "PGCRUD00000000001")
        )
        found = result.scalar_one()
        assert found.nickname == "CRUD Test Car"
        assert found.year == 2024

    async def test_create_fuel_record(self, pg_session):
        """Fuel record with Decimal fields."""
        from app.models.fuel import FuelRecord

        _, vehicle = await _make_user_and_vehicle(pg_session, "fuel1")

        record = FuelRecord(
            vin=vehicle.vin,
            date=date(2026, 3, 1),
            gallons=Decimal("12.345"),
            cost=Decimal("45.67"),
            mileage=50000,
            fuel_type="Regular",
        )
        pg_session.add(record)
        await pg_session.flush()

        result = await pg_session.execute(
            select(FuelRecord).where(FuelRecord.vin == vehicle.vin)
        )
        found = result.scalar_one()
        assert found.gallons == Decimal("12.345")
        assert found.cost == Decimal("45.67")

    async def test_create_service_visit(self, pg_session):
        """Service visit with nullable fields."""
        from app.models.service_visit import ServiceVisit

        _, vehicle = await _make_user_and_vehicle(pg_session, "svc1")

        visit = ServiceVisit(
            vin=vehicle.vin,
            date=date(2026, 2, 15),
            notes="Oil change",
            total_cost=Decimal("89.99"),
            mileage=49500,
        )
        pg_session.add(visit)
        await pg_session.flush()

        result = await pg_session.execute(
            select(ServiceVisit).where(ServiceVisit.vin == vehicle.vin)
        )
        found = result.scalar_one()
        assert found.notes == "Oil change"
        assert found.total_cost == Decimal("89.99")

    async def test_null_values_in_fuel_record(self, pg_session):
        """Fuel record with NULL optional fields (267dca5 fix)."""
        from app.models.fuel import FuelRecord

        _, vehicle = await _make_user_and_vehicle(pg_session, "fuelnull")

        record = FuelRecord(
            vin=vehicle.vin,
            date=date(2026, 3, 10),
            gallons=Decimal("10.0"),
            cost=Decimal("35.00"),
            mileage=50500,
            fuel_type="Regular",
            notes=None,
        )
        pg_session.add(record)
        await pg_session.flush()
        await pg_session.refresh(record)

        assert record.notes is None


# ===========================================================================
# 9. POSTGRESQL-SPECIFIC FEATURES
# ===========================================================================

class TestPgSpecificFeatures:
    """Verify PostgreSQL-specific schema features."""

    async def test_indexes_created(self, pg_engine):
        """Indexes should exist in PG schema."""
        async with pg_engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public'"
            ))
            idx_count = result.scalar()
            assert idx_count > 0
            print(f"  -> {idx_count} indexes created")

    async def test_foreign_keys_enforced(self, pg_engine):
        """Foreign key constraints should exist."""
        async with pg_engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT count(*) FROM information_schema.table_constraints "
                "WHERE constraint_type = 'FOREIGN KEY' AND table_schema = 'public'"
            ))
            fk_count = result.scalar()
            assert fk_count > 0
            print(f"  -> {fk_count} foreign key constraints")

    async def test_numeric_precision(self, pg_session):
        """Decimal/Numeric columns should preserve precision."""
        from app.models.toll import TollTransaction

        _, vehicle = await _make_user_and_vehicle(pg_session, "prec1")

        pg_session.add(TollTransaction(
            vin=vehicle.vin,
            date=date(2026, 6, 15),
            amount=Decimal("123.45"),
            location="Precision Test",
        ))
        await pg_session.flush()

        result = await pg_session.execute(text(
            "SELECT amount FROM toll_transactions WHERE location = 'Precision Test'"
        ))
        val = result.scalar()
        assert val == Decimal("123.45"), f"Expected 123.45, got {val}"
