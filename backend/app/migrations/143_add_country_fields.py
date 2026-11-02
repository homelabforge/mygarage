"""Add the country columns behind the EU/national profiles (#211).

- ``users.country`` VARCHAR(2), nullable: the person's country (ISO 3166-1
  alpha-2), the default for their vehicles. NULL = not set, today's behaviour.
- ``users.inspection_auto_schedule`` BOOLEAN NOT NULL DEFAULT TRUE: whether the
  periodic technical inspection reminder is kept up to date automatically for
  their vehicles. Shipped here, with the other users column, so the preference
  exists before the engine that reads it lands.
- ``vehicles.registration_country`` VARCHAR(2), nullable: where this vehicle is
  registered when that differs from the owner's country (cross-border
  households).
- ``vehicles.first_registration_date`` DATE, nullable: field B of an EU
  registration certificate, which inspection cadences count from.

Vocabularies are enforced by Pydantic, not by a CHECK. FATAL: the ORM declares
every column and selects it on every vehicle and auth path, so a silent
failure would boot the app against a missing column (066/120's precedent).
``ADD COLUMN ... NOT NULL DEFAULT`` fills existing rows on both SQLite and
PostgreSQL, so no backfill is needed. Idempotent: each column is added only
when absent.
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


def _add_missing(engine: Engine, table: str, columns: tuple[tuple[str, str], ...]) -> None:
    if not inspect(engine).has_table(table):
        return
    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns(table)}
        for name, ddl in columns:
            if name in existing:
                print(f"  → {table}.{name} already exists, skipping")
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            print(f"  ✓ Added {table}.{name}")


def upgrade(engine: Engine | None = None) -> None:
    """Add the four country columns (see module docstring)."""
    if engine is None:
        engine = _get_fallback_engine()

    bool_true = "TRUE" if engine.dialect.name == "postgresql" else "1"
    _add_missing(
        engine,
        "users",
        (
            ("country", "VARCHAR(2)"),
            ("inspection_auto_schedule", f"BOOLEAN NOT NULL DEFAULT {bool_true}"),
        ),
    )
    _add_missing(
        engine,
        "vehicles",
        (
            ("registration_country", "VARCHAR(2)"),
            ("first_registration_date", "DATE"),
        ),
    )


def downgrade() -> None:
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()
