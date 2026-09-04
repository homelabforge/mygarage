"""The four-tool upgrade procedure, run the way the CHANGELOG tells people to.

The CHANGELOG prescribes an exact sequence:

    docker exec -w /app mygarage python tools/backfill_livelink_odometer.py --apply
    docker exec -w /app mygarage python tools/normalize_telemetry_odometer_units.py --apply
    docker exec -w /app mygarage python tools/fix_session_odometer_units.py --apply
    docker exec -w /app mygarage python tools/recompute_session_aggregates.py --apply

Nothing exercised that. The unit tests covered URL resolution and exit codes,
which is why `backfill_livelink_odometer.py` shipped calling
`date.fromisoformat()` on a PostgreSQL DATE and dying on the first row: every
test that touched it either used SQLite (where a DATE is a string) or never gave
it a row to read.

So these run the tools as **subprocesses**, in the documented order, with no
`--db`, against whichever database the suite is using. That is the real
invocation: it exercises `sys.path.insert(0, ".")`, argparse, the
`settings.database_url` fallback, and the driver's actual return types.

Dry run only. `--apply` is deliberately not tested here: these tools mutate
odometer history, and a test that writes into the shared suite database would
change what every later test sees. What is being guarded is that each tool can
*read* the live schema on this dialect and reach its own exit, which is the
class of failure that shipped.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.db_url import to_sync_url

BACKEND_ROOT = Path(__file__).resolve().parents[3]

#: The published order. Index 0 must run before index 1: the odometer backfill
#: reads telemetry as the device reported it, so it has to run while the
#: history is still device-native.
UPGRADE_SEQUENCE = (
    "backfill_livelink_odometer.py",
    "normalize_telemetry_odometer_units.py",
    "fix_session_odometer_units.py",
    "recompute_session_aggregates.py",
)


def _run_tool(name: str) -> subprocess.CompletedProcess[str]:
    """Run one tool exactly as the CHANGELOG says, in a clean subprocess."""
    from tests.conftest import TEST_DATABASE_URL

    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND_ROOT),
        # What `docker exec` sees: the app's own configured database, no --db.
        "MYGARAGE_DATABASE_URL": TEST_DATABASE_URL,
    }
    return subprocess.run(
        [sys.executable, f"tools/{name}"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest_asyncio.fixture
async def a_vehicle_with_telemetry(db_session: AsyncSession, test_user: dict[str, object]) -> str:
    """Enough real data that every tool has something to read.

    A tool with an empty table exits 0 without touching the code paths that
    parse driver return values, so seeding is what makes these tests non-vacuous.
    """
    import uuid

    from app.models.livelink_device import LiveLinkDevice
    from app.models.odometer import OdometerRecord
    from app.models.vehicle import Vehicle
    from app.models.vehicle_telemetry import VehicleTelemetry

    vin = f"UPGRADE{uuid.uuid4().hex[:10].upper()}"
    device_id = f"u-{vin[-12:]}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Upgrade test",
            vehicle_type="Car",
            year=2020,
            make="Ram",
            model="1500",
        )
    )
    db_session.add(LiveLinkDevice(device_id=device_id, vin=vin, odometer_unit="mi"))
    base = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)
    for offset, value in enumerate((1000.0, 1050.0, 1100.0)):
        db_session.add(
            VehicleTelemetry(
                vin=vin,
                device_id=device_id,
                param_key="ODOMETER",
                value=value,
                timestamp=base + timedelta(days=offset),
            )
        )
    db_session.add(OdometerRecord(vin=vin, date=base.date(), odometer_km=1609, source="manual"))
    await db_session.commit()
    return vin


@pytest.mark.asyncio
class TestUpgradeProcedure:
    """Every tool in the published sequence runs to completion on this dialect."""

    async def test_the_seed_is_visible_to_a_separate_connection(
        self, a_vehicle_with_telemetry: str
    ) -> None:
        """Guards the guard.

        The tools run in their own process on their own connection. If the
        fixture's rows were not committed, every tool below would find an empty
        table, exit 0, and prove nothing -- while looking green.
        """
        from sqlalchemy import create_engine, text

        from tests.conftest import TEST_DATABASE_URL

        engine = create_engine(to_sync_url(TEST_DATABASE_URL))
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM vehicle_telemetry WHERE vin = :v"),
                {"v": a_vehicle_with_telemetry},
            ).scalar_one()
        engine.dispose()
        assert count == 3

    @pytest.mark.parametrize("tool", UPGRADE_SEQUENCE)
    async def test_tool_runs_to_completion(self, tool: str, a_vehicle_with_telemetry: str) -> None:
        """A dry run exits cleanly rather than raising on a driver return type.

        Exit code 2 is a legitimate refusal ("mixed units present, run the other
        tool first") and is accepted. A traceback is not.
        """
        result = _run_tool(tool)
        assert "Traceback" not in result.stderr, (
            f"{tool} raised on this dialect:\n{result.stderr[-2000:]}"
        )
        assert result.returncode in (0, 2), (
            f"{tool} exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
        )
