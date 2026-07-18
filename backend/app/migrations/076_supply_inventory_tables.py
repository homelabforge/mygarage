"""Create parts & supplies inventory tables: supplies, supply_purchases, supply_usages.

Dialect-aware (SQLite + PostgreSQL). Non-FATAL: brand-new tables also covered by
Base.metadata.create_all on a fresh boot — a failure here degrades the supplies
feature only, it does not brick app startup.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text

# Non-FATAL: purely additive new tables (see module docstring).


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    if engine is None:
        engine = _get_fallback_engine()
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if is_pg else "DATETIME"
    bool_true = "TRUE" if is_pg else "1"

    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS supplies (
                    id {pk},
                    name VARCHAR(120) NOT NULL,
                    part_number VARCHAR(60),
                    category VARCHAR(40),
                    unit_type VARCHAR(10) NOT NULL,
                    vin VARCHAR(17) REFERENCES vehicles(vin) ON DELETE CASCADE,
                    is_active BOOLEAN NOT NULL DEFAULT {bool_true},
                    notes TEXT,
                    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at {ts} DEFAULT CURRENT_TIMESTAMP,
                    updated_at {ts},
                    CHECK (unit_type IN ('volume', 'count'))
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS supply_purchases (
                    id {pk},
                    supply_id INTEGER NOT NULL REFERENCES supplies(id) ON DELETE CASCADE,
                    date DATE NOT NULL,
                    quantity NUMERIC(12, 3) NOT NULL,
                    total_cost NUMERIC(10, 2),
                    supplier_id INTEGER REFERENCES address_book(id) ON DELETE SET NULL,
                    part_number VARCHAR(60),
                    notes TEXT,
                    created_at {ts} DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS supply_usages (
                    id {pk},
                    supply_id INTEGER NOT NULL REFERENCES supplies(id) ON DELETE CASCADE,
                    quantity NUMERIC(12, 3) NOT NULL,
                    unit_cost_snapshot NUMERIC(10, 4),
                    cost_snapshot NUMERIC(10, 2),
                    service_line_item_id INTEGER
                        REFERENCES service_line_items(id) ON DELETE CASCADE,
                    created_at {ts} DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        for name, table, cols in (
            ("idx_supplies_vin", "supplies", "vin"),
            ("idx_supply_purchases_supply_date", "supply_purchases", "supply_id, date"),
            ("idx_supply_usages_supply", "supply_usages", "supply_id"),
            ("idx_supply_usages_line_item", "supply_usages", "service_line_item_id"),
        ):
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))


def downgrade():
    print("Downgrade not supported for inventory table creation")


if __name__ == "__main__":
    upgrade()
