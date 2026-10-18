# LiveLink (WiCAN) Setup

MyGarage ingests real-time vehicle telemetry from [WiCAN](https://github.com/meatpiHQ/wican-fw)
devices. Webhook (HTTPS) ingestion needs a WiCAN PRO on firmware **v4.40 or
newer**; the standard WiCAN has no HTTPS POST and sends over MQTT instead.

## Webhook (HTTPS) ingestion

Point your WiCAN device's webhook at MyGarage's ingest endpoint:

- **Webhook URL:** `https://<your-mygarage-host>/api/v1/livelink/ingest`
- **Method:** `POST`
- **Auth:** include the per-device token issued in MyGarage
  (Settings → Integrations → LiveLink → Configure → device token).

The endpoint returns `202 Accepted` immediately and queues the payload for
async processing.

## Primary + failover webhook (firmware v4.49 / v4.50p)

Recent PRO firmware supports a **primary** and a **failover** webhook URL.
Both may target MyGarage for delivery resilience — if the primary path fails,
the device retries the failover. Configure either or both fields in the
device's web UI to the ingest URL above; MyGarage deduplicates replays, so a
payload delivered via both paths is stored once.

## MQTT ingestion (alternative)

If you run an MQTT broker, MyGarage can subscribe instead of receiving
webhooks. See Settings → Integrations → LiveLink → Mosquitto.

**Enable LiveLink** (the card's gear) gates every source: with it off, nothing
from WiCAN, Torque, MQTT or an SD-card backfill is stored, and no new WiCAN
dongle is discovered.

## Generic MQTT sources

WiCAN and Torque parse their own wire formats in code. Any other MQTT device is
described by rows in `livelink_topic_maps` instead, so adding one is a Settings
task rather than a pull request.

Settings → Integrations → LiveLink → **Add source** → Blank device. Its topics
are then mapped from its tab's settings.

### 1. Create the device

A generic MQTT device cannot appear on its own: it has no auto-discovery (unlike
WiCAN, which announces itself) and no token flow (unlike Torque). Create it with
a device ID, an optional label and an optional vehicle. Leaving the vehicle
unset is fine; the device stores nothing until it is linked, exactly like a
freshly discovered WiCAN dongle.

### 2. Find out what it publishes

**Discover** subscribes to a prefix for a few seconds and lists the topics it
saw with one sample payload each. It is bounded server-side: 60 seconds maximum,
500 distinct topics, 256-byte samples, one run at a time, admin only. It uses
its own short-lived connection, so the live subscription set is untouched.

### 3. Map a topic to a parameter

| Field | Meaning |
|---|---|
| Topic | **Exact**, never a wildcard. `+` and `#` are rejected. |
| Parameter key | Where the value is stored. Prefilled from the topic's last segment, uppercased. |
| Unit / class | Display metadata, copied onto the parameter. |
| Value path | Leave empty for a bare scalar payload (`71`). Set a dotted path (`battery.voltage`) to read one value out of a JSON payload. |
| Scale / offset | `value = raw * scale + offset`. This is where unit conversion happens. |
| Role | `telemetry` stores a reading. `status` marks the device online/offline, for an LWT topic. |

Topics are exact by design. Subscriptions then are just the distinct topic
values, dispatch is a dictionary lookup, and there is no way to configure a `#`
that firehoses the broker into the database.

**One topic belongs to one device.** Mapping the same topic under a second
device is rejected with a conflict, because a batch is attributed to a single
device and the alternative is writing one device's readings against another
device's vehicle.

### Payloads that are not numbers

`ON`, `TRUE`, `ONLINE`, `OPEN`, `YES` and `1` become 1.0; `OFF`, `FALSE`,
`OFFLINE`, `CLOSED`, `NO` and `0` become 0.0. Anything else is dropped.

A payload that is neither numeric nor boolean **cannot be mapped at all**:
`vehicle_telemetry.value` is a float. An IP address published on a diagnostics
topic is a common example, and the discovery list flags samples like that.

### Set a storage interval

This is required, not tuning. Mapped topics are usually retained, and retained
messages replay on every resubscribe while the storage path stamps server time,
so without an interval each reconnect writes a fresh row. Setting
`storage_interval_seconds` on the parameter also decides how much history you
keep: at 300 seconds, a device publishing every 10 seconds stores about 288 rows
per parameter per day instead of 8,640.

### Presets

A preset adds one sensor at a time. Each sensor is its own device, and a
preset's sensors share one tab, the way WiCAN's dongles do.

Add a sensor from **Add source**, or from the preset's tab once it has one: a
name, a vehicle, and the exact topic its level arrives on. MyGarage then
listens to the broker for a few seconds and suggests the other readings'
topics:

- The segment of the level topic that names the level is the one that varies,
  and every other segment must match. `rv/propane/tank1/level_percent` looks in
  `rv/propane/tank1/`; `garage/mopeka_front/sensor/propane_level/state` looks at
  `garage/mopeka_front/sensor/<anything>/state`.
- Topics it hears there are matched to readings by keyword (`temp`, `batt`,
  `depth` and so on). A reading nothing matches is left empty and not mapped.
- If nothing in that shape is heard at all (broker unreachable, nothing
  retained), each reading gets a guess from the reference names below.

Every suggestion is editable, and only the level is required. Each sensor gets
its own parameter keys (`PROPANE_T3_LEVEL_PCT`, never reused after a sensor is
deleted), its readings are named after it ("Front tank level") and follow a
rename, and the storage interval is set on every reading.

The reference names come from one ESPHome gateway. They are an example, not a
requirement:

```
mygarage/rv/propane/tank1/level_percent
mygarage/rv/propane/tank1/temperature_c
mygarage/rv/propane/tank1/battery_percent
mygarage/rv/propane/tank1/reading_quality
mygarage/rv/propane/tank1/depth_mm
mygarage/rv/propane/tank1/rejected_readings
mygarage/rv/propane/tank1/availability
```

Each tank has its own alert lines, under **Alerts** in its block: the level
warns below **Low** (25% on a new sensor) and again below **Critical** (10%),
and the sensor battery warns below **Low** (20%). A blank line is off. The
lines colour the tank on the Live tab, and each sends one notification when
the reading drops below it, through LiveLink's threshold alert (switched off
by **Parameter threshold breaches** in LiveLink's settings). It fires again
only after the reading climbs 5 points back above the line, so a refill
re-arms it and a level wobbling at 25% does not. If no notification service
takes it, it tries again after the alert cooldown. WiCAN readings keep
repeating their alerts every alert cooldown.

Reading Mopeka values:

- Signal quality gates only the level and depth. Temperature and battery
  publish regardless, so "sensor heard" means the radio was heard, not that the
  measurement is valid.
- Rejected readings above 0 is the real "this retained level is stale" flag.
- "Sensor heard" is not cleared when the gateway itself dies.
- A bottle can read deeper than its calibrated full depth (a 30 lb bottle
  calibrated full at 381 mm reads 395 to 400 mm), so the level is **saturated
  at 100%** and the first few percent of consumption are invisible.

### What a generic source deliberately cannot do

It declares telemetry only. It cannot open a drive session, and that is
structural rather than a guard: the ingest pipeline has no code path reaching
session handling for a module that does not declare the capability. A propane
sensor on a parked trailer reporting every few seconds will never manufacture a
drive.
