"""Seed DTC definitions table with SAE J2012 standard codes.

This migration loads ~3000 generic OBD-II DTC codes from the bundled JSON file.
Covers P, B, C, and U code categories.

Data sourced from: https://github.com/mytrile/obd-trouble-codes
Licensed under MIT.

Phase 1 scope: code + description + category + severity only.
common_causes, symptoms, and fix_guidance are NULL (future enhancement).
"""

import json
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Seed DTC definitions from bundled JSON file."""
    if engine is None:
        engine = _get_fallback_engine()

    # Find the JSON file relative to this migration file
    migration_dir = Path(__file__).parent
    json_path = migration_dir.parent / "data" / "dtc_definitions.json"

    if not json_path.exists():
        print(f"  DTC definitions JSON not found at {json_path}, skipping")
        return

    # Load DTC definitions
    with open(json_path, encoding="utf-8") as f:
        dtc_list = json.load(f)

    print(f"  Loading {len(dtc_list)} DTC definitions...")

    with engine.begin() as conn:
        # Check if table exists
        if not inspect(engine).has_table("dtc_definitions"):
            print("  dtc_definitions table does not exist, skipping seed")
            return

        # Check if already seeded
        result = conn.execute(text("SELECT COUNT(*) FROM dtc_definitions"))
        row = result.fetchone()
        existing_count = row[0] if row else 0
        if existing_count > 0:
            print(f"  dtc_definitions already has {existing_count} codes, skipping seed")
            return

        # Build parameter list with correct types (bool for PostgreSQL BOOLEAN)
        params = [
            {
                "code": dtc["code"],
                "description": dtc["description"],
                "category": dtc["category"],
                "subcategory": dtc.get("subcategory"),
                "severity": dtc["severity"],
                "severity_level": dtc["estimated_severity_level"],
                "emissions": bool(dtc.get("is_emissions_related")),
            }
            for dtc in dtc_list
        ]

        # Bulk insert in batches
        insert_sql = text("""
            INSERT INTO dtc_definitions (
                code, description, category, subcategory,
                severity, estimated_severity_level, is_emissions_related
            ) VALUES (
                :code, :description, :category, :subcategory,
                :severity, :severity_level, :emissions
            )
        """)

        batch_size = 500
        inserted = 0
        for i in range(0, len(params), batch_size):
            batch = params[i : i + batch_size]
            for row in batch:
                conn.execute(insert_sql, row)
                inserted += 1

        print(f"  Inserted {inserted} DTC definitions")

    print("  Migration 033 complete - DTC definitions seeded")


if __name__ == "__main__":
    upgrade()
