"""Units a source declares ahead of its values, held per device in memory (#223).

Torque sends each PID's default unit once per session, in a request with no
values. Holding them here instead of registering a parameter per declared PID
means only PIDs that carry a value get a registry row (Jamey 2026-10-16,
fable-plan/F-3). The app runs one worker for APScheduler, so one map serves
every request; a restart forgets it until the next session start.
"""

from collections.abc import Mapping

#: device_id -> param_key -> unit. A household's devices, so it never needs pruning.
_BY_DEVICE: dict[str, dict[str, str]] = {}


def remember(device_id: str, units: Mapping[str, str]) -> None:
    """Keep a device's declared units; a later declaration wins, key by key."""
    _BY_DEVICE.setdefault(device_id, {}).update(units)


def unit_for(device_id: str, param_key: str) -> str | None:
    """The unit a device declared for a key since this process started, if any."""
    return _BY_DEVICE.get(device_id, {}).get(param_key)
