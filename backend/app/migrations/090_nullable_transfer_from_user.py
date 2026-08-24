"""Allow NULL vehicle_transfers.from_user_id for ownerless assignments.

Vehicles may have ``user_id IS NULL`` (pre-multi-user rows, auth-mode none,
archived orphans). Admin transfer previously rejected those with
"Vehicle has no current owner". Initial ownership assignment needs an audit
row whose ``from_user_id`` is NULL.

FATAL: the ORM model declares ``from_user_id`` nullable; a NOT NULL column
would reject assignment commits after the service change.

Dialect-aware:
  - **PostgreSQL:** ``ALTER COLUMN ... DROP NOT NULL``.
  - **SQLite:** table rebuild (SQLite cannot drop NOT NULL in place).
    ``vehicle_transfers`` has no inbound FKs, so a simple rebuild is safe.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_vehicle_transfers_vehicle_vin "
    "ON vehicle_transfers (vehicle_vin)",
    "CREATE INDEX IF NOT EXISTS ix_vehicle_transfers_from_user_id "
    "ON vehicle_transfers (from_user_id)",
    "CREATE INDEX IF NOT EXISTS ix_vehicle_transfers_to_user_id "
    "ON vehicle_transfers (to_user_id)",
    "CREATE INDEX IF NOT EXISTS ix_vehicle_transfers_transferred_at "
    "ON vehicle_transfers (transferred_at)",
)


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    """Make vehicle_transfers.from_user_id nullable."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("vehicle_transfers"):
        print("  → vehicle_transfers missing; skip (run 037 first)")
        return

    columns = {c["name"]: c for c in inspector.get_columns("vehicle_transfers")}
    if "from_user_id" not in columns:
        print("  → from_user_id missing; skip")
        return
    if columns["from_user_id"]["nullable"]:
        print("  → vehicle_transfers.from_user_id already nullable, skipping")
        return

    print("Making vehicle_transfers.from_user_id nullable…")
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE vehicle_transfers "
                    "ALTER COLUMN from_user_id DROP NOT NULL"
                )
            )
            print("  ✓ Dropped NOT NULL on vehicle_transfers.from_user_id")
    else:
        _run_sqlite(engine)

    print("✓ vehicle_transfers.from_user_id nullable migration completed")


def _run_sqlite(engine) -> None:
    """SQLite: rebuild vehicle_transfers with nullable from_user_id."""
    raw = engine.raw_connection()
    try:
        raw.execute("PRAGMA foreign_keys = OFF")
        raw.execute("BEGIN")
        try:
            raw.execute(
                """
                CREATE TABLE vehicle_transfers_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vehicle_vin VARCHAR(17) NOT NULL,
                    from_user_id INTEGER,
                    to_user_id INTEGER NOT NULL,
                    transferred_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    transferred_by INTEGER NOT NULL,
                    transfer_notes TEXT,
                    data_included TEXT,
                    FOREIGN KEY (vehicle_vin) REFERENCES vehicles(vin) ON DELETE CASCADE,
                    FOREIGN KEY (from_user_id) REFERENCES users(id),
                    FOREIGN KEY (to_user_id) REFERENCES users(id),
                    FOREIGN KEY (transferred_by) REFERENCES users(id)
                )
                """
            )
            raw.execute(
                """
                INSERT INTO vehicle_transfers_new (
                    id, vehicle_vin, from_user_id, to_user_id,
                    transferred_at, transferred_by, transfer_notes, data_included
                )
                SELECT
                    id, vehicle_vin, from_user_id, to_user_id,
                    transferred_at, transferred_by, transfer_notes, data_included
                FROM vehicle_transfers
                """
            )
            raw.execute("DROP TABLE vehicle_transfers")
            raw.execute("ALTER TABLE vehicle_transfers_new RENAME TO vehicle_transfers")
            for stmt in _INDEXES:
                raw.execute(stmt)
            check = raw.execute("PRAGMA foreign_key_check").fetchall()
            if check:
                raise RuntimeError(
                    f"foreign_key_check failed after vehicle_transfers rebuild: {check}"
                )
            raw.execute("COMMIT")
            print("  ✓ Rebuilt vehicle_transfers with nullable from_user_id")
        except Exception:
            raw.execute("ROLLBACK")
            raise
    finally:
        try:
            raw.execute("PRAGMA foreign_keys = ON")
        finally:
            raw.close()


def downgrade() -> None:
    print("Downgrade not supported (would reject ownerless assignment history)")


if __name__ == "__main__":
    upgrade()
