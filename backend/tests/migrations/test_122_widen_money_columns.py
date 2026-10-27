"""Migration 122: every money column widened to its policy type on PostgreSQL.

The tables are built by hand at their pre-122 types, with a value in every
column. A create_all baseline starts at the new types, so the ALTERs would never
run (Codex R1-F1). SQLite ignores declared precision, so there the migration
must do nothing, and the check is that every value comes through untouched.
"""

import importlib.util
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import Column, Engine, Float, Integer, MetaData, Numeric, Table, event, select, text

import app.migrations as _m
from app.schemas._money import MONEY_MAX, UNIT_COST_MAX
from tests.migrations._money_columns import PRE_122_TYPES, TYPES_AT_122, pg_numeric_types
from tests.unit.schemas._money_names import MONEY_TYPE, UNIT_COST_TYPE

pytestmark = pytest.mark.migrations

NAME = "122_widen_money_columns"
#: The largest value of each type 122 widens to. Its unit price is (12,3).
POLICY_MAX = {
    MONEY_TYPE: MONEY_MAX,
    (12, 3): Decimal("999999999.999"),
    UNIT_COST_TYPE: UNIT_COST_MAX,
}

type Values = dict[str, dict[int, Decimal | None]]
#: What the engine_for_migration fixture yields: (dialect, engine, url).
type EngineParam = tuple[str, Engine, str]


def _load() -> ModuleType:
    """Load the migration module by file, as the runner does."""
    path = Path(_m.__file__).parent / f"{NAME}.py"
    spec = importlib.util.spec_from_file_location(NAME, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _by_table(columns: Iterable[str]) -> dict[str, list[str]]:
    """table -> its column names, from table.column names."""
    tables: dict[str, list[str]] = {}
    for qualified in sorted(columns):
        table, column = qualified.split(".", 1)
        tables.setdefault(table, []).append(column)
    return tables


def _largest(precision: int, scale: int) -> Decimal:
    """The largest value a NUMERIC(precision, scale) holds: every digit a 9."""
    return Decimal(10) ** (precision - scale) - Decimal(10) ** -scale


def _smallest(_precision: int, scale: int) -> Decimal:
    """The smallest step a NUMERIC(_, scale) holds."""
    return Decimal(10) ** -scale


def _tables(types: dict[str, tuple[int, int]]) -> MetaData:
    """Core tables named after the real ones, each column at the given type."""
    metadata = MetaData()
    for name, columns in _by_table(types).items():
        Table(
            name,
            metadata,
            Column("id", Integer, primary_key=True),
            *(Column(column, Numeric(*types[f"{name}.{column}"])) for column in columns),
        )
    return metadata


def _make_pre_122_tables(engine: Engine) -> Values:
    """Every column the migration widens, at its old type, with values in it.

    Row 1 holds each column's old max, row 2 its smallest step, row 3 nothing.
    Returns what was written.
    """
    written: Values = {}
    metadata = _tables(PRE_122_TYPES)
    metadata.create_all(engine)
    pick: dict[int, Callable[[int, int], Decimal | None]] = {
        1: _largest,
        2: _smallest,
        3: lambda _p, _s: None,
    }
    with engine.begin() as conn:
        for name, table in metadata.tables.items():
            for row_id, value_of in pick.items():
                row: dict[str, Any] = {
                    column: value_of(*PRE_122_TYPES[f"{name}.{column}"])
                    for column in table.columns.keys()
                    if column != "id"
                }
                conn.execute(table.insert(), {"id": row_id, **row})
                for column, value in row.items():
                    written.setdefault(f"{name}.{column}", {})[row_id] = value
    return written


def _stored(engine: Engine) -> Values:
    """Every value in the widened columns, read raw so no column type rounds it."""
    stored: Values = {}
    with engine.connect() as conn:
        for name, columns in _by_table(PRE_122_TYPES).items():
            rows = conn.execute(text(f"SELECT id, {', '.join(columns)} FROM {name}")).all()
            for row in rows:
                for column, value in zip(columns, row[1:], strict=True):
                    stored.setdefault(f"{name}.{column}", {})[row[0]] = (
                        None if value is None else Decimal(str(value))
                    )
    return stored


def _types(engine: Engine) -> dict[str, tuple[int | None, int | None]]:
    """(precision, scale) of every column the migration widens, on PostgreSQL."""
    found = pg_numeric_types(engine)
    return {qualified: found[qualified][1:] for qualified in PRE_122_TYPES}


@contextmanager
def _alters(engine: Engine) -> Generator[list[str]]:
    """Every ALTER statement the engine runs inside the block."""
    seen: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if statement.lstrip().upper().startswith("ALTER"):
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_is_fatal():
    # The models declare the new widths, so a PG install that skipped this
    # would 500 on the first amount past the old ones.
    assert _load().FATAL is True


def test_the_list_is_every_registered_column_that_was_narrower():
    listed = {
        f"{table}.{column}": target
        for table, columns in _load().COLUMNS.items()
        for column, target in columns.items()
    }
    assert listed == {qualified: TYPES_AT_122[qualified] for qualified in PRE_122_TYPES}
    # The rest of the registry was already at its type before 122.
    assert sorted(TYPES_AT_122.keys() - listed.keys()) == [
        "insurance_coverages.limit_primary",
        "insurance_coverages.limit_secondary",
    ]
    # Every old type is a narrower one at the same scale, so widening never rounds.
    assert {
        qualified: old
        for qualified, old in PRE_122_TYPES.items()
        if not (old[1] == listed[qualified][1] and old[0] < listed[qualified][0])
    } == {}


@pytest.mark.parametrize(
    ("column_type", "expected"),
    [
        (Numeric(12, 2), (12, 2)),
        (Numeric(8, 2), (8, 2)),
        (Numeric(), None),
        # PG always reports both or neither; a half-bounded type is still no answer.
        (Numeric(precision=12), None),
        (Numeric(scale=2), None),
        (Float(), None),
        (Float(precision=53), None),
        (Integer(), None),
    ],
    ids=repr,
)
def test_only_a_bounded_numeric_has_a_width(column_type: Any, expected: tuple[int, int] | None):
    assert _load()._numeric(column_type) == expected


def test_widens_every_column_and_keeps_every_value(engine_for_migration: EngineParam):
    dialect, engine, _url = engine_for_migration
    written = _make_pre_122_tables(engine)
    assert _stored(engine) == written
    if dialect == "pg":
        assert _types(engine) == PRE_122_TYPES, "fixture must start in the PRE state"

    _load().upgrade(engine)

    if dialect == "pg":
        assert _types(engine) == {qualified: TYPES_AT_122[qualified] for qualified in PRE_122_TYPES}
    assert _stored(engine) == written


def test_a_widened_column_holds_its_policy_max(engine_for_migration: EngineParam):
    # The boundary round trip: each type's max goes in and comes back exact,
    # written and read through the policy types, the way the models do it.
    _dialect, engine, _url = engine_for_migration
    _make_pre_122_tables(engine)
    _load().upgrade(engine)

    policy = {qualified: TYPES_AT_122[qualified] for qualified in PRE_122_TYPES}
    maxima = {qualified: POLICY_MAX[target] for qualified, target in policy.items()}
    tables = _tables(policy).tables
    with engine.begin() as conn:
        for name, table in tables.items():
            conn.execute(
                table.update().where(table.c.id == 1),
                {column: maxima[f"{name}.{column}"] for column in _by_table(policy)[name]},
            )
    read: dict[str, Decimal] = {}
    with engine.connect() as conn:
        for name, table in tables.items():
            row = conn.execute(select(table).where(table.c.id == 1)).mappings().one()
            for column in _by_table(policy)[name]:
                read[f"{name}.{column}"] = row[column]
    assert read == maxima


def test_a_second_run_changes_nothing(
    engine_for_migration: EngineParam, capsys: pytest.CaptureFixture[str]
):
    dialect, engine, _url = engine_for_migration
    written = _make_pre_122_tables(engine)
    migration = _load()
    with _alters(engine) as first:
        migration.upgrade(engine)
    widened = _types(engine) if dialect == "pg" else None
    # Non-vacuous on PG: the first run did the work.
    assert bool(first) == (dialect == "pg")

    capsys.readouterr()
    with _alters(engine) as second:
        migration.upgrade(engine)

    assert second == []
    # And quietly: a column already at its type isn't reported as left alone.
    assert "left alone" not in capsys.readouterr().out
    if dialect == "pg":
        assert _types(engine) == widened
    assert _stored(engine) == written


@pytest.mark.parametrize("engine_for_migration", ["pg"], indirect=True)
def test_leaves_alone_what_it_cannot_widen_safely(
    engine_for_migration: EngineParam, capsys: pytest.CaptureFixture[str]
):
    # Only a bounded NUMERIC narrower than its target at the same scale is
    # altered. A wider one would be narrowed, and another scale or a float could
    # round. A missing column or table is skipped, not an error.
    _dialect, engine, _url = engine_for_migration
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE vehicles ("
                " vin VARCHAR(17) PRIMARY KEY,"
                " purchase_price NUMERIC(14, 2),"
                " sold_price NUMERIC,"
                " msrp_base NUMERIC(10, 4),"
                " msrp_options DOUBLE PRECISION)"
            )
        )
    before = pg_numeric_types(engine)

    with _alters(engine) as statements:
        _load().upgrade(engine)

    assert statements == []
    assert pg_numeric_types(engine) == before
    assert before["vehicles.purchase_price"] == ("numeric", 14, 2)
    assert before["vehicles.sold_price"] == ("numeric", None, None)
    assert before["vehicles.msrp_base"] == ("numeric", 10, 4)
    assert before["vehicles.msrp_options"][0] == "double precision"
    out = capsys.readouterr().out
    for column in ("purchase_price", "sold_price", "msrp_base", "msrp_options"):
        assert f"vehicles.{column}" in out, f"{column} left alone without a word"
