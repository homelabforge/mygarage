"""Create financing_records table for lease, loan, and upfront-fee costs.

Normally created earlier by Base.metadata.create_all, so the has_table guard skips it.
Non-FATAL by design.
"""

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

_CATEGORIES = ("lease_payment", "loan_payment", "upfront_fee")


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None):
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    inspector = inspect(engine)
    if not inspector.has_table("vehicles"):
        return
    if inspector.has_table("financing_records"):
        return

    is_pg = engine.dialect.name == "postgresql"
    pk_type = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts_type = "TIMESTAMP" if is_pg else "DATETIME"
    category_list = ", ".join(f"'{c}'" for c in _CATEGORIES)

    with engine.begin() as conn:
        conn.execute(
            text(f"""
            CREATE TABLE financing_records (
                id {pk_type},
                vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                vendor_id INTEGER REFERENCES vendors(id),
                date DATE NOT NULL,
                amount NUMERIC(10,2) NOT NULL,
                category VARCHAR(20) NOT NULL
                    CONSTRAINT check_financing_records_category CHECK (category IN ({category_list})),
                notes TEXT,
                created_at {ts_type} DEFAULT CURRENT_TIMESTAMP,
                updated_at {ts_type}
            )
        """)
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_financing_records_vin ON financing_records (vin)")
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_financing_records_date ON financing_records (date)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_financing_records_vendor_id "
                "ON financing_records (vendor_id)"
            )
        )


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 121 is forward-only.")


if __name__ == "__main__":
    upgrade()
