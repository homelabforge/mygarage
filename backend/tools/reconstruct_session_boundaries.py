"""Rebuild historic drive-session boundaries from surviving telemetry.

Every session recorded before migration 098 was bounded on *contact* -- any sign
the dongle could reach the broker. A parked WiCAN publishes a battery-voltage
heartbeat roughly every 95 minutes, so on this instance 83% of recorded sessions
(2,975 of 3,238) are a heartbeat rather than a drive, while real drives taken out
of broker range were recorded as nothing at all.

The live fix is mandatory and took effect at upgrade. This is opt-in and bounded
by telemetry retention, so a default 90-day instance can never reach further
back than 90 days: most instances will keep a session history whose definition
of "a drive" changes at the upgrade date. That cannot be fixed, only disclosed --
each session records the algorithm version and gap that produced it.

DRY RUN IS THE DEFAULT. Nothing is written without --apply.

    python tools/reconstruct_session_boundaries.py
    python tools/reconstruct_session_boundaries.py --vin ML32A5HJ9KH009478
    python tools/reconstruct_session_boundaries.py --apply

**Back up first, with the backup API rather than `cp`:**

    curl -X POST -H "Authorization: Bearer <token>" \\
         https://<host>/api/v1/backup/create-full

MyGarage runs SQLite in WAL mode, and a plain file copy of a database with a
live WAL sidecar is torn but plausible -- it restores, and it is wrong.

Exit codes, following the other repair tools here:

    0  nothing needed doing, or everything asked for was done
    2  at least one session was REFUSED

Exit 2 is not a failure. Refusal is the routine, safe outcome for a session
whose telemetry coverage cannot be proven, and every run records what it refused
and why in `livelink_reconstruction_runs` -- because in a quiet log a safe
refusal and a broken tool look identical.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import pkgutil
import sys

sys.path.insert(0, ".")

import app.models as _models  # noqa: E402

# Every model module must be imported before the first query: SQLAlchemy
# resolves relationship() targets by name at mapper-init time, and
# app/models/__init__.py exports only a subset. The app gets away with it
# because its routes import the rest on the way up; a standalone tool does not.
for _module in pkgutil.iter_modules(_models.__path__):
    importlib.import_module(f"app.models.{_module.name}")

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.livelink_service import LiveLinkService  # noqa: E402
from app.services.session_reconstruction import (  # noqa: E402
    SessionReconstructionService,
)
from app.utils.datetime_utils import utc_now  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vin", help="Limit to one VIN (default: every vehicle)")
    parser.add_argument(
        "--gap-minutes",
        type=int,
        help=(
            "Minutes stationary before a stop counts as a separate drive. "
            "Defaults to the instance's livelink_session_gap_minutes setting, "
            "so a replayed drive is cut the same way a live one is."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the rebuilt boundaries. Without this nothing is saved.",
    )
    return parser.parse_args()


def _report(plan, *, dry_run: bool) -> None:
    for note in plan.notes:
        print(f"  {note}")

    print("\n  Sessions:")
    print(f"    created  {plan.created}")
    print(f"    split    {plan.split}")
    print(f"    merged   {plan.merged}")
    print(f"    rebuilt  {plan.closed}")
    print(f"    refused  {plan.refused}")

    if plan.refusals:
        print("\n  Refused, by reason:")
        for reason, count in sorted(plan.reason_counts().items()):
            print(f"    {reason:<28} {count}")
        print(
            "\n  A refusal means the telemetry coverage for that session could not be\n"
            "  PROVEN, so it was left exactly as it is. That is the safe outcome, not\n"
            "  an error: retention prunes by timestamp, so a session straddling the\n"
            "  horizon keeps its later rows and loses its movement rows -- and\n"
            "  'telemetry present, no movement' is indistinguishable from a phantom."
        )

    if dry_run:
        print(
            "\n  DRY RUN -- nothing was written. Re-run with --apply to commit,\n"
            "  after taking a backup via POST /api/v1/backup/create-full (not `cp`)."
        )


async def run(args: argparse.Namespace) -> int:
    """Rebuild boundaries and report. Returns the process exit code."""
    started_at = utc_now().replace(tzinfo=None)

    async with AsyncSessionLocal() as db:
        livelink = LiveLinkService(db)
        gap_minutes = args.gap_minutes or await livelink.get_session_gap_minutes()
        retention_days = await livelink.get_retention_days()

        print(
            f"Reconstructing pre-098 session boundaries "
            f"(gap {gap_minutes}m, retention {retention_days}d"
            f"{', vin ' + args.vin if args.vin else ''})"
        )

        service = SessionReconstructionService(db)
        plan = await service.reconstruct(
            gap_minutes=gap_minutes,
            retention_days=retention_days,
            vin=args.vin,
        )

        if args.apply:
            await service.record_run(
                plan, dry_run=False, gap_minutes=gap_minutes, started_at=started_at
            )
            await db.commit()
        else:
            # Discard the rebuild, then record the plan in a fresh transaction.
            #
            # The order matters: recording BEFORE the rollback would roll the
            # audit row back along with the changes it describes, leaving a dry
            # run that reports on screen and remembers nothing. And the rebuild
            # itself has to run against the real rows -- the dry run exercises
            # the same code path an applied run does, so a preview cannot
            # disagree with the thing it previews.
            await db.rollback()
            await service.record_run(
                plan, dry_run=True, gap_minutes=gap_minutes, started_at=started_at
            )
            await db.commit()

        _report(plan, dry_run=not args.apply)

    return 2 if plan.refused else 0


def main() -> int:
    """Entry point."""
    return asyncio.run(run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
