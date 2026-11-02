"""Add vehicles.identifier_type and vehicles.identifier (#226).

A vehicle without a VIN (a tractor, a mower, a boat with a HIN) is keyed by a
generated "Q" key in `vin`; what people see is `identifier`, and
`identifier_type` says what it is: vin, serial, hin, chassis, asset_tag or none.

identifier_type is NOT NULL DEFAULT 'vin', so every existing vehicle keeps
meaning "the key is the VIN" with no backfill. identifier is a nullable
VARCHAR(64). No CHECK: the vocabulary is validated by Pydantic and read
leniently, and a CHECK would need a SQLite rebuild for nothing.

FATAL: the model declares both and every vehicle query selects them, so a
silent failure would boot the app against missing columns. Idempotent: each
column is added only when absent. Both types are identical on SQLite and
PostgreSQL.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add the two identifier columns to vehicles."""
    if engine is None:
        engine = _get_fallback_engine()

    if not inspect(engine).has_table("vehicles"):
        return

    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns("vehicles")}
        if "identifier_type" not in existing:
            conn.execute(
                text(
                    "ALTER TABLE vehicles ADD COLUMN identifier_type VARCHAR(10) "
                    "NOT NULL DEFAULT 'vin'"
                )
            )
            print("  ✓ Added vehicles.identifier_type (default 'vin')")
        else:
            print("  → identifier_type already exists, skipping")
        if "identifier" not in existing:
            conn.execute(text("ALTER TABLE vehicles ADD COLUMN identifier VARCHAR(64)"))
            print("  ✓ Added vehicles.identifier (nullable)")
        else:
            print("  → identifier already exists, skipping")


def downgrade() -> None:
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()
