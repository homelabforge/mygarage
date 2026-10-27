"""Convert PostgreSQL timestamps written in the server's zone to UTC (RD-6).

Every DateTime column is naive UTC, but `func.now()` (server defaults and
onupdates) and a migration's `CURRENT_TIMESTAMP` land in the SESSION's zone.
Until 3.10 nothing pinned PG sessions, so a server with any other zone (a `TZ`
on the container is enough) stored those stamps hours off. 3.10 pins every
session to UTC; this converts what's already stored, once.

The zone is read on the runner's own connection, which is still unpinned here
(the runner pins only once this is stamped), so it's the zone the app and the
migrations wrote in. Each listed column gets
`(c AT TIME ZONE zone) AT TIME ZONE 'UTC'`, which follows DST, and only where
that changes the value: a UTC server rewrites nothing, and London rewrites only
its summer rows. The repeated fall-back hour reads as standard time, so a stamp
from that one hour a year can come out an hour off.

The zone isn't trusted when it came from the client (`PGTZ`, `PGOPTIONS` or a
URL option): the app's driver ignores those, so the app may have written in
another zone. Then nothing is converted, a warning names the zone, and the
migration is stamped anyway, so it never runs again.

Which columns (R4), hard-coded because a historical migration can't follow
later models. Of the 81 `func.now()` columns:

- SERVER-ONLY (62): only `func.now()` or a migration's `CURRENT_TIMESTAMP` ever
  wrote them. All listed.
- `livelink_devices.created_at`, `odometer_records.created_at`: the app writes
  them in UTC since 3.10, but no release had that, so every stored row is a
  server stamp. Listed.
- `livelink_device_units.created_at`: the table is new in 3.10, and its only
  rows when this runs are migration 133's, written unpinned earlier in the same
  boot. Listed.
- MIXED (7, left alone): the app also writes UTC into `users.updated_at`,
  `vehicles.updated_at`, `livelink_devices.updated_at`,
  `vehicle_telemetry.received_at` and `vehicle_telemetry_latest.received_at`,
  `settings.updated_at` holds the container's local time as well, and
  `livelink_firmware_cache.checked_at` is the app's after the first check. A row
  can't be told apart, so converting would break the right ones.
- APP-ALWAYS (9, left alone): the app sets them on every write.

FATAL, and `upgrade(conn)`: the runner runs it and stamps it in one
transaction. Booting the pinned app with this pending would write UTC rows that
a later run then shifts, and so would a rerun after a crash between the two.
SQLite is a no-op: its `CURRENT_TIMESTAMP` was UTC all along. On a big table
the UPDATE leaves dead rows behind; autovacuum takes care of them.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, inspect, text

FATAL = True

logger = logging.getLogger(__name__)

#: table -> the server-stamped columns in it, by table name.
COLUMNS: dict[str, tuple[str, ...]] = {
    "address_book": ("created_at", "updated_at"),
    "attachments": ("uploaded_at",),
    "brake_axles": ("created_at", "updated_at"),
    "brake_jobs": ("created_at",),
    "brake_measurements": ("created_at",),
    "brake_reminder_marks": ("created_at", "updated_at"),
    "def_records": ("created_at",),
    "documents": ("uploaded_at",),
    "drive_sessions": ("created_at",),
    "external_vehicles": ("created_at", "updated_at"),
    "financing_records": ("created_at", "updated_at"),
    "fuel_records": ("created_at",),
    "hours_records": ("created_at",),
    "insurance_policies": ("created_at",),
    "insurance_policy_vehicles": ("created_at",),
    "livelink_device_units": ("created_at",),
    "livelink_devices": ("created_at",),
    "livelink_parameters": ("created_at", "updated_at"),
    "livelink_topic_maps": ("created_at", "updated_at"),
    "location_points": ("received_at",),
    "notes": ("created_at", "updated_at"),
    "odometer_records": ("created_at",),
    "recalls": ("created_at",),
    "reminder_packs": ("created_at", "updated_at"),
    "sd_log_ingest_state": ("updated_at",),
    "service_line_items": ("created_at",),
    "service_visits": ("created_at", "updated_at"),
    "settings": ("created_at",),
    "spot_rental_billings": ("created_at",),
    "spot_rentals": ("created_at",),
    "supplies": ("created_at", "updated_at"),
    "supply_purchases": ("created_at",),
    "supply_usages": ("created_at",),
    "tax_records": ("created_at",),
    "tire_mount_periods": ("created_at",),
    "tire_readings": ("created_at",),
    "tire_sets": ("created_at",),
    "tires": ("created_at", "updated_at"),
    "toll_tags": ("created_at", "updated_at"),
    "toll_transactions": ("created_at",),
    "users": ("created_at",),
    "vehicle_dtcs": ("created_at",),
    "vehicle_maintenance_rules": ("created_at", "updated_at"),
    "vehicle_photos": ("uploaded_at",),
    "vehicle_reminders": ("created_at", "updated_at"),
    "vehicles": ("created_at",),
    "vendors": ("created_at", "updated_at"),
    "warranty_records": ("created_at",),
    "widget_api_keys": ("created_at",),
}

_ZONE = text("SELECT current_setting('TimeZone'), source FROM pg_settings WHERE name = 'TimeZone'")

_CONVERT = (
    "UPDATE {table} SET {column} = ({column} AT TIME ZONE :zone) AT TIME ZONE 'UTC' "
    "WHERE {column} IS NOT NULL AND {column} <> ({column} AT TIME ZONE :zone) AT TIME ZONE 'UTC'"
)


def upgrade(conn: Connection) -> None:
    """Convert every listed column from the session's zone to UTC, on the runner's connection."""
    if conn.dialect.name != "postgresql":
        logger.info("SQLite stamps were UTC already; no timestamps to repair")
        return

    zone, source = conn.execute(_ZONE).one()
    if source == "client":
        logger.warning(
            "Timestamp repair skipped: the session zone %s came from the client "
            "(PGTZ, PGOPTIONS or a connection option), so it may not be the zone the "
            "app wrote in. Stored timestamps are left as they are.",
            zone,
        )
        return

    inspector = inspect(conn)
    total = 0
    for table, columns in COLUMNS.items():
        if not inspector.has_table(table):
            logger.info("Timestamp repair: %s missing; skip", table)
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        converted = 0
        for column in columns:
            if column not in present:
                logger.info("Timestamp repair: %s.%s missing; skip", table, column)
                continue
            result = conn.execute(text(_CONVERT.format(table=table, column=column)), {"zone": zone})
            converted += result.rowcount
        if converted:
            logger.info("Timestamp repair: %s, %s value(s) converted", table, converted)
        total += converted
    logger.info("Timestamp repair from %s to UTC: converted %s timestamp(s)", zone, total)
