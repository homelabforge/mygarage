"""Add vehicle_maintenance_rules.lead_days (#211).

How many days before its due date a reminder of this rule may be acted on:
the French contrôle technique can be done in the six months before the
deadline, the Dutch APK two months before. The automatic inspection engine
writes it from the country profile; the UI shows "can be done from" and the
scheduler sends one notification when that window opens. NULL means no
window, which is every rule that exists today, so there is no backfill.

FATAL: the model declares the column and every reminder read embeds its
rule, so a silent failure would boot the app against a missing column.
Idempotent: the column is added only when absent. An INTEGER is the same on
SQLite and PostgreSQL, so there is no per-dialect type.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_TABLE = "vehicle_maintenance_rules"
_COLUMNS: tuple[tuple[str, str], ...] = (("lead_days", "INTEGER"),)


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add vehicle_maintenance_rules.lead_days (nullable INTEGER, no backfill)."""
    if engine is None:
        engine = _get_fallback_engine()

    if not inspect(engine).has_table(_TABLE):
        return

    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns(_TABLE)}
        for name, ddl in _COLUMNS:
            if name in existing:
                print(f"  → {name} already exists, skipping")
                continue
            conn.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN {name} {ddl}"))
            print(f"  ✓ Added {_TABLE}.{name} (nullable)")


def downgrade() -> None:
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()
