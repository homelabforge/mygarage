"""Allow NULL tire_readings.tread_depth_mm for pressure-only readings.

Issue #152's reporter tracks a slow pressure leak and owns no tread gauge.
``tire_readings.tread_depth_mm`` was NOT NULL while ``odometer_km`` and
``pressure_kpa`` were both optional, so there was no way to record a pressure
at all: the schema demanded a measurement the user cannot take.

FATAL: the ORM model declares the column nullable and the API accepts a reading
without one. A log-and-continue failure would boot the app against a schema that
disagrees with the model, and every pressure-only POST would fail at INSERT with
a NOT NULL constraint violation after passing validation.

Dialect-aware:
  - **PostgreSQL:** ``ALTER COLUMN ... DROP NOT NULL``.
  - **SQLite:** table rebuild (SQLite has no ALTER COLUMN). Nothing references
    ``tire_readings``, so the DROP/RENAME cannot orphan an inbound FK; its own
    two outbound FKs (``tire_id -> tires.id``, ``vin -> vehicles.vin``, both
    ON DELETE CASCADE) and both indexes (``idx_tire_readings_tire``,
    ``idx_tire_readings_vin``) are recreated and then verified with
    ``PRAGMA foreign_key_check``.

The rebuilt table declares its foreign keys as table-level ``FOREIGN KEY (...)``
clauses where 085 wrote them inline on the column. Identical to SQLite (the
``foreign_key_list`` pragma reports ``CASCADE`` either way), NOT identical to
SQLAlchemy: its SQLite reflection parses ``ON DELETE`` only out of the
table-level form, so an inline-declared cascade reflects as
``options: {}``. ``tests/migrations/test_schema_parity.py`` compares reflected
``ondelete``, and ``Base.metadata.create_all`` emits the table-level form, so
the rebuilt table is the one that MATCHES the model. Measured, not assumed:
085's inline form reflects no ondelete while the pragma shows the cascade
active.

Idempotent: the current nullability is read first and an already-nullable column
is a no-op. That guard is load-bearing on SQLite rather than decorative, for the
reason 093 documents at length: pysqlite autocommits DDL outside the enclosing
block, and the runner stamps ``schema_migrations`` in a separate transaction
from ``upgrade``, so a crash in that window re-runs an already-committed
migration on the next boot. Without the guard the second run would rebuild a
table that no longer has the NOT NULL it is looking for.

This migration widens a constraint and copies every column across, so it loses
no data and needs no backfill. Existing rows keep the tread they were recorded
with; only new rows may omit one.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_tire_readings_tire ON tire_readings (tire_id)",
    "CREATE INDEX IF NOT EXISTS idx_tire_readings_vin ON tire_readings (vin)",
)


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    """Make tire_readings.tread_depth_mm nullable."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("tire_readings"):
        print("  → tire_readings missing; skip (run 085 first)")
        return

    columns = {c["name"]: c for c in inspector.get_columns("tire_readings")}
    if "tread_depth_mm" not in columns:
        print("  → tire_readings.tread_depth_mm missing; skip")
        return
    if columns["tread_depth_mm"]["nullable"]:
        print("  → tire_readings.tread_depth_mm already nullable, skipping")
        return

    print("Making tire_readings.tread_depth_mm nullable…")
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE tire_readings ALTER COLUMN tread_depth_mm DROP NOT NULL")
            )
            print("  ✓ Dropped NOT NULL on tire_readings.tread_depth_mm")
    else:
        _run_sqlite(engine)

    print("✓ tire_readings.tread_depth_mm nullable migration completed")


def _run_sqlite(engine) -> None:
    """SQLite: rebuild tire_readings with a nullable tread_depth_mm."""
    raw = engine.raw_connection()
    try:
        raw.execute("PRAGMA foreign_keys = OFF")
        raw.execute("BEGIN")
        try:
            raw.execute(
                """
                CREATE TABLE tire_readings_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tire_id INTEGER NOT NULL,
                    vin VARCHAR(17) NOT NULL,
                    position VARCHAR(10) NOT NULL,
                    recorded_at DATE NOT NULL,
                    odometer_km NUMERIC(10, 2),
                    tread_depth_mm NUMERIC(5, 2),
                    pressure_kpa NUMERIC(7, 2),
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tire_id) REFERENCES tires(id) ON DELETE CASCADE,
                    FOREIGN KEY (vin) REFERENCES vehicles(vin) ON DELETE CASCADE
                )
                """
            )
            raw.execute(
                """
                INSERT INTO tire_readings_new (
                    id, tire_id, vin, position, recorded_at,
                    odometer_km, tread_depth_mm, pressure_kpa, notes, created_at
                )
                SELECT
                    id, tire_id, vin, position, recorded_at,
                    odometer_km, tread_depth_mm, pressure_kpa, notes, created_at
                FROM tire_readings
                """
            )
            raw.execute("DROP TABLE tire_readings")
            raw.execute("ALTER TABLE tire_readings_new RENAME TO tire_readings")
            for stmt in _INDEXES:
                raw.execute(stmt)
            check = raw.execute("PRAGMA foreign_key_check").fetchall()
            if check:
                raise RuntimeError(f"foreign_key_check failed after tire_readings rebuild: {check}")
            raw.execute("COMMIT")
            print("  ✓ Rebuilt tire_readings with nullable tread_depth_mm")
        except Exception:
            raw.execute("ROLLBACK")
            raise
    finally:
        try:
            raw.execute("PRAGMA foreign_keys = ON")
        finally:
            raw.close()


def downgrade() -> None:
    print("Downgrade not supported (would reject every pressure-only reading)")


if __name__ == "__main__":
    upgrade()
