"""Migration 162: supply_usages.cost_estimated, NOT NULL default false (#307).

Column only; 163 does the pricing. FATAL, because the model maps it NOT NULL
and every usage SELECT reads it. Parameterised over SQLite and PostgreSQL via
`engine_for_migration`.
"""

import importlib
from pathlib import Path

import pytest
from sqlalchemy import Engine, MetaData, inspect, text
from sqlalchemy.engine.interfaces import ReflectedColumn

from tests.migrations._loader import load_migration

pytestmark = pytest.mark.migrations

_NAME = "162_add_supply_usage_cost_estimated"
_TABLE = "supply_usages"
_COLUMN = "cost_estimated"


def _load():
    return load_migration(_NAME)


def _metadata() -> MetaData:
    """Every model registered, so create_all builds the whole schema the FKs need."""
    import app.models as models_pkg

    for py in sorted(Path(models_pkg.__file__).parent.glob("*.py")):
        if py.stem != "__init__":
            importlib.import_module(f"app.models.{py.stem}")
    from app.database import Base

    return Base.metadata


def _make_161_usages(engine: Engine) -> None:
    """supply_usages as 161 leaves it (the columns 162 cares about), with two rows."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE supply_usages (id INTEGER PRIMARY KEY, supply_id INTEGER NOT NULL, "
                "quantity NUMERIC(25, 13) NOT NULL, unit_cost_snapshot NUMERIC(15, 4), "
                "cost_snapshot NUMERIC(12, 2))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO supply_usages (id, supply_id, quantity, cost_snapshot) "
                "VALUES (1, 1, 5, 37.45), (2, 1, 1, NULL)"
            )
        )


def _columns(engine: Engine) -> dict[str, ReflectedColumn]:
    return {c["name"]: c for c in inspect(engine).get_columns(_TABLE)}


def _default(column: ReflectedColumn) -> str | None:
    """A reflected server default, normalised the way test_schema_parity does."""
    value = column.get("default")
    return None if value is None else str(value).upper().strip()


def test_162_adds_the_column_and_old_rows_read_false(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_161_usages(engine)
    _load().upgrade(engine)

    assert _columns(engine)[_COLUMN]["nullable"] is False
    with engine.begin() as conn:
        rows = conn.execute(text(f"SELECT {_COLUMN} FROM {_TABLE} ORDER BY id")).scalars().all()
    assert rows == [False, False]


def test_162_a_new_row_without_the_flag_reads_false(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    """The column carries a server default, so a raw insert still works."""
    _dialect, engine, _url = engine_for_migration
    _make_161_usages(engine)
    _load().upgrade(engine)
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO {_TABLE} (id, supply_id, quantity) VALUES (3, 1, 2)"))
        flag = conn.execute(text(f"SELECT {_COLUMN} FROM {_TABLE} WHERE id = 3")).scalar_one()
    # SQLite hands back 0 to a raw SELECT, PG False; both equal False.
    assert [flag] == [False]


def test_create_all_matches_the_migration(engine_for_migration: tuple[str, Engine, str]) -> None:
    """The model's column and 162's agree on type, nullability and server default.

    test_schema_parity can't see this: its migrated database runs create_all
    first, so 162 finds the column there and adds nothing.
    """
    _dialect, engine, _url = engine_for_migration
    _make_161_usages(engine)
    _load().upgrade(engine)
    migrated = _columns(engine)[_COLUMN]

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE {_TABLE}"))
    _metadata().create_all(engine)
    built = _columns(engine)[_COLUMN]

    assert _default(migrated) == _default(built)
    assert _default(built) is not None
    assert str(migrated["type"]).upper() == str(built["type"]).upper()
    assert migrated["nullable"] is built["nullable"] is False


def test_162_is_idempotent(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_161_usages(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)  # must not raise "duplicate column"
    names = [c["name"] for c in inspect(engine).get_columns(_TABLE)]
    assert names.count(_COLUMN) == 1


def test_162_on_a_fresh_create_all_schema_is_a_no_op(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    before = [c["name"] for c in inspect(engine).get_columns(_TABLE)]
    assert _COLUMN in before
    _load().upgrade(engine)
    assert [c["name"] for c in inspect(engine).get_columns(_TABLE)] == before


def test_162_missing_table_skips(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table(_TABLE)


def test_162_is_fatal() -> None:
    assert _load().FATAL is True
