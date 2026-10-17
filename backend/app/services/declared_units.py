"""Units a source declares ahead of its values, held per device in memory (#223).

Torque sends each PID's default unit once per session, in a request with no
values. Holding them here instead of registering a parameter per declared PID
means only PIDs that carry a value get a registry row (Jamey 2026-10-16,
fable-plan/F-3). The app runs one worker for APScheduler, so one map serves
every request; a restart forgets it until the next session start.
"""

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)

#: Most keys held per device, so a stream of made-up PIDs can't grow the map forever.
_MAX_KEYS_PER_DEVICE = 512

#: device_id -> param_key -> unit. Registered devices only, each capped above.
_BY_DEVICE: dict[str, dict[str, str]] = {}


def remember(device_id: str, units: Mapping[str, str]) -> None:
    """Keep a device's declared units; a later declaration wins, key by key.

    Past the cap a new key is dropped, but a key already held still updates.
    """
    held = _BY_DEVICE.setdefault(device_id, {})
    dropped = 0
    for key, unit in units.items():
        if key in held or len(held) < _MAX_KEYS_PER_DEVICE:
            held[key] = unit
        else:
            dropped += 1
    if dropped:
        logger.debug(
            "Dropped %d declared unit(s) from %s: it already holds %d keys",
            dropped,
            device_id,
            _MAX_KEYS_PER_DEVICE,
        )


def unit_for(device_id: str, param_key: str) -> str | None:
    """The unit a device declared for a key since this process started, if any."""
    return _BY_DEVICE.get(device_id, {}).get(param_key)
