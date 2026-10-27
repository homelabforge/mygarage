"""Migration 134: PG timestamps written in the server's zone come back as UTC.

Rows here are written the way the bug wrote them: on an unpinned session, in
that session's zone. The sidecar's own zone is Asia/Kolkata (+05:30), and a
test that wants another zone sets it with `SET TIME ZONE` on the connection it
hands to `upgrade(conn)` (or `ALTER DATABASE` and a reconnect), never through
`options`, which is the `source = client` path the repair refuses (Fable F-5).

The pinned `pg_engine` fixture only does DDL and reads here. Anything that has
to land in a server zone goes through `_unpinned`.
"""

import importlib.util
import logging
import os
import shutil
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import (
    Boolean,
    Connection,
    Date,
    DateTime,
    Engine,
    Enum,
    Float,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import functions

import app.migrations as _m
import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.database import Base
from app.migrations.runner import TIMESTAMP_REPAIR_STEM, MigrationRunner, run_migrations
from app.utils.datetime_utils import utc_now
from app.utils.db_url import to_sync_url

pytestmark = pytest.mark.migrations

MIGRATIONS = Path(_m.__file__).parent
REPAIR_FILE = MIGRATIONS / f"{TIMESTAMP_REPAIR_STEM}.py"

# Commit latency and a slow fresh install, not zone error: a server-zone stamp is 5.5 h out here.
SKEW = timedelta(seconds=120)

#: The model columns stamped by func.now() that the repair leaves alone, and why.
#: A new func.now() column has to land here or in the migration's list, so the
#: test below fails until someone decides.
LEFT_ALONE = {
    # MIXED: the app writes UTC into these too, so a row can't be told apart.
    "livelink_devices.updated_at",
    "users.updated_at",
    "vehicles.updated_at",
    "settings.updated_at",
    "vehicle_telemetry.received_at",
    "vehicle_telemetry_latest.received_at",
    "livelink_firmware_cache.checked_at",
    # APP-ALWAYS: never the server's default at runtime.
    "audit_logs.timestamp",
    "csrf_tokens.created_at",
    "oidc_states.created_at",
    "oidc_pending_links.created_at",
    "vehicle_dtcs.first_seen",
    "vehicle_dtcs.last_seen",
    "vehicle_shares.shared_at",
    "vehicle_transfers.transferred_at",
    "livelink_device_units.updated_at",
}


def _load() -> ModuleType:
    """Load 134 by file, as the runner does."""
    spec = importlib.util.spec_from_file_location(TIMESTAMP_REPAIR_STEM, REPAIR_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pg_url() -> str:
    """The sidecar as a psycopg2 URL. Only called under `pg_engine`, which skips without it."""
    return to_sync_url(os.environ["TEST_DATABASE_URL"])


@contextmanager
def _unpinned(**connect_args: Any) -> Iterator[Engine]:
    """A plain psycopg2 engine: the server's zone, as the runner had before the repair."""
    engine = create_engine(_pg_url(), poolclass=NullPool, connect_args=connect_args)
    try:
        yield engine
    finally:
        engine.dispose()


def _now_stamped_columns() -> set[str]:
    """Every model column whose server default or onupdate is func.now()."""
    found: set[str] = set()
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            server = getattr(column.server_default, "arg", None)
            onupdate = getattr(column.onupdate, "arg", None)
            if isinstance(server, functions.now) or isinstance(onupdate, functions.now):
                found.add(f"{table.name}.{column.name}")
    return found


def _r4_from_models() -> dict[str, list[str]]:
    """R4 from the models, not the migration.

    The end-to-end tests check the outcome, so they don't take 134's word for
    which columns it covers. The list test pins the two equal.
    """
    tables: dict[str, list[str]] = {}
    for name in sorted(_now_stamped_columns() - LEFT_ALONE):
        table, column = name.split(".", 1)
        tables.setdefault(table, []).append(column)
    return tables


_R4 = _r4_from_models()
_R4_NAMES = {f"{table}.{column}" for table, columns in _R4.items() for column in columns}


def _listed(module: ModuleType) -> set[str]:
    return {f"{table}.{column}" for table, columns in module.COLUMNS.items() for column in columns}


def _repair_dir(tmp_path: Path) -> Path:
    """A migrations dir holding only the real 134, so the runner can drive it on its own."""
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "__init__.py").write_text("")
    shutil.copy(REPAIR_FILE, d / REPAIR_FILE.name)
    return d


def _applied(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return set(conn.execute(text("SELECT migration_name FROM schema_migrations")).scalars())


@pytest.fixture
def schema(pg_engine: Engine) -> Engine:
    """Every model table, on an empty PG schema. DDL only, so the pin doesn't matter."""
    Base.metadata.create_all(pg_engine)
    return pg_engine


def _put_setting(conn: Connection, key: str, created_at: str, *, zone_instant: bool) -> None:
    """A settings row; with `zone_instant` the stamp is an instant cast into the session's zone.

    That cast is what `now()` did: the instant, as a wall time in the session's zone.
    """
    if conn.dialect.name == "sqlite":
        expr = ":at"  # a CAST there takes numeric affinity and keeps the year
    elif zone_instant:
        expr = "CAST(CAST(:at AS timestamptz) AS timestamp)"
    else:
        expr = "CAST(:at AS timestamp)"
    conn.execute(
        text(f"INSERT INTO settings (key, value, created_at) VALUES (:key, 'v', {expr})"),
        {"key": key, "at": created_at},
    )


def _settings_created(conn: Connection) -> dict[str, datetime]:
    rows = conn.execute(text("SELECT key, created_at FROM settings"))
    return {row.key: row.created_at for row in rows}


def _xmins(conn: Connection, table: str) -> dict[Any, str]:
    """Row version per primary key: an UPDATE that touches a row gives it a new xmin."""
    key = "key" if table == "settings" else "id"
    rows = conn.execute(text(f"SELECT {key} AS k, xmin::text AS x FROM {table}"))
    return {row.k: row.x for row in rows}


# --- the list (R4) ---------------------------------------------------------------


def test_the_list_is_every_func_now_column_but_the_mixed_and_app_written_ones() -> None:
    """62 server-only columns plus the three whose app writer isn't released (R4)."""
    repair = _load()
    listed = _listed(repair)

    assert listed == _now_stamped_columns() - LEFT_ALONE
    assert len(listed) == 65
    assert {
        "livelink_devices.created_at",
        "odometer_records.created_at",
        "livelink_device_units.created_at",
    } <= listed
    assert not listed & LEFT_ALONE


def test_the_repair_is_fatal_and_commits_with_its_stamp() -> None:
    """R5 and R5a: FATAL, `upgrade(conn)`, and no REPLACES (that path stamps elsewhere)."""
    repair = _load()
    runner = MigrationRunner("sqlite://", MIGRATIONS)
    try:
        assert repair.FATAL is True
        assert runner._takes_conn(repair)
        assert runner._get_replaces(repair) == []
    finally:
        runner.engine.dispose()


# --- conversion (R3) ---------------------------------------------------------------


def test_pg_chicago_rows_across_dst_come_back_as_the_utc_instants(schema: Engine) -> None:
    """January is CST (-6), July is CDT (-5): a fixed shift gets one of them wrong."""
    repair = _load()
    with _unpinned() as engine, engine.begin() as conn:
        conn.execute(text("SET TIME ZONE 'America/Chicago'"))
        _put_setting(conn, "january", "2026-01-15 18:00:00+00", zone_instant=True)
        _put_setting(conn, "july", "2026-07-15 17:00:00+00", zone_instant=True)
        # Both were noon on the Chicago wall clock.
        assert _settings_created(conn) == {
            "january": datetime(2026, 1, 15, 12, 0),
            "july": datetime(2026, 7, 15, 12, 0),
        }

        repair.upgrade(conn)

        assert _settings_created(conn) == {
            "january": datetime(2026, 1, 15, 18, 0),
            "july": datetime(2026, 7, 15, 17, 0),
        }


def test_pg_the_server_zone_comes_from_alter_database_too(schema: Engine) -> None:
    """A zone set on the database (source `database`) is the app's zone too, so it converts."""
    repair = _load()
    with schema.begin() as conn:
        db = conn.execute(text("SELECT current_database()")).scalar_one()
        conn.execute(text(f"ALTER DATABASE \"{db}\" SET timezone = 'America/Chicago'"))
    try:
        with _unpinned() as engine, engine.begin() as conn:
            source = conn.execute(
                text("SELECT source FROM pg_settings WHERE name = 'TimeZone'")
            ).scalar_one()
            assert source == "database"
            _put_setting(conn, "january", "2026-01-15 18:00:00+00", zone_instant=True)

            repair.upgrade(conn)

            assert _settings_created(conn) == {"january": datetime(2026, 1, 15, 18, 0)}
    finally:
        with schema.begin() as conn:
            conn.execute(text(f'ALTER DATABASE "{db}" RESET timezone'))


def test_pg_a_utc_server_is_a_logged_no_op(
    schema: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    """The predicate alone makes UTC a no-op: no row is even rewritten."""
    repair = _load()
    with schema.begin() as conn:
        db = conn.execute(text("SELECT current_database()")).scalar_one()
        conn.execute(text(f"ALTER DATABASE \"{db}\" SET timezone = 'UTC'"))
    try:
        with _unpinned() as engine, engine.connect() as conn:
            assert conn.execute(text("SHOW timezone")).scalar_one() == "UTC"
            _put_setting(conn, "a", "2026-01-15 18:00:00", zone_instant=False)
            _put_setting(conn, "b", "2026-07-15 17:00:00", zone_instant=False)
            conn.commit()  # so a rewrite would carry a new xmin
            before = _xmins(conn, "settings")

            with caplog.at_level(logging.INFO):
                repair.upgrade(conn)

            assert _settings_created(conn) == {
                "a": datetime(2026, 1, 15, 18, 0),
                "b": datetime(2026, 7, 15, 17, 0),
            }
            assert _xmins(conn, "settings") == before
    finally:
        with schema.begin() as conn:
            conn.execute(text(f'ALTER DATABASE "{db}" RESET timezone'))
    assert "converted 0 timestamp(s)" in caplog.text
    assert "UTC" in caplog.text


def test_pg_a_value_already_equal_under_the_zone_is_not_rewritten(schema: Engine) -> None:
    """London is UTC in winter: the January row matches its own conversion and stays put.

    Guard (the July row converting fails at t=0, the xmin check is the guard):
    kills dropping `c <> (c AT TIME ZONE zone) AT TIME ZONE 'UTC'` from the WHERE.
    """
    repair = _load()
    with _unpinned() as engine, engine.connect() as conn:
        conn.execute(text("SET TIME ZONE 'Europe/London'"))
        _put_setting(conn, "winter", "2026-01-15 12:00:00+00", zone_instant=True)
        _put_setting(conn, "summer", "2026-07-15 11:00:00+00", zone_instant=True)
        conn.commit()  # so a rewrite would carry a new xmin
        before = _xmins(conn, "settings")

        repair.upgrade(conn)

        assert _settings_created(conn) == {
            "winter": datetime(2026, 1, 15, 12, 0),
            "summer": datetime(2026, 7, 15, 11, 0),
        }
        after = _xmins(conn, "settings")
        assert after["winter"] == before["winter"], "winter row was rewritten"
        assert after["summer"] != before["summer"]


def test_pg_a_utc_session_rewrites_no_row(schema: Engine, caplog: pytest.LogCaptureFixture) -> None:
    """Guard: every value already equals its conversion, so the count is 0 and no xmin moves.

    Kills dropping the `<>` predicate (every non-null row rewritten, count 2).
    """
    repair = _load()
    with _unpinned() as engine, engine.connect() as conn:
        conn.execute(text("SET TIME ZONE 'UTC'"))
        _put_setting(conn, "a", "2026-01-15 18:00:00", zone_instant=False)
        _put_setting(conn, "b", "2026-07-15 17:00:00", zone_instant=False)
        conn.commit()  # so a rewrite would carry a new xmin
        before = _xmins(conn, "settings")

        with caplog.at_level(logging.INFO):
            repair.upgrade(conn)

        assert _xmins(conn, "settings") == before
    assert "converted 0 timestamp(s)" in caplog.text


def test_pg_a_mixed_column_is_left_alone(schema: Engine) -> None:
    """users.updated_at holds the app's UTC as well as server stamps, so it stays as it is."""
    repair = _load()
    users: Table = Base.metadata.tables["users"]
    with _unpinned() as engine, engine.begin() as conn:
        conn.execute(text("SET TIME ZONE 'America/Chicago'"))
        conn.execute(users.insert().values(username="u", email="u@example.com"))
        conn.execute(
            text(
                "UPDATE users SET created_at = TIMESTAMP '2026-07-15 12:00', "
                "updated_at = TIMESTAMP '2026-07-15 12:00'"
            )
        )

        repair.upgrade(conn)

        row = conn.execute(text("SELECT created_at, updated_at FROM users")).one()
        assert row.created_at == datetime(2026, 7, 15, 17, 0)
        assert row.updated_at == datetime(2026, 7, 15, 12, 0)


def test_pg_a_client_zone_converts_nothing_and_warns(
    schema: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    """`options=-c timezone` (like PGTZ/PGOPTIONS) may not be the zone the app wrote in."""
    repair = _load()
    with _unpinned(options="-c timezone=America/Chicago") as engine, engine.begin() as conn:
        _put_setting(conn, "a", "2026-07-15 12:00:00", zone_instant=False)

        with caplog.at_level(logging.INFO):
            repair.upgrade(conn)

        assert _settings_created(conn) == {"a": datetime(2026, 7, 15, 12, 0)}
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "no warning"
    assert "America/Chicago" in warnings[0].getMessage()
    assert "client" in warnings[0].getMessage()


def test_pg_pgtz_through_the_runner_converts_nothing_and_still_stamps(
    schema: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The real case: PGTZ in the runner's environment. Stamped, so it never comes back."""
    with _unpinned() as engine, engine.begin() as conn:
        _put_setting(conn, "a", "2026-07-15 12:00:00", zone_instant=False)
    monkeypatch.setenv("PGTZ", "America/Chicago")

    with caplog.at_level(logging.INFO):
        run_migrations(_pg_url(), _repair_dir(tmp_path))

    with schema.connect() as conn:
        assert _settings_created(conn) == {"a": datetime(2026, 7, 15, 12, 0)}
    assert TIMESTAMP_REPAIR_STEM in _applied(schema)
    assert any(r.levelno == logging.WARNING and "client" in r.getMessage() for r in caplog.records)


_FAIL_ON_UPDATE = """
CREATE FUNCTION repair_test_refuse() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'second table refuses the update';
END
$$ LANGUAGE plpgsql
"""


def test_pg_a_failure_on_the_second_table_rolls_back_the_first(
    schema: Engine, tmp_path: Path
) -> None:
    """One transaction with the stamp (R5a): nothing converted, nothing stamped, and fatal."""
    repair = _load()
    first, second = list(repair.COLUMNS)[:2]
    assert (first, second) == ("address_book", "attachments")
    with _unpinned() as engine, engine.begin() as conn:
        conn.execute(text("INSERT INTO address_book (business_name) VALUES ('shop')"))
        conn.execute(
            text(
                "INSERT INTO attachments (record_type, record_id, file_path) "
                "VALUES ('service', 1, 'a.pdf')"
            )
        )
        conn.execute(text(_FAIL_ON_UPDATE))
        conn.execute(
            text(
                "CREATE TRIGGER refuse BEFORE UPDATE ON attachments "
                "FOR EACH ROW EXECUTE FUNCTION repair_test_refuse()"
            )
        )
    with schema.connect() as conn:
        stamped = conn.execute(text("SELECT created_at FROM address_book")).scalar_one()

    with pytest.raises(Exception, match="refuses the update") as raised:
        run_migrations(_pg_url(), _repair_dir(tmp_path))

    assert getattr(raised.value, "__migration_fatal__", None) is True
    with schema.connect() as conn:
        assert conn.execute(text("SELECT created_at FROM address_book")).scalar_one() == stamped
    assert TIMESTAMP_REPAIR_STEM not in _applied(schema)


def test_pg_a_stamped_repair_never_runs_again(
    schema: Engine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Guard: a second pass skips it, and a server-zone row written after it stays as written.

    Kills a runner that runs an applied migration again. Its pinned session would
    make that rerun convert nothing, so the log is what tells.
    """
    d = _repair_dir(tmp_path)
    run_migrations(_pg_url(), d)
    with _unpinned() as engine, engine.begin() as conn:
        _put_setting(conn, "later", "2026-07-15 12:00:00", zone_instant=False)
    caplog.clear()

    with caplog.at_level(logging.INFO):
        run_migrations(_pg_url(), d)

    assert "Timestamp repair from" not in caplog.text
    assert TIMESTAMP_REPAIR_STEM not in caplog.text
    with schema.connect() as conn:
        assert _settings_created(conn) == {"later": datetime(2026, 7, 15, 12, 0)}


def test_sqlite_the_repair_is_a_no_op(tmp_path: Path) -> None:
    """Guard: SQLite has no session zone; CURRENT_TIMESTAMP was UTC all along.

    Kills dropping the dialect test (pg_settings doesn't exist there).
    """
    repair = _load()
    engine = create_engine(f"sqlite:///{tmp_path / 'mygarage.db'}")
    try:
        Base.metadata.tables["settings"].create(engine)
        with engine.begin() as conn:
            _put_setting(conn, "a", "2026-07-15 12:00:00", zone_instant=False)
            repair.upgrade(conn)
            stored = conn.execute(text("SELECT created_at FROM settings")).scalar_one()
            assert stored == "2026-07-15 12:00:00"
        run_migrations(f"sqlite:///{tmp_path / 'mygarage.db'}", _repair_dir(tmp_path))
        assert _applied(engine) == {TIMESTAMP_REPAIR_STEM}
    finally:
        engine.dispose()


# --- end to end under the +05:30 sidecar ------------------------------------------

#: Values for NOT NULL columns a type-based guess gets wrong (CHECKs and the like).
_OVERRIDES: dict[str, dict[str, Any]] = {
    "attachments": {"record_type": "service"},
    "brake_axles": {"brake_type": "disc", "axle": "front"},
    "brake_jobs": {"brake_type": "disc", "position": "FL"},
    "brake_measurements": {"position": "FL"},
    "brake_reminder_marks": {"position": "FL"},
    "financing_records": {"category": "loan_payment"},
    "insurance_policies": {"premium_frequency": "Monthly"},
    "insurance_policy_vehicles": {"policy_type": "Liability"},
    "livelink_device_units": {"source": "wire"},
    "service_visits": {"service_category": "Maintenance"},
    "supplies": {"unit_type": "count"},
    "tax_records": {"tax_type": "Registration"},
    "vehicle_maintenance_rules": {"interval_months": 6},
    "vehicle_reminders": {"reminder_type": "date", "status": "pending"},
    "warranty_records": {"warranty_type": "Manufacturer"},
}


def _value_for(table: Table, name: str) -> Any:
    """A value for a NOT NULL column with no default, by type."""
    override = _OVERRIDES.get(table.name, {})
    if name in override:
        return override[name]
    column = table.columns[name]
    kind = column.type
    if isinstance(kind, Enum):
        return kind.enums[0]
    if isinstance(kind, Boolean):
        return False
    if isinstance(kind, DateTime):
        return datetime(2026, 1, 1, 12, 0)
    if isinstance(kind, Date):
        return date(2026, 1, 1)
    if isinstance(kind, Integer):
        return 1
    if isinstance(kind, Numeric | Float):
        return Decimal("1")
    if isinstance(kind, String | Text):
        length = getattr(kind, "length", None) or 20
        return ("x" * 20)[:length]
    raise AssertionError(f"no seed value for {table.name}.{name} ({kind!r})")


def _seed(conn: Connection, table: Table, seeded: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Insert one row into `table` (and its required parents first); return the row.

    Every listed stamp is `now()`, in the session's zone, as 3.9.0's server defaults
    and onupdates wrote them. That includes the two that gained `default=utc_now`
    after 3.9.0, which a plain insert would fill in UTC.
    """
    if table.name in seeded:
        return seeded[table.name]
    values: dict[str, Any] = {column: functions.now() for column in _R4.get(table.name, [])}
    for column in table.columns:
        if column.name in values:
            continue
        if column.server_default is not None or column.default is not None:
            continue
        if (
            column.primary_key
            and column.autoincrement in (True, "auto")
            and isinstance(column.type, Integer)
        ):
            continue
        fks = list(column.foreign_keys)
        if fks and (not column.nullable or column.primary_key):
            parent = _seed(conn, fks[0].column.table, seeded)
            values[column.name] = parent[fks[0].column.name]
            continue
        if column.nullable:
            continue
        values[column.name] = _value_for(table, column.name)
    values.update(_OVERRIDES.get(table.name, {}))
    row = conn.execute(table.insert().values(**values).returning(*table.columns)).mappings().one()
    seeded[table.name] = dict(row)
    return seeded[table.name]


def _seed_every_listed_table(conn: Connection) -> None:
    """A row in every table the repair lists."""
    seeded: dict[str, dict[str, Any]] = {}
    for name in _R4:
        _seed(conn, Base.metadata.tables[name], seeded)


def _spread(conn: Connection) -> dict[str, tuple[int, datetime, datetime]]:
    """Per listed column: how many values, and the earliest and latest."""
    out: dict[str, tuple[int, datetime, datetime]] = {}
    for table, columns in _R4.items():
        for column in columns:
            row = conn.execute(
                text(f"SELECT count({column}), min({column}), max({column}) FROM {table}")
            ).one()
            if row[0]:
                out[f"{table}.{column}"] = (row[0], row[1], row[2])
    return out


def _off_utc(
    spread: dict[str, tuple[int, datetime, datetime]], start: datetime, end: datetime
) -> dict[str, tuple[datetime, datetime]]:
    """Columns holding a value outside [start, end] widened by SKEW."""
    return {
        name: (lo, hi)
        for name, (_, lo, hi) in spread.items()
        if lo < start - SKEW or hi > end + SKEW
    }


async def _app_write_after_boot() -> datetime:
    """A settings row from the app's own engine, right after init_db; its server-default stamp."""
    from app.database import AsyncSessionLocal
    from app.models.settings import Setting

    async with AsyncSessionLocal() as db:
        db.add(Setting(key="after_boot_probe", value="x"))
        await db.commit()
    async with AsyncSessionLocal() as db:
        found = await db.get(Setting, "after_boot_probe")
        assert found is not None
        return found.created_at


@pytest.fixture
async def app_engine_disposed() -> AsyncIterator[None]:
    """The app engine pools; leave none of its connections behind for other tests."""
    from app import database

    yield
    await database.engine.dispose()


async def test_pg_a_fresh_install_leaves_every_listed_column_in_utc(
    pg_engine: Engine, app_engine_disposed: None
) -> None:
    """init_db from an empty database: the migrations' own server-zone stamps get repaired."""
    from app import database

    start = utc_now()
    await database.init_db()
    end = utc_now()

    with pg_engine.connect() as conn:
        spread = _spread(conn)
    assert spread.get("settings.created_at", (0,))[0] > 0, "no stamped rows, so this proves nothing"
    assert _off_utc(spread, start, end) == {}

    # Guard: the app engine is pinned on its own (T2); kills dropping that pin.
    written = await _app_write_after_boot()
    assert abs(written - utc_now()) < SKEW
    assert TIMESTAMP_REPAIR_STEM in _applied(pg_engine)


async def test_pg_an_upgrade_from_the_390_head_leaves_every_listed_column_in_utc(
    schema: Engine, app_engine_disposed: None
) -> None:
    """3.9.0's schema and history, a row in every listed table stamped in +05:30, then init_db.

    users.updated_at (MIXED) is stamped too and has to come out still 5:30 ahead.
    """
    from app import database

    released = sorted(
        p.stem for p in MIGRATIONS.glob("[0-9][0-9][0-9]_*.py") if int(p.stem[:3]) <= 131
    )
    assert released[-1].startswith("131_")
    runner = MigrationRunner(_pg_url(), MIGRATIONS)
    try:
        runner._ensure_migration_tracking_table()
        runner._mark_migrations_applied(released)
    finally:
        runner.engine.dispose()

    start = utc_now()
    with _unpinned() as engine, engine.begin() as conn:
        offset = conn.execute(text("SELECT EXTRACT(TIMEZONE FROM now())")).scalar_one()
        assert offset != 0, "sidecar runs UTC, so this proves nothing"
        _seed_every_listed_table(conn)
    with schema.connect() as conn:
        seeded = _spread(conn)
    assert set(seeded) == _R4_NAMES, "a listed column got no value"
    assert set(_off_utc(seeded, start, utc_now())) == set(seeded), "seeded in UTC already"

    await database.init_db()
    end = utc_now()

    with schema.connect() as conn:
        assert _off_utc(_spread(conn), start, end) == {}
        mixed = conn.execute(text("SELECT updated_at FROM users")).scalar_one()
    assert abs(mixed - timedelta(seconds=int(offset)) - start) < SKEW, "users.updated_at moved"

    # Guard: the app engine is pinned on its own (T2); kills dropping that pin.
    written = await _app_write_after_boot()
    assert abs(written - utc_now()) < SKEW
