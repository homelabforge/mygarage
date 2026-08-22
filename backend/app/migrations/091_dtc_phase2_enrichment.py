"""Seed Phase 2 DTC causes/symptoms/fix_guidance for common codes.

Non-fatal: enrichment is additive; missing table or codes should not block boot.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = False

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "dtc_phase2_enrichment.json"


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    if engine is None:
        engine = _get_fallback_engine()

    if not DATA_PATH.is_file():
        print(f"  → {DATA_PATH.name} missing, skipping DTC Phase 2 enrichment")
        return

    with engine.begin() as conn:
        inspector = inspect(engine)
        if "dtc_definitions" not in inspector.get_table_names():
            print("  → dtc_definitions missing, skipping")
            return

        rows = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        updated = 0
        for row in rows:
            code = row.get("code")
            if not code:
                continue
            causes = json.dumps(row.get("common_causes") or [])
            symptoms = json.dumps(row.get("symptoms") or [])
            guidance = row.get("fix_guidance")
            result = conn.execute(
                text(
                    """
                    UPDATE dtc_definitions
                    SET common_causes = :causes,
                        symptoms = :symptoms,
                        fix_guidance = :guidance
                    WHERE code = :code
                    """
                ),
                {
                    "causes": causes,
                    "symptoms": symptoms,
                    "guidance": guidance,
                    "code": code,
                },
            )
            updated += result.rowcount or 0
        print(f"  → DTC Phase 2 enrichment updated {updated} definition(s)")
