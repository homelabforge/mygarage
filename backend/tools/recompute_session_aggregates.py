"""Recompute closed drive-session aggregates from the telemetry now on record.

Session aggregates (max/avg speed, RPM, coolant, throttle, fuel) were computed
once, when the session closed, from whatever telemetry had arrived by then. A
WiCAN off home WiFi buffers its readings and replays them later with their
original timestamps, so a session's own telemetry routinely lands after it has
already been summarised. On Diamond a drive that peaked at 85 km/h was recorded
as max_speed 20: only the samples taken pulling out of the driveway had arrived
when the session closed.

`TelemetryService.store_telemetry` now refreshes a closed session when a late
reading falls inside its window, so this is only needed once, to repair the
sessions summarised before that.

It recomputes through `SessionService.refresh_aggregates`, the same code the
live path uses, rather than reimplementing the aggregation.

Sessions whose telemetry has since been pruned are left exactly as they are:
the aggregate step only assigns a value when it finds samples, so an empty
window cannot blank a session that still carries figures from when it closed.

Usage (dry run is the default; nothing is written without --apply):

    python tools/recompute_session_aggregates.py
    python tools/recompute_session_aggregates.py --apply --vin ML32A5HJ9KH009478

Back up the database first, and use the backup API rather than `cp`.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import pkgutil
import sys

from sqlalchemy import select

sys.path.insert(0, ".")

import app.models as _models  # noqa: E402

# Every model module must be imported before the first query: SQLAlchemy
# resolves relationship() targets by name at mapper-init time, and
# app/models/__init__.py exports only a subset (it imports CSRFToken, whose
# relationship needs User, which it does not import). The app gets away with it
# because its routes import the rest on the way up; a standalone tool does not,
# so walk the package rather than chasing names one failure at a time.
for _module in pkgutil.iter_modules(_models.__path__):
    importlib.import_module(f"app.models.{_module.name}")

from app.database import AsyncSessionLocal  # noqa: E402
from app.models.drive_session import DriveSession  # noqa: E402
from app.services.session_service import SessionService  # noqa: E402

#: Aggregate columns this recomputes, for the before/after comparison.
TRACKED = (
    "max_speed",
    "avg_speed",
    "max_rpm",
    "avg_rpm",
    "max_coolant_temp",
    "avg_coolant_temp",
    "max_throttle",
    "avg_throttle",
    "avg_fuel_level",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vin", help="Limit to one VIN (default: every vehicle)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the recomputed aggregates. Without this nothing is saved.",
    )
    return parser.parse_args()


def _snapshot(session: DriveSession) -> dict[str, float | None]:
    return {name: getattr(session, name) for name in TRACKED}


async def run(args: argparse.Namespace) -> int:
    """Recompute every closed session's aggregates and report what moved."""
    async with AsyncSessionLocal() as db:
        query = select(DriveSession).where(DriveSession.ended_at.is_not(None))
        if args.vin:
            query = query.where(DriveSession.vin == args.vin)
        sessions = list((await db.execute(query.order_by(DriveSession.id))).scalars().all())

        if not sessions:
            print("No closed sessions found.")
            return 0

        service = SessionService(db)
        changed: list[tuple[int, dict[str, float | None], dict[str, float | None]]] = []

        for session in sessions:
            before = _snapshot(session)
            await service.refresh_aggregates(session)
            after = _snapshot(session)
            if before != after:
                changed.append((session.id, before, after))

        print(f"Examined {len(sessions):,} closed session(s); {len(changed):,} would change.")

        speed_gains = [
            (sid, b["max_speed"], a["max_speed"])
            for sid, b, a in changed
            if a["max_speed"] is not None
            and b["max_speed"] is not None
            and a["max_speed"] > b["max_speed"]
        ]
        if speed_gains:
            speed_gains.sort(key=lambda row: (row[2] or 0) - (row[1] or 0), reverse=True)
            print(f"\n{len(speed_gains):,} session(s) gain a higher max speed. Largest moves:")
            for sid, before_v, after_v in speed_gains[:10]:
                print(f"  session {sid}: max speed {before_v:,.0f} -> {after_v:,.0f} km/h")

        if not args.apply:
            await db.rollback()
            print("\nDRY RUN - nothing written. Re-run with --apply.")
            return 0

        await db.commit()
        print(f"\n✓ Recomputed {len(changed):,} session(s).")
    return 0


def main() -> int:
    """Entry point."""
    return asyncio.run(run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
