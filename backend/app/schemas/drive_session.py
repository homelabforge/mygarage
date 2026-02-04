"""Pydantic schemas for drive session operations."""

from datetime import datetime

from pydantic import BaseModel, Field

# =============================================================================
# Drive Session Schemas
# =============================================================================


class DriveSessionBase(BaseModel):
    """Base drive session schema."""

    started_at: datetime = Field(..., description="Session start time")
    ended_at: datetime | None = Field(None, description="Session end time")
    duration_seconds: int | None = Field(None, description="Session duration in seconds")


class DriveSessionResponse(DriveSessionBase):
    """Schema for drive session response."""

    id: int
    vin: str
    device_id: str

    # Odometer data
    start_odometer: float | None = Field(None, description="Odometer at start (km)")
    end_odometer: float | None = Field(None, description="Odometer at end (km)")
    distance_km: float | None = Field(None, description="Distance traveled (km)")

    # Speed aggregates
    avg_speed: float | None = Field(None, description="Average speed (km/h)")
    max_speed: float | None = Field(None, description="Maximum speed (km/h)")

    # RPM aggregates
    avg_rpm: float | None = Field(None, description="Average RPM")
    max_rpm: float | None = Field(None, description="Maximum RPM")

    # Temperature aggregates
    avg_coolant_temp: float | None = Field(None, description="Average coolant temp (°C)")
    max_coolant_temp: float | None = Field(None, description="Maximum coolant temp (°C)")

    # Throttle aggregates
    avg_throttle: float | None = Field(None, description="Average throttle (%)")
    max_throttle: float | None = Field(None, description="Maximum throttle (%)")

    # Fuel metrics
    avg_fuel_level: float | None = Field(None, description="Average fuel level (%)")
    fuel_used_estimate: float | None = Field(None, description="Estimated fuel used (L)")

    # Metadata
    created_at: datetime

    model_config = {"from_attributes": True}


class DriveSessionListResponse(BaseModel):
    """Schema for drive session list response."""

    sessions: list[DriveSessionResponse]
    total: int


class DriveSessionDetailResponse(DriveSessionResponse):
    """Schema for detailed session response with telemetry summary."""

    # Summary of parameters recorded during session
    parameters_recorded: list[str] = Field(
        default_factory=list, description="Parameter keys recorded"
    )
    data_points_count: int = Field(0, description="Total telemetry points in session")

    # DTC events during session
    dtcs_appeared: list[str] = Field(
        default_factory=list, description="DTCs that appeared during session"
    )
    dtcs_cleared: list[str] = Field(
        default_factory=list, description="DTCs that cleared during session"
    )


# =============================================================================
# Session Query Schemas
# =============================================================================


class SessionQueryParams(BaseModel):
    """Schema for session query parameters."""

    start: datetime | None = Field(None, description="Filter sessions starting after this time")
    end: datetime | None = Field(None, description="Filter sessions ending before this time")
    min_duration_seconds: int | None = Field(None, description="Minimum session duration", ge=0)
    limit: int = Field(50, description="Maximum sessions to return", ge=1, le=500)
    offset: int = Field(0, description="Pagination offset", ge=0)


# =============================================================================
# Session Telemetry Schemas
# =============================================================================


class SessionTelemetryRequest(BaseModel):
    """Schema for requesting telemetry data for a session."""

    param_keys: list[str] | None = Field(None, description="Parameters to include (None = all)")
    downsample_seconds: int | None = Field(None, description="Optional downsampling interval", ge=1)


class SessionTelemetryDataPoint(BaseModel):
    """Schema for a session telemetry data point."""

    timestamp: datetime
    param_key: str
    value: float


class SessionTelemetryResponse(BaseModel):
    """Schema for session telemetry response."""

    session_id: int
    started_at: datetime
    ended_at: datetime | None
    data: list[SessionTelemetryDataPoint]
    total_points: int
