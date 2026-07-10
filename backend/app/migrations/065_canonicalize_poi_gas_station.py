"""Canonicalize the gas-station POI tag: 'fuel_station' -> 'gas_station'.

Two code paths historically wrote different strings for the same concept:
the server-side fuel-record save wrote ``poi_category='fuel_station'`` while
the fuel-form quick-add wrote ``'gas_station'``. The Gas-Stations filter, the
autocomplete usage-ranking, and the vendor-sync exclusion guard all matched
only ``'fuel_station'``, so quick-add-created stations were invisible to them
and were not excluded from vendor sync. We standardize on ``'gas_station'``
(the canonical ``POICategory`` enum member) and re-key the legacy rows here.

FATAL: the post-migration code reads/writes only ``'gas_station'``. If this
UPDATE fails, startup must halt rather than run the new readers against
unmigrated ``'fuel_station'`` rows (which reproduces the original bug).

Idempotent (second run matches zero rows), dialect-neutral (plain UPDATE),
forward-only.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    """Re-key legacy 'fuel_station' poi_category rows to 'gas_station'."""
    if engine is None:
        engine = _get_fallback_engine()

    print("Migration 065: canonicalize poi_category 'fuel_station' -> 'gas_station'...")

    inspector = inspect(engine)
    if not inspector.has_table("address_book"):
        print("  = address_book table absent, skipping")
        print("Migration 065 complete.")
        return

    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE address_book SET poi_category = 'gas_station' "
                "WHERE poi_category = 'fuel_station'"
            )
        )
    print(f"  + Re-keyed {result.rowcount} row(s) to 'gas_station'")
    print("Migration 065 complete.")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 065 is forward-only. The legacy 'fuel_station' value is "
        "retired; there is no meaningful state to restore."
    )


if __name__ == "__main__":
    upgrade()
