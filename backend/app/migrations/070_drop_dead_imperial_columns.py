"""Drop dead legacy imperial columns left by pre-metric migrations.

Added by 003 (fuel_economy_city/highway/combined), 009 (propane_gallons),
021 (tank_size_lb), 047 (last_milestone_notified); superseded by metric-canonical
columns (053) but never removed on the create_all-then-migrate fresh-install path
because 053's idempotency guard short-circuits once create_all has built the
metric columns. No current model declares them; dropping makes fresh installs
match the model. Dialect-aware (native DROP COLUMN — SQLite >=3.35 per 053's
floor, PG), idempotent, forward-only, NON-FATAL. Guarded per column: a column
holding non-NULL values is PRESERVED (never dropped). On an actual DROP error
it RAISES (no swallow) so the runner keeps it unstamped + retryable (R1-H2).
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

DEAD_COLUMNS = {
    "fuel_records": ("propane_gallons", "tank_size_lb"),
    "vehicles": (
        "fuel_economy_city",
        "fuel_economy_highway",
        "fuel_economy_combined",
        "last_milestone_notified",
    ),
}


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    """Drop dead imperial columns that hold no non-NULL values."""
    if engine is None:
        engine = _get_fallback_engine()
    print("Migration 070: drop dead imperial columns (empty only)...")
    for table, columns in DEAD_COLUMNS.items():
        if not inspect(engine).has_table(table):
            continue
        existing = {c["name"] for c in inspect(engine).get_columns(table)}
        for col in columns:
            if col not in existing:
                continue
            with engine.begin() as conn:
                non_null = (
                    conn.execute(
                        text(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NOT NULL')
                    ).scalar()
                    or 0
                )
                if non_null:
                    # Deliberate preservation (guard) — never drop populated data.
                    print(
                        f"  ! {table}.{col} has {non_null} non-NULL value(s) — preserving (NOT dropping); investigate"
                    )
                    continue
                conn.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{col}"'))
                print(f"  - dropped {table}.{col}")
    print("Migration 070 complete.")
    # NOTE (R1-H2): no broad try/except — an ALTER/connection error must raise so the
    # runner leaves 070 unstamped and retryable. Guards (has_table / column-exists /
    # non-NULL count) keep normal runs from raising.


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 070 is forward-only.")


if __name__ == "__main__":
    upgrade()
