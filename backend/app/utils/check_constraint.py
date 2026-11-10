"""Drop an `IN (...)` CHECK constraint on one column, on either dialect.

Migration 079 did this for `vehicles.vehicle_type` inline; 146 (tax types)
and later ones need the same for other tables, so the mechanics live here.
Under `app/utils/` and not beside the migrations: the runner imports every
module in `app/migrations/` as a migration.

PostgreSQL: the constraint is found by its definition (so its name does not
matter) and dropped with ALTER TABLE.

SQLite has no in-place CHECK drop, so the table is rebuilt the way 079 does
it: the live CREATE TABLE is read from sqlite_master, the CHECK clause is
stripped (with the comma it strands repaired), and the table is recreated,
filled, swapped in and re-indexed inside one transaction with foreign keys
off, then `PRAGMA foreign_key_check` must come back clean before commit.
With foreign keys off, dropping the old table cascades to nothing, which is
what makes this safe on an FK parent.

Idempotent: a table without the CHECK is left alone.
"""

from __future__ import annotations

import re
import sqlite3

from sqlalchemy import Engine, inspect, text

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _check_re(column: str) -> re.Pattern[str]:
    """The CHECK whether written as a named table constraint
    (`CONSTRAINT check_x CHECK (...)`) or an unnamed inline column constraint
    (`CHECK (x IN (...))`). The IN-list has one paren level, so `[^)]*` is
    safe up to its closing paren."""
    return re.compile(
        rf"(?:CONSTRAINT\s+\w+\s+)?CHECK\s*\(\s*{re.escape(column)}\s+IN\s*\([^)]*\)\s*\)",
        re.IGNORECASE | re.DOTALL,
    )


def strip_check(ddl: str, column: str) -> str:
    """Remove the column's CHECK clause and repair the comma it leaves behind.

    Inline on the column, deleting the clause leaves `NOT NULL ,`, already
    valid. As a table-level constraint (`, CHECK (...),` from create_all),
    deleting it strands its comma: `,  ,` mid-table or `,  )` at the end,
    both syntax errors. The comma cannot be folded into the pattern, because
    in the inline shape it is the column separator; strip first, then
    normalise, which is safe for both (079's lesson, issue #137).
    """
    out = _check_re(column).sub("", ddl)
    out = re.sub(r",\s*,", ",", out)
    out = re.sub(r",\s*\)", "\n)", out)
    return out


def drop_check_constraint(engine: Engine, table: str, column: str) -> bool:
    """Drop the `column IN (...)` CHECK of `table`; True when one was dropped."""
    if not _IDENT.match(table) or not _IDENT.match(column):
        raise ValueError(f"identifier expected, got {table!r}.{column!r}")
    if not inspect(engine).has_table(table):
        return False
    if engine.dialect.name == "postgresql":
        return _drop_pg(engine, table, column)
    return _drop_sqlite(engine, table, column)


def _drop_pg(engine: Engine, table: str, column: str) -> bool:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass) AND contype = 'c' "
                "AND pg_get_constraintdef(oid) LIKE :needle"
            ),
            {"table": table, "needle": f"%{column}%"},
        ).fetchall()
        for (name,) in rows:
            conn.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"'))
        return bool(rows)


def _drop_sqlite(engine: Engine, table: str, column: str) -> bool:
    pattern = _check_re(column)
    with engine.connect() as conn:
        ddl = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).scalar()
        if not ddl or not pattern.search(ddl):
            return False
        index_sqls = [
            r[0]
            for r in conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? "
                "AND sql IS NOT NULL",
                (table,),
            ).fetchall()
        ]

    new_table = f"{table}_new"
    new_ddl = re.sub(
        rf'CREATE\s+TABLE\s+"?{table}"?',
        f'CREATE TABLE "{new_table}"',
        strip_check(ddl, column),
        count=1,
        flags=re.IGNORECASE,
    )

    raw = engine.raw_connection()
    try:
        dbapi = raw.driver_connection  # the sqlite3.Connection underneath
        if not isinstance(dbapi, sqlite3.Connection):
            raise TypeError(f"the SQLite rebuild needs sqlite3, got {type(dbapi).__name__}")
        prev_iso = dbapi.isolation_level
        dbapi.isolation_level = None  # autocommit: the transaction is driven below
        cur = dbapi.cursor()
        # foreign_keys only toggles outside a transaction, so first, then BEGIN.
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute("BEGIN")
        try:
            cur.execute(f'DROP TABLE IF EXISTS "{new_table}"')
            cur.execute(new_ddl)
            cur.execute(f'INSERT INTO "{new_table}" SELECT * FROM "{table}"')
            cur.execute(f'DROP TABLE "{table}"')
            cur.execute(f'ALTER TABLE "{new_table}" RENAME TO "{table}"')
            for isql in index_sqls:
                cur.execute(isql)
            violations = cur.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"FK violations after {table} rebuild: {violations}")
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys=ON")
            dbapi.isolation_level = prev_iso
    finally:
        raw.close()
    return True
