"""One Mopeka Pro Check propane sensor.

Mopeka sensors speak only Bluetooth. Something nearby (an ESP32 running
ESPHome, a Home Assistant bridge, another gateway) hears them and republishes
each reading to MQTT, and that relay is transport, like the broker: each sensor
is its own device. Where a gateway publishes is its owner's choice, so a sensor
is added from its level topic and the other readings' topics are suggested from
it, not assumed.

Semantics worth knowing when reading these values (verified against the
operator's ESPHome gateway, the reference layout the default topic names come
from):

- The gateway's `minimum_signal_quality` gates ONLY the level and depth.
  Temperature and battery publish on every packet, so "sensor heard" means the
  radio was heard, not that the measurement is valid.
- Rejected readings > 0 is the real "the retained level is stale" flag.
- "Sensor heard" is not cleared when the gateway itself dies.
- A 30 lb bottle calibrated empty at 38 mm and full at 381 mm reads 395-400 mm
  when full, so the level is SATURATED at 100% and the first few percent of
  consumption are invisible. Burn-rate maths must allow for a flat top.
"""

from __future__ import annotations

from app.services.livelink_sources.presets.model import PresetReading

#: Seconds between persisted samples. REQUIRED, not tuning: the gateway
#: republishes every reading every few seconds and the storage path stamps
#: server time, so without this a tank writes a row per message.
STORAGE_INTERVAL_SECONDS = 300

#: In the order a sensor's readings are shown. Keywords are lowercase
#: substrings that identify a reading's topic segment in any layout.
READINGS: tuple[PresetReading, ...] = (
    PresetReading(
        "LEVEL_PCT",
        "level",
        "%",
        "propane",
        "level_percent",
        ("level",),
        True,
        low=25.0,
        critical=10.0,
    ),
    PresetReading("TEMP_C", "temperature", "C", "temperature", "temperature_c", ("temp",)),
    PresetReading(
        "SENSOR_BATT_PCT", "battery", "%", "battery", "battery_percent", ("batt",), low=20.0
    ),
    # ESPHome publishes the sensor's own quality grade: 0 none, 1 low, 2 medium,
    # 3 high. The gateway's `minimum_signal_quality` gates level and depth on it.
    PresetReading(
        "QUALITY",
        "reading quality",
        None,
        "diagnostic",
        "reading_quality",
        ("quality", "signal"),
        format="of_max",
        max_value=3,
    ),
    PresetReading("DEPTH_MM", "depth", "mm", "propane", "depth_mm", ("depth", "distance")),
    PresetReading(
        "REJECTED",
        "rejected readings",
        None,
        "diagnostic",
        "rejected_readings",
        ("reject", "ignored"),
        format="count",
    ),
    PresetReading(
        "AVAILABLE",
        "sensor heard",
        None,
        "diagnostic",
        "availability",
        ("avail", "heard"),
        format="boolean",
    ),
)
