"""Pydantic schemas for LiveLink device and settings operations."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator

from app.schemas._nullability import reject_null
from app.utils.lenient_vocab import LenientVocab, lenient_reader

#: The raw telemetry retention range, in days. The LiveLink settings route and
#: the settings restore hold `livelink_telemetry_retention_days` to it; the daily
#: prune refuses only a value below the minimum (a longer one only keeps more).
TELEMETRY_RETENTION_MIN_DAYS = 30
TELEMETRY_RETENTION_MAX_DAYS = 365

# Shared status literals for OpenAPI schema generation
DeviceStatusType = Literal["online", "offline", "unknown"]
ECUStatusType = Literal["online", "offline", "unknown"]

# For responses: a stored status we don't know is just "unknown", which the
# vocabulary already has, so these stay non-null.
LenientDeviceStatus = Annotated[
    DeviceStatusType,
    BeforeValidator(lenient_reader(DeviceStatusType, fallback="unknown")),
    LenientVocab("unknown"),
]
LenientECUStatus = Annotated[
    ECUStatusType,
    BeforeValidator(lenient_reader(ECUStatusType, fallback="unknown")),
    LenientVocab("unknown"),
]

# =============================================================================
# Device Schemas
# =============================================================================


class LiveLinkDeviceBase(BaseModel):
    """Base device schema."""

    device_id: str = Field(..., description="WiCAN device ID (12-char hex)")
    label: str | None = Field(None, description="User-friendly device name")


class LiveLinkDeviceCreate(LiveLinkDeviceBase):
    """Schema for auto-discovering a new device."""

    hw_version: str | None = Field(None, description="Hardware version (e.g., WiCAN-OBD-PRO)")
    fw_version: str | None = Field(None, description="Firmware version (e.g., 4.45)")
    git_version: str | None = Field(None, description="Git version tag (e.g., v4.45p)")


#: A device id an operator types must be safe as a single URL path segment.
#: Every per-device admin route embeds it (`/devices/{device_id}/readings`), so
#: `rv/gw` routes elsewhere, `gw#1` is cut at the fragment and `""` produces
#: `/devices//readings`. Leading letter or digit also rules out `.` and `..`.
#: Auto-discovered WiCAN ids (hex) and generated Torque ids already fit.
DEVICE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


class LiveLinkDeviceManualCreate(BaseModel):
    """Schema for creating a device by hand, rather than by auto-discovery.

    `LiveLinkDeviceCreate` above is the auto-discovery shape: it carries no
    `kind` and no `vin` because a WiCAN dongle announces itself and is linked
    afterwards. A `generic_mqtt` device declares neither AUTO_DISCOVER nor a
    token flow, so without this route the only way such a device can exist is
    by applying a preset.

    `vin` is optional, matching every other device: the pipeline returns early
    for a device with no VIN, so an unlinked device is a valid intermediate
    state rather than an error.
    """

    device_id: str = Field(..., max_length=20, pattern=DEVICE_ID_PATTERN)
    kind: str = Field(..., max_length=20)
    label: str | None = Field(None, max_length=100)
    vin: str | None = Field(None, min_length=17, max_length=17)

    @field_validator("kind")
    @classmethod
    def kind_must_be_registered(cls, v: str) -> str:
        """The registry owns the set of valid kinds, not a database CHECK."""
        from app.services.livelink_sources.registry import default_registry

        valid = default_registry().valid_kinds()
        if v not in valid:
            raise ValueError(f"Unknown source kind {v!r}. Valid kinds: {sorted(valid)}")
        return v


class LiveLinkDeviceUpdate(BaseModel):
    """Schema for updating a device."""

    label: str | None = Field(
        None,
        max_length=100,
        description=(
            "User-friendly device name, stored stripped. Null or blank clears it; "
            "longer than the column's 100 characters is a 422."
        ),
    )
    vin: str | None = Field(
        None,
        max_length=17,
        description=(
            "VIN to link the device to, any case. An empty string UNLINKS it; "
            "omitted or null leaves the link unchanged. Same convention as "
            "odometer_param_key below."
        ),
    )
    enabled: bool | None = Field(None, description="Enable/disable device")
    odometer_unit: Literal["km", "mi", "auto"] | None = Field(
        None,
        description=(
            "Units this device reports its odometer in. 'auto' clears the "
            "override and infers from the param key shape. None leaves it unchanged."
        ),
    )
    odometer_param_key: str | None = Field(
        None,
        max_length=100,
        description=(
            "Which reported parameter carries this device's odometer. Omitted "
            "leaves it unchanged, an empty string clears it, a key sets it "
            "(uppercased). The empty string must NOT be coerced to None here, "
            "or the service cannot tell 'clear it' from 'not supplied'."
        ),
    )

    # NOT NULL column: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("enabled")

    @field_validator("vin", mode="before")
    @classmethod
    def _vin_is_empty_or_whole(cls, value: object) -> object:
        """Normalise before the length check, so the ownership check and the
        store see one string. The route checked an uppercased VIN and then
        stored the one it was sent, so a lowercase VIN failed the foreign key
        to vehicles.vin at commit: a 500.
        """
        if not isinstance(value, str):
            return value
        normalised = value.strip().upper()
        if normalised and len(normalised) != 17:
            raise ValueError("vin must be 17 characters, or empty to unlink")
        return normalised

    @field_validator("label", mode="before")
    @classmethod
    def _label_is_stripped(cls, value: object) -> object:
        """Strip before max_length counts it. The name is stored stripped, so
        padding shouldn't push a 100-character name over the column."""
        return value.strip() if isinstance(value, str) else value


class LiveLinkDeviceResponse(LiveLinkDeviceBase):
    """Schema for device response."""

    id: int
    vin: str | None = Field(None, description="Linked vehicle VIN")
    hw_version: str | None
    fw_version: str | None
    git_version: str | None
    sta_ip: str | None = Field(None, description="Device IP on local network")
    rssi: int | None = Field(None, description="WiFi signal strength (dBm)")
    battery_voltage: float | None = Field(None, description="Vehicle battery voltage (V)")
    ecu_status: LenientECUStatus = Field(
        "unknown", description="ECU status: online/offline/unknown"
    )
    device_status: LenientDeviceStatus = Field(
        "unknown", description="Device status: online/offline/unknown"
    )
    has_device_token: bool = Field(False, description="Whether device has per-device token")
    device_address: str | None = Field(None, description="Admin-set IP/host for SD-card log pulls")
    sd_backfill_enabled: bool = Field(False, description="Whether SD-card backfill is enabled")
    odometer_unit: str | None = Field(
        None, description="Declared odometer units ('km'/'mi'); None means inferred from the key"
    )
    kind: str = Field("wican", description="Source module that owns this device (see GET /sources)")
    odometer_param_key: str | None = Field(
        None, description="Which reported parameter carries this device's odometer"
    )
    preset_key: str | None = Field(
        None,
        description=(
            "The preset that created this device, if any. A preset device's tab "
            "is named by its preset, and its mappings are the preset's, not hand-made."
        ),
    )
    enabled: bool
    last_seen: datetime | None
    #: When this device last proved the vehicle moved. NULL on a device whose
    #: speed and odometer arrive under names nothing here recognises, which
    #: records no drives at all -- so the admin page can say which device that
    #: is instead of showing an empty session list with no explanation. A silent
    #: zero is the failure the whole boundary rework exists to remove.
    last_movement_at: datetime | None = Field(
        None, description="When this device last reported a recognised movement signal"
    )
    #: Computed per response, not stored; see
    #: `LiveLinkService.movement_unreadable_device_ids` for the rule and why it
    #: is not simply `last_movement_at is None`. Every handler returning this
    #: schema must answer it: the False default would otherwise report "reads
    #: fine" about a device nobody asked about.
    movement_unreadable: bool = Field(
        False, description="Device reports telemetry but nothing recognisable as movement"
    )
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class LiveLinkDeviceListResponse(BaseModel):
    """Schema for device list response."""

    devices: list[LiveLinkDeviceResponse]
    total: int
    online_count: int = Field(0, description="Number of devices currently online")


# =============================================================================
# Token Schemas
# =============================================================================


class TokenGenerateResponse(BaseModel):
    """Schema for token generation response.

    Token is shown ONCE on generation, then stored hashed.
    """

    token: str = Field(..., description="Generated API token (shown only once)")
    expires_at: datetime | None = Field(None, description="Token expiration (None = never)")


class TokenInfoResponse(BaseModel):
    """Schema for token info (masked)."""

    masked_token: str = Field(..., description="Masked token for display (e.g., 'abc***xyz')")
    created_at: datetime
    last_used: datetime | None


# =============================================================================
# Parameter Schemas
# =============================================================================


class LiveLinkParameterBase(BaseModel):
    """Base parameter schema."""

    param_key: str = Field(..., description="Parameter key (e.g., ENGINE_RPM)")
    display_name: str | None = Field(None, description="User-friendly display name")
    unit: str | None = Field(None, description="Unit of measurement")
    param_class: str | None = Field(None, description="Parameter class (temperature, speed, etc.)")


class LiveLinkParameterCreate(LiveLinkParameterBase):
    """Schema for auto-registering a new parameter from WiCAN config block."""

    category: str | None = Field(None, description="Category for grouping")


class LiveLinkParameterUpdate(BaseModel):
    """Schema for updating parameter settings."""

    display_name: str | None = Field(None, description="User-friendly display name")
    category: str | None = Field(None, description="Category for grouping")
    icon: str | None = Field(None, description="Icon identifier for frontend")
    # The three alert lines: an explicit null switches a line off, an omitted
    # field leaves it as it is. Not NaN or infinity: NaN is a line no value
    # ever crosses. Lines are compared in the stored unit, so they're in it too.
    warning_min: float | None = Field(
        None,
        description=(
            "Alert if value drops below, in the reading's canonical metric unit "
            "(°C, km/h, kPa, km); a raw-unit reading in its own unit"
        ),
        allow_inf_nan=False,
    )
    critical_min: float | None = Field(
        None,
        description=(
            "Urgent alert if value drops below; must sit under warning_min. In the "
            "reading's canonical metric unit (°C, km/h, kPa, km); a raw-unit "
            "reading in its own unit"
        ),
        allow_inf_nan=False,
    )
    warning_max: float | None = Field(
        None,
        description=(
            "Alert if value exceeds, in the reading's canonical metric unit "
            "(°C, km/h, kPa, km); a raw-unit reading in its own unit"
        ),
        allow_inf_nan=False,
    )
    display_order: int | None = Field(None, description="Gauge display order", ge=0)
    show_on_dashboard: bool | None = Field(None, description="Show in live gauges")
    archive_only: bool | None = Field(None, description="Hide from default views")
    storage_interval_seconds: int | None = Field(
        None, description="Minimum seconds between stored values", ge=0
    )

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null(
        "display_order", "show_on_dashboard", "archive_only", "storage_interval_seconds"
    )


class LiveLinkParameterResponse(LiveLinkParameterBase):
    """Schema for parameter response."""

    id: int
    category: str | None
    icon: str | None
    warning_min: float | None
    critical_min: float | None
    warning_max: float | None
    display_order: int
    show_on_dashboard: bool
    archive_only: bool
    storage_interval_seconds: int
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class LiveLinkParameterListResponse(BaseModel):
    """Schema for parameter list response."""

    parameters: list[LiveLinkParameterResponse]
    total: int


# =============================================================================
# Settings Schemas
# =============================================================================


class LiveLinkSettingsResponse(BaseModel):
    """Schema for LiveLink settings response."""

    enabled: bool = Field(False, description="LiveLink master enable/disable")
    has_global_token: bool = Field(False, description="Whether global token is configured")
    ingestion_url: str = Field(..., description="URL for WiCAN HTTPS POST")
    telemetry_retention_days: int = Field(90, description="Days to retain raw telemetry")
    session_timeout_minutes: int = Field(5, description="Minutes before session timeout")
    device_offline_timeout_minutes: int = Field(15, description="Minutes before device offline")
    daily_aggregation_enabled: bool = Field(True, description="Enable daily rollup")
    firmware_check_enabled: bool = Field(True, description="Auto-check for firmware updates")
    alert_cooldown_minutes: int = Field(30, description="Cooldown between alerts")

    # Session grace period
    session_grace_period_seconds: int = Field(
        60, description="Seconds to wait before ending session after ECU offline (0 = disabled)"
    )

    # Session boundaries. `session_timeout_minutes` above is a CONNECTION-LOSS
    # detector; this is the separate question of whether a stop ended the drive.
    session_gap_minutes: int = Field(
        15, description="Minutes stationary before a stop counts as a separate drive"
    )
    session_boundary_mode: str = Field(
        "movement",
        description=(
            "'movement' decides sessions from speed/odometer/RPM; 'contact' restores "
            "the pre-v3.3.0 rule of opening one whenever the device is reachable"
        ),
    )

    # Notification toggles
    notify_device_offline: bool = Field(True, description="Notify when device goes offline")
    notify_threshold_alerts: bool = Field(True, description="Notify on threshold breaches")
    notify_firmware_update: bool = Field(True, description="Notify on firmware updates")
    notify_new_device: bool = Field(True, description="Notify on new device discovery")


class LiveLinkSettingsUpdate(BaseModel):
    """Schema for updating LiveLink settings."""

    enabled: bool | None = None
    telemetry_retention_days: int | None = Field(
        None, ge=TELEMETRY_RETENTION_MIN_DAYS, le=TELEMETRY_RETENTION_MAX_DAYS
    )
    session_timeout_minutes: int | None = Field(None, ge=1, le=60)
    device_offline_timeout_minutes: int | None = Field(None, ge=5, le=60)
    daily_aggregation_enabled: bool | None = None
    firmware_check_enabled: bool | None = None
    alert_cooldown_minutes: int | None = Field(None, ge=5, le=120)
    session_grace_period_seconds: int | None = Field(None, ge=0, le=300)
    # Lower bound of 1, not 0: a zero gap closes a session on the first
    # stationary sample, so every traffic light becomes a separate trip.
    session_gap_minutes: int | None = Field(None, ge=1, le=240)
    session_boundary_mode: Literal["movement", "contact"] | None = None
    notify_device_offline: bool | None = None
    notify_threshold_alerts: bool | None = None
    notify_firmware_update: bool | None = None
    notify_new_device: bool | None = None


class FirmwareInfoResponse(BaseModel):
    """Schema for firmware information response."""

    latest_version: str | None = Field(None, description="Latest available version")
    latest_tag: str | None = Field(None, description="Git tag (e.g., v4.50p)")
    release_url: str | None = Field(None, description="GitHub release URL")
    release_notes: str | None = Field(None, description="Release notes summary")
    checked_at: datetime | None = Field(None, description="When firmware was last checked")
    firmware_track: str | None = Field(None, description="Firmware track: 'obd' or 'pro'")


class DeviceFirmwareStatus(BaseModel):
    """Schema for per-device firmware status."""

    device_id: str
    current_version: str | None
    latest_version: str | None
    update_available: bool | None = False
    release_url: str | None = None
    firmware_track: str | None = None
    #: The version the admin chose to skip (silences its notification and
    #: badge until a newer release). Surfaced so the UI can show "Skipped
    #: vX" instead of the update badge.
    skipped_version: str | None = None


class IntegrationTab(BaseModel):
    """One entry in the integrations card's tab strip."""

    id: str = Field(
        description=(
            "'wican' | 'torque' | 'broker' | 'preset:<preset name>' (every "
            "sensor made from that preset) | 'device:<device_id>' (any other "
            "generic MQTT device)"
        )
    )
    label: str = Field(description="Proper noun. Never translated.")
    kind: str | None = Field(None, description="Source-module kind; None for the broker")
    status: str = Field(description="'ok' | 'attention' | 'off'")
    reason: str = Field(
        description=(
            "Why it has that status. Status and counts alone cannot tell an "
            "unlinked device from one that has never reported: both are "
            "'attention' with zero online."
        )
    )
    description: str | None = Field(None, description="Literal text, sent only for preset tabs")
    device_count: int = 0
    online_count: int = 0
    linked_count: int = 0
    firmware_updates: int = 0


class IntegrationListResponse(BaseModel):
    """The whole tab strip, in display order."""

    tabs: list[IntegrationTab]


class DeviceReading(BaseModel):
    """One mapped parameter and its most recent device-attributed value."""

    param_key: str
    display_name: str | None = None
    unit: str | None = None
    value: float | None = Field(None, description="None when never reported")
    timestamp: datetime | None = Field(
        None,
        description=(
            "When that value was stored. Subject to storage_interval_seconds, "
            "so it is not the wall-clock moment the sensor published."
        ),
    )
    show_on_dashboard: bool = True
    format: Literal["value", "boolean", "count", "of_max"] = Field(
        "value",
        description=(
            "How to show the value: through the unit adapter, as Yes/No, as a "
            "whole number, or as 'n of max_value'. A preset sensor's readings "
            "say; anything else is a plain value."
        ),
    )
    max_value: int | None = Field(None, description="The top of the scale for an 'of_max' reading")
    warning_min: float | None = Field(None, description="The low alert line, if set")
    critical_min: float | None = Field(None, description="The critical alert line, if set")
    alert_lines: list[Literal["low", "critical"]] = Field(
        default_factory=list,
        description=(
            "The alert lines Settings offers for this reading: a preset sensor's "
            "tank level offers low and critical, its battery low. Empty for "
            "anything else."
        ),
    )


class DeviceReadingsResponse(BaseModel):
    """Every parameter one device is mapped to, with current values."""

    device_id: str
    vin: str | None = Field(None, description="None when the device is unlinked")
    online: bool = Field(
        False,
        description=(
            "Whether the device is reporting now: the integrations card's own "
            "rule, so a device with no status topic counts as online while it "
            "has reported within the offline timeout."
        ),
    )
    readings: list[DeviceReading]


class FirmwareSkipRequest(BaseModel):
    """Body of POST /devices/{device_id}/firmware/skip.

    The client names the version it saw, so a release landing between
    render and click is never silently skipped.
    """

    version: str = Field(..., min_length=1, max_length=20)


# =============================================================================
# MQTT Settings Schemas
# =============================================================================


class MQTTSettingsResponse(BaseModel):
    """Schema for MQTT settings response."""

    enabled: bool = Field(False, description="MQTT subscription enabled")
    broker_host: str = Field("", description="MQTT broker hostname/IP")
    broker_port: int = Field(1883, description="MQTT broker port")
    username: str = Field("", description="MQTT username (empty = anonymous)")
    has_password: bool = Field(False, description="Whether password is configured")
    password_unreadable: bool = Field(
        False,
        description=(
            "True when a password is stored but can't be decrypted with the current "
            "settings key; re-enter it. has_password stays true."
        ),
    )
    topic_prefix: str = Field("wican", description="Topic prefix for subscriptions")
    use_tls: bool = Field(False, description="Use TLS/SSL connection")


class MQTTSettingsUpdate(BaseModel):
    """Schema for updating MQTT settings."""

    enabled: bool | None = Field(None, description="Enable MQTT subscription")
    broker_host: str | None = Field(None, description="MQTT broker hostname/IP")
    broker_port: int | None = Field(None, ge=1, le=65535, description="MQTT broker port")
    username: str | None = Field(None, description="MQTT username (empty = anonymous)")
    password: str | None = Field(None, description="MQTT password")
    topic_prefix: str | None = Field(None, description="Topic prefix (default: wican)")
    use_tls: bool | None = Field(None, description="Use TLS/SSL connection")


class MQTTStatusResponse(BaseModel):
    """Schema for MQTT subscriber status response."""

    running: bool = Field(False, description="Whether subscriber task is running")
    connection_status: str = Field(
        "disconnected",
        description="Connection state: disconnected/connecting/connected/error/disabled",
    )
    last_message_at: str | None = Field(None, description="ISO timestamp of last message")
    messages_processed: int = Field(0, description="Total messages processed since start")


class MQTTTestResult(BaseModel):
    """Schema for MQTT connection test result."""

    success: bool = Field(..., description="Whether connection test succeeded")
    message: str = Field(..., description="Result message")
    broker: str | None = Field(None, description="Broker address tested")


# =============================================================================
# Device Command Schemas
# =============================================================================


class DeviceCommandRequest(BaseModel):
    """Schema for sending a command to a WiCAN device via MQTT."""

    command: str = Field(
        ...,
        description="Command to send (get_vbatt, get_autopid_data, reboot)",
    )


class DeviceCommandResponse(BaseModel):
    """Schema for device command response."""

    status: str = Field(..., description="Command status (sent, error)")
    message: str = Field(..., description="Result message")


# =============================================================================
# SD-Card Backfill Schemas
# =============================================================================


class SdConfigUpdate(BaseModel):
    """Schema for updating SD-card pull config on a device."""

    device_address: str | None = Field(
        None, description="Private/LAN IP or hostname for SD log pulls"
    )
    sd_backfill_enabled: bool = Field(False, description="Enable automatic SD-card backfill")


class SdConfigResponse(BaseModel):
    """Schema for SD-card config update response."""

    status: str = "ok"


class BackfillResultResponse(BaseModel):
    """Schema for SD-card backfill trigger response."""

    files_seen: int = Field(..., description="Number of SD log files found")
    rows_ingested: int = Field(..., description="Telemetry rows inserted")
    rows_skipped: int = Field(..., description="Rows skipped (already present)")
    errors: list[str] = Field(default_factory=list, description="Per-file error messages")
