"""Retire the legacy `fuel_records.fuel_type` free-text column.

Migration 054 introduced `fuel_type_used` (canonical `FuelTypeEnum`) and
kept `fuel_type` as a compatibility alias "for one release", with the
service layer mirroring between the two. That release has long since
shipped, and the alias was actively harmful: the mirror only copies
legacy to canonical when the free text happens to sit on the enum
vocabulary, so the propane form's hardcoded "Propane" (canonical spelling:
`propane_lpg`) left `fuel_type_used` NULL on every record it wrote.

Backfills `fuel_type_used` from the legacy column wherever it is still
NULL, normalizing through the same `normalize_fuel_type` helper the rest
of the app uses, then drops the column.

LOSSY: back up before running. Free text that does not normalize to the
enum (nothing in a post-054 database, but an importer or a hand-edited
row could produce it) is recorded as `other` rather than being carried
across verbatim, and the original string is gone once the column drops.

FATAL: a partial run would leave records with neither a legacy value nor
a canonical one, which reads as "fuel type never recorded" rather than as
a failed migration.

SQLite note: `ALTER TABLE ... DROP COLUMN` needs SQLite >= 3.35 (Python
3.14 ships far newer) and refuses when an index or CHECK constraint names
the column. Nothing on `fuel_records` references `fuel_type` (the only
CHECK is on `price_basis`), so the rebuild-all pattern this project
normally needs for SQLite column removal is not required here. SQLite
itself enforces that: it raises rather than dropping a still-referenced
column, and the surrounding transaction takes the backfill back out with
it, so a future index on `fuel_type` cannot turn into silent data loss.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.constants.fuel import FuelTypeEnum, normalize_fuel_type

FATAL = True


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
    if not inspector.has_table("fuel_records"):
        return

    columns = {col["name"] for col in inspector.get_columns("fuel_records")}
    if "fuel_type" not in columns:
        print("✓ fuel_records.fuel_type already dropped")
        return
    if "fuel_type_used" not in columns:
        raise RuntimeError("fuel_records.fuel_type_used is missing — migration 054 must run first")

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, fuel_type FROM fuel_records "
                "WHERE fuel_type IS NOT NULL AND fuel_type_used IS NULL"
            )
        ).fetchall()

        backfilled = 0
        coerced = 0
        for record_id, legacy in rows:
            normalized = normalize_fuel_type(legacy)
            if normalized is None:
                normalized = FuelTypeEnum.OTHER
                coerced += 1
                print(
                    f"  ! fuel record {record_id}: {legacy!r} is not on the enum, storing 'other'"
                )
            conn.execute(
                text("UPDATE fuel_records SET fuel_type_used = :v WHERE id = :id"),
                {"v": normalized.value, "id": record_id},
            )
            backfilled += 1

        print(
            f"✓ Backfilled fuel_type_used on {backfilled} record(s) ({coerced} coerced to 'other')"
        )

        conn.execute(text("ALTER TABLE fuel_records DROP COLUMN fuel_type"))
        print("✓ Dropped fuel_records.fuel_type")

    print("✓ Migration 089 (retire legacy fuel_type) completed")


def downgrade() -> None:
    print("Downgrade not supported — restore from backup")


if __name__ == "__main__":
    upgrade()
