"""The #307 upgrade path: 161, 162 and 163 on the real runner, and the boot check.

A disk coming straight from 3.11.1 or older still has 161 pending. Shipped as
in 3.11.2, 161 priced its stranded visit usages date-blind and 162 then
stamped them not-estimated, frozen wrong. Now 161 leaves those for 163, which
prices them as of the visit's date. A failing 161 is non-FATAL, so the runner
stops there and the app would boot without ``cost_estimated``; init_db
refuses instead.

Each test builds the full schema with create_all, drops the new column (the
pre-162 shape), stamps the history the case needs and runs the real migrations
directory. Same numbers as 163's own tests: a July 2025 purchase of 5 for
$30.00, a June 2026 purchase of 5 for $37.45, a visit on 2025-07-17 using 5.
"""

import importlib
import types
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, MetaData, inspect, text
from sqlalchemy.orm import Session

from app.migrations.runner import MigrationRunner, run_migrations
from tests.migrations._loader import MIGRATIONS_DIR, load_migration

pytestmark = pytest.mark.migrations

_VIN = "1HGCM82633A004352"
_COLUMN = "cost_estimated"
_161 = "161_price_unpriced_supply_usages"
_162 = "162_add_supply_usage_cost_estimated"
_163 = "163_price_visit_usages_as_of"

#: usage id -> what it is, in the seeded disk.
_OIL = 1  # supply 1 (both purchases), on visit 1
_LATE = 2  # supply 2 (June 2026 purchase only), on visit 2
_ADJUST = 3  # supply 1, standalone adjustment
_FROZEN = 4  # supply 1, on visit 1, a frozen unit and no cost


def _metadata() -> MetaData:
    """Every model registered, so create_all builds the whole schema."""
    import app.models as models_pkg

    for py in sorted(Path(models_pkg.__file__).parent.glob("*.py")):
        if py.stem != "__init__":
            importlib.import_module(f"app.models.{py.stem}")
    from app.database import Base

    return Base.metadata


def _old_disk(engine: Engine) -> None:
    """The full schema without ``cost_estimated``, and the #307 rows, all unpriced."""
    _metadata().create_all(engine)
    from app.models.service_line_item import ServiceLineItem
    from app.models.service_visit import ServiceVisit
    from app.models.supply import Supply, SupplyPurchase, SupplyUsage
    from app.models.vehicle import Vehicle

    with Session(engine) as session:
        session.add(Vehicle(vin=_VIN, nickname="Kawasaki", vehicle_type="Motorcycle"))
        session.add_all(
            [
                Supply(id=1, name="Engine oil", unit_type="count"),
                Supply(id=2, name="Oil filter", unit_type="count"),
            ]
        )
        session.flush()
        session.add_all(
            [
                SupplyPurchase(
                    supply_id=1,
                    date=date(2025, 7, 10),
                    quantity=Decimal(5),
                    total_cost=Decimal("30.00"),
                ),
                SupplyPurchase(
                    supply_id=1,
                    date=date(2026, 6, 2),
                    quantity=Decimal(5),
                    total_cost=Decimal("37.45"),
                ),
                SupplyPurchase(
                    supply_id=2,
                    date=date(2026, 6, 2),
                    quantity=Decimal(5),
                    total_cost=Decimal("37.45"),
                ),
            ]
        )
        for vid, labour in ((1, "40.00"), (2, "20.00")):
            session.add(
                ServiceVisit(id=vid, vin=_VIN, date=date(2025, 7, 17), total_cost=Decimal(labour))
            )
            session.flush()
            session.add(
                ServiceLineItem(id=vid, visit_id=vid, description="Oil", cost=Decimal(labour))
            )
        session.flush()
        session.add_all(
            [
                SupplyUsage(id=_OIL, supply_id=1, service_line_item_id=1, quantity=Decimal(5)),
                SupplyUsage(id=_LATE, supply_id=2, service_line_item_id=2, quantity=Decimal(5)),
                SupplyUsage(id=_ADJUST, supply_id=1, quantity=Decimal(2)),
                SupplyUsage(
                    id=_FROZEN,
                    supply_id=1,
                    service_line_item_id=1,
                    quantity=Decimal(2),
                    unit_cost_snapshot=Decimal("5.0000"),
                ),
            ]
        )
        session.commit()
    if _COLUMN in _columns(engine):
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE supply_usages DROP COLUMN {_COLUMN}"))


def _stamp_below(url: str, first_pending: str) -> None:
    """Stamp every real migration that sorts before `first_pending`, as an old disk has."""
    runner = MigrationRunner(url, MIGRATIONS_DIR)
    try:
        runner._ensure_migration_tracking_table()
        stems = [name for name, _ in runner._discover_migrations() if name < first_pending]
        runner._mark_migrations_applied(stems)
    finally:
        runner.engine.dispose()


def _columns(engine: Engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("supply_usages")}


def _applied(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return set(conn.execute(text("SELECT migration_name FROM schema_migrations")).scalars())


def _usages(engine: Engine) -> dict[int, tuple[Decimal | None, Decimal | None, bool]]:
    """usage id -> (unit, cost, estimated)."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT id, unit_cost_snapshot, cost_snapshot, {_COLUMN} FROM supply_usages "
                "ORDER BY id"
            )
        ).all()
    return {
        uid: (
            None if unit is None else Decimal(str(unit)),
            None if cost is None else Decimal(str(cost)),
            bool(estimated),
        )
        for uid, unit, cost, estimated in rows
    }


def _totals(engine: Engine) -> dict[int, Decimal]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, total_cost FROM service_visits ORDER BY id")).all()
    return {vid: Decimal(str(total)) for vid, total in rows}


@pytest.fixture
def boot(
    engine_for_migration: tuple[str, Engine, str], monkeypatch: pytest.MonkeyPatch
) -> Callable[[], Awaitable[None]]:
    """The app's own startup against the test database, on the real migrations dir.

    On PG the app engine already points at the sidecar. On SQLite it's swapped
    for one on the test's file, as the runner tests do.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import database
    from app.config import settings

    dialect, _engine, url = engine_for_migration
    if dialect == "sqlite":
        app_url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        monkeypatch.setattr(database, "engine", create_async_engine(app_url))
        monkeypatch.setattr(settings, "database_url", app_url)
    _metadata()

    async def run() -> None:
        try:
            await database.init_db()
        finally:
            # The app engine pools; leave none of its connections behind.
            await database.engine.dispose()

    return run


def _failing_161(monkeypatch: pytest.MonkeyPatch) -> None:
    """161 fails, non-FATAL, as a bug in it on some disk's data would."""
    load = MigrationRunner._load_module

    def load_module(self: MigrationRunner, name: str, path: Path) -> types.ModuleType:
        if name != _161:
            return load(self, name, path)
        module = types.ModuleType(name)

        def upgrade(conn: object) -> None:
            raise RuntimeError("injected 161 failure")

        module.__dict__.update(FATAL=False, upgrade=upgrade)
        return module

    monkeypatch.setattr(MigrationRunner, "_load_module", load_module)


async def test_a_fresh_install_has_the_column_and_boots(engine_for_migration, boot) -> None:
    _dialect, engine, _url = engine_for_migration
    await boot()
    assert _COLUMN in _columns(engine)
    assert {_161, _162, _163} <= _applied(engine)


def test_an_upgrade_with_161_stamped_freezes_nothing_new(engine_for_migration) -> None:
    """A 3.11.2 disk. 161 never runs again: the adjustment it would price stays as it is.

    163 still prices a stranded visit usage, as of its visit.
    """
    _dialect, engine, url = engine_for_migration
    _old_disk(engine)
    _stamp_below(url, _162)
    run_migrations(url, MIGRATIONS_DIR)

    assert {_162, _163} <= _applied(engine)
    usages = _usages(engine)
    assert usages[_OIL] == (Decimal("6.0000"), Decimal("30.00"), False)
    assert usages[_LATE] == (Decimal("7.4900"), Decimal("37.45"), True)
    assert usages[_ADJUST] == (None, None, False)
    assert usages[_FROZEN] == (Decimal("5.0000"), None, False)
    # Visit 1 counts the oil only: the frozen-unit row still has no cost.
    assert _totals(engine) == {1: Decimal("70.00"), 2: Decimal("57.45")}


async def test_a_direct_upgrade_with_161_pending_prices_as_of_the_visit(
    engine_for_migration, boot
) -> None:
    """Straight from 3.11.1 or older, through the app's startup.

    3.11.2's 161 would have priced the oil at 67.45 / 10 over both purchases
    (33.73) and 162 would have frozen it there.
    """
    _dialect, engine, url = engine_for_migration
    _old_disk(engine)
    _stamp_below(url, _161)
    await boot()

    assert {_161, _162, _163} <= _applied(engine)
    usages = _usages(engine)
    assert usages[_OIL] == (Decimal("6.0000"), Decimal("30.00"), False)
    assert usages[_LATE] == (Decimal("7.4900"), Decimal("37.45"), True)
    # 161 still prices these: an adjustment date-blind, a frozen unit by itself.
    assert usages[_ADJUST] == (Decimal("6.7450"), Decimal("13.49"), False)
    assert usages[_FROZEN] == (Decimal("5.0000"), Decimal("10.00"), False)
    assert _totals(engine) == {1: Decimal("80.00"), 2: Decimal("57.45")}


async def test_a_failed_161_on_an_old_schema_stops_startup(
    engine_for_migration, boot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner shrugs off a non-FATAL failure and skips 162; init_db must not."""
    _dialect, engine, url = engine_for_migration
    _old_disk(engine)
    _stamp_below(url, _161)
    _failing_161(monkeypatch)

    with pytest.raises(RuntimeError, match=_COLUMN) as raised:
        await boot()

    assert _161 in str(raised.value)
    # The refusal is init_db's own, not the migration error passed through.
    assert "injected 161 failure" not in str(raised.value)
    assert _COLUMN not in _columns(engine)
    assert not {_161, _162, _163} & _applied(engine)


def test_a_second_run_is_a_no_op(engine_for_migration) -> None:
    _dialect, engine, url = engine_for_migration
    _old_disk(engine)
    _stamp_below(url, _161)
    run_migrations(url, MIGRATIONS_DIR)
    usages, totals, applied = _usages(engine), _totals(engine), _applied(engine)

    # A purchase that would change the late oil's as-of price, then everything again.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO supply_purchases (supply_id, date, quantity, total_cost) "
                "VALUES (2, :d, 5, 25)"
            ),
            {"d": "2025-01-01"},  # as text: sqlite3's date adapter is deprecated
        )
    run_migrations(url, MIGRATIONS_DIR)
    load_migration(_162).upgrade(engine)
    for stem in (_161, _163):
        with engine.begin() as conn:
            load_migration(stem).upgrade(conn=conn)

    assert _usages(engine) == usages
    assert _totals(engine) == totals
    assert _applied(engine) == applied
    assert usages[_LATE] == (Decimal("7.4900"), Decimal("37.45"), True)
