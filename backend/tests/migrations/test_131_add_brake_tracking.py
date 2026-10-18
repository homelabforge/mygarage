"""Tests for migration 131 (brake_axles, brake_jobs, brake_measurements)."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

import app.migrations as _m

_VIN = "1FT0000000000000X"
_TABLES = ("brake_axles", "brake_jobs", "brake_measurements")


def _load(name):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_deps(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO vehicles (vin) VALUES (:vin)"), {"vin": _VIN})


def _upgrade(engine):
    _load("131_add_brake_tracking").upgrade(engine)


def test_131_is_not_fatal():
    # create_all builds these tables before the runner, so a failed 131 leaves
    # nothing missing and must not stop startup.
    assert _load("131_add_brake_tracking").FATAL is False


def test_131_creates_tables(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _upgrade(engine)

    insp = inspect(engine)
    for table in _TABLES:
        assert insp.has_table(table)

    assert {c["name"] for c in insp.get_columns("brake_axles")} >= {
        "id",
        "vin",
        "axle",
        "brake_type",
        "min_thickness_mm",
        "new_thickness_mm",
        "rotor_min_mm",
        "drum_max_mm",
        "created_at",
        "updated_at",
    }
    assert {c["name"] for c in insp.get_columns("brake_jobs")} >= {
        "id",
        "vin",
        "position",
        "brake_type",
        "performed_on",
        "odometer_km",
        "engine_hours",
        "friction_replaced",
        "surface",
        "notes",
        "created_at",
    }
    assert {c["name"] for c in insp.get_columns("brake_measurements")} >= {
        "id",
        "vin",
        "position",
        "recorded_at",
        "odometer_km",
        "engine_hours",
        "inner_pad_mm",
        "outer_pad_mm",
        "rotor_mm",
        "shoe_mm",
        "drum_mm",
        "brake_job_id",
        "notes",
        "created_at",
    }

    index_cols = {tuple(ix["column_names"]) for ix in insp.get_indexes("brake_measurements")}
    assert ("vin", "position") in index_cols
    assert ("brake_job_id",) in index_cols
    assert ("vin", "position") in {
        tuple(ix["column_names"]) for ix in insp.get_indexes("brake_jobs")
    }

    targets = {fk["referred_table"] for fk in insp.get_foreign_keys("brake_measurements")}
    assert targets == {"vehicles", "brake_jobs"}


def test_131_one_axle_row_per_vehicle_and_axle(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _upgrade(engine)

    insert = text(
        "INSERT INTO brake_axles (vin, axle, brake_type, min_thickness_mm, new_thickness_mm) "
        "VALUES (:vin, 'front', 'disc', 3.0, 10.0)"
    )
    with engine.begin() as conn:
        conn.execute(insert, {"vin": _VIN})
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert, {"vin": _VIN})


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO brake_axles (vin, axle, brake_type, min_thickness_mm, new_thickness_mm) "
        "VALUES (:vin, 'mid', 'disc', 3.0, 10.0)",
        "INSERT INTO brake_axles (vin, axle, brake_type, min_thickness_mm, new_thickness_mm) "
        "VALUES (:vin, 'front', 'band', 3.0, 10.0)",
        "INSERT INTO brake_jobs (vin, position, brake_type, performed_on, surface) "
        "VALUES (:vin, 'SP', 'disc', '2026-01-01', NULL)",
        "INSERT INTO brake_jobs (vin, position, brake_type, performed_on, surface) "
        "VALUES (:vin, 'FL', 'disc', '2026-01-01', 'polished')",
        "INSERT INTO brake_measurements (vin, position, recorded_at) "
        "VALUES (:vin, 'XX', '2026-01-01')",
    ],
    ids=["axle", "axle-type", "job-position", "job-surface", "measurement-position"],
)
def test_131_checks_refuse_values_outside_the_vocabulary(engine_for_migration, sql):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _upgrade(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(sql), {"vin": _VIN})


def test_131_friction_replaced_defaults_false(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _upgrade(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO brake_jobs (vin, position, brake_type, performed_on, surface) "
                "VALUES (:vin, 'FL', 'disc', '2026-01-01', 'resurfaced')"
            ),
            {"vin": _VIN},
        )
        stored = conn.execute(text("SELECT friction_replaced FROM brake_jobs")).scalar()
    assert not stored


def test_131_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    mod = _load("131_add_brake_tracking")
    mod.upgrade(engine)
    mod.upgrade(engine)
    insp = inspect(engine)
    assert all(insp.has_table(table) for table in _TABLES)


def test_131_missing_vehicles_table_skips(engine_for_migration):
    """Skips, without raising, when the vehicles table is absent."""
    _dialect, engine, _url = engine_for_migration
    _upgrade(engine)
    insp = inspect(engine)
    assert not any(insp.has_table(table) for table in _TABLES)


def _foreign_keys(engine, table: str) -> set[tuple]:
    """Each foreign key as (column, table, column, delete rule)."""
    if engine.dialect.name == "sqlite":
        # The inspector reads a delete rule from a table-level FOREIGN KEY
        # clause only, and 131 writes its keys inline, so ask SQLite itself.
        with engine.connect() as conn:
            rows = conn.execute(text(f"PRAGMA foreign_key_list({table})")).all()
        return {(row[3], row[2], row[4], row[6]) for row in rows}
    return {
        (
            *fk["constrained_columns"],
            fk["referred_table"],
            *fk["referred_columns"],
            (fk.get("options") or {}).get("ondelete"),
        )
        for fk in inspect(engine).get_foreign_keys(table)
    }


def _shape(engine, table: str) -> tuple:
    """What the ORM and the migration must agree on for one table.

    Each column's type, nullability and whether it has a server default (the
    default's text differs by builder: `now()` against `CURRENT_TIMESTAMP`),
    each foreign key with its delete rule, and the CHECK names. The primary key
    column's nullability is left out: SQLite reports `INTEGER PRIMARY KEY
    AUTOINCREMENT` as nullable and create_all's `id INTEGER NOT NULL` as not.
    """
    insp = inspect(engine)
    pk = set(insp.get_pk_constraint(table)["constrained_columns"])
    return (
        {
            c["name"]: (
                str(c["type"]),
                None if c["name"] in pk else c["nullable"],
                c["default"] is not None,
            )
            for c in insp.get_columns(table)
        },
        _foreign_keys(engine, table),
        {ck["name"] for ck in insp.get_check_constraints(table)},
    )


def test_131_model_create_all_matches_migration_shape(engine_for_migration):
    """The ORM tables match the migration DDL: columns, foreign keys and CHECKs."""
    from app.models.brake import BrakeAxle, BrakeJob, BrakeMeasurement

    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    models = (BrakeAxle, BrakeJob, BrakeMeasurement)
    BrakeAxle.metadata.create_all(engine, tables=[m.__table__ for m in models])

    by_orm = {table: _shape(engine, table) for table in _TABLES}

    with engine.begin() as conn:
        for table in reversed(_TABLES):
            conn.execute(text(f"DROP TABLE {table}"))

    _upgrade(engine)
    for table in _TABLES:
        assert _shape(engine, table) == by_orm[table], table
