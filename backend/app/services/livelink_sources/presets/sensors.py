"""Creating, renaming and guarding a preset-made sensor.

Each sensor made from a preset is its own `generic_mqtt` device with one topic
map per reading its owner chose.

Two facts shape everything here:

- Parameter metadata is global per `param_key` (`livelink_parameters` has no
  device or VIN column), and `vehicle_telemetry_latest` is UNIQUE(vin,
  param_key). So each sensor's keys must be unique across ALL sensors, not just
  those on one vehicle: `{key_prefix}_T{n}_{suffix}`, with `n` never used
  before.
- One topic, one device: `generic_mqtt` ignores a topic mapped to more than one
  device, with an ERROR log. So a topic already mapped anywhere is refused up
  front instead of becoming a mapping the subscriber silently drops.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import DISPLAY_NAME_MAX_LENGTH, LiveLinkParameter
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.vehicle_telemetry import (
    TelemetryDailySummary,
    VehicleTelemetry,
    VehicleTelemetryLatest,
)
from app.schemas.telemetry import LiveSensor, LiveSensorReading
from app.services.livelink_integrations import device_is_online
from app.services.livelink_sources.presets import PRESETS, Preset, PresetReading
from app.services.telemetry_service import TelemetryService

#: A long sensor name plus "rejected readings" can pass the column's width, and
#: PostgreSQL refuses where SQLite stores.
_DISPLAY_NAME_MAX = DISPLAY_NAME_MAX_LENGTH


def reading_display_name(label: str, reading: PresetReading) -> str:
    """What the Live tab calls one of a sensor's readings: "Front tank level"."""
    return f"{label} {reading.name}"[:_DISPLAY_NAME_MAX]


async def next_sensor_index(db: AsyncSession, preset: Preset) -> int:
    """One more than the highest sensor index ever used. Never reuses one.

    Held means a parameter row or a device id carries the index. Parameters
    are the durable record: every mapped key has one (the mapping routes
    register it, migration 113 backfilled older maps) and they outlive a
    removed mapping. So a new sensor never lands in the gap an older, deleted
    one left.

    Deleting the NEWEST sensor does free its index, and that is safe:
    `delete_sensor_readings` takes its parameters and every reading with it,
    so there is no history left for the next sensor to merge into (charts are
    queried by VIN and key).
    """
    held: set[int] = set()

    keys = await db.execute(
        select(LiveLinkParameter.param_key).where(
            LiveLinkParameter.param_key.startswith(f"{preset.key_prefix}_T", autoescape=True)
        )
    )
    for (key,) in keys.all():
        index = preset.index_of_key(key)
        if index is not None:
            held.add(index)

    ids = await db.execute(
        select(LiveLinkDevice.device_id).where(
            LiveLinkDevice.device_id.startswith(preset.device_prefix, autoescape=True)
        )
    )
    for (device_id,) in ids.all():
        index = preset.index_of_device(device_id)
        if index is not None:
            held.add(index)

    return max(held, default=0) + 1


async def delete_sensor_readings(db: AsyncSession, device: LiveLinkDevice) -> None:
    """Delete what a preset sensor recorded: its parameters, and every reading
    under them on every vehicle it has reported to.

    A sensor's keys are its own (`reject_foreign_preset_key`), and once its
    device is gone nothing can show them in context. Left behind they were
    loose tiles on the Live tab and a second "Front tank level" in Charts until
    the staleness rule in `get_latest_values` dropped them, and unreachable
    after that.

    Every key of the sensor's index, mapped or not: a reading whose mapping was
    removed earlier is still the sensor's. A key mapped by hand on it (say
    `CABIN_TEMP`) may be shared with another device and stays. A device no
    preset made keeps everything: its keys are not its own.

    Does not commit.
    """
    preset = PRESETS.get(device.preset_key or "")
    index = preset.index_of_device(device.device_id) if preset else None
    if preset is None or index is None:
        return

    # Parameters, because every stored reading's key has one (ingest
    # auto-registers it) and they outlive a removed mapping. The prefix only
    # narrows the fetch: SQLite's LIKE ignores case, so the exact index check
    # (a case-sensitive match that also keeps t1 off t10's keys) decides.
    candidates = await db.execute(
        select(LiveLinkParameter.param_key).where(
            LiveLinkParameter.param_key.startswith(
                f"{preset.key_prefix}_T{index}_", autoescape=True
            )
        )
    )
    # Exact keys, so each delete below is an indexed IN on a table that holds
    # every vehicle's history, not a LIKE scan of it.
    keys = [key for key in candidates.scalars() if preset.index_of_key(key) == index]
    if not keys:
        return

    await db.execute(
        delete(VehicleTelemetryLatest).where(VehicleTelemetryLatest.param_key.in_(keys))
    )
    await db.execute(delete(VehicleTelemetry).where(VehicleTelemetry.param_key.in_(keys)))
    await db.execute(delete(TelemetryDailySummary).where(TelemetryDailySummary.param_key.in_(keys)))
    await db.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(keys)))


def reject_foreign_preset_key(param_key: str | None, device_id: str) -> None:
    """A preset sensor's keys belong to that sensor's device alone.

    Only preset-shaped keys: two handmade gateways on two vehicles may both
    map, say, `CABIN_TEMP`, and the readings endpoint is built for that. A
    preset key carries one sensor's display name ("Front tank level"), so
    another device writing it would put its readings under that name.

    Raises 409.
    """
    if not param_key:
        return
    for preset in PRESETS.values():
        index = preset.index_of_key(param_key)
        if index is not None and device_id != preset.device_id(index):
            raise HTTPException(
                status_code=409,
                detail=f"{param_key} belongs to {preset.title} sensor {preset.device_id(index)}",
            )


async def create_sensor(
    db: AsyncSession,
    preset: Preset,
    label: str,
    vin: str | None,
    topics: dict[str, str],
) -> LiveLinkDevice:
    """Create one sensor device and a topic map per chosen reading.

    Does not commit. `topics` is keyed by reading suffix and the caller has
    already checked it against the preset (required readings present, known
    suffixes, exact and distinct topics).

    Raises 409 when a topic is already mapped by any device.
    """
    taken = (
        await db.execute(
            select(LiveLinkTopicMap.topic, LiveLinkTopicMap.device_id).where(
                LiveLinkTopicMap.topic.in_(list(topics.values()))
            )
        )
    ).first()
    if taken is not None:
        topic, owner = taken
        raise HTTPException(
            status_code=409,
            detail=f"Topic {topic} is already mapped by device {owner}",
        )

    # Device ids count as held, so this id cannot already exist.
    index = await next_sensor_index(db, preset)
    device = LiveLinkDevice(
        device_id=preset.device_id(index),
        kind=preset.kind,
        label=label,
        preset_key=preset.name,
        vin=vin,
        enabled=True,
    )
    db.add(device)

    telemetry = TelemetryService(db)
    # In the preset's order: the readings list shows a device's keys in the
    # order they were mapped, so level comes first.
    for reading in preset.readings:
        topic = topics.get(reading.suffix)
        if not topic:
            continue
        key = preset.key(index, reading.suffix)
        db.add(
            LiveLinkTopicMap(
                device_id=device.device_id,
                topic=topic,
                role="telemetry",
                param_key=key,
                unit=reading.unit,
                param_class=reading.param_class,
            )
        )
        param = await telemetry.get_or_create_parameter(
            key, unit=reading.unit, param_class=reading.param_class
        )
        if param is not None:
            # REQUIRED, not tuning: retained messages replay on every
            # resubscribe and the storage path stamps server time, so without
            # an interval each reconnect writes a fresh row.
            param.storage_interval_seconds = preset.storage_interval_seconds
            param.display_name = reading_display_name(label, reading)
            param.warning_min = reading.low
            param.critical_min = reading.critical
    return device


async def rename_sensor_parameters(
    db: AsyncSession, preset: Preset, device: LiveLinkDevice, old_label: str
) -> None:
    """Carry a sensor's rename into its readings' display names.

    Only names that still read "{old label} {reading}": one someone changed by
    hand is theirs. Does not commit.
    """
    if not device.label:
        return
    by_suffix = {reading.suffix: reading for reading in preset.readings}
    rows = await db.execute(
        select(LiveLinkParameter, LiveLinkTopicMap.param_key)
        .join(LiveLinkTopicMap, LiveLinkTopicMap.param_key == LiveLinkParameter.param_key)
        .where(
            LiveLinkTopicMap.device_id == device.device_id,
            LiveLinkTopicMap.role == "telemetry",
        )
    )
    for param, key in rows.all():
        parts = preset.split_key(key or "")
        reading = by_suffix.get(parts[1]) if parts else None
        if reading and param.display_name == reading_display_name(old_label, reading):
            param.display_name = reading_display_name(device.label, reading)


def reading_of(param_key: str, preset: Preset | None) -> PresetReading | None:
    """The preset reading one of a sensor's mapped keys is. None for a key
    mapped by hand, or a device no preset made: those show as a plain value."""
    return preset.reading_of_key(param_key) if preset else None


async def live_sensors(
    db: AsyncSession,
    devices: list[LiveLinkDevice],
    offline_timeout_minutes: int,
    now: datetime,
) -> list[LiveSensor]:
    """The Live tab's cards: one per preset sensor among `devices`.

    In the order the sensors were added (`mopeka-t1` before `t2`, `t10`
    after), and each sensor's readings in its preset's order, level first.
    Which keys are a sensor's comes from its own topic maps, so a key mapped by
    hand on the sensor is on its card too, after the preset's readings.
    """
    sensors = [d for d in devices if d.preset_key in PRESETS]
    if not sensors:
        return []

    rows = await db.execute(
        select(LiveLinkTopicMap.device_id, LiveLinkTopicMap.param_key)
        .where(
            LiveLinkTopicMap.device_id.in_([d.device_id for d in sensors]),
            LiveLinkTopicMap.role == "telemetry",
            LiveLinkTopicMap.param_key.is_not(None),
        )
        .order_by(LiveLinkTopicMap.id)
    )
    keys_by_device: dict[str, list[str]] = {}
    for device_id, key in rows.all():
        keys = keys_by_device.setdefault(device_id, [])
        if key not in keys:
            keys.append(key)

    def added(device: LiveLinkDevice) -> tuple[str, bool, int, str]:
        index = PRESETS[device.preset_key or ""].index_of_device(device.device_id)
        return (device.preset_key or "", index is None, index or 0, device.device_id)

    cards: list[LiveSensor] = []
    for device in sorted(sensors, key=added):
        preset = PRESETS[device.preset_key or ""]
        rank = {reading.suffix: n for n, reading in enumerate(preset.readings)}

        def suffix(key: str, preset: Preset = preset) -> str | None:
            parts = preset.split_key(key)
            return parts[1] if parts else None

        # Stable: keys the preset does not know keep their mapping order.
        keys = sorted(
            keys_by_device.get(device.device_id, []),
            key=lambda key, rank=rank: rank.get(suffix(key) or "", len(rank)),
        )
        cards.append(
            LiveSensor(
                device_id=device.device_id,
                label=device.label or device.device_id,
                preset_key=preset.name,
                online=device_is_online(device, offline_timeout_minutes, now),
                last_seen=device.last_seen,
                fill_key=next((k for k in keys if suffix(k) == preset.fill_suffix), None),
                readings=[_live_reading(key, reading_of(key, preset)) for key in keys],
            )
        )
    return cards


def _live_reading(param_key: str, reading: PresetReading | None) -> LiveSensorReading:
    if reading is None:
        return LiveSensorReading(param_key=param_key)
    return LiveSensorReading(
        param_key=param_key, format=reading.format, max_value=reading.max_value
    )
