"""Migration 135: the 14 batch 7 columns widened to their new types on PostgreSQL.

Like 122's tests, the tables are built by hand at the old types with values in
them, since a create_all schema starts at the new types and the ALTERs would
never run. SQLite ignores declared precision, so there it must do nothing.
"""

import importlib.util
import logging
import os
from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import Column, Engine, Integer, MetaData, Numeric, Table, event, text

import app.migrations as _m
from app.migrations.runner import MigrationRunner
from app.utils.db_url import to_sync_url
from tests.migrations._money_columns import PRE_122_TYPES, pg_numeric_types
from tests.migrations._widened_columns import PRE_135_TYPES, R7_TYPES

pytestmark = pytest.mark.migrations

NAME = "135_widen_numeric_columns"
MIGRATIONS = Path(_m.__file__).parent

type Values = dict[str, dict[int, Decimal | None]]
type EngineParam = tuple[str, Engine, str]


def _load() -> ModuleType:
    """Load a migration module by file, as the runner does."""
    return _load_named(NAME)


def _load_named(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, MIGRATIONS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _by_table(columns: dict[str, tuple[int, int]]) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for qualified in sorted(columns):
        table, column = qualified.split(".", 1)
        tables.setdefault(table, []).append(column)
    return tables


def _largest(precision: int, scale: int) -> Decimal:
    """Every digit a 9: the most a NUMERIC(precision, scale) holds."""
    return Decimal(10) ** (precision - scale) - Decimal(10) ** -scale


def _make_tables(engine: Engine, types: dict[str, tuple[int, int]]) -> Values:
    """Core tables named after the real ones, each column at `types`, with values in them.

    Row 1 holds each column's max, row 2 its smallest negative step, row 3 nothing.
    """
    metadata = MetaData()
    for name, columns in _by_table(types).items():
        Table(
            name,
            metadata,
            Column("id", Integer, primary_key=True),
            *(Column(column, Numeric(*types[f"{name}.{column}"])) for column in columns),
        )
    metadata.create_all(engine)
    written: Values = {}
    with engine.begin() as conn:
        for name, table in metadata.tables.items():
            for row_id in (1, 2, 3):
                row: dict[str, Decimal | None] = {}
                for column in _by_table(types)[name]:
                    precision, scale = types[f"{name}.{column}"]
                    row[column] = {
                        1: _largest(precision, scale),
                        2: -(Decimal(10) ** -scale),
                        3: None,
                    }[row_id]
                    written.setdefault(f"{name}.{column}", {})[row_id] = row[column]
                conn.execute(table.insert(), {"id": row_id, **row})
    return written


def _stored(engine: Engine) -> Values:
    """Every value in the 14 columns, read raw so no column type rounds it."""
    stored: Values = {}
    with engine.connect() as conn:
        for name, columns in _by_table(R7_TYPES).items():
            for row in conn.execute(text(f"SELECT id, {', '.join(columns)} FROM {name}")):
                for column, value in zip(columns, row[1:], strict=True):
                    stored.setdefault(f"{name}.{column}", {})[row[0]] = (
                        None if value is None else Decimal(str(value))
                    )
    return stored


def _types(engine: Engine) -> dict[str, tuple[int | None, int | None]]:
    """(precision, scale) of each of the 14 columns, straight from information_schema."""
    found = pg_numeric_types(engine)
    return {qualified: found[qualified][1:] for qualified in R7_TYPES}


@contextmanager
def _alters(engine: Engine) -> Generator[list[str]]:
    """Every ALTER the engine runs inside the block."""
    seen: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if statement.lstrip().upper().startswith("ALTER"):
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_is_fatal() -> None:
    # With the ALTER failed the API takes 4-dp prices and 13-dp quantities the
    # old columns round, so a PG install that skipped this mustn't boot.
    assert _load().FATAL is True


def test_the_list_is_the_r7_columns_at_their_model_types() -> None:
    """Guard: passes once 135 exists. Kills a dropped, extra or mistyped column,
    and a model that moves one of them without a migration."""
    import app.main  # noqa: F401 (registers every model on Base.metadata)
    from app.database import Base

    listed = {
        f"{table}.{column}": target
        for table, columns in _load().COLUMNS.items()
        for column, target in columns.items()
    }
    assert listed == R7_TYPES

    models: dict[str, tuple[int, int]] = {}
    for qualified in R7_TYPES:
        table, column = qualified.split(".", 1)
        kind = Base.metadata.tables[table].c[column].type
        impl = getattr(kind, "impl", kind)
        models[qualified] = (impl.precision, impl.scale)
    assert models == R7_TYPES
    # Every old type fits its new one, so widening never rounds or overflows.
    assert {
        qualified: old
        for qualified, old in PRE_135_TYPES.items()
        if not (
            old[1] <= R7_TYPES[qualified][1]
            and old[0] - old[1] <= R7_TYPES[qualified][0] - R7_TYPES[qualified][1]
        )
    } == {}


@pytest.mark.parametrize(
    ("found", "target", "widens"),
    [
        ((12, 3), (13, 4), True),
        ((4, 1), (5, 2), True),
        ((12, 3), (25, 13), True),
        ((7, 2), (8, 3), True),
        # A narrower column at the same scale is fine too.
        ((10, 4), (13, 4), True),
        # More whole digits than the target holds: a stored value could overflow.
        ((14, 4), (13, 4), False),
        ((5, 1), (5, 2), False),
        # More places than the target: a stored value would round.
        ((13, 5), (13, 4), False),
    ],
    ids=repr,
)
def test_only_a_type_the_target_holds_exactly_is_widened(
    found: tuple[int, int], target: tuple[int, int], widens: bool
) -> None:
    assert _load()._widens(found, target) is widens


def test_widens_every_column_and_keeps_every_value(engine_for_migration: EngineParam) -> None:
    dialect, engine, _url = engine_for_migration
    written = _make_tables(engine, PRE_135_TYPES)
    assert _stored(engine) == written
    if dialect == "pg":
        assert _types(engine) == PRE_135_TYPES, "fixture must start at the old types"

    with _alters(engine) as statements:
        _load().upgrade(engine)

    if dialect == "pg":
        assert _types(engine) == R7_TYPES
        # One statement per table, all six of them.
        assert len(statements) == len(_by_table(R7_TYPES))
    else:
        # SQLite has no ALTER COLUMN at all; trying one would raise.
        assert statements == []
    assert _stored(engine) == written


@pytest.mark.parametrize("engine_for_migration", ["pg"], indirect=True)
def test_a_widened_column_holds_what_the_new_type_allows(
    engine_for_migration: EngineParam,
) -> None:
    """Each new type's max and smallest step go in and come back exact.

    PG only: SQLite's REAL can't hold 25 digits, and its side is 136's job.
    """
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine, PRE_135_TYPES)
    _load().upgrade(engine)

    with engine.begin() as conn:
        for name, columns in _by_table(R7_TYPES).items():
            for column in columns:
                precision, scale = R7_TYPES[f"{name}.{column}"]
                conn.execute(
                    text(f"UPDATE {name} SET {column} = :big WHERE id = 1"),
                    {"big": _largest(precision, scale)},
                )
                conn.execute(
                    text(f"UPDATE {name} SET {column} = :step WHERE id = 2"),
                    {"step": Decimal(10) ** -scale},
                )
    stored = _stored(engine)
    assert {q: stored[q][1] for q in R7_TYPES} == {q: _largest(*t) for q, t in R7_TYPES.items()}
    assert {q: stored[q][2] for q in R7_TYPES} == {
        q: Decimal(10) ** -t[1] for q, t in R7_TYPES.items()
    }


def test_a_second_run_changes_nothing(
    engine_for_migration: EngineParam, caplog: pytest.LogCaptureFixture
) -> None:
    dialect, engine, _url = engine_for_migration
    written = _make_tables(engine, PRE_135_TYPES)
    migration = _load()
    with _alters(engine) as first:
        migration.upgrade(engine)
    # Non-vacuous on PG: the first run did the work.
    assert bool(first) == (dialect == "pg")
    widened = _types(engine) if dialect == "pg" else None

    caplog.clear()
    with caplog.at_level(logging.INFO), _alters(engine) as second:
        migration.upgrade(engine)

    assert second == []
    # Quietly: a column at its type isn't reported as left alone.
    assert "left alone" not in caplog.text
    if dialect == "pg":
        assert _types(engine) == widened
    assert _stored(engine) == written


@pytest.mark.parametrize("engine_for_migration", ["sqlite"], indirect=True)
def test_sqlite_is_a_no_op(engine_for_migration: EngineParam) -> None:
    """Declared types stay as they are: SQLite doesn't enforce them, and has no ALTER COLUMN."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine, PRE_135_TYPES)

    def declared() -> dict[str, str]:
        with engine.connect() as conn:
            return {
                f"{name}.{row[1]}": row[2]
                for name in _by_table(R7_TYPES)
                for row in conn.execute(text(f"PRAGMA table_info({name})"))
            }

    before = declared()
    assert before["fuel_records.price_per_unit"] == "NUMERIC(12, 3)"
    with _alters(engine) as statements:
        _load().upgrade(engine)
    assert statements == []
    assert declared() == before


@pytest.mark.parametrize("engine_for_migration", ["pg"], indirect=True)
def test_leaves_alone_what_it_cannot_widen_safely(
    engine_for_migration: EngineParam, caplog: pytest.LogCaptureFixture
) -> None:
    # More whole digits, unbounded, more places, or a float: each would round
    # or overflow a stored value, so each is named and left. A missing column
    # or table is skipped, not an error.
    _dialect, engine, _url = engine_for_migration
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE fuel_records ("
                " id INTEGER PRIMARY KEY,"
                " price_per_unit NUMERIC(14, 4),"
                " outside_temp_c NUMERIC,"
                " obc_l_per_100km NUMERIC(7, 5),"
                " tank_size_kg DOUBLE PRECISION)"
            )
        )
    before = pg_numeric_types(engine)

    with caplog.at_level(logging.INFO), _alters(engine) as statements:
        _load().upgrade(engine)

    assert statements == []
    assert pg_numeric_types(engine) == before
    assert before["fuel_records.price_per_unit"] == ("numeric", 14, 4)
    assert before["fuel_records.outside_temp_c"] == ("numeric", None, None)
    assert before["fuel_records.obc_l_per_100km"] == ("numeric", 7, 5)
    assert before["fuel_records.tank_size_kg"][0] == "double precision"
    named = {r.getMessage() for r in caplog.records if r.levelno == logging.WARNING}
    for column in ("price_per_unit", "outside_temp_c", "obc_l_per_100km", "tank_size_kg"):
        assert any(f"fuel_records.{column} is" in m for m in named), f"{column} left without a word"


@pytest.mark.parametrize("engine_for_migration", ["pg"], indirect=True)
def test_an_install_from_before_122_ends_at_the_new_types(
    engine_for_migration: EngineParam,
) -> None:
    """122 takes the prices from (6,3) to (12,3), then 135 to (13,4)."""
    _dialect, engine, _url = engine_for_migration
    old = {
        **PRE_135_TYPES,
        "def_records.price_per_unit": PRE_122_TYPES["def_records.price_per_unit"],
        "fuel_records.price_per_unit": PRE_122_TYPES["fuel_records.price_per_unit"],
    }
    assert old["fuel_records.price_per_unit"] == (6, 3)
    written = _make_tables(engine, old)

    _load_named("122_widen_money_columns").upgrade(engine)
    assert _types(engine)["fuel_records.price_per_unit"] == (12, 3)
    _load().upgrade(engine)

    assert _types(engine) == R7_TYPES
    assert _stored(engine) == written


@pytest.mark.parametrize("engine_for_migration", ["pg"], indirect=True)
def test_a_fresh_install_is_already_there(engine_for_migration: EngineParam) -> None:
    """create_all makes the new types; 122 leaves the (13,4) prices alone and 135 has nothing to do."""
    import app.main  # noqa: F401 (registers every model on Base.metadata)
    from app.database import Base

    _dialect, engine, _url = engine_for_migration
    Base.metadata.create_all(engine)
    assert _types(engine) == R7_TYPES

    with _alters(engine) as statements:
        _load_named("122_widen_money_columns").upgrade(engine)
        _load().upgrade(engine)

    assert statements == []
    assert _types(engine) == R7_TYPES


@pytest.fixture
async def app_engine_disposed() -> AsyncIterator[None]:
    """The app engine pools; leave none of its connections behind for other tests."""
    from app import database

    yield
    await database.engine.dispose()


async def test_pg_a_failed_alter_stops_init_db(
    pg_engine: Engine, app_engine_disposed: None
) -> None:
    """A view on a column blocks ALTER TYPE: the run rolls back whole and the app doesn't start."""
    import app.main  # noqa: F401 (registers every model on Base.metadata)
    from app import database
    from app.database import Base

    Base.metadata.create_all(pg_engine)
    with pg_engine.begin() as conn:
        for qualified, (precision, scale) in PRE_135_TYPES.items():
            table, column = qualified.split(".", 1)
            conn.execute(
                text(
                    f"ALTER TABLE {table} ALTER COLUMN {column} TYPE NUMERIC({precision}, {scale})"
                )
            )
        conn.execute(text("CREATE VIEW fuel_prices AS SELECT price_per_unit FROM fuel_records"))
    runner = MigrationRunner(to_sync_url(os.environ["TEST_DATABASE_URL"]), MIGRATIONS)
    try:
        runner._ensure_migration_tracking_table()
        runner._mark_migrations_applied(
            [name for name, _ in runner._discover_migrations() if name != NAME]
        )
    finally:
        runner.engine.dispose()

    with pytest.raises(Exception, match="used by a view") as raised:
        await database.init_db()

    assert getattr(raised.value, "__migration_fatal__", None) is True
    # One transaction: def_records went first and is still at its old type.
    assert _types(pg_engine) == PRE_135_TYPES
    with pg_engine.connect() as conn:
        stamped = conn.execute(
            text("SELECT count(*) FROM schema_migrations WHERE migration_name = :n"), {"n": NAME}
        ).scalar_one()
    assert stamped == 0
