"""Migration 137: recalls.component to VARCHAR(200), and one active DTC per vin and code (K10, K11).

Builds the pre-137 tables by hand. The models carry the width and the index
now, so a create_all baseline would start in the post state and every check
would pass before the migration ran. SQLite ignores VARCHAR length, so only
the PG runs prove the widening; the index and the clean-up run on both.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

import app.migrations as _m
from app.database import Base
from app.models.recall import Recall
from app.models.vehicle_dtc import VehicleDTC

pytestmark = pytest.mark.migrations

_NAME = "137_recall_component_and_active_dtcs"
_INDEX = "uq_vehicle_dtcs_active_code"


def _load(name: str):
    """Load a migration module by file, as the runner does."""
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pk(engine) -> str:
    return (
        "SERIAL PRIMARY KEY"
        if engine.dialect.name == "postgresql"
        else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )


def _make_pre_137_tables(engine) -> None:
    """recalls with the old VARCHAR(100) component, vehicle_dtcs with no partial index."""
    ts = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS recalls"))
        conn.execute(text("DROP TABLE IF EXISTS vehicle_dtcs"))
        conn.execute(
            text(
                f"""
                CREATE TABLE recalls (
                    id {_pk(engine)},
                    vin VARCHAR(17) NOT NULL,
                    nhtsa_campaign_number VARCHAR(20),
                    component VARCHAR(100),
                    summary TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE vehicle_dtcs (
                    id {_pk(engine)},
                    vin VARCHAR(17) NOT NULL,
                    device_id VARCHAR(20) NOT NULL,
                    code VARCHAR(10) NOT NULL,
                    severity VARCHAR(20) NOT NULL,
                    user_notes TEXT,
                    first_seen {ts} NOT NULL,
                    last_seen {ts} NOT NULL,
                    cleared_at {ts},
                    is_active BOOLEAN NOT NULL
                )
                """
            )
        )


def _add_dtc(conn, vin: str, code: str, last_seen: datetime, *, active: bool = True, notes=None):
    conn.execute(
        text(
            "INSERT INTO vehicle_dtcs (vin, device_id, code, severity, user_notes, first_seen,"
            " last_seen, is_active) VALUES (:vin, 'dev1', :code, 'warning', :notes, :seen, :seen,"
            " :active)"
        ),
        {"vin": vin, "code": code, "notes": notes, "seen": last_seen, "active": active},
    )


def _dtcs(engine) -> list[tuple]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, vin, code, is_active, cleared_at IS NOT NULL, user_notes"
                " FROM vehicle_dtcs ORDER BY id"
            )
        ).all()
    return [(r[0], r[1], r[2], bool(r[3]), bool(r[4]), r[5]) for r in rows]


def _component_length(engine) -> int | None:
    columns = {c["name"]: c for c in inspect(engine).get_columns("recalls")}
    return getattr(columns["component"]["type"], "length", None)


def _index_names(engine) -> set[str]:
    return {i["name"] for i in inspect(engine).get_indexes("vehicle_dtcs")}


_V1 = "B3BMIG13700000001"
_V2 = "B3BMIG13700000002"
_CLOSED = "Cleared: a second active copy of this code, closed on upgrade (migration 137)"


def test_the_model_takes_what_the_api_and_the_sync_take():
    # main: 100, while RecallCreate and the NHTSA sync allow 200
    assert Recall.__table__.c.component.type.length == 200


def test_the_model_allows_one_active_row_per_code():
    """create_all builds the partial index, so the test database has it too."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[VehicleDTC.__table__])
    seen = datetime(2026, 6, 1, 8, 0, 0)
    with engine.begin() as conn:
        _add_dtc(conn, _V1, "P0300", seen)
        # A cleared copy is history, and there can be any number of those.
        _add_dtc(conn, _V1, "P0300", seen, active=False)
        _add_dtc(conn, _V1, "P0300", seen, active=False)
        _add_dtc(conn, _V2, "P0300", seen)
    # main: no index, so the second active row goes in
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _add_dtc(conn, _V1, "P0300", seen)


def test_the_migration_is_not_fatal():
    # A guard that passes once the file exists. It kills a 137 that copies
    # 110's FATAL = True, which would keep the app down over a cleanup it can live without.
    # If the migration fails at boot, the column stays at 100 and the duplicates stay, which is today.
    assert not getattr(_load(_NAME), "FATAL", False)


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_the_column_is_widened_and_a_long_component_stores(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    _make_pre_137_tables(engine)
    if dialect == "pg":
        assert _component_length(engine) == 100, "fixture must start in the pre state"

    _load(_NAME).upgrade(engine)

    if dialect == "pg":
        assert _component_length(engine) == 200
    component = "C" * 150
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO recalls (vin, component) VALUES (:vin, :c)"),
            {"vin": _V1, "c": component},
        )
        stored = conn.execute(text("SELECT component FROM recalls")).scalar_one()
    assert stored == component


def _cleared_at(engine) -> list[datetime]:
    """Every cleared_at the migration wrote, as naive datetimes (SQLite hands back text)."""
    with engine.connect() as conn:
        values = conn.execute(
            text("SELECT cleared_at FROM vehicle_dtcs WHERE cleared_at IS NOT NULL ORDER BY id")
        ).scalars()
        return [v if isinstance(v, datetime) else datetime.fromisoformat(v) for v in values]


# Off UTC, so a cleared_at written in local time can't pass for UTC.
@pytest.mark.usefixtures("local_clock_off_utc")
@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_duplicate_active_dtcs_are_closed_newest_kept_then_indexed(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_pre_137_tables(engine)
    with engine.begin() as conn:
        _add_dtc(conn, _V1, "P0300", datetime(2026, 1, 1), notes="first one")  # 1
        _add_dtc(conn, _V1, "P0300", datetime(2026, 3, 1))  # 2: newest, kept
        _add_dtc(conn, _V1, "P0300", datetime(2026, 2, 1), notes="")  # 3: blank, like no note
        _add_dtc(conn, _V1, "P0171", datetime(2026, 4, 1))  # 4
        _add_dtc(conn, _V1, "P0171", datetime(2026, 4, 1))  # 5: same last_seen, higher id kept
        _add_dtc(conn, _V2, "P0300", datetime(2026, 1, 1))  # 6: another vehicle, kept
        _add_dtc(conn, _V1, "P0300", datetime(2025, 1, 1), active=False)  # 7: history, untouched

    before = datetime.now(UTC).replace(tzinfo=None)
    _load(_NAME).upgrade(engine)
    after = datetime.now(UTC).replace(tzinfo=None)

    # main: FileNotFoundError, no migration 137
    assert _dtcs(engine) == [
        (1, _V1, "P0300", False, True, f"first one\n\n{_CLOSED}"),
        (2, _V1, "P0300", True, False, None),
        (3, _V1, "P0300", False, True, _CLOSED),
        (4, _V1, "P0171", False, True, _CLOSED),
        (5, _V1, "P0171", True, False, None),
        (6, _V2, "P0300", True, False, None),
        (7, _V1, "P0300", False, False, None),
    ]
    # Naive UTC, as clear_dtc stamps it.
    cleared = _cleared_at(engine)
    assert len(cleared) == 3
    assert all(before <= c <= after for c in cleared), (before, cleared, after)
    assert _INDEX in _index_names(engine)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _add_dtc(conn, _V1, "P0300", datetime(2026, 5, 1))
    with engine.begin() as conn:
        _add_dtc(conn, _V1, "P0300", datetime(2026, 5, 1), active=False)


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_second_run_changes_nothing(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    _make_pre_137_tables(engine)
    with engine.begin() as conn:
        _add_dtc(conn, _V1, "P0300", datetime(2026, 1, 1))
    mod = _load(_NAME)
    mod.upgrade(engine)
    before = _dtcs(engine)
    mod.upgrade(engine)
    assert _dtcs(engine) == before
    assert _INDEX in _index_names(engine)
    if dialect == "pg":
        assert _component_length(engine) == 200


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_missing_tables_are_skipped(engine_for_migration):
    # A guard that passes once the file exists. It kills a 137 that reflects
    # columns or indexes without checking the table first, which raises on an install that lacks one.
    _dialect, engine, _url = engine_for_migration
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS recalls"))
        conn.execute(text("DROP TABLE IF EXISTS vehicle_dtcs"))
    _load(_NAME).upgrade(engine)
    assert not inspect(engine).has_table("recalls")
    assert not inspect(engine).has_table("vehicle_dtcs")
