"""Backfill-normalize existing vehicle fuel types.

Why now: Task 1 (commit ``1c66f27``) added a normalizing validator on
``VehicleCreate``/``VehicleUpdate`` (``app/constants/fuel.py``'s
``normalize_fuel_type()``), so every *new* write to ``vehicles.fuel_type``
/ ``vehicles.fuel_type_secondary`` lands canonical. Rows written before
that validator existed may still carry mixed-case values (``"Diesel"``)
or aliases (``"Gas"``) — this migration backfills those in place using
the same vocabulary current at write time.

For a *migration* it's fine to import ``normalize_fuel_type`` from the
app: this normalizes data using the live vocabulary, which is the
intent (unlike migration 062's param-class mapping, which is explicitly
required to freeze its own copy).

For each row: normalize ``fuel_type`` and ``fuel_type_secondary``; write
back only when the normalized value differs from the stored one.
Unrecognized values (no match in the normalization map) are left
untouched and printed as a warning — they simply won't satisfy any
capability gate, which is a safe default. NULL and empty-string values
are left untouched. Idempotent by construction (second run changes
nothing), dialect-aware (SQLite + PostgreSQL), guarded against the
``vehicles`` table being absent.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

from app.constants.fuel import normalize_fuel_type


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Normalize legacy `vehicles.fuel_type` / `fuel_type_secondary` values."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    print("Migration 061: normalize vehicle fuel types...")

    if not inspect(engine).has_table("vehicles"):
        print("  = vehicles table absent, skipping")
        print("Migration 061 complete.")
        return

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT vin, fuel_type, fuel_type_secondary FROM vehicles")
        ).fetchall()

        updated = 0
        for vin, fuel_type, fuel_type_secondary in rows:
            changes: dict[str, str] = {}

            for column, raw in (
                ("fuel_type", fuel_type),
                ("fuel_type_secondary", fuel_type_secondary),
            ):
                if not raw:
                    continue
                normalized = normalize_fuel_type(raw)
                if normalized is None:
                    print(f"  ! {vin}: unrecognized {column}={raw!r}, leaving untouched")
                    continue
                if normalized.value != raw:
                    changes[column] = normalized.value

            if not changes:
                continue

            set_clause = ", ".join(f"{col} = :{col}" for col in changes)
            conn.execute(
                text(f"UPDATE vehicles SET {set_clause} WHERE vin = :vin"),
                {**changes, "vin": vin},
            )
            updated += 1
            print(f"  - {vin}: normalized {list(changes.keys())}")

    print(f"  {updated} row(s) normalized out of {len(rows)}")
    print("Migration 061 complete.")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 061 is forward-only. Normalization is a data cleanup; the "
        "original mixed-case/alias strings are not preserved."
    )


if __name__ == "__main__":
    upgrade()
