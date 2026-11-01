"""Status rules for the integrations card.

Every rule here has a wrong, obvious version that the naive reading of the
card's requirements produces. Each test names the wrong version it rules out.
"""

from datetime import timedelta

import pytest

from app.models.livelink_device import LiveLinkDevice
from app.schemas.livelink import DeviceFirmwareStatus
from app.services.livelink_integrations import (
    derive_broker_status,
    derive_group_status,
    device_is_linked,
    device_is_online,
    firmware_is_pending,
)
from app.utils.datetime_utils import utc_now

NOW = utc_now()
TIMEOUT = 15


def _device(**over) -> LiveLinkDevice:
    defaults = {
        "device_id": "d1",
        "kind": "wican",
        "enabled": True,
        "vin": "1HGCM82633A004352",
        "device_status": "online",
        "last_seen": NOW,
    }
    return LiveLinkDevice(**{**defaults, **over})


def _fw(**over) -> DeviceFirmwareStatus:
    defaults = {
        "device_id": "d1",
        "current_version": "4.40",
        "latest_version": "4.50",
        "update_available": True,
        "skipped_version": None,
    }
    return DeviceFirmwareStatus(**{**defaults, **over})


# --- device_is_online ------------------------------------------------------


def test_online_device_is_online():
    assert device_is_online(_device(), TIMEOUT, NOW) is True


def test_disabled_device_is_never_online():
    """A disabled device freezes at its last status: ingest returns before the
    status update, and the offline sweep ignores `enabled`. So it reads
    'online' for another 15-20 minutes after being switched off."""
    assert device_is_online(_device(enabled=False), TIMEOUT, NOW) is False


def test_recently_seen_unknown_status_counts_as_online():
    """A handmade generic_mqtt device with no role='status' mapping never sets
    device_status at all, so it stays 'unknown' forever while last_seen is
    bumped on every batch. Reading device_status alone leaves its tab
    permanently yellow while readings are flowing."""
    device = _device(device_status="unknown", last_seen=NOW - timedelta(minutes=1))
    assert device_is_online(device, TIMEOUT, NOW) is True


def test_stale_unknown_status_is_not_online():
    device = _device(device_status="unknown", last_seen=NOW - timedelta(minutes=30))
    assert device_is_online(device, TIMEOUT, NOW) is False


def test_never_seen_unknown_status_is_not_online():
    device = _device(device_status="unknown", last_seen=None)
    assert device_is_online(device, TIMEOUT, NOW) is False


def test_explicitly_offline_device_is_not_online():
    device = _device(device_status="offline", last_seen=NOW)
    assert device_is_online(device, TIMEOUT, NOW) is False


# --- device_is_linked ------------------------------------------------------


def test_device_with_a_vin_is_linked():
    assert device_is_linked(_device()) is True


def test_device_without_a_vin_is_not_linked():
    assert device_is_linked(_device(vin=None)) is False


# --- firmware_is_pending ---------------------------------------------------


def test_available_update_is_pending():
    assert firmware_is_pending(_fw()) is True


def test_skipped_update_is_not_pending():
    """Without this carve-out an operator who deliberately skipped a release
    sees a permanently yellow dot, which trains them to ignore the colour."""
    assert firmware_is_pending(_fw(skipped_version="4.50")) is False


def test_skipping_an_older_version_leaves_a_newer_one_pending():
    assert firmware_is_pending(_fw(latest_version="4.60", skipped_version="4.50")) is True


def test_no_firmware_record_is_not_pending():
    assert firmware_is_pending(None) is False


# --- derive_group_status ---------------------------------------------------


def test_livelink_disabled_overrides_everything():
    """LiveLink being off is the single fact worth showing. Four yellow dots
    underneath it would bury it."""
    result = derive_group_status([_device()], {}, TIMEOUT, NOW, livelink_enabled=False)
    assert (result.status, result.reason) == ("off", "disabled")


def test_no_devices_is_not_configured():
    result = derive_group_status([], {}, TIMEOUT, NOW, livelink_enabled=True)
    assert (result.status, result.reason) == ("off", "not_configured")


def test_all_devices_disabled_is_off():
    result = derive_group_status([_device(enabled=False)], {}, TIMEOUT, NOW, livelink_enabled=True)
    assert (result.status, result.reason) == ("off", "disabled")


def test_healthy_device_is_ok():
    result = derive_group_status([_device()], {}, TIMEOUT, NOW, livelink_enabled=True)
    assert (result.status, result.reason) == ("ok", "receiving")


def test_online_but_unlinked_is_not_ok():
    """The state every install passes through. A WiCAN auto-discovers itself
    and its can/status handler sets device_status='online' with
    requires_link=False, while the can/rx handler carrying the actual telemetry
    is requires_link=True and gets dropped. The naive rule paints this tab
    green and writes 'Receiving data' while storing nothing."""
    result = derive_group_status([_device(vin=None)], {}, TIMEOUT, NOW, livelink_enabled=True)
    assert (result.status, result.reason) == ("attention", "not_linked")


def test_linked_but_offline_is_no_data():
    result = derive_group_status(
        [_device(device_status="offline")], {}, TIMEOUT, NOW, livelink_enabled=True
    )
    assert (result.status, result.reason) == ("attention", "no_data")


def test_healthy_device_with_a_pending_update_reports_firmware():
    result = derive_group_status([_device()], {"d1": _fw()}, TIMEOUT, NOW, livelink_enabled=True)
    assert (result.status, result.reason) == ("attention", "firmware_update")


def test_skipped_update_leaves_a_healthy_device_ok():
    result = derive_group_status(
        [_device()], {"d1": _fw(skipped_version="4.50")}, TIMEOUT, NOW, livelink_enabled=True
    )
    assert (result.status, result.reason) == ("ok", "receiving")


def test_setup_problems_outrank_a_firmware_update():
    """An unlinked device with an update pending needs linking first; the
    update is the 'everything works but there is a new version' case."""
    result = derive_group_status(
        [_device(vin=None)], {"d1": _fw()}, TIMEOUT, NOW, livelink_enabled=True
    )
    assert result.reason == "not_linked"


def test_one_healthy_device_among_several_is_enough():
    devices = [_device(device_id="a", device_status="offline"), _device(device_id="b")]
    result = derive_group_status(devices, {}, TIMEOUT, NOW, livelink_enabled=True)
    assert (result.status, result.reason) == ("ok", "receiving")


def test_disabled_devices_do_not_count_toward_health():
    devices = [_device(device_id="a", enabled=False), _device(device_id="b", vin=None)]
    result = derive_group_status(devices, {}, TIMEOUT, NOW, livelink_enabled=True)
    assert (result.status, result.reason) == ("attention", "not_linked")


# --- derive_broker_status --------------------------------------------------


@pytest.mark.parametrize(
    ("connection_status", "expected"),
    [
        ("connected", ("ok", "receiving")),
        ("disconnected", ("attention", "broker_down")),
        ("connecting", ("attention", "broker_down")),
        ("error", ("attention", "broker_down")),
        ("disabled", ("off", "disabled")),
    ],
)
def test_broker_status_covers_every_connection_state(connection_status, expected):
    """These five are the whole vocabulary of MQTTStatusResponse."""
    result = derive_broker_status(connection_status, livelink_enabled=True)
    assert (result.status, result.reason) == expected


def test_broker_reports_off_when_livelink_is_disabled():
    result = derive_broker_status("connected", livelink_enabled=False)
    assert (result.status, result.reason) == ("off", "disabled")


def test_unknown_broker_state_fails_safe():
    """A state this code has never heard of is 'not currently healthy', never
    'fine'."""
    result = derive_broker_status("something_new", livelink_enabled=True)
    assert result.status == "attention"
