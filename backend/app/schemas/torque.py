"""Pydantic schemas for Torque-sourced trip and GPS-location read endpoints.

Coordinates (and other Decimal-backed columns on ``LocationPoint``) are
serialized as ``float`` -- the frontend's Leaflet map wants JS numbers, not
strings. The Decimal->float conversion happens in the route handlers
(``app/routes/livelink_vehicle.py``) when building these response models;
storage stays ``Decimal`` end to end (see ``LocationPoint``).
"""

from datetime import datetime

from pydantic import BaseModel, Field

# =============================================================================
# Trip (drive-session-with-GPS) Schemas
# =============================================================================


class TripSummary(BaseModel):
    """Summary of one GPS-tracked trip (a drive session with >=1 location point)."""

    session_id: int = Field(..., description="Drive session ID")
    started_at: datetime = Field(..., description="Trip start time")
    ended_at: datetime | None = Field(None, description="Trip end time")
    duration_seconds: int | None = Field(None, description="Trip duration in seconds")
    distance_km: float | None = Field(None, description="Distance traveled (km)")
    point_count: int = Field(..., description="Number of GPS points recorded for this trip")


class TripListResponse(BaseModel):
    """Schema for GET .../livelink/trips."""

    trips: list[TripSummary] = Field(default_factory=list, description="Trips, newest first")


# =============================================================================
# Location Point Schemas
# =============================================================================


class LocationPointOut(BaseModel):
    """A single GPS breadcrumb point, coordinates as float for map rendering."""

    id: int = Field(..., description="Location point ID")
    timestamp: datetime = Field(..., description="When the point was recorded")
    latitude: float = Field(..., description="Latitude (decimal degrees)")
    longitude: float = Field(..., description="Longitude (decimal degrees)")
    speed: float | None = Field(None, description="Speed (km/h)")
    heading: float | None = Field(None, description="Heading (degrees)")
    altitude: float | None = Field(None, description="Altitude (metres)")


class TripPointsResponse(BaseModel):
    """Schema for GET .../livelink/trips/{session_id}/points."""

    session_id: int = Field(..., description="Drive session ID")
    points: list[LocationPointOut] = Field(
        default_factory=list, description="Points ordered by timestamp ascending"
    )


class LastLocationResponse(BaseModel):
    """Schema for GET .../livelink/location/last."""

    latitude: float = Field(..., description="Latitude (decimal degrees)")
    longitude: float = Field(..., description="Longitude (decimal degrees)")
    timestamp: datetime = Field(..., description="When the point was recorded")
    speed: float | None = Field(None, description="Speed (km/h)")
    heading: float | None = Field(None, description="Heading (degrees)")
    altitude: float | None = Field(None, description="Altitude (metres)")
    drive_session_id: int | None = Field(None, description="Trip this point belongs to, if any")


# =============================================================================
# Location Tracking Opt-Out Schemas (R1-H4)
# =============================================================================


class LocationTrackingUpdate(BaseModel):
    """Request body for PATCH .../livelink/location-tracking."""

    enabled: bool = Field(..., description="Whether GPS location tracking is enabled")


class LocationTrackingResponse(BaseModel):
    """Response body for PATCH .../livelink/location-tracking."""

    location_tracking_enabled: bool = Field(
        ..., description="Whether GPS location tracking is now enabled"
    )


# =============================================================================
# Torque Source Registration Schemas (Task 13, owner-scoped)
# =============================================================================


class TorqueSourceCreate(BaseModel):
    """Request body for POST .../livelink/torque-sources."""

    label: str | None = Field(None, description="Optional friendly name for this source")


class TorqueSourceCreateResponse(BaseModel):
    """Response body for POST .../livelink/torque-sources.

    ``token`` is the raw device token embedded in ``upload_url`` -- shown
    ONCE. It is stored hashed and cannot be retrieved again.
    """

    device_id: str = Field(..., description="Newly created torque-kind device id")
    label: str | None = Field(None, description="Friendly name for this source")
    upload_url: str = Field(..., description="Paste this into Torque Pro's 'Upload URL' setting")
    token: str = Field(..., description="One-time device token (shown once, save it now)")


class TorqueSourceResponse(BaseModel):
    """One entry in the torque-sources list -- no token."""

    device_id: str = Field(..., description="Torque device id")
    label: str | None = Field(None, description="Friendly name for this source")
    device_status: str = Field(..., description="online / offline / unknown")
    last_seen: datetime | None = Field(None, description="Last time this source uploaded data")
    created_at: datetime = Field(..., description="When this source was registered")


class TorqueSourceListResponse(BaseModel):
    """Schema for GET .../livelink/torque-sources."""

    sources: list[TorqueSourceResponse] = Field(
        default_factory=list, description="This vehicle's registered Torque sources"
    )
