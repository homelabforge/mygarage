"""Extended fuel tracking — issue #69.

Additive schema for richer per-fillup metadata + user-scoped form defaults.
No DROP COLUMN, no ALTER COLUMN — every change is purely add + backfill.

Concepts (all stored as VARCHAR(20), validated at the Pydantic layer):
- payment method, trip type — fixed enums
- fuel type — three columns: vehicle primary capability, vehicle secondary
  capability, fill-up actual fuel dispensed

What this migration adds:
1. `vehicles.fuel_type_secondary`              — optional secondary capability
2. `users.default_payment_method`              — per-user form default
3. `users.default_trip_type`                   — per-user form default
4. `fuel_records.filled_at`                    — optional fill-up timestamp
5. `fuel_records.station_address_book_id`      — FK to address_book (POI)
6. `fuel_records.station_name_freetext`        — freetext fallback / one-time-visit
7. `fuel_records.driver_user_id`               — FK to users (household)
8. `fuel_records.driver_name_freetext`         — freetext fallback
9. `fuel_records.payment_method`               — enum
10. `fuel_records.trip_type`                   — enum
11. `fuel_records.outside_temp_c`              — Celsius (canonical)
12. `fuel_records.obc_l_per_100km`             — OBC reported consumption
13. `fuel_records.obc_avg_speed_kmh`           — OBC reported avg speed
14. `fuel_records.obc_trip_duration_s`         — OBC reported duration
15. `fuel_records.fuel_type_used`              — actual fuel dispensed (multi-fuel only)
16. Backfill `vehicles.fuel_type` & `fuel_records.fuel_type` to enum vocabulary
17. Indexes for new query paths

The migration is idempotent: re-running is a no-op via column-existence
checks before each ALTER TABLE, and the backfill skips rows whose value is
already on a valid enum.

Why not FATAL: this is purely additive, so a partial-apply at worst leaves
some unbackfilled rows that the next run will pick up. No reason to halt
startup if a single ALTER fails on a corner-case dialect.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

logger = logging.getLogger(__name__)


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


# ---------------------------------------------------------------------------
#  Column definitions — single source of truth for the additive ALTERs.
#  Each entry: (table, column, type_sql)
# ---------------------------------------------------------------------------

_NEW_COLUMNS: list[tuple[str, str, str]] = [
    # Vehicles — secondary fuel capability
    ("vehicles", "fuel_type_secondary", "VARCHAR(20)"),
    # Users — per-user fuel-form defaults
    ("users", "default_payment_method", "VARCHAR(20)"),
    ("users", "default_trip_type", "VARCHAR(20)"),
    # Fuel records — extended metadata
    # ``DATETIME`` is the SQLite-style spelling. ``_translate_type`` rewrites
    # it to ``TIMESTAMP`` for PG at apply time (PG rejects the literal
    # ``DATETIME`` keyword).
    ("fuel_records", "filled_at", "DATETIME"),
    ("fuel_records", "station_address_book_id", "INTEGER"),
    ("fuel_records", "station_name_freetext", "VARCHAR(150)"),
    ("fuel_records", "driver_user_id", "INTEGER"),
    ("fuel_records", "driver_name_freetext", "VARCHAR(100)"),
    ("fuel_records", "payment_method", "VARCHAR(20)"),
    ("fuel_records", "trip_type", "VARCHAR(20)"),
    ("fuel_records", "outside_temp_c", "NUMERIC(4,1)"),
    ("fuel_records", "obc_l_per_100km", "NUMERIC(5,2)"),
    ("fuel_records", "obc_avg_speed_kmh", "NUMERIC(5,1)"),
    ("fuel_records", "obc_trip_duration_s", "INTEGER"),
    ("fuel_records", "fuel_type_used", "VARCHAR(20)"),
]


# SQLite-style → dialect-specific type translations.
# Only types actually used in _NEW_COLUMNS need entries.
_PG_TYPE_REWRITES: dict[str, str] = {
    "DATETIME": "TIMESTAMP",
}


def _translate_type(sql_type: str, dialect: str) -> str:
    """Translate a SQLite-style column type spelling to the target dialect.

    The migration keeps ``_NEW_COLUMNS`` in SQLite spelling (the dev DB)
    and translates at apply time. PG accepts most types verbatim, but
    rejects ``DATETIME`` — it wants ``TIMESTAMP``. Anything not in the
    rewrite table passes through unchanged.
    """
    if dialect != "postgresql":
        return sql_type
    return _PG_TYPE_REWRITES.get(sql_type.upper(), sql_type)


# (constraint_name, ALTER TABLE statement) pairs used by _ensure_pg_fk_constraints.
# Statements omit ``IF NOT EXISTS`` (PG doesn't support it on ADD CONSTRAINT
# in any version) and rely on the caller's information_schema check for
# idempotency.
_PG_FK_CONSTRAINTS: list[tuple[str, str]] = [
    (
        "fk_fuel_records_station_address_book",
        "ALTER TABLE fuel_records ADD CONSTRAINT fk_fuel_records_station_address_book "
        "FOREIGN KEY (station_address_book_id) REFERENCES address_book(id) "
        "ON DELETE SET NULL",
    ),
    (
        "fk_fuel_records_driver_user",
        "ALTER TABLE fuel_records ADD CONSTRAINT fk_fuel_records_driver_user "
        "FOREIGN KEY (driver_user_id) REFERENCES users(id) ON DELETE SET NULL",
    ),
]


def _ensure_pg_fk_constraints(engine) -> None:
    """Idempotently add the PG-only FK constraints for migration 054.

    Earlier rc1 code used ``ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS``
    which PG rejects with a syntax error; the surrounding try/except
    silently swallowed it, so the FKs never got installed. This helper
    checks ``information_schema.table_constraints`` first and only
    issues the plain ``ADD CONSTRAINT`` (no ``IF NOT EXISTS``) when the
    constraint is absent. Re-running the migration is a no-op.
    """
    with engine.begin() as conn:
        for name, stmt in _PG_FK_CONSTRAINTS:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.table_constraints "
                    "WHERE constraint_name = :name AND table_name = :table "
                    "AND constraint_type = 'FOREIGN KEY'"
                ),
                {"name": name, "table": "fuel_records"},
            ).scalar()
            if exists:
                print(f"  → FK {name} already present, skipping")
                continue
            conn.execute(text(stmt))
            print(f"  ✓ Added FK {name}")


_NEW_INDEXES: list[tuple[str, str, str]] = [
    # (index_name, table, column_expr)
    ("idx_fuel_records_station_id", "fuel_records", "station_address_book_id"),
    ("idx_fuel_records_driver_id", "fuel_records", "driver_user_id"),
    ("idx_fuel_records_trip_type", "fuel_records", "trip_type"),
    ("idx_fuel_records_filled_at", "fuel_records", "filled_at"),
]


# ---------------------------------------------------------------------------
#  Free-text → enum normalization (mirrors app/constants/fuel.py)
#
#  Duplicated here intentionally so the migration is self-contained and can
#  run before the application package is fully importable. Keep in sync if
#  the canonical map in app/constants/fuel.py changes meaningfully.
# ---------------------------------------------------------------------------

_VALID_FUEL_ENUM_VALUES: set[str] = {
    "gasoline",
    "diesel",
    "electric",
    "hybrid",
    "plugin_hybrid",
    "e85",
    "propane_lpg",
    "cng",
    "hydrogen",
    "other",
}

_NORMALIZATION_MAP: dict[str, str] = {
    # Direct enum values pass through unchanged
    "gasoline": "gasoline",
    "diesel": "diesel",
    "electric": "electric",
    "hybrid": "hybrid",
    "plugin_hybrid": "plugin_hybrid",
    "e85": "e85",
    "propane_lpg": "propane_lpg",
    "cng": "cng",
    "hydrogen": "hydrogen",
    "other": "other",
    # Gasoline aliases
    "gas": "gasoline",
    "petrol": "gasoline",
    "regular": "gasoline",
    "regular gasoline": "gasoline",
    "unleaded": "gasoline",
    "premium": "gasoline",
    "premium gasoline": "gasoline",
    "midgrade": "gasoline",
    "mid-grade": "gasoline",
    "87": "gasoline",
    "89": "gasoline",
    "91": "gasoline",
    "93": "gasoline",
    # Diesel
    "biodiesel": "diesel",
    "b20": "diesel",
    # Electric
    "ev": "electric",
    "battery electric": "electric",
    "battery": "electric",
    # Hybrid
    "hev": "hybrid",
    "hybrid electric": "hybrid",
    # Plug-in hybrid
    "phev": "plugin_hybrid",
    "plug-in hybrid": "plugin_hybrid",
    "plug in hybrid": "plugin_hybrid",
    "plugin hybrid": "plugin_hybrid",
    # E85 / flex fuel
    "flex fuel": "e85",
    "flex-fuel": "e85",
    "flexfuel": "e85",
    "ethanol": "e85",
    "ethanol (e85)": "e85",
    # LPG / propane
    "lpg": "propane_lpg",
    "propane": "propane_lpg",
    "propane (lpg)": "propane_lpg",
    "liquified petroleum gas (propane)": "propane_lpg",
    # CNG
    "natural gas": "cng",
    "compressed natural gas": "cng",
    "compressed natural gas (cng)": "cng",
    # Hydrogen
    "fuel cell": "hydrogen",
    "fuel cell vehicle": "hydrogen",
    "fuel cell hydrogen": "hydrogen",
    # ---- Locale aliases (pl/uk/ru) ------------------------------------
    # Surfaced by issue #69: andrzejf1994's Polish-locale install had
    # vehicle.fuel_type='Benzyna' which silently mapped to 'other'.
    # Coverage matrix: tests/migrations/fixtures/fuel_type_locales.py
    # Polish ----
    "benzyna": "gasoline",
    "olej napędowy": "diesel",
    # NOTE: Polish/Ukrainian/Russian "gaz/газ" means LPG/autogas (very
    # common as a propane retrofit in Poland). The English "gas"
    # mapping above already routes to gasoline; the Cyrillic and PL
    # spellings here intentionally route to propane_lpg.
    "gaz": "propane_lpg",
    "elektryczny": "electric",
    "hybryda": "hybrid",
    "hybrydowy": "hybrid",
    # Ukrainian ----
    "бензин": "gasoline",
    "дизель": "diesel",
    "газ": "propane_lpg",
    "електричний": "electric",
    "гібрид": "hybrid",
    # Russian (some forms shared with Ukrainian above) ----
    "электрический": "electric",
    "гибрид": "hybrid",
}


def _normalize_combined(raw: str) -> tuple[str | None, str | None]:
    """Decode NHTSA combined strings ("Gasoline, Hybrid Electric") into
    (primary, secondary). Returns (None, None) when the string isn't combined."""
    key = raw.strip().lower()
    if "plug-in hybrid" in key or "plug in hybrid" in key or "phev" in key:
        return "plugin_hybrid", "electric"
    if "hybrid electric" in key:
        return "hybrid", "electric"
    if "e85" in key or "flex fuel" in key or "flex-fuel" in key:
        # Only treat as combined when the primary mention is gasoline-ish
        if "gasoline" in key or "gas" in key:
            return "gasoline", "e85"
    return None, None


# ---------------------------------------------------------------------------
#  Main entry point
# ---------------------------------------------------------------------------


def upgrade(engine=None) -> None:
    """Apply the additive schema + backfill enum values."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    inspector = inspect(engine)

    print("Extended fuel tracking migration...")

    # 1. Column additions — idempotent per column.
    added = 0
    skipped = 0
    with engine.begin() as conn:
        for table, column, sql_type in _NEW_COLUMNS:
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            if column in existing_cols:
                skipped += 1
                continue
            resolved_type = _translate_type(sql_type, engine.dialect.name)
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {resolved_type}"))
            print(f"  ✓ Added {table}.{column}")
            added += 1

    print(f"  → Added {added} column(s); {skipped} already existed")

    # Refresh inspector after DDL.
    inspector = inspect(engine)

    # 2. Indexes — CREATE IF NOT EXISTS works on both dialects.
    with engine.begin() as conn:
        for index_name, table, column in _NEW_INDEXES:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})"))
        print(f"  ✓ Ensured {len(_NEW_INDEXES)} index(es)")

    # 3. Postgres-only: add a soft FK on driver_user_id / station_address_book_id.
    #    SQLite doesn't support adding constraints to existing tables without
    #    rebuilding, so we rely on application-layer validation there.
    #
    #    PostgreSQL ALTER TABLE does NOT support ``ADD CONSTRAINT IF NOT
    #    EXISTS`` (any version). Earlier rc1 code wrapped the statement
    #    in try/except which silently swallowed the syntax error — the
    #    FKs never actually got added. Now we check
    #    information_schema.table_constraints first and add only if
    #    absent.
    if is_postgres:
        _ensure_pg_fk_constraints(engine)

    # 4. Backfill vehicles.fuel_type and fuel_records.fuel_type to enum vocab.
    #    Idempotent — only touches rows whose current value is NOT already a
    #    valid enum. Unrecognized values mapped to 'other' and logged.
    unrecognized: list[tuple[str, int, str]] = []  # (table, id, original)

    with engine.begin() as conn:
        # vehicles.fuel_type — also populates fuel_type_secondary when the
        # primary value is a combined NHTSA string.
        rows = conn.execute(
            text("SELECT vin, fuel_type FROM vehicles WHERE fuel_type IS NOT NULL")
        ).fetchall()
        v_normalized = 0
        v_combined = 0
        v_other = 0
        for vin, raw in rows:
            if raw is None:
                continue
            key = raw.strip().lower()
            if not key:
                continue
            if raw == key and key in _VALID_FUEL_ENUM_VALUES:
                continue  # already normalized + lowercased — nothing to do
            if key in _VALID_FUEL_ENUM_VALUES:
                # Case-only difference (e.g. "Diesel" → "diesel"). Lowercase it.
                conn.execute(
                    text("UPDATE vehicles SET fuel_type = :v WHERE vin = :vin"),
                    {"v": key, "vin": vin},
                )
                v_normalized += 1
                continue

            # Try combined-string decoding first (sets secondary if applicable)
            primary, secondary = _normalize_combined(raw)
            if primary is not None:
                conn.execute(
                    text(
                        "UPDATE vehicles SET fuel_type = :p, "
                        "fuel_type_secondary = COALESCE(fuel_type_secondary, :s) "
                        "WHERE vin = :vin"
                    ),
                    {"p": primary, "s": secondary, "vin": vin},
                )
                v_combined += 1
                continue

            # Fall back to single-value normalization
            normalized = _NORMALIZATION_MAP.get(key)
            if normalized is None:
                unrecognized.append(("vehicles", 0, raw))
                normalized = "other"
                v_other += 1
            conn.execute(
                text("UPDATE vehicles SET fuel_type = :v WHERE vin = :vin"),
                {"v": normalized, "vin": vin},
            )
            v_normalized += 1

        # fuel_records.fuel_type — same backfill, no combined-string handling
        # (fuel records always represent a single fuel dispensed).
        rows = conn.execute(
            text("SELECT id, fuel_type FROM fuel_records WHERE fuel_type IS NOT NULL")
        ).fetchall()
        f_normalized = 0
        f_other = 0
        for record_id, raw in rows:
            if raw is None:
                continue
            key = raw.strip().lower()
            if not key:
                continue
            if raw == key and key in _VALID_FUEL_ENUM_VALUES:
                continue  # already normalized + lowercased
            if key in _VALID_FUEL_ENUM_VALUES:
                # Case-only difference — lowercase it.
                conn.execute(
                    text("UPDATE fuel_records SET fuel_type = :v WHERE id = :id"),
                    {"v": key, "id": record_id},
                )
                f_normalized += 1
                continue
            normalized = _NORMALIZATION_MAP.get(key)
            if normalized is None:
                unrecognized.append(("fuel_records", record_id, raw))
                normalized = "other"
                f_other += 1
            conn.execute(
                text("UPDATE fuel_records SET fuel_type = :v WHERE id = :id"),
                {"v": normalized, "id": record_id},
            )
            f_normalized += 1

    print(
        f"  ✓ Backfill: vehicles {v_normalized} ({v_combined} combined, {v_other} →other), "
        f"fuel_records {f_normalized} ({f_other} →other)"
    )

    # 5. Side-log unrecognized values for ops review.
    if unrecognized:
        log_path = Path(
            os.environ.get(
                "MIGRATION_054_LOG",
                "/data/migration-054-unrecognized-fuel-types.log",
            )
        )
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                for table, row_id, raw in unrecognized:
                    f.write(f"{table}\t{row_id}\t{raw!r}\n")
            print(f"  ! {len(unrecognized)} unrecognized value(s) logged to {log_path}")
        except OSError as e:
            print(f"  ! Could not write unrecognized-values log to {log_path}: {e}")

    print("✓ Extended fuel tracking migration completed")


def downgrade(engine=None) -> None:
    """Reverse the migration. Loses backfilled enum normalization."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    print("Rolling back extended fuel tracking migration...")

    with engine.begin() as conn:
        # Drop indexes first
        for index_name, _table, _col in _NEW_INDEXES:
            conn.execute(text(f"DROP INDEX IF EXISTS {index_name}"))

        # Postgres can DROP COLUMN in place; SQLite cannot without a rebuild
        if is_postgres:
            for table, column, _ in _NEW_COLUMNS:
                conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}"))
            for stmt in (
                "ALTER TABLE fuel_records DROP CONSTRAINT IF EXISTS "
                "fk_fuel_records_station_address_book",
                "ALTER TABLE fuel_records DROP CONSTRAINT IF EXISTS fk_fuel_records_driver_user",
            ):
                conn.execute(text(stmt))
        else:
            print(
                "  ! SQLite downgrade is a no-op (would require full table rebuild). "
                "Restore from backup for production rollback."
            )

    print("✓ Rollback completed")


if __name__ == "__main__":
    upgrade()
