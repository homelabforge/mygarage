"""Widen ``recalls.component`` to VARCHAR(200), and allow one active DTC per vehicle and code.

The API and the NHTSA sync both take a 200-character component, but the column
held 100, so PostgreSQL refused a long one and the whole recall refresh failed
with it. SQLite ignores the length, so the widening only runs on PostgreSQL.

Two active rows of one code make DTC ingest raise, since it reads the active
row with scalar_one_or_none, and an import racing a live report could make
them. So any duplicates are closed first, newest kept, the way a person
clearing one would close it, and then a partial unique index holds the line.

Not FATAL: if it fails, the column stays at 100 and the duplicates stay, which is today.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

logger = logging.getLogger(__name__)

_INDEX = "uq_vehicle_dtcs_active_code"
_WIDTH = 200
#: What a closed duplicate's note says, in clear_dtc's "Cleared: ..." shape.
_CLOSED_NOTE = "Cleared: a second active copy of this code, closed on upgrade (migration 137)"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    # hide_parameters: a failed statement's message leaves out its bound values.
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}", hide_parameters=True)
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}", hide_parameters=True)


def _widen_component(engine: Engine) -> None:
    """recalls.component to VARCHAR(200) on PostgreSQL; nothing to do on SQLite."""
    if engine.dialect.name != "postgresql":
        logger.info("137: SQLite ignores VARCHAR length; recalls.component left as is")
        return
    inspector = inspect(engine)
    if not inspector.has_table("recalls"):
        logger.info("137: recalls missing; skip the widening")
        return
    columns = {c["name"]: c for c in inspector.get_columns("recalls")}
    if "component" not in columns:
        logger.info("137: recalls.component missing; skip the widening")
        return
    width = getattr(columns["component"]["type"], "length", None)
    if width is None or width >= _WIDTH:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE recalls ALTER COLUMN component TYPE VARCHAR({_WIDTH})"))
    logger.info("137: widened recalls.component to VARCHAR(%d)", _WIDTH)


def _index_active_dtcs(engine: Engine) -> None:
    """Close duplicate active DTCs, newest kept, then add the one-active-per-code index."""
    inspector = inspect(engine)
    if not inspector.has_table("vehicle_dtcs"):
        logger.info("137: vehicle_dtcs missing; skip the index")
        return
    # A fresh install gets it from create_all, and a rerun finds it here.
    if _INDEX in {i["name"] for i in inspector.get_indexes("vehicle_dtcs")}:
        return

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, vin, code FROM vehicle_dtcs WHERE is_active"
                " ORDER BY vin, code, last_seen DESC, id DESC"
            )
        ).all()
        seen: set[tuple[str, str]] = set()
        duplicates: list[int] = []
        for row_id, vin, code in rows:
            if (vin, code) in seen:
                duplicates.append(row_id)
            else:
                seen.add((vin, code))

        if duplicates:
            # Naive UTC, like every timestamp column here.
            now = datetime.now(UTC).replace(tzinfo=None)
            conn.execute(
                text(
                    "UPDATE vehicle_dtcs SET is_active = :inactive, cleared_at = :now,"
                    " user_notes = CASE WHEN user_notes IS NULL OR user_notes = ''"
                    " THEN :note ELSE user_notes || :sep || :note END"
                    " WHERE id = :id"
                ),
                [
                    {"inactive": False, "now": now, "note": _CLOSED_NOTE, "sep": "\n\n", "id": i}
                    for i in duplicates
                ],
            )
        conn.execute(
            text(f"CREATE UNIQUE INDEX {_INDEX} ON vehicle_dtcs (vin, code) WHERE is_active")
        )
    logger.info("137: closed %d duplicate active DTC row(s) and added %s", len(duplicates), _INDEX)


def upgrade(engine: Engine | None = None) -> None:
    """Widen the recall component, then index the active DTCs. Each half skips on its own."""
    if engine is None:
        engine = _get_fallback_engine()
    _widen_component(engine)
    _index_active_dtcs(engine)


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 137 is forward-only.")


if __name__ == "__main__":
    upgrade()
