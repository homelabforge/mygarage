"""Add ``vehicles.fuel_filter_part_number`` to the maintenance specs.

Deliberately not gated on fuel type, though a diesel is what prompted it. A
6.7 Cummins carries two serviceable fuel filters and they are a scheduled item;
a modern petrol car usually has a lifetime in-tank filter and never needs one.
But "usually" is not "never": older petrol vehicles run serviceable inline
filters, and a column that exists only for diesels cannot record those. The card
renders a spec only when it holds a value, so a vehicle that has no fuel filter
simply never shows the row.

FATAL for migration 095's reason: the Vehicle ORM maps this column, so every
vehicle SELECT includes it and a silent skip would 500 all vehicle reads after
the model change.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True

#: Matches ``oil_filter_part_number``: part numbers are short alphanumeric
#: strings, and the two fields are entered side by side.
_COLUMNS: tuple[tuple[str, str], ...] = (("fuel_filter_part_number", "VARCHAR(50)"),)


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("vehicles"):
        return

    existing = {c["name"] for c in inspector.get_columns("vehicles")}
    missing = [(name, ddl) for name, ddl in _COLUMNS if name not in existing]
    if not missing:
        print("✓ vehicles.fuel_filter_part_number already present")
        return

    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE vehicles ADD COLUMN {name} {ddl}"))
            print(f"✓ Added vehicles.{name}")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 099 is forward-only.")


if __name__ == "__main__":
    upgrade()
