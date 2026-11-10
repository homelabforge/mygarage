"""Tests for migration 121 (financing_records)."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests.migrations._loader import load_migration


def _make_deps(engine):
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(text(f"CREATE TABLE vendors (id {pk}, name VARCHAR(200))"))
        conn.execute(text("INSERT INTO vehicles (vin) VALUES ('1FT0000000000000X')"))
        conn.execute(text("INSERT INTO vendors (name) VALUES ('Test Bank')"))


def test_121_creates_table(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    load_migration("121_add_financing_records").upgrade(engine)

    insp = inspect(engine)
    assert insp.has_table("financing_records")
    cols = {c["name"] for c in insp.get_columns("financing_records")}
    assert {
        "id",
        "vin",
        "vendor_id",
        "date",
        "amount",
        "category",
        "notes",
        "created_at",
        "updated_at",
    } <= cols

    index_cols = {tuple(ix["column_names"]) for ix in insp.get_indexes("financing_records")}
    assert ("vin",) in index_cols
    assert ("date",) in index_cols
    assert ("vendor_id",) in index_cols

    fk_targets = {fk["referred_table"] for fk in insp.get_foreign_keys("financing_records")}
    assert {"vehicles", "vendors"} <= fk_targets


def test_121_category_check_accepts_valid_values(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    load_migration("121_add_financing_records").upgrade(engine)

    with engine.begin() as conn:
        for category in ("lease_payment", "loan_payment", "upfront_fee"):
            conn.execute(
                text(
                    "INSERT INTO financing_records (vin, date, amount, category) "
                    "VALUES (:vin, '2026-01-01', 100.00, :category)"
                ),
                {"vin": "1FT0000000000000X", "category": category},
            )

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM financing_records")).scalar()
    assert count == 3


def test_121_category_check_rejects_invalid_value(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    load_migration("121_add_financing_records").upgrade(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO financing_records (vin, date, amount, category) "
                    "VALUES (:vin, '2026-01-01', 100.00, 'other')"
                ),
                {"vin": "1FT0000000000000X"},
            )


def test_121_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    mod = load_migration("121_add_financing_records")
    mod.upgrade(engine)
    mod.upgrade(engine)
    assert inspect(engine).has_table("financing_records")


def test_121_missing_vehicles_table_skips(engine_for_migration):
    """Skips, without raising, when the vehicles table is absent."""
    _dialect, engine, _url = engine_for_migration
    load_migration("121_add_financing_records").upgrade(engine)
    assert not inspect(engine).has_table("financing_records")


def test_121_model_create_all_matches_migration_shape(engine_for_migration):
    """The ORM-declared table matches the migration DDL: columns, FKs, category CHECK."""
    from app.models.financing import FinancingRecord

    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)

    FinancingRecord.metadata.create_all(
        engine, tables=[FinancingRecord.metadata.tables[FinancingRecord.__tablename__]]
    )

    insp = inspect(engine)
    assert insp.has_table("financing_records")
    cols = {c["name"] for c in insp.get_columns("financing_records")}
    assert {
        "id",
        "vin",
        "vendor_id",
        "date",
        "amount",
        "category",
        "notes",
        "created_at",
        "updated_at",
    } <= cols

    fk_targets = {fk["referred_table"] for fk in insp.get_foreign_keys("financing_records")}
    assert {"vehicles", "vendors"} <= fk_targets

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO financing_records (vin, date, amount, category) "
                    "VALUES (:vin, '2026-01-01', 100.00, 'other')"
                ),
                {"vin": "1FT0000000000000X"},
            )
