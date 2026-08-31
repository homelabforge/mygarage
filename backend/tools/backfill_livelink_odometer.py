"""Rebuild the odometer records a units regression silently discarded.

Between `6f04e53` ("Fix/v2.26.2 currency and metric canonical", 2026-04-25) and
migration 096, a device publishing a bare `ODOMETER` autopid had every odometer
auto-record dropped: the reading was read as kilometres, landed below the
vehicle's real odometer, and the monotonic guard returned without logging. The
raw telemetry kept arriving the whole time, so the records can be reconstructed
from it.

For each affected vehicle this walks `vehicle_telemetry`, takes the highest
odometer reading per calendar day, converts it with the device's now-declared
units, and writes one `source='livelink'` record per day.

It will NOT touch a day that already has any odometer record — a manual or
fuel-sourced entry is more authoritative than a reconstruction, and this is
exactly the kind of script that should never overwrite a human's number.

Usage (dry run is the default; nothing is written without --apply):

    python tools/backfill_livelink_odometer.py --db /data/mygarage.db
    python tools/backfill_livelink_odometer.py --db /data/mygarage.db --apply

Back up the database first, and use the backup API rather than `cp`: a live
WAL sidecar makes a plain file copy torn but plausible.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date

from sqlalchemy import create_engine, text

sys.path.insert(0, ".")

from app.utils.odometer_units import (  # noqa: E402
    is_odometer_param_key,
    odometer_value_to_km,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to mygarage.db")
    parser.add_argument("--vin", help="Limit to one VIN (default: every affected vehicle)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the records. Without this the script only reports.",
    )
    return parser.parse_args()


def main() -> int:
    """Reconstruct and optionally write the missing odometer records."""
    args = _parse_args()
    engine = create_engine(f"sqlite:///{args.db}")

    with engine.begin() as conn:
        devices = {
            row.device_id: (row.vin, row.odometer_unit, row.kind)
            for row in conn.execute(
                text("SELECT device_id, vin, odometer_unit, kind FROM livelink_devices")
            )
        }

        # Highest reading per (vin, day), carrying the key and device it came from.
        best: dict[tuple[str, date], tuple[float, str, str]] = {}
        for row in conn.execute(
            text(
                "SELECT vin, device_id, param_key, value, date(timestamp) AS day "
                "FROM vehicle_telemetry WHERE value IS NOT NULL"
            )
        ):
            if not is_odometer_param_key(row.param_key):
                continue
            if args.vin and row.vin != args.vin:
                continue
            day = date.fromisoformat(row.day)
            key = (row.vin, day)
            if key not in best or row.value > best[key][0]:
                best[key] = (row.value, row.param_key, row.device_id)

        if not best:
            print("No odometer telemetry found — nothing to reconstruct.")
            return 0

        # Days that already carry a record of any source are left alone.
        taken: set[tuple[str, date]] = {
            (row.vin, date.fromisoformat(row.date))
            for row in conn.execute(text("SELECT vin, date FROM odometer_records"))
        }

        # The highest reading already on record at or before each day, so the
        # reconstruction upholds the same "only a new higher reading" invariant
        # the live service enforces. Without this the integer rounding here can
        # land a hair BELOW a neighbouring fractional record written by the
        # pre-v2.26.2 code path (which stored converted floats), manufacturing
        # sub-kilometre odometer regressions on days the vehicle barely moved.
        existing: dict[str, list[tuple[date, float]]] = defaultdict(list)
        for row in conn.execute(
            text("SELECT vin, date, odometer_km FROM odometer_records ORDER BY date")
        ):
            existing[row.vin].append((date.fromisoformat(row.date), float(row.odometer_km)))

        def _floor_for(vin: str, day: date) -> float:
            """Highest odometer already recorded on or before ``day``."""
            return max((km for d, km in existing.get(vin, []) if d <= day), default=0.0)

        planned: dict[str, list[tuple[date, int, str]]] = defaultdict(list)
        running: dict[str, float] = {}
        for (vin, day), (value, param_key, device_id) in sorted(best.items()):
            if (vin, day) in taken:
                continue
            _dev_vin, unit, kind = devices.get(device_id, (None, None, None))
            km = odometer_value_to_km(value, param_key, unit, kind)
            if km is None or km <= 0:
                continue
            rounded = int(round(km))
            floor = max(_floor_for(vin, day), running.get(vin, 0.0))
            if rounded <= floor:
                continue  # not a new higher reading — same rule the service applies
            running[vin] = float(rounded)
            planned[vin].append((day, rounded, param_key))

        if not planned:
            print("Every day with odometer telemetry already has a record. Nothing to do.")
            return 0

        total = 0
        for vin, rows in sorted(planned.items()):
            print(f"\n{vin}: {len(rows)} record(s) to add")
            print(f"  {rows[0][0]} → {rows[-1][0]}")
            print(f"  {rows[0][1]:,} km → {rows[-1][1]:,} km  (from {rows[0][2]})")
            total += len(rows)

        if not args.apply:
            print(f"\nDRY RUN — {total} record(s) would be created. Re-run with --apply.")
            return 0

        for vin, rows in sorted(planned.items()):
            for day, km, param_key in rows:
                conn.execute(
                    text(
                        "INSERT INTO odometer_records (vin, date, odometer_km, source, notes) "
                        "VALUES (:vin, :day, :km, 'livelink', :notes)"
                    ),
                    {
                        "vin": vin,
                        "day": day.isoformat(),
                        "km": km,
                        "notes": f"Backfilled from LiveLink telemetry ({param_key})",
                    },
                )
        print(f"\n✓ Wrote {total} odometer record(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
