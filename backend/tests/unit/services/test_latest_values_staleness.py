"""`get_latest_values` must not render long-dead params as live gauges.

`vehicle_telemetry_latest` holds one row per (vin, param_key) and is never
pruned — the daily prune job only touches the historical table. So any param
ever written under a VIN renders on that vehicle's LiveLink page forever.

On Diamond that surfaced as a Mitsubishi showing a diesel dashboard: the Ram's
first ingest (2026-02-11) landed under the Mirage's VIN, leaving ~20 rows for
DPF pressure, NOx sensors, SCR, turbo RPM and DEF dosing that were still being
drawn as cards six months later, with no historical rows behind them.

Staleness is measured **relative to the vehicle's own newest sample**, not
wall-clock. A car parked for a month has uniformly old telemetry and must still
show its full dashboard; what should disappear is a param that stopped
reporting while the rest of the vehicle kept going.
"""

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetryLatest
from app.services.telemetry_service import TelemetryService
from app.utils.datetime_utils import utc_now


@pytest_asyncio.fixture
async def make_latest_vehicle(db_session: AsyncSession):
    """Async factory: (suffix, {param_key: age_timedelta}) -> vin."""

    async def _factory(suffix: str, params: dict[str, timedelta]) -> str:
        user = User(
            username=f"stale_user_{suffix}",
            email=f"stale_{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.flush()

        vin = f"STALETEST{suffix:0>8}"
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=user.id,
                nickname=f"Stale Car {suffix}",
                vehicle_type="Car",
            )
        )
        await db_session.flush()

        now = utc_now()
        for param_key, age in params.items():
            db_session.add(
                VehicleTelemetryLatest(
                    vin=vin,
                    param_key=param_key,
                    value=1.0,
                    timestamp=now - age,
                    received_at=now - age,
                )
            )
        await db_session.flush()
        return vin

    return _factory


@pytest.mark.asyncio
class TestLatestValuesStaleness:
    """Params that stopped reporting drop off; uniformly old ones do not."""

    async def test_param_left_behind_by_the_rest_is_dropped(self, db_session, make_latest_vehicle):
        """A param 6 months behind the vehicle's live data is not a live gauge."""
        vin = await make_latest_vehicle(
            "1",
            {
                "0C-ENGINERPM": timedelta(minutes=1),
                "05-ENGINECOOLANTTEMP": timedelta(minutes=1),
                "A5-COMDIESELEXHAUSTFLUIDDOSING": timedelta(days=200),
            },
        )

        values = await TelemetryService(db_session).get_latest_values(vin)

        keys = {v.param_key for v in values}
        assert "A5-COMDIESELEXHAUSTFLUIDDOSING" not in keys, "stale param still rendered"
        assert keys == {"0C-ENGINERPM", "05-ENGINECOOLANTTEMP"}

    async def test_uniformly_old_telemetry_is_all_kept(self, db_session, make_latest_vehicle):
        """A car parked for months must still show its whole dashboard.

        This is why the cutoff is relative to the vehicle's newest sample: an
        absolute wall-clock cutoff would blank the page of any parked vehicle.
        """
        vin = await make_latest_vehicle(
            "2",
            {
                "0C-ENGINERPM": timedelta(days=200),
                "05-ENGINECOOLANTTEMP": timedelta(days=201),
                "BATTERY_VOLTAGE": timedelta(days=200),
            },
        )

        values = await TelemetryService(db_session).get_latest_values(vin)

        assert len(values) == 3, "a parked vehicle lost its dashboard"
