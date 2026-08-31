"""Tests for migration 096: livelink_devices.odometer_unit (+ backfill).

FATAL migration: the ORM declares ``odometer_unit`` and SQLAlchemy selects it on
every device query, so a missing column breaks the entire LiveLink surface.

The backfill is the part worth testing. Units are a per-device property and the
only evidence on record is the odometer key shape a device has actually
published, so 096 classifies each device from its own ``vehicle_telemetry``
rows. Getting that wrong in either direction is a live bug: calling a metric
device imperial inflates its odometer by 1.6x, and calling an imperial device
metric silently drops every reading through the monotonic guard — which is the
regression that killed auto-recording on 2026-04-23.

Parameterized over SQLite *and* PostgreSQL via ``engine_for_migration`` (PG runs
skip when ``TEST_DATABASE_URL`` is unset).

Every test builds the PRE-096 shape by hand rather than from
``Base.metadata.create_all``: the model now declares ``odometer_unit``, so a
create_all baseline would start in the post-state and "column exists" would be
true before the migration ever ran.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

import app.migrations as _m


def _load(name):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_pre_096_schema(engine) -> None:
    """Build livelink_devices + vehicle_telemetry with NO odometer_unit column."""
    with engine.begin() as conn:
        conn.execute(
            text("""
                CREATE TABLE livelink_devices (
                    id INTEGER PRIMARY KEY,
                    device_id VARCHAR(20) NOT NULL,
                    vin VARCHAR(17),
                    enabled BOOLEAN DEFAULT TRUE
                )
            """)
        )
        conn.execute(
            text("""
                CREATE TABLE vehicle_telemetry (
                    id INTEGER PRIMARY KEY,
                    vin VARCHAR(17) NOT NULL,
                    device_id VARCHAR(20) NOT NULL,
                    param_key VARCHAR(100) NOT NULL,
                    value FLOAT NOT NULL
                )
            """)
        )


def _add_device(conn, device_id: str, unit: str | None = None) -> None:
    conn.execute(
        text("INSERT INTO livelink_devices (device_id, vin) VALUES (:d, :v)"),
        {"d": device_id, "v": f"VIN{device_id:0>14}"},
    )
    if unit is not None:
        conn.execute(
            text("UPDATE livelink_devices SET odometer_unit = :u WHERE device_id = :d"),
            {"u": unit, "d": device_id},
        )


def _add_telemetry(conn, device_id: str, param_key: str) -> None:
    conn.execute(
        text(
            "INSERT INTO vehicle_telemetry (vin, device_id, param_key, value) "
            "VALUES (:v, :d, :p, 1.0)"
        ),
        {"v": f"VIN{device_id:0>14}", "d": device_id, "p": param_key},
    )


def _unit_of(engine, device_id: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT odometer_unit FROM livelink_devices WHERE device_id = :d"),
            {"d": device_id},
        ).scalar_one()


@pytest.mark.usefixtures("engine_for_migration")
class TestMigration096:
    """Column creation and evidence-based backfill."""

    def test_adds_odometer_unit_column(self, engine_for_migration):
        """The column must exist after upgrade; it does not before."""
        _dialect, engine, _url = engine_for_migration
        _make_pre_096_schema(engine)

        before = {c["name"] for c in inspect(engine).get_columns("livelink_devices")}
        assert "odometer_unit" not in before, "pre-096 baseline is already in the post-state"

        _load("096_add_device_odometer_unit").upgrade(engine)

        after = {c["name"] for c in inspect(engine).get_columns("livelink_devices")}
        assert "odometer_unit" in after

    def test_standard_pid_device_is_classified_metric(self, engine_for_migration):
        """A device publishing `A6-ODOMETER` is metric per SAE J1979."""
        _dialect, engine, _url = engine_for_migration
        _make_pre_096_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "devmetric")
            _add_telemetry(conn, "devmetric", "A6-ODOMETER")

        _load("096_add_device_odometer_unit").upgrade(engine)

        assert _unit_of(engine, "devmetric") == "km"

    def test_bare_autopid_device_is_classified_imperial(self, engine_for_migration):
        """A bare `ODOMETER` autopid reads the dash odometer — miles."""
        _dialect, engine, _url = engine_for_migration
        _make_pre_096_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "devmiles")
            _add_telemetry(conn, "devmiles", "ODOMETER")

        _load("096_add_device_odometer_unit").upgrade(engine)

        assert _unit_of(engine, "devmiles") == "mi"

    def test_device_with_no_odometer_telemetry_stays_null(self, engine_for_migration):
        """No evidence means no guess — the service infers on first sight."""
        _dialect, engine, _url = engine_for_migration
        _make_pre_096_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "devquiet")
            _add_telemetry(conn, "devquiet", "0C-ENGINERPM")

        _load("096_add_device_odometer_unit").upgrade(engine)

        assert _unit_of(engine, "devquiet") is None

    def test_rerun_does_not_overwrite_an_operator_set_unit(self, engine_for_migration):
        """Idempotent: the backfill only fills NULLs.

        The runner stamps `schema_migrations` in a separate transaction from
        `upgrade`, so a crash in that window re-runs an applied migration. A
        re-run must not stomp a unit the operator has since corrected by hand.
        """
        _dialect, engine, _url = engine_for_migration
        _make_pre_096_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "devfixed")
            _add_telemetry(conn, "devfixed", "ODOMETER")

        migration = _load("096_add_device_odometer_unit")
        migration.upgrade(engine)
        assert _unit_of(engine, "devfixed") == "mi"

        # Operator overrides the guess: this hardware really does report km.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE livelink_devices SET odometer_unit = 'km' WHERE device_id = 'devfixed'"
                )
            )

        migration.upgrade(engine)

        assert _unit_of(engine, "devfixed") == "km", "re-run clobbered an operator-set unit"
