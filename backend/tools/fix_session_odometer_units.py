"""Convert drive-session odometers recorded in miles to kilometres.

`SessionService._get_current_odometer` stamped `start_odometer` /
`end_odometer` with the device's raw reading and never converted it, and
`distance_km` is their difference. For a device reporting a bare `ODOMETER`
autopid in miles that means every session on record understates its distance by
the miles-to-kilometres factor, in a column whose name says kilometres.

The live defect is fixed (the service now converts on write, using the device's
declared `odometer_unit`). This repairs the rows written before that.

Scope is taken from the device, not a VIN: every session belonging to a device
whose `odometer_unit` is 'mi'. Run it AFTER migration 096 has classified your
devices and after the odometer backfill, so the kilometre records it compares
against are present.

Safe to run twice: whether conversion is still needed is read from the data
(the vehicle's kilometre odometer records against its session odometers), not
from a marker row that could drift.

`distance_km` is converted only when both odometer ends are present, because
that is the only case where it was derived from the odometer delta. A session
whose distance came from the GPS breadcrumb fallback is already in kilometres
and must not be touched.

Usage (dry run is the default; nothing is written without --apply):

    python tools/fix_session_odometer_units.py --db /data/mygarage.db
    python tools/fix_session_odometer_units.py --db /data/mygarage.db --apply

Back up the database first, and use the backup API rather than `cp`.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, ".")

from app.utils.units import UnitConverter  # noqa: E402

#: Above this, the vehicle's km odometer records tower over its session
#: odometers by roughly the miles factor (1.609), so the sessions are still in
#: miles. Once converted the ratio collapses to ~1.0. Derived from the data
#: rather than a marker row, so it cannot drift out of sync with reality and is
#: still correct on a restored or copied database.
NEEDS_CONVERSION_RATIO = 1.4

#: A units change shows up as a step of the miles factor between sessions that
#: are adjacent in time. An odometer never really moves 55% between two drives.
MIXED_STEP_LOW = 1.55
MIXED_STEP_HIGH = 1.67


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
    """Convert miles-recorded session odometers to kilometres."""
    args = _parse_args()
    engine = create_engine(f"sqlite:///{args.db}")

    with engine.begin() as conn:
        devices = [
            (row.device_id, row.vin)
            for row in conn.execute(
                text("SELECT device_id, vin FROM livelink_devices WHERE odometer_unit = 'mi'")
            )
        ]
        if not devices:
            print("No devices declare odometer_unit='mi'. Nothing to convert.")
            print("(Run migration 096 first so devices are classified.)")
            return 0

        def _mixed_units_step(device_id: str):
            """Return a (previous, next) session odometer straddling a units change.

            `session_max` alone cannot tell a converted history from a
            half-converted one: sessions closed after the ingest fix already
            hold kilometres and are numerically the largest, so one new drive
            makes the max-ratio test report "already converted" while every
            older session is still in miles. Converting would double the new
            ones; skipping leaves the old ones wrong.
            """
            row = conn.execute(
                text(
                    "SELECT prev, end_odometer FROM ("
                    "  SELECT end_odometer,"
                    "         LAG(end_odometer) OVER (ORDER BY started_at) AS prev"
                    "  FROM drive_sessions"
                    "  WHERE device_id = :d AND end_odometer IS NOT NULL"
                    ") stepped "
                    "WHERE prev IS NOT NULL AND prev > 0 AND end_odometer > 0 "
                    "  AND ((end_odometer / prev BETWEEN :lo AND :hi)"
                    "    OR (prev / end_odometer BETWEEN :lo AND :hi)) "
                    "LIMIT 1"
                ),
                {"d": device_id, "lo": MIXED_STEP_LOW, "hi": MIXED_STEP_HIGH},
            ).first()
            return (row.prev, row.end_odometer) if row else None

        def _needs_conversion(device_id: str, vin: str | None) -> bool:
            """True while the km odometer records still dwarf the session odometers."""
            session_max = conn.execute(
                text("SELECT MAX(end_odometer) FROM drive_sessions WHERE device_id = :d"),
                {"d": device_id},
            ).scalar()
            record_max = conn.execute(
                text("SELECT MAX(odometer_km) FROM odometer_records WHERE vin = :v"),
                {"v": vin},
            ).scalar()
            if not session_max or not record_max:
                return False
            return (float(record_max) / float(session_max)) > NEEDS_CONVERSION_RATIO

        mixed = [(d, _mixed_units_step(d)) for d, _v in devices]
        mixed = [(d, step) for d, step in mixed if step]
        for device_id, (before, after) in mixed:
            print(f"\n{device_id}")
            print(
                f"  ✗ MIXED UNITS: session odometers step {before:,.1f} -> {after:,.1f}, "
                f"a factor of {max(before, after) / min(before, after):.3f}."
            )
            print(
                "    Some sessions are already canonical kilometres and some are still "
                "miles, so neither converting nor skipping this device is safe."
            )
            print(
                "    This happens when a drive closed before this tool ran. Restore the "
                "pre-upgrade backup and run this first."
            )
        mixed_devices = {d for d, _ in mixed}

        pending = [(d, v) for d, v in devices if d not in mixed_devices and _needs_conversion(d, v)]
        if not pending:
            print(
                "No device needs conversion: every 'mi' device's session odometers "
                "already sit in the same range as its kilometre odometer records."
            )
            return 2 if mixed_devices else 0

        total = 0
        for device_id, _vin in pending:
            rows = conn.execute(
                text(
                    "SELECT COUNT(*) n, MIN(start_odometer) lo, MAX(end_odometer) hi, "
                    "SUM(distance_km) dist FROM drive_sessions "
                    "WHERE device_id = :d AND start_odometer IS NOT NULL"
                ),
                {"d": device_id},
            ).one()
            if not rows.n:
                continue
            lo_km = UnitConverter.miles_to_km(rows.lo or 0)
            hi_km = UnitConverter.miles_to_km(rows.hi or 0)
            dist_km = UnitConverter.miles_to_km(rows.dist or 0)
            print(f"\n{device_id}: {rows.n} session(s)")
            print(f"  odometer {rows.lo:,.0f} -> {rows.hi:,.0f} mi")
            print(f"           {lo_km:,.0f} -> {hi_km:,.0f} km")
            print(f"  total distance {rows.dist:,.0f} -> {dist_km:,.0f} km")
            total += rows.n

        if not total:
            print("Devices are classified 'mi' but none has sessions with an odometer.")
            return 2 if mixed_devices else 0

        if not args.apply:
            print(f"\nDRY RUN - {total} session(s) would be converted. Re-run with --apply.")
            return 2 if mixed_devices else 0

        factor = float(UnitConverter.MILES_TO_KM)
        for device_id, _vin in pending:
            # Both ends present: distance_km came from the odometer delta, so it
            # scales with them. Otherwise leave distance alone (GPS fallback).
            conn.execute(
                text(
                    "UPDATE drive_sessions SET distance_km = distance_km * :f "
                    "WHERE device_id = :d AND distance_km IS NOT NULL "
                    "AND start_odometer IS NOT NULL AND end_odometer IS NOT NULL"
                ),
                {"f": factor, "d": device_id},
            )
            conn.execute(
                text(
                    "UPDATE drive_sessions SET "
                    "start_odometer = start_odometer * :f, "
                    "end_odometer = CASE WHEN end_odometer IS NOT NULL "
                    "THEN end_odometer * :f ELSE NULL END "
                    "WHERE device_id = :d AND start_odometer IS NOT NULL"
                ),
                {"f": factor, "d": device_id},
            )

        print(f"\n✓ Converted {total} session(s).")

    if mixed_devices:
        print(
            f"\n✗ {len(mixed_devices)} device(s) were left untouched because their session "
            "history mixes miles and kilometres. They are listed above."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
