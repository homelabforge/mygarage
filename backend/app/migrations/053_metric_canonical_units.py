"""Metric-canonical storage migration — addresses GitHub issue #67.

Converts every unit-bearing column from imperial to SI metric in-place:

  - Odometer / mileage  →  kilometers  (NUMERIC(10,2))
  - Fuel / DEF volume   →  liters      (NUMERIC(9,3))
  - Propane volume      →  liters      (NUMERIC(9,3))
  - Propane tank mass   →  kilograms   (NUMERIC(6,2))
  - DEF tank capacity   →  liters      (NUMERIC(6,2))
  - GVWR                →  kilograms   (NUMERIC(7,2))
  - Trailer dimensions  →  meters      (NUMERIC(5,2))
  - Vehicle spec MPG    →  L/100 km    (NUMERIC(5,2))

Also adds fuel_records.price_basis (enum) so the per-volume / per-weight /
per-kWh / per-tank distinction is explicit, and converts price_per_unit
with the correct factor per row basis (see §2.2 of the plan).

Breaking change; bumps MyGarage to v3.0.0. This migration is FATAL: failures
are re-raised from init_db() so the app won't serve requests against a
half-migrated schema.

SQLite implementation notes:
  - Uses engine.raw_connection() so `PRAGMA foreign_keys = OFF` lands OUTSIDE
    any SQLAlchemy auto-begun transaction (required by the SQLite docs).
  - Rebuild-all pattern — every affected table is rebuilt rather than
    ALTER'd. Required because CHECK constraints on def_records.mileage/
    gallons (038) and vehicle_reminders.due_mileage (048) would reject
    native DROP COLUMN. Also preserves NOT NULL invariants on
    odometer_records.odometer_km.
  - FK integrity is validated via PRAGMA foreign_key_check BEFORE COMMIT so
    a violation rolls back cleanly; without this, a failed check would leave
    the schema renamed but the idempotency guard would skip re-running next
    startup.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

# Signal to init_db() that failures here must halt startup (see §7 Rollout).
FATAL = True


# Exact conversion factors stored as text literals so they embed in SQL
# without any float coercion by the dialect's parameter binder.
MI_TO_KM = "1.60934"
GAL_TO_L = "3.78541"
LB_TO_KG = "0.45359237"
FT_TO_M = "0.3048"
# L/100km = 235.214 / MPG (reciprocal unit — division, not multiplication).
MPG_TO_L100KM_NUMERATOR = "235.214"


# Columns that will be dropped — used by the SQLite sqlite_master preflight
# scan to detect unanticipated CHECK/trigger/view references.
_DROPPED_COLUMNS = [
    "mileage",
    "gallons",
    "propane_gallons",
    "tank_size_lb",
    "def_tank_capacity_gallons",
    "last_milestone_notified",
    "mileage_limit",
    "due_mileage",
    "length_ft",
    "width_ft",
    "height_ft",
    "gvwr",
    "fuel_economy_city",
    "fuel_economy_highway",
    "fuel_economy_combined",
]

_ANTICIPATED_TABLES = {
    "fuel_records",
    "odometer_records",
    "def_records",
    "vehicle_reminders",
    "service_visits",
    "warranty_records",
    "vehicles",
    "trailer_details",
}


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


# ============================================================================
#  Main entry point
# ============================================================================


def upgrade(engine=None) -> None:
    """Convert all unit-bearing columns from imperial to SI metric."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)

    # Idempotency guard — cheap read, no transaction implications.
    fuel_cols = {c["name"] for c in inspector.get_columns("fuel_records")}
    if "odometer_km" in fuel_cols:
        print("  → Metric-canonical migration already applied, skipping")
        return

    print("Metric-canonical migration starting…")
    is_postgres = engine.dialect.name == "postgresql"

    if is_postgres:
        _run_postgres_migration(engine)
    else:
        _run_sqlite_migration(engine)

    print("✓ Metric-canonical migration completed")


# ============================================================================
#  Postgres path — single engine.begin() transaction, direct DROP COLUMN.
# ============================================================================


def _run_postgres_migration(engine) -> None:
    """Postgres: one transaction, direct ALTER TABLE commands."""
    with engine.begin() as conn:
        _populate_metric_columns(conn)
        _drop_imperial_columns_postgres(conn)
        _recreate_indexes(conn)


def _populate_metric_columns(conn) -> None:
    """Add metric columns + populate them via Decimal-safe arithmetic.

    Uses SQLAlchemy Connection.execute(text(...)) — works on both dialects.
    Runs inside whatever transaction context the caller opened.
    """
    # --- 1. ADD metric columns (nullable so the UPDATE below can populate them) ---

    add_statements = [
        # fuel_records
        "ALTER TABLE fuel_records ADD COLUMN odometer_km NUMERIC(10,2)",
        "ALTER TABLE fuel_records ADD COLUMN liters NUMERIC(9,3)",
        "ALTER TABLE fuel_records ADD COLUMN propane_liters NUMERIC(9,3)",
        "ALTER TABLE fuel_records ADD COLUMN tank_size_kg NUMERIC(6,2)",
        "ALTER TABLE fuel_records ADD COLUMN price_basis VARCHAR(12)",
        # odometer_records
        "ALTER TABLE odometer_records ADD COLUMN odometer_km NUMERIC(10,2)",
        # def_records
        "ALTER TABLE def_records ADD COLUMN odometer_km NUMERIC(10,2)",
        "ALTER TABLE def_records ADD COLUMN liters NUMERIC(9,3)",
        # vehicles
        "ALTER TABLE vehicles ADD COLUMN def_tank_capacity_liters NUMERIC(6,2)",
        "ALTER TABLE vehicles ADD COLUMN last_milestone_notified_km NUMERIC(10,2)",
        "ALTER TABLE vehicles ADD COLUMN fuel_economy_city_l_per_100km NUMERIC(5,2)",
        "ALTER TABLE vehicles ADD COLUMN fuel_economy_highway_l_per_100km NUMERIC(5,2)",
        "ALTER TABLE vehicles ADD COLUMN fuel_economy_combined_l_per_100km NUMERIC(5,2)",
        # warranty_records
        "ALTER TABLE warranty_records ADD COLUMN mileage_limit_km NUMERIC(10,2)",
        # vehicle_reminders
        "ALTER TABLE vehicle_reminders ADD COLUMN due_mileage_km NUMERIC(10,2)",
        # service_visits
        "ALTER TABLE service_visits ADD COLUMN odometer_km NUMERIC(10,2)",
        # trailer_details
        "ALTER TABLE trailer_details ADD COLUMN length_m NUMERIC(5,2)",
        "ALTER TABLE trailer_details ADD COLUMN width_m NUMERIC(5,2)",
        "ALTER TABLE trailer_details ADD COLUMN height_m NUMERIC(5,2)",
        "ALTER TABLE trailer_details ADD COLUMN gvwr_kg NUMERIC(7,2)",
    ]
    for stmt in add_statements:
        conn.execute(text(stmt))

    # --- 2. POPULATE fuel_records.price_basis BEFORE price_per_unit math ---
    conn.execute(
        text("""
        UPDATE fuel_records SET price_basis = CASE
            WHEN kwh IS NOT NULL AND gallons IS NULL AND propane_gallons IS NULL
                THEN 'per_kwh'
            WHEN propane_gallons IS NOT NULL OR gallons IS NOT NULL
                THEN 'per_volume'
            WHEN tank_size_lb IS NOT NULL AND tank_quantity IS NOT NULL
                THEN 'per_weight'
            ELSE NULL
        END
    """)
    )

    # --- 3. POPULATE metric columns via math UPDATEs ---
    conn.execute(
        text(f"""
        UPDATE fuel_records SET
            odometer_km    = CAST(mileage         AS NUMERIC) * {MI_TO_KM},
            liters         = CAST(gallons         AS NUMERIC) * {GAL_TO_L},
            propane_liters = CAST(propane_gallons AS NUMERIC) * {GAL_TO_L},
            tank_size_kg   = CAST(tank_size_lb    AS NUMERIC) * {LB_TO_KG}
    """)
    )

    # --- 3a. price_per_unit conversion keyed off price_basis ---
    conn.execute(
        text(f"""
        UPDATE fuel_records SET price_per_unit = CASE price_basis
            WHEN 'per_volume' THEN CAST(price_per_unit AS NUMERIC) / {GAL_TO_L}
            WHEN 'per_weight' THEN CAST(price_per_unit AS NUMERIC) / {LB_TO_KG}
            WHEN 'per_kwh'    THEN price_per_unit
            ELSE price_per_unit
        END WHERE price_per_unit IS NOT NULL
    """)
    )

    # --- 3b. odometer_records ---
    conn.execute(
        text(f"""
        UPDATE odometer_records
        SET odometer_km = CAST(mileage AS NUMERIC) * {MI_TO_KM}
        WHERE mileage IS NOT NULL
    """)
    )

    # --- 3c. def_records (mileage + liters + price_per_unit) ---
    conn.execute(
        text(f"""
        UPDATE def_records SET
            odometer_km = CAST(mileage AS NUMERIC) * {MI_TO_KM},
            liters      = CAST(gallons AS NUMERIC) * {GAL_TO_L}
    """)
    )
    # DEF is always sold by volume — unconditional per-gallon → per-liter.
    conn.execute(
        text(f"""
        UPDATE def_records
        SET price_per_unit = CAST(price_per_unit AS NUMERIC) / {GAL_TO_L}
        WHERE price_per_unit IS NOT NULL
    """)
    )

    # --- 3d. vehicles ---
    conn.execute(
        text(f"""
        UPDATE vehicles SET
            def_tank_capacity_liters   = CAST(def_tank_capacity_gallons AS NUMERIC) * {GAL_TO_L},
            last_milestone_notified_km = CAST(last_milestone_notified   AS NUMERIC) * {MI_TO_KM}
    """)
    )
    # MPG → L/100km. CASE guards against NULL and divide-by-zero.
    for src, dst in [
        ("fuel_economy_city", "fuel_economy_city_l_per_100km"),
        ("fuel_economy_highway", "fuel_economy_highway_l_per_100km"),
        ("fuel_economy_combined", "fuel_economy_combined_l_per_100km"),
    ]:
        conn.execute(
            text(f"""
            UPDATE vehicles SET {dst} = CASE
                WHEN {src} IS NULL OR {src} = 0 THEN NULL
                ELSE {MPG_TO_L100KM_NUMERATOR} / CAST({src} AS NUMERIC)
            END
        """)
        )

    # --- 3e. warranty_records ---
    conn.execute(
        text(f"""
        UPDATE warranty_records
        SET mileage_limit_km = CAST(mileage_limit AS NUMERIC) * {MI_TO_KM}
        WHERE mileage_limit IS NOT NULL
    """)
    )

    # --- 3f. vehicle_reminders ---
    conn.execute(
        text(f"""
        UPDATE vehicle_reminders
        SET due_mileage_km = CAST(due_mileage AS NUMERIC) * {MI_TO_KM}
        WHERE due_mileage IS NOT NULL
    """)
    )

    # --- 3g. service_visits ---
    conn.execute(
        text(f"""
        UPDATE service_visits
        SET odometer_km = CAST(mileage AS NUMERIC) * {MI_TO_KM}
        WHERE mileage IS NOT NULL
    """)
    )

    # --- 3h. trailer_details (dimensions + gvwr) ---
    conn.execute(
        text(f"""
        UPDATE trailer_details SET
            length_m = CAST(length_ft AS NUMERIC) * {FT_TO_M},
            width_m  = CAST(width_ft  AS NUMERIC) * {FT_TO_M},
            height_m = CAST(height_ft AS NUMERIC) * {FT_TO_M},
            gvwr_kg  = CAST(gvwr      AS NUMERIC) * {LB_TO_KG}
    """)
    )


def _drop_imperial_columns_postgres(conn) -> None:
    """Postgres-only: drop imperial-named indexes and columns, restore CHECKs."""
    # Drop only indexes that reference imperial columns.
    for stmt in [
        "DROP INDEX IF EXISTS idx_fuel_records_mileage",
        "DROP INDEX IF EXISTS idx_odometer_records_mileage",
        "DROP INDEX IF EXISTS idx_odometer_vin_mileage",
        "DROP INDEX IF EXISTS idx_def_records_mileage",
        "DROP INDEX IF EXISTS ix_reminders_due_mileage",
    ]:
        conn.execute(text(stmt))

    # Enforce NOT NULL on odometer_km BEFORE dropping the old `mileage` column
    # (Postgres supports in-place NOT NULL when no NULL rows remain).
    conn.execute(text("ALTER TABLE odometer_records ALTER COLUMN odometer_km SET NOT NULL"))

    # Drop imperial columns. Order within each table doesn't matter for Postgres.
    for stmt in [
        "ALTER TABLE fuel_records      DROP COLUMN mileage",
        "ALTER TABLE fuel_records      DROP COLUMN gallons",
        "ALTER TABLE fuel_records      DROP COLUMN propane_gallons",
        "ALTER TABLE fuel_records      DROP COLUMN tank_size_lb",
        "ALTER TABLE odometer_records  DROP COLUMN mileage",
        "ALTER TABLE def_records       DROP COLUMN mileage",
        "ALTER TABLE def_records       DROP COLUMN gallons",
        "ALTER TABLE vehicles          DROP COLUMN def_tank_capacity_gallons",
        "ALTER TABLE vehicles          DROP COLUMN last_milestone_notified",
        "ALTER TABLE vehicles          DROP COLUMN fuel_economy_city",
        "ALTER TABLE vehicles          DROP COLUMN fuel_economy_highway",
        "ALTER TABLE vehicles          DROP COLUMN fuel_economy_combined",
        "ALTER TABLE warranty_records  DROP COLUMN mileage_limit",
        "ALTER TABLE vehicle_reminders DROP COLUMN due_mileage",
        "ALTER TABLE service_visits    DROP COLUMN mileage",
        "ALTER TABLE trailer_details   DROP COLUMN length_ft",
        "ALTER TABLE trailer_details   DROP COLUMN width_ft",
        "ALTER TABLE trailer_details   DROP COLUMN height_ft",
        "ALTER TABLE trailer_details   DROP COLUMN gvwr",
    ]:
        conn.execute(text(stmt))

    # Restore metric-equivalent CHECK constraints that migrations 038/048 had
    # on the imperial columns. Without these, Postgres has weaker data
    # validation than the SQLite rebuild path (which inlines them in CREATE TABLE).
    for stmt in [
        # def_records — mirrors 038_add_def_tracking.py constraints
        "ALTER TABLE def_records ADD CONSTRAINT chk_def_odometer_km_range "
        "  CHECK (odometer_km IS NULL OR (odometer_km >= 0 AND odometer_km <= 99999999.99))",
        "ALTER TABLE def_records ADD CONSTRAINT chk_def_liters_nonneg "
        "  CHECK (liters IS NULL OR liters >= 0)",
        # vehicle_reminders — mirrors 048_service_visit_overhaul.py `due_mileage > 0`
        "ALTER TABLE vehicle_reminders ADD CONSTRAINT chk_reminders_due_mileage_km_pos "
        "  CHECK (due_mileage_km IS NULL OR due_mileage_km > 0)",
        # fuel_records — price_basis enum
        "ALTER TABLE fuel_records ADD CONSTRAINT chk_fuel_price_basis_enum "
        "  CHECK (price_basis IS NULL OR price_basis IN "
        "  ('per_volume', 'per_weight', 'per_tank', 'per_kwh'))",
    ]:
        conn.execute(text(stmt))


def _recreate_indexes(conn) -> None:
    """Recreate metric-named indexes for the renamed columns (both dialects)."""
    for stmt in [
        "CREATE INDEX idx_fuel_records_odometer_km      ON fuel_records(odometer_km)",
        "CREATE INDEX idx_odometer_records_odometer_km  ON odometer_records(odometer_km)",
        "CREATE INDEX idx_odometer_vin_odometer_km      ON odometer_records(vin, odometer_km)",
        "CREATE INDEX idx_def_records_odometer_km       ON def_records(odometer_km)",
        "CREATE INDEX ix_reminders_due_mileage_km       ON vehicle_reminders(due_mileage_km)",
    ]:
        conn.execute(text(stmt))


# ============================================================================
#  SQLite path — raw DBAPI connection, PRAGMA outside tx, rebuild every table.
# ============================================================================


def _run_sqlite_migration(engine) -> None:
    """SQLite path using the raw DBAPI connection.

    SQLAlchemy 2.0 Connection.execute() autobegins a transaction, which would
    make `PRAGMA foreign_keys = OFF` a silent no-op (SQLite ignores FK mode
    changes inside a transaction). engine.raw_connection() gives us the
    DB-API connection without the autobegin layer, so we can drive BEGIN /
    COMMIT / ROLLBACK explicitly on a cursor and get the PRAGMA semantics
    the SQLite docs prescribe for ALTER TABLE-heavy migrations.
    """
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        # 1. Version gate.
        version_row = cur.execute("SELECT sqlite_version()").fetchone()[0]
        major_minor = version_row.split(".")
        major, minor = int(major_minor[0]), int(major_minor[1])
        if (major, minor) < (3, 35):
            raise RuntimeError(
                f"SQLite {version_row} < 3.35 required for migration 053 "
                "(native DROP COLUMN + rebuild support)."
            )

        # 2. Preflight sqlite_master scan — catch CHECK/trigger/view refs to
        #    dropped columns that aren't on our anticipated tables.
        suspicious = _scan_raw_sqlite_master_for_imperial_refs(cur)
        if suspicious:
            raise RuntimeError(
                "Unanticipated sqlite_master references to dropped columns:\n"
                + "\n".join(f"  - {s}" for s in suspicious)
            )

        # 3. Disable FKs OUTSIDE any transaction (required by SQLite docs).
        cur.execute("PRAGMA foreign_keys = OFF")
        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 0:
            raise RuntimeError(
                f"PRAGMA foreign_keys = OFF failed; got {fk_state}. "
                "Are we inside an active transaction?"
            )

        # 4. Explicit transaction for the rebuild.
        try:
            cur.execute("BEGIN")

            # 4a. Add + populate the metric columns using the shared helper.
            #     Builds a shim that looks like a SQLAlchemy Connection to the
            #     helper but forwards to the raw cursor without autobegin.
            _populate_metric_columns_via_cursor(cur)

            # 4b. Rebuild every affected table.
            _rebuild_odometer_records(cur)
            _rebuild_fuel_records(cur)
            _rebuild_def_records(cur)
            _rebuild_vehicle_reminders(cur)
            _rebuild_service_visits(cur)
            _rebuild_warranty_records(cur)
            _rebuild_vehicles(cur)
            _rebuild_trailer_details(cur)

            # 4c. Recreate metric indexes inside the same transaction.
            _recreate_indexes_raw(cur)

            # 4d. PRE-COMMIT FK integrity check. If any row points to a row
            #     that doesn't exist, rollback and leave the DB untouched.
            for tbl in (
                "odometer_records",
                "fuel_records",
                "def_records",
                "vehicle_reminders",
                "service_visits",
                "warranty_records",
                "vehicles",
                "trailer_details",
            ):
                violations = cur.execute(f"PRAGMA foreign_key_check({tbl})").fetchall()
                if violations:
                    raise RuntimeError(
                        f"FK violations on {tbl} after rebuild (pre-commit): {violations!r}"
                    )

            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

        # 5. Re-enable FKs.
        cur.execute("PRAGMA foreign_keys = ON")
        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 1:
            raise RuntimeError(f"PRAGMA foreign_keys = ON failed; got {fk_state}.")

        # 6. Belt-and-braces post-commit FK check (with FKs enabled).
        for tbl in (
            "odometer_records",
            "fuel_records",
            "def_records",
            "vehicle_reminders",
            "service_visits",
            "warranty_records",
            "vehicles",
            "trailer_details",
        ):
            violations = cur.execute(f"PRAGMA foreign_key_check({tbl})").fetchall()
            if violations:
                raise RuntimeError(
                    f"Post-commit FK violations on {tbl} "
                    f"(should have been caught pre-commit): {violations!r}"
                )
    finally:
        raw.close()


def _scan_raw_sqlite_master_for_imperial_refs(cur) -> list[str]:
    """Scan sqlite_master for CHECK/trigger/view references to dropped columns."""
    cur.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND type IN ('trigger', 'view', 'table')"
    )
    suspicious: list[str] = []
    for type_, name, tbl, sql in cur.fetchall():
        if type_ == "table" and name in _ANTICIPATED_TABLES:
            continue
        # Skip tables we rebuild — any imperial refs on them are handled by
        # the rebuild CREATE TABLE redefining the schema from scratch.
        for col in _DROPPED_COLUMNS:
            if re.search(rf"\b{col}\b", sql):
                suspicious.append(f"{type_} {name} (on {tbl}) references `{col}`")
                break
    return suspicious


class _CursorConnectionShim:
    """Adapter so _populate_metric_columns() (which expects a SQLAlchemy
    Connection-like object supporting `execute(text(...))`) can run against
    a raw DB-API cursor inside our explicit BEGIN/COMMIT on SQLite."""

    def __init__(self, cur) -> None:
        self._cur = cur

    def execute(self, clause) -> None:
        sql = str(clause)
        self._cur.execute(sql)


def _populate_metric_columns_via_cursor(cur) -> None:
    """Run the dialect-agnostic ADD/UPDATE helper against the raw cursor."""
    _populate_metric_columns(_CursorConnectionShim(cur))


def _recreate_indexes_raw(cur) -> None:
    """SQLite-path index creation via raw cursor."""
    for stmt in (
        "CREATE INDEX idx_fuel_records_odometer_km      ON fuel_records(odometer_km)",
        "CREATE INDEX idx_odometer_records_odometer_km  ON odometer_records(odometer_km)",
        "CREATE INDEX idx_odometer_vin_odometer_km      ON odometer_records(vin, odometer_km)",
        "CREATE INDEX idx_def_records_odometer_km       ON def_records(odometer_km)",
        "CREATE INDEX ix_reminders_due_mileage_km       ON vehicle_reminders(due_mileage_km)",
    ):
        cur.execute(stmt)


# ============================================================================
#  SQLite rebuild helpers
#
#  Each rebuild:
#    1. CREATE <table>_new with the new schema (metric cols, drop imperial,
#       preserve every other column + CHECK + FK + NOT NULL intact).
#    2. INSERT INTO <table>_new SELECT ... FROM <table>
#       (COALESCE on NOT NULL targets whose originals may hold NULLs).
#    3. DROP TABLE <table>; ALTER TABLE <table>_new RENAME TO <table>.
#    4. Recreate non-imperial indexes that the old table had.
# ============================================================================


def _rebuild_odometer_records(cur) -> None:
    """odometer_records rebuild — preserves NOT NULL on odometer_km.

    Handles legacy rows where `source` may be NULL (the 035 migration added
    the column with DEFAULT 'manual' but no NOT NULL constraint).
    """
    cur.execute("""
        CREATE TABLE odometer_records_new (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            vin         VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
            date        DATE        NOT NULL,
            odometer_km NUMERIC(10,2) NOT NULL,
            notes       TEXT,
            source      VARCHAR(20) NOT NULL DEFAULT 'manual',
            created_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        INSERT INTO odometer_records_new
               (id, vin, date, odometer_km, notes, source, created_at)
        SELECT  id, vin, date, odometer_km, notes,
                COALESCE(source, 'manual'),
                COALESCE(created_at, CURRENT_TIMESTAMP)
        FROM odometer_records
    """)
    cur.execute("DROP TABLE odometer_records")
    cur.execute("ALTER TABLE odometer_records_new RENAME TO odometer_records")
    # Recreate the non-mileage indexes (per odometer.py __table_args__).
    for stmt in (
        "CREATE INDEX idx_odometer_records_vin ON odometer_records(vin)",
        "CREATE INDEX idx_odometer_records_date ON odometer_records(date)",
        "CREATE INDEX idx_odometer_vin_date ON odometer_records(vin, date)",
        "CREATE INDEX idx_odometer_source ON odometer_records(source)",
    ):
        cur.execute(stmt)


def _rebuild_fuel_records(cur) -> None:
    """fuel_records rebuild — drops mileage/gallons/propane_gallons/tank_size_lb,
    adds price_basis enum CHECK, preserves all other columns and indexes."""
    cur.execute("""
        CREATE TABLE fuel_records_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            vin             VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
            date            DATE NOT NULL,
            odometer_km     NUMERIC(10,2),
            liters          NUMERIC(9,3),
            propane_liters  NUMERIC(9,3),
            tank_size_kg    NUMERIC(6,2),
            tank_quantity   INTEGER,
            kwh             NUMERIC(8,3),
            cost            NUMERIC(8,2),
            price_per_unit  NUMERIC(6,3),
            price_basis     VARCHAR(12)
                            CHECK (price_basis IS NULL OR price_basis IN
                              ('per_volume', 'per_weight', 'per_tank', 'per_kwh')),
            fuel_type       VARCHAR(50),
            is_full_tank    BOOLEAN DEFAULT 1,
            missed_fillup   BOOLEAN DEFAULT 0,
            is_hauling      BOOLEAN DEFAULT 0,
            notes           TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        INSERT INTO fuel_records_new
               (id, vin, date, odometer_km, liters, propane_liters, tank_size_kg,
                tank_quantity, kwh, cost, price_per_unit, price_basis, fuel_type,
                is_full_tank, missed_fillup, is_hauling, notes, created_at)
        SELECT  id, vin, date, odometer_km, liters, propane_liters, tank_size_kg,
                tank_quantity, kwh, cost, price_per_unit, price_basis, fuel_type,
                is_full_tank, missed_fillup, is_hauling, notes,
                COALESCE(created_at, CURRENT_TIMESTAMP)
        FROM fuel_records
    """)
    cur.execute("DROP TABLE fuel_records")
    cur.execute("ALTER TABLE fuel_records_new RENAME TO fuel_records")
    # Recreate non-mileage indexes from fuel.py __table_args__.
    for stmt in (
        "CREATE INDEX idx_fuel_records_vin ON fuel_records(vin)",
        "CREATE INDEX idx_fuel_records_date ON fuel_records(date)",
        "CREATE INDEX idx_fuel_vin_date ON fuel_records(vin, date)",
        "CREATE INDEX idx_fuel_is_full_tank ON fuel_records(is_full_tank)",
        "CREATE INDEX idx_fuel_full_tank_vin ON fuel_records(vin, is_full_tank)",
        "CREATE INDEX idx_fuel_hauling ON fuel_records(is_hauling)",
        "CREATE INDEX idx_fuel_normal_mpg ON fuel_records(vin, is_full_tank, is_hauling)",
    ):
        cur.execute(stmt)


def _rebuild_def_records(cur) -> None:
    """def_records rebuild — drops mileage/gallons (and their CHECKs), keeps
    entry_type + origin_fuel_record_id added in migration 041."""
    cur.execute("""
        CREATE TABLE def_records_new (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            vin                   VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
            date                  DATE NOT NULL,
            odometer_km           NUMERIC(10,2)
                                  CHECK (odometer_km IS NULL OR
                                    (odometer_km >= 0 AND odometer_km <= 99999999.99)),
            liters                NUMERIC(9,3) CHECK (liters IS NULL OR liters >= 0),
            cost                  NUMERIC(8,2) CHECK (cost IS NULL OR cost >= 0),
            price_per_unit        NUMERIC(6,3),
            fill_level            NUMERIC(3,2)
                                  CHECK (fill_level IS NULL OR
                                    (fill_level >= 0.00 AND fill_level <= 1.00)),
            source                VARCHAR(100),
            brand                 VARCHAR(100),
            notes                 TEXT,
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
            entry_type            VARCHAR(20) NOT NULL DEFAULT 'purchase'
                                  CHECK (entry_type IN ('purchase', 'auto_fuel_sync')),
            origin_fuel_record_id INTEGER REFERENCES fuel_records(id) ON DELETE SET NULL
        )
    """)
    cur.execute("""
        INSERT INTO def_records_new
               (id, vin, date, odometer_km, liters, cost, price_per_unit,
                fill_level, source, brand, notes, created_at,
                entry_type, origin_fuel_record_id)
        SELECT  id, vin, date, odometer_km, liters, cost, price_per_unit,
                fill_level, source, brand, notes,
                COALESCE(created_at, CURRENT_TIMESTAMP),
                COALESCE(entry_type, 'purchase'),
                origin_fuel_record_id
        FROM def_records
    """)
    cur.execute("DROP TABLE def_records")
    cur.execute("ALTER TABLE def_records_new RENAME TO def_records")
    for stmt in (
        "CREATE INDEX idx_def_records_vin ON def_records(vin)",
        "CREATE INDEX idx_def_records_date ON def_records(date)",
        "CREATE INDEX idx_def_records_vin_date ON def_records(vin, date)",
        "CREATE INDEX idx_def_entry_type ON def_records(entry_type)",
        "CREATE INDEX idx_def_origin_fuel_record_id ON def_records(origin_fuel_record_id)",
    ):
        cur.execute(stmt)


def _rebuild_vehicle_reminders(cur) -> None:
    """vehicle_reminders rebuild — drops due_mileage (and its CHECK > 0),
    replaces with due_mileage_km (also CHECK > 0)."""
    cur.execute("""
        CREATE TABLE vehicle_reminders_new (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            vin              VARCHAR(17)  NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
            line_item_id     INTEGER      REFERENCES service_line_items(id) ON DELETE SET NULL,
            title            VARCHAR(200) NOT NULL,
            reminder_type    VARCHAR(10)  NOT NULL
                             CHECK (reminder_type IN ('date','mileage','both','smart')),
            due_date         DATE,
            due_mileage_km   NUMERIC(10,2)
                             CHECK (due_mileage_km IS NULL OR due_mileage_km > 0),
            status           VARCHAR(10)  NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending','done','dismissed')),
            notes            TEXT,
            last_notified_at DATETIME,
            created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        INSERT INTO vehicle_reminders_new
               (id, vin, line_item_id, title, reminder_type, due_date, due_mileage_km,
                status, notes, last_notified_at, created_at, updated_at)
        SELECT  id, vin, line_item_id, title, reminder_type, due_date, due_mileage_km,
                status, notes, last_notified_at,
                COALESCE(created_at, CURRENT_TIMESTAMP),
                COALESCE(updated_at, CURRENT_TIMESTAMP)
        FROM vehicle_reminders
    """)
    cur.execute("DROP TABLE vehicle_reminders")
    cur.execute("ALTER TABLE vehicle_reminders_new RENAME TO vehicle_reminders")
    # Non-mileage indexes from reminder.py __table_args__.
    for stmt in (
        "CREATE INDEX ix_reminders_vin_status ON vehicle_reminders(vin, status)",
        "CREATE INDEX ix_reminders_due_date ON vehicle_reminders(due_date)",
    ):
        cur.execute(stmt)


def _rebuild_service_visits(cur) -> None:
    """service_visits rebuild — drops mileage, adds odometer_km."""
    cur.execute("""
        CREATE TABLE service_visits_new (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            vin                    VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
            vendor_id              INTEGER REFERENCES vendors(id),
            date                   DATE NOT NULL,
            odometer_km            NUMERIC(10,2),
            total_cost             NUMERIC(10,2),
            tax_amount             NUMERIC(10,2),
            shop_supplies          NUMERIC(10,2),
            misc_fees              NUMERIC(10,2),
            notes                  TEXT,
            service_category       VARCHAR(30)
                                   CHECK (service_category IS NULL OR service_category IN
                                     ('Maintenance','Inspection','Collision','Upgrades','Detailing')),
            insurance_claim_number VARCHAR(50),
            created_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at             DATETIME
        )
    """)
    cur.execute("""
        INSERT INTO service_visits_new
               (id, vin, vendor_id, date, odometer_km, total_cost, tax_amount,
                shop_supplies, misc_fees, notes, service_category,
                insurance_claim_number, created_at, updated_at)
        SELECT  id, vin, vendor_id, date, odometer_km, total_cost, tax_amount,
                shop_supplies, misc_fees, notes, service_category,
                insurance_claim_number,
                COALESCE(created_at, CURRENT_TIMESTAMP),
                updated_at
        FROM service_visits
    """)
    cur.execute("DROP TABLE service_visits")
    cur.execute("ALTER TABLE service_visits_new RENAME TO service_visits")
    for stmt in (
        "CREATE INDEX idx_service_visits_vin ON service_visits(vin)",
        "CREATE INDEX idx_service_visits_date ON service_visits(date)",
        "CREATE INDEX idx_service_visits_vendor ON service_visits(vendor_id)",
        "CREATE INDEX idx_service_visits_vin_date ON service_visits(vin, date)",
    ):
        cur.execute(stmt)


def _rebuild_warranty_records(cur) -> None:
    """warranty_records rebuild — drops mileage_limit, adds mileage_limit_km."""
    cur.execute("""
        CREATE TABLE warranty_records_new (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            vin               VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
            warranty_type     VARCHAR(50) NOT NULL
                              CHECK (warranty_type IN
                                ('Manufacturer','Powertrain','Extended','Bumper-to-Bumper',
                                 'Emissions','Corrosion','Other')),
            provider          VARCHAR(100),
            start_date        DATE NOT NULL,
            end_date          DATE,
            mileage_limit_km  NUMERIC(10,2),
            coverage_details  TEXT,
            policy_number     VARCHAR(50),
            notes             TEXT,
            created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_notified_at  DATETIME
        )
    """)
    cur.execute("""
        INSERT INTO warranty_records_new
               (id, vin, warranty_type, provider, start_date, end_date,
                mileage_limit_km, coverage_details, policy_number, notes,
                created_at, last_notified_at)
        SELECT  id, vin, warranty_type, provider, start_date, end_date,
                mileage_limit_km, coverage_details, policy_number, notes,
                COALESCE(created_at, CURRENT_TIMESTAMP),
                last_notified_at
        FROM warranty_records
    """)
    cur.execute("DROP TABLE warranty_records")
    cur.execute("ALTER TABLE warranty_records_new RENAME TO warranty_records")
    for stmt in (
        "CREATE INDEX idx_warranty_records_vin ON warranty_records(vin)",
        "CREATE INDEX idx_warranty_records_end_date ON warranty_records(end_date)",
    ):
        cur.execute(stmt)


def _rebuild_vehicles(cur) -> None:
    """vehicles rebuild — big one (~60 columns). Drops imperial spec columns,
    adds metric replacements, preserves everything else incl. FK to users."""
    cur.execute("""
        CREATE TABLE vehicles_new (
            vin                                VARCHAR(17) PRIMARY KEY,
            nickname                           VARCHAR(100) NOT NULL,
            vehicle_type                       VARCHAR(20) NOT NULL
                                               CHECK (vehicle_type IN
                                                 ('Car','Truck','SUV','Motorcycle','RV','Trailer',
                                                  'FifthWheel','TravelTrailer','Electric','Hybrid')),
            year                               INTEGER,
            make                               VARCHAR(50),
            model                              VARCHAR(50),
            license_plate                      VARCHAR(20),
            color                              VARCHAR(30),
            purchase_date                      DATE,
            purchase_price                     NUMERIC(10,2),
            sold_date                          DATE,
            sold_price                         NUMERIC(10,2),
            main_photo                         VARCHAR(255),
            trim                               VARCHAR(50),
            body_class                         VARCHAR(100),
            drive_type                         VARCHAR(30),
            doors                              INTEGER,
            gvwr_class                         VARCHAR(50),
            displacement_l                     VARCHAR(20),
            cylinders                          INTEGER,
            fuel_type                          VARCHAR(50),
            transmission_type                  VARCHAR(50),
            transmission_speeds                VARCHAR(20),
            window_sticker_file_path           VARCHAR(255),
            window_sticker_uploaded_at         DATETIME,
            msrp_base                          NUMERIC(10,2),
            msrp_options                       NUMERIC(10,2),
            msrp_total                         NUMERIC(10,2),
            fuel_economy_city_l_per_100km      NUMERIC(5,2),
            fuel_economy_highway_l_per_100km   NUMERIC(5,2),
            fuel_economy_combined_l_per_100km  NUMERIC(5,2),
            standard_equipment                 JSON,
            optional_equipment                 JSON,
            assembly_location                  VARCHAR(100),
            destination_charge                 NUMERIC(10,2),
            window_sticker_options_detail      JSON,
            window_sticker_packages            JSON,
            exterior_color                     VARCHAR(100),
            interior_color                     VARCHAR(100),
            sticker_engine_description         VARCHAR(150),
            sticker_transmission_description   VARCHAR(150),
            sticker_drivetrain                 VARCHAR(50),
            wheel_specs                        VARCHAR(100),
            tire_specs                         VARCHAR(100),
            warranty_powertrain                VARCHAR(100),
            warranty_basic                     VARCHAR(100),
            environmental_rating_ghg           VARCHAR(10),
            environmental_rating_smog          VARCHAR(10),
            window_sticker_parser_used         VARCHAR(50),
            window_sticker_confidence_score    NUMERIC(5,2),
            window_sticker_extracted_vin       VARCHAR(17),
            user_id                            INTEGER REFERENCES users(id) ON DELETE CASCADE,
            archived_at                        DATETIME,
            archive_reason                     VARCHAR(50),
            archive_sale_price                 NUMERIC(10,2),
            archive_sale_date                  DATE,
            archive_notes                      VARCHAR(1000),
            archived_visible                   BOOLEAN DEFAULT 1,
            def_tank_capacity_liters           NUMERIC(6,2),
            last_milestone_notified_km         NUMERIC(10,2),
            created_at                         DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at                         DATETIME
        )
    """)
    cur.execute("""
        INSERT INTO vehicles_new
        SELECT vin, nickname, vehicle_type, year, make, model, license_plate, color,
               purchase_date, purchase_price, sold_date, sold_price, main_photo,
               trim, body_class, drive_type, doors, gvwr_class, displacement_l,
               cylinders, fuel_type, transmission_type, transmission_speeds,
               window_sticker_file_path, window_sticker_uploaded_at, msrp_base,
               msrp_options, msrp_total,
               fuel_economy_city_l_per_100km, fuel_economy_highway_l_per_100km,
               fuel_economy_combined_l_per_100km,
               standard_equipment, optional_equipment, assembly_location,
               destination_charge, window_sticker_options_detail,
               window_sticker_packages, exterior_color, interior_color,
               sticker_engine_description, sticker_transmission_description,
               sticker_drivetrain, wheel_specs, tire_specs, warranty_powertrain,
               warranty_basic, environmental_rating_ghg, environmental_rating_smog,
               window_sticker_parser_used, window_sticker_confidence_score,
               window_sticker_extracted_vin, user_id, archived_at, archive_reason,
               archive_sale_price, archive_sale_date, archive_notes, archived_visible,
               def_tank_capacity_liters, last_milestone_notified_km,
               COALESCE(created_at, CURRENT_TIMESTAMP), updated_at
        FROM vehicles
    """)
    cur.execute("DROP TABLE vehicles")
    cur.execute("ALTER TABLE vehicles_new RENAME TO vehicles")
    for stmt in (
        "CREATE INDEX ix_vehicles_user_id ON vehicles(user_id)",
        "CREATE INDEX idx_vehicles_type ON vehicles(vehicle_type)",
        "CREATE INDEX idx_vehicles_nickname ON vehicles(nickname)",
    ):
        cur.execute(stmt)


def _rebuild_trailer_details(cur) -> None:
    """trailer_details rebuild — drops *_ft and gvwr, adds *_m and gvwr_kg."""
    cur.execute("""
        CREATE TABLE trailer_details_new (
            vin               VARCHAR(17) PRIMARY KEY
                              REFERENCES vehicles(vin) ON DELETE CASCADE,
            gvwr_kg           NUMERIC(7,2),
            hitch_type        VARCHAR(30)
                              CHECK (hitch_type IS NULL OR hitch_type IN
                                ('Ball','Pintle','Fifth Wheel','Gooseneck')),
            axle_count        INTEGER,
            brake_type        VARCHAR(20)
                              CHECK (brake_type IS NULL OR brake_type IN
                                ('None','Electric','Hydraulic')),
            length_m          NUMERIC(5,2),
            width_m           NUMERIC(5,2),
            height_m          NUMERIC(5,2),
            tow_vehicle_vin   VARCHAR(17) REFERENCES vehicles(vin) ON DELETE SET NULL
        )
    """)
    cur.execute("""
        INSERT INTO trailer_details_new
               (vin, gvwr_kg, hitch_type, axle_count, brake_type,
                length_m, width_m, height_m, tow_vehicle_vin)
        SELECT  vin, gvwr_kg, hitch_type, axle_count, brake_type,
                length_m, width_m, height_m, tow_vehicle_vin
        FROM trailer_details
    """)
    cur.execute("DROP TABLE trailer_details")
    cur.execute("ALTER TABLE trailer_details_new RENAME TO trailer_details")


# ============================================================================
#  Downgrade (best-effort; primary rollback is backup restore)
# ============================================================================


def downgrade(engine=None) -> None:
    """Reverse the migration. Lossy for odometer values originally stored as
    integer miles — converting km → mi → int can drift by ≤1 mi per record.

    Provided mainly for the test suite. Operational rollback should use the
    backup snapshot taken before deployment, per the v3.0.0 rollout runbook.
    """
    raise NotImplementedError(
        "Migration 053 downgrade is intentionally not implemented for production. "
        "Restore from the pre-migration backup instead."
    )


if __name__ == "__main__":
    upgrade()
