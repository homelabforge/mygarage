"""Stored makes and models in Title Case (#219 takeover).

NHTSA hands back makes in capitals and rows were saved that way
(``MITSUBISHI``, ``RAM``). The writers normalize now; this rewrites what is
already stored with the same helpers, ``app.utils.vehicle_names`` (live
vocabulary on purpose, as 061 does with fuel types). Makes take the canonical
spelling, and that includes the aliases in mixed case: a stored ``Chevy``
becomes ``Chevrolet``. Models only change when stored in ALL CAPS.

``vehicles`` is keyed by vin. ``external_vehicles`` is keyed by id: its vin is
nullable and not unique, so a vin-keyed update would skip some rows and give
two rows sharing a vin one row's values (Codex R1-H1).

``upgrade(conn)``: the rewrite and the stamp commit together. Not FATAL: a
failure leaves the old casing, which reads fine. Each table runs in its own
savepoint and a failure there is logged and swallowed, so 159 never stops the
migrations after it.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.utils.vehicle_names import normalize_make, normalize_model

logger = logging.getLogger(__name__)

#: Table and its key column.
_TABLES = (("vehicles", "vin"), ("external_vehicles", "id"))


def _rewrite(conn: Connection, table: str, key: str) -> int:
    """Normalize one table's make and model; return how many rows changed."""
    rows = conn.execute(text(f"SELECT {key}, make, model FROM {table}")).all()
    changed = 0
    for row_key, make, model in rows:
        new_make = normalize_make(make) if make else make
        new_model = normalize_model(model, make) if model else model
        if (new_make, new_model) == (make, model):
            continue
        conn.execute(
            text(f"UPDATE {table} SET make = :make, model = :model WHERE {key} = :key"),
            {"make": new_make, "model": new_model, "key": row_key},
        )
        changed += 1
    return changed


def _open_transaction(conn: Connection) -> None:
    """Start the real transaction the savepoints nest in (SQLite only).

    pysqlite's legacy transaction control only BEGINs before a write, so a
    SAVEPOINT issued first opens its own transaction and its RELEASE commits,
    ahead of the runner's stamp (Codex diff R1-M1). PostgreSQL is already in
    one.
    """
    if conn.dialect.name != "sqlite":
        return
    dbapi = conn.connection.dbapi_connection
    if dbapi is not None and not dbapi.in_transaction:
        conn.exec_driver_sql("BEGIN")


def upgrade(conn: Connection) -> None:
    """Title Case every stored make and model, on the runner's connection."""
    present = set(inspect(conn).get_table_names())
    _open_transaction(conn)
    for table, key in _TABLES:
        if table not in present:
            logger.info("159: %s missing; nothing to rewrite", table)
            continue
        try:
            with conn.begin_nested():
                changed = _rewrite(conn, table, key)
        except SQLAlchemyError:
            logger.warning("159: %s left as it was; the rewrite failed", table, exc_info=True)
            continue
        logger.info("159: %d %s row(s) rewritten", changed, table)


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 159 is forward-only; the original casing is not kept.")
