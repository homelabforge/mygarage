"""Clear the prose the low-tread sync used to write into reminder notes (G3a-21).

It baked mm and km into the note for every reader, and the km figure was
always 0. The tread now lives in the reminder's own columns and renders in
each reader's units, so the old sentence would only repeat it. Exact matches
only: a note someone edited stays.

Non-FATAL: no model maps anything new, and a failed run only leaves the old
sentence on screen.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = False

logger = logging.getLogger(__name__)

#: What the sync wrote: the tread sentence, then an optional "~N km remaining."
_GENERATED = re.compile(r"Tread [0-9.]+ mm ≤ threshold [0-9.]+ mm\.( ~[0-9.]+ km remaining\.)?")


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Null the notes of low-tread reminders that still hold the old generated sentence."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("vehicle_reminders"):
        return
    if "source" not in {c["name"] for c in inspector.get_columns("vehicle_reminders")}:
        return

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, notes FROM vehicle_reminders "
                "WHERE source = 'low_tread' AND notes IS NOT NULL"
            )
        ).all()
        cleared = [row_id for row_id, notes in rows if _GENERATED.fullmatch(notes)]
        for row_id in cleared:
            conn.execute(
                text("UPDATE vehicle_reminders SET notes = NULL WHERE id = :id"), {"id": row_id}
            )
    logger.info("Cleared the old low-tread sentence on %d reminder(s)", len(cleared))


def downgrade() -> None:  # pragma: no cover
    """Rollback not supported."""
    raise NotImplementedError("Migration 127 is forward-only.")


if __name__ == "__main__":
    upgrade()
