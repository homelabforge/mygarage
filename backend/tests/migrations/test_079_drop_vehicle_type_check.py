"""Correctness + safety tests for migration 079_drop_vehicle_type_check.

Covers:
- Pre-migration, a bad vehicle_type ('ATV') is rejected by the CHECK.
- Post-migration, the CHECK is gone and 'ATV' inserts succeed.
- The rebuild PRESERVES existing vehicle rows AND a child row that FKs to
  vehicles(vin) — the risky part, since vehicles is an FK parent.
- Foreign keys still enforce after the rebuild (a dangling child insert fails).
- The vehicle_type index survives.
- Re-running the migration is a no-op (idempotent).
"""

from __future__ import annotations

import importlib.util
import sqlite3
import types
from contextlib import closing
from pathlib import Path

import pytest

_TYPES = (
    "('Car','Truck','SUV','Motorcycle','RV','Trailer',"
    "'FifthWheel','TravelTrailer','Electric','Hybrid')"
)

# The CHECK appears in four shapes in the wild, and the shape decides whether
# stripping it strands a comma. Every test below runs against all four.
#
# `inline` is what the early hand-written CREATE TABLE migrations produced, and
# was the ONLY shape covered before v3.0.0-rc3 — which is exactly why the
# table-level breakage shipped green. `create_all` emitted the table-level shape
# for the CheckConstraint the model declared from v2.14.0 until v3.0.0, so real
# installs carry it (reported by @SCDT95 against rc2, PR #137).
_VEHICLES_DDL_SHAPES = {
    # Column constraint. Deleting the clause leaves "NOT NULL ," — already valid.
    "inline": f"""
CREATE TABLE "vehicles" (
    vin VARCHAR(17) PRIMARY KEY,
    nickname VARCHAR(100) NOT NULL,
    vehicle_type VARCHAR(20) NOT NULL
        CHECK (vehicle_type IN
            {_TYPES}),
    year INTEGER,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at DATETIME
);
""",
    # What create_all emits: all columns, then the table constraints. SQLite
    # requires that order, so the CHECK can only ever be followed by another
    # table constraint — never by a column. Strands ",  ," -> `near ","`.
    "table_level_mid": f"""
CREATE TABLE "vehicles" (
    vin VARCHAR(17) NOT NULL,
    nickname VARCHAR(100) NOT NULL,
    vehicle_type VARCHAR(20) NOT NULL,
    year INTEGER,
    user_id INTEGER,
    created_at DATETIME,
    CHECK (vehicle_type IN {_TYPES}),
    PRIMARY KEY (vin),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
""",
    # Same, but the CHECK is the final item in the body: strands ",  )" -> `near ")"`.
    "table_level_last": f"""
CREATE TABLE "vehicles" (
    vin VARCHAR(17) NOT NULL,
    nickname VARCHAR(100) NOT NULL,
    vehicle_type VARCHAR(20) NOT NULL,
    year INTEGER,
    user_id INTEGER,
    created_at DATETIME,
    PRIMARY KEY (vin),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    CHECK (vehicle_type IN {_TYPES})
);
""",
    # Named table constraint — same stranding, plus the CONSTRAINT <name> prefix.
    "named_constraint": f"""
CREATE TABLE "vehicles" (
    vin VARCHAR(17) NOT NULL,
    nickname VARCHAR(100) NOT NULL,
    vehicle_type VARCHAR(20) NOT NULL,
    year INTEGER,
    user_id INTEGER,
    created_at DATETIME,
    CONSTRAINT check_vehicle_type CHECK (vehicle_type IN {_TYPES}),
    PRIMARY KEY (vin),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
""",
}

_SHAPES = pytest.mark.parametrize("ddl_shape", sorted(_VEHICLES_DDL_SHAPES))


def _load_migration() -> types.ModuleType:
    path = (
        Path(__file__).parent.parent.parent
        / "app"
        / "migrations"
        / "079_drop_vehicle_type_check.py"
    )
    spec = importlib.util.spec_from_file_location("m079", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _connect(db_file: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _setup_db(db_file: Path, ddl_shape: str = "inline") -> None:
    conn = _connect(db_file)
    conn.executescript(
        _VEHICLES_DDL_SHAPES[ddl_shape]
        + """
        CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(100));
        CREATE INDEX idx_vehicles_type ON vehicles(vehicle_type);
        CREATE TABLE service_visits (
            id INTEGER PRIMARY KEY,
            vehicle_vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE
        );
        INSERT INTO users (id, username) VALUES (1, 'jamey');
        INSERT INTO vehicles (vin, nickname, vehicle_type, year, user_id)
            VALUES ('CARVIN00000000001', 'DailyDriver', 'Car', 2020, 1);
        INSERT INTO service_visits (id, vehicle_vin) VALUES (1, 'CARVIN00000000001');
        """
    )
    conn.commit()
    conn.close()


@_SHAPES
def test_check_dropped_and_atv_insertable_preserving_data(
    tmp_path: Path, ddl_shape: str, sync_engine
) -> None:
    db_file = tmp_path / "m079.db"
    _setup_db(db_file, ddl_shape)
    m = _load_migration()

    # Pre-migration: the CHECK rejects a new type.
    conn = _connect(db_file)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO vehicles (vin, nickname, vehicle_type, user_id) "
            "VALUES ('ATVVIN00000000001', 'QuadA', 'ATV', 1)"
        )
    conn.rollback()
    conn.close()

    engine = sync_engine(f"sqlite:///{db_file}")
    m.upgrade(engine)

    conn = _connect(db_file)
    # CHECK is gone from the rebuilt table.
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='vehicles'"
    ).fetchone()[0]
    assert "CHECK" not in ddl.upper()

    # 'ATV' now inserts.
    conn.execute(
        "INSERT INTO vehicles (vin, nickname, vehicle_type, user_id) "
        "VALUES ('ATVVIN00000000001', 'QuadA', 'ATV', 1)"
    )
    conn.commit()

    # Existing vehicle row + its FK child survived the rebuild.
    row = conn.execute(
        "SELECT nickname, vehicle_type, year, user_id FROM vehicles WHERE vin='CARVIN00000000001'"
    ).fetchone()
    assert row == ("DailyDriver", "Car", 2020, 1)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM service_visits WHERE vehicle_vin='CARVIN00000000001'"
        ).fetchone()[0]
        == 1
    )

    # FK enforcement still works after the rebuild (dangling child rejected).
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO service_visits (id, vehicle_vin) VALUES (2, 'NOSUCHVIN00000001')")
    conn.rollback()

    # Index survived.
    idx = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_vehicles_type'"
    ).fetchone()
    assert idx is not None
    conn.close()


@_SHAPES
def test_idempotent_rerun_is_noop(tmp_path: Path, ddl_shape: str, sync_engine) -> None:
    db_file = tmp_path / "m079_idem.db"
    _setup_db(db_file, ddl_shape)
    m = _load_migration()
    engine = sync_engine(f"sqlite:///{db_file}")

    m.upgrade(engine)
    m.upgrade(engine)  # second run must not raise

    conn = _connect(db_file)
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='vehicles'"
    ).fetchone()[0]
    assert "CHECK" not in ddl.upper()
    # Original row still intact after two runs.
    assert (
        conn.execute("SELECT COUNT(*) FROM vehicles WHERE vin='CARVIN00000000001'").fetchone()[0]
        == 1
    )
    conn.close()


@_SHAPES
def test_strip_check_produces_valid_ddl_for_every_shape(ddl_shape: str) -> None:
    """_strip_check must leave executable DDL whatever shape the CHECK was in.

    Guards the comma repair directly, without a rebuild in the way, so a failure
    points at the regex rather than at the table swap.
    """
    m = _load_migration()
    stripped = m._strip_check(_VEHICLES_DDL_SHAPES[ddl_shape])
    assert "CHECK" not in stripped.upper()
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute(stripped.replace('"vehicles"', '"vehicles_new"').strip().rstrip(";"))


def test_strip_check_keeps_the_column_separator_comma() -> None:
    """The inline shape's trailing comma separates COLUMNS — it must survive.

    Folding the comma into _CHECK_RE (the first fix attempted for this bug)
    passes every table-level shape and silently welds `vehicle_type` onto the
    next column, so the table comes back a column short. Assert the columns,
    not just that the DDL parses.
    """
    m = _load_migration()
    stripped = m._strip_check(_VEHICLES_DDL_SHAPES["inline"])
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute(stripped.replace('"vehicles"', '"vehicles_new"').strip().rstrip(";"))
        cols = [r[1] for r in conn.execute('PRAGMA table_info("vehicles_new")')]
    assert cols == ["vin", "nickname", "vehicle_type", "year", "user_id", "created_at"]
