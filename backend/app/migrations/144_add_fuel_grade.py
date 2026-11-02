"""Add fuel_records.fuel_grade, the EN 16942 pump label of a fill-up (#211).

A nullable VARCHAR(10) holding a FuelGradeEnum value (E5, E10, E85, B7, B10,
B20, B30, B100, XTL, H2, CNG, LPG, LNG), validated by Pydantic like the
octane / diesel_grade pair of migration 105. NULL on every existing row: the
label is only known for fill-ups logged after this release, and the UI
prefills it from the newest fill-up like the two sibling grade fields.

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

_COLUMNS: tuple[tuple[str, str], ...] = (("fuel_grade", "VARCHAR(10)"),)


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add fuel_records.fuel_grade (nullable VARCHAR(10), no backfill)."""
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
