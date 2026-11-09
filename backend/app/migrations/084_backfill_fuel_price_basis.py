"""Backfill fuel_records.price_basis on rows the importer left NULL (#128).

``price_basis`` names the denominator ``price_per_unit`` is measured against.
Migration 053 introduced the column and populated every row that existed then,
and the record form has always set it — but neither import path (CSV nor JSON
backup) ever did, so every fill-up brought in by an import landed with
``price_basis = NULL``.

That matters because the frontend's ``priceToDisplay`` converts a stored price
into the user's units ONLY when the basis reads ``per_volume``; given NULL it
returns the value untouched. On an imperial account the canonical per-litre
figure was therefore rendered under a "Price/Gal" heading — $2.50/gal was
stored correctly as $0.660/L and then displayed as "0.66".

Fixing the importer stops new rows being created that way but does nothing for
data already imported, which for the reporter is the entire 15-year history
they migrated in. This backfills it.

The CASE is migration 053's rule unchanged, expressed on the metric column
names 053 left behind (``liters``/``propane_liters``/``kwh`` rather than
``gallons``/``propane_gallons``). Scoped to rows that have a price and no
basis: a row without a price has no denominator to name, and a row that
already has one is either correct or a deliberate user choice — neither is
ours to overwrite. That scoping also makes it idempotent, since a second run
matches nothing.

NOT FATAL: no model declares ``price_basis`` non-nullable and every reader
treats it as optional, so a failure here degrades to the pre-existing display
bug rather than booting the app against a schema it cannot use.

Dialect-agnostic: a plain ``UPDATE ... CASE ... WHERE`` valid on both SQLite
and PostgreSQL, so no dialect branch is needed (contrast migration 054).
"""

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = False

_BACKFILL = text("""
    UPDATE fuel_records SET price_basis = CASE
        WHEN kwh IS NOT NULL AND liters IS NULL AND propane_liters IS NULL
            THEN 'per_kwh'
        WHEN propane_liters IS NOT NULL OR liters IS NOT NULL
            THEN 'per_volume'
        ELSE NULL
    END
    WHERE price_basis IS NULL AND price_per_unit IS NOT NULL
""")


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None):
    """Populate price_basis for priced fuel rows that have none."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    inspector = inspect(engine)
    if not inspector.has_table("fuel_records"):
        print("  → fuel_records table absent, skipping price_basis backfill")
        return

    columns = {col["name"] for col in inspector.get_columns("fuel_records")}
    # Guard rather than assume: a database somehow predating 053 has no such
    # column, and the UPDATE would be a hard error instead of a no-op.
    required = {"price_basis", "price_per_unit", "liters", "propane_liters", "kwh"}
    missing = required - columns
    if missing:
        print(f"  → fuel_records missing {sorted(missing)}, skipping price_basis backfill")
        return

    with engine.begin() as conn:
        print("Backfilling fuel_records.price_basis (imported rows)...")
        result = conn.execute(_BACKFILL)
        print(f"  ✓ Set price_basis on {result.rowcount} imported fuel record(s)")


def downgrade():
    """Rollback not supported.

    The prior state is NULL, which is indistinguishable from a row that
    legitimately has no basis, so reversing would have to null rows this never
    touched. Leaving the values is harmless — they are correct, and every
    reader treats the column as optional.
    """
    print("Downgrade not supported for a data backfill")


if __name__ == "__main__":
    upgrade()
