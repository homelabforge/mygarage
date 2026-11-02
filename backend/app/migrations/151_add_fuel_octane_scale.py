"""Add fuel_records.octane_scale, the scale a fill-up's octane was read on (B4).

A nullable VARCHAR(3) holding 'RON' (Europe) or 'AKI' (North America),
validated by Pydantic like octane itself (migration 105). NULL on every
existing row: a past fill-up's scale is unknown, and it is never inferred
from the country settings of today, which may not be the ones it was logged
under. The form defaults a NEW fill-up to the country profile's scale; an
edit keeps the stored pair.

FATAL: the model declares the column and every fuel query selects it, so a
silent failure would boot the app against a missing column (105's
precedent). Idempotent: the column is added only when absent. A VARCHAR is
identical on SQLite and PostgreSQL, so there is no per-dialect type.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_COLUMNS: tuple[tuple[str, str], ...] = (("octane_scale", "VARCHAR(3)"),)


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add fuel_records.octane_scale (nullable VARCHAR(3), no backfill)."""
    if engine is None:
        engine = _get_fallback_engine()

    if not inspect(engine).has_table("fuel_records"):
        return

    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns("fuel_records")}
        for name, ddl in _COLUMNS:
            if name in existing:
                print(f"  → {name} already exists, skipping")
                continue
            conn.execute(text(f"ALTER TABLE fuel_records ADD COLUMN {name} {ddl}"))
            print(f"  ✓ Added fuel_records.{name} (nullable)")


def downgrade() -> None:
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()
