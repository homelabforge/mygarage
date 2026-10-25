"""Pipeline orchestration, above all the capability gate."""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.models.drive_session import DriveSession
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.vehicle_telemetry import VehicleTelemetryLatest
from app.services.livelink_ingest import ingest
from app.services.livelink_sources.base import (
    BaseSourceModule,
    Capability,
    InferSession,
    IngestBatch,
    MqttEnvelope,
    Reading,
    StoragePolicy,
)
from app.services.livelink_sources.generic_mqtt import GenericMqttModule
from app.services.livelink_sources.registry import default_registry

# LiveLink's master switch gates the ingest pipeline and SD backfill, and it is
# off by default. Explicit, not inherited from whatever an earlier test left in
# the shared database.
pytestmark = pytest.mark.usefixtures("livelink_enabled")


class _Fake(BaseSourceModule):
    """Base for the fakes: carries the device id its batches address.

    Parameterised rather than hardcoded because each test seeds its own
    uuid-scoped device; a fixed "gw01" collides on the UNIQUE index at the
    second test (the suite shares one database with no rollback).
    """

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id


class _Sessionless(_Fake):
    """A propane-shaped source: telemetry only, no sessions."""

    kind = "sessionless"
    capabilities = frozenset({Capability.TELEMETRY})
    storage_policy = StoragePolicy()

    async def parse(self, env):
        return IngestBatch(
            device_key=self.device_id,
            readings=[Reading("PROPANE_T1_LEVEL_PCT", 71.0, unit="%")],
            device_status="online",
            session=InferSession(),  # emitted but MUST be ignored
            requires_link=True,
            # Propane-shaped: low-tank alerting is the point, so this source
            # opts in. `_Quiet` below is the counterpart that does not, which
            # is how Torque and WiCAN battery frames behave today.
            alert_on_thresholds=True,
        )


class _Sessionful(_Fake):
    kind = "sessionful"
    capabilities = frozenset({Capability.TELEMETRY, Capability.DRIVE_SESSION})
    storage_policy = StoragePolicy()

    async def parse(self, env):
        return IngestBatch(
            device_key=self.device_id,
            readings=[Reading("RPM", 900.0)],
            session=InferSession(),
            requires_link=True,
        )


@pytest_asyncio.fixture
async def linked_device(db_session, make_livelink_vehicle, request):
    """An isolated vehicle + device, one per test.

    The suffix MUST vary per test. `make_livelink_vehicle` derives the user
    name, email and VIN from it, and the suite shares one database with no
    per-test rollback, so a fixed suffix collides on the UNIQUE indexes at the
    second test in the file. Keyed off the test's own name, which is unique by
    construction and keeps failures readable.
    """
    suffix = f"{abs(hash(request.node.name)) % 10**6:06d}"
    _vin, device = await make_livelink_vehicle("ingest", suffix, kind="sessionless")
    return device


ENV = MqttEnvelope(topic="t", payload=b"1")


@pytest.mark.asyncio
async def test_a_source_without_the_drive_session_capability_never_opens_one(
    db_session, make_livelink_vehicle, request
):
    """THE regression guard: propane must not manufacture drives on a parked trailer.

    Regression guard (A-12): passes on main by design. The real generic module
    from the real registry through real `ingest`, nothing mocked, so the store's
    `_observe_movement` back door is covered too. These speed samples open a
    drive once generic_mqtt has DRIVE_SESSION and movement observation, so a
    failure here means it gained them by accident.
    """
    suffix = f"{abs(hash(request.node.name)) % 10**6:06d}"
    vin, device = await make_livelink_vehicle("nods", suffix, kind="generic_mqtt")
    device_id = device.device_id
    topic = f"ingest/test/{suffix}/speed"
    await db_session.execute(delete(LiveLinkTopicMap).where(LiveLinkTopicMap.topic == topic))
    db_session.add(
        LiveLinkTopicMap(device_id=device_id, topic=topic, param_key="SPEED", unit="km/h")
    )
    await db_session.commit()
    module = default_registry().get_module("generic_mqtt")
    assert isinstance(module, GenericMqttModule)
    await module.refresh(db_session)
    try:
        # Steady speed: a jump in a few milliseconds fails the rate check and
        # never reaches the session code at all.
        for value in (b"60", b"60", b"60"):
            await ingest(module, MqttEnvelope(topic, value), db_session)
            await db_session.commit()

        sessions = await db_session.scalar(
            select(func.count()).select_from(DriveSession).where(DriveSession.vin == vin)
        )
        assert sessions == 0
        # The readings did land, so the zero above isn't a dropped frame.
        latest = await db_session.scalar(
            select(VehicleTelemetryLatest.value).where(
                VehicleTelemetryLatest.vin == vin, VehicleTelemetryLatest.param_key == "SPEED"
            )
        )
        assert latest == 60.0
    finally:
        await db_session.rollback()
        await db_session.execute(
            delete(LiveLinkTopicMap).where(LiveLinkTopicMap.device_id == device_id)
        )
        await db_session.commit()
        # The registry is a process-wide singleton: don't leave our topic in its cache.
        await module.refresh(db_session)


@pytest.mark.asyncio
async def test_the_pipeline_ignores_a_session_signal_without_the_capability(
    db_session, linked_device
):
    """The ingest-level gate: a module without DRIVE_SESSION that still emits
    `InferSession` never reaches `handle_ecu_online`.

    Regression guard: main's test, kept beside the real-module one, which can't
    see this gate because generic batches carry no session signal.
    """
    with patch("app.services.livelink_ingest.SessionService") as svc:
        svc.return_value.handle_ecu_online = AsyncMock()
        await ingest(_Sessionless(linked_device.device_id), ENV, db_session)
        svc.return_value.handle_ecu_online.assert_not_called()


@pytest.mark.asyncio
async def test_a_source_with_the_drive_session_capability_does_open_one(db_session, linked_device):
    linked_device.kind = "sessionful"
    await db_session.commit()
    with patch("app.services.livelink_ingest.SessionService") as svc:
        svc.return_value.handle_ecu_online = AsyncMock()
        await ingest(_Sessionful(linked_device.device_id), ENV, db_session)
        svc.return_value.handle_ecu_online.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_is_applied_before_device_status_is_updated(db_session, linked_device):
    """Ordering is load-bearing: the detector reads the OLD ecu_status."""
    linked_device.kind = "sessionful"
    await db_session.commit()
    calls: list[str] = []
    with (
        patch("app.services.livelink_ingest.SessionService") as sess,
        patch("app.services.livelink_ingest.LiveLinkService") as live,
    ):
        sess.return_value.handle_ecu_online = AsyncMock(
            side_effect=lambda *a: calls.append("session")
        )
        live.return_value.update_device_status = AsyncMock(
            side_effect=lambda **k: calls.append("status")
        )
        live.return_value.get_device_by_id = AsyncMock(return_value=linked_device)
        live.return_value.is_enabled = AsyncMock(return_value=True)  # the master switch
        await ingest(_Sessionful(linked_device.device_id), ENV, db_session)
    assert calls.index("session") < calls.index("status")


@pytest.mark.asyncio
async def test_telemetry_is_stored_for_a_linked_device(db_session, linked_device):
    with patch("app.services.livelink_ingest.TelemetryService") as tel:
        tel.return_value.store_readings = AsyncMock(
            return_value=type("R", (), {"validated_data": {}, "stored_count": 1})()
        )
        tel.return_value.check_thresholds = AsyncMock()
        await ingest(_Sessionless(linked_device.device_id), ENV, db_session)
        tel.return_value.store_readings.assert_awaited_once()


@pytest.mark.asyncio
async def test_thresholds_are_checked_for_each_validated_param(db_session, linked_device):
    with patch("app.services.livelink_ingest.TelemetryService") as tel:
        tel.return_value.store_readings = AsyncMock(
            return_value=type(
                "R", (), {"validated_data": {"PROPANE_T1_LEVEL_PCT": 71.0}, "stored_count": 1}
            )()
        )
        tel.return_value.check_thresholds = AsyncMock()
        await ingest(_Sessionless(linked_device.device_id), ENV, db_session)
        tel.return_value.check_thresholds.assert_awaited_once()
        # Not a preset sensor: alerts repeat every cooldown, as WiCAN's do.
        assert tel.return_value.check_thresholds.await_args.kwargs["once"] is False
        # No ODOMETER capability, so nothing here went through odometer
        # normalisation and an odometer-named key is not known to be km (D2a).
        assert tel.return_value.check_thresholds.await_args.kwargs["odometer_normalised"] is False


class _OdometerSource(_Fake):
    """Torque-shaped: ODOMETER, on the simple storage path. That path only
    normalises the device's declared odometer key."""

    kind = "odometersource"
    capabilities = frozenset({Capability.TELEMETRY, Capability.ODOMETER})
    storage_policy = StoragePolicy()

    async def parse(self, env):
        return IngestBatch(
            device_key=self.device_id,
            readings=[Reading("ODOMETER", 1000.0)],
            requires_link=True,
            alert_on_thresholds=True,
        )


class _DelegatingSource(_OdometerSource):
    """WiCAN-shaped: its policy sends storage through `store_telemetry`,
    which normalises every odometer key, declared or not."""

    kind = "delegatingsource"
    storage_policy = StoragePolicy(sync_odometer=True, observe_movement=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_cls", "declared", "expected"),
    [
        # The case the capability check got wrong: Torque's path converts
        # nothing without a declared key.
        (_OdometerSource, None, False),
        (_OdometerSource, "ODOMETER", True),
        (_DelegatingSource, None, True),
        (_DelegatingSource, "ODOMETER", True),
    ],
)
async def test_thresholds_learn_whether_the_store_normalised_the_odometer(
    db_session, linked_device, module_cls, declared, expected
):
    """The alert renders an odometer in the owner's units only if storage
    really converted it to km, so the flag must follow the storage path."""
    linked_device.kind = module_cls.kind
    linked_device.odometer_param_key = declared
    await db_session.commit()
    with patch("app.services.livelink_ingest.TelemetryService") as tel:
        tel.return_value.store_readings = AsyncMock(
            return_value=type(
                "R", (), {"validated_data": {"ODOMETER": 1000.0}, "stored_count": 1}
            )()
        )
        tel.return_value.check_thresholds = AsyncMock()
        await ingest(module_cls(linked_device.device_id), ENV, db_session)

    kwargs = tel.return_value.check_thresholds.await_args.kwargs
    assert kwargs["odometer_normalised"] is expected
    assert kwargs["declared_odometer_key"] == declared


@pytest.mark.asyncio
async def test_a_preset_sensors_readings_alert_once_per_crossing(db_session, linked_device):
    """A tank sits below its line for days: the cooldown would repeat it."""
    linked_device.preset_key = "mopeka"
    await db_session.commit()
    with patch("app.services.livelink_ingest.TelemetryService") as tel:
        tel.return_value.store_readings = AsyncMock(
            return_value=type(
                "R", (), {"validated_data": {"PROPANE_T1_LEVEL_PCT": 71.0}, "stored_count": 1}
            )()
        )
        tel.return_value.check_thresholds = AsyncMock()
        await ingest(_Sessionless(linked_device.device_id), ENV, db_session)

    assert tel.return_value.check_thresholds.await_args.kwargs["once"] is True


@pytest.mark.asyncio
async def test_an_unlinked_device_stores_nothing(db_session, linked_device):
    linked_device.vin = None
    await db_session.commit()
    with patch("app.services.livelink_ingest.TelemetryService") as tel:
        tel.return_value.store_readings = AsyncMock()
        await ingest(_Sessionless(linked_device.device_id), ENV, db_session)
        tel.return_value.store_readings.assert_not_called()


@pytest.mark.asyncio
async def test_a_disabled_device_stores_nothing(db_session, linked_device):
    linked_device.enabled = False
    await db_session.commit()
    with patch("app.services.livelink_ingest.TelemetryService") as tel:
        tel.return_value.store_readings = AsyncMock()
        await ingest(_Sessionless(linked_device.device_id), ENV, db_session)
        tel.return_value.store_readings.assert_not_called()


@pytest.mark.asyncio
async def test_a_module_returning_none_is_a_no_op(db_session, linked_device):
    class _Silent(_Sessionless):
        kind = "silent"

        async def parse(self, env):
            return None

    with patch("app.services.livelink_ingest.TelemetryService") as tel:
        tel.return_value.store_readings = AsyncMock()
        await ingest(_Silent(linked_device.device_id), ENV, db_session)
        tel.return_value.store_readings.assert_not_called()


@pytest.mark.asyncio
async def test_an_unlinked_device_still_gets_its_status_updated(db_session, linked_device):
    """R1-H4a: _handle_status updates status outside its `if device.vin` block.

    Breaking this breaks discover-then-link: a new dongle never shows online.
    """
    linked_device.vin = None
    await db_session.commit()

    class _StatusOnly(_Sessionless):
        kind = "statusonly"

        async def parse(self, env):
            return IngestBatch(
                device_key=self.device_id, device_status="online", requires_link=False
            )

    with patch("app.services.livelink_ingest.LiveLinkService") as live:
        live.return_value.get_device_by_id = AsyncMock(return_value=linked_device)
        live.return_value.is_enabled = AsyncMock(return_value=True)  # the master switch
        live.return_value.update_device_status = AsyncMock()
        await ingest(_StatusOnly(linked_device.device_id), ENV, db_session)
        live.return_value.update_device_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_batch_that_does_not_clear_pending_offline_leaves_it(db_session, linked_device):
    """R1-H4b: a WiCAN battery frame must not cancel a pending offline."""
    from datetime import datetime

    linked_device.pending_offline_at = datetime(2026, 9, 21, 12, 0, 0)
    await db_session.commit()
    with patch("app.services.livelink_ingest.LiveLinkService") as live:
        live.return_value.get_device_by_id = AsyncMock(return_value=linked_device)
        live.return_value.is_enabled = AsyncMock(return_value=True)  # the master switch
        live.return_value.clear_pending_offline = AsyncMock()
        live.return_value.update_device_status = AsyncMock()
        await ingest(
            _Sessionless(linked_device.device_id), ENV, db_session
        )  # clear_pending_offline defaults False
        live.return_value.clear_pending_offline.assert_not_called()


@pytest.mark.asyncio
async def test_thresholds_are_not_checked_unless_the_batch_asks(db_session, linked_device):
    """R1-H4c: WiCAN battery and Torque have never sent threshold alerts."""

    class _Quiet(_Sessionless):
        kind = "quiet"

        async def parse(self, env):
            return IngestBatch(
                device_key=self.device_id,
                readings=[Reading("X", 1.0)],
                alert_on_thresholds=False,
                requires_link=True,
            )

    with patch("app.services.livelink_ingest.TelemetryService") as tel:
        tel.return_value.store_readings = AsyncMock(
            return_value=type("R", (), {"validated_data": {"X": 1.0}, "stored_count": 1})()
        )
        tel.return_value.check_thresholds = AsyncMock()
        await ingest(_Quiet(linked_device.device_id), ENV, db_session)
        tel.return_value.check_thresholds.assert_not_called()


@pytest.mark.asyncio
async def test_a_telemetry_batch_does_not_resurrect_an_offline_device(db_session, linked_device):
    """R1-H5: retained replay after an LWT offline must not mark it online."""

    class _NoStatus(_Sessionless):
        kind = "nostatus"

        async def parse(self, env):
            return IngestBatch(
                device_key=self.device_id, readings=[Reading("X", 1.0)], device_status=None
            )

    with patch("app.services.livelink_ingest.LiveLinkService") as live:
        live.return_value.get_device_by_id = AsyncMock(return_value=linked_device)
        live.return_value.is_enabled = AsyncMock(return_value=True)  # the master switch
        live.return_value.update_device_status = AsyncMock()
        await ingest(_NoStatus(linked_device.device_id), ENV, db_session)
        assert live.return_value.update_device_status.await_args.kwargs["device_status"] is None


@pytest.mark.asyncio
async def test_a_source_without_the_odometer_capability_cannot_record_one(
    db_session, linked_device
):
    """The capability claim must hold for ODOMETER as it does for DRIVE_SESSION.

    A declared odometer parameter on a TELEMETRY-only device records nothing.
    """
    linked_device.odometer_param_key = "PROPANE_T1_LEVEL_PCT"
    await db_session.commit()
    with patch("app.services.livelink_ingest.TelemetryService") as tel:
        tel.return_value.store_readings = AsyncMock(
            return_value=type("R", (), {"validated_data": {}, "stored_count": 1})()
        )
        tel.return_value.check_thresholds = AsyncMock()
        await ingest(_Sessionless(linked_device.device_id), ENV, db_session)
        assert tel.return_value.store_readings.await_args.kwargs["device"] is None


@pytest.mark.asyncio
async def test_location_is_skipped_without_the_location_capability(db_session, linked_device):
    from decimal import Decimal

    from app.services.livelink_sources.base import GeoPoint

    class _Located(_Sessionless):
        kind = "located"

        async def parse(self, env):
            return IngestBatch(
                device_key=self.device_id,
                readings=[Reading("X", 1.0)],
                location=GeoPoint(latitude=Decimal("1"), longitude=Decimal("2")),
            )

    with patch("app.services.livelink_ingest.LocationService") as loc:
        loc.return_value.record_point = AsyncMock()
        await ingest(_Located(linked_device.device_id), ENV, db_session)
        loc.return_value.record_point.assert_not_called()
