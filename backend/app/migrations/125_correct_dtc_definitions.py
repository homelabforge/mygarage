"""Correct the DTC definitions by code, and fill DTCs recorded without one (1d).

033 seeded from mytrile/obd-trouble-codes, whose generic P0 descriptions are
misaligned from about P0126 on (P0300 read "Cylinder 12 Contribution/Range
Fault") and whose maker-range rows are one maker's meanings with no maker
named. The shipped file is now the SAE generic ranges only, built by
tools/build_dtc_definitions.py. In one transaction this makes the table match
it: reset vehicle DTCs that copied their code's old text, delete codes it
doesn't carry, upsert every code by its key, re-apply 091's enrichment (it
describes the real meanings; same SQL as 091, which stays frozen), and give
vehicle DTCs without a description the new one, plus the severity if it is
still the no-definition default.

Non-FATAL, and it swallows its own errors (INDEX.md): reference data must
never stop the migrations queued behind it. A failure rolls back, logs at
ERROR and leaves the old rows. The runner still stamps it, so a restart
doesn't retry; a staged restore of an older backup (no stamp) runs it again.
Unlike 091, a missing or bad enrichment file refuses the whole correction:
both files are read before the first write, and they ship together.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

FATAL = False

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA = _DATA_DIR / "dtc_definitions.json"
_ENRICHMENT = _DATA_DIR / "dtc_phase2_enrichment.json"
_KEYS = frozenset(
    {
        "code",
        "description",
        "category",
        "subcategory",
        "severity",
        "estimated_severity_level",
        "is_emissions_related",
    }
)

# Never the enrichment columns: _ENRICH owns those, and an upsert that touched
# them would wipe causes and guidance the moment a code was corrected.
_UPSERT = text(
    """
    INSERT INTO dtc_definitions (code, description, category, subcategory,
        severity, estimated_severity_level, is_emissions_related)
    VALUES (:code, :description, :category, :subcategory, :severity, :level, :emissions)
    ON CONFLICT (code) DO UPDATE SET
        description = excluded.description,
        category = excluded.category,
        subcategory = excluded.subcategory,
        severity = excluded.severity,
        estimated_severity_level = excluded.estimated_severity_level,
        is_emissions_related = excluded.is_emissions_related
    """
)
# 091's UPDATE, run here so the correction and the enrichment commit together.
_ENRICH = text(
    """
    UPDATE dtc_definitions
    SET common_causes = :causes, symptoms = :symptoms, fix_guidance = :guidance
    WHERE code = :code
    """
)
# Runs against the old rows: a DTC whose text matches its code's definition
# copied it, so it goes back to no description and, if copied too, the
# no-definition severity. _FILL_VEHICLE_DTCS then fills it from the new rows.
_UNCOPY_VEHICLE_DTCS = text(
    """
    UPDATE vehicle_dtcs
    SET severity = CASE WHEN severity =
                (SELECT d.severity FROM dtc_definitions d WHERE d.code = vehicle_dtcs.code)
            THEN 'warning' ELSE severity END,
        description = NULL
    WHERE description =
        (SELECT d.description FROM dtc_definitions d WHERE d.code = vehicle_dtcs.code)
    """
)
# 'warning' is what a DTC gets when no definition existed at the time
# (DTCService._create_vehicle_dtc); any other value was set on purpose.
_FILL_VEHICLE_DTCS = text(
    """
    UPDATE vehicle_dtcs
    SET severity = CASE WHEN severity = 'warning'
            THEN (SELECT d.severity FROM dtc_definitions d WHERE d.code = vehicle_dtcs.code)
            ELSE severity END,
        description = (SELECT d.description FROM dtc_definitions d WHERE d.code = vehicle_dtcs.code)
    WHERE description IS NULL
      AND code IN (SELECT code FROM dtc_definitions)
    """
)


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _objects(loaded: list[object]) -> list[dict[str, Any]]:
    """The JSON objects in a parsed list; JSON keys are always strings."""
    return [cast(dict[str, Any], item) for item in loaded if isinstance(item, dict)]


def _entries() -> list[dict[str, Any]]:
    loaded = json.loads(_DATA.read_text(encoding="utf-8"))
    if not isinstance(loaded, list) or not loaded:
        raise ValueError("dtc_definitions.json is not a non-empty list")
    items = cast(list[object], loaded)
    entries = _objects(items)
    if len(entries) != len(items) or any(frozenset(e) != _KEYS for e in entries):
        raise ValueError("dtc_definitions.json has an entry with the wrong keys")
    return entries


def _enrichment() -> list[dict[str, Any]]:
    """091's rows as 091 binds them: lists stored as JSON text."""
    loaded = json.loads(_ENRICHMENT.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError("dtc_phase2_enrichment.json is not a list")
    return [
        {
            "code": row["code"],
            "causes": json.dumps(row.get("common_causes") or []),
            "symptoms": json.dumps(row.get("symptoms") or []),
            "guidance": row.get("fix_guidance"),
        }
        for row in _objects(cast(list[object], loaded))
        if row.get("code")
    ]


def _correct(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("dtc_definitions"):
        logger.info("125: dtc_definitions missing, skipping")
        return
    # Both files are read and checked before the first write.
    entries = _entries()
    enrichment = _enrichment()
    wanted = {str(e["code"]) for e in entries}
    params = [
        {
            "code": e["code"],
            "description": e["description"],
            "category": e["category"],
            "subcategory": e["subcategory"],
            "severity": e["severity"],
            "level": int(e["estimated_severity_level"]),
            "emissions": bool(e["is_emissions_related"]),
        }
        for e in entries
    ]
    has_vehicle_dtcs = inspector.has_table("vehicle_dtcs")
    with engine.begin() as conn:
        reset = conn.execute(_UNCOPY_VEHICLE_DTCS).rowcount if has_vehicle_dtcs else 0
        before = {str(c) for c in conn.execute(text("SELECT code FROM dtc_definitions")).scalars()}
        stale = sorted(before - wanted)
        if stale:
            conn.execute(
                text("DELETE FROM dtc_definitions WHERE code = :code"),
                [{"code": c} for c in stale],
            )
        conn.execute(_UPSERT, params)
        if enrichment:
            conn.execute(_ENRICH, enrichment)
        filled = conn.execute(_FILL_VEHICLE_DTCS).rowcount if has_vehicle_dtcs else 0
    logger.info(
        "125: dtc_definitions now %d codes (%d added, %d removed); "
        "%d vehicle DTCs reset from the old text, %d filled",
        len(wanted),
        len(wanted - before),
        len(stale),
        reset,
        filled,
    )


def upgrade(engine: Engine | None = None) -> None:
    """Correct dtc_definitions from the shipped files, all or nothing."""
    if engine is None:
        engine = _get_fallback_engine()
    try:
        _correct(engine)
    except (OSError, ValueError, KeyError, TypeError, SQLAlchemyError) as e:
        logger.error("125: DTC definitions not corrected, the old rows stay: %s", e, exc_info=True)
