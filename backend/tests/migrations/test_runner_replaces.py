"""Tests for the migration runner's REPLACES (squash/baseline) mechanism and its
failure contract. The state machine is pure set-logic over already-dialect-aware
stamping, so these SQLite tests exercise it fully (see the design spec).
"""

import logging

import pytest
from sqlalchemy import create_engine, inspect, text

from app.migrations.runner import MigrationRunner

pytestmark = pytest.mark.migrations

_INDIVIDUAL = """\
from sqlalchemy import text

def upgrade(engine=None):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS _run_log (migration VARCHAR)"))
        conn.execute(text("CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO _run_log (migration) VALUES ('{name}')"))
"""

_BASELINE = """\
from sqlalchemy import text

REPLACES = ["001_alpha", "002_beta", "003_gamma"]

def upgrade(engine=None):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS _run_log (migration VARCHAR)"))
        conn.execute(text("CREATE TABLE t_alpha (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE t_beta (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE t_gamma (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO _run_log (migration) VALUES ('000_base')"))
"""

_BASELINE_GHOST = """\
from sqlalchemy import text

REPLACES = ["001_alpha", "999_ghost"]

def upgrade(engine=None):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS _run_log (migration VARCHAR)"))
        conn.execute(text("CREATE TABLE t_alpha (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO _run_log (migration) VALUES ('000_base')"))
"""

_TABLE_FOR = {"001_alpha": "t_alpha", "002_beta": "t_beta", "003_gamma": "t_gamma"}


def _write_dir(tmp_path, *, baseline=_BASELINE, individuals=("001_alpha", "002_beta", "003_gamma")):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "__init__.py").write_text("")
    (d / "000_base.py").write_text(baseline)
    for name in individuals:
        (d / f"{name}.py").write_text(_INDIVIDUAL.format(table=_TABLE_FOR[name], name=name))
    return d


def _runner(tmp_path, migrations_dir):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    return MigrationRunner(url, migrations_dir), url


def _query(url, sql):
    eng = create_engine(url)
    try:
        with eng.connect() as conn:
            return [r[0] for r in conn.execute(text(sql))]
    finally:
        eng.dispose()


def _applied(url):
    eng = create_engine(url)
    try:
        if not inspect(eng).has_table("schema_migrations"):
            return set()
    finally:
        eng.dispose()
    return set(_query(url, "SELECT migration_name FROM schema_migrations"))


def _run_log(url):
    eng = create_engine(url)
    try:
        if not inspect(eng).has_table("_run_log"):
            return set()
    finally:
        eng.dispose()
    return set(_query(url, "SELECT migration FROM _run_log"))


def _tables(url):
    eng = create_engine(url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def _seed(url, *, stamped=(), tables=()):
    """Simulate prior history: stamp migrations applied and/or pre-create tables."""
    eng = create_engine(url)
    try:
        with eng.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_migrations "
                    "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "migration_name VARCHAR(255) NOT NULL UNIQUE, "
                    "applied_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"
                )
            )
            for n in stamped:
                conn.execute(
                    text("INSERT INTO schema_migrations (migration_name) VALUES (:n)"), {"n": n}
                )
            for t in tables:
                conn.execute(text(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY)"))
    finally:
        eng.dispose()


# --- squash classification -------------------------------------------------------


def test_fresh_install_runs_only_baseline(tmp_path):
    runner, url = _runner(tmp_path, _write_dir(tmp_path))
    runner.run_pending_migrations()
    assert _applied(url) == {"000_base", "001_alpha", "002_beta", "003_gamma"}
    assert _run_log(url) == {"000_base"}  # only the baseline ran
    assert {"t_alpha", "t_beta", "t_gamma"} <= _tables(url)


def test_fully_migrated_stamps_baseline_without_running(tmp_path):
    runner, url = _runner(tmp_path, _write_dir(tmp_path))
    _seed(
        url, stamped=("001_alpha", "002_beta", "003_gamma"), tables=("t_alpha", "t_beta", "t_gamma")
    )
    runner.run_pending_migrations()
    assert "000_base" in _applied(url)
    assert _run_log(url) == set()  # baseline upgrade did NOT run


def test_partial_defers_then_converges(tmp_path):
    migrations_dir = _write_dir(tmp_path)
    runner, url = _runner(tmp_path, migrations_dir)
    _seed(url, stamped=("001_alpha",), tables=("t_alpha",))

    runner.run_pending_migrations()  # first boot
    assert "000_base" not in _applied(url)  # baseline deferred
    assert {"001_alpha", "002_beta", "003_gamma"} <= _applied(url)
    assert _run_log(url) == {"002_beta", "003_gamma"}  # only remaining individuals ran

    runner2, _ = _runner(tmp_path, migrations_dir)  # second boot, same DB
    runner2.run_pending_migrations()
    assert "000_base" in _applied(url)  # converged
    assert _run_log(url) == {"002_beta", "003_gamma"}  # baseline never ran its upgrade


def test_idempotent_second_run_is_noop(tmp_path):
    migrations_dir = _write_dir(tmp_path)
    runner, url = _runner(tmp_path, migrations_dir)
    runner.run_pending_migrations()
    applied1, runlog1 = _applied(url), _run_log(url)

    runner2, _ = _runner(tmp_path, migrations_dir)
    runner2.run_pending_migrations()
    assert _applied(url) == applied1
    assert _run_log(url) == runlog1  # nothing re-ran


def test_unknown_replaces_stem_is_warned_and_ignored(tmp_path, caplog):
    migrations_dir = _write_dir(tmp_path, baseline=_BASELINE_GHOST, individuals=("001_alpha",))
    runner, url = _runner(tmp_path, migrations_dir)
    with caplog.at_level(logging.WARNING):
        runner.run_pending_migrations()
    applied = _applied(url)
    assert {"000_base", "001_alpha"} <= applied
    assert "999_ghost" not in applied  # ignored, not stamped
    assert any("999_ghost" in rec.message for rec in caplog.records)


# --- failure contract ------------------------------------------------------------


def test_stamp_failure_on_fatal_module_annotates_fatal(tmp_path, monkeypatch):
    """A tracking-table write failure is inside the per-migration boundary and
    carries the module's FATAL flag, so init_db() halts (R1-H3)."""
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "__init__.py").write_text("")
    (d / "001_fatal.py").write_text("FATAL = True\ndef upgrade(engine=None):\n    pass\n")
    runner, _ = _runner(tmp_path, d)

    def boom(*_a, **_k):
        raise RuntimeError("stamp write failed")

    monkeypatch.setattr(runner, "_mark_migration_applied", boom)
    with pytest.raises(RuntimeError, match="stamp write failed") as ei:
        runner.run_pending_migrations()
    assert getattr(ei.value, "__migration_fatal__", None) is True


def test_module_load_failure_is_caught_and_nonfatal(tmp_path):
    """A module that fails to import is caught by the boundary and annotated
    non-FATAL (no module to read FATAL from) (R1-H3)."""
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "__init__.py").write_text("")
    (d / "001_broken.py").write_text("this is not valid python )(\n")
    runner, _ = _runner(tmp_path, d)
    with pytest.raises(Exception) as ei:  # SyntaxError type is the point
        runner.run_pending_migrations()
    assert getattr(ei.value, "__migration_fatal__", None) is False


def test_batch_stamp_is_atomic(tmp_path):
    """_mark_migrations_applied commits all-or-nothing: a mid-batch UNIQUE
    violation rolls back every marker (R1-H5)."""
    runner, url = _runner(tmp_path, tmp_path)  # dir unused
    runner._ensure_migration_tracking_table()
    with pytest.raises(Exception):  # IntegrityError from the duplicate
        runner._mark_migrations_applied(["dup", "dup"])
    assert _applied(url) == set()  # nothing committed
