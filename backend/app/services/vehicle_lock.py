"""Serialise the writers that change where a vehicle's tires are, and imports.

Imports take the same lock for a different reason: on SQLite it opens the one
transaction every per-row savepoint nests in, so a failed import rolls back
whole instead of leaving the rows its released savepoints already committed.

The rule "one open mount period per corner per vehicle" cannot be a database
constraint: `tire_mount_periods` carries no `vin`. It is enforced by a
check-then-write in the service, and a check-then-write is only correct if
the two halves cannot interleave with another request's. This module is the
mechanism that stops them interleaving.

Why the VEHICLE row and not the tire row: two different tires being mounted
at FL would lock two different tire rows and never contend. The rule is per
vehicle, so the lock is on the shared parent.

Why not `with_for_update()` alone: SQLite has no `SELECT ... FOR UPDATE` and
SQLAlchemy compiles it away silently. Worse, the pysqlite driver runs every
statement before the first write in autocommit, so the occupant check and the
write were not serialised on SQLite at all. "SQLite's single writer serialises
anyway" is true of the WRITES and false of the check that precedes them.
Measured on 2026-09-12: two unlocked racers each saw zero rows and both wrote;
with `BEGIN IMMEDIATE` the second waited exactly the first's hold and then
read the first's row.

The contract, `LOCK_CONTRACT` below, is what the SQLite guard enforces and
what `test_tire_concurrency.py` spies on.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

LOCK_CONTRACT = (
    "lock_vehicle_for_write must precede every write of a tire change or an "
    "import: call it once, after the route's authorization check, and before any "
    "write or any tire or period read"
)

LOCK_BUSY_DETAIL = "Another change to this vehicle is in progress. Try again."

#: lock_not_available (a row lock wait that outlived `lock_timeout`) and
#: deadlock_detected.
_PG_CONTENTION_SQLSTATES = frozenset({"55P03", "40P01"})
#: Primary result codes; the extended BUSY_* and LOCKED_* codes share them.
_SQLITE_CONTENTION_CODES = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})
_SQLITE_CONTENTION_MESSAGES = (
    "database is locked",
    "database is busy",
    "database table is locked",
    "database schema is locked",
)


def is_lock_contention(exc: DBAPIError) -> bool:
    """Whether a driver error means another writer holds the lock, and nothing worse.

    Judged on the driver's own code, never on the SQLAlchemy wrapper class,
    because the class differs by driver for the same condition: asyncpg's
    lock timeout and deadlock arrive as a plain `DBAPIError`, psycopg's as an
    `OperationalError`. PostgreSQL drivers expose the SQLSTATE as `sqlstate`
    (asyncpg through SQLAlchemy, psycopg) or `pgcode` (asyncpg through
    SQLAlchemy, psycopg2); a present code decides alone. The sqlite3 module
    attaches `sqlite_errorcode`, masked to its primary code so the extended
    busy and locked codes count. Only an error carrying neither falls back to
    SQLite's message text.
    """
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if isinstance(sqlstate, str):
        return sqlstate in _PG_CONTENTION_SQLSTATES
    sqlite_code = getattr(orig, "sqlite_errorcode", None)
    if isinstance(sqlite_code, int):
        return (sqlite_code & 0xFF) in _SQLITE_CONTENTION_CODES
    message = str(orig).lower()
    return any(fragment in message for fragment in _SQLITE_CONTENTION_MESSAGES)


async def sqlite_begin_immediate(db: AsyncSession, contract: str) -> None:
    """`BEGIN IMMEDIATE` on the session's connection, or a RuntimeError if the call is misplaced.

    Shared by the vehicle lock and the sign-in settings lock. A driver
    connection already inside a transaction means the caller broke its lock's
    contract, so that raises `contract` instead of letting the driver's "cannot
    start a transaction within a transaction" surface as a 503. Contention is
    left to the caller, which knows what sentence to show.

    Raises:
        RuntimeError: The connection is already in a transaction, or has no
            driver connection at all.
    """
    raw = await (await db.connection()).get_raw_connection()
    driver = raw.driver_connection
    if driver is None:
        raise RuntimeError("SQLite lock: the pooled connection has no driver connection")
    if driver.in_transaction:
        raise RuntimeError(contract)
    await db.execute(text("BEGIN IMMEDIATE"))


async def lock_vehicle_for_write(db: AsyncSession, vin: str) -> None:
    """Take the vehicle's write lock for the rest of this transaction.

    SQLite: `BEGIN IMMEDIATE`, the database write lock, taken before any tire
    or period read so every read after it sees the last committed writer.
    Waits up to `busy_timeout`. If the driver connection is already inside a
    transaction the call is misplaced, and that is a programming error, not a
    runtime condition: it raises `RuntimeError` naming the contract rather
    than letting the driver's "cannot start a transaction within a
    transaction" surface as a 503.

    Anything else: `SELECT ... FOR NO KEY UPDATE` on the vehicle row, which
    waits for a concurrent holder's commit. Not `FOR UPDATE`: that also
    conflicts with the key-share lock every insert referencing the vehicle
    takes, so telemetry ingest and other records for the vehicle would wait
    out a whole import. `FOR NO KEY UPDATE` still conflicts with itself and
    with a delete of the vehicle.

    A lock that cannot be taken in time is a 503 with a sentence the user can
    act on. Before this helper the same condition was a generic 500. Only
    contention gets that sentence (`is_lock_contention`): a disk I/O error or
    a dropped connection propagates as itself, because telling the user to try
    again would send them into the same failure.
    """
    dialect = db.get_bind().dialect.name
    try:
        if dialect == "sqlite":
            await sqlite_begin_immediate(db, LOCK_CONTRACT)
        else:
            await db.execute(
                text("SELECT vin FROM vehicles WHERE vin = :vin FOR NO KEY UPDATE"),
                {"vin": vin},
            )
    except DBAPIError as exc:
        if not is_lock_contention(exc):
            raise
        logger.warning("Vehicle write lock unavailable for %s: %s", sanitize_for_log(vin), exc)
        raise HTTPException(status_code=503, detail=LOCK_BUSY_DETAIL) from exc
