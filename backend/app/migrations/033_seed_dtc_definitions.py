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

from sqlalchemy import create_engine, text


def upgrade():
    """Seed DTC definitions from bundled JSON file."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

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
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='dtc_definitions'")
        )
        if not result.fetchone():
            print("  dtc_definitions table does not exist, skipping seed")
            return

        # Check if already seeded
        result = conn.execute(text("SELECT COUNT(*) FROM dtc_definitions"))
        row = result.fetchone()
        existing_count = row[0] if row else 0
        if existing_count > 0:
            print(f"  dtc_definitions already has {existing_count} codes, skipping seed")
            return

        # Insert in batches for efficiency
        batch_size = 100
        inserted = 0

        for i in range(0, len(dtc_list), batch_size):
            batch = dtc_list[i : i + batch_size]

            for dtc in batch:
                try:
                    conn.execute(
                        text("""
                            INSERT INTO dtc_definitions (
                                code, description, category, subcategory,
                                severity, estimated_severity_level, is_emissions_related
                            ) VALUES (
                                :code, :description, :category, :subcategory,
                                :severity, :severity_level, :emissions
                            )
                        """),
                        {
                            "code": dtc["code"],
                            "description": dtc["description"],
                            "category": dtc["category"],
                            "subcategory": dtc.get("subcategory"),
                            "severity": dtc["severity"],
                            "severity_level": dtc["estimated_severity_level"],
                            "emissions": 1 if dtc.get("is_emissions_related") else 0,
                        },
                    )
                    inserted += 1
                except Exception as e:
                    # Skip duplicates or errors
                    print(f"  Warning: Could not insert {dtc['code']}: {e}")

        print(f"  Inserted {inserted} DTC definitions")

    print("  Migration 033 complete - DTC definitions seeded")


if __name__ == "__main__":
    upgrade()
