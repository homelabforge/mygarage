"""Migration 097: tire mount periods, nullable position, retired_on.

Every test builds a throwaway SQLite database from scratch, so these are
independent of the shared test database.

The hazard this migration is built around is worth restating, because it is
silent: `PRAGMA foreign_keys = OFF` is a **no-op inside a transaction** and
SQLite reports no error -- the pragma read still returns 1. A rebuild that
assumes it worked fires `ON DELETE CASCADE` on `DROP TABLE tires` and takes
every `tire_readings` row with it, leaving a schema that looks correct and a
database with no tread history. `test_the_cascade_hazard_is_real` demonstrates
it rather than describing it.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

_MIGRATION = (
    Path(__file__).parent.parent.parent / "app" / "migrations" / "097_tire_mount_periods.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m097", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_schema(path: Path) -> None:
    """The v3.2.0 shape of every table 097 touches."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE vehicles (
            vin VARCHAR(17) PRIMARY KEY,
            nickname VARCHAR(100)
        );
        CREATE TABLE service_line_items (id INTEGER PRIMARY KEY);
        CREATE TABLE tires (
            id INTEGER NOT NULL,
            vin VARCHAR(17) NOT NULL,
            position VARCHAR(10) NOT NULL,
            brand VARCHAR(80),
            model_name VARCHAR(80),
            size VARCHAR(40),
            dot_code VARCHAR(20),
            installed_date DATE,
            tread_depth_mm NUMERIC(5, 2),
            pressure_kpa NUMERIC(7, 2),
            min_tread_mm NUMERIC(5, 2),
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_tires_vin_position UNIQUE (vin, position),
            FOREIGN KEY(vin) REFERENCES vehicles (vin) ON DELETE CASCADE
        );
        CREATE INDEX idx_tires_vin ON tires (vin);
        CREATE TABLE tire_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tire_id INTEGER NOT NULL,
            vin VARCHAR(17) NOT NULL,
            position VARCHAR(10) NOT NULL,
            recorded_at DATE NOT NULL,
            odometer_km NUMERIC(10, 2),
            tread_depth_mm NUMERIC(5, 2),
            pressure_kpa NUMERIC(7, 2),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tire_id) REFERENCES tires(id) ON DELETE CASCADE,
            FOREIGN KEY (vin) REFERENCES vehicles(vin) ON DELETE CASCADE
        );
        CREATE INDEX idx_tire_readings_tire ON tire_readings (tire_id);
        CREATE INDEX idx_tire_readings_vin ON tire_readings (vin);
        CREATE TABLE vehicle_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
            line_item_id INTEGER REFERENCES service_line_items(id) ON DELETE SET NULL,
            title VARCHAR(200) NOT NULL,
            reminder_type VARCHAR(10) NOT NULL
                CHECK (reminder_type IN ('date','mileage','both','smart','hours')),
            due_date DATE,
            due_mileage_km NUMERIC(10,2)
                CHECK (due_mileage_km IS NULL OR due_mileage_km > 0),
            due_hours NUMERIC(10,1),
            status VARCHAR(10) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','done','dismissed')),
            notes TEXT,
            last_notified_at DATETIME,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX ix_reminders_vin_status ON vehicle_reminders (vin, status);
        CREATE INDEX ix_reminders_due_date ON vehicle_reminders (due_date);
        CREATE INDEX ix_reminders_due_mileage_km ON vehicle_reminders (due_mileage_km);
        INSERT INTO vehicles (vin, nickname) VALUES ('VINAAA00000000001', 'A');
        INSERT INTO vehicles (vin, nickname) VALUES ('VINBBB00000000002', 'B');
    """)
    conn.commit()
    conn.close()


def _seed_tire(
    path: Path,
    *,
    tire_id: int,
    vin: str,
    position: str,
    installed: str | None = None,
    readings: int = 1,
) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO tires (id, vin, position, installed_date, tread_depth_mm, "
        "min_tread_mm) VALUES (?, ?, ?, ?, 8.0, 2.0)",
        (tire_id, vin, position, installed),
    )
    for n in range(readings):
        conn.execute(
            "INSERT INTO tire_readings (tire_id, vin, position, recorded_at, "
            "tread_depth_mm) VALUES (?, ?, ?, ?, ?)",
            (tire_id, vin, position, f"2026-0{n + 1}-01", 8.0 - n),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def legacy_db(tmp_path: Path) -> Path:
    path = tmp_path / "legacy.db"
    _legacy_schema(path)
    return path


class TestTheMigrationPreservesData:
    def test_readings_survive_the_tires_rebuild(self, legacy_db: Path):
        """The cascade hazard, asserted on the outcome.

        `DROP TABLE tires` in step 3 will fire `ON DELETE CASCADE` on
        `tire_readings` unless FK enforcement is genuinely off. Two readings in,
        two readings out.
        """
        _seed_tire(legacy_db, tire_id=1, vin="VINAAA00000000001", position="FL", readings=2)
        _load_migration().upgrade(create_engine(f"sqlite:///{legacy_db}"))

        conn = sqlite3.connect(legacy_db)
        assert conn.execute("SELECT COUNT(*) FROM tire_readings").fetchone()[0] == 2
        conn.close()

    def test_the_cascade_hazard_is_real(self, tmp_path: Path):
        """Demonstrates WHY the pragma read-back exists, rather than asserting
        that the code contains it.

        With FK enforcement on, dropping the parent silently empties the child.
        Inside a transaction the pragma cannot be turned off, and reading it
        back still reports 1 -- so a migration that sets it and trusts the set
        loses the data with no error anywhere.
        """
        path = tmp_path / "hazard.db"
        _legacy_schema(path)
        _seed_tire(path, tire_id=1, vin="VINAAA00000000001", position="FL", readings=2)

        conn = sqlite3.connect(path)
        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute("SELECT COUNT(*) FROM tire_readings").fetchone()[0] == 2

        conn.execute("BEGIN")
        conn.execute("PRAGMA foreign_keys = OFF")  # a no-op inside a transaction
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1, (
            "the pragma reports success while having done nothing, which is the "
            "whole reason 097 sets it on a raw connection outside any transaction"
        )
        conn.execute("DROP TABLE tires")
        assert conn.execute("SELECT COUNT(*) FROM tire_readings").fetchone()[0] == 0, (
            "expected the cascade to empty tire_readings; if this ever stops "
            "being true the read-back guard could be relaxed"
        )
        conn.close()

    def test_reminders_survive_and_gain_their_columns(self, legacy_db: Path):
        conn = sqlite3.connect(legacy_db)
        conn.execute(
            "INSERT INTO vehicle_reminders (vin, title, reminder_type, status) "
            "VALUES ('VINAAA00000000001', 'Keep me', 'date', 'pending')"
        )
        conn.commit()
        conn.close()

        _load_migration().upgrade(create_engine(f"sqlite:///{legacy_db}"))

        conn = sqlite3.connect(legacy_db)
        rows = conn.execute("SELECT title, tire_id, source FROM vehicle_reminders").fetchall()
        assert rows == [("Keep me", None, None)]
        conn.close()

    def test_an_assumed_period_is_created_per_mounted_tire(self, legacy_db: Path):
        _seed_tire(
            legacy_db, tire_id=1, vin="VINAAA00000000001", position="FL", installed="2024-03-01"
        )
        _seed_tire(legacy_db, tire_id=2, vin="VINAAA00000000001", position="FR")
        _load_migration().upgrade(create_engine(f"sqlite:///{legacy_db}"))

        conn = sqlite3.connect(legacy_db)
        periods = conn.execute(
            "SELECT tire_id, position, mounted_on, is_assumed, observed_active_on "
            "FROM tire_mount_periods ORDER BY tire_id"
        ).fetchall()
        assert len(periods) == 2
        # The tire that HAD an installed_date keeps it as the period start.
        assert periods[0][:4] == (1, "FL", "2024-03-01", 1)
        # The one that did not gets a NULL start -- unknown, not invented. That
        # is what makes distance_on_tire report `nothing_bounded` for it.
        assert periods[1][:4] == (2, "FR", None, 1)
        # Both record WHEN the assumption was made.
        assert all(p[4] is not None for p in periods)
        conn.close()

    def test_existing_readings_are_attached_to_the_assumed_period(self, legacy_db: Path):
        _seed_tire(legacy_db, tire_id=1, vin="VINAAA00000000001", position="FL", readings=3)
        _load_migration().upgrade(create_engine(f"sqlite:///{legacy_db}"))

        conn = sqlite3.connect(legacy_db)
        unlinked = conn.execute(
            "SELECT COUNT(*) FROM tire_readings WHERE mount_period_id IS NULL"
        ).fetchone()[0]
        assert unlinked == 0
        conn.close()


class TestPreflight:
    def test_p1_repairs_a_child_whose_vin_disagrees_with_its_tire(self, legacy_db: Path):
        """The composite FK makes this row impossible, so it must be repaired
        BEFORE the FK is installed, not discovered by it."""
        _seed_tire(legacy_db, tire_id=1, vin="VINAAA00000000001", position="FL", readings=0)
        conn = sqlite3.connect(legacy_db)
        conn.execute(
            "INSERT INTO tire_readings (tire_id, vin, position, recorded_at, "
            "tread_depth_mm) VALUES (1, 'VINBBB00000000002', 'FL', '2026-01-01', 7.0)"
        )
        conn.commit()
        conn.close()

        _load_migration().upgrade(create_engine(f"sqlite:///{legacy_db}"))

        conn = sqlite3.connect(legacy_db)
        # Repaired to the TIRE's vin, not deleted: the tire is the authority
        # and the denormalised vin on the child is the copy.
        assert conn.execute("SELECT vin FROM tire_readings").fetchall() == [("VINAAA00000000001",)]
        conn.close()

    def test_p2_skips_a_violated_check_instead_of_crash_looping(self, legacy_db: Path):
        """A FATAL migration that raises here does not fail once: the app
        crash-loops on every restart until someone with database access repairs
        the row by hand. A missing constraint is recoverable; that is not.

        The violating value is one the application can actually produce: the
        legacy JSON importer derives `has_miles` from
        `bool(is_recurring and recurrence_miles)`, which is true for a negative.
        """
        conn = sqlite3.connect(legacy_db)
        # Insert past the CHECK the same way a pre-053 database would carry it.
        conn.execute("PRAGMA writable_schema = ON")
        conn.execute(
            "UPDATE sqlite_master SET sql = replace(sql, "
            "'CHECK (due_mileage_km IS NULL OR due_mileage_km > 0)', '') "
            "WHERE name = 'vehicle_reminders'"
        )
        conn.execute("PRAGMA writable_schema = OFF")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(legacy_db)
        conn.execute(
            "INSERT INTO vehicle_reminders (vin, title, reminder_type, status, "
            "due_mileage_km) VALUES ('VINAAA00000000001', 'Negative', 'mileage', "
            "'pending', -5)"
        )
        conn.commit()
        conn.close()

        # Must NOT raise.
        _load_migration().upgrade(create_engine(f"sqlite:///{legacy_db}"))

        conn = sqlite3.connect(legacy_db)
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'vehicle_reminders'"
        ).fetchone()[0]
        # The two it CAN take are installed; the one it cannot is skipped.
        assert "check_reminder_type" in sql
        assert "check_reminder_status" in sql
        assert "check_due_mileage_km" not in sql
        # And the offending row survives, so it can be repaired.
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM vehicle_reminders WHERE due_mileage_km = -5"
            ).fetchone()[0]
            == 1
        )
        conn.close()

    def test_all_three_checks_are_installed_when_the_data_is_clean(self, legacy_db: Path):
        """The other direction. Without this, a P2 that skipped everything
        would pass the test above."""
        _load_migration().upgrade(create_engine(f"sqlite:///{legacy_db}"))
        conn = sqlite3.connect(legacy_db)
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'vehicle_reminders'"
        ).fetchone()[0]
        for name in ("check_reminder_type", "check_reminder_status", "check_due_mileage_km"):
            assert name in sql, f"{name} missing from a clean upgrade"
        conn.close()


class TestReEntrancy:
    def test_running_twice_is_a_no_op(self, legacy_db: Path):
        _seed_tire(legacy_db, tire_id=1, vin="VINAAA00000000001", position="FL", readings=2)
        migration = _load_migration()
        engine = create_engine(f"sqlite:///{legacy_db}")

        migration.upgrade(engine)
        migration.upgrade(engine)

        conn = sqlite3.connect(legacy_db)
        # One period, not two: the second run must not backfill again.
        assert conn.execute("SELECT COUNT(*) FROM tire_mount_periods").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM tire_readings").fetchone()[0] == 2
        conn.close()

    def test_a_fresh_create_all_database_is_left_alone(self, tmp_path: Path):
        """The discriminator is `vehicle_reminders.source`, the LAST thing 097
        writes -- not `tire_mount_periods`, which `create_all` makes on every
        upgrade before migrations run, and not `tires.installed_date`, which a
        fresh database never had.
        """
        from app.database import Base

        path = tmp_path / "fresh.db"
        engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(engine)

        _load_migration().upgrade(engine)

        conn = sqlite3.connect(path)
        assert conn.execute("SELECT COUNT(*) FROM tire_mount_periods").fetchone()[0] == 0
        conn.close()


class TestSchemaParity:
    """A fresh install and an upgraded one must end up with the same schema.

    Comparing `create_all` against `create_all` + a no-op 097 proves nothing.
    The comparison that matters is a BARE `create_all` against
    legacy + 097, which is the pair that can actually diverge.
    """

    @staticmethod
    def _shape(engine) -> dict[str, set[str]]:
        insp = inspect(engine)
        shape = {}
        for table in ("tires", "tire_readings", "tire_mount_periods", "tire_sets"):
            shape[table] = {c["name"] for c in insp.get_columns(table)}
        shape["vehicle_reminders"] = {c["name"] for c in insp.get_columns("vehicle_reminders")}
        return shape

    def test_upgraded_columns_match_a_fresh_install(self, legacy_db: Path, tmp_path: Path):
        from app.database import Base

        _seed_tire(legacy_db, tire_id=1, vin="VINAAA00000000001", position="FL")
        upgraded = create_engine(f"sqlite:///{legacy_db}")
        _load_migration().upgrade(upgraded)

        fresh_path = tmp_path / "fresh_parity.db"
        fresh = create_engine(f"sqlite:///{fresh_path}")
        Base.metadata.create_all(fresh)

        assert self._shape(upgraded) == self._shape(fresh)

    def test_the_open_period_index_exists_on_both_paths(self, legacy_db: Path, tmp_path: Path):
        """A tire cannot be mounted in two places at once, and that has to be
        true however the database was built."""
        from app.database import Base

        upgraded = create_engine(f"sqlite:///{legacy_db}")
        _load_migration().upgrade(upgraded)
        fresh_path = tmp_path / "fresh_idx.db"
        fresh = create_engine(f"sqlite:///{fresh_path}")
        Base.metadata.create_all(fresh)

        for engine in (upgraded, fresh):
            names = {i["name"] for i in inspect(engine).get_indexes("tire_mount_periods")}
            assert "uq_tire_single_open_period" in names

    def test_uq_tires_vin_position_survives_the_rebuild(self, legacy_db: Path):
        """It is the only thing stopping two mounted tires sharing a corner,
        and a SQLite rebuild keeps only what the new CREATE TABLE names."""
        _load_migration().upgrade(create_engine(f"sqlite:///{legacy_db}"))
        conn = sqlite3.connect(legacy_db)
        conn.execute("INSERT INTO tires (vin, position) VALUES ('VINAAA00000000001', 'FL')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tires (vin, position) VALUES ('VINAAA00000000001', 'FL')")
        conn.close()

    def test_two_stored_tires_can_coexist(self, legacy_db: Path):
        """The property that actually CHANGED. NULLs compare as distinct under
        UNIQUE, so a nullable `position` makes the same constraint mounted-only
        without a partial-index replacement.

        Note this is asserted alongside the test above, not instead of it: on
        its own it would also pass against a schema that dropped the constraint
        entirely.
        """
        _load_migration().upgrade(create_engine(f"sqlite:///{legacy_db}"))
        conn = sqlite3.connect(legacy_db)
        conn.execute("INSERT INTO tires (vin, position) VALUES ('VINAAA00000000001', NULL)")
        conn.execute("INSERT INTO tires (vin, position) VALUES ('VINAAA00000000001', NULL)")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM tires WHERE position IS NULL").fetchone()[0] == 2
        conn.close()


_PG_LEGACY = """
CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, nickname VARCHAR(100));
CREATE TABLE service_line_items (id SERIAL PRIMARY KEY);
CREATE TABLE tires (
    id SERIAL PRIMARY KEY,
    vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
    position VARCHAR(10) NOT NULL,
    brand VARCHAR(80), model_name VARCHAR(80), size VARCHAR(40),
    dot_code VARCHAR(20), installed_date DATE,
    tread_depth_mm NUMERIC(5,2), pressure_kpa NUMERIC(7,2),
    min_tread_mm NUMERIC(5,2), notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_tires_vin_position UNIQUE (vin, position)
);
CREATE INDEX idx_tires_vin ON tires (vin);
CREATE TABLE tire_readings (
    id SERIAL PRIMARY KEY,
    tire_id INTEGER NOT NULL REFERENCES tires(id) ON DELETE CASCADE,
    vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
    position VARCHAR(10) NOT NULL,
    recorded_at DATE NOT NULL,
    odometer_km NUMERIC(10,2), tread_depth_mm NUMERIC(5,2),
    pressure_kpa NUMERIC(7,2), notes TEXT,
    created_at TIMESTAMP DEFAULT now()
);
CREATE TABLE tire_sets (
    id SERIAL PRIMARY KEY,
    vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
    name VARCHAR(60) NOT NULL, notes TEXT,
    created_at TIMESTAMP DEFAULT now()
);
CREATE TABLE tire_mount_periods (
    id SERIAL PRIMARY KEY,
    tire_id INTEGER NOT NULL REFERENCES tires(id) ON DELETE CASCADE,
    position VARCHAR(10) NOT NULL,
    mounted_on DATE, dismounted_on DATE,
    mounted_odometer_km NUMERIC(10,2), dismounted_odometer_km NUMERIC(10,2),
    is_assumed BOOLEAN NOT NULL DEFAULT false,
    observed_active_on DATE, notes TEXT,
    created_at TIMESTAMP DEFAULT now()
);
CREATE TABLE vehicle_reminders (
    id SERIAL PRIMARY KEY,
    vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
    line_item_id INTEGER REFERENCES service_line_items(id) ON DELETE SET NULL,
    title VARCHAR(200) NOT NULL,
    reminder_type VARCHAR(10) NOT NULL,
    due_date DATE, due_mileage_km NUMERIC(10,2), due_hours NUMERIC(10,1),
    status VARCHAR(10) NOT NULL DEFAULT 'pending',
    notes TEXT, last_notified_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX ix_reminders_vin_status ON vehicle_reminders (vin, status);
CREATE INDEX ix_reminders_due_date ON vehicle_reminders (due_date);
CREATE INDEX ix_reminders_due_mileage_km ON vehicle_reminders (due_mileage_km);
INSERT INTO vehicles (vin, nickname) VALUES ('VINAAA00000000001', 'A');
INSERT INTO tires (vin, position, installed_date) VALUES
    ('VINAAA00000000001', 'FL', '2024-03-01'),
    ('VINAAA00000000001', 'FR', NULL);
INSERT INTO tire_readings (tire_id, vin, position, recorded_at, tread_depth_mm)
    SELECT id, vin, position, DATE '2026-01-01', 8.0 FROM tires;
INSERT INTO vehicle_reminders (vin, title, reminder_type, status)
    VALUES ('VINAAA00000000001', 'Keep me', 'date', 'pending');
"""


class TestPostgres:
    """097's PostgreSQL branch, which is a different implementation.

    PostgreSQL has real `ALTER TABLE`, so nothing is rebuilt and none of the
    SQLite rebuild machinery runs. That branch was previously exercised by
    nothing at all: on PostgreSQL the suite's own database is built by
    `create_all`, which already has the new shape, so 097 sees its own
    discriminator and returns before touching anything.
    """

    def test_the_upgrade_runs_and_keeps_the_data(self, pg_engine):
        with pg_engine.begin() as conn:
            for statement in _PG_LEGACY.strip().split(";\n"):
                if statement.strip():
                    conn.execute(text(statement))

        _load_migration().upgrade(pg_engine)

        insp = inspect(pg_engine)
        tire_columns = {c["name"] for c in insp.get_columns("tires")}
        assert "installed_date" not in tire_columns
        assert {"set_id", "retired_on"} <= tire_columns

        reminder_columns = {c["name"] for c in insp.get_columns("vehicle_reminders")}
        assert {"tire_id", "source", "tread_depth_mm"} <= reminder_columns

        with pg_engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM tire_readings")).scalar() == 2
            assert conn.execute(text("SELECT COUNT(*) FROM vehicle_reminders")).scalar() == 1
            periods = conn.execute(
                text(
                    "SELECT position, mounted_on, is_assumed FROM tire_mount_periods "
                    "ORDER BY position"
                )
            ).fetchall()
        assert len(periods) == 2
        assert periods[0][1] is not None and periods[0][2] is True
        # The tire with no installed_date gets a period with an unknown start.
        assert periods[1][1] is None

    def test_position_becomes_nullable_and_stored_tires_coexist(self, pg_engine):
        with pg_engine.begin() as conn:
            for statement in _PG_LEGACY.strip().split(";\n"):
                if statement.strip():
                    conn.execute(text(statement))
        _load_migration().upgrade(pg_engine)

        # The NULL-distinct property this design depends on, on PostgreSQL too.
        with pg_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO tires (vin, position) VALUES ('VINAAA00000000001', NULL)")
            )
            conn.execute(
                text("INSERT INTO tires (vin, position) VALUES ('VINAAA00000000001', NULL)")
            )
        with pg_engine.connect() as conn:
            assert (
                conn.execute(text("SELECT COUNT(*) FROM tires WHERE position IS NULL")).scalar()
                == 2
            )

    def test_running_twice_is_a_no_op(self, pg_engine):
        with pg_engine.begin() as conn:
            for statement in _PG_LEGACY.strip().split(";\n"):
                if statement.strip():
                    conn.execute(text(statement))
        migration = _load_migration()
        migration.upgrade(pg_engine)
        migration.upgrade(pg_engine)

        with pg_engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM tire_mount_periods")).scalar() == 2
