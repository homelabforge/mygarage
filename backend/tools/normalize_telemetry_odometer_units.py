"""Convert stored odometer telemetry recorded in miles to canonical kilometres.

`vehicle_telemetry.value` and `vehicle_telemetry_latest.value` are unit-bearing
and metric-canonical like every other column, but the odometer was stored
exactly as the device sent it. For a WiCAN autopid on a US-market car that is
miles, which made the odometer the one parameter whose stored number's unit
depended on which dongle wrote it, and forced the LiveLink gauges to render it
as "(unknown unit)" rather than claim one.

`TelemetryService.store_telemetry` now normalises on ingest (see
`_normalize_odometer_units`), so this repairs the rows written before that,
using the exact same conversion the ingest path applies.

Run it AFTER migration 096 has classified your devices.

Safe to run twice: whether conversion is still outstanding is read from the
data, by comparing the vehicle's kilometre odometer records against its stored
odometer telemetry, not from a marker row that could drift.

That comparison can only speak for a key whose rows are all in one unit. If
ingest wrote canonical kilometres before this ran, the newest rows are metric
and the oldest are still miles; the comparison then reports "already
converted" and leaves the old rows wrong. A key in that state is detected and
reported rather than guessed at, and the script exits 2.

Usage (dry run is the default; nothing is written without --apply):

    python tools/normalize_telemetry_odometer_units.py --db /data/mygarage.db
    python tools/normalize_telemetry_odometer_units.py --db /data/mygarage.db --apply

Back up the database first, and use the backup API rather than `cp`.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, ".")

from app.utils.odometer_units import (  # noqa: E402
    ODOMETER_UNIT_KM,
    is_odometer_param_key,
    resolve_odometer_unit,
)
from app.utils.units import UnitConverter  # noqa: E402
from tools._tool_db import resolve_sync_url  # noqa: E402

#: Above this, the vehicle's km odometer records tower over its stored odometer
#: telemetry by roughly the miles factor, so the telemetry is still in miles.
NEEDS_CONVERSION_RATIO = 1.4

#: A unit change inside one series shows up as a step of the miles factor
#: between readings that are adjacent in time. An odometer never really moves
#: 55% in one sample interval, so a step in this band is a units discontinuity.
MIXED_STEP_LOW = 1.55
MIXED_STEP_HIGH = 1.67


def _mixed_units_step(conn, device_id: str, param_key: str):
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
        {
            "d": device_id,
            "p": param_key,
            "lo": MIXED_STEP_LOW,
            "hi": MIXED_STEP_HIGH,
        },
    ).first()
    return (row.prev, row.value) if row else None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        help=(
            "Database to operate on: a path to mygarage.db, or a full SQLAlchemy URL (postgresql+asyncpg://...). Omit to use the instance's configured database, which is the right choice when running inside the container."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the conversion. Without this the script only reports.",
    )
    return parser.parse_args()


def main() -> int:
    """Convert miles-recorded odometer telemetry to kilometres."""
    args = _parse_args()
    engine = create_engine(resolve_sync_url(args.db))
    factor = float(UnitConverter.MILES_TO_KM)

    with engine.begin() as conn:
        devices = [
            (row.device_id, row.vin, row.odometer_unit, row.kind)
            for row in conn.execute(
                text("SELECT device_id, vin, odometer_unit, kind FROM livelink_devices")
            )
        ]

        total_hist = 0
        total_latest = 0
        plan: list[tuple[str, str, str]] = []
        mixed_keys: list[tuple[str, str]] = []

        for device_id, vin, unit, kind in devices:
            keys = [
                row.param_key
                for row in conn.execute(
                    text("SELECT DISTINCT param_key FROM vehicle_telemetry WHERE device_id = :d"),
                    {"d": device_id},
                )
                if is_odometer_param_key(row.param_key)
            ]
            for param_key in keys:
                if resolve_odometer_unit(param_key, unit, kind) == ODOMETER_UNIT_KM:
                    continue  # already metric on the wire

                mixed = _mixed_units_step(conn, device_id, param_key)
                if mixed:
                    before, after = mixed
                    print(f"\n{device_id} / {param_key}")
                    print(
                        f"  ✗ MIXED UNITS: readings step {before:,.2f} -> {after:,.2f}, "
                        f"a factor of {max(before, after) / min(before, after):.3f}."
                    )
                    print(
                        "    Some rows are already canonical kilometres and some are still "
                        "miles, so neither converting nor skipping this key is safe."
                    )
                    print(
                        "    This happens when ingest wrote new readings before this tool "
                        "ran. Restore the pre-upgrade backup and run this first."
                    )
                    mixed_keys.append((device_id, param_key))
                    continue

                stored_max = conn.execute(
                    text(
                        "SELECT MAX(value) FROM vehicle_telemetry "
                        "WHERE device_id = :d AND param_key = :p"
                    ),
                    {"d": device_id, "p": param_key},
                ).scalar()
                record_max = conn.execute(
                    text("SELECT MAX(odometer_km) FROM odometer_records WHERE vin = :v"),
                    {"v": vin},
                ).scalar()
                if not stored_max or not record_max:
                    continue
                if (float(record_max) / float(stored_max)) <= NEEDS_CONVERSION_RATIO:
                    continue  # already converted

                hist = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM vehicle_telemetry "
                        "WHERE device_id = :d AND param_key = :p"
                    ),
                    {"d": device_id, "p": param_key},
                ).scalar()
                latest = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM vehicle_telemetry_latest "
                        "WHERE vin = :v AND param_key = :p"
                    ),
                    {"v": vin, "p": param_key},
                ).scalar()
                plan.append((device_id, vin, param_key))
                total_hist += hist or 0
                total_latest += latest or 0
                print(f"\n{device_id} / {param_key}")
                print(f"  {hist:,} historical row(s), {latest} latest row(s)")
                print(f"  max {float(stored_max):,.0f} mi -> {float(stored_max) * factor:,.0f} km")

        if not plan:
            print("No odometer telemetry needs conversion.")
            return 2 if mixed_keys else 0

        if not args.apply:
            print(
                f"\nDRY RUN - {total_hist:,} historical and {total_latest} latest row(s) "
                "would be converted. Re-run with --apply."
            )
            # A refused key must reach the caller's exit status, not just the
            # console: the upgrade note has operators dry-run first, and a
            # script gating --apply on this would otherwise apply what the dry
            # run just refused. Matches fix_session_odometer_units.py.
            return 2 if mixed_keys else 0

        for device_id, vin, param_key in plan:
            conn.execute(
                text(
                    "UPDATE vehicle_telemetry SET value = value * :f "
                    "WHERE device_id = :d AND param_key = :p"
                ),
                {"f": factor, "d": device_id, "p": param_key},
            )
            # Rebuild the cache from history rather than scaling it. The
            # historical rows are scoped by device, but `vehicle_telemetry_latest`
            # is keyed only by (vin, param_key): with two devices on one VIN
            # publishing the same key in different units, multiplying the shared
            # row can scale a value the metric device wrote. The newest
            # historical sample is what the cache is meant to hold anyway.
            conn.execute(
                text(
                    "UPDATE vehicle_telemetry_latest SET value = ("
                    "  SELECT value FROM vehicle_telemetry"
                    "  WHERE vin = :v AND param_key = :p"
                    "  ORDER BY timestamp DESC LIMIT 1"
                    ") "
                    "WHERE vin = :v AND param_key = :p AND EXISTS ("
                    "  SELECT 1 FROM vehicle_telemetry WHERE vin = :v AND param_key = :p"
                    ")"
                ),
                {"v": vin, "p": param_key},
            )
        print(f"\n✓ Converted {total_hist:,} historical and {total_latest} latest row(s).")

    if mixed_keys:
        print(
            f"\n✗ {len(mixed_keys)} key(s) were left untouched because their history mixes "
            "miles and kilometres. They are listed above and still need attention."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
