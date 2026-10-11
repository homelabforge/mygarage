"""Migration 128: drop `vehicle_reminders.projected_distance_km` on both dialects.

The table is the real one from `create_all`, CHECKs and indexes included, with
the old column put back, so SQLite's DROP COLUMN runs against what prod has.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path

from sqlalchemy import inspect, text

import app.migrations as _m
import app.models  # noqa: F401  (registers the tables create_all needs)
from app.database import Base

_NAME = "128_drop_reminder_projected_distance"
_VIN = "VINPROJDIST000001"
_COLUMN = "projected_distance_km"


def _load():
    path = Path(_m.__file__).parent / f"{_NAME}.py"
    spec = importlib.util.spec_from_file_location(_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(engine) -> int:
    """The current table plus the old column, and one low-tread reminder using it."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE vehicle_reminders ADD COLUMN projected_distance_km NUMERIC(10, 2)")
        )
        conn.execute(
            text(
                "INSERT INTO vehicles "
                "(vin, nickname, vehicle_type, usage_unit, secondary_usage_enabled) "
                "VALUES (:vin, 'Proj Dist', 'Car', 'distance', false)"
            ),
            {"vin": _VIN},
        )
        conn.execute(
            text(
                "INSERT INTO vehicle_reminders "
                "(vin, title, reminder_type, due_date, due_mileage_km, status, source, "
                "tread_depth_mm, tread_threshold_mm, notes, projected_distance_km) "
                "VALUES (:vin, 'Tire tread low (FL)', 'date', '2025-05-01', 90000, "
                "'pending', 'low_tread', 1.50, 2.00, 'Rotated in spring.', 1234.50)"
            ),
            {"vin": _VIN},
        )
        return conn.execute(
            text("SELECT id FROM vehicle_reminders WHERE vin = :vin"), {"vin": _VIN}
        ).scalar_one()


def _columns(engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("vehicle_reminders")}


def _row(engine, reminder_id: int) -> dict:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                text("SELECT * FROM vehicle_reminders WHERE id = :id"), {"id": reminder_id}
            )
            .mappings()
            .one()
        )


def _structure(engine) -> dict[str, set]:
    insp = inspect(engine)
    return {
        "checks": {c["name"] for c in insp.get_check_constraints("vehicle_reminders")},
        "indexes": {i["name"] for i in insp.get_indexes("vehicle_reminders")},
        "fks": {
            (fk["name"], tuple(fk["constrained_columns"]), fk["referred_table"])
            for fk in insp.get_foreign_keys("vehicle_reminders")
        },
    }


def test_128_drops_the_column_and_keeps_the_row_and_the_table(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    reminder_id = _seed(engine)
    before = _row(engine, reminder_id)
    structure = _structure(engine)
    assert before[_COLUMN] is not None
    assert {"check_reminder_type", "check_reminder_status", "check_due_mileage_km"} <= structure[
        "checks"
    ]
    assert {
        "ix_reminders_vin_status",
        "ix_reminders_due_date",
        "ix_reminders_due_mileage_km",
        "uq_reminders_rule_pending",
    } <= structure["indexes"]
    assert "fk_reminders_tire_vin" in {name for name, _cols, _table in structure["fks"]}

    _load().upgrade(engine)

    assert _COLUMN not in _columns(engine)
    after = _row(engine, reminder_id)
    assert after == {k: v for k, v in before.items() if k != _COLUMN}
    assert (after["title"], after["notes"]) == ("Tire tread low (FL)", "Rotated in spring.")
    assert Decimal(str(after["tread_depth_mm"])) == Decimal("1.50")
    assert _structure(engine) == structure


def test_128_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    reminder_id = _seed(engine)
    mod = _load()
    mod.upgrade(engine)
    once = _row(engine, reminder_id)
    mod.upgrade(engine)
    assert _COLUMN not in _columns(engine)
    assert _row(engine, reminder_id) == once


def test_128_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)


def test_128_is_not_fatal():
    assert _load().FATAL is False
