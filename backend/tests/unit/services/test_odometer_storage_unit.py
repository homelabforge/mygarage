"""What storage says an odometer is in: km, on every path that converts one.

R1-M1 (Codex): `ODOMETER_MI` is miles for every device kind, so a generic MQTT
topic mapped to it stores km like WiCAN's does, and the browser, which reads
the key as canonical km, shows what was sent.

FB-5 (Fable): a normalised odometer's parameter row names km. A kept legacy
`mi` row reached `auto_register_parameter` through the reading's unit, so the
fleet-wide row said mi over km values.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device_unit import LiveLinkDeviceUnit
from app.models.livelink_parameter import LiveLinkParameter
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.livelink_ingest import ingest
from app.services.livelink_sources.base import MqttEnvelope
from app.services.livelink_sources.generic_mqtt import GenericMqttModule
from app.services.livelink_sources.wican import WicanModule
from app.utils.datetime_utils import utc_now

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("livelink_enabled", "drop_params")]

#: `ODOMETER_MI` is the key under test, so its row is the shared one: cleared
#: before and after. The others are this file's own.
MI_KEY = "ODOMETER_MI"
LEGACY_KEY = "FB5_ODOMETER_LEGACY"
MILES_ROW_KEY = "FB5_ODOMETER_MILESROW"
#: Plus the case's suffix: the other device's raw rows are committed, and the
#: file DB keeps them for the next case, which would then see them too.
SHARED_ROW_KEY = "FB5_ODOMETER_SHARED"
SHARED_ROW_CASES = ("1", "2", "3", "4")
TOPIC = "r1m1/test/odometer_mi"


@pytest_asyncio.fixture
async def drop_params(db_session: AsyncSession) -> AsyncGenerator[None]:
    keys = [MI_KEY, LEGACY_KEY, MILES_ROW_KEY, *(SHARED_ROW_KEY + s for s in SHARED_ROW_CASES)]
    await db_session.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(keys)))
    await db_session.commit()
    yield
    await db_session.rollback()
    await db_session.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(keys)))
    await db_session.commit()


async def _param_unit(db: AsyncSession, key: str) -> str | None:
    return await db.scalar(select(LiveLinkParameter.unit).where(LiveLinkParameter.param_key == key))


async def _raw(db: AsyncSession, device_id: str, key: str) -> list[float]:
    rows = await db.execute(
        select(VehicleTelemetry.value).where(
            VehicleTelemetry.device_id == device_id, VehicleTelemetry.param_key == key
        )
    )
    return list(rows.scalars().all())


@pytest.mark.parametrize("unit", [None, "mi"])
async def test_a_generic_mqtt_odometer_mi_is_stored_as_km(
    db_session: AsyncSession, make_livelink_vehicle, unit: str | None
):
    """Raw 50,000 mi is 80,467.2 km, unrounded like every simple-path reading.
    Red on ed8fbef9, which stored 50,000 under a key the browser reads as km
    (31,069 mi to an imperial viewer)."""
    vin, device = await make_livelink_vehicle("r1m1gen", "1" if unit else "2", kind="generic_mqtt")
    device_id = device.device_id
    await db_session.execute(delete(LiveLinkTopicMap).where(LiveLinkTopicMap.topic == TOPIC))
    db_session.add(LiveLinkTopicMap(device_id=device_id, topic=TOPIC, param_key=MI_KEY, unit=unit))
    await db_session.commit()
    module = GenericMqttModule()
    await module.refresh(db_session)
    try:
        await ingest(module, MqttEnvelope(TOPIC, b"50000"), db_session)
        await db_session.commit()

        assert await _raw(db_session, device_id, MI_KEY) == [80467.2]
        latest = await db_session.scalar(
            select(VehicleTelemetryLatest.value).where(
                VehicleTelemetryLatest.vin == vin, VehicleTelemetryLatest.param_key == MI_KEY
            )
        )
        assert latest == 80467.2
        # FB-5 on this path too: a topic's `mi` doesn't label km values.
        assert await _param_unit(db_session, MI_KEY) == "km"
    finally:
        await db_session.rollback()
        await db_session.execute(
            delete(LiveLinkTopicMap).where(LiveLinkTopicMap.device_id == device_id)
        )
        await db_session.commit()
        await module.refresh(db_session)


async def test_a_generic_mqtt_odometer_mi_alert_reads_in_the_owners_unit(
    db_session: AsyncSession, make_livelink_vehicle, monkeypatch
):
    """The alert follows storage: km, so the imperial owner reads miles. Red
    on ed8fbef9, which stored 50,000 raw, under the 80,000 km line, so nothing
    fired at all."""
    _vin, device = await make_livelink_vehicle("r1m1alt", "1", kind="generic_mqtt")
    device_id = device.device_id
    await db_session.execute(delete(LiveLinkTopicMap).where(LiveLinkTopicMap.topic == TOPIC))
    db_session.add(LiveLinkTopicMap(device_id=device_id, topic=TOPIC, param_key=MI_KEY))
    db_session.add(
        LiveLinkParameter(
            param_key=MI_KEY,
            display_name=MI_KEY,
            param_class="distance",
            category="engine",
            show_on_dashboard=True,
            archive_only=False,
            storage_interval_seconds=0,
            warning_max=80000.0,
        )
    )
    await db_session.commit()
    module = GenericMqttModule()
    await module.refresh(db_session)
    send = AsyncMock(return_value={"ntfy": True})
    monkeypatch.setattr(
        "app.services.notifications.dispatcher.NotificationDispatcher.dispatch", send
    )
    try:
        await ingest(module, MqttEnvelope(TOPIC, b"50000"), db_session)

        (call,) = [
            c for c in send.await_args_list if c.kwargs["event_type"] == "livelink_threshold_alert"
        ]
        message = call.kwargs["message"]
        assert "exceeded maximum: 50,000 mi vs threshold 49,710 mi." in message
    finally:
        await db_session.rollback()
        await db_session.execute(
            delete(LiveLinkTopicMap).where(LiveLinkTopicMap.device_id == device_id)
        )
        await db_session.commit()
        await module.refresh(db_session)


async def test_a_legacy_miles_odometer_registers_its_parameter_in_km(
    db_session: AsyncSession, make_livelink_vehicle
):
    """The legacy row gives the reading `mi`, which is what it's converted
    FROM; the stored value is km and so is its row. Red on ed8fbef9 (mi)."""
    _vin, device = await make_livelink_vehicle("fb5leg", "1")
    db_session.add(
        LiveLinkDeviceUnit(
            device_id=device.device_id,
            param_key=LEGACY_KEY,
            unit="mi",
            param_class="distance",
            source="legacy",
        )
    )
    await db_session.commit()

    await ingest(
        WicanModule(),
        MqttEnvelope(f"wican/{device.device_id}/can/rx", f'{{"{LEGACY_KEY}": 50000}}'.encode()),
        db_session,
    )
    await db_session.commit()

    assert await _raw(db_session, device.device_id, LEGACY_KEY) == [80467.0]
    assert await _param_unit(db_session, LEGACY_KEY) == "km"


@pytest.mark.parametrize(
    "label",
    [
        "mi",
        "Miles",
        # FW-A-r3 (N2): a row registered before FB-5 says nothing. The browser
        # trusts this label now, so it gets km too. Red on 4e32c6eb.
        None,
    ],
)
async def test_an_odometer_row_labelled_miles_is_relabelled_km(
    db_session: AsyncSession, make_livelink_vehicle, label: str | None
):
    """A row an earlier version labelled miles (or nothing) over km values, the way R4
    relabels an mph row. Its lines were always compared with km values, so they
    stay. Red on ed8fbef9 (the label stayed)."""
    _vin, device = await make_livelink_vehicle(
        "fb5row", {"mi": "1", "Miles": "2"}.get(label or "", "3"), odometer_unit="mi"
    )
    db_session.add(
        LiveLinkParameter(
            param_key=MILES_ROW_KEY,
            display_name=MILES_ROW_KEY,
            unit=label,
            param_class="distance",
            category="engine",
            show_on_dashboard=True,
            archive_only=False,
            storage_interval_seconds=0,
            warning_max=200000.0,
        )
    )
    await db_session.commit()

    await ingest(
        WicanModule(),
        MqttEnvelope(f"wican/{device.device_id}/can/rx", f'{{"{MILES_ROW_KEY}": 50000}}'.encode()),
        db_session,
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(LiveLinkParameter).where(LiveLinkParameter.param_key == MILES_ROW_KEY)
    )
    assert row is not None
    assert (row.unit, row.warning_max) == ("km", 200000.0)


@pytest.mark.parametrize(
    ("suffix", "other_kind", "other_declares", "expected"),
    [
        # A generic device stores an undeclared odometer-named key raw, so the
        # shared row can't say km. Red on 63640d97 (km).
        ("1", "generic_mqtt", None, None),
        # Regression guards: a device that records the key stores it in km,
        # whatever its kind, so the label goes on.
        ("2", "generic_mqtt", "same", "km"),
        ("3", "wican", None, "km"),
        # A WiCAN that declares a different key converts only that one, so its
        # rows under this key are raw too. Red on 63640d97 (km).
        ("4", "wican", "other", None),
    ],
)
async def test_a_wican_km_label_waits_on_a_key_another_device_stores_raw(
    db_session: AsyncSession,
    make_livelink_vehicle,
    suffix: str,
    other_kind: str,
    other_declares: str | None,
    expected: str | None,
):
    """Parameter rows are global by key. Migration 133 skips a key another
    device sends raw, and the live relabel asks the same question (FW-A-r4b).
    The WiCAN's own value is stored in km either way."""
    key = SHARED_ROW_KEY + suffix
    _vin, wican = await make_livelink_vehicle("fb5shr", suffix, odometer_unit="mi")
    other_vin, other = await make_livelink_vehicle(
        "fb5oth",
        suffix,
        kind=other_kind,
        odometer_param_key={None: None, "same": key, "other": "MY_ODO"}[other_declares],
    )
    now = utc_now()
    db_session.add(
        VehicleTelemetry(
            vin=other_vin,
            device_id=other.device_id,
            param_key=key,
            value=50000.0,
            timestamp=now,
            received_at=now,
        )
    )
    db_session.add(
        LiveLinkParameter(
            param_key=key,
            display_name=key,
            unit=None,
            param_class="distance",
            category="engine",
            show_on_dashboard=True,
            archive_only=False,
            storage_interval_seconds=0,
        )
    )
    await db_session.commit()

    await ingest(
        WicanModule(),
        MqttEnvelope(f"wican/{wican.device_id}/can/rx", f'{{"{key}": 50000}}'.encode()),
        db_session,
    )
    await db_session.commit()

    assert await _param_unit(db_session, key) == expected
    assert await _raw(db_session, wican.device_id, key) == [80467.0]
