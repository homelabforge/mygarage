import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "app" / "migrations"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, MIGRATIONS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_attachments(engine):
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if is_pg else "DATETIME"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""CREATE TABLE attachments (
                    id {pk},
                    record_type VARCHAR(30) NOT NULL,
                    record_id INTEGER NOT NULL,
                    file_path VARCHAR(255) NOT NULL,
                    file_type VARCHAR(10),
                    file_size INTEGER,
                    uploaded_at {ts} DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT check_record_type CHECK (record_type IN
                        ('service', 'service_visit', 'fuel', 'upgrade', 'collision', 'tax', 'note'))
                )"""
            )
        )
        conn.execute(
            text("CREATE INDEX idx_attachments_record ON attachments(record_type, record_id)")
        )


def test_077_allows_supply_purchase(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_attachments(engine)
    # Before: the new type is rejected.
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO attachments (record_type, record_id, file_path) "
                    "VALUES ('supply_purchase', 1, 'x')"
                )
            )
    _load("077_attachment_supply_purchase_type").upgrade(engine)
    # After: accepted, and the old types still work.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO attachments (record_type, record_id, file_path) "
                "VALUES ('supply_purchase', 1, 'r.pdf')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO attachments (record_type, record_id, file_path) "
                "VALUES ('service_visit', 2, 's.pdf')"
            )
        )


def test_077_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_attachments(engine)
    mod = _load("077_attachment_supply_purchase_type")
    mod.upgrade(engine)
    mod.upgrade(engine)  # must not raise


def test_077_widens_file_type_for_mime(engine_for_migration):
    """After upgrade, a full MIME string fits file_type — the PG-visible fix for R1-H2."""
    from sqlalchemy import inspect

    _dialect, engine, _url = engine_for_migration
    _make_attachments(engine)  # starts at VARCHAR(10)
    _load("077_attachment_supply_purchase_type").upgrade(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO attachments (record_type, record_id, file_path, file_type) "
                "VALUES ('supply_purchase', 1, 'r.pdf', 'application/octet-stream')"
            )
        )
    col = {c["name"]: c for c in inspect(engine).get_columns("attachments")}["file_type"]
    # SQLite reports length loosely; on PG the declared length is now 50.
    if engine.dialect.name == "postgresql":
        assert col["type"].length == 50


def test_077_one_receipt_per_purchase(engine_for_migration):
    """R1-H4: the partial unique index rejects a second receipt for the same purchase,
    but still allows a different record_type to reuse the same record_id."""
    _dialect, engine, _url = engine_for_migration
    _make_attachments(engine)
    _load("077_attachment_supply_purchase_type").upgrade(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO attachments (record_type, record_id, file_path) "
                "VALUES ('supply_purchase', 7, 'a.pdf')"
            )
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO attachments (record_type, record_id, file_path) "
                    "VALUES ('supply_purchase', 7, 'b.pdf')"
                )
            )
    with engine.begin() as conn:  # scoped index: other record types unaffected
        conn.execute(
            text(
                "INSERT INTO attachments (record_type, record_id, file_path) "
                "VALUES ('service_visit', 7, 'c.pdf')"
            )
        )
