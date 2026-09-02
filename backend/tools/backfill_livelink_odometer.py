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
    ODOMETER_UNIT_KM,
    is_odometer_param_key,
    odometer_value_to_km,
    resolve_odometer_unit,
)
from tools._tool_db import resolve_sync_url  # noqa: E402

#: Below this, a "mi" device's stored telemetry already sits in the same range
#: as the vehicle's kilometre odometer records, so it has been converted and
#: converting it again would inflate it. Mirrors NEEDS_CONVERSION_RATIO in
#: normalize_telemetry_odometer_units.py, read in the opposite direction.
ALREADY_CANONICAL_RATIO = 1.4


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        help=(
            "Database to operate on: a path to mygarage.db, or a full SQLAlchemy URL (postgresql+asyncpg://...). Omit to use the instance's configured database, which is the right choice when running inside the container."
        ),
    )
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
    engine = create_engine(resolve_sync_url(args.db))

    with engine.begin() as conn:
        devices = {
            row.device_id: (row.vin, row.odometer_unit, row.kind)
            for row in conn.execute(
                text("SELECT device_id, vin, odometer_unit, kind FROM livelink_devices")
            )
        }

        # Refuse if the telemetry has already been converted. This reads
        # `value` as the device reported it and applies the device's declared
        # unit, so running it after normalize_telemetry_odometer_units.py would
        # multiply an already-canonical kilometre figure by 1.609 again. The
        # inflated reading then becomes the floor the monotonic guard enforces
        # forever, so the damage outlives the run. Reconstruct first, convert
        # second: the documented upgrade order says so, and this enforces it.
        already_canonical: list[str] = []
        for device_id, (dev_vin, unit, kind) in devices.items():
            if not dev_vin:
                continue
            for key_row in conn.execute(
                text("SELECT DISTINCT param_key FROM vehicle_telemetry WHERE device_id = :d"),
                {"d": device_id},
            ):
                param_key = key_row.param_key
                if not is_odometer_param_key(param_key):
                    continue
                if resolve_odometer_unit(param_key, unit, kind) == ODOMETER_UNIT_KM:
                    continue  # nothing would be converted for this key anyway
                stored_max = conn.execute(
                    text(
                        "SELECT MAX(value) FROM vehicle_telemetry "
                        "WHERE device_id = :d AND param_key = :p"
                    ),
                    {"d": device_id, "p": param_key},
                ).scalar()
                record_max = conn.execute(
                    text("SELECT MAX(odometer_km) FROM odometer_records WHERE vin = :v"),
                    {"v": dev_vin},
                ).scalar()
                if not stored_max or not record_max:
                    continue
                if float(record_max) / float(stored_max) <= ALREADY_CANONICAL_RATIO:
                    already_canonical.append(f"{device_id} / {param_key}")

        if already_canonical:
            print("✗ Telemetry for the following already reads as canonical kilometres:")
            for entry in already_canonical:
                print(f"    {entry}")
            print(
                "\n  These devices declare miles, so this tool would convert their readings\n"
                "  again and write odometer records about 1.609x too high. An inflated\n"
                "  record becomes the floor every later reading must beat, so it does not\n"
                "  simply get overwritten.\n"
                "\n  Run this BEFORE normalize_telemetry_odometer_units.py, not after."
            )
            return 2

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
