"""Pydantic schemas for LiveLink device and settings operations."""

from datetime import datetime

from pydantic import BaseModel, Field

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


class LiveLinkDeviceUpdate(BaseModel):
    """Schema for updating a device."""

    label: str | None = Field(None, description="User-friendly device name")
    vin: str | None = Field(None, description="VIN to link device to", min_length=17, max_length=17)
    enabled: bool | None = Field(None, description="Enable/disable device")


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
    ecu_status: str = Field("unknown", description="ECU status: online/offline/unknown")
    device_status: str = Field("unknown", description="Device status: online/offline/unknown")
    has_device_token: bool = Field(False, description="Whether device has per-device token")
    enabled: bool
    last_seen: datetime | None
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
    warning_min: float | None = Field(None, description="Alert if value drops below")
    warning_max: float | None = Field(None, description="Alert if value exceeds")
    display_order: int | None = Field(None, description="Gauge display order", ge=0)
    show_on_dashboard: bool | None = Field(None, description="Show in live gauges")
    archive_only: bool | None = Field(None, description="Hide from default views")
    storage_interval_seconds: int | None = Field(
        None, description="Minimum seconds between stored values", ge=0
    )


class LiveLinkParameterResponse(LiveLinkParameterBase):
    """Schema for parameter response."""

    id: int
    category: str | None
    icon: str | None
    warning_min: float | None
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

    # Notification toggles
    notify_device_offline: bool = Field(True, description="Notify when device goes offline")
    notify_threshold_alerts: bool = Field(True, description="Notify on threshold breaches")
    notify_firmware_update: bool = Field(True, description="Notify on firmware updates")
    notify_new_device: bool = Field(True, description="Notify on new device discovery")


class LiveLinkSettingsUpdate(BaseModel):
    """Schema for updating LiveLink settings."""

    enabled: bool | None = None
    telemetry_retention_days: int | None = Field(None, ge=30, le=365)
    session_timeout_minutes: int | None = Field(None, ge=1, le=60)
    device_offline_timeout_minutes: int | None = Field(None, ge=5, le=60)
    daily_aggregation_enabled: bool | None = None
    firmware_check_enabled: bool | None = None
    alert_cooldown_minutes: int | None = Field(None, ge=5, le=120)
    notify_device_offline: bool | None = None
    notify_threshold_alerts: bool | None = None
    notify_firmware_update: bool | None = None
    notify_new_device: bool | None = None


# =============================================================================
# Firmware Schemas
# =============================================================================


class FirmwareInfoResponse(BaseModel):
    """Schema for firmware information response."""

    latest_version: str | None = Field(None, description="Latest available version")
    latest_tag: str | None = Field(None, description="Git tag (e.g., v4.50p)")
    release_url: str | None = Field(None, description="GitHub release URL")
    release_notes: str | None = Field(None, description="Release notes summary")
    checked_at: datetime | None = Field(None, description="When firmware was last checked")


class DeviceFirmwareStatus(BaseModel):
    """Schema for per-device firmware status."""

    device_id: str
    current_version: str | None
    latest_version: str | None
    update_available: bool = False
    release_url: str | None = None


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
