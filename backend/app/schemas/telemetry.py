"""Pydantic schemas for vehicle telemetry operations."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.livelink import DeviceStatusType, LenientECUStatus

# =============================================================================
# Latest Value Schemas (for live dashboard)
# =============================================================================


class TelemetryLatestValue(BaseModel):
    """Schema for a single latest telemetry value."""

    param_key: str = Field(..., description="Parameter key")
    value: float = Field(..., description="Current value")
    unit: str | None = Field(None, description="Unit of measurement")
    display_name: str | None = Field(None, description="User-friendly name")
    timestamp: datetime = Field(..., description="When value was recorded")

    # Display metadata
    warning_min: float | None = Field(None, description="Low warning threshold")
    warning_max: float | None = Field(None, description="High warning threshold")
    in_warning: bool = Field(False, description="Whether value is outside thresholds")
    alert_band: Literal["low", "critical", "high"] | None = Field(
        None,
        description=(
            "Which alert line the value is past: below low, below critical (a "
            "tank's red line, under low), or above high. None inside its lines."
        ),
    )
    show_on_dashboard: bool = Field(
        True,
        description=(
            "Whether the Live tab draws a gauge for this reading. Every value is "
            "still returned: the vehicle widget looks keys up by name and must "
            "not lose one because its gauge is hidden."
        ),
    )


class LiveSensorReading(BaseModel):
    """One of a preset sensor's readings, and how to show it."""

    param_key: str
    format: Literal["value", "boolean", "count", "of_max"] = Field(
        "value",
        description=(
            "Through the unit adapter, as Yes/No, as a whole number, or as 'n of max_value'"
        ),
    )
    max_value: int | None = Field(None, description="The top of the scale for an 'of_max' reading")


class LiveSensor(BaseModel):
    """One preset sensor on this vehicle (a propane tank), drawn as its own card.

    Its readings' values are in `latest_values`, looked up by `param_key`.
    """

    device_id: str
    label: str = Field(
        description="The sensor's name, which its readings' display names start with"
    )
    preset_key: str
    online: bool = Field(description="Reporting now, by the integrations card's rule")
    last_seen: datetime | None = None
    fill_key: str | None = Field(
        None, description="The reading drawn as the tank's fill (its level), when mapped"
    )
    readings: list[LiveSensorReading] = Field(
        default_factory=list,
        description="Every reading the sensor maps, in the preset's order, the fill included",
    )


class VehicleLiveLinkStatus(BaseModel):
    """Schema for vehicle LiveLink status response (live dashboard)."""

    vin: str
    device_id: str | None = Field(None, description="Linked device ID")
    kind: str | None = Field(
        None,
        description=(
            "Source kind of the device this status describes: the most recently "
            "seen one that drives sessions, else the most recently seen of any "
            "kind. device_id, ecu_status, rssi, battery_voltage and the session "
            "fields come from the same device."
        ),
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description=(
            "Union of Capability values across every device linked to this VIN. "
            "The UI gates sub-tabs on these: a propane gateway declares telemetry "
            "alone and must not be offered DTCs, sessions or trips."
        ),
    )
    #: Strict on purpose: it's computed from `online`, never read from the
    #: stored column, so nothing outside the vocabulary can reach it.
    device_status: DeviceStatusType = Field(
        "offline", description="'online' when `online` is true, else 'offline'"
    )
    online: bool = Field(
        False,
        description=(
            "Whether any device linked to this vehicle is reporting now, each by "
            "the integrations card's rule: a device whose device_status is "
            "'online' counts as online until the offline sweep flips it, one that "
            "never reports a status (Torque) keeps 'unknown' and counts as online "
            "while it has reported within the offline timeout, and a disabled "
            "device is never online."
        ),
    )
    ecu_status: LenientECUStatus = Field("unknown", description="ECU: online/offline/unknown")
    last_seen: datetime | None = Field(None, description="Last data received")
    battery_voltage: float | None = Field(None, description="Vehicle battery (V)")
    rssi: int | None = Field(None, description="WiFi signal (dBm)")

    # Current session info
    current_session_id: int | None = Field(None, description="Active session ID")
    session_started_at: datetime | None = Field(None, description="Current session start")
    session_duration_seconds: int | None = Field(None, description="Session duration so far")

    # Latest parameter values
    latest_values: list[TelemetryLatestValue] = Field(
        default_factory=list, description="Current telemetry readings"
    )
    sensors: list[LiveSensor] = Field(
        default_factory=list,
        description=(
            "Preset sensors on this vehicle, in the order they were added. "
            "Their readings are in latest_values too; the Live tab draws them "
            "on the sensor's card instead of as separate gauges."
        ),
    )


# =============================================================================
# Historical Telemetry Schemas
# =============================================================================


class TelemetryDataPoint(BaseModel):
    """Schema for a single telemetry data point."""

    timestamp: datetime
    value: float


class TelemetrySeriesResponse(BaseModel):
    """Schema for a single parameter's time series."""

    param_key: str
    display_name: str | None
    unit: str | None
    data: list[TelemetryDataPoint]
    min_value: float | None = Field(None, description="Minimum value in range")
    max_value: float | None = Field(None, description="Maximum value in range")
    avg_value: float | None = Field(None, description="Average value in range")


class TelemetryQueryParams(BaseModel):
    """Schema for telemetry query parameters."""

    start: datetime = Field(..., description="Start of time range")
    end: datetime = Field(..., description="End of time range")
    param_keys: list[str] | None = Field(None, description="Parameters to query (None = all)")
    interval_seconds: int | None = Field(None, description="Optional downsampling interval", ge=1)
    limit: int = Field(10000, description="Maximum data points per parameter", ge=1, le=100000)


class TelemetryQueryResponse(BaseModel):
    """Schema for telemetry query response."""

    vin: str
    start: datetime
    end: datetime
    series: list[TelemetrySeriesResponse]
    total_points: int = Field(0, description="Total data points returned")


# =============================================================================
# Daily Summary Schemas
# =============================================================================


class DailySummaryEntry(BaseModel):
    """Schema for a daily summary entry."""

    date: datetime
    min_value: float | None
    max_value: float | None
    avg_value: float | None
    sample_count: int


class DailySummaryResponse(BaseModel):
    """Schema for daily summary query response."""

    param_key: str
    display_name: str | None
    unit: str | None
    entries: list[DailySummaryEntry]


# =============================================================================
# Export Schemas
# =============================================================================


class TelemetryExportParams(BaseModel):
    """Schema for telemetry export parameters."""

    start: datetime = Field(..., description="Start of export range")
    end: datetime = Field(..., description="End of export range")
    param_keys: list[str] | None = Field(None, description="Parameters to export (None = all)")
    format: str = Field("csv", description="Export format: csv or json")
    include_session_markers: bool = Field(True, description="Include session boundaries")
    downsample_seconds: int | None = Field(None, description="Optional downsampling interval", ge=1)
