"""Migration 148: recall sources (#211).

Four columns, a backfill of the NHTSA identifiers, an index. FATAL, because
the ORM declares the columns. Parameterised over SQLite and PostgreSQL via
`engine_for_migration`.
"""

import importlib.util
import sqlite3
from pathlib import Path

from sqlalchemy import inspect, text

import app.migrations as _m

_NAME = "148_recall_sources"
_COLUMNS = ("source", "external_id", "external_url", "match_confidence")


def _load(name: str = _NAME):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_tables(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, nickname VARCHAR(100))")
        )
        conn.execute(
            text(
                "CREATE TABLE recalls (id INTEGER PRIMARY KEY, vin VARCHAR(17) NOT NULL "
                "REFERENCES vehicles(vin), nhtsa_campaign_number VARCHAR(20), "
                "component VARCHAR(100), summary TEXT, is_resolved BOOLEAN DEFAULT FALSE)"
            )
        )
        conn.execute(text("INSERT INTO vehicles (vin, nickname) VALUES ('1HGCM82633A004352', 'A')"))
        conn.execute(
            text(
                "INSERT INTO recalls (id, vin, nhtsa_campaign_number, component, summary) VALUES "
                "(1, '1HGCM82633A004352', '24V001', 'Airbag', 'x'), "
                "(2, '1HGCM82633A004352', NULL, 'Typed', 'y')"
            )
        )


def test_148_adds_the_columns_backfills_and_indexes(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _load().upgrade(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("recalls")}
    for name in _COLUMNS:
        assert name in cols, name
    assert cols["source"]["nullable"] is False
    assert cols["external_id"]["nullable"] is True
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, source, external_id, external_url, match_confidence FROM recalls ORDER BY id"
            )
        ).all()
    # Every existing row is NHTSA's; the campaign number becomes the identifier.
    assert rows == [(1, "nhtsa", "24V001", None, None), (2, "nhtsa", None, None, None)]
    names = {index["name"] for index in inspect(engine).get_indexes("recalls")}
    assert "idx_recalls_source_external" in names


def test_148_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    names = [c["name"] for c in inspect(engine).get_columns("recalls")]
    for name in _COLUMNS:
        assert names.count(name) == 1
    assert [i["name"] for i in inspect(engine).get_indexes("recalls")].count(
        "idx_recalls_source_external"
    ) == 1


def test_148_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("recalls")


def test_148_is_fatal():
    assert _load().FATAL is True


def test_148_sqlite_declares_types(tmp_path: Path, sync_engine) -> None:
    db_file = tmp_path / "m148.db"
    engine = sync_engine(f"sqlite:///{db_file}")
    _make_tables(engine)
    _load().upgrade(engine)
    conn = sqlite3.connect(str(db_file))
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(recalls)")}
    conn.close()
    assert cols["source"][2].upper() == "VARCHAR(20)"
    assert cols["source"][3] == 1  # NOT NULL
    assert cols["source"][4] == "'nhtsa'"
    assert cols["external_url"][2].upper() == "VARCHAR(500)"
