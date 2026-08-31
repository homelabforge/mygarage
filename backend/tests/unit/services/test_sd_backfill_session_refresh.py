"""SD-card backfill must fold its rows into the sessions they belong to.

`store_telemetry` refreshes a closed session when a replayed reading lands
inside its window. The SD-card path does not go through `store_telemetry`: it
writes rows directly via `bulk_backfill`, for good reason (a pull is tens of
thousands of rows and must not run the live side-effects once per row).

That left the repair covering the wrong path. The SD card is where late data
actually comes from -- off home WiFi a WiCAN reaches no broker at all, so the
entire drive arrives hours later in one bulk pull -- and none of it reached the
sessions it belonged to. On Diamond a drive whose real peak was 85 km/h stayed
recorded as 20 km/h until the history repair tool was run by hand.

Refreshing once per row would undo the reason `bulk_backfill` exists, so the
refresh happens once per pull, over the sessions its rows actually span.
"""

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.sd_log_parser import SdRow
from app.services.telemetry_service import TelemetryService


@pytest_asyncio.fixture
async def make_closed_session(make_closed_drive_session):
    """Async factory: (suffix) -> (vin, device_id, session). See conftest."""

    async def _factory(suffix: str) -> tuple[str, str, DriveSession]:
        return await make_closed_drive_session("sdref", suffix, distance_km=129.0)

    return _factory


@pytest.mark.asyncio
class TestSdBackfillSessionRefresh:
    """A bulk SD pull updates the closed sessions its rows fall inside."""

    async def test_backfilled_rows_update_the_session_they_fall_inside(
        self, db_session, make_closed_session
    ):
        """The buffered 85 km/h sample must reach the session it belongs to."""
        vin, device_id, session = await make_closed_session("1")
        inside = session.started_at + timedelta(minutes=2)

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device_id,
            [SdRow(param_key="0D-VEHICLESPEED", value=85.0, timestamp=inside)],
        )
        await db_session.refresh(session)

        assert session.max_speed == 85.0, "SD rows never reached the session they fall inside"

    async def test_backfilled_odometer_corrects_the_session_distance(
        self, db_session, make_closed_session
    ):
        """Distance is recomputed too, not just the speed aggregates."""
        vin, device_id, session = await make_closed_session("2")
        first = session.started_at + timedelta(minutes=1)
        last = session.started_at + timedelta(minutes=8)

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device_id,
            [
                SdRow(param_key="A6-ODOMETER", value=12510.0, timestamp=first),
                SdRow(param_key="A6-ODOMETER", value=12518.0, timestamp=last),
            ],
        )
        await db_session.refresh(session)

        assert session.distance_km == 8.0, "the stored 129 km survived an SD pull"

    async def test_a_straddled_session_with_nothing_inside_keeps_its_values(
        self, db_session, make_closed_session
    ):
        """Overlap picks the candidates; each session recomputes from its own window.

        A pull routinely spans a session it landed no rows in -- the SD card
        holds a whole day and sessions are minutes long. Such a session must
        keep the aggregates it was closed with rather than being blanked,
        exactly as `_calculate_session_aggregates` already treats a window whose
        telemetry has been pruned.

        Note what this file does NOT re-assert: that a foreign VIN's rows or an
        out-of-window row cannot change a session. Both were tested here and
        both were vacuous -- mutants that dropped the VIN filter and the overlap
        bound from the selection query passed anyway, because the selection is
        only an optimisation. `refresh_aggregates` is VIN- and window-scoped
        itself, and that is pinned in test_session_distance_window.py.
        """
        vin, device_id, session = await make_closed_session("3")
        before = session.started_at - timedelta(minutes=10)
        after = session.ended_at + timedelta(minutes=10)

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device_id,
            [
                SdRow(param_key="0D-VEHICLESPEED", value=200.0, timestamp=before),
                SdRow(param_key="A6-ODOMETER", value=99999.0, timestamp=after),
            ],
        )
        await db_session.refresh(session)

        assert session.max_speed == 20.0, (
            "a straddled session was recomputed from outside its window"
        )
        assert session.distance_km == 129.0, "a straddled session had its distance blanked"

    async def test_the_pull_reaches_its_own_vehicles_session(self, db_session, make_closed_session):
        """Two vehicles' sessions can share a wall-clock window; the pull must land."""
        _vin_a, _dev_a, session_a = await make_closed_session("4")
        vin_b, dev_b, session_b = await make_closed_session("5")
        inside = session_a.started_at + timedelta(minutes=2)

        await TelemetryService(db_session).bulk_backfill(
            vin_b,
            dev_b,
            [SdRow(param_key="0D-VEHICLESPEED", value=150.0, timestamp=inside)],
        )
        await db_session.refresh(session_b)

        assert session_b.max_speed == 150.0, "the pull did not reach its own vehicle's session"


@pytest.mark.asyncio
class TestSdBackfillOdometerUnits:
    """SD rows land in a metric-canonical column and must be converted too."""

    async def test_sd_odometer_is_stored_in_kilometres(self, db_session, make_closed_session):
        """A bare `ODOMETER` autopid reports miles on a US-market car.

        `store_telemetry` normalises it via `_normalize_odometer_units`; the SD
        path wrote `r.value` verbatim, so the same reading was stored in miles
        on one path and kilometres on the other, into one column. It went
        unnoticed because the SD log rarely carries the autopid -- and because
        the one device that does emit it had its history converted by hand.

        Session distance is now measured from these rows, so the two paths have
        to agree: mixing them understates a drive by 1.609x.
        """
        vin, device_id, session = await make_closed_session("6")
        device = (
            await db_session.execute(
                select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
            )
        ).scalar_one()
        device.odometer_unit = "mi"
        await db_session.flush()

        inside = session.started_at + timedelta(minutes=2)
        await TelemetryService(db_session).bulk_backfill(
            vin,
            device_id,
            [SdRow(param_key="ODOMETER", value=1000.0, timestamp=inside)],
        )

        stored = (
            await db_session.execute(
                select(VehicleTelemetry.value)
                .where(VehicleTelemetry.vin == vin)
                .where(VehicleTelemetry.param_key == "ODOMETER")
            )
        ).scalar_one()

        assert stored == pytest.approx(1609.34), "SD odometer was stored in miles"

    async def test_sd_odometer_on_a_metric_device_is_left_alone(
        self, db_session, make_closed_session
    ):
        """A device declaring km must not be converted a second time."""
        vin, device_id, session = await make_closed_session("7")
        device = (
            await db_session.execute(
                select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
            )
        ).scalar_one()
        device.odometer_unit = "km"
        await db_session.flush()

        inside = session.started_at + timedelta(minutes=2)
        await TelemetryService(db_session).bulk_backfill(
            vin,
            device_id,
            [SdRow(param_key="ODOMETER", value=1000.0, timestamp=inside)],
        )

        stored = (
            await db_session.execute(
                select(VehicleTelemetry.value)
                .where(VehicleTelemetry.vin == vin)
                .where(VehicleTelemetry.param_key == "ODOMETER")
            )
        ).scalar_one()

        assert stored == 1000.0, "a metric device's SD odometer was converted anyway"


@pytest.mark.asyncio
class TestSdBackfillRefreshSpan:
    """Only rows that actually landed widen the span the refresh covers."""

    async def test_a_duplicate_only_repull_refreshes_nothing(self, db_session, make_closed_session):
        """The active log file is re-read from its watermark on every run.

        Tracking every parsed row would make one new row at the tail of a
        re-read card recompute every session the card spans -- at eight window
        scans each, on the scheduler thread, every pull, forever.

        Observed without mocks: a stored value is corrupted between the two
        pulls, so a refresh that should not happen is visible when it repairs
        it. `on_conflict_do_nothing` makes the second pull insert nothing.
        """
        vin, device_id, session = await make_closed_session("8")
        inside = session.started_at + timedelta(minutes=2)
        rows = [SdRow(param_key="0D-VEHICLESPEED", value=85.0, timestamp=inside)]

        service = TelemetryService(db_session)
        assert await service.bulk_backfill(vin, device_id, rows) == 1
        await db_session.refresh(session)
        assert session.max_speed == 85.0  # the first pull did refresh

        session.max_speed = 999.0
        await db_session.commit()

        assert await service.bulk_backfill(vin, device_id, rows) == 0, "row was not a duplicate"
        await db_session.refresh(session)

        assert session.max_speed == 999.0, "a duplicate-only re-pull refreshed the session anyway"
