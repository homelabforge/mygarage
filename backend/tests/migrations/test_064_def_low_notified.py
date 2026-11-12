"""Tests for migration 064 — add `vehicles.def_low_notified_at` dedup column.

Parameterized over SQLite *and* PostgreSQL via the ``engine_for_migration``
fixture (PG runs skip when ``TEST_DATABASE_URL`` is unset).
"""

from sqlalchemy import inspect, text

from tests.migrations._loader import load_migration


def _make_vehicles(engine):
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY"
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE vehicles (id {pk}, vin VARCHAR(17) UNIQUE NOT NULL)"))


def test_064_adds_column(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)

    load_migration("064_def_low_notified").upgrade(engine)

    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("vehicles")}
    assert "def_low_notified_at" in cols


def test_064_column_is_writable_and_nullable(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    load_migration("064_def_low_notified").upgrade(engine)

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO vehicles (vin) VALUES ('1HGCM82633A004352')"))
        row = conn.execute(
            text("SELECT def_low_notified_at FROM vehicles WHERE vin = '1HGCM82633A004352'")
        ).fetchone()
    assert row is not None
    assert row[0] is None

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE vehicles SET def_low_notified_at = "
                "CURRENT_TIMESTAMP WHERE vin = '1HGCM82633A004352'"
            )
        )
        row = conn.execute(
            text("SELECT def_low_notified_at FROM vehicles WHERE vin = '1HGCM82633A004352'")
        ).fetchone()
    assert row is not None
    assert row[0] is not None


def test_064_idempotent(engine_for_migration):
    """Second run is a no-op — no raise, no duplicate column."""
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    mod = load_migration("064_def_low_notified")

    mod.upgrade(engine)
    mod.upgrade(engine)  # must not raise

    insp = inspect(engine)
    cols = [c["name"] for c in insp.get_columns("vehicles")]
    assert cols.count("def_low_notified_at") == 1


def test_064_missing_table_skips(engine_for_migration):
    """Fresh DB without vehicles table → migration must skip, not raise."""
    _dialect, engine, _url = engine_for_migration
    load_migration("064_def_low_notified").upgrade(engine)  # no table created
