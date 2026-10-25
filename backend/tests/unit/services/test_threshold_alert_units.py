"""Threshold alerts speak the reader's units (D2a, G3a-63).

Alert lines are canonical metric, the unit standard PIDs, WiCAN profile
parameters and Torque already store, so the compare never converts. The
notification does: value and line go through the vehicle owner's
`RenderContext`, with the quantity taken from the reading's class. Only when
the stored value is known to be canonical, though: a custom key whose
parameter says `psi` holds psi, and is printed as it is.

`make_livelink_vehicle`'s user has the column default, `unit_preference =
'imperial'`, which is the reader these tests need.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_parameter import LiveLinkParameter
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.services.livelink_ingest import ingest
from app.services.livelink_sources.base import MqttEnvelope
from app.services.livelink_sources.generic_mqtt import GenericMqttModule
from app.services.livelink_sources.wican import WicanModule
from app.services.telemetry_service import TelemetryService

#: Keys no other test registers: parameter rows are global and the suite
#: shares one database.
COOLANT = "T6_COOLANT_TEMP_9701"
BOOST = "T6_BOOST_PRES_9701"
ODO = "T6_ODOMETER_9701"
ODO_TOPIC = "t6units/test/odometer"


def _param(key: str, *, unit: str | None, param_class: str, **lines: float) -> LiveLinkParameter:
    return LiveLinkParameter(
        param_key=key,
        display_name=key,
        unit=unit,
        param_class=param_class,
        category="engine",
        show_on_dashboard=True,
        archive_only=False,
        storage_interval_seconds=0,
        **lines,
    )


def _capture(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Swap the dispatcher's send for a mock that says one service took it."""
    mock = AsyncMock(return_value={"ntfy": True})
    monkeypatch.setattr(
        "app.services.notifications.dispatcher.NotificationDispatcher.dispatch", mock
    )
    return mock


def _alert_message(mock: AsyncMock) -> str:
    calls = [
        c for c in mock.await_args_list if c.kwargs["event_type"] == "livelink_threshold_alert"
    ]
    assert len(calls) == 1, mock.await_args_list
    return calls[0].kwargs["message"]


@pytest_asyncio.fixture
async def drop_params(db_session: AsyncSession) -> AsyncGenerator[None]:
    """Leave none of this file's parameter rows behind, whatever a test committed."""
    yield
    await db_session.rollback()
    await db_session.execute(
        delete(LiveLinkParameter).where(LiveLinkParameter.param_key.in_([COOLANT, BOOST, ODO]))
    )
    await db_session.commit()


@pytest.mark.unit
class TestAlertQuantity:
    """The class-to-quantity map and its canonical-unit gate.

    Imported per test so the behaviour tests below still collect, and fail on
    their assertions, against code that has no `alert_quantity` yet.
    """

    @pytest.mark.parametrize(
        ("param_class", "unit", "expected"),
        [
            ("temperature", None, "temperature"),
            ("temperature", "°C", "temperature"),
            ("temperature", "C", "temperature"),
            ("temperature", " °c ", "temperature"),
            ("speed", "km/h", "speed"),
            ("speed", "KM/H", "speed"),
            ("pressure", "kPa", "pressure"),
            ("pressure", "kpa", "pressure"),
            ("distance", "km", "distance"),
            ("distance", None, "distance"),
        ],
    )
    def test_a_canonical_reading_gets_its_quantity(
        self, param_class: str, unit: str | None, expected: str
    ) -> None:
        from app.services.livelink_alerts import alert_quantity

        assert alert_quantity(param_class, unit, odometer_normalised=False) == expected

    @pytest.mark.parametrize(
        ("param_class", "unit"),
        [
            ("temperature", "°F"),
            ("speed", "mph"),
            ("pressure", "psi"),
            ("pressure", "bar"),
            ("distance", "mi"),
            # A symbol that is canonical for another class is not this one's.
            ("pressure", "km"),
            ("percentage", "%"),
            ("voltage", "V"),
            ("frequency", None),
            (None, None),
        ],
    )
    def test_anything_else_prints_raw(self, param_class: str | None, unit: str | None) -> None:
        from app.services.livelink_alerts import alert_quantity

        assert alert_quantity(param_class, unit, odometer_normalised=False) is None

    def test_a_normalised_odometer_is_km_whatever_its_unit_says(self) -> None:
        from app.services.livelink_alerts import alert_quantity

        assert alert_quantity("distance", "mi", odometer_normalised=True) == "distance"

    def test_normalisation_vouches_only_for_distance(self) -> None:
        """Odometer normalisation converts to km, so it says nothing about a
        reading of any other class."""
        from app.services.livelink_alerts import alert_quantity

        assert alert_quantity("speed", "mph", odometer_normalised=True) is None


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.usefixtures("drop_params")
class TestCheckThresholdsRendersInTheReadersUnits:
    async def test_coolant_over_its_line_reads_in_fahrenheit(
        self, db_session: AsyncSession, make_livelink_vehicle, monkeypatch
    ) -> None:
        """106 °C over a 105 °C line, to an imperial owner: both numbers in °F."""
        vin, _device = await make_livelink_vehicle("t6cool", "1")
        db_session.add(_param(COOLANT, unit="°C", param_class="temperature", warning_max=105.0))
        await db_session.flush()
        mock = _capture(monkeypatch)

        await TelemetryService(db_session).check_thresholds(vin, COOLANT, 106.0)

        message = _alert_message(mock)
        assert "222.8 F vs threshold 221.0 F" in message
        assert "°C" not in message

    async def test_a_raw_unit_custom_key_prints_its_own_unit(
        self, db_session: AsyncSession, make_livelink_vehicle, monkeypatch
    ) -> None:
        """Regression guard: a parameter whose unit says psi holds psi, so the
        alert prints the numbers as stored, with psi, for any reader."""
        vin, _device = await make_livelink_vehicle("t6psi", "1")
        db_session.add(_param(BOOST, unit="psi", param_class="pressure", warning_max=35.0))
        await db_session.flush()
        mock = _capture(monkeypatch)

        await TelemetryService(db_session).check_thresholds(vin, BOOST, 40.0)

        assert "(40.0 psi vs threshold 35.0 psi)" in _alert_message(mock)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.usefixtures("livelink_enabled", "drop_params")
class TestOdometerLinesThroughIngest:
    """An odometer key is canonical km only when the source normalised it.

    Only a module with `Capability.ODOMETER` runs odometer normalisation, so a
    WiCAN's odometer is km whatever the parameter row's free-text unit says,
    and a generic_mqtt topic's is whatever was published (Codex R1-M1).
    """

    async def test_a_wican_odometer_line_reads_in_the_owners_distance_unit(
        self, db_session: AsyncSession, make_livelink_vehicle, monkeypatch
    ) -> None:
        """The row says mi (an HTTPS `config` once declared it), but the device
        reports km and ingest stored km: 100,500 km over a 100,000 km line."""
        _vin, device = await make_livelink_vehicle("t6odow", "1", odometer_unit="km")
        await db_session.commit()
        db_session.add(_param(ODO, unit="mi", param_class="distance", warning_max=100000.0))
        await db_session.flush()
        mock = _capture(monkeypatch)

        await ingest(
            WicanModule(),
            MqttEnvelope(f"wican/{device.device_id}/can/rx", f'{{"{ODO}": 100500}}'.encode()),
            db_session,
        )

        assert "(62,448 mi vs threshold 62,137 mi)" in _alert_message(mock)

    async def test_a_wican_key_its_device_does_not_declare_prints_raw(
        self, db_session: AsyncSession, make_livelink_vehicle, monkeypatch
    ) -> None:
        """Regression guard: a device's declared odometer key replaces the
        name match, so only that key is normalised. Another odometer-named key
        on the same WiCAN is stored as sent, and printed as it is."""
        _vin, device = await make_livelink_vehicle(
            "t6odod", "1", odometer_unit="km", odometer_param_key="A6-ODOMETER"
        )
        await db_session.commit()
        db_session.add(_param(ODO, unit="mi", param_class="distance", warning_max=60000.0))
        await db_session.flush()
        mock = _capture(monkeypatch)

        await ingest(
            WicanModule(),
            MqttEnvelope(f"wican/{device.device_id}/can/rx", f'{{"{ODO}": 62000}}'.encode()),
            db_session,
        )

        assert "(62000.0 mi vs threshold 60000.0 mi)" in _alert_message(mock)

    async def test_a_generic_mqtt_odometer_prints_raw(
        self, db_session: AsyncSession, make_livelink_vehicle, monkeypatch
    ) -> None:
        """Regression guard: generic_mqtt has no ODOMETER capability, so the
        same key from a topic is stored as published and printed as is."""
        _vin, device = await make_livelink_vehicle("t6odog", "1", kind="generic_mqtt")
        device_id = device.device_id
        await db_session.execute(
            delete(LiveLinkTopicMap).where(LiveLinkTopicMap.topic == ODO_TOPIC)
        )
        db_session.add(LiveLinkTopicMap(device_id=device_id, topic=ODO_TOPIC, param_key=ODO))
        await db_session.commit()
        module = GenericMqttModule()
        await module.refresh(db_session)
        try:
            db_session.add(_param(ODO, unit="mi", param_class="distance", warning_max=60000.0))
            await db_session.flush()
            mock = _capture(monkeypatch)

            await ingest(module, MqttEnvelope(ODO_TOPIC, b"62000"), db_session)

            assert "(62000.0 mi vs threshold 60000.0 mi)" in _alert_message(mock)
        finally:
            await db_session.rollback()
            await db_session.execute(
                delete(LiveLinkTopicMap).where(LiveLinkTopicMap.device_id == device_id)
            )
            await db_session.commit()
