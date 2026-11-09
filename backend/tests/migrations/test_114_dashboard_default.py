"""Migration 114: reset show_on_dashboard to TRUE, and touch nothing else."""

import importlib.util
from pathlib import Path

from sqlalchemy import text

from tests._engines import SyncEngine

_MIG = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "migrations"
    / "114_livelink_parameter_dashboard_default.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("mig114", _MIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seeded(sync_engine: SyncEngine, tmp_path):
    engine = sync_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE livelink_parameters ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  param_key VARCHAR(100) NOT NULL UNIQUE,"
                "  show_on_dashboard BOOLEAN NOT NULL DEFAULT TRUE,"
                "  archive_only BOOLEAN NOT NULL DEFAULT FALSE"
                ")"
            )
        )
        # The shapes found on a production copy: a WiCAN PID hidden by its
        # class default, and one that was shown.
        conn.execute(
            text(
                "INSERT INTO livelink_parameters (param_key, show_on_dashboard, archive_only) "
                "VALUES ('0B-INTAKEMANIFOLDPRESSURE', FALSE, TRUE), ('0D-VEHICLESPEED', TRUE, FALSE)"
            )
        )
    return engine


def _rows(engine):
    with engine.connect() as conn:
        return {
            key: (bool(show), bool(archive))
            for key, show, archive in conn.execute(
                text("SELECT param_key, show_on_dashboard, archive_only FROM livelink_parameters")
            )
        }


def test_migration_is_fatal():
    """The Live tab's filter ships with it: skipped, dozens of gauges vanish
    with no error anywhere."""
    assert _load().FATAL is True


def test_every_parameter_is_back_on_the_dashboard(tmp_path, sync_engine):
    engine = _seeded(sync_engine, tmp_path)

    _load().upgrade(engine)

    assert all(show for show, _archive in _rows(engine).values())


def test_archive_only_is_untouched(tmp_path, sync_engine):
    """The negative control. archive_only keeps diagnostics out of the chart
    picker, and resetting it too would surface every one of them there."""
    engine = _seeded(sync_engine, tmp_path)

    _load().upgrade(engine)

    rows = _rows(engine)
    assert rows["0B-INTAKEMANIFOLDPRESSURE"][1] is True
    assert rows["0D-VEHICLESPEED"][1] is False


def test_is_idempotent(tmp_path, sync_engine):
    engine = _seeded(sync_engine, tmp_path)
    migration = _load()

    migration.upgrade(engine)
    first = _rows(engine)
    migration.upgrade(engine)

    assert _rows(engine) == first


def test_a_missing_table_is_a_no_op(tmp_path, sync_engine):
    engine = sync_engine(f"sqlite:///{tmp_path / 'empty.db'}")

    _load().upgrade(engine)
