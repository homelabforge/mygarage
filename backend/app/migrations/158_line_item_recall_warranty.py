"""Recall and warranty flags and links on service_line_items, and recalls.resolved_via.

service_line_items gets is_recall and is_warranty (NOT NULL, default false)
and recall_id / warranty_id, each a nullable FK with ON DELETE SET NULL, so a
deleted recall or warranty leaves the item flagged but unlinked (D8). A
partial unique index allows one item per recall (D9); warranty_id gets a
plain index. recalls gets resolved_via VARCHAR(20), NULL on every old row,
which reads as a manual resolve (D10).

FATAL: the models map every one of these columns, so a silent failure would
boot the app against a schema every line item and recall SELECT trips on.

Idempotent: each column is added only when absent, the indexes use IF NOT
EXISTS, and on PostgreSQL an FK is only added when no FK on that COLUMN exists
(create_all names it differently, so a name check would add a second one). A
NULL-default ADD COLUMN ... REFERENCES is legal on SQLite, which can't add an
FK to a column that's already there; that state never comes from this file.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, inspect, text

logger = logging.getLogger(__name__)

FATAL = True

_ITEMS = "service_line_items"
#: Link column -> the table it points at.
_LINKS = {"recall_id": "recalls", "warranty_id": "warranty_records"}
_FLAGS = ("is_recall", "is_warranty")
_UNIQUE_RECALL = "uq_line_items_recall_id"
_WARRANTY_INDEX = "ix_line_items_warranty_id"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    # hide_parameters: a failed statement's message leaves out its bound values.
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}", hide_parameters=True)
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}", hide_parameters=True)


def _fk_columns(engine: Engine, table: str) -> set[str]:
    """Single-column FKs on a table, by the column they constrain."""
    return {
        fk["constrained_columns"][0]
        for fk in inspect(engine).get_foreign_keys(table)
        if len(fk["constrained_columns"]) == 1
    }


def _add_line_item_columns(engine: Engine, conn: Connection, is_pg: bool) -> None:
    """The two flags, the two links and their indexes on service_line_items."""
    existing = {c["name"] for c in inspect(engine).get_columns(_ITEMS)}
    has_fk = _fk_columns(engine, _ITEMS)
    false = "FALSE" if is_pg else "0"

    for flag in _FLAGS:
        if flag not in existing:
            conn.execute(
                text(f"ALTER TABLE {_ITEMS} ADD COLUMN {flag} BOOLEAN NOT NULL DEFAULT {false}")
            )
            logger.info("158: added %s.%s", _ITEMS, flag)

    for column, target in _LINKS.items():
        if column not in existing:
            conn.execute(
                text(
                    f"ALTER TABLE {_ITEMS} ADD COLUMN {column} INTEGER "
                    f"REFERENCES {target}(id) ON DELETE SET NULL"
                )
            )
            logger.info("158: added %s.%s", _ITEMS, column)
        elif is_pg and column not in has_fk:
            # A column from a run that died halfway: give it its FK.
            conn.execute(
                text(
                    f"ALTER TABLE {_ITEMS} ADD FOREIGN KEY ({column}) "
                    f"REFERENCES {target}(id) ON DELETE SET NULL"
                )
            )
            logger.info("158: added the FK on %s.%s", _ITEMS, column)

    conn.execute(
        text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_UNIQUE_RECALL} ON {_ITEMS} (recall_id) "
            "WHERE recall_id IS NOT NULL"
        )
    )
    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {_WARRANTY_INDEX} ON {_ITEMS} (warranty_id)"))


def upgrade(engine: Engine | None = None) -> None:
    """Add the line item recall/warranty columns and recalls.resolved_via."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()
    is_pg = engine.dialect.name == "postgresql"
    inspector = inspect(engine)
    has_recalls = inspector.has_table("recalls")
    links_ready = (
        inspector.has_table(_ITEMS) and has_recalls and inspector.has_table("warranty_records")
    )

    needs_resolved_via = has_recalls and "resolved_via" not in {
        c["name"] for c in inspector.get_columns("recalls")
    }

    with engine.begin() as conn:
        if links_ready:
            _add_line_item_columns(engine, conn, is_pg)
        else:
            logger.info("158: line items, recalls or warranties missing; skip the links")
        if needs_resolved_via:
            conn.execute(text("ALTER TABLE recalls ADD COLUMN resolved_via VARCHAR(20)"))
            logger.info("158: added recalls.resolved_via")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 158 is forward-only.")


if __name__ == "__main__":
    upgrade()
