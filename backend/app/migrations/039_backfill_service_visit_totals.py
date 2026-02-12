"""Backfill service_visits.total_cost from line items + fees.

Ensures total_cost is populated for all visits where it was previously NULL,
making SQL-level aggregation in analytics/reports always accurate.

Idempotent — only touches rows where total_cost IS NULL and there's
something to compute (line items with cost, or tax/fee fields set).
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Backfill total_cost on service_visits from line items + fees."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Backfilling service_visits.total_cost...")

        # Count rows before
        before_result = conn.execute(
            text("SELECT COUNT(*) FROM service_visits WHERE total_cost IS NULL")
        )
        before_count = before_result.scalar() or 0
        print(f"  → {before_count} visits with NULL total_cost before backfill")

        if before_count == 0:
            print("  → Nothing to backfill, all visits already have total_cost")
            return

        # Backfill: sum line item costs + tax/fees for any visit with NULL total_cost
        conn.execute(
            text("""
                UPDATE service_visits
                SET total_cost = (
                    SELECT COALESCE(SUM(sli.cost), 0)
                    FROM service_line_items sli
                    WHERE sli.visit_id = service_visits.id
                ) + COALESCE(tax_amount, 0)
                  + COALESCE(shop_supplies, 0)
                  + COALESCE(misc_fees, 0)
                WHERE total_cost IS NULL
                AND (
                    EXISTS (
                        SELECT 1 FROM service_line_items sli
                        WHERE sli.visit_id = service_visits.id
                        AND sli.cost IS NOT NULL
                    )
                    OR tax_amount IS NOT NULL
                    OR shop_supplies IS NOT NULL
                    OR misc_fees IS NOT NULL
                )
            """)
        )

        # Count rows after
        after_result = conn.execute(
            text("SELECT COUNT(*) FROM service_visits WHERE total_cost IS NULL")
        )
        after_count = after_result.scalar()
        backfilled = before_count - after_count
        print(f"  → Backfilled {backfilled} visits")
        print(f"  → {after_count} visits still have NULL total_cost (no data to compute)")

        print("Service visit total_cost backfill complete.")


def downgrade():
    """Downgrade not supported for this migration."""
    print("  Downgrade not supported for this migration")


if __name__ == "__main__":
    upgrade()
