"""Pydantic schemas for vehicle telemetry operations."""

from datetime import datetime

from pydantic import BaseModel, Field

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


class VehicleLiveLinkStatus(BaseModel):
    """Schema for vehicle LiveLink status response (live dashboard)."""

    vin: str
    device_id: str | None = Field(None, description="Linked device ID")
    device_status: str = Field("offline", description="Device: online/offline")
    ecu_status: str = Field("unknown", description="ECU: online/offline/unknown")
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
