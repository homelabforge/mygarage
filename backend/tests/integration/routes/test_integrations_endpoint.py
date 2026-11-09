"""The integrations tab strip.

Composition rules under test: every registered module is one tab, except
generic_mqtt, whose preset sensors share one tab per preset and whose other
devices get a tab each, plus one broker tab.
"""

import itertools
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import delete

from tests._logged import problems

BASE = "/api/livelink/integrations"
_SEQ = itertools.count()


@pytest_asyncio.fixture(autouse=True)
async def _clean_devices(db_session):
    """These tests assert exact tab lists, and the suite shares one database."""
    from app.models.livelink_device import LiveLinkDevice

    async def _wipe():
        await db_session.execute(delete(LiveLinkDevice))
        await db_session.commit()

    await _wipe()
    yield
    await _wipe()


@pytest_asyncio.fixture(autouse=True)
async def _livelink_on(db_session):
    """Every tab reads 'off'/'disabled' while LiveLink is globally off.

    The setting defaults to absent, which `is_enabled()` reads as False, so
    without this the whole strip is disabled and no status rule is exercised.
    The prior value is restored: the suite shares one database and other
    tests assert the default.
    """
    from app.models.settings import Setting

    existing = await db_session.get(Setting, "livelink_enabled")
    previous = existing.value if existing else None
    if existing:
        existing.value = "true"
    else:
        db_session.add(Setting(key="livelink_enabled", value="true"))
    await db_session.commit()

    yield

    row = await db_session.get(Setting, "livelink_enabled")
    if previous is None:
        if row:
            await db_session.delete(row)
    elif row:
        row.value = previous
    await db_session.commit()


@pytest.fixture
def broker_connected():
    with patch(
        "app.routes.livelink_admin.get_subscriber_status",
        return_value={"connection_status": "connected"},
    ) as m:
        yield m


async def _add_device(db_session, **over):
    from app.models.livelink_device import LiveLinkDevice

    defaults = {
        "device_id": f"d{next(_SEQ):08d}",
        "kind": "wican",
        "enabled": True,
        "device_status": "offline",
    }
    device = LiveLinkDevice(**{**defaults, **over})
    db_session.add(device)
    await db_session.commit()
    return device


def _by_id(body):
    return {tab["id"]: tab for tab in body["tabs"]}


def test_the_subscriber_status_helper_is_not_shadowed_by_the_route():
    """`livelink_admin` already defines a ROUTE HANDLER called
    `get_mqtt_status`, so importing the task function under its own name
    binds it and is then overwritten by the `def` further down the module.

    Every other test here patches the module attribute, so the mock is
    installed either way and they all pass while production calls a FastAPI
    handler with no arguments, raises TypeError, and reports the broker
    permanently down. Nothing but this identity check can see that.
    """
    from app.routes import livelink_admin
    from app.tasks import livelink_tasks

    assert livelink_admin.get_subscriber_status is livelink_tasks.get_mqtt_status
    assert isinstance(livelink_admin.get_subscriber_status(), dict)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_requires_admin(client):
    response = await client.get(BASE)
    assert response.status_code in (401, 403)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_always_offers_the_three_built_in_tabs(client, auth_headers, broker_connected):
    """A module with no devices still gets a tab, so the operator can find it
    in order to set it up."""
    response = await client.get(BASE, headers=auth_headers)

    assert response.status_code == 200
    tabs = _by_id(response.json())
    assert {"wican", "torque", "broker"} <= set(tabs)
    assert tabs["wican"]["label"] == "WiCAN"
    assert tabs["torque"]["label"] == "Torque"
    assert tabs["broker"]["label"] == "Mosquitto"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_generic_mqtt_has_no_tab_of_its_own(client, auth_headers, broker_connected):
    """generic_mqtt expands per device rather than appearing as one tab, so a
    bare 'Generic MQTT' entry would be a duplicate with nothing behind it."""
    tabs = _by_id((await client.get(BASE, headers=auth_headers)).json())
    assert "generic_mqtt" not in tabs


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_presets_sensors_share_one_tab(client, auth_headers, db_session, broker_connected):
    """Like WiCAN: two tanks are two devices under one tab, not two tabs.

    Titled by the PRESET, not a sensor's own name ("Front tank").
    """
    front = await _add_device(db_session, kind="generic_mqtt", preset_key="mopeka", label="Front")
    rear = await _add_device(db_session, kind="generic_mqtt", preset_key="mopeka", label="Rear")

    tabs = _by_id((await client.get(BASE, headers=auth_headers)).json())

    tab = tabs["preset:mopeka"]
    assert (tab["label"], tab["kind"], tab["device_count"]) == ("Mopeka", "generic_mqtt", 2)
    assert "Mopeka" in tab["description"]
    assert f"device:{front.device_id}" not in tabs
    assert f"device:{rear.device_id}" not in tabs


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_preset_tab_sits_between_the_broker_and_handmade_devices(
    client, auth_headers, db_session, broker_connected
):
    handmade = await _add_device(db_session, kind="generic_mqtt", label="My own gateway")
    await _add_device(db_session, kind="generic_mqtt", preset_key="mopeka")

    ids = [t["id"] for t in (await client.get(BASE, headers=auth_headers)).json()["tabs"]]

    assert ids.index("preset:mopeka") == ids.index("broker") + 1
    assert ids.index(f"device:{handmade.device_id}") == ids.index("preset:mopeka") + 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_preset_with_no_sensors_has_no_tab(client, auth_headers, broker_connected):
    """It is added from Add source; an empty tab would be a dead end."""
    tabs = _by_id((await client.get(BASE, headers=auth_headers)).json())

    assert "preset:mopeka" not in tabs


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_device_whose_preset_is_gone_keeps_a_tab_of_its_own(
    client, auth_headers, db_session, broker_connected
):
    """The two-tank preset's `rvgateway` on the dev database: it must stay
    reachable to be deleted."""
    device = await _add_device(
        db_session, kind="generic_mqtt", preset_key="mopeka_two_tank", label="Mopeka propane"
    )

    tabs = _by_id((await client.get(BASE, headers=auth_headers)).json())

    assert tabs[f"device:{device.device_id}"]["label"] == "Mopeka propane"
    assert tabs[f"device:{device.device_id}"]["description"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_handmade_device_is_labelled_from_its_label(
    client, auth_headers, db_session, broker_connected
):
    """Handmade devices are the documented escape hatch from the preset flow
    and must not vanish from the card."""
    device = await _add_device(
        db_session, kind="generic_mqtt", preset_key=None, label="My own gateway"
    )

    tabs = _by_id((await client.get(BASE, headers=auth_headers)).json())

    assert tabs[f"device:{device.device_id}"]["label"] == "My own gateway"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_unlabelled_device_falls_back_to_its_id(
    client, auth_headers, db_session, broker_connected
):
    device = await _add_device(db_session, kind="generic_mqtt", label=None)

    tabs = _by_id((await client.get(BASE, headers=auth_headers)).json())

    assert tabs[f"device:{device.device_id}"]["label"] == device.device_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_counts_are_reported_per_tab(client, auth_headers, db_session, broker_connected):
    await _add_device(db_session, kind="wican", device_status="online", vin=None)
    await _add_device(db_session, kind="wican", device_status="offline", vin=None)

    tabs = _by_id((await client.get(BASE, headers=auth_headers)).json())

    assert tabs["wican"]["device_count"] == 2
    assert tabs["wican"]["online_count"] == 1
    assert tabs["wican"]["linked_count"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unlinked_and_never_reported_are_told_apart_by_reason(
    client, auth_headers, db_session, broker_connected, test_vehicle
):
    """Both are status='attention' with online_count=0. Only `reason`
    distinguishes them, which is why the field exists."""
    await _add_device(db_session, kind="wican", device_status="online", vin=None)
    unlinked = _by_id((await client.get(BASE, headers=auth_headers)).json())["wican"]
    assert (unlinked["status"], unlinked["reason"]) == ("attention", "not_linked")

    from sqlalchemy import update

    from app.models.livelink_device import LiveLinkDevice

    await db_session.execute(
        update(LiveLinkDevice)
        .where(LiveLinkDevice.kind == "wican")
        .values(vin=test_vehicle["vin"], device_status="offline")
    )
    await db_session.commit()

    linked = _by_id((await client.get(BASE, headers=auth_headers)).json())["wican"]
    assert (linked["status"], linked["reason"]) == ("attention", "no_data")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_broker_status_comes_from_the_subscriber(client, auth_headers):
    with patch(
        "app.routes.livelink_admin.get_subscriber_status",
        return_value={"connection_status": "error"},
    ):
        tabs = _by_id((await client.get(BASE, headers=auth_headers)).json())

    assert (tabs["broker"]["status"], tabs["broker"]["reason"]) == (
        "attention",
        "broker_down",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_broker_read_failure_does_not_take_the_strip_down(
    client, auth_headers, caplog, caplog_only
):
    """G8. This card is one of six on the settings tab; a 500 here would blank
    the others too. A broker whose status cannot be read is exactly 'not
    currently healthy'."""
    with (
        caplog_only("app.routes.livelink_admin"),
        patch(
            "app.routes.livelink_admin.get_subscriber_status",
            side_effect=RuntimeError("subscriber exploded"),
        ),
    ):
        response = await client.get(BASE, headers=auth_headers)

    assert response.status_code == 200
    assert _by_id(response.json())["broker"]["status"] == "attention"
    (logged,) = problems(caplog, "app.routes.livelink_admin")
    assert logged.getMessage() == "Could not read MQTT subscriber status"
    assert logged.exc_info is not None
    assert str(logged.exc_info[1]) == "subscriber exploded"
