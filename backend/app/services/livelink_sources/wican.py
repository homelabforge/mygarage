"""WiCAN OBD2 dongle, over MQTT.

Parsing only; extracted verbatim in behavior from
`mqtt_subscriber._process_message` and its three handlers.

WiCAN is the one module that still needs a wildcard subscription: its topics
carry a device id that is discovered at runtime, so the exact-topics rule that
governs `generic_mqtt` cannot apply here.
"""

from __future__ import annotations

import json
import logging
import math
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.livelink_sources.base import (
    BaseSourceModule,
    Capability,
    InferSession,
    IngestBatch,
    MqttEnvelope,
    Reading,
    StatusTransition,
    StoragePolicy,
)
from app.utils.autopid_normalizer import DTC_KEY, canonical_param_key, normalize_autopid_data
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

#: A system letter and four hex digits (P0301, U0100, P2A0F). Every one of the
#: 9341 seeded definitions has this shape, so nothing else would ever match one.
#: It also keeps a token over `VehicleDTC.code`'s 10 chars from failing the
#: flush on PG.
_DTC_SHAPE = re.compile(r"[PCBU][0-9A-F]{4}")


def dtc_codes_from_wire(value: object) -> list[str]:
    """Split a comma-separated DTC string into clean codes.

    Stripped, uppercased, blanks and repeats dropped, order kept. Anything but
    a string is no codes. A token that isn't DTC-shaped is dropped with a debug
    line, so one junk token can't take the frame's readings down with it.
    Repeats are dropped to save `process_dtcs` a lookup each.
    """
    if not isinstance(value, str):
        return []
    codes: list[str] = []
    for part in value.split(","):
        code = part.strip().upper()
        if not code:
            continue
        if not _DTC_SHAPE.fullmatch(code):
            logger.debug("Dropping a token that isn't a DTC: %s", sanitize_for_log(code))
            continue
        codes.append(code)
    return list(dict.fromkeys(codes))


class WicanModule(BaseSourceModule):
    """The WiCAN dongle."""

    kind = "wican"
    capabilities = frozenset(
        {
            Capability.TELEMETRY,
            Capability.DRIVE_SESSION,
            Capability.DTC,
            Capability.ODOMETER,
            Capability.COMMANDS,
            Capability.SD_BACKFILL,
            Capability.AUTO_DISCOVER,
        }
    )
    #: Exactly today's behavior: unconditional latest, odometer sync and
    #: movement observation on, storage intervals honoured.
    storage_policy = StoragePolicy(
        latest="always",
        apply_storage_interval=True,
        sync_odometer=True,
        observe_movement=True,
    )

    async def subscriptions(self, db: AsyncSession) -> list[str]:
        """The configured prefix, wildcarded. Device ids are runtime-discovered."""
        from app.services.mqtt_subscriber import mqtt_subscriber

        prefix = await mqtt_subscriber.configured_topic_prefix(db)
        return [f"{prefix}/+/#"] if prefix else []

    async def parse(self, env) -> IngestBatch | None:
        if not isinstance(env, MqttEnvelope):
            return None
        parts = env.topic.split("/")
        if len(parts) < 3:
            logger.debug("Ignoring malformed topic: %s", sanitize_for_log(env.topic))
            return None

        device_key = parts[1].lower().replace(":", "").replace("-", "")
        subtopic = "/".join(parts[2:])

        try:
            data = json.loads(env.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.debug("Failed to parse MQTT payload: %s", exc)
            return None

        if subtopic == "can/status":
            status = str(data.get("status", "unknown")).lower()
            ecu = status if status in ("online", "offline") else "unknown"
            return IngestBatch(
                device_key=device_key,
                ecu_status=ecu,
                device_status="online",
                session=StatusTransition(ecu_status=ecu),
                # _handle_status updates status OUTSIDE its `if device.vin`
                # block, so an unlinked device still shows online.
                requires_link=False,
            )

        if subtopic == "battery":
            voltage = data.get("battery_voltage")
            if voltage is None:
                return None
            return IngestBatch(
                device_key=device_key,
                device_status="online",
                battery_voltage=float(voltage),
                readings=[
                    Reading("BATTERY_VOLTAGE", float(voltage), unit="V", param_class="voltage")
                ],
                # _handle_battery updates status BEFORE its `if device.vin`.
                requires_link=False,
                # It does NOT clear pending offline and does NOT alert. Both
                # verified as zero occurrences in mqtt_subscriber.py:366-401.
                clear_pending_offline=False,
                alert_on_thresholds=False,
            )

        if subtopic == "can/rx":
            autopid = normalize_autopid_data(data)
            # Lifted before the numeric filter below, which would drop it.
            dtcs = dtc_codes_from_wire(autopid.get(DTC_KEY))
            # Canonicalise HERE. `normalize_autopid_data` does not uppercase;
            # historically `store_telemetry` did it downstream, which left
            # WiCAN the only source emitting non-canonical keys and made
            # `Reading`'s "already canonical" contract a lie. Idempotent, so
            # the delegating path still produces identical stored keys.
            # `json.loads` takes NaN and Infinity literals, so finite only.
            readings = [
                Reading(canonical_param_key(key), float(value))
                for key, value in autopid.items()
                if isinstance(value, (int, float)) and math.isfinite(value)
            ]
            # Nothing usable in the frame (`{"X": null}`): not proof the ECU
            # is on, so no batch, or it would mark the ECU online (A-7).
            if not readings and not dtcs:
                return None
            if not readings:
                # Codes only. Same A-7 logic: a code list doesn't prove the ECU
                # is on, so no ecu_status, no session and no pending clear.
                return IngestBatch(device_key=device_key, dtcs=dtcs, device_status="online")
            return IngestBatch(
                device_key=device_key,
                readings=readings,
                dtcs=dtcs,
                device_status="online",
                ecu_status="online",
                session=InferSession(),
                # can/rx returns at `if not device.vin` before any status
                # update (mqtt_subscriber.py:419-423).
                requires_link=True,
                # It DOES clear pending offline and DOES alert today.
                clear_pending_offline=True,
                alert_on_thresholds=True,
            )

        logger.debug("Ignoring unknown subtopic: %s", sanitize_for_log(subtopic))
        return None
