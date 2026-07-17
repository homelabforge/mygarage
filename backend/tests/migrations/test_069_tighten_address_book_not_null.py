"""Tests for migration 069 (tighten address_book NOT NULL constraints).

Migration 069 tightens the four historically under-constrained address_book
columns — ``source``, ``usage_count``, ``created_at``, ``updated_at`` — to
NOT NULL. On PostgreSQL this is a backfill + ``ALTER COLUMN ... SET NOT NULL``;
on SQLite it is an FK-safe table rebuild (mirroring migration 053) because
``fuel_records.station_address_book_id`` holds an inbound FK
(``ON DELETE SET NULL``) and a naive DROP under FK enforcement would null it.

Three tests:
  1. NOT NULL + backfill + indexes-survive + idempotent (both dialects).
  2. Full-column value preservation — a 24-column sentinel row survives the
     rebuild value-for-value, including ``id`` (both dialects).
  3. Inbound-FK preservation — a ``fuel_records`` row referencing
     ``address_book(id=1)`` under ``PRAGMA foreign_keys=ON`` keeps its FK
     value AND ``PRAGMA foreign_key_check`` stays empty (SQLite only).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import event, inspect, text

import app.migrations as _m

MIGRATION = "069_tighten_address_book_not_null"
_TARGETS = ("source", "usage_count", "created_at", "updated_at")

# Full model column set, in model order. The SQLite rebuild reproduces this
# exactly; the sentinel/before-after compare selects it explicitly so a
# reordering rebuild can't hide a value swap.
_ALL_COLUMNS = (
    "id",
    "business_name",
    "name",
    "address",
    "city",
    "state",
    "zip_code",
    "phone",
    "email",
    "website",
    "category",
    "notes",
    "latitude",
    "longitude",
    "source",
    "external_id",
    "rating",
    "user_rating",
    "usage_count",
    "last_used",
    "poi_category",
    "poi_metadata",
    "created_at",
    "updated_at",
)


def _load(name: str):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _create_under_constrained(engine, dialect: str) -> None:
    """Create address_book in migration 025's under-constrained shape.

    All 24 model columns are present, but the four targets are NULLABLE (no
    NOT NULL) — exactly the drift 069 repairs. The three model indexes are
    created so the test can assert they survive the rebuild.
    """
    id_type = "SERIAL PRIMARY KEY" if dialect == "pg" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    dt_type = "TIMESTAMP" if dialect == "pg" else "DATETIME"
    ddl = f"""
        CREATE TABLE address_book (
            id            {id_type},
            business_name VARCHAR(150) NOT NULL,
            name          VARCHAR(100),
            address       TEXT,
            city          VARCHAR(100),
            state         VARCHAR(50),
            zip_code      VARCHAR(20),
            phone         VARCHAR(20),
            email         VARCHAR(100),
            website       VARCHAR(200),
            category      VARCHAR(50),
            notes         TEXT,
            latitude      NUMERIC(10,8),
            longitude     NUMERIC(11,8),
            source        VARCHAR(20) DEFAULT 'manual',
            external_id   VARCHAR(100),
            rating        NUMERIC(3,2),
            user_rating   INTEGER,
            usage_count   INTEGER DEFAULT 0,
            last_used     {dt_type},
            poi_category  VARCHAR(50),
            poi_metadata  TEXT,
            created_at    {dt_type} DEFAULT CURRENT_TIMESTAMP,
            updated_at    {dt_type} DEFAULT CURRENT_TIMESTAMP
        )
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))
        conn.execute(text("CREATE INDEX idx_address_book_name ON address_book(name)"))
        conn.execute(text("CREATE INDEX idx_address_book_category ON address_book(category)"))
        conn.execute(
            text("CREATE INDEX idx_address_book_poi_category ON address_book(poi_category)")
        )


def test_069_notnull_backfill_indexes_idempotent(engine_for_migration) -> None:
    """NOT NULL is enforced, NULLs are backfilled, indexes survive, idempotent."""
    dialect, engine, _url = engine_for_migration
    _create_under_constrained(engine, dialect)

    # Row A: every target NULL -> must be backfilled. Row B: all set -> untouched.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO address_book "
                "(id, business_name, source, usage_count, created_at, updated_at) "
                "VALUES (1, 'Needs Backfill', NULL, NULL, NULL, NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO address_book "
                "(id, business_name, source, usage_count, created_at, updated_at) "
                "VALUES (2, 'Already Set', 'google_places', 9, "
                "'2020-01-01 00:00:00', '2020-01-02 00:00:00')"
            )
        )

    _load(MIGRATION).upgrade(engine=engine)

    cols = {c["name"]: c for c in inspect(engine).get_columns("address_book")}
    for name in _TARGETS:
        assert cols[name]["nullable"] is False, f"{name} should be NOT NULL after 069"

    with engine.connect() as conn:
        a = conn.execute(
            text(
                "SELECT source, usage_count, created_at, updated_at FROM address_book WHERE id = 1"
            )
        ).one()
        assert a[0] == "manual"
        assert int(a[1]) == 0
        assert a[2] is not None
        assert a[3] is not None

        b = conn.execute(text("SELECT source, usage_count FROM address_book WHERE id = 2")).one()
        assert b[0] == "google_places"
        assert int(b[1]) == 9

    indexes = {ix["name"] for ix in inspect(engine).get_indexes("address_book")}
    for name in (
        "idx_address_book_name",
        "idx_address_book_category",
        "idx_address_book_poi_category",
    ):
        assert name in indexes, f"index {name} must survive the rebuild"

    # Idempotent: a second run is a no-op and does not raise; still NOT NULL.
    _load(MIGRATION).upgrade(engine=engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("address_book")}
    for name in _TARGETS:
        assert cols[name]["nullable"] is False


def test_069_full_column_value_preservation(engine_for_migration) -> None:
    """A 24-column sentinel row survives value-for-value, including id."""
    dialect, engine, _url = engine_for_migration
    _create_under_constrained(engine, dialect)

    sentinel = {
        "id": 42,
        "business_name": "Sentinel Auto",
        "name": "Sentinel Name",
        "address": "1 Sentinel St",
        "city": "Sentinelville",
        "state": "SN",
        "zip_code": "90210",
        "phone": "555-0100",
        "email": "sentinel@example.com",
        "website": "https://sentinel.example.com",
        "category": "service",
        "notes": "sentinel notes",
        # NUMERIC columns bound as strings: the sync sqlite3 driver rejects
        # Decimal params, and both dialects coerce the string via NUMERIC
        # affinity. The before/after compare stays exact (same driver reads both).
        "latitude": "12.34567890",
        "longitude": "123.45678900",
        "source": "google_places",  # distinct, non-default -> not clobbered to 'manual'
        "external_id": "ext-123",
        "rating": "4.50",
        "user_rating": 5,
        "usage_count": 7,  # distinct, non-zero -> not clobbered to 0
        "last_used": "2021-06-07 08:09:10",
        "poi_category": "auto_shop",
        "poi_metadata": '{"k": "v"}',
        "created_at": "2020-01-02 03:04:05",
        "updated_at": "2020-02-03 04:05:06",
    }
    collist = ", ".join(_ALL_COLUMNS)
    placeholders = ", ".join(f":{c}" for c in _ALL_COLUMNS)
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO address_book ({collist}) VALUES ({placeholders})"), sentinel
        )

    select_sql = text(f"SELECT {collist} FROM address_book WHERE id = 42")
    with engine.connect() as conn:
        before = conn.execute(select_sql).one()

    _load(MIGRATION).upgrade(engine=engine)

    with engine.connect() as conn:
        after = conn.execute(select_sql).one()

    # Value-for-value identity across all 24 columns (dialect-robust: same
    # driver reads both snapshots). A miscopied/reordered rebuild would diverge.
    assert tuple(after) == tuple(before), f"row changed by rebuild:\nbefore={before}\nafter={after}"

    # Explicit stable-type spot checks for legibility and same-type-swap safety.
    row = dict(zip(_ALL_COLUMNS, after, strict=True))
    assert row["id"] == 42
    assert row["business_name"] == "Sentinel Auto"
    assert row["source"] == "google_places"
    assert int(row["usage_count"]) == 7
    assert row["poi_metadata"] == '{"k": "v"}'


def test_069_inbound_fk_preserved(engine_for_migration) -> None:
    """The inbound fuel_records FK survives the rebuild (SQLite only).

    fuel_records.station_address_book_id -> address_book.id (ON DELETE SET
    NULL). The engine is given a connect-listener enabling PRAGMA
    foreign_keys=ON, so if the migration failed to disable FK enforcement
    before DROP TABLE, the implicit delete would SET NULL the FK and this
    test would fail. It asserts the FK value stays 1 AND foreign_key_check
    is empty.
    """
    dialect, engine, _url = engine_for_migration
    if dialect != "sqlite":
        pytest.skip("Inbound-FK rebuild is SQLite-specific (PG uses ALTER SET NOT NULL)")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    _create_under_constrained(engine, dialect)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE fuel_records ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  station_address_book_id INTEGER "
                "    REFERENCES address_book(id) ON DELETE SET NULL"
                ")"
            )
        )
        # Parent first (FK enforced), then the referencing child row.
        conn.execute(text("INSERT INTO address_book (id, business_name) VALUES (1, 'Station One')"))
        conn.execute(text("INSERT INTO fuel_records (id, station_address_book_id) VALUES (1, 1)"))

    _load(MIGRATION).upgrade(engine=engine)

    with engine.connect() as conn:
        fk_value = conn.execute(
            text("SELECT station_address_book_id FROM fuel_records WHERE id = 1")
        ).scalar()
        violations = conn.execute(text("PRAGMA foreign_key_check")).fetchall()

    assert fk_value == 1, "inbound FK value must survive the rebuild (not nulled/orphaned)"
    assert violations == [], f"foreign_key_check must be empty, got: {violations!r}"
