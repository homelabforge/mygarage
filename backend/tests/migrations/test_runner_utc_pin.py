"""The runner's UTC pin, its atomic upgrade+stamp path, and PG failing closed.

Rows a PG migration writes before the timestamp repair have to be in the
server's zone, or the repair shifts them wrongly. So the runner and the tools
stay unpinned until the repair is stamped, then pin (R2). The sidecar runs
Asia/Kolkata, so an unpinned stamp lands 5.5 h off UTC.

The repair's stem is monkeypatched to a fake migration here, so none of this
needs the real file.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.pool import NullPool

import app.migrations.runner as runner_module
from app.migrations.runner import MigrationRunner, run_migrations
from app.utils.datetime_utils import utc_now
from app.utils.db_url import to_sync_url
from app.utils.pg_session import _set_session_utc

pytestmark = pytest.mark.migrations

# Commit latency, not zone error: an unpinned stamp is 5.5 h out here.
SKEW = timedelta(seconds=30)
STEM = "002_timestamp_repair"

_NOOP = "def upgrade(engine):\n    pass\n"
_FAIL = 'def upgrade(engine):\n    raise RuntimeError("an ordinary non-fatal failure")\n'
_WONT_LOAD = 'raise ImportError("the repair module will not load")\n'
_PROBE_TABLE = """\
from sqlalchemy import text

def upgrade(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE zone_probe (name VARCHAR(10) PRIMARY KEY, stamped TIMESTAMP NOT NULL)"))
"""


def _stamp_now(name: str) -> str:
    """A migration that writes CURRENT_TIMESTAMP, which lands in the session's zone."""
    return (
        "from sqlalchemy import text\n\n"
        "def upgrade(engine):\n"
        "    with engine.begin() as conn:\n"
        '        conn.execute(text("INSERT INTO zone_probe (name, stamped) '
        f"VALUES ('{name}', CURRENT_TIMESTAMP)\"))\n"
    )


def _migrations(tmp_path: Path, files: dict[str, str]) -> Path:
    """A fake migrations dir; call again to add files to it."""
    d = tmp_path / "migrations"
    d.mkdir(exist_ok=True)
    (d / "__init__.py").write_text("")
    for stem, body in files.items():
        (d / f"{stem}.py").write_text(body)
    return d


def _pg_url() -> str:
    """The sidecar as a psycopg2 URL. Only called under `pg_engine`, which skips without it."""
    return to_sync_url(os.environ["TEST_DATABASE_URL"])


def _stamps(engine: Engine) -> dict[str, datetime]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name, stamped FROM zone_probe"))
        return {row.name: row.stamped for row in rows}


def _applied(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return set(conn.execute(text("SELECT migration_name FROM schema_migrations")).scalars())


def _server_offset(url: str) -> timedelta:
    """How far the server's own zone sits from UTC, read on an unpinned session."""
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            seconds = conn.execute(text("SELECT EXTRACT(TIMEZONE FROM now())")).scalar_one()
    finally:
        engine.dispose()
    return timedelta(seconds=int(seconds))


def _zone(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SHOW timezone")).scalar_one()


@pytest.fixture
def repair_stem(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point the runner's repair stem at a fake migration."""
    monkeypatch.setattr(runner_module, "TIMESTAMP_REPAIR_STEM", STEM)
    return STEM


# --- R2: unpinned until the repair, pinned after --------------------------------


def test_pg_rows_before_the_repair_keep_the_server_zone_and_rows_after_are_utc(
    pg_engine: Engine, tmp_path: Path, repair_stem: str
) -> None:
    """One pass: a writes before the repair, c after it."""
    url = _pg_url()
    d = _migrations(
        tmp_path,
        {
            "000_probe": _PROBE_TABLE,
            "001_a": _stamp_now("a"),
            repair_stem: _NOOP,
            "003_c": _stamp_now("c"),
        },
    )

    run_migrations(url, d)

    offset = _server_offset(url)
    stamps = _stamps(pg_engine)
    now = utc_now()
    assert offset != timedelta(0), "sidecar runs UTC, so this proves nothing"
    assert abs(stamps["a"] - offset - now) < SKEW, f"a={stamps['a']} not in the server zone"
    assert abs(stamps["c"] - now) < SKEW, f"c={stamps['c']} vs UTC now {now}"


def test_pg_a_pass_over_an_already_repaired_db_pins_from_the_start(
    pg_engine: Engine, tmp_path: Path, repair_stem: str
) -> None:
    """d is the first thing the second pass runs, so only a pin at start puts it in UTC."""
    url = _pg_url()
    d = _migrations(tmp_path, {"001_probe": _PROBE_TABLE, repair_stem: _NOOP})
    run_migrations(url, d)

    _migrations(tmp_path, {"003_d": _stamp_now("d")})
    run_migrations(url, d)

    stamped = _stamps(pg_engine)["d"]
    now = utc_now()
    assert abs(stamped - now) < SKEW, f"d={stamped} vs UTC now {now}"


def test_pg_the_pin_is_a_new_engine_and_the_unpinned_one_is_disposed(
    pg_engine: Engine, tmp_path: Path, repair_stem: str
) -> None:
    """A listener on the live pool would miss the connection already in it (R1-F1)."""
    runner = MigrationRunner(_pg_url(), _migrations(tmp_path, {repair_stem: _NOOP}))
    unpinned = runner.engine
    try:
        runner.run_pending_migrations()
        assert runner.engine is not unpinned
        assert event.contains(runner.engine, "connect", _set_session_utc)
        assert not event.contains(unpinned, "connect", _set_session_utc)
        # dispose() empties the pool; the bootstrap's connection would still be in it otherwise.
        assert unpinned.pool.checkedin() == 0
        assert runner.engine.hide_parameters is True
    finally:
        runner.engine.dispose()


def test_pg_the_runners_pin_survives_a_rollback_and_a_pool_round_trip(
    pg_engine: Engine, tmp_path: Path, repair_stem: str
) -> None:
    """Same backend both times, so the second checkout is the session the first rolled back."""
    runner = MigrationRunner(_pg_url(), _migrations(tmp_path, {repair_stem: _NOOP}))
    try:
        runner.run_pending_migrations()
        with runner.engine.connect() as conn:
            pid = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
            conn.rollback()
            assert conn.execute(text("SHOW timezone")).scalar_one() == "UTC"
        with runner.engine.connect() as conn:
            assert conn.execute(text("SELECT pg_backend_pid()")).scalar_one() == pid
            assert conn.execute(text("SHOW timezone")).scalar_one() == "UTC"
    finally:
        runner.engine.dispose()


def test_sqlite_runner_never_swaps_its_engine(tmp_path: Path, repair_stem: str) -> None:
    """Guard: SQLite has no session zone, so the repair stem changes nothing there.

    Kills dropping the dialect test from the pin rule (create_utc_engine passes
    SQLite through, so the swap would still happen).
    """
    d = _migrations(tmp_path, {repair_stem: _NOOP, "003_after": _NOOP})
    runner = MigrationRunner(f"sqlite:///{tmp_path / 'mygarage.db'}", d)
    engine = runner.engine
    try:
        runner.run_pending_migrations()
        assert runner.engine is engine
        assert not event.contains(engine, "connect", _set_session_utc)
        assert _applied(engine) == {repair_stem, "003_after"}
    finally:
        runner.engine.dispose()


# --- R5a: upgrade(conn) commits with its stamp ----------------------------------

_ATOMIC_PROBE = """\
from sqlalchemy import text

def upgrade(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE atomic_probe (id INTEGER PRIMARY KEY, value VARCHAR(20) NOT NULL)"))
        conn.execute(text("INSERT INTO atomic_probe (id, value) VALUES (1, 'before')"))
"""

_ATOMIC = """\
from sqlalchemy import text

def upgrade(conn):
    conn.execute(text("UPDATE atomic_probe SET value = 'after' WHERE id = 1"))
"""


def _probe_value(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT value FROM atomic_probe WHERE id = 1")).scalar_one()


def test_a_conn_migration_commits_its_data_and_stamp(
    engine_for_migration: tuple[str, Engine, str], tmp_path: Path
) -> None:
    _, engine, url = engine_for_migration
    d = _migrations(tmp_path, {"001_probe": _ATOMIC_PROBE, "002_atomic": _ATOMIC})

    run_migrations(url, d)

    assert _probe_value(engine) == "after"
    assert _applied(engine) == {"001_probe", "002_atomic"}


def test_a_conn_migration_that_raises_leaves_no_data_and_no_stamp(
    engine_for_migration: tuple[str, Engine, str], tmp_path: Path
) -> None:
    _, engine, url = engine_for_migration
    raising = _ATOMIC + '    raise RuntimeError("upgrade failed after its update")\n'
    d = _migrations(tmp_path, {"001_probe": _ATOMIC_PROBE, "002_atomic": raising})

    with pytest.raises(RuntimeError, match="after its update"):
        run_migrations(url, d)

    assert _probe_value(engine) == "before"
    assert _applied(engine) == {"001_probe"}


def test_a_conn_migration_whose_stamp_fails_leaves_no_data(
    engine_for_migration: tuple[str, Engine, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stamp INSERT runs, then blows up: the data rolls back with it.

    A rerun of the repair would shift every row twice, so data without a stamp
    is the one outcome this path exists to rule out.
    """
    _, engine, url = engine_for_migration
    d = _migrations(tmp_path, {"001_probe": _ATOMIC_PROBE, "002_atomic": _ATOMIC})
    insert_stamps = MigrationRunner._insert_stamps

    def _stamp_then_fail(self: MigrationRunner, conn: object, names: list[str]) -> None:
        insert_stamps(self, conn, names)  # type: ignore[arg-type]
        if "002_atomic" in names:
            raise RuntimeError("stamp failed")

    monkeypatch.setattr(MigrationRunner, "_insert_stamps", _stamp_then_fail)

    with pytest.raises(RuntimeError, match="stamp failed"):
        run_migrations(url, d)

    assert _probe_value(engine) == "before"
    assert _applied(engine) == {"001_probe"}


def test_a_conn_migration_cannot_also_replace(tmp_path: Path) -> None:
    """The squash path stamps several stems, which the one-conn path doesn't do."""
    d = _migrations(
        tmp_path,
        {
            "001_squash": 'REPLACES = ["000_gone"]\n\ndef upgrade(conn):\n    raise AssertionError("ran")\n'
        },
    )
    runner = MigrationRunner(f"sqlite:///{tmp_path / 'mygarage.db'}", d)
    try:
        with pytest.raises(TypeError, match="REPLACES"):
            runner.run_pending_migrations()
        assert _applied(runner.engine) == set()
    finally:
        runner.engine.dispose()


# --- R5b: on PG, nothing fails quietly before the repair -------------------------

_BEFORE_THE_REPAIR = [
    pytest.param({"001_fail": _FAIL}, id="non-fatal-migration-fails"),
    pytest.param({STEM: _WONT_LOAD}, id="repair-module-will-not-load"),
]


@pytest.mark.parametrize("files", _BEFORE_THE_REPAIR)
def test_pg_a_failure_before_the_repair_is_fatal(
    pg_engine: Engine, tmp_path: Path, repair_stem: str, files: dict[str, str]
) -> None:
    with pytest.raises(Exception) as raised:
        run_migrations(_pg_url(), _migrations(tmp_path, files))
    assert getattr(raised.value, "__migration_fatal__", None) is True


@pytest.mark.parametrize("files", _BEFORE_THE_REPAIR)
async def test_pg_init_db_stops_when_a_migration_fails_before_the_repair(
    pg_engine: Engine,
    tmp_path: Path,
    repair_stem: str,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, str],
) -> None:
    """The app's own startup, on the real runner, against the fake dir."""
    from app import database

    d = _migrations(tmp_path, files)
    run = runner_module.run_migrations
    monkeypatch.setattr(runner_module, "run_migrations", lambda url, _dir: run(url, d))
    try:
        with pytest.raises(Exception) as raised:
            await database.init_db()
    finally:
        # The app engine pools; leave none of its connections behind for other tests.
        await database.engine.dispose()
    assert getattr(raised.value, "__migration_fatal__", None) is True


def test_pg_a_failure_after_the_repair_stays_non_fatal(
    pg_engine: Engine, tmp_path: Path, repair_stem: str
) -> None:
    """Guard: once the repair is stamped, a non-FATAL migration goes back to log-and-continue.

    Kills dropping the stem test from the except path (every PG failure fatal).
    """
    d = _migrations(tmp_path, {repair_stem: _NOOP, "003_fail": _FAIL})
    with pytest.raises(RuntimeError) as raised:
        run_migrations(_pg_url(), d)
    assert getattr(raised.value, "__migration_fatal__", None) is False
    assert _applied(pg_engine) == {repair_stem}


def test_sqlite_a_failure_before_the_repair_stays_non_fatal(
    tmp_path: Path, repair_stem: str
) -> None:
    """Guard: SQLite keeps today's policy. Kills dropping the dialect test from the except path."""
    d = _migrations(tmp_path, {"001_fail": _FAIL})
    with pytest.raises(RuntimeError) as raised:
        run_migrations(f"sqlite:///{tmp_path / 'mygarage.db'}", d)
    assert getattr(raised.value, "__migration_fatal__", None) is False


# --- R5b: init_db's positive check, and a pin swap that fails --------------------


async def _init_db_on(d: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The app's own startup, on the real runner, against a fake dir."""
    from app import database

    run = runner_module.run_migrations
    monkeypatch.setattr(runner_module, "run_migrations", lambda url, _dir: run(url, d))
    try:
        await database.init_db()
    finally:
        # The app engine pools; leave none of its connections behind for other tests.
        await database.engine.dispose()


def _injected(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("injected failure")


@pytest.mark.parametrize("seam", ["_ensure_migration_tracking_table", "_get_applied_migrations"])
async def test_pg_init_db_stops_when_the_runner_fails_outside_its_handler(
    pg_engine: Engine,
    tmp_path: Path,
    repair_stem: str,
    monkeypatch: pytest.MonkeyPatch,
    seam: str,
) -> None:
    """The bootstrap and the history read run before the per-migration try, unannotated."""
    monkeypatch.setattr(MigrationRunner, seam, _injected)

    with pytest.raises(RuntimeError, match=repair_stem):
        await _init_db_on(_migrations(tmp_path, {repair_stem: _NOOP}), monkeypatch)


async def test_pg_init_db_stops_when_the_runner_is_clean_but_the_repair_is_missing(
    pg_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No file has the stem's name, so every migration runs fine and the repair never does."""
    monkeypatch.setattr(runner_module, "TIMESTAMP_REPAIR_STEM", "999_no_such_migration")

    with pytest.raises(RuntimeError, match="999_no_such_migration"):
        await _init_db_on(_migrations(tmp_path, {"001_other": _NOOP}), monkeypatch)

    assert _applied(pg_engine) == {"001_other"}


async def test_pg_init_db_goes_on_once_the_repair_is_stamped(
    pg_engine: Engine, tmp_path: Path, repair_stem: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard: the check lets a repaired database start.

    Kills a check that refuses on PG whatever it finds, or that looks for a name
    other than the runner's constant.
    """
    await _init_db_on(_migrations(tmp_path, {repair_stem: _NOOP}), monkeypatch)

    assert _applied(pg_engine) == {repair_stem}


async def test_sqlite_init_db_still_logs_a_bootstrap_failure_and_goes_on(
    tmp_path: Path, repair_stem: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard: SQLite keeps today's policy. Kills dropping the dialect test from the check."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import database
    from app.config import settings

    url = f"sqlite+aiosqlite:///{tmp_path / 'mygarage.db'}"
    engine = create_async_engine(url)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(MigrationRunner, "_ensure_migration_tracking_table", _injected)
    d = _migrations(tmp_path, {repair_stem: _NOOP})
    run = runner_module.run_migrations
    monkeypatch.setattr(runner_module, "run_migrations", lambda u, _dir: run(u, d))
    try:
        await database.init_db()
    finally:
        await engine.dispose()


def _swap_fails(*_args: object, **_kwargs: object) -> Engine:
    raise RuntimeError("pin swap failed")


async def test_pg_a_pin_swap_that_fails_at_start_stops_startup(
    pg_engine: Engine, tmp_path: Path, repair_stem: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repair is stamped, so the positive check passes; the swap itself has to be fatal.

    Otherwise the run stops at the swap, unannotated, and the app boots with
    later migrations never run.
    """
    d = _migrations(tmp_path, {repair_stem: _NOOP})
    run_migrations(_pg_url(), d)
    _migrations(tmp_path, {"003_after": _NOOP})
    monkeypatch.setattr(runner_module, "create_utc_engine", _swap_fails)

    with pytest.raises(RuntimeError, match="pin swap failed") as raised:
        await _init_db_on(d, monkeypatch)

    assert getattr(raised.value, "__migration_fatal__", None) is True
    assert _applied(pg_engine) == {repair_stem}


def test_pg_a_pin_swap_that_fails_after_the_repair_is_fatal(
    pg_engine: Engine, tmp_path: Path, repair_stem: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repair stamped, then its swap failed: fatal even though the repair's module isn't."""
    d = _migrations(tmp_path, {repair_stem: _NOOP, "003_after": _NOOP})
    monkeypatch.setattr(runner_module, "create_utc_engine", _swap_fails)

    with pytest.raises(RuntimeError, match="pin swap failed") as raised:
        run_migrations(_pg_url(), d)

    assert getattr(raised.value, "__migration_fatal__", None) is True
    assert _applied(pg_engine) == {repair_stem}


# --- tools: same pin rule as the runner -------------------------------------------


def test_pg_tool_engine_pins_only_once_the_repair_is_stamped(
    pg_engine: Engine, tmp_path: Path, repair_stem: str
) -> None:
    from tools._tool_db import create_tool_engine

    url = _pg_url()

    def tool_zone() -> str:
        engine = create_tool_engine(url)
        try:
            assert engine.hide_parameters is True
            return _zone(engine)
        finally:
            engine.dispose()

    assert tool_zone() != "UTC", "no schema_migrations yet: a never-booted database"

    run_migrations(url, _migrations(tmp_path, {"001_other": _NOOP}))
    assert tool_zone() != "UTC", "tracking table, but no repair stamp"

    with pg_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO schema_migrations (migration_name) VALUES (:n)"), {"n": repair_stem}
        )
    assert tool_zone() == "UTC"
