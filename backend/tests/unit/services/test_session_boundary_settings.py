"""The two new settings, and the diagnostic that keeps `contact` mode honest.

**Why the gap is its own setting (C11).** An earlier design revision reused
``livelink_session_timeout_minutes`` and argued the two would then "agree by
construction". They would not: the live path also ends a session on explicit
ECU-offline plus a 60-second grace, and on Torque's own session id, so a
key-off/key-on pair 90 seconds apart splits live and merges in reconstruction.
The questions are different -- "has this device gone quiet?" is not "was that
the same drive?" -- and conflating them means an admin cannot fix trip grouping
without also changing failure detection.

**Why there is a reversal switch (C12).** The first revision argued against any
setting because it would "only keep producing phantom drives". That is wrong for
one cohort: a device whose movement signals nothing recognises produces **real**
drives under the contact rule and none at all under the movement rule. It also
gives an operator a way to bisect a bad upgrade where downgrading is impossible.

**And why the switch needs a diagnostic.** A silent zero is the failure mode
this entire change exists to eliminate; shipping a mode that reintroduces it
without saying so would be absurd. A device that produces telemetry across a
window but never a movement signal is named in the log, with the keys it did
send, so the operator has something to act on rather than an empty session list.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.services.livelink_service import LiveLinkService
from app.services.session_service import SessionService
from app.services.settings_service import SettingsService

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 1, 8, 0, 0)

#: Every global key this module writes. These are GLOBAL settings, and the suite
#: shares one database with no per-test rollback, so a test that leaves
#: `livelink_session_boundary_mode = contact` behind silently switches off
#: movement boundaries for every test that runs after it. Measured: 28 failures
#: in files that never mention settings, all of them in `contact` mode without
#: knowing it. Restoring is not tidiness, it is the difference between this file
#: testing a switch and this file breaking the suite.
_GLOBAL_KEYS = (
    "livelink_session_gap_minutes",
    "livelink_session_boundary_mode",
    "livelink_session_timeout_minutes",
)


@pytest_asyncio.fixture(autouse=True)
async def restore_global_settings(db_session: AsyncSession):
    """Snapshot and restore the global keys this module writes."""
    before = {}
    for key in _GLOBAL_KEYS:
        setting = await SettingsService.get(db_session, key)
        before[key] = setting.value if setting else None

    yield

    for key, value in before.items():
        setting = await SettingsService.get(db_session, key)
        if setting is None:
            continue
        if value is None:
            await db_session.delete(setting)
        else:
            setting.value = value
    # COMMIT, not flush: the route under test calls `db.commit()` itself, so a
    # flushed restore is discarded by the next commit boundary and the poisoned
    # value survives. This was measured -- 28 failures in files that never
    # mention settings, all silently running in `contact` mode.
    await db_session.commit()


async def _sessions(db: AsyncSession, device_id: str) -> list[DriveSession]:
    return list(
        (await db.execute(select(DriveSession).where(DriveSession.device_id == device_id)))
        .scalars()
        .all()
    )


class TestTheGapSetting:
    async def test_it_defaults_to_fifteen_minutes(self, db_session: AsyncSession):
        assert await LiveLinkService(db_session).get_session_gap_minutes() == 15

    async def test_it_is_not_the_session_timeout(self, db_session: AsyncSession):
        """Two settings, not one. Reusing the timeout would mean an admin
        cannot fix trip grouping without also changing failure detection."""
        service = LiveLinkService(db_session)
        await SettingsService.set(db_session, "livelink_session_timeout_minutes", "9")
        await db_session.flush()

        assert await service.get_session_timeout_minutes() == 9
        assert await service.get_session_gap_minutes() == 15

    async def test_a_configured_gap_changes_where_a_drive_is_cut(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The setting must reach the boundary logic, not just the getter.

        A setting that reads back correctly and changes no behaviour is the
        commonest way a knob ships broken, and it looks identical to a working
        one from the settings page.
        """
        vin, device = await make_livelink_vehicle("gapset", "1")
        await SettingsService.set(db_session, "livelink_session_gap_minutes", "3")
        await db_session.flush()
        service = SessionService(db_session)

        for at in (T0, T0 + timedelta(minutes=1)):
            device.last_seen = at
            await service.observe_telemetry(device, {"SPEED": 45.0}, at, live=True)
        await db_session.flush()

        # Six minutes stationary: inside the default 15-minute gap, well past
        # the configured 3-minute one.
        stopped = T0 + timedelta(minutes=7)
        device.last_seen = stopped
        await service.observe_telemetry(device, {"SPEED": 0.0}, stopped, live=True)
        await service.check_session_timeouts(timeout_minutes=60, now=stopped)
        await db_session.flush()

        sessions = await _sessions(db_session, device.device_id)
        assert len(sessions) == 1
        assert sessions[0].ended_at is not None, "the 3-minute gap should have closed this"
        assert sessions[0].effective_gap_minutes == 3, (
            "the gap in force is recorded on the session, so a later "
            "reconstruction knows what it is looking at"
        )


class TestTheBoundaryModeSetting:
    async def test_it_defaults_to_movement(self, db_session: AsyncSession):
        assert await LiveLinkService(db_session).get_session_boundary_mode() == "movement"

    async def test_an_unrecognised_value_falls_back_to_movement(self, db_session: AsyncSession):
        """A typo in the settings table must not silently disable the fix."""
        await SettingsService.set(db_session, "livelink_session_boundary_mode", "moovment")
        await db_session.flush()

        assert await LiveLinkService(db_session).get_session_boundary_mode() == "movement"

    async def test_contact_mode_restores_the_old_rule(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """For a device whose signals nothing recognises, contact produces REAL
        drives where movement produces none."""
        vin, device = await make_livelink_vehicle("modeset", "1")
        await SettingsService.set(db_session, "livelink_session_boundary_mode", "contact")
        await db_session.flush()
        service = SessionService(db_session)

        opened = await service.handle_ecu_status_change(device, "online", T0)
        await db_session.flush()

        assert opened is not None, "contact mode must open a session on ECU-online"
        assert opened.boundary_algorithm_version == 0, (
            "a contact-bounded session must not claim the movement algorithm"
        )

    async def test_movement_mode_does_not(self, db_session: AsyncSession, make_livelink_vehicle):
        """The paired control. Without it the test above passes in both modes."""
        vin, device = await make_livelink_vehicle("modeset", "2")
        service = SessionService(db_session)

        opened = await service.handle_ecu_status_change(device, "online", T0)
        await db_session.flush()

        assert opened is None
        assert await _sessions(db_session, device.device_id) == []

    async def test_contact_mode_ignores_telemetry_for_boundaries(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Both halves have to switch together, or the two rules run at once and
        a single drive gets a contact-bounded session AND a movement-bounded
        one, overlapping."""
        vin, device = await make_livelink_vehicle("modeset", "3")
        await SettingsService.set(db_session, "livelink_session_boundary_mode", "contact")
        await db_session.flush()
        service = SessionService(db_session)

        for at in (T0, T0 + timedelta(minutes=1)):
            await service.observe_telemetry(device, {"SPEED": 45.0}, at, live=True)
        await db_session.flush()

        assert await _sessions(db_session, device.device_id) == []


class TestTheNoMovementDiagnostic:
    async def test_a_device_with_no_movement_signal_is_named(
        self, db_session: AsyncSession, make_livelink_vehicle, caplog
    ):
        """A silent zero is the failure this whole change exists to eliminate.

        The log names the device and the keys it DID send, because "no sessions"
        with an unknown cause is not something an operator can act on, while
        "this device publishes MY_SPEED_PID and nothing recognises it" is.
        """
        vin, device = await make_livelink_vehicle("diagset", "1")
        service = SessionService(db_session)

        with caplog.at_level(logging.WARNING, logger="app.services.session_service"):
            for minute in range(4):
                at = T0 + timedelta(minutes=minute * 30)
                device.last_seen = at
                await service.observe_telemetry(
                    device, {"CUSTOM_ROAD_SPEED": 55.0, "COOLANT_TMP": 88.0}, at, live=True
                )
        await db_session.flush()

        messages = [r.getMessage() for r in caplog.records]
        assert any(device.device_id in m for m in messages), messages
        assert any("CUSTOM_ROAD_SPEED" in m for m in messages), (
            "the keys it did send are the actionable part; naming the device alone "
            f"tells an operator nothing they can fix: {messages}"
        )

    async def test_it_is_logged_once_not_per_payload(
        self, db_session: AsyncSession, make_livelink_vehicle, caplog
    ):
        """A device sends a payload every few seconds. Logging per payload
        floods the log and buries the diagnostic it is trying to surface."""
        vin, device = await make_livelink_vehicle("diagset", "2")
        service = SessionService(db_session)

        with caplog.at_level(logging.WARNING, logger="app.services.session_service"):
            for minute in range(30):
                at = T0 + timedelta(minutes=minute)
                device.last_seen = at
                await service.observe_telemetry(device, {"CUSTOM_PID": 12.0}, at, live=True)

        warnings = [r for r in caplog.records if device.device_id in r.getMessage()]
        assert len(warnings) == 1, f"logged {len(warnings)} times"

    async def test_a_device_that_reports_movement_is_not_flagged(
        self, db_session: AsyncSession, make_livelink_vehicle, caplog
    ):
        """The control. Without it the assertions above are satisfied by a
        diagnostic that fires for every device on every payload."""
        vin, device = await make_livelink_vehicle("diagset", "3")
        service = SessionService(db_session)

        with caplog.at_level(logging.WARNING, logger="app.services.session_service"):
            for minute in range(4):
                at = T0 + timedelta(minutes=minute)
                device.last_seen = at
                await service.observe_telemetry(device, {"SPEED": 45.0}, at, live=True)

        assert [r.getMessage() for r in caplog.records if device.device_id in r.getMessage()] == []

    async def test_a_parked_device_is_not_flagged(
        self, db_session: AsyncSession, make_livelink_vehicle, caplog
    ):
        """A battery heartbeat is not a broken device.

        This is the distinction that makes the diagnostic worth having: a parked
        vehicle SHOULD produce no sessions, and flagging it would make the
        warning meaningless on every instance.
        """
        vin, device = await make_livelink_vehicle("diagset", "4")
        service = SessionService(db_session)

        with caplog.at_level(logging.WARNING, logger="app.services.session_service"):
            for minute in range(5):
                at = T0 + timedelta(minutes=minute * 95)
                device.last_seen = at
                await service.observe_telemetry(device, {"BATTERY_VOLTAGE": 12.4}, at, live=True)

        assert [r.getMessage() for r in caplog.records if device.device_id in r.getMessage()] == []


class TestTheSettingsReachTheAdminApi:
    """A setting the UI cannot edit is a setting that does not exist.

    Both are read from the settings table with a sensible default, so every
    behavioural test above passes whether or not the admin surface knows about
    them. That is exactly the gap where a knob ships unreachable: the code
    honours it, the tests prove the code honours it, and no user can ever set
    it. So the response and the update path each get an assertion.
    """

    async def test_the_response_reports_both(self, db_session: AsyncSession):
        from app.schemas.livelink import LiveLinkSettingsResponse

        fields = LiveLinkSettingsResponse.model_fields
        assert "session_gap_minutes" in fields
        assert "session_boundary_mode" in fields

    async def test_the_update_schema_accepts_both(self, db_session: AsyncSession):
        from app.schemas.livelink import LiveLinkSettingsUpdate

        parsed = LiveLinkSettingsUpdate(session_gap_minutes=20, session_boundary_mode="contact")
        assert parsed.session_gap_minutes == 20
        assert parsed.session_boundary_mode == "contact"

    async def test_a_zero_gap_is_refused(self, db_session: AsyncSession):
        """Zero closes a session on the first stationary sample, so every
        traffic light becomes its own trip."""
        import pydantic

        from app.schemas.livelink import LiveLinkSettingsUpdate

        with pytest.raises(pydantic.ValidationError):
            LiveLinkSettingsUpdate(session_gap_minutes=0)

    async def test_an_invalid_mode_is_refused_at_the_boundary(self, db_session: AsyncSession):
        """The service also falls back to `movement` on a bad value, but that is
        a safety net for hand-edited rows. The API should say no."""
        import pydantic

        from app.schemas.livelink import LiveLinkSettingsUpdate

        with pytest.raises(pydantic.ValidationError):
            LiveLinkSettingsUpdate(session_boundary_mode="whatever")

    async def test_the_route_persists_the_gap(self, db_session: AsyncSession):
        """Exercises the update branch itself, which is a hand-written if-chain
        of thirteen near-identical blocks -- the shape where a new setting gets
        its getter and its schema field and no `SettingsService.set` call."""
        # A real Request, because the route echoes the settings back through
        # `get_livelink_settings`, which builds the WiCAN ingestion URL from it.
        from starlette.requests import Request as StarletteRequest

        from app.routes.livelink_admin import update_livelink_settings
        from app.schemas.livelink import LiveLinkSettingsUpdate

        request = StarletteRequest(
            {
                "type": "http",
                "method": "PUT",
                "path": "/api/v1/livelink/settings",
                "headers": [(b"host", b"testserver")],
                "scheme": "http",
                "server": ("testserver", 80),
                "query_string": b"",
            }
        )

        await update_livelink_settings(
            updates=LiveLinkSettingsUpdate(session_gap_minutes=25, session_boundary_mode="contact"),
            request=request,
            db=db_session,
            current_user=None,
        )
        await db_session.flush()

        service = LiveLinkService(db_session)
        assert await service.get_session_gap_minutes() == 25
        assert await service.get_session_boundary_mode() == "contact"
