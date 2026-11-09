"""Add ``livelink_topic_maps``, the table behind config-driven MQTT sources.

One new table and nothing else: no column dropped, no row rewritten, no
existing table touched. So this needs no backup warning.

FATAL = False, and that is a real choice. The ORM maps the table, so a silent
skip would 500 every topic-map list; but ``create_all`` runs BEFORE migrations
(``app/database.py:144``) and creates it from the model, so on the ordinary
startup path the table exists whether or not this migration runs. This
migration is what gets it onto a database whose ``create_all`` already ran in
an older release.

That same ordering is why the column TYPES here must match the model rather
than merely be compatible with it: whichever of the two runs first decides what
the table looks like.

``value_offset``, not ``offset``: OFFSET is a reserved word.

No ForeignKey on ``device_id``, matching every other LiveLink child table (see
the comment at ``app/models/livelink_device.py:138``). Cleanup is explicit in
``LiveLinkService.delete_device``.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = False

_TABLE = "livelink_topic_maps"


def _ddl(serial: str, timestamp: str) -> str:
    """DDL for both dialects.

    `enabled BOOLEAN ... DEFAULT TRUE`, not `DEFAULT 1`: PostgreSQL rejects an
    integer default on a boolean column with DatatypeMismatch, while SQLite
    accepts either. SQLite has understood the TRUE keyword since 3.23, so one
    spelling serves both and there is no third dialect parameter to forget.
    """
    return f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id {serial},
            device_id VARCHAR(20) NOT NULL,
            topic VARCHAR(255) NOT NULL,
            role VARCHAR(12) NOT NULL DEFAULT 'telemetry',
            param_key VARCHAR(100),
            value_path VARCHAR(100),
            unit VARCHAR(20),
            param_class VARCHAR(50),
            scale DECIMAL(12, 6) NOT NULL DEFAULT 1,
            value_offset DECIMAL(12, 6) NOT NULL DEFAULT 0,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at {timestamp} DEFAULT CURRENT_TIMESTAMP,
            updated_at {timestamp}
        )
    """


_UNIQUE = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS uq_topic_maps_topic_param ON {_TABLE} (topic, param_key)"
)
_INDEX = f"CREATE INDEX IF NOT EXISTS idx_topic_maps_device ON {_TABLE} (device_id)"


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Create ``livelink_topic_maps`` if it is not already there."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    if inspect(engine).has_table(_TABLE):
        print(f"\u2713 {_TABLE} already present")
        return

    if engine.dialect.name == "postgresql":
        serial, timestamp = "SERIAL PRIMARY KEY", "TIMESTAMP"
    else:
        serial, timestamp = "INTEGER PRIMARY KEY AUTOINCREMENT", "DATETIME"

    with engine.begin() as conn:
        conn.execute(text(_ddl(serial, timestamp)))
        conn.execute(text(_UNIQUE))
        conn.execute(text(_INDEX))
        print(f"\u2713 Created {_TABLE}")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 111 is forward-only.")


if __name__ == "__main__":
    upgrade()
