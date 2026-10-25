"""Resolve which database a maintenance tool should operate on.

Shared by the raw-SQL repair tools. Each of them previously did

    engine = create_engine(f"sqlite:///{args.db}")

which is wrong on a PostgreSQL instance in the worst way: SQLAlchemy creates an
empty SQLite file at the given path and the tool then fails with
`no such table: livelink_devices`, so the operator sees a missing-table error
rather than "this tool cannot reach your database". PostgreSQL is a supported,
CI-tested deployment, so those instances had no repair path at all.

`--db` now accepts three forms:

* a **path** (`/data/mygarage.db`) -- the form the published upgrade note uses,
  kept working deliberately;
* a **URL** (`postgresql+asyncpg://...`), converted to the sync driver;
* **omitted**, falling back to the app's own configured database, which is the
  right answer when the tool runs inside the container.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import date, datetime
from pathlib import Path
from types import ModuleType

from sqlalchemy import inspect, text
from sqlalchemy.engine import URL, Connection

from app.utils.db_url import to_sync_url

#: A URL scheme: letters, digits, +/-/. then "://". Requiring the slashes keeps
#: a Windows-style path ("C:/data/mygarage.db") from being read as a scheme.
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")

#: Dialects the tools' raw SQL is written against. Anything else is refused by
#: name rather than failing later inside a statement.
_SUPPORTED_DIALECTS = ("sqlite", "postgresql")


def resolve_sync_url(db_arg: str | None) -> str:
    """Return the sync SQLAlchemy URL a tool should connect with.

    Args:
        db_arg: The value of ``--db``: a filesystem path, a SQLAlchemy URL, or
            None to use the app's configured database.

    Returns:
        A sync-driver SQLAlchemy URL.

    Raises:
        ValueError: If the resolved URL names a dialect these tools do not
            support, or if the configured database URL is empty.
    """
    if db_arg is None:
        from app.config import settings

        url = to_sync_url(settings.database_url)
    elif _URL_SCHEME_RE.match(db_arg):
        url = to_sync_url(db_arg)
    else:
        # A path is a path. SQLAlchemy 2.1 would percent-decode it inside a URL,
        # so let URL.create escape it rather than pasting it in raw.
        url = URL.create("sqlite", database=db_arg).render_as_string(hide_password=False)

    if not url.startswith(_SUPPORTED_DIALECTS):
        dialect = url.split("://", 1)[0]
        raise ValueError(
            f"unsupported database dialect {dialect!r}; "
            f"these tools support {' and '.join(_SUPPORTED_DIALECTS)}"
        )
    return url


def as_date(value: object) -> date:
    """Return a ``date`` for whatever the driver gave back for a DATE column.

    SQLite has no date type: both a ``DATE`` column and ``date(timestamp)`` come
    back as ``str``. psycopg2 adapts PostgreSQL ``DATE`` to ``datetime.date``,
    and ``date.fromisoformat`` raises ``TypeError`` on one of those. The tools
    run on both dialects, so they must not assume either representation.

    Args:
        value: A ``date``, a ``datetime``, or an ISO-8601 date string.

    Returns:
        The corresponding ``date``.

    Raises:
        ValueError: If ``value`` is None, or is a string that is not a date.
            Null is refused rather than tolerated: a null grouping key would
            collapse every null row into one fabricated day.
    """
    if value is None:
        raise ValueError("expected a date, got null")
    # datetime is a subclass of date, so narrow it before the isinstance below.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


#: The migration that records main's miles reading of a bare ODOMETER.
_LEGACY_ODOMETER_MIGRATION = "133_record_wican_legacy_odometer_unit"


def _migration_applied(conn: Connection, name: str) -> bool:
    """Whether the runner has recorded ``name`` in ``schema_migrations``."""
    if not inspect(conn).has_table("schema_migrations"):
        return False
    found = conn.execute(
        text("SELECT 1 FROM schema_migrations WHERE migration_name = :n"), {"n": name}
    ).first()
    return found is not None


def _load_legacy_migration() -> ModuleType:
    """Migration 133, loaded from its file.

    Loaded by path (the name starts with a digit) so the migration stays
    self-contained and the tools can't drift from what it will record.
    """
    import app.migrations

    path = Path(app.migrations.__file__).parent / f"{_LEGACY_ODOMETER_MIGRATION}.py"
    spec = importlib.util.spec_from_file_location(_LEGACY_ODOMETER_MIGRATION, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def legacy_migration_applied(conn: Connection) -> bool:
    """Whether the runner has recorded migration 133, so its legacy rows are in place."""
    return _migration_applied(conn, _LEGACY_ODOMETER_MIGRATION)


def _missing_device_columns(conn: Connection) -> list[str]:
    """The `livelink_devices` columns the tools and migration 133 need but this database lacks."""
    return list(_load_legacy_migration().missing_device_columns(conn))


def print_unreadable_note(conn: Connection) -> bool:
    """Say why this database is too old to read, on stderr. True when it is.

    The odometer tools call it before their first device query, which names
    these columns, so an old database gets the reason, not an OperationalError
    (carry 17).
    """
    missing = _missing_device_columns(conn)
    if not missing:
        return False
    columns = ", ".join(f"livelink_devices.{col}" for col in missing)
    print(
        f"Note: this database has no {columns}, so it predates the migrations these "
        "tools read. To read it the way this version will, start this version once "
        "(with MYGARAGE_MAINTENANCE_MODE=1, so no reading lands) and run the tools then.",
        file=sys.stderr,
    )
    return True


def device_key_units(conn: Connection) -> dict[tuple[str, str], str | None]:
    """Each device's R12 unit, by ``(device_id, param_key)``, as live ingest will see it.

    The stored rows, so a tool converting an odometer agrees with the live
    path (``resolve_odometer_unit``'s ``key_unit``). Before migration 133 has
    run (a tool run before the first boot, often with no
    ``livelink_device_units`` at all) its legacy rows aren't there yet, so the
    keys it will record read in main's unit here too. Without that, the km
    key rule would skip every bare ``ODOMETER`` as already metric.

    A database too old for 133's query (no ``kind`` on ``livelink_devices``,
    say) gets no emulation and a note on stderr rather than a crash.
    """
    units: dict[tuple[str, str], str | None] = {}
    if inspect(conn).has_table("livelink_device_units"):
        rows = conn.execute(text("SELECT device_id, param_key, unit FROM livelink_device_units"))
        units = {(row.device_id, row.param_key): row.unit for row in rows}
    if not legacy_migration_applied(conn):
        migration = _load_legacy_migration()
        if migration.missing_device_columns(conn):
            print_unreadable_note(conn)
            return units
        for device_id, key, unit in migration.legacy_odometer_rows(conn):
            units.setdefault((device_id, key), unit)
    return units


def migrated_odometer_mi_devices(conn: Connection) -> set[str]:
    """Devices whose raw `ODOMETER_MI` migration 133 moves to km (FW-A1).

    Before the first boot their rows are still miles and 133 converts them,
    so a tool converting them first would have them done twice; after it,
    they're km. Main never recorded an odometer from them either. So the
    tools leave these devices' `ODOMETER_MI` alone either way.
    """
    return set(_load_legacy_migration().odometer_mi_devices(conn))


#: A unit change inside one series shows up as a step of the miles factor
#: between readings that are adjacent in time. An odometer never really moves
#: 55% in one sample interval, so a step in this band is a units discontinuity.
MIXED_STEP_LOW = 1.55
MIXED_STEP_HIGH = 1.67


def mixed_units_step(
    conn: Connection, device_id: str, param_key: str
) -> tuple[float, float] | None:
    """Return a (previous, next) reading straddling a units change, or None.

    `stored_max` alone cannot tell a converted series from a half-converted
    one: post-fix rows are already kilometres and are numerically the largest,
    so one new reading after the ingest fix makes the max-ratio test report
    "already converted" while every older row is still in miles. Converting
    such a series would double the new rows; skipping it leaves the old ones
    wrong. Neither is safe, so detect it and stop.
    """
    row = conn.execute(
        text(
            "SELECT prev, value FROM ("
            "  SELECT value, LAG(value) OVER (ORDER BY timestamp) AS prev"
            "  FROM vehicle_telemetry WHERE device_id = :d AND param_key = :p"
            ") stepped "
            "WHERE prev IS NOT NULL AND prev > 0 AND value > 0 "
            "  AND ((value / prev BETWEEN :lo AND :hi)"
            "    OR (prev / value BETWEEN :lo AND :hi)) "
            "LIMIT 1"
        ),
        {"d": device_id, "p": param_key, "lo": MIXED_STEP_LOW, "hi": MIXED_STEP_HIGH},
    ).first()
    return (float(row.prev), float(row.value)) if row else None
