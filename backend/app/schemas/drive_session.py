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

    #: Which rule cut this session's boundaries. 0 means the pre-v3.3.0 contact
    #: rule, which opened a drive whenever the dongle reached the broker, so a
    #: parked vehicle checking in became one. Exposed so a row shown under
    #: "include earlier drives" can say what it is rather than just look wrong.
    boundary_algorithm_version: int = Field(
        0, description="0 = recorded on device contact (pre-v3.3.0), 1 = on movement"
    )

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

    # Driving insights
    idle_seconds: int | None = Field(None, description="Time spent near-stopped (s)")
    harsh_accel_count: int | None = Field(None, description="Harsh acceleration events")
    harsh_brake_count: int | None = Field(None, description="Harsh braking events")

    # Metadata
    created_at: datetime

    model_config = {"from_attributes": True}


class DriveSessionListResponse(BaseModel):
    """Schema for drive session list response."""

    sessions: list[DriveSessionResponse]
    #: Sessions matching the request's filter, so pagination and the list agree.
    total: int
    #: Sessions with no evidence the vehicle moved, reported whether or not they
    #: are included. A filtered list that shows nothing is indistinguishable
    #: from a broken one unless it can say how many it is holding back.
    stationary_total: int = 0


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
