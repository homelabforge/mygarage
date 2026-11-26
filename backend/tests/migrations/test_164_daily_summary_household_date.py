"""Migration 164: telemetry_daily_summary.date becomes a DATE.

The summary job keys a day by its household date now. On SQLite a new
``2026-03-09`` key and an old ``2026-03-09 00:00:00`` one both get past the
unique constraint, so the old rows are rebuilt as plain dates there; PostgreSQL
casts the column. Old rows keep their date part and stay UTC-day aggregates.
"""

import logging
from datetime import date

import pytest
from sqlalchemy import Connection, Date, DateTime, Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models.vehicle_telemetry import TelemetryDailySummary
from tests.migrations._loader import load_migration

pytestmark = pytest.mark.migrations

_NAME = "164_daily_summary_household_date"
_BOTH = pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
_VIN = "1HGCM82633A004352"

#: (param_key, stamp, min, max, avg, count), all at UTC midnight on 2026-03-09.
#: The microseconds form is how SQLAlchemy writes a DATETIME on SQLite.
_SEED = [
    ("SPEED", "2026-03-09 00:00:00.000000", 0.0, 112.5, 48.25, 1200),
    ("COOLANT_TEMP", "2026-03-09 00:00:00", 71.0, 96.0, 88.5, 640),
]


def _insert_old(
    conn: Connection, key: str, stamp: str, low: float, high: float, avg: float, n: int
) -> None:
    conn.execute(
        text(
            "INSERT INTO telemetry_daily_summary"
            " (vin, param_key, date, min_value, max_value, avg_value, sample_count)"
            " VALUES (:v, :k, :at, :lo, :hi, :avg, :n)"
        ),
        {"v": _VIN, "k": key, "at": stamp, "lo": low, "hi": high, "avg": avg, "n": n},
    )


def _make_old_table(engine: Engine, seed: list[tuple] = _SEED) -> None:
    """The table as 032 made it: a timestamp column, unnamed unique and two indexes."""
    pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if pg else "DATETIME"
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO vehicles (vin) VALUES (:v)"), {"v": _VIN})
        conn.execute(
            text(
                f"CREATE TABLE telemetry_daily_summary (id {pk},"
                " vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,"
                f" param_key VARCHAR(100) NOT NULL, date {ts} NOT NULL,"
                " min_value FLOAT, max_value FLOAT, avg_value FLOAT,"
                " sample_count INTEGER NOT NULL DEFAULT 0, UNIQUE(vin, param_key, date))"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX idx_daily_summary_vehicle_date ON telemetry_daily_summary(vin, date)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX idx_daily_summary_param"
                " ON telemetry_daily_summary(vin, param_key, date)"
            )
        )
        for row in seed:
            _insert_old(conn, *row)


def _rows(engine: Engine) -> dict[str, tuple]:
    """Each row as the model reads it."""
    t = TelemetryDailySummary.__table__
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                t.c.param_key,
                t.c.date,
                t.c.min_value,
                t.c.max_value,
                t.c.avg_value,
                t.c.sample_count,
            ).order_by(t.c.param_key)
        ).all()
    return {r[0]: tuple(r[1:]) for r in rows}


def _raw_dates(engine: Engine) -> list[object]:
    with engine.connect() as conn:
        return list(conn.execute(text("SELECT date FROM telemetry_daily_summary")).scalars())


def _ddl(engine: Engine) -> str | None:
    if engine.dialect.name != "sqlite":
        return None
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'telemetry_daily_summary'")
        ).scalar()


_EXPECTED = {
    "COOLANT_TEMP": (date(2026, 3, 9), 71.0, 96.0, 88.5, 640),
    "SPEED": (date(2026, 3, 9), 0.0, 112.5, 48.25, 1200),
}


def test_the_migration_is_not_fatal() -> None:
    # The summary job refuses to write until 164 lands, so the rest of the app can run.
    assert not getattr(load_migration(_NAME), "FATAL", False)


@_BOTH
def test_old_rows_become_dates_with_their_numbers_intact(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    dialect, engine, _url = engine_for_migration
    _make_old_table(engine)

    load_migration(_NAME).upgrade(engine)

    assert _rows(engine) == _EXPECTED
    # The stored value itself, not just what the model's parser makes of it.
    expected_raw = "2026-03-09" if dialect == "sqlite" else date(2026, 3, 9)
    raw = _raw_dates(engine)
    assert raw == [expected_raw, expected_raw]
    assert all(type(v) is type(expected_raw) for v in raw)


@_BOTH
def test_the_column_is_date_and_keys_and_indexes_survive(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    dialect, engine, _url = engine_for_migration
    _make_old_table(engine)

    load_migration(_NAME).upgrade(engine)

    insp = inspect(engine)
    column = {c["name"]: c for c in insp.get_columns("telemetry_daily_summary")}["date"]
    assert isinstance(column["type"], Date)
    assert not isinstance(column["type"], DateTime)
    assert column["nullable"] is False
    uniques = [
        sorted(u["column_names"]) for u in insp.get_unique_constraints("telemetry_daily_summary")
    ]
    assert uniques == [["date", "param_key", "vin"]]
    if dialect == "sqlite":
        # The rebuild names it the way the model does; PG keeps its own name.
        names = [u["name"] for u in insp.get_unique_constraints("telemetry_daily_summary")]
        assert names == ["uq_daily_summary_vin_param_date"]
    indexes = {
        i["name"]: i["column_names"]
        for i in insp.get_indexes("telemetry_daily_summary")
        if (i["name"] or "").startswith("idx_")
    }
    assert indexes == {
        "idx_daily_summary_vehicle_date": ["vin", "date"],
        "idx_daily_summary_param": ["vin", "param_key", "date"],
    }
    fks = insp.get_foreign_keys("telemetry_daily_summary")
    assert [(f["constrained_columns"], f["referred_table"]) for f in fks] == [(["vin"], "vehicles")]
    assert fks[0].get("options", {}).get("ondelete") == "CASCADE"


@_BOTH
def test_a_date_key_now_collides_with_the_migrated_day(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    # Before 164, SQLite took this as a second row for the same day.
    _dialect, engine, _url = engine_for_migration
    _make_old_table(engine)

    load_migration(_NAME).upgrade(engine)

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO telemetry_daily_summary (vin, param_key, date, sample_count)"
                " VALUES (:v, 'SPEED', :d, 1)"
            ),
            {"v": _VIN, "d": "2026-03-09"},
        )


@_BOTH
def test_rows_that_share_a_date_are_merged_into_one(
    engine_for_migration: tuple[str, Engine, str], caplog: pytest.LogCaptureFixture
) -> None:
    # SQLite can hold one midnight twice, PG two stamps on the same day.
    dialect, engine, _url = engine_for_migration
    second = "2026-03-09 00:00:00.000000" if dialect == "sqlite" else "2026-03-09 05:00:00"
    _make_old_table(
        engine,
        [
            ("SPEED", "2026-03-09 00:00:00", 10.0, 20.0, 15.0, 2),
            ("SPEED", second, 5.0, 30.0, 25.0, 8),
            ("COOLANT_TEMP", "2026-03-09 00:00:00", 71.0, 96.0, 88.5, 640),
        ],
    )

    with caplog.at_level(logging.INFO):
        load_migration(_NAME).upgrade(engine)

    with engine.connect() as conn:
        ids = (
            conn.execute(text("SELECT id FROM telemetry_daily_summary WHERE param_key = 'SPEED'"))
            .scalars()
            .all()
        )
    # The lower id is the one kept.
    assert ids == [1]
    assert _rows(engine) == {
        "COOLANT_TEMP": (date(2026, 3, 9), 71.0, 96.0, 88.5, 640),
        "SPEED": (date(2026, 3, 9), 5.0, 30.0, 23.0, 10),
    }
    assert any("Merged 1 " in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("engine_for_migration", ["sqlite"], indirect=True)
def test_a_failed_rebuild_puts_the_merged_rows_back(
    engine_for_migration: tuple[str, Engine, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # R1-M2: the merge used to commit on its own, so a rebuild that failed
    # after it left the old table short the rows it had folded away.
    _dialect, engine, _url = engine_for_migration
    seed = [
        ("SPEED", "2026-03-09 00:00:00", 10.0, 20.0, 15.0, 2),
        ("SPEED", "2026-03-09 00:00:00.000000", 5.0, 30.0, 25.0, 8),
        ("COOLANT_TEMP", "2026-03-09 00:00:00", 71.0, 96.0, 88.5, 640),
    ]
    _make_old_table(engine, seed)
    mod = load_migration(_NAME)
    monkeypatch.setattr(mod, "_INDEXES", (*mod._INDEXES, "CREATE INDEX boom ON no_such_table (x)"))

    with pytest.raises(OperationalError):
        mod.upgrade(engine)

    insp = inspect(engine)
    column = {c["name"]: c for c in insp.get_columns("telemetry_daily_summary")}["date"]
    assert isinstance(column["type"], DateTime)
    assert not insp.has_table("telemetry_daily_summary_new")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT param_key, date, min_value, max_value, avg_value, sample_count"
                " FROM telemetry_daily_summary ORDER BY id"
            )
        ).all()
    assert [tuple(r) for r in rows] == seed


@_BOTH
def test_a_second_run_changes_nothing(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_old_table(engine)
    mod = load_migration(_NAME)
    mod.upgrade(engine)
    ddl = _ddl(engine)

    mod.upgrade(engine)

    assert _rows(engine) == _EXPECTED
    assert _ddl(engine) == ddl


@_BOTH
def test_a_table_create_all_made_is_left_alone(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    # A fresh install gets DATE from create_all before the runner starts.
    _dialect, engine, _url = engine_for_migration
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO vehicles (vin) VALUES (:v)"), {"v": _VIN})
    table = TelemetryDailySummary.metadata.tables[TelemetryDailySummary.__tablename__]
    table.create(engine)
    with engine.begin() as conn:
        conn.execute(
            table.insert().values(
                vin=_VIN, param_key="SPEED", date=date(2026, 3, 9), sample_count=2
            )
        )
    ddl = _ddl(engine)

    load_migration(_NAME).upgrade(engine)

    assert _ddl(engine) == ddl
    assert _rows(engine) == {"SPEED": (date(2026, 3, 9), None, None, None, 2)}


@_BOTH
def test_no_table_is_a_no_op(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    load_migration(_NAME).upgrade(engine)
    assert not inspect(engine).has_table("telemetry_daily_summary")
