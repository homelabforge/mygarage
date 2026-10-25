"""A preset adds ONE sensor: its own device, and a topic map per chosen reading.

Sensor indexes are never reused and the suite shares one database, so every
index here is read from `next_sensor_index` at the start of the test, never
assumed to be 1.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import LiveLinkParameter
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import (
    TelemetryDailySummary,
    VehicleTelemetry,
    VehicleTelemetryLatest,
)
from app.services.livelink_sources.presets import PRESETS
from app.services.livelink_sources.presets.sensors import next_sensor_index
from app.utils.datetime_utils import utc_now

BASE = "/api/livelink/presets"
MOPEKA = PRESETS["mopeka"]


@pytest_asyncio.fixture(autouse=True)
async def _clean(db_session):
    """Topic maps, generic devices and preset-shaped parameters, before and after.

    Parameters too: they are what keeps an index held after its device is gone,
    so a leftover one moves every later test's index along.
    """

    async def _wipe():
        await db_session.execute(delete(LiveLinkTopicMap))
        await db_session.execute(
            delete(LiveLinkDevice).where(LiveLinkDevice.kind == "generic_mqtt")
        )
        await db_session.execute(
            delete(LiveLinkParameter).where(
                LiveLinkParameter.param_key.startswith("PROPANE_T")
                | LiveLinkParameter.param_key.startswith("RV_GATEWAY_")
            )
        )
        await db_session.commit()

    await _wipe()
    yield
    await _wipe()


@pytest.fixture
def no_reload():
    with patch("app.routes.livelink_admin.mqtt_subscriber.reload", new=AsyncMock()) as r:
        yield r


def _topics(tag: str, *suffixes: str) -> dict[str, str]:
    """Distinct per test: a topic already mapped anywhere is refused."""
    return {suffix: f"test/{tag}/{suffix.lower()}" for suffix in suffixes}


async def _add(client, headers, label="Front tank", vin=None, topics=None):
    return await client.post(
        f"{BASE}/mopeka/apply",
        json={"label": label, "vin": vin, "topics": topics or _topics(label, "LEVEL_PCT")},
        headers=headers,
    )


async def _parameter(db_session, key):
    db_session.expire_all()
    return (
        await db_session.execute(
            select(LiveLinkParameter).where(LiveLinkParameter.param_key == key)
        )
    ).scalar_one_or_none()


async def _sensor_count(db_session) -> int:
    return (
        await db_session.execute(
            select(func.count())
            .select_from(LiveLinkDevice)
            .where(LiveLinkDevice.preset_key == "mopeka")
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_catalogue_describes_one_sensor(client, auth_headers):
    resp = await client.get(BASE, headers=auth_headers)

    assert resp.status_code == 200
    mopeka = {p["name"]: p for p in resp.json()}["mopeka"]
    assert mopeka["title"] == "Mopeka"
    assert [r["suffix"] for r in mopeka["readings"]] == [
        "LEVEL_PCT",
        "TEMP_C",
        "SENSOR_BATT_PCT",
        "QUALITY",
        "DEPTH_MM",
        "REJECTED",
        "AVAILABLE",
    ]
    assert [r["suffix"] for r in mopeka["readings"] if r["required"]] == ["LEVEL_PCT"]
    level = mopeka["readings"][0]
    assert level["default_topic"] == "level_percent"
    assert "level" in level["keywords"]


def test_no_reading_belongs_to_the_gateway():
    """The relay's Wi-Fi signal and uptime are the gateway's, not a tank's."""
    for reading in MOPEKA.readings:
        assert "GATEWAY" not in reading.suffix
        assert "gateway" not in reading.name


def test_the_description_assumes_no_count_layout_or_bottle():
    """Somebody else's setup might be different: one tank or three, another
    gateway, another bottle."""
    for word in ("Two", "ESPHome", "30 lb", "gateway"):
        assert word not in MOPEKA.description


def test_each_reading_says_how_it_is_shown():
    """The tank card and the settings drawer read these: "sensor heard" is Yes
    or No, not 1.0, and quality is a grade out of 3."""
    shown = {r.suffix: (r.format, r.max_value) for r in MOPEKA.readings}

    assert shown["AVAILABLE"] == ("boolean", None)
    assert shown["REJECTED"] == ("count", None)
    assert shown["QUALITY"] == ("of_max", 3)
    assert shown["TEMP_C"] == ("value", None)
    assert shown["DEPTH_MM"] == ("value", None)


def test_the_tank_is_filled_by_the_level():
    assert MOPEKA.fill_suffix == "LEVEL_PCT"
    assert MOPEKA.reading(MOPEKA.fill_suffix) is not None


def test_the_level_and_battery_offer_alert_lines():
    lines = {r.suffix: (r.low, r.critical) for r in MOPEKA.readings if r.alert_lines}

    assert lines == {"LEVEL_PCT": (25.0, 10.0), "SENSOR_BATT_PCT": (20.0, None)}
    assert MOPEKA.reading("LEVEL_PCT").alert_lines == ("low", "critical")
    assert MOPEKA.reading("SENSOR_BATT_PCT").alert_lines == ("low",)


def test_only_percent_readings_offer_alert_lines():
    """The settings edit lines as 0 to 100 with no unit conversion, so a line
    on a converted reading (a temperature) would be saved in the wrong unit."""
    for reading in MOPEKA.readings:
        if reading.alert_lines:
            assert reading.unit == "%", reading.suffix


def test_every_default_topic_is_one_exact_segment():
    """It is appended to the level topic's folder, so it cannot carry a slash
    or a wildcard."""
    for reading in MOPEKA.readings:
        assert not {"/", "+", "#"} & set(reading.default_topic)


# ---------------------------------------------------------------------------
# Adding a sensor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adding_a_sensor_creates_its_device_maps_and_names(
    client, auth_headers, db_session, test_vehicle, no_reload
):
    n = await next_sensor_index(db_session, MOPEKA)

    resp = await _add(
        client,
        auth_headers,
        vin=test_vehicle["vin"],
        topics=_topics("front", "LEVEL_PCT", "TEMP_C"),
    )

    assert resp.status_code == 201
    assert resp.json()["device_id"] == f"mopeka-t{n}"
    assert resp.json()["preset_key"] == "mopeka"
    device = (
        await db_session.execute(
            select(LiveLinkDevice).where(LiveLinkDevice.device_id == f"mopeka-t{n}")
        )
    ).scalar_one()
    assert (device.kind, device.label, device.vin) == (
        "generic_mqtt",
        "Front tank",
        test_vehicle["vin"],
    )
    maps = (
        (
            await db_session.execute(
                select(LiveLinkTopicMap)
                .where(LiveLinkTopicMap.device_id == f"mopeka-t{n}")
                .order_by(LiveLinkTopicMap.id)
            )
        )
        .scalars()
        .all()
    )
    # Level first: the readings list shows keys in mapping order.
    assert [(m.topic, m.param_key) for m in maps] == [
        ("test/front/level_pct", f"PROPANE_T{n}_LEVEL_PCT"),
        ("test/front/temp_c", f"PROPANE_T{n}_TEMP_C"),
    ]
    # One at a time: `_parameter` expires everything it did not just load.
    level = await _parameter(db_session, f"PROPANE_T{n}_LEVEL_PCT")
    level_fields = (level.display_name, level.storage_interval_seconds)
    temp = await _parameter(db_session, f"PROPANE_T{n}_TEMP_C")
    temp_fields = (temp.display_name, temp.storage_interval_seconds)
    # Retained messages replay on every resubscribe; without an interval each
    # reconnect writes a row.
    assert level_fields == ("Front tank level", 300)
    assert temp_fields == ("Front tank temperature", 300)


@pytest.mark.asyncio
async def test_a_new_sensor_starts_with_the_default_alert_lines(
    client, auth_headers, db_session, no_reload
):
    n = await next_sensor_index(db_session, MOPEKA)

    resp = await _add(
        client, auth_headers, topics=_topics("lines", "LEVEL_PCT", "SENSOR_BATT_PCT", "TEMP_C")
    )

    assert resp.status_code == 201
    level = await _parameter(db_session, f"PROPANE_T{n}_LEVEL_PCT")
    level_lines = (level.warning_min, level.critical_min)
    battery = await _parameter(db_session, f"PROPANE_T{n}_SENSOR_BATT_PCT")
    battery_lines = (battery.warning_min, battery.critical_min)
    temp = await _parameter(db_session, f"PROPANE_T{n}_TEMP_C")
    temp_lines = (temp.warning_min, temp.critical_min)
    assert level_lines == (25.0, 10.0)
    assert battery_lines == (20.0, None)
    assert temp_lines == (None, None)


@pytest.mark.asyncio
async def test_a_reading_left_blank_is_not_mapped(client, auth_headers, db_session, no_reload):
    topics = {**_topics("blank", "LEVEL_PCT"), "TEMP_C": "  "}

    resp = await _add(client, auth_headers, topics=topics)

    assert resp.status_code == 201
    maps = (
        (
            await db_session.execute(
                select(LiveLinkTopicMap.param_key).where(
                    LiveLinkTopicMap.device_id == resp.json()["device_id"]
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(maps) == 1 and maps[0].endswith("_LEVEL_PCT")


@pytest.mark.asyncio
async def test_each_sensor_gets_the_next_index(client, auth_headers, db_session, no_reload):
    n = await next_sensor_index(db_session, MOPEKA)

    first = await _add(client, auth_headers, label="Front tank")
    second = await _add(client, auth_headers, label="Rear tank")

    assert first.json()["device_id"] == f"mopeka-t{n}"
    assert second.json()["device_id"] == f"mopeka-t{n + 1}"


@pytest.mark.asyncio
async def test_a_new_sensor_never_takes_an_older_sensors_index(
    client, auth_headers, db_session, no_reload
):
    """One more than the highest index held, so the gap a deleted sensor
    leaves stays a gap: a third tank is t3, never a second t1."""
    n = await next_sensor_index(db_session, MOPEKA)
    await _add(client, auth_headers, label="Front tank")
    await _add(client, auth_headers, label="Rear tank")

    deleted = await client.delete(f"/api/livelink/devices/mopeka-t{n}", headers=auth_headers)
    third = await _add(client, auth_headers, label="Spare tank")

    assert deleted.status_code == 204
    assert third.json()["device_id"] == f"mopeka-t{n + 2}"


@pytest.mark.asyncio
async def test_deleting_a_sensor_deletes_its_readings(
    client, auth_headers, db_session, test_user, test_vehicle, no_reload
):
    """A sensor's keys are its own, so once it is gone nothing can show them in
    context: left behind they were loose tiles on the Live tab and a second
    "Front tank level" in Charts. Every vehicle it reported to, and a reading
    whose mapping was removed earlier, go with it. A key mapped by hand on the
    sensor may be shared with another device, and stays, as does every other
    sensor's: t10, which shares t1's digits, and a hand-made lowercase key,
    which SQLite's case-blind LIKE would otherwise match."""
    n = await next_sensor_index(db_session, MOPEKA)
    vin = test_vehicle["vin"]
    old_vin = "SENSORMOVEDFROM01"
    moved_from = Vehicle(
        vin=old_vin,
        user_id=test_user["id"],
        nickname="Old trailer",
        vehicle_type="Car",
        year=2010,
        make="Test",
        model="Trailer",
    )
    db_session.add(moved_from)
    await db_session.commit()
    await _add(client, auth_headers, vin=vin, topics=_topics("gone", "LEVEL_PCT", "TEMP_C"))
    await _add(
        client, auth_headers, label="Rear tank", vin=vin, topics=_topics("kept", "LEVEL_PCT")
    )
    unmapped = f"PROPANE_T{n}_DEPTH_MM"
    shared = "TEST_SENSOR_SHARED_CABIN_TEMP"
    db_session.add(
        LiveLinkTopicMap(
            device_id=f"mopeka-t{n}", topic="test/gone/cabin", role="telemetry", param_key=shared
        )
    )
    gone = [f"PROPANE_T{n}_LEVEL_PCT", f"PROPANE_T{n}_TEMP_C", unmapped]
    lookalikes = [f"PROPANE_T{n}0_LEVEL_PCT", f"propane_t{n}_level_pct"]
    kept = [f"PROPANE_T{n + 1}_LEVEL_PCT", *lookalikes, shared]
    at = utc_now()
    for key in [unmapped, shared, *lookalikes]:
        db_session.add(LiveLinkParameter(param_key=key))
    for key in gone + kept:
        # Apart in time: history is unique per (device, key, timestamp).
        for on, when in ((vin, at), (old_vin, at - timedelta(days=1))):
            db_session.add(VehicleTelemetryLatest(vin=on, param_key=key, value=1.0, timestamp=when))
            db_session.add(
                VehicleTelemetry(
                    vin=on, device_id=f"mopeka-t{n}", param_key=key, value=1.0, timestamp=when
                )
            )
            db_session.add(TelemetryDailySummary(vin=on, param_key=key, date=when, sample_count=1))
    await db_session.commit()

    try:
        resp = await client.delete(f"/api/livelink/devices/mopeka-t{n}", headers=auth_headers)

        assert resp.status_code == 204
        db_session.expire_all()
        left = {}
        for model in (
            VehicleTelemetryLatest,
            VehicleTelemetry,
            TelemetryDailySummary,
            LiveLinkParameter,
        ):
            keys = await db_session.execute(
                select(model.param_key).where(model.param_key.in_(gone + kept))
            )
            left[model.__name__] = sorted(set(keys.scalars()))
        assert left == dict.fromkeys(left, sorted(kept))
    finally:
        for model in (VehicleTelemetryLatest, VehicleTelemetry, TelemetryDailySummary):
            await db_session.execute(delete(model).where(model.param_key.in_(gone + kept)))
        # `_clean` takes the rest, but its prefix match is case-blind on SQLite
        # only, so the lowercase key goes here for PostgreSQL.
        await db_session.execute(
            delete(LiveLinkParameter).where(LiveLinkParameter.param_key.in_([shared, *lookalikes]))
        )
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == old_vin))
        await db_session.commit()


@pytest.mark.asyncio
async def test_deleting_a_handmade_device_keeps_its_readings(
    client, auth_headers, db_session, test_vehicle, no_reload
):
    """Only a preset sensor's keys are its own. A device made by hand, even one
    named like a sensor, maps keys another device may share."""
    n = await next_sensor_index(db_session, MOPEKA)
    vin = test_vehicle["vin"]
    key = f"PROPANE_T{n}_LEVEL_PCT"
    db_session.add(LiveLinkDevice(device_id=f"mopeka-t{n}", kind="generic_mqtt", vin=vin))
    db_session.add(LiveLinkParameter(param_key=key))
    db_session.add(VehicleTelemetryLatest(vin=vin, param_key=key, value=1.0, timestamp=utc_now()))
    await db_session.commit()

    try:
        resp = await client.delete(f"/api/livelink/devices/mopeka-t{n}", headers=auth_headers)

        assert resp.status_code == 204
        db_session.expire_all()
        latest = await db_session.execute(
            select(VehicleTelemetryLatest.param_key).where(VehicleTelemetryLatest.param_key == key)
        )
        assert list(latest.scalars()) == [key]
        assert await _parameter(db_session, key) is not None
    finally:
        await db_session.execute(
            delete(VehicleTelemetryLatest).where(VehicleTelemetryLatest.param_key == key)
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_an_index_held_only_by_a_parameter_is_skipped(
    client, auth_headers, db_session, no_reload
):
    """The device and its maps are gone; the parameter is what remembers."""
    n = await next_sensor_index(db_session, MOPEKA)
    db_session.add(LiveLinkParameter(param_key=f"PROPANE_T{n}_LEVEL_PCT"))
    await db_session.commit()

    resp = await _add(client, auth_headers)

    assert resp.json()["device_id"] == f"mopeka-t{n + 1}"


@pytest.mark.asyncio
async def test_an_index_held_only_by_a_device_id_is_skipped(
    client, auth_headers, db_session, no_reload
):
    """A device made by hand under a sensor's name: creating over it would 500
    on the primary key."""
    n = await next_sensor_index(db_session, MOPEKA)
    db_session.add(LiveLinkDevice(device_id=f"mopeka-t{n}", kind="generic_mqtt"))
    await db_session.commit()

    resp = await _add(client, auth_headers)

    assert resp.json()["device_id"] == f"mopeka-t{n + 1}"


@pytest.mark.asyncio
async def test_a_topic_mapped_by_another_device_is_409_and_creates_nothing(
    client, auth_headers, db_session, no_reload
):
    """One topic, one device: the subscriber ignores a topic two devices map."""
    db_session.add(
        LiveLinkTopicMap(
            device_id="handmade1", topic="test/taken/level", role="telemetry", param_key="HM_LEVEL"
        )
    )
    await db_session.commit()

    resp = await _add(client, auth_headers, topics={"LEVEL_PCT": "test/taken/level"})

    assert resp.status_code == 409
    assert "test/taken/level" in resp.json()["detail"]
    assert "handmade1" in resp.json()["detail"]
    assert await _sensor_count(db_session) == 0
    no_reload.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "topics"),
    [
        pytest.param("Front tank", {"TEMP_C": "test/v/temp"}, id="no-level"),
        pytest.param("Front tank", {"LEVEL_PCT": "  "}, id="blank-level"),
        pytest.param("Front tank", {"LEVEL_PCT": "test/v/+/level"}, id="wildcard-plus"),
        pytest.param("Front tank", {"LEVEL_PCT": "test/v/#"}, id="wildcard-hash"),
        pytest.param(
            "Front tank", {"LEVEL_PCT": "test/v/level", "BOGUS": "test/v/b"}, id="unknown-reading"
        ),
        pytest.param(
            "Front tank", {"LEVEL_PCT": "test/v/same", "TEMP_C": "test/v/same"}, id="same-topic"
        ),
        pytest.param("Front tank", {"LEVEL_PCT": "t/" + "x" * 254}, id="topic-too-long"),
        pytest.param("   ", {"LEVEL_PCT": "test/v/level"}, id="blank-label"),
        pytest.param("x" * 61, {"LEVEL_PCT": "test/v/level"}, id="label-too-long"),
    ],
)
async def test_an_invalid_sensor_is_422_and_creates_nothing(
    client, auth_headers, db_session, no_reload, label, topics
):
    resp = await _add(client, auth_headers, label=label, topics=topics)

    assert resp.status_code == 422
    assert await _sensor_count(db_session) == 0


@pytest.mark.asyncio
async def test_adding_a_sensor_resubscribes(client, auth_headers, no_reload):
    await _add(client, auth_headers)

    no_reload.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_unknown_preset_is_404(client, auth_headers):
    resp = await client.post(
        f"{BASE}/nope/apply",
        json={"label": "x", "topics": {"LEVEL_PCT": "test/nope/level"}},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_admins_are_refused(client, non_admin_headers):
    assert (await _add(client, non_admin_headers)).status_code in (401, 403)


@pytest.mark.asyncio
async def test_a_sensor_says_which_preset_made_it(client, auth_headers, no_reload):
    """The drawers group and title a device by it."""
    device_id = (await _add(client, auth_headers)).json()["device_id"]

    resp = await client.get(f"/api/livelink/devices/{device_id}", headers=auth_headers)

    assert resp.json()["preset_key"] == "mopeka"


# ---------------------------------------------------------------------------
# Renaming a sensor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_renaming_a_sensor_renames_its_readings(
    client, auth_headers, db_session, test_vehicle, no_reload
):
    """The Live tab shows two tanks' readings side by side, by these names."""
    device_id = (
        await _add(
            client,
            auth_headers,
            vin=test_vehicle["vin"],
            topics=_topics("rename", "LEVEL_PCT", "TEMP_C"),
        )
    ).json()["device_id"]
    n = MOPEKA.index_of_device(device_id)
    temp = await _parameter(db_session, f"PROPANE_T{n}_TEMP_C")
    temp.display_name = "Bottle temp"  # set by hand: theirs
    await db_session.commit()

    resp = await client.put(
        f"/api/livelink/devices/{device_id}", json={"label": "Rear tank"}, headers=auth_headers
    )

    assert resp.status_code == 200
    assert (await _parameter(db_session, f"PROPANE_T{n}_LEVEL_PCT")).display_name == (
        "Rear tank level"
    )
    assert (await _parameter(db_session, f"PROPANE_T{n}_TEMP_C")).display_name == "Bottle temp"


@pytest.mark.asyncio
async def test_a_change_that_is_not_a_rename_leaves_the_names_alone(
    client, auth_headers, db_session, test_vehicle, no_reload
):
    device_id = (await _add(client, auth_headers)).json()["device_id"]
    n = MOPEKA.index_of_device(device_id)

    resp = await client.put(
        f"/api/livelink/devices/{device_id}", json={"enabled": False}, headers=auth_headers
    )

    assert resp.status_code == 200
    assert (await _parameter(db_session, f"PROPANE_T{n}_LEVEL_PCT")).display_name == (
        "Front tank level"
    )


# ---------------------------------------------------------------------------
# A sensor's keys are its own (E10)
# ---------------------------------------------------------------------------

MAPS = "/api/livelink/topic-maps"


@pytest.mark.asyncio
async def test_another_device_cannot_map_a_sensors_key(client, auth_headers, db_session, no_reload):
    """The key carries the sensor's name ("Front tank level"), so another
    device writing it would file its readings under that name."""
    device_id = (await _add(client, auth_headers)).json()["device_id"]
    n = MOPEKA.index_of_device(device_id)

    resp = await client.post(
        MAPS,
        json={
            "device_id": "handmade1",
            "topic": "test/foreign/level",
            "param_key": f"PROPANE_T{n}_LEVEL_PCT",
        },
        headers=auth_headers,
    )

    assert resp.status_code == 409
    assert device_id in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_sensor_can_map_another_reading_of_its_own(
    client, auth_headers, db_session, no_reload
):
    """The Topic mappings editor inside the sensor's block."""
    device_id = (await _add(client, auth_headers)).json()["device_id"]
    n = MOPEKA.index_of_device(device_id)

    resp = await client.post(
        MAPS,
        json={
            "device_id": device_id,
            "topic": "test/own/depth",
            "param_key": f"PROPANE_T{n}_DEPTH_MM",
        },
        headers=auth_headers,
    )

    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_a_mapping_cannot_be_repointed_at_a_sensors_key(
    client, auth_headers, db_session, no_reload
):
    device_id = (await _add(client, auth_headers)).json()["device_id"]
    n = MOPEKA.index_of_device(device_id)
    own = await client.post(
        MAPS,
        json={"device_id": "handmade1", "topic": "test/hm/level", "param_key": "HM_LEVEL"},
        headers=auth_headers,
    )

    resp = await client.patch(
        f"{MAPS}/{own.json()['id']}",
        json={"param_key": f"PROPANE_T{n}_LEVEL_PCT"},
        headers=auth_headers,
    )

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_an_older_mapping_of_a_sensor_key_can_still_be_edited(
    client, auth_headers, db_session, no_reload
):
    """A key mapped before the rule existed (the two-tank preset's `rvgateway`
    on the dev database) is refused only a NEW claim: switching it off must
    still work, or it can never be retired."""
    row = LiveLinkTopicMap(
        device_id="rvgateway",
        topic="test/old/level",
        role="telemetry",
        param_key="PROPANE_T1_LEVEL_PCT",
    )
    db_session.add(row)
    await db_session.commit()

    resp = await client.patch(f"{MAPS}/{row.id}", json={"enabled": False}, headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_other_keys_stay_shareable(client, auth_headers, db_session, no_reload):
    """Two handmade gateways on two vehicles publishing the same kind of
    reading is a supported setup."""
    for device_id in ("handmade1", "handmade2"):
        resp = await client.post(
            MAPS,
            json={"device_id": device_id, "topic": f"test/{device_id}/t", "param_key": "CABIN_T"},
            headers=auth_headers,
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Who may delete a sensor (R6), and a racing apply (B-13)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def owned_by_non_admin(db_session, non_admin_user):
    """A vehicle the non-admin user owns, so their delete passes the owner check."""
    vin = "SENSOROWNERNA0001"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=non_admin_user["id"],
            nickname="Their trailer",
            vehicle_type="Car",
            year=2015,
            make="Test",
            model="Trailer",
        )
    )
    await db_session.commit()
    yield vin
    await db_session.rollback()
    await db_session.execute(delete(LiveLinkDevice).where(LiveLinkDevice.vin == vin))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


@pytest.mark.asyncio
async def test_an_owner_who_is_not_an_admin_cannot_delete_a_preset_sensor(
    client, auth_headers, non_admin_headers, db_session, owned_by_non_admin, no_reload
):
    """Deleting a sensor drops its global topic maps and its readings on every
    vehicle it ever reported to, so it's global LiveLink infra: admin only."""
    added = await _add(client, auth_headers, vin=owned_by_non_admin)
    assert added.status_code == 201, added.text
    device_id = added.json()["device_id"]

    resp = await client.delete(f"/api/livelink/devices/{device_id}", headers=non_admin_headers)

    assert resp.status_code == 403, resp.text
    db_session.expire_all()
    assert await db_session.get(LiveLinkDevice, added.json()["id"]) is not None
    maps = await db_session.execute(
        select(LiveLinkTopicMap.id).where(LiveLinkTopicMap.device_id == device_id)
    )
    assert len(maps.all()) == 1


@pytest.mark.asyncio
async def test_an_owner_can_still_delete_a_handmade_device(
    client, non_admin_headers, db_session, owned_by_non_admin, no_reload
):
    """Regression guard: a device no preset made keeps owner delete."""
    db_session.add(
        LiveLinkDevice(device_id="handmade-owned", kind="generic_mqtt", vin=owned_by_non_admin)
    )
    await db_session.commit()

    resp = await client.delete("/api/livelink/devices/handmade-owned", headers=non_admin_headers)

    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_an_apply_that_loses_a_race_is_409_and_creates_nothing(
    client, auth_headers, db_session, test_sessionmaker, no_reload
):
    """Two applies read the same free index; the second insert hits the unique
    device id. The rival commits from its own connection between this request's
    index read and its insert, which is exactly the window a concurrent request has."""
    from app.services.livelink_sources.presets import sensors

    real_next = sensors.next_sensor_index

    async def _rival_wins(db, preset):
        index = await real_next(db, preset)
        async with test_sessionmaker() as rival:
            rival.add(
                LiveLinkDevice(
                    device_id=preset.device_id(index),
                    kind=preset.kind,
                    label="Rival",
                    preset_key=preset.name,
                    enabled=True,
                )
            )
            await rival.commit()
        return index

    with patch.object(sensors, "next_sensor_index", new=_rival_wins):
        resp = await _add(client, auth_headers, label="Loser", topics=_topics("race", "LEVEL_PCT"))

    assert resp.status_code == 409, resp.text
    db_session.expire_all()
    labels = await db_session.execute(
        select(LiveLinkDevice.label).where(LiveLinkDevice.preset_key == "mopeka")
    )
    assert list(labels.scalars()) == ["Rival"]
    maps = await db_session.execute(
        select(LiveLinkTopicMap.id).where(LiveLinkTopicMap.topic == "test/race/level_pct")
    )
    assert maps.all() == []
    no_reload.assert_not_awaited()
