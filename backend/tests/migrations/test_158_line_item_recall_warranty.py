"""Migration 158: recall and warranty flags and links on service_line_items.

Two NOT NULL booleans defaulting false, two nullable FKs with ON DELETE SET
NULL, one item per recall (partial unique index), and recalls.resolved_via.
The FK behaviour is checked by deleting the target, not by reflection: SQLite's
inspector reports an ADD COLUMN FK with empty options. Parameterised over
SQLite and PostgreSQL via `engine_for_migration`.
"""

import importlib
import importlib.util
import types
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, MetaData, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.migrations as _m

pytestmark = pytest.mark.migrations

_NAME = "158_line_item_recall_warranty"
_ITEMS = "service_line_items"
_UNIQUE = "uq_line_items_recall_id"
_WARRANTY_INDEX = "ix_line_items_warranty_id"
_VIN = "1HGCM82633A004352"


def _load(name: str = _NAME) -> types.ModuleType:
    """Load a migration module by file, as the runner does."""
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _metadata() -> MetaData:
    """Every model registered, so create_all builds the whole schema the FKs need."""
    import app.models as models_pkg

    for py in sorted(Path(models_pkg.__file__).parent.glob("*.py")):
        if py.stem != "__init__":
            importlib.import_module(f"app.models.{py.stem}")
    from app.database import Base

    return Base.metadata


@contextmanager
def _fk_conn(engine: Engine) -> Generator[Connection]:
    """A connection that enforces FKs, committed on exit.

    SQLite ships with FK enforcement off per connection, and the app turns it
    on the same way. PG always enforces.
    """
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        yield conn
        conn.commit()


def _make_157(engine: Engine) -> None:
    """The three tables as 157 leaves them (the columns 158 cares about), one row each."""
    pk = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE recalls (id {pk}, vin VARCHAR(17) NOT NULL, "
                "is_resolved BOOLEAN, resolved_at TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                f"CREATE TABLE warranty_records (id {pk}, vin VARCHAR(17) NOT NULL, "
                "warranty_type VARCHAR(50) NOT NULL)"
            )
        )
        conn.execute(
            text(
                f"CREATE TABLE {_ITEMS} (id {pk}, description VARCHAR(200) NOT NULL, "
                "is_inspection BOOLEAN)"
            )
        )
        conn.execute(
            text("INSERT INTO recalls (vin, is_resolved) VALUES (:vin, :f), (:vin, :f)"),
            {"vin": _VIN, "f": False},
        )
        conn.execute(
            text("INSERT INTO warranty_records (vin, warranty_type) VALUES (:vin, 'Powertrain')"),
            {"vin": _VIN},
        )
        conn.execute(
            text(f"INSERT INTO {_ITEMS} (description, is_inspection) VALUES ('a', :f), ('b', :f)"),
            {"f": False},
        )


def _ids(engine: Engine, table: str) -> list[int]:
    with engine.begin() as conn:
        return list(conn.execute(text(f"SELECT id FROM {table} ORDER BY id")).scalars())


def test_158_adds_the_columns_old_rows_read_false_and_null(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_157(engine)
    _load().upgrade(engine)

    cols = {c["name"]: c for c in inspect(engine).get_columns(_ITEMS)}
    assert cols["is_recall"]["nullable"] is False
    assert cols["is_warranty"]["nullable"] is False
    assert cols["recall_id"]["nullable"] is True
    assert cols["warranty_id"]["nullable"] is True
    with engine.begin() as conn:
        rows = conn.execute(
            text(f"SELECT is_recall, recall_id, is_warranty, warranty_id FROM {_ITEMS}")
        ).all()
    assert [tuple(r) for r in rows] == [(False, None, False, None)] * 2

    recall_cols = {c["name"]: c for c in inspect(engine).get_columns("recalls")}
    assert recall_cols["resolved_via"]["nullable"] is True
    assert getattr(recall_cols["resolved_via"]["type"], "length", None) == 20
    with engine.begin() as conn:
        assert conn.execute(text("SELECT resolved_via FROM recalls")).scalars().all() == [
            None,
            None,
        ]


def test_158_a_new_row_without_the_flags_reads_false(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    """The NOT NULL booleans carry a server default, so a raw insert still works."""
    _dialect, engine, _url = engine_for_migration
    _make_157(engine)
    _load().upgrade(engine)
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO {_ITEMS} (description) VALUES ('c')"))
        row = conn.execute(
            text(f"SELECT is_recall, is_warranty FROM {_ITEMS} WHERE description = 'c'")
        ).one()
    assert tuple(row) == (False, False)


def test_158_builds_both_indexes(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_157(engine)
    _load().upgrade(engine)
    indexes = {i["name"]: i for i in inspect(engine).get_indexes(_ITEMS)}
    assert indexes[_UNIQUE]["unique"]
    assert indexes[_UNIQUE]["column_names"] == ["recall_id"]
    assert not indexes[_WARRANTY_INDEX]["unique"]
    assert indexes[_WARRANTY_INDEX]["column_names"] == ["warranty_id"]


def test_158_is_idempotent(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_157(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)  # must not raise "duplicate column"
    insp = inspect(engine)
    names = [c["name"] for c in insp.get_columns(_ITEMS)]
    for name in ("is_recall", "recall_id", "is_warranty", "warranty_id"):
        assert names.count(name) == 1, name
    assert [c["name"] for c in insp.get_columns("recalls")].count("resolved_via") == 1
    fk_cols = [tuple(fk["constrained_columns"]) for fk in insp.get_foreign_keys(_ITEMS)]
    assert sorted(fk_cols) == [("recall_id",), ("warranty_id",)]


def test_158_deleting_a_linked_recall_nulls_the_link(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_157(engine)
    _load().upgrade(engine)
    recall_id = _ids(engine, "recalls")[0]
    item_id = _ids(engine, _ITEMS)[0]
    with _fk_conn(engine) as conn:
        conn.execute(
            text(f"UPDATE {_ITEMS} SET is_recall = :t, recall_id = :r WHERE id = :i"),
            {"t": True, "r": recall_id, "i": item_id},
        )
    with _fk_conn(engine) as conn:
        conn.execute(text("DELETE FROM recalls WHERE id = :r"), {"r": recall_id})
    with engine.begin() as conn:
        row = conn.execute(
            text(f"SELECT is_recall, recall_id FROM {_ITEMS} WHERE id = :i"), {"i": item_id}
        ).one()
    # The flag stays: the work was still recall work (D8).
    assert tuple(row) == (True, None)


def test_158_deleting_a_linked_warranty_nulls_the_link(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_157(engine)
    _load().upgrade(engine)
    warranty_id = _ids(engine, "warranty_records")[0]
    item_id = _ids(engine, _ITEMS)[0]
    with _fk_conn(engine) as conn:
        conn.execute(
            text(f"UPDATE {_ITEMS} SET is_warranty = :t, warranty_id = :w WHERE id = :i"),
            {"t": True, "w": warranty_id, "i": item_id},
        )
    with _fk_conn(engine) as conn:
        conn.execute(text("DELETE FROM warranty_records WHERE id = :w"), {"w": warranty_id})
    with engine.begin() as conn:
        row = conn.execute(
            text(f"SELECT is_warranty, warranty_id FROM {_ITEMS} WHERE id = :i"), {"i": item_id}
        ).one()
    assert tuple(row) == (True, None)


def test_158_two_items_cannot_link_one_recall(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_157(engine)
    _load().upgrade(engine)
    recall_id = _ids(engine, "recalls")[0]
    first, second = _ids(engine, _ITEMS)
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE {_ITEMS} SET recall_id = :r WHERE id = :i"), {"r": recall_id, "i": first}
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(f"UPDATE {_ITEMS} SET recall_id = :r WHERE id = :i"),
            {"r": recall_id, "i": second},
        )


def test_158_many_items_can_have_no_recall(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    """The unique index is partial: NULL links never collide."""
    _dialect, engine, _url = engine_for_migration
    _make_157(engine)
    _load().upgrade(engine)
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO {_ITEMS} (description) VALUES ('c'), ('d')"))
        nulls = conn.execute(
            text(f"SELECT COUNT(*) FROM {_ITEMS} WHERE recall_id IS NULL")
        ).scalar()
    assert nulls == 4


def test_158_pg_adds_a_missing_fk_to_an_existing_column(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    """A recall_id column without its FK (a half-applied run) gets the FK, once."""
    dialect, engine, _url = engine_for_migration
    if dialect != "pg":
        pytest.skip("SQLite can't add an FK to an existing column without a table rebuild")
    _make_157(engine)
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {_ITEMS} ADD COLUMN recall_id INTEGER"))
    _load().upgrade(engine)
    fk_cols = [tuple(fk["constrained_columns"]) for fk in inspect(engine).get_foreign_keys(_ITEMS)]
    assert fk_cols.count(("recall_id",)) == 1
    recall_id = _ids(engine, "recalls")[0]
    item_id = _ids(engine, _ITEMS)[0]
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE {_ITEMS} SET recall_id = :r WHERE id = :i"),
            {"r": recall_id, "i": item_id},
        )
        conn.execute(text("DELETE FROM recalls WHERE id = :r"), {"r": recall_id})
        assert (
            conn.execute(
                text(f"SELECT recall_id FROM {_ITEMS} WHERE id = :i"), {"i": item_id}
            ).scalar()
            is None
        )


def test_158_on_a_fresh_create_all_schema_is_a_no_op(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    insp = inspect(engine)
    before_cols = [c["name"] for c in insp.get_columns(_ITEMS)]
    before_fks = sorted(tuple(fk["constrained_columns"]) for fk in insp.get_foreign_keys(_ITEMS))
    before_idx = sorted(str(i["name"]) for i in insp.get_indexes(_ITEMS))
    assert {"is_recall", "recall_id", "is_warranty", "warranty_id"} <= set(before_cols)
    assert {_UNIQUE, _WARRANTY_INDEX} <= set(before_idx)
    _load().upgrade(engine)
    insp = inspect(engine)
    assert [c["name"] for c in insp.get_columns(_ITEMS)] == before_cols
    # No second FK on PG: the guard matches by column, not name.
    assert sorted(tuple(fk["constrained_columns"]) for fk in insp.get_foreign_keys(_ITEMS)) == (
        before_fks
    )
    assert sorted(str(i["name"]) for i in insp.get_indexes(_ITEMS)) == before_idx


def test_create_all_matches_the_migration(engine_for_migration: tuple[str, Engine, str]) -> None:
    """The model builds what 158 builds: server-side false defaults, the partial
    unique index and SET NULL on delete. Parity can't see these, because DB-B
    runs create_all first.
    """
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    from app.models.recall import Recall
    from app.models.service_visit import ServiceVisit
    from app.models.vehicle import Vehicle

    with _fk_conn(engine) as conn:
        # The parents through the ORM: vehicles has NOT NULL columns with
        # Python-side defaults only.
        session = Session(bind=conn)
        visit = ServiceVisit(vin=_VIN, date=date(2026, 3, 1))
        recall = Recall(vin=_VIN, source="manual")
        session.add_all([Vehicle(vin=_VIN, nickname="Car", vehicle_type="Car"), visit, recall])
        session.flush()
        visit_id, recall_id = visit.id, recall.id
        # No is_recall / is_warranty: the server default has to fill them.
        conn.execute(
            text(
                f"INSERT INTO {_ITEMS} (visit_id, description, is_inspection) "
                "VALUES (:v, 'a', :f), (:v, 'b', :f)"
            ),
            {"v": visit_id, "f": False},
        )
        flags = conn.execute(text(f"SELECT is_recall, is_warranty FROM {_ITEMS}")).all()
        assert [tuple(r) for r in flags] == [(False, False)] * 2
        first, second = conn.execute(text(f"SELECT id FROM {_ITEMS} ORDER BY id")).scalars()
        conn.execute(
            text(f"UPDATE {_ITEMS} SET recall_id = :r WHERE id = :i"), {"r": recall_id, "i": first}
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(f"UPDATE {_ITEMS} SET recall_id = :r WHERE id = :i"),
            {"r": recall_id, "i": second},
        )
    with _fk_conn(engine) as conn:
        conn.execute(text("DELETE FROM recalls WHERE id = :r"), {"r": recall_id})
        assert (
            conn.execute(
                text(f"SELECT recall_id FROM {_ITEMS} WHERE id = :i"), {"i": first}
            ).scalar()
            is None
        )


def test_158_missing_table_skips(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table(_ITEMS)
    assert not inspect(engine).has_table("recalls")


def test_158_is_fatal() -> None:
    assert _load().FATAL is True
