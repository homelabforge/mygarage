"""Add 'supply_purchase' to attachments.record_type CHECK + widen file_type.

Three coupled attachments changes (all needed before supply receipts work on PG):
  1. Add 'supply_purchase' to the record_type CHECK.
  2. Widen file_type VARCHAR(10) → VARCHAR(50) so MIME types (application/pdf,
     application/octet-stream) fit — SQLite ignores the length, but PostgreSQL
     rejects the receipt upload without this (R1-H2).
  3. Partial unique index uq_supply_purchase_receipt on (record_id) WHERE
     record_type='supply_purchase' — one receipt per purchase, atomic even under
     concurrent uploads (R1-H4).

Dialect-aware: PostgreSQL DROP/ADD CONSTRAINT + ALTER COLUMN TYPE; SQLite full
table rebuild (no in-place CHECK alter — the rebuilt table also carries the wider
column). Idempotent — re-checks the live constraint and column width first.

Non-FATAL: a failure only disables supply_purchase receipt uploads (CHECK
violation / length overflow at insert); catalog, purchases, adjustments, usages
and app startup are unaffected. Fail-soft is correct here.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

_ALLOWED = (
    "'service', 'service_visit', 'fuel', 'upgrade', 'collision', 'tax', 'note', 'supply_purchase'"
)


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    if engine is None:
        engine = _get_fallback_engine()
    if not inspect(engine).has_table("attachments"):
        return
    if engine.dialect.name == "postgresql":
        _upgrade_pg(engine)
    else:
        _upgrade_sqlite(engine)
    # (3) One receipt per purchase, enforced at the DB level (R1-H4). Partial unique
    # index works on both dialects; supply_purchase is a brand-new record_type so no
    # pre-existing rows can collide. IF NOT EXISTS keeps it idempotent.
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_supply_purchase_receipt "
                "ON attachments (record_id) WHERE record_type = 'supply_purchase'"
            )
        )


def _upgrade_pg(engine):
    with engine.begin() as conn:
        # (2) Widen file_type so MIME strings fit. Idempotent — skip if already wide.
        width = conn.execute(
            text(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name='attachments' AND column_name='file_type'"
            )
        ).scalar()
        if width is not None and width < 50:
            conn.execute(text("ALTER TABLE attachments ALTER COLUMN file_type TYPE VARCHAR(50)"))
        # (1) Add supply_purchase to the record_type CHECK.
        row = conn.execute(
            text(
                """
                SELECT conname, pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = 'attachments'::regclass AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%record_type%'
                """
            )
        ).fetchone()
        if row and "supply_purchase" in row[1]:
            return  # constraint already applied (file_type handled above)
        if row:
            conn.execute(text(f"ALTER TABLE attachments DROP CONSTRAINT {row[0]}"))
        conn.execute(
            text(
                f"ALTER TABLE attachments ADD CONSTRAINT check_record_type "
                f"CHECK (record_type IN ({_ALLOWED}))"
            )
        )


def _upgrade_sqlite(engine):
    with engine.begin() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='attachments'")
        ).scalar()
        if ddl and "supply_purchase" in ddl:
            return  # already applied
        conn.execute(text("DROP TABLE IF EXISTS attachments_new"))
        conn.execute(
            text(
                f"""
                CREATE TABLE attachments_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_type VARCHAR(30) NOT NULL,
                    record_id INTEGER NOT NULL,
                    file_path VARCHAR(255) NOT NULL,
                    file_type VARCHAR(50),
                    file_size INTEGER,
                    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT check_record_type CHECK (record_type IN ({_ALLOWED}))
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO attachments_new "
                "(id, record_type, record_id, file_path, file_type, file_size, uploaded_at) "
                "SELECT id, record_type, record_id, file_path, file_type, file_size, uploaded_at "
                "FROM attachments"
            )
        )
        conn.execute(text("DROP TABLE attachments"))
        conn.execute(text("ALTER TABLE attachments_new RENAME TO attachments"))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_attachments_record "
                "ON attachments(record_type, record_id)"
            )
        )


def downgrade():
    print("Downgrade not supported for CHECK constraint change")


if __name__ == "__main__":
    upgrade()
