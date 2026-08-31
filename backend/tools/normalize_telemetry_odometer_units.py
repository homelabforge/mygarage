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

#: Above this, the vehicle's km odometer records tower over its stored odometer
#: telemetry by roughly the miles factor, so the telemetry is still in miles.
NEEDS_CONVERSION_RATIO = 1.4


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to mygarage.db")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the conversion. Without this the script only reports.",
    )
    return parser.parse_args()


def main() -> int:
    """Convert miles-recorded odometer telemetry to kilometres."""
    args = _parse_args()
    engine = create_engine(f"sqlite:///{args.db}")
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
            return 0

        if not args.apply:
            print(
                f"\nDRY RUN - {total_hist:,} historical and {total_latest} latest row(s) "
                "would be converted. Re-run with --apply."
            )
            return 0

        for device_id, vin, param_key in plan:
            conn.execute(
                text(
                    "UPDATE vehicle_telemetry SET value = value * :f "
                    "WHERE device_id = :d AND param_key = :p"
                ),
                {"f": factor, "d": device_id, "p": param_key},
            )
            conn.execute(
                text(
                    "UPDATE vehicle_telemetry_latest SET value = value * :f "
                    "WHERE vin = :v AND param_key = :p"
                ),
                {"f": factor, "v": vin, "p": param_key},
            )
        print(f"\n✓ Converted {total_hist:,} historical and {total_latest} latest row(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
