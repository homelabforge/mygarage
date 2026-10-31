"""Clear repair links that don't name an inspection on the same visit (S1d-04, D1).

A repair's ``triggered_by_inspection_id`` used to take any item, so a link
could point at a plain repair, at an item on another visit, or at the item
itself. The API drops those now; this clears the ones already stored.

``upgrade(conn)``: the UPDATE and the stamp commit together. Not FATAL: a
failure leaves the stray links, the API drops them on the next save, and 142
retries next boot.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, inspect, text

logger = logging.getLogger(__name__)

_CLEAR = text(
    "UPDATE service_line_items SET triggered_by_inspection_id = NULL"
    " WHERE triggered_by_inspection_id IS NOT NULL"
    " AND (triggered_by_inspection_id = id OR NOT EXISTS ("
    "SELECT 1 FROM service_line_items t"
    " WHERE t.id = service_line_items.triggered_by_inspection_id"
    " AND t.visit_id = service_line_items.visit_id"
    " AND t.is_inspection = :yes))"
)


def upgrade(conn: Connection) -> None:
    """Null every stray inspection link, on the runner's connection."""
    if not inspect(conn).has_table("service_line_items"):
        logger.info("142: service_line_items missing; nothing to clear")
        return
    cleared = conn.execute(_CLEAR, {"yes": True}).rowcount
    logger.info("142: cleared %d stray inspection link(s)", cleared)


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 142 is forward-only.")
