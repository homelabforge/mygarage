"""Migration 154: the brake position CHECK takes F and R as well (#272).

Runs on SQLite and PostgreSQL via `engine_for_migration`, against both shapes
the brake tables exist in out there: the one 131 wrote by hand and the one an
older create_all wrote (table-level CHECKs). The SQLite side is a table
rebuild, so most of this is about what has to survive it.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import Engine, Table, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable

import app.migrations as _m

_NAME = "154_widen_brake_position_check"
_VIN = "1HGCM82633A004352"
_TABLES = ("brake_jobs", "brake_measurements", "brake_reminder_marks")
_OLD_LIST = "('FL', 'FR', 'RL', 'RR')"
_NEW_LIST = "('FL', 'FR', 'RL', 'RR', 'F', 'R')"

# One insert per table, with the corner left as a parameter.
_INSERTS = {
    "brake_jobs": (
        "INSERT INTO brake_jobs (vin, position, brake_type, performed_on) "
        "VALUES (:vin, :pos, 'disc', '2026-01-01')"
    ),
    "brake_measurements": (
        "INSERT INTO brake_measurements (vin, position, recorded_at) "
        "VALUES (:vin, :pos, '2026-01-01')"
    ),
    "brake_reminder_marks": (
        "INSERT INTO brake_reminder_marks (vin, position, seen_through_id) VALUES (:vin, :pos, 1)"
    ),
}


def _load(name: str = _NAME):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_131(engine: Engine) -> None:
    _load("131_add_brake_tracking").upgrade(engine)


def _build_old_create_all(engine: Engine) -> None:
    """The brake tables as create_all wrote them before 154: the model's DDL, old list."""
    from app.models.brake import BrakeAxle, BrakeJob, BrakeMeasurement, BrakeReminderMark

    with engine.begin() as conn:
        for model in (BrakeAxle, BrakeJob, BrakeMeasurement, BrakeReminderMark):
            table = model.__table__
            assert isinstance(table, Table)
            ddl = str(CreateTable(table).compile(dialect=engine.dialect))
            if model is not BrakeAxle:
                assert _NEW_LIST in ddl, model.__tablename__
                ddl = ddl.replace(_NEW_LIST, _OLD_LIST)
            conn.exec_driver_sql(ddl)
            for index in table.indexes:
                conn.execute(CreateIndex(index))


_BUILDERS = {"migration_131": _build_131, "old_create_all": _build_old_create_all}


@pytest.fixture(params=sorted(_BUILDERS))
def brake_db(request, engine_for_migration) -> tuple[str, Engine]:
    """Vehicles plus the brake tables with the old four-corner CHECK, in each shape."""
    dialect, engine, _url = engine_for_migration
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO vehicles (vin) VALUES (:vin)"), {"vin": _VIN})
    _BUILDERS[request.param](engine)
    return dialect, engine


def _insert(engine: Engine, table: str, pos: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(_INSERTS[table]), {"vin": _VIN, "pos": pos})


def _dump(engine: Engine, table: str) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(f"SELECT * FROM {table} ORDER BY id"))]


def _fingerprint(engine: Engine) -> dict:
    """Something that changes whenever a table or its CHECK is rebuilt.

    SQLite: the DDL and the table's root page (a rebuild builds the new table
    before dropping the old one, so it lands on another page). PostgreSQL: the
    oid of each position CHECK.
    """
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            rows = conn.execute(
                text("SELECT name, sql, rootpage FROM sqlite_master WHERE type = 'table'")
            )
        else:
            rows = conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid), oid FROM pg_constraint "
                    "WHERE contype = 'c' AND pg_get_constraintdef(oid) LIKE '%position%'"
                )
            )
        return {r[0]: (r[1], r[2]) for r in rows}


def test_154_is_fatal():
    # Pydantic takes F and R now, so a failed widen would 500 every two-wheel write.
    assert _load().FATAL is True


@pytest.mark.parametrize("table", _TABLES)
def test_widened_check_accepts_f_and_r(brake_db, table):
    _dialect, engine = brake_db
    # Before: the old CHECK turns F away, or this test proves nothing.
    with pytest.raises(IntegrityError):
        _insert(engine, table, "F")

    _load().upgrade(engine)

    _insert(engine, table, "F")
    _insert(engine, table, "R")
    _insert(engine, table, "FL")
    with pytest.raises(IntegrityError):
        _insert(engine, table, "X")


def test_rows_and_indexes_survive(brake_db):
    _dialect, engine = brake_db
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO brake_jobs (vin, position, brake_type, performed_on, odometer_km, "
                "engine_hours, friction_replaced, surface, notes) VALUES "
                "(:vin, 'FL', 'disc', '2026-01-01', 12345.67, 12.5, TRUE, 'replaced', 'pads'), "
                "(:vin, 'RR', 'drum', '2026-02-01', NULL, NULL, FALSE, NULL, NULL)"
            ),
            {"vin": _VIN},
        )
        conn.execute(
            text(
                "INSERT INTO brake_measurements (vin, position, recorded_at, odometer_km, "
                "inner_pad_mm, outer_pad_mm, rotor_mm, shoe_mm, drum_mm, brake_job_id, notes) "
                "VALUES (:vin, 'FL', '2026-01-01', 12345.67, 9.5, 9.25, 27.1, NULL, NULL, 1, 'new'), "
                "(:vin, 'RR', '2026-02-01', NULL, NULL, NULL, NULL, 4.5, 228.6, NULL, NULL)"
            ),
            {"vin": _VIN},
        )
        conn.execute(
            text(
                "INSERT INTO brake_reminder_marks (vin, position, seen_through_id, "
                "covered_replace_now) VALUES (:vin, 'FL', 2, TRUE), (:vin, 'RL', 1, FALSE)"
            ),
            {"vin": _VIN},
        )
    before = {table: _dump(engine, table) for table in _TABLES}
    assert all(len(rows) == 2 for rows in before.values())

    _load().upgrade(engine)

    assert {table: _dump(engine, table) for table in _TABLES} == before
    insp = inspect(engine)
    assert {ix["name"] for ix in insp.get_indexes("brake_jobs")} >= {"idx_brake_jobs_vin_position"}
    assert {ix["name"] for ix in insp.get_indexes("brake_measurements")} >= {
        "idx_brake_measurements_vin_position",
        "idx_brake_measurements_brake_job",
    }
    assert "uq_brake_reminder_marks_vin_position" in {
        uc["name"] for uc in insp.get_unique_constraints("brake_reminder_marks")
    }
    # The mark's UNIQUE still bites.
    with pytest.raises(IntegrityError):
        _insert(engine, "brake_reminder_marks", "FL")
    # And the CHECKs keep their names.
    for table in _TABLES:
        names = {ck["name"] for ck in insp.get_check_constraints(table)}
        assert f"check_{table}_position" in names, table


@pytest.mark.parametrize("keep", [2, 0], ids=["newest-deleted", "all-deleted"])
def test_measurement_ids_never_reused(brake_db, keep):
    # A reminder mark tells new from old by id, so a reused id hides a new check.
    _dialect, engine = brake_db
    for _ in range(3):
        _insert(engine, "brake_measurements", "FL")
    assert [r[0] for r in _dump(engine, "brake_measurements")] == [1, 2, 3]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM brake_measurements WHERE id > :keep"), {"keep": keep})

    _load().upgrade(engine)

    _insert(engine, "brake_measurements", "F")
    assert _dump(engine, "brake_measurements")[-1][0] == 4


@pytest.mark.parametrize("keep", [2, 0], ids=["newest-deleted", "all-deleted"])
def test_sqlite_sequence_keeps_one_row_per_table(brake_db, keep):
    dialect, engine = brake_db
    if dialect != "sqlite":
        pytest.skip("sqlite_sequence is SQLite's")
    for _ in range(3):
        _insert(engine, "brake_measurements", "FL")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM brake_measurements WHERE id > :keep"), {"keep": keep})

    _load().upgrade(engine)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name, seq FROM sqlite_sequence WHERE name LIKE 'brake_measurements%'")
        ).all()
    assert [tuple(r) for r in rows] == [("brake_measurements", 3)]


def test_job_delete_still_cascades(brake_db):
    dialect, engine = brake_db
    if dialect == "sqlite":
        # FKs on at connect, like the app's engine. That's what makes dropping
        # brake_jobs mid-rebuild dangerous: it would cascade into its measurements.
        engine.dispose()
        event.listen(engine, "connect", lambda dbapi, _rec: dbapi.execute("PRAGMA foreign_keys=ON"))
    _insert(engine, "brake_jobs", "FL")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO brake_measurements (vin, position, recorded_at, brake_job_id) "
                "VALUES (:vin, 'FL', '2026-01-01', 1)"
            ),
            {"vin": _VIN},
        )

    _load().upgrade(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM brake_measurements")).scalar() == 1
        if dialect == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        conn.execute(text("DELETE FROM brake_jobs WHERE id = 1"))
        left = conn.execute(text("SELECT COUNT(*) FROM brake_measurements")).scalar()
        conn.commit()
    assert left == 0


def test_rerun_is_noop(brake_db):
    _dialect, engine = brake_db
    mod = _load()
    before = _fingerprint(engine)
    mod.upgrade(engine)
    once = _fingerprint(engine)
    assert once != before  # the first run did rebuild something
    mod.upgrade(engine)
    assert _fingerprint(engine) == once


def test_pg_finds_a_check_with_another_name(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    if dialect != "pg":
        pytest.skip("constraint names are a PostgreSQL lookup")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO vehicles (vin) VALUES (:vin)"), {"vin": _VIN})
    _build_131(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE brake_jobs RENAME CONSTRAINT check_brake_jobs_position "
                "TO brake_jobs_position_check"
            )
        )

    _load().upgrade(engine)

    _insert(engine, "brake_jobs", "F")
    with engine.connect() as conn:
        names = set(
            conn.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = 'brake_jobs'::regclass "
                    "AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%position%'"
                )
            ).scalars()
        )
    assert names == {"check_brake_jobs_position"}


def test_sqlite_refuses_a_check_it_cannot_read(tmp_path):
    # FATAL: an IN-list it can't find must stop the boot, not skip quietly.
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'm154.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE brake_jobs (id INTEGER PRIMARY KEY, position VARCHAR(2) NOT NULL "
            "CHECK (position = 'FL' OR position = 'FR' OR position = 'RL' OR position = 'RR'))"
        )
    with pytest.raises(RuntimeError, match="brake_jobs"):
        _load().upgrade(engine)
    engine.dispose()


def test_sqlite_an_orphan_from_before_does_not_stop_it(brake_db):
    # Only orphans the rebuild made fail the boot. One that was already there
    # (FKs off at some point) has to ride through, row and all.
    dialect, engine = brake_db
    if dialect != "sqlite":
        pytest.skip("PostgreSQL never lets the orphan in")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.execute(
            text(
                "INSERT INTO brake_measurements (vin, position, recorded_at) "
                "VALUES ('NOSUCHVIN00000000', 'FL', '2026-01-01')"
            )
        )
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_key_check(brake_measurements)").all()

    _load().upgrade(engine)

    assert [r[1] for r in _dump(engine, "brake_measurements")] == ["NOSUCHVIN00000000"]
    _insert(engine, "brake_measurements", "F")


def test_sqlite_widens_every_position_check(tmp_path):
    # Two position CHECKs on one table: leaving either narrow still refuses F.
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'm154.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE brake_jobs (id INTEGER PRIMARY KEY, position VARCHAR(2) NOT NULL "
                f"CHECK (position IN {_OLD_LIST}), CONSTRAINT check_brake_jobs_position "
                f"CHECK (position IN {_OLD_LIST}))"
            )

        _load().upgrade(engine)

        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO brake_jobs (position) VALUES ('F')")
            ddl = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name = 'brake_jobs'"
            ).scalar()
        assert ddl is not None and ddl.count(_NEW_LIST) == 2
    finally:
        engine.dispose()


def test_pg_widens_every_position_check(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    if dialect != "pg":
        pytest.skip("constraint names are a PostgreSQL lookup")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO vehicles (vin) VALUES (:vin)"), {"vin": _VIN})
    _build_131(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE brake_jobs ADD CONSTRAINT brake_jobs_position_check "
                f"CHECK (position IN {_OLD_LIST})"
            )
        )
        # Mentions position but isn't a corner list, so it stays.
        conn.execute(
            text(
                "ALTER TABLE brake_jobs ADD CONSTRAINT brake_jobs_position_not_blank "
                "CHECK (position <> '')"
            )
        )

    _load().upgrade(engine)

    _insert(engine, "brake_jobs", "F")
    with engine.connect() as conn:
        names = set(
            conn.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = 'brake_jobs'::regclass "
                    "AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%position%'"
                )
            ).scalars()
        )
    assert names == {"check_brake_jobs_position", "brake_jobs_position_not_blank"}


def test_missing_tables_skip(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not any(inspect(engine).has_table(t) for t in _TABLES)
