"""`drop_check_constraint` on SQLite, over every shape the CHECK takes (#211).

The same four shapes 079 learnt the hard way (issue #137): inline on the
column, table-level mid-body, table-level last, named constraint. The table
under test is `tax_records`, an FK child of `vehicles`, with an index and a
row that must survive the rebuild.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.utils.check_constraint import drop_check_constraint, strip_check

_VALUES = "('Registration', 'Inspection', 'Property Tax', 'Tolls')"

_SHAPES = {
    "inline": f"""
CREATE TABLE "tax_records" (
    id INTEGER PRIMARY KEY,
    vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
    date DATE NOT NULL,
    tax_type VARCHAR(30) CHECK (tax_type IN {_VALUES}),
    amount NUMERIC(12, 2) NOT NULL,
    notes TEXT
);
""",
    "table_level_mid": f"""
CREATE TABLE "tax_records" (
    id INTEGER NOT NULL,
    vin VARCHAR(17) NOT NULL,
    date DATE NOT NULL,
    tax_type VARCHAR(30),
    amount NUMERIC(12, 2) NOT NULL,
    notes TEXT,
    CHECK (tax_type IN {_VALUES}),
    PRIMARY KEY (id),
    FOREIGN KEY(vin) REFERENCES vehicles (vin) ON DELETE CASCADE
);
""",
    "table_level_last": f"""
CREATE TABLE "tax_records" (
    id INTEGER NOT NULL,
    vin VARCHAR(17) NOT NULL,
    date DATE NOT NULL,
    tax_type VARCHAR(30),
    amount NUMERIC(12, 2) NOT NULL,
    notes TEXT,
    PRIMARY KEY (id),
    FOREIGN KEY(vin) REFERENCES vehicles (vin) ON DELETE CASCADE,
    CHECK (tax_type IN {_VALUES})
);
""",
    "named_constraint": f"""
CREATE TABLE "tax_records" (
    id INTEGER NOT NULL,
    vin VARCHAR(17) NOT NULL,
    date DATE NOT NULL,
    tax_type VARCHAR(30),
    amount NUMERIC(12, 2) NOT NULL,
    notes TEXT,
    CONSTRAINT check_tax_type CHECK (tax_type IN {_VALUES}),
    PRIMARY KEY (id),
    FOREIGN KEY(vin) REFERENCES vehicles (vin) ON DELETE CASCADE
);
""",
}

shapes = pytest.mark.parametrize("shape", sorted(_SHAPES))


def _connect(db_file: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _setup(db_file: Path, shape: str) -> None:
    conn = _connect(db_file)
    conn.executescript(
        "CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, nickname VARCHAR(100));\n"
        + _SHAPES[shape]
        + """
        CREATE INDEX idx_tax_records_vin ON tax_records(vin);
        INSERT INTO vehicles (vin, nickname) VALUES ('CARVIN00000000001', 'Daily');
        INSERT INTO tax_records (id, vin, date, tax_type, amount, notes)
            VALUES (1, 'CARVIN00000000001', '2026-01-15', 'Property Tax', 150.00, 'kept');
        """
    )
    conn.commit()
    conn.close()


@shapes
def test_drops_the_check_and_keeps_rows_index_and_fk(tmp_path: Path, shape: str):
    db_file = tmp_path / "cc.db"
    _setup(db_file, shape)
    conn = _connect(db_file)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tax_records (id, vin, date, tax_type, amount) "
            "VALUES (2, 'CARVIN00000000001', '2026-02-01', 'co2_malus', 1.0)"
        )
    conn.rollback()
    conn.close()

    engine = create_engine(f"sqlite:///{db_file}")
    assert drop_check_constraint(engine, "tax_records", "tax_type") is True

    conn = _connect(db_file)
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tax_records'"
    ).fetchone()[0]
    assert "CHECK" not in ddl.upper()
    conn.execute(
        "INSERT INTO tax_records (id, vin, date, tax_type, amount) "
        "VALUES (2, 'CARVIN00000000001', '2026-02-01', 'co2_malus', 1.0)"
    )
    conn.commit()
    assert conn.execute(
        "SELECT vin, tax_type, amount, notes FROM tax_records WHERE id = 1"
    ).fetchone() == ("CARVIN00000000001", "Property Tax", 150, "kept")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tax_records (id, vin, date, amount) "
            "VALUES (3, 'NOSUCHVIN00000001', '2026-02-01', 1.0)"
        )
    conn.rollback()
    assert (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_tax_records_vin'"
        ).fetchone()
        is not None
    )
    # The parent's cascade still reaches the child after the rebuild.
    conn.execute("DELETE FROM vehicles WHERE vin = 'CARVIN00000000001'")
    assert conn.execute("SELECT COUNT(*) FROM tax_records").fetchone()[0] == 0
    conn.close()


@shapes
def test_second_call_finds_nothing(tmp_path: Path, shape: str):
    db_file = tmp_path / "cc2.db"
    _setup(db_file, shape)
    engine = create_engine(f"sqlite:///{db_file}")
    assert drop_check_constraint(engine, "tax_records", "tax_type") is True
    assert drop_check_constraint(engine, "tax_records", "tax_type") is False
    conn = _connect(db_file)
    assert conn.execute("SELECT COUNT(*) FROM tax_records").fetchone()[0] == 1
    conn.close()


def test_missing_table_and_other_column_are_no_ops(tmp_path: Path):
    db_file = tmp_path / "cc3.db"
    _setup(db_file, "named_constraint")
    engine = create_engine(f"sqlite:///{db_file}")
    assert drop_check_constraint(engine, "no_such_table", "tax_type") is False
    # A CHECK on another column is not this call's to drop.
    assert drop_check_constraint(engine, "tax_records", "amount") is False
    conn = _connect(db_file)
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tax_records'"
    ).fetchone()[0]
    assert "CHECK" in ddl.upper()
    conn.close()


def test_identifiers_are_checked():
    engine = create_engine("sqlite://")
    with pytest.raises(ValueError):
        drop_check_constraint(engine, "tax_records; DROP TABLE x", "tax_type")


@shapes
def test_strip_check_leaves_executable_ddl_with_every_column(shape: str):
    stripped = strip_check(_SHAPES[shape], "tax_type")
    assert "CHECK" not in stripped.upper()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)")
    conn.execute(stripped.strip().rstrip(";"))
    cols = [r[1] for r in conn.execute('PRAGMA table_info("tax_records")')]
    assert cols == ["id", "vin", "date", "tax_type", "amount", "notes"]
