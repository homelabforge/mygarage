"""Topic-map CRUD, admin-gated, reload-triggering."""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete

BASE = "/api/livelink/topic-maps"
#: Not a preset-shaped key (`PROPANE_T1_...`): those belong to one preset
#: sensor's device alone, and `gw01` is a handmade one.
ROW = {
    "device_id": "gw01",
    "topic": "mygarage/rv/propane/tank1/level_percent",
    "param_key": "TANK1_LEVEL_PCT",
    "unit": "%",
}


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(db_session):
    """Empty topic maps and generic devices before and after each test.

    These tests assert exact list contents and exact conflict behaviour, and
    the suite shares one database with no per-test rollback.
    """
    from app.models.livelink_device import LiveLinkDevice
    from app.models.livelink_topic_map import LiveLinkTopicMap

    async def _wipe():
        await db_session.execute(delete(LiveLinkTopicMap))
        await db_session.execute(
            delete(LiveLinkDevice).where(LiveLinkDevice.kind == "generic_mqtt")
        )
        await db_session.commit()

    await _wipe()
    yield
    await _wipe()


@pytest.fixture
def no_reload():
    with patch("app.routes.livelink_admin.mqtt_subscriber.reload", new=AsyncMock()) as r:
        yield r


@pytest.mark.asyncio
async def test_create_then_list(client, auth_headers, no_reload):
    resp = await client.post(BASE, json=ROW, headers=auth_headers)
    assert resp.status_code == 201
    listed = await client.get(BASE, headers=auth_headers)
    assert [r["topic"] for r in listed.json()] == [ROW["topic"]]


@pytest.mark.asyncio
async def test_create_triggers_a_resubscribe(client, auth_headers, no_reload):
    await client.post(BASE, json=ROW, headers=auth_headers)
    no_reload.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_triggers_a_resubscribe(client, auth_headers, no_reload):
    created = await client.post(BASE, json=ROW, headers=auth_headers)
    no_reload.reset_mock()
    resp = await client.delete(f"{BASE}/{created.json()['id']}", headers=auth_headers)
    assert resp.status_code == 204
    no_reload.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_triggers_a_resubscribe(client, auth_headers, no_reload):
    created = await client.post(BASE, json=ROW, headers=auth_headers)
    no_reload.reset_mock()
    resp = await client.patch(
        f"{BASE}/{created.json()['id']}", json={"enabled": False}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    no_reload.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_topic", ["a/+/b", "a/#", "#"])
async def test_wildcards_are_rejected(client, auth_headers, no_reload, bad_topic):
    resp = await client.post(BASE, json={**ROW, "topic": bad_topic}, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_param_key_required_unless_role_is_status(client, auth_headers, no_reload):
    bad = {k: v for k, v in ROW.items() if k != "param_key"}
    assert (await client.post(BASE, json=bad, headers=auth_headers)).status_code == 422
    ok = {**bad, "role": "status"}
    assert (await client.post(BASE, json=ok, headers=auth_headers)).status_code == 201


@pytest.mark.asyncio
async def test_param_key_is_uppercased(client, auth_headers, no_reload):
    resp = await client.post(
        BASE, json={**ROW, "param_key": "tank1_level_pct"}, headers=auth_headers
    )
    assert resp.json()["param_key"] == "TANK1_LEVEL_PCT"


@pytest.mark.asyncio
async def test_a_duplicate_topic_and_param_is_a_conflict(client, auth_headers, no_reload):
    await client.post(BASE, json=ROW, headers=auth_headers)
    assert (await client.post(BASE, json=ROW, headers=auth_headers)).status_code == 409


@pytest.mark.asyncio
async def test_listing_can_be_filtered_by_device(client, auth_headers, no_reload):
    await client.post(BASE, json=ROW, headers=auth_headers)
    await client.post(
        BASE, json={**ROW, "device_id": "other", "topic": "z/z"}, headers=auth_headers
    )
    resp = await client.get(f"{BASE}?device_id=gw01", headers=auth_headers)
    assert [r["device_id"] for r in resp.json()] == ["gw01"]


@pytest.mark.asyncio
async def test_non_admins_are_refused(client, non_admin_headers):
    assert (await client.get(BASE, headers=non_admin_headers)).status_code in (401, 403)
    assert (await client.post(BASE, json=ROW, headers=non_admin_headers)).status_code in (401, 403)


@pytest.mark.asyncio
async def test_a_generic_device_can_be_created(client, auth_headers, test_vehicle):
    """R1-H1: without this route, mappings reference a device that cannot exist."""
    resp = await client.post(
        "/api/livelink/devices",
        json={
            "device_id": "rvgw",
            "kind": "generic_mqtt",
            "label": "RV Gateway",
            "vin": test_vehicle["vin"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "generic_mqtt"


@pytest.mark.asyncio
async def test_creating_a_device_with_an_unknown_kind_is_refused(client, auth_headers):
    """The registry is the source of truth for valid kinds."""
    resp = await client.post(
        "/api/livelink/devices",
        json={"device_id": "x", "kind": "not_a_real_source"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_duplicate_device_id_is_a_conflict(client, auth_headers):
    body = {"device_id": "rvgw", "kind": "generic_mqtt"}
    await client.post("/api/livelink/devices", json=body, headers=auth_headers)
    resp = await client.post("/api/livelink/devices", json=body, headers=auth_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_a_topic_already_claimed_by_another_device_is_refused(
    client, auth_headers, no_reload
):
    """R1-H2 at write time."""
    await client.post(BASE, json=ROW, headers=auth_headers)
    resp = await client.post(
        BASE,
        json={**ROW, "device_id": "someone_else", "param_key": "OTHER_KEY"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_patch_cannot_null_param_key_on_a_telemetry_row(client, auth_headers, no_reload):
    """R1-F4: PATCH must re-validate the merged row."""
    created = await client.post(BASE, json=ROW, headers=auth_headers)
    resp = await client.patch(
        f"{BASE}/{created.json()['id']}", json={"param_key": None}, headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_canonicalizes_param_key_like_create(client, auth_headers, no_reload):
    created = await client.post(BASE, json=ROW, headers=auth_headers)
    resp = await client.patch(
        f"{BASE}/{created.json()['id']}", json={"param_key": "lower_case"}, headers=auth_headers
    )
    assert resp.json()["param_key"] == "LOWER_CASE"


@pytest.mark.asyncio
async def test_deleting_a_device_resubscribes(client, auth_headers, no_reload):
    await client.post(
        "/api/livelink/devices",
        json={"device_id": "rvgw", "kind": "generic_mqtt"},
        headers=auth_headers,
    )
    no_reload.reset_mock()
    resp = await client.delete("/api/livelink/devices/rvgw", headers=auth_headers)
    assert resp.status_code == 204
    no_reload.assert_awaited_once()


@pytest.mark.asyncio
async def test_sources_endpoint_reports_the_registry(client, auth_headers):
    resp = await client.get("/api/livelink/sources", headers=auth_headers)
    kinds = {s["kind"]: s for s in resp.json()}
    assert set(kinds) == {"wican", "torque", "generic_mqtt"}
    assert "drive_session" not in kinds["generic_mqtt"]["capabilities"]
    assert "drive_session" in kinds["wican"]["capabilities"]


@pytest_asyncio.fixture
async def other_kinds(db_session):
    """A WiCAN and a Torque phone, gone again afterwards."""
    from app.models.livelink_device import LiveLinkDevice

    ids = ("tmkindwican1", "tmkindtorque1")
    db_session.add(LiveLinkDevice(device_id=ids[0], kind="wican", enabled=True))
    db_session.add(LiveLinkDevice(device_id=ids[1], kind="torque", enabled=True))
    await db_session.commit()
    yield ids
    await db_session.rollback()
    await db_session.execute(delete(LiveLinkDevice).where(LiveLinkDevice.device_id.in_(ids)))
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_map_naming_another_kinds_device_is_refused(
    client, auth_headers, no_reload, other_kinds
):
    """FW-B-c5: topic maps feed the generic MQTT module, which won't ingest
    another kind's device (FB-1), so a map naming a WiCAN would sit there doing
    nothing. Refused when it's made. Red on f3a8b81c (201)."""
    wican_id, _torque_id = other_kinds

    resp = await client.post(BASE, json={**ROW, "device_id": wican_id}, headers=auth_headers)

    assert resp.status_code == 422
    assert resp.json()["detail"] == (
        f"Device {wican_id} is a wican device. Topic maps are for generic MQTT devices."
    )
    no_reload.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_map_cant_be_repointed_at_another_device(
    client, auth_headers, no_reload, other_kinds
):
    """Regression guard: a PATCH can't change a map's device at all, which is
    why the kind check (FW-B-c5) only needs to sit on create."""
    _wican_id, torque_id = other_kinds
    created = await client.post(BASE, json=ROW, headers=auth_headers)

    resp = await client.patch(
        f"{BASE}/{created.json()['id']}", json={"device_id": torque_id}, headers=auth_headers
    )

    assert resp.status_code == 422
    assert resp.json()["details"][0]["loc"] == ["body", "device_id"]


@pytest.mark.asyncio
async def test_a_map_made_before_the_rule_can_still_be_switched_off(
    client, auth_headers, no_reload, other_kinds, db_session
):
    """Regression guard: an old map naming a WiCAN has to stay editable, or it
    can't be switched off. Only a new claim is checked. Kills checking every
    PATCH."""
    from app.models.livelink_topic_map import LiveLinkTopicMap

    wican_id, _torque_id = other_kinds
    row = LiveLinkTopicMap(device_id=wican_id, topic="tmkind/old/map", param_key="OLD_MAP")
    db_session.add(row)
    await db_session.commit()

    resp = await client.patch(f"{BASE}/{row.id}", json={"enabled": False}, headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_a_map_naming_a_generic_device_is_still_made(
    client, auth_headers, no_reload, db_session
):
    """Regression guard, the positive control: kills refusing every device on file."""
    from app.models.livelink_device import LiveLinkDevice

    db_session.add(LiveLinkDevice(device_id="tmkindgen1", kind="generic_mqtt", enabled=True))
    await db_session.commit()

    resp = await client.post(BASE, json={**ROW, "device_id": "tmkindgen1"}, headers=auth_headers)

    assert resp.status_code == 201
