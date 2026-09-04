"""No live ingest path opens a session without movement. All three of them.

The count is the point. An earlier revision of this design named
``mqtt_subscriber.py:440`` as "the root cause, in code" and fixed that one path.
Enumerating **every** path that can construct a ``DriveSession``, rather than
the one the design expected to find, there are five:

===================================  ==========================  ==============
path                                 trigger                     in scope
===================================  ==========================  ==============
``mqtt_subscriber`` ``can/rx``       any telemetry at all        yes
``mqtt_subscriber`` ``can/status``   explicit ``ecu_status``     yes
``routes/livelink`` ``/ingest``      explicit status block       yes
``routes/torque``                    phone-supplied session id   no, by design
``bulk_backfill`` (SD card)          replayed SD rows            yes, separately
===================================  ==========================  ==============

The comment directly above the path that first revision fixed says it "handles
WiCAN devices that don't send explicit can/status messages" -- so by the code's
own account it is the FALLBACK. An instance whose dongle sends status messages,
or any instance on HTTPS ingest, would have kept every one of its phantom
sessions while the changelog said they were fixed.

**Where a battery-only test must be seeded.** The dedicated MQTT ``battery``
subtopic never called ``SessionService`` at all and was already correct, so a
battery-only assertion seeded there passes trivially and proves nothing. It has
to go on ``can/rx``, which is the path that inferred ECU-online from *any*
telemetry.

Mutation check for this file: restore the unconditional ``handle_ecu_online``
call in ``SessionService.handle_ecu_status_change``'s online branch, and every
``opens_nothing`` test here must fail. Recorded in the commit message.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.settings import Setting
from app.services.mqtt_subscriber import MQTTSubscriber
from app.services.session_service import SessionService

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 1, 8, 0, 0)


async def _sessions(db: AsyncSession, device_id: str) -> list[DriveSession]:
    return list(
        (await db.execute(select(DriveSession).where(DriveSession.device_id == device_id)))
        .scalars()
        .all()
    )


async def _enable_livelink(db: AsyncSession) -> None:
    existing = (
        await db.execute(select(Setting).where(Setting.key == "livelink_enabled"))
    ).scalar_one_or_none()
    if existing is None:
        db.add(Setting(key="livelink_enabled", value="true"))
    else:
        existing.value = "true"
    await db.flush()


class TestMqttCanRx:
    """The telemetry-inferred path: the one the first design revision fixed."""

    async def test_a_battery_only_payload_opens_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The exact payload behind 2,975 of this instance's 3,238 sessions.

        Seeded on `can/rx`, NOT on the `battery` subtopic: that subtopic never
        touched SessionService, so the same assertion there would pass against
        completely unfixed code.
        """
        vin, device = await make_livelink_vehicle("ingrx", "1")
        await _enable_livelink(db_session)

        await MQTTSubscriber()._handle_telemetry(
            db_session, device.device_id, {"BATTERY_VOLTAGE": 12.4}
        )
        await db_session.flush()

        assert await _sessions(db_session, device.device_id) == []

    async def test_an_idling_payload_opens_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Engine on, stationary. The eleven-minute driveway idle."""
        vin, device = await make_livelink_vehicle("ingrx", "2")
        await _enable_livelink(db_session)

        subscriber = MQTTSubscriber()
        for _ in range(3):
            await subscriber._handle_telemetry(
                db_session, device.device_id, {"ENGINE_RPM": 760, "SPEED": 0}
            )
        await db_session.flush()

        assert await _sessions(db_session, device.device_id) == []

    async def test_a_moving_payload_does_open_one(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The positive control.

        Without it, every assertion above is satisfied by an ingest path that
        has stopped creating sessions under any circumstances -- which is a far
        worse bug than the one being fixed, and would look identical here.
        """
        vin, device = await make_livelink_vehicle("ingrx", "3")
        await _enable_livelink(db_session)

        subscriber = MQTTSubscriber()
        for _ in range(2):
            await subscriber._handle_telemetry(
                db_session, device.device_id, {"SPEED": 52, "ENGINE_RPM": 2200}
            )
        await db_session.flush()

        sessions = await _sessions(db_session, device.device_id)
        assert len(sessions) == 1
        assert sessions[0].boundary_algorithm_version == 1


class TestMqttCanStatus:
    """The explicit-status path, which the first revision did not reach."""

    async def test_an_explicit_ecu_online_opens_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The payload key is `status`, not `ecu_status`.

        Worth a sentence, because writing it wrong is not a failing test: an
        unrecognised value maps to `"unknown"`, and the handler skips session
        handling entirely for unknown. So the mis-keyed version of this test
        passed against completely unfixed code, and only the paired
        `test_an_ecu_online_signal_still_marks_the_device_online` below caught
        it. Both assertions have to be here for either to mean anything.
        """
        vin, device = await make_livelink_vehicle("ingst", "1")
        await _enable_livelink(db_session)

        await MQTTSubscriber()._handle_status(db_session, device.device_id, {"status": "online"})
        await db_session.flush()
        await db_session.refresh(device)

        assert await _sessions(db_session, device.device_id) == []
        assert device.ecu_status == "online", (
            "guard on the guard: a payload the handler treats as `unknown` "
            "skips session handling, so the assertion above would pass unfixed"
        )

    async def test_an_ecu_online_signal_still_marks_the_device_online(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """It marks the device online and nothing more -- but it must still do
        that. `device_command_service` refuses any `requires_ecu` command when
        `ecu_status != "online"`, so losing this would take the remote-command
        surface down with it."""
        vin, device = await make_livelink_vehicle("ingst", "2")
        await _enable_livelink(db_session)

        await MQTTSubscriber()._handle_status(db_session, device.device_id, {"status": "online"})
        await db_session.flush()
        await db_session.refresh(device)

        assert device.ecu_status == "online"


class TestHttpsIngest:
    """The third live site, driven through the real route."""

    async def test_a_status_block_alone_opens_nothing(
        self, db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("inghttp", "1")
        await _enable_livelink(db_session)

        with patch(
            "app.routes.livelink.validate_livelink_token", new_callable=AsyncMock
        ) as validate:
            validate.return_value = True
            response = await client.post(
                "/api/v1/livelink/ingest",
                json={
                    "autopid_data": {"BATTERY_VOLTAGE": 12.4},
                    "config": {},
                    "status": {"device_id": device.device_id, "ecu_status": "online"},
                },
                headers={"Authorization": "Bearer t"},
            )

        assert response.status_code == 202
        assert await _sessions(db_session, device.device_id) == []

    async def test_movement_over_https_does_open_one(
        self, db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("inghttp", "2")
        await _enable_livelink(db_session)

        with patch(
            "app.routes.livelink.validate_livelink_token", new_callable=AsyncMock
        ) as validate:
            validate.return_value = True
            for _ in range(2):
                response = await client.post(
                    "/api/v1/livelink/ingest",
                    json={
                        "autopid_data": {"SPEED": 48, "ENGINE_RPM": 2100},
                        "config": {},
                        "status": {"device_id": device.device_id, "ecu_status": "online"},
                    },
                    headers={"Authorization": "Bearer t"},
                )
                assert response.status_code == 202

        assert len(await _sessions(db_session, device.device_id)) == 1


class TestTorqueIsUntouched:
    """C8: Torque's behaviour is byte-identical before and after.

    ``resolve_torque_session`` is a second constructor on a separate contract:
    the phone has already decided where the drive begins and supplies its id, so
    a movement predicate has nothing to add and would only overrule a better
    source. Any pass over history excludes Torque by ``external_session_id``
    rather than by heuristic, for the same reason.
    """

    async def test_a_torque_upload_still_opens_a_session_immediately(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """One payload, no debounce, no movement signal at all -- because the
        phone's session id IS the evidence."""
        vin, device = await make_livelink_vehicle("ingtq", "1", kind="torque")
        service = SessionService(db_session)

        session = await service.resolve_torque_session(device, "torque-session-1", T0)
        await db_session.flush()

        assert session is not None
        assert session.external_session_id == "torque-session-1"

    async def test_a_torque_session_is_stamped_as_not_this_algorithm(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Version 0, because its boundaries come from the phone.

        Stamping it 1 would claim a provenance it does not have, and it is also
        how any later pass over history knows to leave it alone.
        """
        vin, device = await make_livelink_vehicle("ingtq", "2", kind="torque")
        service = SessionService(db_session)

        session = await service.resolve_torque_session(device, "torque-session-2", T0)
        await db_session.flush()

        assert session is not None
        assert session.boundary_algorithm_version == 0
        assert session.effective_gap_minutes is None
