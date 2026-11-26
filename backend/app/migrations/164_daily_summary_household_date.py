"""Store telemetry_daily_summary.date as a DATE, keyed by household day.

The 01:00 summary job used to cut days at UTC midnight and stamp each row with
that midnight. It aggregates household days now and writes a plain date. On the
old SQLite DATETIME column a new ``2026-03-09`` key and an old
``2026-03-09 00:00:00`` one both pass the unique constraint, so every day would
double; this moves the old rows onto the same keys.

Existing rows keep their date part, so they stay UTC-day aggregates. Nothing
re-aggregates them: raw readings past the retention window are gone.

PostgreSQL casts the column in place. SQLite can't alter a column type, so the
table is rebuilt the way 154 does it, copying ``substr(date, 1, 10)`` and putting
back ``uq_daily_summary_vin_param_date``, ``idx_daily_summary_vehicle_date`` and
``idx_daily_summary_param``.

Rows that would share a date once they're dates (two stamps on one day, or
SQLite's same midnight with and without microseconds) are merged first, into the
lowest id, with the count-weighted avg.

Not FATAL: the summary job checks the column type and writes nothing until this
has run, and the rest of the app doesn't read the table. Idempotent: a column
that already reflects as DATE is left alone.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from sqlalchemy import Connection, Date, Engine, create_engine, inspect, text

FATAL = False

logger = logging.getLogger(__name__)

_TABLE = "telemetry_daily_summary"

# The model's table as create_all writes it, with date as DATE.
_SQLITE_DDL = f"""
CREATE TABLE {_TABLE}_new (
    id INTEGER NOT NULL,
    vin VARCHAR(17) NOT NULL,
    param_key VARCHAR(100) NOT NULL,
    date DATE NOT NULL,
    min_value FLOAT,
    max_value FLOAT,
    avg_value FLOAT,
    sample_count INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_daily_summary_vin_param_date UNIQUE (vin, param_key, date),
    FOREIGN KEY(vin) REFERENCES vehicles (vin) ON DELETE CASCADE
)
"""

_COLUMNS = "id, vin, param_key, date, min_value, max_value, avg_value, sample_count"

_INDEXES = (
    f"CREATE INDEX idx_daily_summary_vehicle_date ON {_TABLE} (vin, date)",
    f"CREATE INDEX idx_daily_summary_param ON {_TABLE} (vin, param_key, date)",
)


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Turn telemetry_daily_summary.date into a DATE, keeping each row's day."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()
    insp = inspect(engine)
    if not insp.has_table(_TABLE):
        return
    column_type = next((c["type"] for c in insp.get_columns(_TABLE) if c["name"] == "date"), None)
    # DATETIME and TIMESTAMP aren't Date subclasses, so only the new type passes.
    if column_type is None or isinstance(column_type, Date):
        return
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            _merge_same_day_rows(conn, 'CAST("date" AS DATE)')
            conn.execute(
                text(f'ALTER TABLE {_TABLE} ALTER COLUMN "date" TYPE DATE USING "date"::date')
            )
    else:
        with engine.begin() as conn:
            _merge_same_day_rows(conn, "substr(date, 1, 10)")
        _rebuild_sqlite(engine)
    logger.info("telemetry_daily_summary.date is a DATE now")


def _merge_same_day_rows(conn: Connection, day: str) -> None:
    """Fold rows that land on the same date into the one with the lowest id.

    Two stamps on one day (SQLite also holds the same midnight with and without
    microseconds) would hit the unique key once they're dates. The kept row
    takes the lowest min, the highest max, the count-weighted avg and the
    summed count.
    """
    groups = conn.execute(
        text(
            f"SELECT vin, param_key, {day} AS day, MIN(id) AS keep, MIN(min_value) AS lo, "
            "MAX(max_value) AS hi, SUM(avg_value * sample_count) AS weighted, "
            "SUM(CASE WHEN avg_value IS NOT NULL THEN sample_count ELSE 0 END) AS weight, "
            "AVG(avg_value) AS plain_avg, SUM(sample_count) AS n "
            f"FROM {_TABLE} GROUP BY vin, param_key, {day} HAVING COUNT(*) > 1"
        )
    ).all()
    for g in groups:
        avg = g.weighted / g.weight if g.weight else g.plain_avg
        conn.execute(
            text(
                f"UPDATE {_TABLE} SET min_value = :lo, max_value = :hi, avg_value = :avg, "
                "sample_count = :n WHERE id = :keep"
            ),
            {"lo": g.lo, "hi": g.hi, "avg": avg, "n": g.n, "keep": g.keep},
        )
        conn.execute(
            text(
                f"DELETE FROM {_TABLE} WHERE vin = :v AND param_key = :k "
                f"AND {day} = :day AND id <> :keep"
            ),
            {"v": g.vin, "k": g.param_key, "day": g.day, "keep": g.keep},
        )
    if groups:
        logger.info("Merged %d telemetry_daily_summary day(s) that shared a date", len(groups))


def _rebuild_sqlite(engine: Engine) -> None:
    raw = engine.raw_connection()
    try:
        dbapi = raw.driver_connection
        assert isinstance(dbapi, sqlite3.Connection)
        prev_iso = dbapi.isolation_level
        dbapi.isolation_level = None  # we run the transaction ourselves
        cur = dbapi.cursor()
        # foreign_keys can't change inside a transaction, so it goes first.
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute("BEGIN")
        try:
            cur.execute(f"DROP TABLE IF EXISTS {_TABLE}_new")
            cur.execute(_SQLITE_DDL)
            cur.execute(
                f"INSERT INTO {_TABLE}_new ({_COLUMNS}) "
                f"SELECT id, vin, param_key, substr(date, 1, 10), min_value, max_value, "
                f"avg_value, sample_count FROM {_TABLE}"
            )
            cur.execute(f"DROP TABLE {_TABLE}")
            cur.execute(f"ALTER TABLE {_TABLE}_new RENAME TO {_TABLE}")
            for sql in _INDEXES:
                cur.execute(sql)
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys=ON")
            dbapi.isolation_level = prev_iso
    finally:
        raw.close()


def downgrade() -> None:  # pragma: no cover
    """Forward-only: new rows are household days, so a timestamp would lie about them."""
    raise NotImplementedError("Migration 164 is forward-only.")


if __name__ == "__main__":
    upgrade()
