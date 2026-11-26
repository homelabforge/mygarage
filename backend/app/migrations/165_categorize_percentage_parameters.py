"""Give percentage parameters a real category instead of other (B-9).

WiCAN files every % reading under class ``percentage``, and that class had no
branch in ``TelemetryService._classify_param``, so fuel level, throttle and
state of charge all landed on ``other``. New rows get a category by key now;
this moves the rows already on file.

A ``percentage`` row on ``other`` or no category (NULL or empty, which the
runtime treats the same) gets one by its canonical key:
``FUEL`` in it gives ``fuel``, ``SOC`` or ``BATT`` gives ``electrical``, anything
else ``engine``. A category someone set stays, and so does every row on another
class. Once this has run, a percentage row on ``other`` is one an admin put
there, and the app leaves it.

The rule and the key canonicalizer are frozen copies, as in 062: a historical
migration's output must not move when the runtime rule does.

Not FATAL: nothing reads ``category`` yet, and the admin page writes it.
Idempotent: a second run finds no percentage row on other, empty or NULL.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Engine, bindparam, create_engine, inspect, text

logger = logging.getLogger(__name__)

FATAL = False

_CATEGORIES = ("fuel", "electrical", "engine")


def _category_for(param_key: str) -> str:
    """Frozen copy of the percentage branch of TelemetryService._classify_param."""
    key = param_key.upper().replace(" ", "_")  # canonical_param_key, frozen
    if "FUEL" in key:
        return "fuel"
    if "SOC" in key or "BATT" in key:
        return "electrical"
    return "engine"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}", hide_parameters=True)
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}", hide_parameters=True)


def upgrade(engine: Engine | None = None) -> None:
    """File percentage rows on other or no category under fuel, electrical or engine."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    if not inspect(engine).has_table("livelink_parameters"):
        logger.info("165: livelink_parameters missing, nothing to categorize")
        return

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, param_key FROM livelink_parameters"
                # The app lowercases the class before it matches, so this does too.
                " WHERE LOWER(param_class) = 'percentage'"
                " AND (category IS NULL OR category = '' OR category = 'other')"
            )
        ).all()

        ids: dict[str, list[int]] = {category: [] for category in _CATEGORIES}
        for row_id, param_key in rows:
            ids[_category_for(param_key)].append(row_id)

        update = text(
            "UPDATE livelink_parameters SET category = :category WHERE id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        for category, row_ids in ids.items():
            if row_ids:
                conn.execute(update, {"category": category, "ids": row_ids})

    logger.info(
        "165: categorized %d percentage parameters (%d fuel, %d electrical, %d engine)",
        len(rows),
        len(ids["fuel"]),
        len(ids["electrical"]),
        len(ids["engine"]),
    )


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 165 is forward-only.")


if __name__ == "__main__":
    upgrade()
