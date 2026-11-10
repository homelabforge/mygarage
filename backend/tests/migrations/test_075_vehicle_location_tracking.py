"""Tests for migration 075 — add `vehicles.location_tracking_enabled` opt-out column.

Parameterized over SQLite *and* PostgreSQL via the ``engine_for_migration``
fixture (PG runs skip when ``TEST_DATABASE_URL`` is unset).
"""

from sqlalchemy import inspect, text

from tests.migrations._loader import load_migration


def _make_vehicles(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))


def test_075_adds_column(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO vehicles (vin) VALUES ('1FT0000000000000X')"))
    load_migration("075_vehicle_location_tracking").upgrade(engine)
    insp = inspect(engine)
    assert "location_tracking_enabled" in {c["name"] for c in insp.get_columns("vehicles")}
    with engine.connect() as conn:
        val = conn.execute(text("SELECT location_tracking_enabled FROM vehicles LIMIT 1")).scalar()
    assert bool(val) is True


def test_075_idempotent(engine_for_migration):
    """Second run is a no-op — no raise, no duplicate column."""
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    mod = load_migration("075_vehicle_location_tracking")

    mod.upgrade(engine)
    mod.upgrade(engine)  # must not raise

    insp = inspect(engine)
    cols = [c["name"] for c in insp.get_columns("vehicles")]
    assert cols.count("location_tracking_enabled") == 1


def test_075_missing_table_skips(engine_for_migration):
    """Fresh DB without vehicles table → migration must skip, not raise."""
    _dialect, engine, _url = engine_for_migration
    load_migration("075_vehicle_location_tracking").upgrade(engine)  # no table created
