"""Give tires a mount history, and make `position` mean "where it is now".

Before this migration a tire row WAS a corner: `position` was NOT NULL and
`uq_tires_vin_position` meant one row per corner per vehicle. A tire taken off
the vehicle had nowhere to be, so a seasonal set had to be deleted and
re-entered every spring and autumn, losing its readings with it.

After it, `tires.position` is nullable ("in storage" is a state), and
`tire_mount_periods` records where each tire has been and when. Distance and
wear are computed from those periods, not from the vehicle's raw odometer
delta -- which is the actual defect this exists to fix: `_project_wear` treated
the whole odometer span between two readings as distance driven ON THAT TIRE,
so anyone running two seasonal sets was told their tires had hundreds of
thousands of kilometres of life left. Erring high, on a tire.

FATAL, because every later query assumes the new shape.

WHY ONE TRANSACTION
-------------------
Steps 1-7 run inside a single transaction on both dialects. That is not
tidiness: the runner executes and stamps in SEPARATE transactions
(`runner.py:226`), so a crash between two non-transactional steps would leave a
schema that matches neither branch of the re-entrancy check. With one
transaction the observable states collapse to two, keyed on the LAST thing this
migration writes (`vehicle_reminders.source`) rather than the first.

WHY THE PRAGMA IS READ BACK
---------------------------
`PRAGMA foreign_keys = OFF` is a **no-op inside a transaction**, and SQLite
reports no error: the pragma read still returns 1. Measured. A rebuild that
assumes it worked will fire `ON DELETE CASCADE` on `DROP TABLE tires` and take
every `tire_readings` row with it, silently. This follows migration 070
(`070:119-162`), which disables FKs on a raw DB-API connection outside any
transaction and asserts the read-back. Do NOT copy 092: it sets the pragma and
never checks, and survives only because its table has no children.

Back up before deploying, with the backup API (`POST /api/backup/create-full`),
not `cp`: MyGarage runs in WAL mode and a plain file copy of a database with a
live WAL sidecar is torn but plausible.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True

#: Every CHECK that step 7 restores on `vehicle_reminders`, with the scan that
#: proves the data can take it. Preflight P2 runs all of them: a violated CHECK
#: is skipped and logged, because a missing constraint is recoverable and a
#: crash-looping instance is not.
#:
#: Enumerated from the DDL step 7 writes, not from the ones that came to mind.
#: An earlier draft listed only the two vocabulary CHECKs and missed the range
#: CHECK -- which is the one with a reachable violation, via the legacy JSON
#: importer's `bool(is_recurring and recurrence_miles)` accepting a negative.
REMINDER_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "check_reminder_type",
        "reminder_type IN ('date','mileage','both','smart','hours')",
        "SELECT id FROM vehicle_reminders WHERE reminder_type NOT IN "
        "('date','mileage','both','smart','hours')",
    ),
    (
        "check_reminder_status",
        "status IN ('pending','done','dismissed')",
        "SELECT id FROM vehicle_reminders WHERE status NOT IN ('pending','done','dismissed')",
    ),
    (
        "check_due_mileage_km",
        "due_mileage_km IS NULL OR due_mileage_km > 0",
        "SELECT id FROM vehicle_reminders WHERE due_mileage_km IS NOT NULL AND due_mileage_km <= 0",
    ),
)


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


# ============================================================================
#  Preflight
# ============================================================================


def _preflight_vin_mismatches(cur) -> None:
    """P1. Repair children whose `vin` disagrees with their tire's.

    The composite FK `(tire_id, vin) -> tires(id, vin)` exists to make that
    disagreement impossible. Installing it while such a row exists fails the
    rebuild, so the rows are repaired first rather than the migration dying on
    data it could have fixed. The tire is the authority; the denormalised `vin`
    on the child is a copy.
    """
    for table in ("tire_readings", "vehicle_reminders"):
        cols = {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
        if "tire_id" not in cols:
            continue
        bad = cur.execute(
            f"SELECT c.id FROM {table} c JOIN tires t ON t.id = c.tire_id WHERE c.vin <> t.vin"
        ).fetchall()
        if not bad:
            continue
        print(
            f"  → P1: repairing {len(bad)} {table} row(s) with a mismatched vin: "
            f"{[r[0] for r in bad]}"
        )
        cur.execute(
            f"UPDATE {table} SET vin = (SELECT vin FROM tires WHERE id = {table}.tire_id) "
            f"WHERE id IN (SELECT c.id FROM {table} c JOIN tires t ON t.id = c.tire_id "
            f"WHERE c.vin <> t.vin)"
        )


def _preflight_reminder_checks(cur) -> list[tuple[str, str]]:
    """P2. Which CHECKs the data can actually take.

    Returns the (name, expression) pairs to include in the rebuilt table. A
    CHECK whose data is violating is LOGGED AND SKIPPED, not enforced: adding
    it would abort a FATAL migration and crash-loop the instance on every
    restart until someone with database access repaired the row by hand.
    """
    keep: list[tuple[str, str]] = []
    for name, expression, scan in REMINDER_CHECKS:
        violations = [r[0] for r in cur.execute(scan).fetchall()]
        if violations:
            print(
                f"  → P2: SKIPPING {name}; {len(violations)} row(s) violate it: "
                f"{violations}. The constraint is not installed. Repair those rows "
                f"and a later release will add it."
            )
            continue
        keep.append((name, expression))
    return keep


def _preflight_backup_marker(engine) -> None:
    """P3. Warn loudly if there is no recent full backup.

    This release cannot be downgraded: step 3 drops `tires.installed_date`, and
    v3.2.0's ORM declares it, so an older image raises `no such column` on
    every tire request. Restore is the only way back.
    """
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    backups = data_dir / "backups"
    if not backups.is_dir() or not any(backups.iterdir()):
        print(
            "  → P3: WARNING — no backup found in "
            f"{backups}. This migration cannot be reversed: it drops "
            "tires.installed_date, which the previous release's ORM requires. "
            "If this upgrade goes wrong, restoring a backup is the only way "
            "back. Take one now (POST /api/backup/create-full) if you have not."
        )


# ============================================================================
#  SQLite rebuilds
# ============================================================================


def _rebuild_tires(cur) -> None:
    """Step 3. `position` nullable, `set_id` + `retired_on` added,
    `installed_date` dropped, `UNIQUE (id, vin)` added.

    `uq_tires_vin_position` is reproduced verbatim and NOT replaced by a
    partial index: NULLs compare as distinct under UNIQUE on both dialects, so
    once `position` is nullable the same constraint permits any number of
    stored tires while still rejecting a second mounted tire at one corner.

    `tires` carries exactly one constraint and no CHECKs. Verified against a
    production database rather than assumed -- an earlier draft of the design
    said "reproduce all three CHECKs", carrying the count over from
    `vehicle_reminders`, where the three actually live.
    """
    cur.execute("""
        CREATE TABLE tires_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            vin             VARCHAR(17) NOT NULL,
            position        VARCHAR(10),
            brand           VARCHAR(80),
            model_name      VARCHAR(80),
            size            VARCHAR(40),
            dot_code        VARCHAR(20),
            set_id          INTEGER,
            retired_on      DATE,
            tread_depth_mm  NUMERIC(5, 2),
            pressure_kpa    NUMERIC(7, 2),
            min_tread_mm    NUMERIC(5, 2),
            notes           TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            CONSTRAINT uq_tires_vin_position UNIQUE (vin, position),
            CONSTRAINT uq_tires_id_vin UNIQUE (id, vin),
            FOREIGN KEY (vin) REFERENCES vehicles(vin) ON DELETE CASCADE,
            FOREIGN KEY (set_id) REFERENCES tire_sets(id) ON DELETE SET NULL
        )
    """)
    cur.execute("""
        INSERT INTO tires_new
            (id, vin, position, brand, model_name, size, dot_code,
             tread_depth_mm, pressure_kpa, min_tread_mm, notes,
             created_at, updated_at)
        SELECT id, vin, position, brand, model_name, size, dot_code,
               tread_depth_mm, pressure_kpa, min_tread_mm, notes,
               created_at, updated_at
        FROM tires
    """)
    cur.execute("DROP TABLE tires")
    cur.execute("ALTER TABLE tires_new RENAME TO tires")
    cur.execute("CREATE INDEX idx_tires_vin ON tires (vin)")


def _rebuild_tire_readings(cur) -> None:
    """Step 6. Add `mount_period_id`, drop `position`'s NOT NULL, move to the
    composite `(tire_id, vin) -> tires(id, vin)`.

    Reproduces what migration **094** left, not what 085 wrote: 094 made
    `tread_depth_mm` nullable so a reader with no tread gauge can log pressure
    alone, and transcribing 085's column list would silently undo it.

    The composite FK is `ON DELETE CASCADE`, unlike the reminder one. A tread
    reading is OWNED by its tire and is meaningless without it, whereas a
    reminder is history about a vehicle that happens to name a tire.
    """
    cur.execute("""
        CREATE TABLE tire_readings_new (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            tire_id          INTEGER NOT NULL,
            vin              VARCHAR(17) NOT NULL,
            position         VARCHAR(10),
            mount_period_id  INTEGER,
            recorded_at      DATE NOT NULL,
            odometer_km      NUMERIC(10, 2),
            tread_depth_mm   NUMERIC(5, 2),
            pressure_kpa     NUMERIC(7, 2),
            notes            TEXT,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tire_id, vin) REFERENCES tires(id, vin) ON DELETE CASCADE,
            FOREIGN KEY (vin) REFERENCES vehicles(vin) ON DELETE CASCADE,
            FOREIGN KEY (mount_period_id) REFERENCES tire_mount_periods(id)
                ON DELETE SET NULL
        )
    """)
    cur.execute("""
        INSERT INTO tire_readings_new
            (id, tire_id, vin, position, recorded_at, odometer_km,
             tread_depth_mm, pressure_kpa, notes, created_at)
        SELECT id, tire_id, vin, position, recorded_at, odometer_km,
               tread_depth_mm, pressure_kpa, notes, created_at
        FROM tire_readings
    """)
    cur.execute("DROP TABLE tire_readings")
    cur.execute("ALTER TABLE tire_readings_new RENAME TO tire_readings")
    cur.execute("CREATE INDEX idx_tire_readings_tire ON tire_readings (tire_id)")
    cur.execute("CREATE INDEX idx_tire_readings_vin ON tire_readings (vin)")
    cur.execute("CREATE INDEX idx_tire_readings_mount_period ON tire_readings (mount_period_id)")


def _rebuild_vehicle_reminders(cur, checks: list[tuple[str, str]]) -> None:
    """Step 7. Add `tire_id`, `source`, and the three low-tread columns.

    The composite FK carries **no `ON DELETE` action**. A referential action
    applies to every column in the FK, so `SET NULL` would try to null `vin`
    as well -- and `vehicle_reminders.vin` is NOT NULL. Measured: SQLite raises
    `NOT NULL constraint failed: vehicle_reminders.vin` and REJECTS the tire
    deletion, so "SET NULL solves the delete problem" is exactly backwards; it
    makes deleting a tire impossible. The service nulls `tire_id` explicitly in
    the same transaction as the delete instead.

    `checks` comes from P2 and may be short: a CHECK the data violates is
    skipped rather than crash-looping a FATAL migration.
    """
    check_sql = "".join(f",\n            CONSTRAINT {n} CHECK ({e})" for n, e in checks)
    cur.execute(f"""
        CREATE TABLE vehicle_reminders_new (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            vin                   VARCHAR(17) NOT NULL,
            line_item_id          INTEGER,
            tire_id               INTEGER,
            source                VARCHAR(20),
            title                 VARCHAR(200) NOT NULL,
            reminder_type         VARCHAR(10) NOT NULL,
            due_date              DATE,
            due_mileage_km        NUMERIC(10, 2),
            due_hours             NUMERIC(10, 1),
            tread_depth_mm        NUMERIC(5, 2),
            tread_threshold_mm    NUMERIC(5, 2),
            projected_distance_km NUMERIC(10, 2),
            status                VARCHAR(10) NOT NULL DEFAULT 'pending',
            notes                 TEXT,
            last_notified_at      DATETIME,
            created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP{check_sql},
            FOREIGN KEY (vin) REFERENCES vehicles(vin) ON DELETE CASCADE,
            FOREIGN KEY (line_item_id) REFERENCES service_line_items(id) ON DELETE SET NULL,
            FOREIGN KEY (tire_id, vin) REFERENCES tires(id, vin)
        )
    """)
    cur.execute("""
        INSERT INTO vehicle_reminders_new
            (id, vin, line_item_id, title, reminder_type, due_date,
             due_mileage_km, due_hours, status, notes, last_notified_at,
             created_at, updated_at)
        SELECT id, vin, line_item_id, title, reminder_type, due_date,
               due_mileage_km, due_hours, status, notes, last_notified_at,
               created_at, updated_at
        FROM vehicle_reminders
    """)
    cur.execute("DROP TABLE vehicle_reminders")
    cur.execute("ALTER TABLE vehicle_reminders_new RENAME TO vehicle_reminders")
    cur.execute("CREATE INDEX ix_reminders_vin_status ON vehicle_reminders (vin, status)")
    cur.execute("CREATE INDEX ix_reminders_due_date ON vehicle_reminders (due_date)")
    cur.execute("CREATE INDEX ix_reminders_due_mileage_km ON vehicle_reminders (due_mileage_km)")


def _ensure_new_tables(cur) -> None:
    """Step 4. `tire_sets` and `tire_mount_periods`.

    On an upgraded instance `create_all()` has already made these from the ORM
    before migrations run, so this is usually a no-op. It exists for the case
    where it has not, and because step 3's `tires.set_id` FK and step 6's
    `mount_period_id` FK both need the targets to exist first.

    Neither table carries a `vin`. `tire_mount_periods` deliberately has none
    (the parent tire is the authority), which is why the "one open period per
    corner per vehicle" rule cannot be a database constraint and is enforced in
    the service instead.
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tire_sets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            vin        VARCHAR(17) NOT NULL,
            name       VARCHAR(60) NOT NULL,
            notes      TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vin) REFERENCES vehicles(vin) ON DELETE CASCADE
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tire_sets_vin ON tire_sets (vin)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tire_mount_periods (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            tire_id                INTEGER NOT NULL,
            position               VARCHAR(10) NOT NULL,
            mounted_on             DATE,
            dismounted_on          DATE,
            mounted_odometer_km    NUMERIC(10, 2),
            dismounted_odometer_km NUMERIC(10, 2),
            is_assumed             BOOLEAN NOT NULL DEFAULT 0,
            observed_active_on     DATE,
            notes                  TEXT,
            created_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tire_id) REFERENCES tires(id) ON DELETE CASCADE
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_tire_mount_periods_tire ON tire_mount_periods (tire_id)"
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tire_single_open_period "
        "ON tire_mount_periods (tire_id) WHERE dismounted_on IS NULL"
    )


def _backfill_periods(cur) -> int:
    """Step 5. One assumed open period per existing tire.

    `mounted_on` comes from the staged `installed_date` and is usually NULL --
    the field existed end to end but had no UI, so almost nobody set it. That
    NULL is the point: the period asserts "this tire was at this corner as of
    the migration date" and nothing about when it got there, which is why
    `distance_on_tire` reports `nothing_bounded` for it rather than inventing a
    figure. `observed_active_on` records the date the assumption was made.

    Only tires that HAVE a position get one. A tire with a NULL position cannot
    exist yet (the column was NOT NULL until step 3), but the filter is written
    anyway so a re-run against a partially-migrated database cannot invent a
    period at a NULL corner.
    """
    cur.execute("""
        INSERT INTO tire_mount_periods
            (tire_id, position, mounted_on, dismounted_on, mounted_odometer_km,
             dismounted_odometer_km, is_assumed, observed_active_on)
        SELECT t.id, t.position, s.installed_date, NULL, NULL, NULL, 1, DATE('now')
        FROM tires t
        LEFT JOIN _mig097_installed_dates s ON s.tire_id = t.id
        WHERE t.position IS NOT NULL
    """)
    return cur.rowcount


def _link_readings_to_periods(cur) -> int:
    """Attach existing readings to the assumed period for their tire.

    Every reading predates the migration, and each tire has exactly one period
    at this point, so the mapping is unambiguous. Without it every historical
    reading would sit with a NULL `mount_period_id` and no surface could
    attribute it to anything.
    """
    cur.execute("""
        UPDATE tire_readings
        SET mount_period_id = (
            SELECT p.id FROM tire_mount_periods p
            WHERE p.tire_id = tire_readings.tire_id
            ORDER BY p.id LIMIT 1
        )
        WHERE mount_period_id IS NULL
    """)
    return cur.rowcount


def _run_sqlite(engine) -> None:
    """The whole migration, on one raw connection, in one transaction.

    `engine.raw_connection()` yields the DB-API connection without SQLAlchemy's
    autobegin layer, so `PRAGMA foreign_keys = OFF` lands OUTSIDE a transaction
    where it actually takes effect. Inside one it is silently ignored and the
    read still returns 1 -- measured -- and the `DROP TABLE tires` in step 3
    would then cascade every `tire_readings` row away without a word.
    """
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        cur.execute("PRAGMA foreign_keys = OFF")
        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 0:
            raise RuntimeError(
                f"PRAGMA foreign_keys = OFF failed; got {fk_state}. "
                "Are we inside an active transaction? Proceeding would let "
                "DROP TABLE tires cascade away every tire_readings row."
            )

        try:
            cur.execute("BEGIN")

            # 1. Preflight.
            _preflight_vin_mismatches(cur)
            checks = _preflight_reminder_checks(cur)

            # 2. Stage installed_date; step 3 drops the column it came from.
            cur.execute("DROP TABLE IF EXISTS _mig097_installed_dates")
            cur.execute(
                "CREATE TABLE _mig097_installed_dates "
                "(tire_id INTEGER PRIMARY KEY, installed_date DATE)"
            )
            cur.execute(
                "INSERT INTO _mig097_installed_dates (tire_id, installed_date) "
                "SELECT id, installed_date FROM tires"
            )

            # 4 before 3: step 3's set_id FK needs tire_sets to exist.
            _ensure_new_tables(cur)
            # 3.
            _rebuild_tires(cur)
            # 5.
            periods = _backfill_periods(cur)
            # 6.
            _rebuild_tire_readings(cur)
            linked = _link_readings_to_periods(cur)
            # 7.
            _rebuild_vehicle_reminders(cur, checks)

            cur.execute("DROP TABLE _mig097_installed_dates")

            violations = cur.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(
                    f"FK violations after the tire rebuilds (pre-commit): {violations!r}"
                )

            cur.execute("COMMIT")
            print(
                f"  → 097: {periods} assumed mount period(s) created, "
                f"{linked} reading(s) linked, "
                f"{len(checks)}/{len(REMINDER_CHECKS)} reminder CHECK(s) installed"
            )
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys = ON")

        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 1:
            raise RuntimeError(f"PRAGMA foreign_keys = ON failed; got {fk_state}.")
    finally:
        raw.close()


# ============================================================================
#  PostgreSQL
# ============================================================================


def _run_postgres(engine) -> None:
    """PostgreSQL has real ALTER TABLE, so nothing is rebuilt.

    That difference matters for the CHECKs: on SQLite an omitted constraint
    vanishes with the old table, whereas here the existing ones are untouched
    and only the missing ones are added. A database created by `create_all`
    has none of the three (the ORM declares no CheckConstraint), while a
    migrated one has all three, so both are handled by adding what is absent.
    """
    with engine.begin() as conn:
        _pg_preflight_vin_mismatches(conn)

        conn.execute(text("ALTER TABLE tires ALTER COLUMN position DROP NOT NULL"))
        conn.execute(text("ALTER TABLE tires ADD COLUMN IF NOT EXISTS set_id INTEGER"))
        conn.execute(text("ALTER TABLE tires ADD COLUMN IF NOT EXISTS retired_on DATE"))
        conn.execute(
            text(
                "DO $$ BEGIN "
                "ALTER TABLE tires ADD CONSTRAINT uq_tires_id_vin UNIQUE (id, vin); "
                "EXCEPTION WHEN duplicate_table THEN NULL; "
                "WHEN duplicate_object THEN NULL; END $$"
            )
        )
        conn.execute(
            text(
                "DO $$ BEGIN "
                "ALTER TABLE tires ADD CONSTRAINT fk_tires_set_id "
                "FOREIGN KEY (set_id) REFERENCES tire_sets(id) ON DELETE SET NULL; "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
        )

        conn.execute(text("ALTER TABLE tire_readings ALTER COLUMN position DROP NOT NULL"))
        conn.execute(
            text("ALTER TABLE tire_readings ADD COLUMN IF NOT EXISTS mount_period_id INTEGER")
        )
        conn.execute(
            text(
                "DO $$ BEGIN "
                "ALTER TABLE tire_readings ADD CONSTRAINT fk_tire_readings_mount_period "
                "FOREIGN KEY (mount_period_id) REFERENCES tire_mount_periods(id) "
                "ON DELETE SET NULL; "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
        )
        conn.execute(
            text(
                "DO $$ BEGIN "
                "ALTER TABLE tire_readings ADD CONSTRAINT fk_tire_readings_tire_vin "
                "FOREIGN KEY (tire_id, vin) REFERENCES tires(id, vin) ON DELETE CASCADE; "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_tire_readings_mount_period "
                "ON tire_readings (mount_period_id)"
            )
        )

        for column, ddl in (
            ("tire_id", "INTEGER"),
            ("source", "VARCHAR(20)"),
            ("tread_depth_mm", "NUMERIC(5, 2)"),
            ("tread_threshold_mm", "NUMERIC(5, 2)"),
            ("projected_distance_km", "NUMERIC(10, 2)"),
        ):
            conn.execute(
                text(f"ALTER TABLE vehicle_reminders ADD COLUMN IF NOT EXISTS {column} {ddl}")
            )
        conn.execute(
            text(
                "DO $$ BEGIN "
                "ALTER TABLE vehicle_reminders ADD CONSTRAINT fk_reminders_tire_vin "
                "FOREIGN KEY (tire_id, vin) REFERENCES tires(id, vin); "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
        )
        # Same P2 policy as SQLite: add only the CHECKs the data can take.
        for name, expression, scan in REMINDER_CHECKS:
            violations = [r[0] for r in conn.execute(text(scan)).fetchall()]
            if violations:
                print(
                    f"  → P2: SKIPPING {name}; {len(violations)} row(s) violate it: {violations}."
                )
                continue
            conn.execute(
                text(
                    f"DO $$ BEGIN "
                    f"ALTER TABLE vehicle_reminders ADD CONSTRAINT {name} "
                    f"CHECK ({expression}); "
                    f"EXCEPTION WHEN duplicate_object THEN NULL; END $$"
                )
            )

        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_tire_single_open_period "
                "ON tire_mount_periods (tire_id) WHERE dismounted_on IS NULL"
            )
        )

        # Steps 5 and its reading links, then drop the source column.
        result = conn.execute(
            text(
                "INSERT INTO tire_mount_periods "
                "(tire_id, position, mounted_on, dismounted_on, mounted_odometer_km, "
                " dismounted_odometer_km, is_assumed, observed_active_on) "
                "SELECT t.id, t.position, t.installed_date, NULL, NULL, NULL, true, "
                "       CURRENT_DATE "
                "FROM tires t WHERE t.position IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE tire_readings SET mount_period_id = ("
                "  SELECT p.id FROM tire_mount_periods p "
                "  WHERE p.tire_id = tire_readings.tire_id ORDER BY p.id LIMIT 1) "
                "WHERE mount_period_id IS NULL"
            )
        )
        conn.execute(text("ALTER TABLE tires DROP COLUMN IF EXISTS installed_date"))
        print(f"  → 097: {result.rowcount} assumed mount period(s) created")


def _pg_preflight_vin_mismatches(conn) -> None:
    """P1 on PostgreSQL. Same repair, expressed as an UPDATE ... FROM."""
    for table in ("tire_readings", "vehicle_reminders"):
        has_tire_id = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = 'tire_id'"
            ),
            {"t": table},
        ).first()
        if not has_tire_id:
            continue
        bad = [
            r[0]
            for r in conn.execute(
                text(
                    f"SELECT c.id FROM {table} c JOIN tires t ON t.id = c.tire_id "
                    f"WHERE c.vin <> t.vin"
                )
            ).fetchall()
        ]
        if not bad:
            continue
        print(f"  → P1: repairing {len(bad)} {table} row(s) with a mismatched vin: {bad}")
        conn.execute(
            text(
                f"UPDATE {table} c SET vin = t.vin FROM tires t "
                f"WHERE t.id = c.tire_id AND c.vin <> t.vin"
            )
        )


# ============================================================================
#  Entry point
# ============================================================================


def upgrade(engine=None) -> None:
    """Run the migration, or return cleanly if it has already been applied.

    RE-ENTRANCY. With steps 1-7 in one transaction the observable states
    collapse to two, and the discriminator is the LAST thing this migration
    writes (`vehicle_reminders.source`), not the first.

    Keying on the presence of `tire_mount_periods` would be wrong: `create_all`
    creates that table from the ORM on every upgrade BEFORE migrations run, so
    "periods exist" is true of a database that has done nothing. Keying on
    `tires.installed_date` alone would be wrong the other way: a fresh
    `create_all` database never had the column, and would look mid-migration.

    | Observed | Meaning | Action |
    |---|---|---|
    | `vehicle_reminders.source` exists | 097 finished (or fresh create_all) | return |
    | otherwise | legacy schema | run steps 1-7 |
    """
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("tires"):
        print("  → tires missing; skip (run the earlier migrations first)")
        return

    reminder_columns = {c["name"] for c in inspector.get_columns("vehicle_reminders")}
    if "source" in reminder_columns:
        print("  → 097 already applied (vehicle_reminders.source present); nothing to do")
        return

    _preflight_backup_marker(engine)

    if engine.dialect.name == "postgresql":
        _run_postgres(engine)
    else:
        _run_sqlite(engine)
