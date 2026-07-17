"""Migration 069 — tighten address_book's four under-constrained NOT NULLs.

Historically the ``address_book`` columns ``source``, ``usage_count``,
``created_at`` and ``updated_at`` were added by migrations 002/025 without a
NOT NULL constraint, while the model (``app/models/address_book.py``) declares
all four non-nullable. This migration reconciles the DB with the model.

Dialect-aware:
  - **PostgreSQL:** backfill any NULLs, then ``ALTER COLUMN ... SET NOT NULL``.
  - **SQLite:** an FK-safe table rebuild, because SQLite cannot ``ALTER COLUMN
    SET NOT NULL`` and ``address_book`` carries an **inbound** foreign key
    (``fuel_records.station_address_book_id -> address_book.id``,
    ``ON DELETE SET NULL``). A naive ``DROP TABLE address_book`` under FK
    enforcement performs an implicit DELETE, firing ``ON DELETE SET NULL`` and
    silently nulling that FK. So the rebuild mirrors migration 053's proven
    ordering exactly (053 lines 385-496):
      1. ``PRAGMA foreign_keys = OFF`` on a **raw** DB-API connection, OUTSIDE
         any transaction — SQLAlchemy's ``engine.begin()`` autobegins a txn in
         which the PRAGMA is a silent no-op (053:385-425).
      2. Explicit ``BEGIN``; ``CREATE TABLE address_book_new`` with the model's
         full 24-column set (the four targets NOT NULL with DEFAULTs),
         ``INSERT ... SELECT`` (``COALESCE`` backfills the NOT NULL targets),
         ``DROP``/``RENAME``, recreate the three indexes (053:427-447).
      3. ``PRAGMA foreign_key_check`` **BEFORE COMMIT**; a non-empty result
         **raises** so the transaction rolls back — never commit a rebuild that
         orphaned or nulled the inbound FK (053:449-470).
      4. FK enforcement is restored via ``PRAGMA foreign_keys = ON`` in a
         ``finally`` so it returns even if the rebuild raised (053:472-476).

Failure contract: this migration has NO broad try/except. A backfill/rebuild
error, or a non-empty ``foreign_key_check``, propagates — the runner then does
NOT stamp it, so it is retried on the next boot. The only guarded ``return`` is
the idempotency short-circuit (all four targets already NOT NULL). Forward-only:
``downgrade`` raises.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

# The four historically under-constrained columns this migration tightens.
_TARGET_COLUMNS = ("source", "usage_count", "created_at", "updated_at")

# The model's three indexes (address_book.py __table_args__), recreated after
# the SQLite rebuild.
_INDEXES = (
    "CREATE INDEX idx_address_book_name ON address_book(name)",
    "CREATE INDEX idx_address_book_category ON address_book(category)",
    "CREATE INDEX idx_address_book_poi_category ON address_book(poi_category)",
)


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    """Tighten the four under-constrained address_book columns to NOT NULL."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)

    # Idempotency guard — cheap read, no transaction implications. If every
    # target is already NOT NULL there is nothing to do. This is the ONLY
    # guarded return (see the module docstring's failure contract).
    columns = {c["name"]: c for c in inspector.get_columns("address_book")}
    if all(not columns[name]["nullable"] for name in _TARGET_COLUMNS):
        print("  → address_book NOT NULL constraints already applied, skipping")
        return

    print("Tightening address_book NOT NULL constraints…")
    if engine.dialect.name == "postgresql":
        _run_postgres(engine)
    else:
        _run_sqlite(engine)

    print("✓ address_book NOT NULL tightening completed")


# ============================================================================
#  PostgreSQL path — backfill then ALTER COLUMN ... SET NOT NULL.
# ============================================================================


def _run_postgres(engine) -> None:
    """Postgres: one transaction, backfill NULLs, then SET NOT NULL per column."""
    with engine.begin() as conn:
        conn.execute(text("UPDATE address_book SET source = 'manual' WHERE source IS NULL"))
        conn.execute(text("UPDATE address_book SET usage_count = 0 WHERE usage_count IS NULL"))
        conn.execute(
            text("UPDATE address_book SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
        )
        conn.execute(
            text("UPDATE address_book SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
        )
        for col in _TARGET_COLUMNS:
            conn.execute(text(f"ALTER TABLE address_book ALTER COLUMN {col} SET NOT NULL"))


# ============================================================================
#  SQLite path — raw DBAPI connection, PRAGMA outside tx, FK-safe rebuild.
#  Mirrors migration 053's ordering (053:385-496).
# ============================================================================


def _run_sqlite(engine) -> None:
    """SQLite path using the raw DBAPI connection (mirrors migration 053).

    ``engine.raw_connection()`` yields the DB-API connection without
    SQLAlchemy's autobegin layer, so ``PRAGMA foreign_keys = OFF`` lands
    OUTSIDE a transaction (a no-op inside one) as the SQLite docs require for
    ALTER-TABLE-heavy migrations.
    """
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        # 1. Disable FKs OUTSIDE any transaction (required by SQLite docs).
        cur.execute("PRAGMA foreign_keys = OFF")
        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 0:
            raise RuntimeError(
                f"PRAGMA foreign_keys = OFF failed; got {fk_state}. "
                "Are we inside an active transaction?"
            )

        # 2. Explicit transaction for the rebuild. The `finally` ALWAYS restores
        #    FK enforcement, even if the rebuild raises.
        try:
            cur.execute("BEGIN")
            _rebuild_address_book(cur)

            # 2a. PRE-COMMIT whole-DB FK integrity check. address_book has an
            #     inbound FK (fuel_records.station_address_book_id); if the
            #     rebuild orphaned or nulled it, roll back untouched.
            violations = cur.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(
                    f"FK violations after address_book rebuild (pre-commit): {violations!r}"
                )

            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys = ON")

        # 3. Verify enforcement was restored (only reached on the success path;
        #    on failure the original exception has already propagated).
        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 1:
            raise RuntimeError(f"PRAGMA foreign_keys = ON failed; got {fk_state}.")
    finally:
        raw.close()


def _rebuild_address_book(cur) -> None:
    """Rebuild address_book with the four targets NOT NULL.

    Reproduces the model's exact full 24-column set (app/models/address_book.py),
    with ``source``/``usage_count``/``created_at``/``updated_at`` declared NOT
    NULL and carrying their DDL DEFAULTs. ``COALESCE`` on the four targets in the
    SELECT backfills any legacy NULLs so the NOT NULL constraint is satisfiable.
    """
    cur.execute("""
        CREATE TABLE address_book_new (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
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
            source        VARCHAR(20) NOT NULL DEFAULT 'manual',
            external_id   VARCHAR(100),
            rating        NUMERIC(3,2),
            user_rating   INTEGER,
            usage_count   INTEGER NOT NULL DEFAULT 0,
            last_used     DATETIME,
            poi_category  VARCHAR(50),
            poi_metadata  TEXT,
            created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        INSERT INTO address_book_new
               (id, business_name, name, address, city, state, zip_code, phone,
                email, website, category, notes, latitude, longitude, source,
                external_id, rating, user_rating, usage_count, last_used,
                poi_category, poi_metadata, created_at, updated_at)
        SELECT  id, business_name, name, address, city, state, zip_code, phone,
                email, website, category, notes, latitude, longitude,
                COALESCE(source, 'manual'),
                external_id, rating, user_rating,
                COALESCE(usage_count, 0),
                last_used, poi_category, poi_metadata,
                COALESCE(created_at, CURRENT_TIMESTAMP),
                COALESCE(updated_at, CURRENT_TIMESTAMP)
        FROM address_book
    """)
    cur.execute("DROP TABLE address_book")
    cur.execute("ALTER TABLE address_book_new RENAME TO address_book")
    for stmt in _INDEXES:
        cur.execute(stmt)


def downgrade(engine=None) -> None:
    """Forward-only. Rollback is a pre-migration backup restore, not a downgrade."""
    raise NotImplementedError(
        "Migration 069 is forward-only. Restore from the pre-migration backup instead."
    )


if __name__ == "__main__":
    upgrade()
