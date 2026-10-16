"""Migration 129: the readings an unanchored reminder counts from, on both dialects.

The tables carry only the columns 129 reads, so each test decides exactly which
readings were on file when the reminder was made.
"""

import importlib.util
import logging
from pathlib import Path

import pytest
from sqlalchemy import Numeric, inspect, text

import app.migrations as _m

_NAME = "129_add_reminder_start_readings"
_VIN = "1FT0000000000129X"


def _load():
    path = Path(_m.__file__).parent / f"{_NAME}.py"
    spec = importlib.util.spec_from_file_location(_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_tables(engine, *, zone: str = "UTC", readings: bool = True) -> None:
    """The columns 129 reads, plus a timezone row so the creation day is deterministic."""
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if is_pg else "DATETIME"
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE settings (key VARCHAR(50) PRIMARY KEY, value TEXT)"))
        conn.execute(text("INSERT INTO settings (key, value) VALUES ('timezone', :z)"), {"z": zone})
        conn.execute(
            text(
                f"CREATE TABLE vehicle_reminders (id {pk}, vin VARCHAR(17), status VARCHAR(10), "
                f"anchor_kind VARCHAR(12), anchor_date DATE, due_date DATE, "
                f"due_mileage_km NUMERIC(10,2), due_hours NUMERIC(10,1), created_at {ts})"
            )
        )
        if readings:
            conn.execute(
                text(
                    f"CREATE TABLE odometer_records (id {pk}, vin VARCHAR(17), date DATE, "
                    f"odometer_km NUMERIC(10,2), created_at {ts})"
                )
            )
            conn.execute(
                text(
                    f"CREATE TABLE hours_records (id {pk}, vin VARCHAR(17), date DATE, "
                    f"engine_hours NUMERIC(10,1), created_at {ts})"
                )
            )


def _reminder(conn, **row) -> None:
    """One reminder; anything not given is a pending, unanchored default."""
    values = {
        "vin": _VIN,
        "status": "pending",
        "anchor_kind": None,
        "anchor_date": None,
        "due_date": None,
        "due_mileage_km": None,
        "due_hours": None,
        "created_at": "2026-10-05 12:00:00",
        **row,
    }
    columns = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    conn.execute(text(f"INSERT INTO vehicle_reminders ({columns}) VALUES ({params})"), values)


def _odometer(conn, day, km, created_at) -> None:
    conn.execute(
        text(
            "INSERT INTO odometer_records (vin, date, odometer_km, created_at) "
            "VALUES (:vin, :day, :km, :created_at)"
        ),
        {"vin": _VIN, "day": day, "km": km, "created_at": created_at},
    )


def _hours(conn, day, hours, created_at) -> None:
    conn.execute(
        text(
            "INSERT INTO hours_records (vin, date, engine_hours, created_at) "
            "VALUES (:vin, :day, :hours, :created_at)"
        ),
        {"vin": _VIN, "day": day, "hours": hours, "created_at": created_at},
    )


def _starts(engine) -> list[tuple[float | None, float | None]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT start_odometer_km, start_hours FROM vehicle_reminders ORDER BY id")
        ).all()
    return [
        (None if km is None else float(km), None if hours is None else float(hours))
        for km, hours in rows
    ]


def test_129_is_fatal():
    assert _load().FATAL is True


def test_129_adds_two_nullable_columns_at_the_anchor_scales(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _load().upgrade(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("vehicle_reminders")}
    for name, scale in (("start_odometer_km", 2), ("start_hours", 1)):
        assert cols[name]["nullable"] is True
        assert isinstance(cols[name]["type"], Numeric)
        assert cols[name]["type"].scale == scale


def test_129_backfills_pending_unanchored_reminders_from_the_readings_on_file_then(
    engine_for_migration, caplog
):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    caplog.set_level(logging.INFO)
    with engine.begin() as conn:
        _odometer(conn, "2026-10-01", 1000, "2026-10-01 09:00:00")
        # Higher, but an earlier day: the latest day wins.
        _odometer(conn, "2026-10-04", 1300, "2026-10-04 09:00:00")
        _odometer(conn, "2026-10-05", 1200, "2026-10-05 11:00:00")
        # Same day and on file too, but lower (and a higher id): the higher one wins.
        _odometer(conn, "2026-10-05", 1150, "2026-10-05 10:00:00")
        # Entered after the reminders, though dated their day: never a start.
        _odometer(conn, "2026-10-05", 1500, "2026-10-05 13:00:00")
        # On file before them but dated after their day: never a start.
        _odometer(conn, "2026-10-06", 1600, "2026-10-05 11:30:00")
        _hours(conn, "2026-10-01", 120.0, "2026-10-01 09:00:00")
        # A later-dated lower correction: current hours is the highest reading.
        _hours(conn, "2026-10-03", 110.0, "2026-10-03 09:00:00")
        _hours(conn, "2026-10-05", 130.0, "2026-10-05 14:00:00")
        _reminder(conn, due_mileage_km=2000)  # 1
        _reminder(conn, due_date="2026-12-01")  # 2 date-only
        _reminder(conn, due_mileage_km=2000, anchor_kind="service")  # 3 kind, no date
        _reminder(
            conn, due_mileage_km=2000, anchor_kind="baseline", anchor_date="2026-09-01"
        )  # 4 anchored
        _reminder(conn, due_mileage_km=2000, status="done")  # 5 closed
        _reminder(conn, due_mileage_km=2000, created_at="2026-09-01 00:00:00")  # 6 nothing before

    _load().upgrade(engine)

    assert _starts(engine) == [
        (1200.0, 120.0),
        (1200.0, 120.0),
        (1200.0, 120.0),
        (None, None),
        (None, None),
        (None, None),
    ]
    # Row 6 is looked at but finds nothing, so it isn't counted.
    assert "Filled start readings on 3 pending unanchored reminders" in caplog.text


def test_129_counts_a_reading_without_created_at_and_skips_a_reminder_without_one(
    engine_for_migration,
):
    """A reading with no created_at can't be shown to be late, so it counts. A
    reminder with no created_at has no creation day, so it's left alone."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    with engine.begin() as conn:
        _odometer(conn, "2026-10-04", 1100, None)
        _hours(conn, "2026-10-04", 125.0, None)
        _reminder(conn, due_mileage_km=2000)
        _reminder(conn, due_mileage_km=2000, created_at=None)
    _load().upgrade(engine)
    assert _starts(engine) == [(1100.0, 125.0), (None, None)]


def test_129_reads_the_creation_day_in_the_household_zone(engine_for_migration):
    """20:00 UTC on the 1st is 08:00 on the 2nd in Auckland, so a reading dated
    the 2nd and entered at 07:00 local was on file when the reminder was made."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine, zone="Pacific/Auckland")
    with engine.begin() as conn:
        _odometer(conn, "2026-09-02", 2000, "2026-09-01 19:00:00")
        _reminder(conn, due_mileage_km=3000, created_at="2026-09-01 20:00:00")
    _load().upgrade(engine)
    assert _starts(engine) == [(2000.0, None)]


def test_129_is_idempotent_and_keeps_a_stored_start(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    with engine.begin() as conn:
        _odometer(conn, "2026-10-01", 1000, "2026-10-01 09:00:00")
        _hours(conn, "2026-10-01", 100.0, "2026-10-01 09:00:00")
        _reminder(conn, due_mileage_km=2000)
        _reminder(conn, due_mileage_km=2000)
    mod = _load()
    mod.upgrade(engine)
    # Each row keeps one start and loses the other, so the rerun picks it up and
    # only that UPDATE's IS NULL guard keeps the stored one.
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE vehicle_reminders SET start_odometer_km = 999, start_hours = NULL "
                "WHERE id = 1"
            )
        )
        conn.execute(
            text(
                "UPDATE vehicle_reminders SET start_odometer_km = NULL, start_hours = 99 "
                "WHERE id = 2"
            )
        )
    mod.upgrade(engine)
    names = [c["name"] for c in inspect(engine).get_columns("vehicle_reminders")]
    assert names.count("start_odometer_km") == names.count("start_hours") == 1
    assert _starts(engine) == [(999.0, 100.0), (1000.0, 99.0)]


def test_129_adds_the_columns_without_reading_tables(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine, readings=False)
    with engine.begin() as conn:
        _reminder(conn, due_mileage_km=2000)
    _load().upgrade(engine)
    assert _starts(engine) == [(None, None)]


def test_129_a_failed_backfill_is_finished_by_the_next_run(engine_for_migration, monkeypatch):
    """SQLite may keep the columns from the failed run (pysqlite runs DDL outside
    a transaction), PostgreSQL rolls them back; either way the retry completes."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    with engine.begin() as conn:
        _odometer(conn, "2026-10-01", 1000, "2026-10-01 09:00:00")
        _reminder(conn, due_mileage_km=2000)
    mod = _load()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("backfill failed")

    monkeypatch.setattr(mod, "_backfill", _boom)
    with pytest.raises(RuntimeError):
        mod.upgrade(engine)
    monkeypatch.undo()
    mod.upgrade(engine)
    names = [c["name"] for c in inspect(engine).get_columns("vehicle_reminders")]
    assert names.count("start_odometer_km") == names.count("start_hours") == 1
    assert _starts(engine) == [(1000.0, None)]


def test_129_without_the_reminders_table_does_nothing(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("vehicle_reminders")
