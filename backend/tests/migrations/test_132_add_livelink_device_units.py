"""Tests for migration 132 (livelink_device_units, R12)."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

import app.migrations as _m

_NAME = "132_add_livelink_device_units"
_DEVICE = "aabbccddeeff"


def _load():
    path = Path(_m.__file__).parent / f"{_NAME}.py"
    spec = importlib.util.spec_from_file_location(_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_deps(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE livelink_devices "
                "(id INTEGER PRIMARY KEY, device_id VARCHAR(20) NOT NULL UNIQUE)"
            )
        )
        conn.execute(
            text("INSERT INTO livelink_devices (id, device_id) VALUES (1, :d)"), {"d": _DEVICE}
        )


def _foreign_keys_on(conn, dialect: str) -> None:
    # A bare SQLite engine ships with FK enforcement off; the app turns it on.
    if dialect == "sqlite":
        conn.execute(text("PRAGMA foreign_keys=ON"))


def _insert(conn, key: str = "SPEED", source: str = "wire") -> None:
    conn.execute(
        text(
            "INSERT INTO livelink_device_units (device_id, param_key, unit, param_class, source) "
            "VALUES (:d, :k, 'mph', 'speed', :s)"
        ),
        {"d": _DEVICE, "k": key, "s": source},
    )


def test_132_is_not_fatal():
    # create_all builds the table before the runner, so a failed 132 leaves
    # nothing missing and must not stop startup.
    assert _load().FATAL is False


def test_132_creates_the_table_like_the_model(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _load().upgrade(engine)

    insp = inspect(engine)
    assert {c["name"] for c in insp.get_columns("livelink_device_units")} == {
        "id",
        "device_id",
        "param_key",
        "unit",
        "param_class",
        "source",
        "created_at",
        "updated_at",
    }
    (fk,) = insp.get_foreign_keys("livelink_device_units")
    assert fk["referred_table"] == "livelink_devices"
    assert fk["referred_columns"] == ["device_id"]
    assert fk["options"].get("ondelete", "").upper() == "CASCADE"


def test_132_one_row_per_device_and_key(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _load().upgrade(engine)

    with engine.begin() as conn:
        _insert(conn)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _insert(conn)


def test_132_source_is_wire_or_legacy(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _load().upgrade(engine)

    with engine.begin() as conn:
        _insert(conn, "ODOMETER", "legacy")
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _insert(conn, "COOLANT", "guess")


def test_132_rows_go_with_their_device(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _load().upgrade(engine)

    with engine.begin() as conn:
        _foreign_keys_on(conn, dialect)
        _insert(conn)
        conn.execute(text("DELETE FROM livelink_devices WHERE device_id = :d"), {"d": _DEVICE})
        left = conn.execute(text("SELECT COUNT(*) FROM livelink_device_units")).scalar_one()
    assert left == 0


def test_132_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _load().upgrade(engine)
    _load().upgrade(engine)

    assert inspect(engine).has_table("livelink_device_units")


def test_132_skips_an_install_with_no_devices_table(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)

    assert not inspect(engine).has_table("livelink_device_units")
