"""Recall sources (#211): where a recall came from, and its own identifier.

Four columns on ``recalls``:

- ``source`` VARCHAR(20) NOT NULL DEFAULT 'nhtsa': ``nhtsa``, ``rappelconso``
  or ``manual``. Every existing row came from NHTSA or was typed against an
  NHTSA campaign number, so the default is right for all of them.
- ``external_id`` VARCHAR(64): the provider's identifier (an NHTSA campaign
  number, a RappelConso notice number); with ``source`` it is what keeps a
  recall from being stored twice. Backfilled from ``nhtsa_campaign_number``.
- ``external_url`` VARCHAR(500): the notice online.
- ``match_confidence`` INTEGER: 0 to 100, how surely the notice concerns
  this vehicle (RappelConso has no VIN).

Plus the index ``idx_recalls_source_external`` on (vin, source, external_id).
No CHECK: the vocabulary is Pydantic's, and the response reads an unknown
source as null. FATAL: the ORM declares the columns. Idempotent.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_TABLE = "recalls"
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source", "VARCHAR(20) NOT NULL DEFAULT 'nhtsa'"),
    ("external_id", "VARCHAR(64)"),
    ("external_url", "VARCHAR(500)"),
    ("match_confidence", "INTEGER"),
)
_INDEX = "idx_recalls_source_external"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add the columns, backfill the NHTSA identifiers, add the index."""
    if engine is None:
        engine = _get_fallback_engine()
    if not inspect(engine).has_table(_TABLE):
        return
    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns(_TABLE)}
        for name, ddl in _COLUMNS:
            if name in existing:
                continue
            conn.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN {name} {ddl}"))
        conn.execute(
            text(
                f"UPDATE {_TABLE} SET external_id = nhtsa_campaign_number "
                "WHERE external_id IS NULL AND nhtsa_campaign_number IS NOT NULL"
            )
        )
        indexes = {index["name"] for index in inspect(engine).get_indexes(_TABLE)}
        if _INDEX not in indexes:
            conn.execute(text(f"CREATE INDEX {_INDEX} ON {_TABLE} (vin, source, external_id)"))


if __name__ == "__main__":
    upgrade()
