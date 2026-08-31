"""Drive-session odometer must be found and stored in kilometres.

`SessionService._get_current_odometer` reads the vehicle's latest odometer
sample to stamp `start_odometer` / `end_odometer`, and `distance_km` is their
difference. Two defects fell out of the same units/key confusion that killed
odometer auto-recording (see test_telemetry_odometer_units.py):

  - the lookup matched param keys *exactly* against a short list that omits the
    standard SAE J1979 key, so an `A6-ODOMETER` device produced sessions with no
    odometer and no distance at all;
  - a bare `ODOMETER` autopid reports miles, which was stored and differenced
    as though it were kilometres, understating every distance by 1.609x.

`distance_km` is a metric-canonical column, so both ends must be converted
before they are subtracted.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetryLatest
from app.services.session_service import SessionService
from app.utils.datetime_utils import utc_now


@pytest_asyncio.fixture
async def make_session_device(db_session: AsyncSession):
    """Async factory: (suffix, param_key, value, unit) -> LiveLinkDevice."""

    async def _factory(
        suffix: str,
        param_key: str,
        value: float,
        odometer_unit: str | None = None,
        kind: str = "wican",
    ) -> LiveLinkDevice:
        user = User(
            username=f"sessodo_user_{suffix}",
            email=f"sessodo_{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.flush()

        vin = f"SESSODOTEST{suffix:0>6}"
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=user.id,
                nickname=f"Session Odo Car {suffix}",
                vehicle_type="Car",
            )
        )
        await db_session.flush()

        device = LiveLinkDevice(
            device_id=f"sessdev{suffix:0>5}",
            vin=vin,
            enabled=True,
            odometer_unit=odometer_unit,
            kind=kind,
        )
        db_session.add(device)

        now = utc_now()
        db_session.add(
            VehicleTelemetryLatest(
                vin=vin,
                param_key=param_key,
                value=value,
                timestamp=now,
                received_at=now,
            )
        )
        await db_session.flush()
        return device

    return _factory


@pytest.mark.asyncio
class TestSessionOdometerUnits:
    """Session odometer stamping across both odometer key shapes."""

    async def test_standard_pid_odometer_is_found(self, db_session, make_session_device):
        """`A6-ODOMETER` must be recognised — it was missed by exact matching."""
        device = await make_session_device("1", "A6-ODOMETER", 12381.0)

        session = await SessionService(db_session).start_session(device, utc_now())

        assert session.start_odometer == 12381.0, "standard PID odometer was not found"

    async def test_bare_autopid_odometer_is_converted_to_km(self, db_session, make_session_device):
        """A miles autopid reading must be stamped as kilometres."""
        device = await make_session_device("2", "ODOMETER", 89984.0)

        session = await SessionService(db_session).start_session(device, utc_now())

        # 89984 mi * 1.60934 = 144814.85 km
        assert session.start_odometer is not None
        assert round(session.start_odometer) == 144815

    async def test_non_wican_bare_odometer_is_left_metric(self, db_session, make_session_device):
        """The bare-key=miles guess is a WiCAN autopid fact, not a general one.

        Torque Pro also publishes a bare `ODOMETER` and does not report miles,
        so applying the heuristic to it would inflate every reading by 1.609x.
        """
        device = await make_session_device("3", "ODOMETER", 1000.0, kind="torque")

        session = await SessionService(db_session).start_session(device, utc_now())

        assert session.start_odometer == 1000.0, "non-WiCAN reading was wrongly converted"
