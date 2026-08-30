"""Tests for migration 094: nullable tire_readings.tread_depth_mm (#152).

FATAL migration: the ORM declares the column nullable and the API accepts a
pressure-only reading, so a schema that still says NOT NULL fails every such
INSERT after validation has already passed.

Parameterized over SQLite *and* PostgreSQL via the ``engine_for_migration``
fixture (PG runs skip when ``TEST_DATABASE_URL`` is unset). SQLite takes the
table-rebuild path and PostgreSQL takes ``ALTER COLUMN ... DROP NOT NULL``;
they are different enough code that testing one proves nothing about the other.

Every test builds the PRE-094 shape from 085 rather than from
``Base.metadata.create_all``: the model now declares the column nullable, so a
create_all baseline would already be in the post-state and every assertion here
would be true before the migration ran.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

import app.migrations as _m


def _load(name):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_pre_094_schema(engine) -> None:
    """Build vehicles + tires + tire_readings exactly as 085 left them.

    085 is replayed rather than reimplemented, so the starting point cannot
    drift away from what a real database actually holds.

    :param engine: The engine to build the schema in.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE vehicles (
                    vin VARCHAR(17) PRIMARY KEY,
                    nickname VARCHAR(80)
                )
                """
            )
        )
    _load("085_add_tire_tracking").upgrade(engine)


def _tread_column(engine) -> dict:
    """Reflect tire_readings.tread_depth_mm.

    :param engine: The engine to inspect.
    :returns: The reflected column dict.
    """
    return next(
        c for c in inspect(engine).get_columns("tire_readings") if c["name"] == "tread_depth_mm"
    )


def _seed_row(engine, reading_id: int, tread: str | None) -> None:
    """Insert one vehicle/tire/reading triple.

    :param engine: The engine to write to.
    :param reading_id: Explicit reading id, so the copy can be checked by id.
    :param tread: Tread value, or None for a pressure-only reading.
    """
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO vehicles (vin) VALUES (:vin)"),
            {"vin": "VIN00000000000094"},
        )
        conn.execute(
            text(
                "INSERT INTO tires (id, vin, position, brand) "
                "VALUES (1, 'VIN00000000000094', 'FL', 'Michelin')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO tire_readings (
                    id, tire_id, vin, position, recorded_at,
                    odometer_km, tread_depth_mm, pressure_kpa, notes
                ) VALUES (
                    :id, 1, 'VIN00000000000094', 'FL', '2026-01-01',
                    12345.60, :tread, 231.00, 'seeded'
                )
                """
            ),
            {"id": reading_id, "tread": tread},
        )


def test_094_starting_state_is_not_null(engine_for_migration):
    """Guard the guard: 085 really does leave the column NOT NULL.

    Without this, every assertion below could be satisfied by a starting point
    that was already nullable and the migration would be untested.
    """
    _dialect, engine, _url = engine_for_migration
    _make_pre_094_schema(engine)

    assert _tread_column(engine)["nullable"] is False


def test_094_makes_tread_depth_nullable(engine_for_migration):
    """After 094 the column accepts NULL: reflected AND actually inserted."""
    dialect, engine, _url = engine_for_migration
    _make_pre_094_schema(engine)
    assert _tread_column(engine)["nullable"] is False

    # Before: the database itself refuses a pressure-only reading.
    _seed_row(engine, reading_id=1, tread="7.50")
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tire_readings (tire_id, vin, position, recorded_at, pressure_kpa) "
                    "VALUES (1, 'VIN00000000000094', 'FL', '2026-02-01', 205.00)"
                )
            )

    _load("094_nullable_reading_tread").upgrade(engine)

    assert _tread_column(engine)["nullable"] is True
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tire_readings (tire_id, vin, position, recorded_at, pressure_kpa) "
                "VALUES (1, 'VIN00000000000094', 'FL', '2026-02-01', 205.00)"
            )
        )
        stored = conn.execute(
            text(
                "SELECT tread_depth_mm, pressure_kpa FROM tire_readings "
                "WHERE recorded_at = '2026-02-01'"
            )
        ).fetchone()
    assert stored[0] is None
    assert float(stored[1]) == pytest.approx(205.0)

    if dialect == "sqlite":
        # The rebuild must not leave its scratch table behind.
        assert not inspect(engine).has_table("tire_readings_new")


def test_094_preserves_existing_rows(engine_for_migration):
    """The rebuild copies every column of every row, not just the ids."""
    _dialect, engine, _url = engine_for_migration
    _make_pre_094_schema(engine)
    _seed_row(engine, reading_id=7, tread="7.50")

    _load("094_nullable_reading_tread").upgrade(engine)

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, tire_id, vin, position, recorded_at, "
                "odometer_km, tread_depth_mm, pressure_kpa, notes "
                "FROM tire_readings"
            )
        ).fetchall()
    assert len(row) == 1
    (rid, tire_id, vin, position, _recorded, odo, tread, pressure, notes) = row[0]
    assert rid == 7
    assert tire_id == 1
    assert vin == "VIN00000000000094"
    assert position == "FL"
    assert float(odo) == pytest.approx(12345.6)
    assert float(tread) == pytest.approx(7.5)
    assert float(pressure) == pytest.approx(231.0)
    assert notes == "seeded"


def test_094_preserves_indexes_and_cascade_foreign_keys(engine_for_migration):
    """Both indexes and both ON DELETE CASCADE foreign keys survive the rebuild.

    Asserted TWICE, because neither check subsumes the other and this test
    failed on its first run for a reason that was neither:

    * REFLECTED, which is what ``test_schema_parity.py`` compares. SQLAlchemy's
      SQLite reflection parses ``ON DELETE`` only out of a table-level
      ``FOREIGN KEY (...)`` clause, so 085's INLINE ``REFERENCES tires(id) ON
      DELETE CASCADE`` reflects as ``options: {}`` while
      ``PRAGMA foreign_key_list`` reports ``CASCADE``. The rebuild deliberately
      emits the table-level form, which is also what ``create_all`` emits.
    * EXERCISED, because a reflected ``ondelete`` says nothing about whether
      the pragma that enforces it is on, and losing the cascade would orphan
      every reading behind a deleted tire.
    """
    dialect, engine, _url = engine_for_migration
    _make_pre_094_schema(engine)
    _seed_row(engine, reading_id=1, tread="7.50")

    _load("094_nullable_reading_tread").upgrade(engine)

    with engine.connect() as conn:
        if dialect == "sqlite":
            rows = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index'")
            ).fetchall()
        else:
            rows = conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'tire_readings'")
            ).fetchall()
    index_names = {r[0] for r in rows if r[0]}
    assert "idx_tire_readings_tire" in index_names
    assert "idx_tire_readings_vin" in index_names

    fks = {
        (
            tuple(fk["constrained_columns"]),
            fk["referred_table"],
            (fk.get("options") or {}).get("ondelete"),
        )
        for fk in inspect(engine).get_foreign_keys("tire_readings")
    }
    assert (("tire_id",), "tires", "CASCADE") in fks
    assert (("vin",), "vehicles", "CASCADE") in fks

    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text("PRAGMA foreign_keys = ON"))
        conn.execute(text("DELETE FROM tires WHERE id = 1"))
        remaining = conn.execute(text("SELECT COUNT(*) FROM tire_readings")).scalar()
    assert remaining == 0


def test_094_is_idempotent(engine_for_migration):
    """A second run is a no-op and keeps the data the first run copied.

    The runner stamps ``schema_migrations`` in a transaction separate from
    ``upgrade``, so a crash in that window re-runs an already-applied
    migration on the next boot. A rebuild that ran twice on live data is
    exactly the failure this has to rule out.
    """
    _dialect, engine, _url = engine_for_migration
    _make_pre_094_schema(engine)
    _seed_row(engine, reading_id=3, tread="5.25")

    mod = _load("094_nullable_reading_tread")
    mod.upgrade(engine)
    mod.upgrade(engine)

    assert _tread_column(engine)["nullable"] is True
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, tread_depth_mm FROM tire_readings")).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 3
    assert float(rows[0][1]) == pytest.approx(5.25)


def test_094_skips_cleanly_when_tire_readings_absent(engine_for_migration):
    """Early return when 085 has not run yet."""
    _dialect, engine, _url = engine_for_migration

    _load("094_nullable_reading_tread").upgrade(engine)

    assert not inspect(engine).has_table("tire_readings")
