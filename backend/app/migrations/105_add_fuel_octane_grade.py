"""Add ``fuel_records.octane`` and ``fuel_records.diesel_grade`` (#164).

Per-fillup fuel grade: an integer octane rating for gasoline/E85 (AKI or
RON) and a diesel grade ('onroad' | 'offroad' — the US clear-vs-dyed
distinction). Both nullable; validation lives on the input schemas.

FATAL for migration 095's reason: the FuelRecord ORM maps both columns, so
every fuel SELECT includes them and a silent skip would 500 all fuel reads
after the model change.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_COLUMNS: tuple[tuple[str, str], ...] = (
    ("octane", "INTEGER"),
    ("diesel_grade", "VARCHAR(10)"),
)


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    inspector = inspect(engine)
    if not inspector.has_table("fuel_records"):
        return

    existing = {c["name"] for c in inspector.get_columns("fuel_records")}
    missing = [(name, ddl) for name, ddl in _COLUMNS if name not in existing]
    if not missing:
        print("✓ fuel_records octane/diesel_grade already present")
        return

    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE fuel_records ADD COLUMN {name} {ddl}"))
            print(f"✓ Added fuel_records.{name}")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 105 is forward-only.")


if __name__ == "__main__":
    upgrade()
