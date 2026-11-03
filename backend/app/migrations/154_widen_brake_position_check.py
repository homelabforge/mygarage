"""Widen the brake position CHECK to take F and R, for one-wheel axles (#272).

Covers brake_jobs, brake_measurements and brake_reminder_marks. The CHECK keeps
its name, `check_<table>_position`.

FATAL: the API takes F and R now, so a widen that failed quietly would turn
every two-wheeler brake write into a 500. Idempotent: a table whose CHECK
already lists 'F' is left alone, and so is one with no position CHECK at all.

PostgreSQL drops and re-adds the constraint, found by name or else by its
definition. SQLite can't alter a CHECK, so the tables are rebuilt from their
own DDL with the IN-list swapped, the way 079 does it. Rebuilding copies the
rows, which would reset an AUTOINCREMENT counter to the highest id left, so the
old counter is carried over: a reminder mark tells new pad checks from old by
brake_measurements id, and a reused id would hide a new one.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, inspect, text

FATAL = True

logger = logging.getLogger(__name__)

_TABLES = ("brake_jobs", "brake_measurements", "brake_reminder_marks")
_POSITIONS = "'FL', 'FR', 'RL', 'RR', 'F', 'R'"

# The position CHECK's IN-list, inline the way 131 wrote it or table-level the
# way create_all does. The list has no nested parens, so [^)]* stops at its end.
_POSITION_RE = re.compile(r"(CHECK\s*\(\s*\"?position\"?\s+IN\s*\()([^)]*)(\))", re.IGNORECASE)


@dataclass(frozen=True)
class _Rebuild:
    """One SQLite table to rebuild: its new DDL and the indexes to put back."""

    table: str
    ddl: str
    index_sqls: list[str]


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Let the brake position CHECK on all three tables take F and R."""
    if engine is None:
        engine = _get_fallback_engine()
    insp = inspect(engine)
    tables = [t for t in _TABLES if insp.has_table(t)]
    if not tables:
        return
    if engine.dialect.name == "postgresql":
        _upgrade_pg(engine, tables)
    else:
        _upgrade_sqlite(engine, tables)


def _pg_position_check(conn: Connection, table: str) -> tuple[str, str] | None:
    """The table's position CHECK as (name, definition), by name first, then by definition."""
    sql = (
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = CAST(:table AS regclass) AND contype = 'c' AND {where}"
    )
    row = conn.execute(
        text(sql.format(where="conname = :name")),
        {"table": table, "name": f"check_{table}_position"},
    ).first()
    if row is None:
        row = conn.execute(
            text(sql.format(where="pg_get_constraintdef(oid) LIKE '%position%'")),
            {"table": table},
        ).first()
    return None if row is None else (row[0], row[1])


def _upgrade_pg(engine: Engine, tables: list[str]) -> None:
    with engine.begin() as conn:
        for table in tables:
            found = _pg_position_check(conn, table)
            if found is None or "'F'" in found[1]:
                continue
            conn.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT "{found[0]}"'))
            conn.execute(
                text(
                    f"ALTER TABLE {table} ADD CONSTRAINT check_{table}_position "
                    f"CHECK (position IN ({_POSITIONS}))"
                )
            )
            logger.info("Widened the brake position CHECK on %s", table)


def _plan_sqlite(conn: Connection, table: str) -> _Rebuild | None:
    """What rebuilding `table` takes, or None when its CHECK already lets F in."""
    ddl = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).scalar()
    if not ddl:
        return None
    match = _POSITION_RE.search(ddl)
    if match is None:
        if "'RR'" in ddl:
            # There's a corner CHECK but not one we can read. Skipping it
            # would leave F refused, so stop here instead.
            raise RuntimeError(f"154: can't find the position IN-list to widen on {table}")
        return None
    if "'F'" in match.group(2):
        return None
    new_ddl = _POSITION_RE.sub(lambda m: f"{m.group(1)}{_POSITIONS}{m.group(3)}", ddl, count=1)
    new_ddl, renamed = re.subn(
        rf'CREATE\s+TABLE\s+"?{table}"?(?=\s*\()',
        f'CREATE TABLE "{table}_new"',
        new_ddl,
        count=1,
        flags=re.IGNORECASE,
    )
    if not renamed:
        raise RuntimeError(f"154: can't read the CREATE TABLE for {table}")
    index_sqls = [
        r[0]
        for r in conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? "
            "AND sql IS NOT NULL",
            (table,),
        ).fetchall()
    ]
    return _Rebuild(table, new_ddl, index_sqls)


def _fk_violations(cur: sqlite3.Cursor, tables: list[str]) -> set[tuple[object, ...]]:
    out: set[tuple[object, ...]] = set()
    for table in tables:
        out |= {tuple(r) for r in cur.execute(f"PRAGMA foreign_key_check({table})").fetchall()}
    return out


def _rebuild(cur: sqlite3.Cursor, plan: _Rebuild) -> None:
    table, new = plan.table, f"{plan.table}_new"
    cur.execute(f"DROP TABLE IF EXISTS {new}")
    cur.execute(plan.ddl)
    cur.execute(f"INSERT INTO {new} SELECT * FROM {table}")
    # The copy leaves the new table's counter at the highest id it copied (0 if
    # none), so put the old counter back. The INSERT is only for a SQLite that
    # skips that row. Never INSERT OR REPLACE: no unique key, it'd add a row.
    has_sequence = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
    ).fetchone()
    old_seq = (
        cur.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
        if has_sequence
        else None
    )
    if old_seq is not None:
        updated = cur.execute(
            "UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (old_seq[0], new)
        ).rowcount
        if updated == 0:
            cur.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (new, old_seq[0]))
    cur.execute(f"DROP TABLE {table}")
    cur.execute(f"ALTER TABLE {new} RENAME TO {table}")
    for isql in plan.index_sqls:
        cur.execute(isql)


def _upgrade_sqlite(engine: Engine, tables: list[str]) -> None:
    with engine.connect() as conn:
        plans = [p for p in (_plan_sqlite(conn, t) for t in tables) if p is not None]
    if not plans:
        return

    raw = engine.raw_connection()
    try:
        dbapi = raw.driver_connection
        assert isinstance(dbapi, sqlite3.Connection)
        prev_iso = dbapi.isolation_level
        dbapi.isolation_level = None  # we run the transaction ourselves
        cur = dbapi.cursor()
        # foreign_keys can't change inside a transaction, so it goes first.
        # With it off, dropping brake_jobs doesn't cascade into its measurements.
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute("BEGIN")
        try:
            # Only complain about orphans the rebuild made, not ones already there.
            before = _fk_violations(cur, tables)
            for plan in plans:
                _rebuild(cur, plan)
            new_violations = _fk_violations(cur, tables) - before
            if new_violations:
                raise RuntimeError(f"154: FK violations after the rebuild: {new_violations}")
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys=ON")
            dbapi.isolation_level = prev_iso
    finally:
        raw.close()
    for plan in plans:
        logger.info("Widened the brake position CHECK on %s", plan.table)


def downgrade() -> None:  # pragma: no cover
    """Forward-only: narrowing it back would refuse every F and R row."""
    raise NotImplementedError("Migration 154 is forward-only.")


if __name__ == "__main__":
    upgrade()
