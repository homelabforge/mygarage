"""Every device response says whether the device is online (G5b-58).

DeviceRow read `device_status` raw, so an uploading Torque phone (which never
leaves 'unknown') read as not online, and so did a disabled WiCAN's frozen
'online' the other way round. The rule is `device_is_online`, the same one the
integrations card and the vehicle status use.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import LiveLinkParameter
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.services.livelink_sources.presets import PRESETS
from app.utils.datetime_utils import utc_now

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

DEVICES = "/api/livelink/devices"


@pytest_asyncio.fixture
async def made(db_session) -> AsyncGenerator[list[str]]:
    """Device ids a test creates, removed afterwards with their maps."""
    ids: list[str] = []
    yield ids
    await db_session.rollback()
    await db_session.execute(delete(LiveLinkTopicMap).where(LiveLinkTopicMap.device_id.in_(ids)))
    await db_session.execute(delete(LiveLinkDevice).where(LiveLinkDevice.device_id.in_(ids)))
    await db_session.commit()


async def _device(db_session, made: list[str], **fields) -> str:
    device_id = f"on{uuid.uuid4().hex[:10]}"
    db_session.add(LiveLinkDevice(device_id=device_id, **{"enabled": True, **fields}))
    await db_session.commit()
    made.append(device_id)
    return device_id


async def _list(client, auth_headers) -> dict:
    resp = await client.get(DEVICES, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_an_uploading_torque_phone_is_online(client, auth_headers, db_session, made):
    device_id = await _device(
        db_session, made, kind="torque", device_status="unknown", last_seen=utc_now()
    )

    resp = await client.get(f"{DEVICES}/{device_id}", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["online"] is True


async def test_a_disabled_device_is_offline_whatever_it_last_said(
    client, auth_headers, db_session, made
):
    device_id = await _device(
        db_session, made, kind="wican", device_status="online", last_seen=utc_now(), enabled=False
    )

    resp = await client.get(f"{DEVICES}/{device_id}", headers=auth_headers)

    assert resp.json()["online"] is False


async def test_the_list_counts_online_by_the_same_rule(client, auth_headers, db_session, made):
    """online_count counted raw `device_status`, so a list with one uploading
    Torque phone said 0 online next to a phone the row now calls online.

    Two steps, so a decoy can't cancel the phone out: the phone alone moves the
    count by one, then devices that aren't online (a disabled WiCAN frozen at
    'online', a Torque phone quiet for days) move it by nothing.
    """
    before = await _list(client, auth_headers)
    device_id = await _device(
        db_session, made, kind="torque", device_status="unknown", last_seen=utc_now()
    )

    with_phone = await _list(client, auth_headers)

    row = next(d for d in with_phone["devices"] if d["device_id"] == device_id)
    assert row["online"] is True
    assert with_phone["online_count"] - before["online_count"] == 1

    await _device(
        db_session, made, kind="wican", device_status="online", last_seen=utc_now(), enabled=False
    )
    await _device(
        db_session,
        made,
        kind="torque",
        device_status="unknown",
        last_seen=utc_now() - timedelta(days=2),
    )

    with_decoys = await _list(client, auth_headers)

    assert with_decoys["online_count"] == with_phone["online_count"]
    assert with_decoys["online_count"] == sum(d["online"] for d in with_decoys["devices"])


async def test_an_update_answers_online(client, auth_headers, db_session, made):
    device_id = await _device(
        db_session, made, kind="torque", device_status="unknown", last_seen=utc_now()
    )

    resp = await client.put(f"{DEVICES}/{device_id}", json={"label": "Phone"}, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["online"] is True


#: A brand new device is never online, which is also the schema default, so a
#: route returning the bare ORM row would pass. Forcing the rule's answer to
#: True tells "computed" from "defaulted".
_ALWAYS_ONLINE = "app.routes.livelink_admin.device_is_online"


async def test_a_created_device_answers_online(client, auth_headers, made):
    device_id = f"on{uuid.uuid4().hex[:10]}"
    made.append(device_id)

    with patch(_ALWAYS_ONLINE, return_value=True):
        resp = await client.post(
            DEVICES, json={"device_id": device_id, "kind": "generic_mqtt"}, headers=auth_headers
        )

    assert resp.status_code == 201, resp.text
    assert resp.json()["online"] is True


async def test_an_applied_preset_answers_online(client, auth_headers, db_session, made):
    with (
        patch("app.routes.livelink_admin.mqtt_subscriber.reload", new=AsyncMock()),
        patch(_ALWAYS_ONLINE, return_value=True),
    ):
        resp = await client.post(
            "/api/livelink/presets/mopeka/apply",
            json={"label": "Online test tank", "topics": {"LEVEL_PCT": "test/online/level"}},
            headers=auth_headers,
        )

    assert resp.status_code == 201, resp.text
    device_id = resp.json()["device_id"]
    made.append(device_id)
    try:
        assert resp.json()["online"] is True
    finally:
        # Its parameters hold the sensor index; the preset tests read the next
        # free one, so leave none behind.
        index = PRESETS["mopeka"].index_of_device(device_id)
        await db_session.execute(
            delete(LiveLinkParameter).where(
                LiveLinkParameter.param_key.startswith(f"PROPANE_T{index}_")
            )
        )
        await db_session.commit()


async def test_a_blank_label_on_create_is_no_label(client, auth_headers, db_session, made):
    """H-F3/P2D-3: the update schema strips and blanks to None; create didn't,
    so "   " was stored and beat the device id fallback."""
    device_id = f"on{uuid.uuid4().hex[:10]}"
    made.append(device_id)

    resp = await client.post(
        DEVICES,
        json={"device_id": device_id, "kind": "generic_mqtt", "label": "   "},
        headers=auth_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["label"] is None
    db_session.expire_all()
    stored = (
        await db_session.execute(
            LiveLinkDevice.__table__.select().where(LiveLinkDevice.device_id == device_id)
        )
    ).one()
    assert stored.label is None


async def test_a_padded_label_on_create_is_stored_stripped(client, auth_headers, made):
    device_id = f"on{uuid.uuid4().hex[:10]}"
    made.append(device_id)

    resp = await client.post(
        DEVICES,
        json={"device_id": device_id, "kind": "generic_mqtt", "label": "  Gate  "},
        headers=auth_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["label"] == "Gate"


async def test_a_blank_label_on_update_is_no_label(client, auth_headers, db_session, made):
    """Regression guard: the update path already cleared a blank name."""
    device_id = await _device(db_session, made, kind="generic_mqtt", label="Old")

    resp = await client.put(f"{DEVICES}/{device_id}", json={"label": "   "}, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["label"] is None
