"""Pydantic schemas for WiCAN payload ingestion.

These schemas validate the incoming HTTPS POST payloads from WiCAN devices.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class WiCANConfigEntry(BaseModel):
    """Schema for a single parameter config entry from WiCAN.

    Example:
        {"class": "temperature", "unit": "°C"}
    """

    param_class: str | None = Field(None, alias="class", description="Parameter class")
    unit: str | None = Field(None, description="Unit of measurement")

    model_config = {"populate_by_name": True}


class WiCANStatus(BaseModel):
    """Schema for WiCAN device status block.

    Example:
        {
            "device_id": "aabbccddeeff",
            "fw_version": "4.45",
            "git_version": "v4.45p",
            "hw_version": "WiCAN-OBD-PRO",
            "ecu_status": "online",
            "sta_ip": "192.168.1.50",
            "battery_voltage": 12.6,
            "rssi": -45
        }
    """

    device_id: str = Field(..., description="Device ID (12-char hex from MAC)")
    fw_version: str | None = Field(None, description="Firmware version")
    git_version: str | None = Field(None, description="Git version tag")
    hw_version: str | None = Field(None, description="Hardware version")
    ecu_status: str = Field("unknown", description="ECU status: online/offline")
    sta_ip: str | None = Field(None, description="Device IP on local network")
    battery_voltage: float | None = Field(None, description="Vehicle battery voltage")
    rssi: int | None = Field(None, description="WiFi signal strength")

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, v: str) -> str:
        """Validate and normalize device ID."""
        # Strip whitespace and convert to lowercase
        v = v.strip().lower()
        # Remove any colons or dashes (some devices include MAC separators)
        v = v.replace(":", "").replace("-", "")
        if len(v) < 6 or len(v) > 20:
            raise ValueError("device_id must be 6-20 characters")
        return v

    @field_validator("ecu_status")
    @classmethod
    def validate_ecu_status(cls, v: str) -> str:
        """Normalize ECU status to known values."""
        v = v.strip().lower()
        if v in ("online", "on", "1", "true"):
            return "online"
        elif v in ("offline", "off", "0", "false"):
            return "offline"
        return "unknown"


class WiCANPayload(BaseModel):
    """Schema for complete WiCAN HTTPS POST payload.

    WiCAN devices send two types of payloads:
    1. Status payloads (include device info) - sent periodically
    2. Telemetry-only payloads (just autopid_data) - sent every cycle

    Example with status:
        {
            "autopid_data": {"ENGINE_RPM": 2150, "SPEED": 65},
            "status": {"device_id": "aabbccddeeff", "ecu_status": "online"}
        }

    Example telemetry-only:
        {
            "autopid_data": {"0C-EngineRPM": 750, "0D-VehicleSpeed": 0}
        }
    """

    autopid_data: dict[str, float | int | None] = Field(
        ..., description="Decoded OBD2 parameter values"
    )
    config: dict[str, WiCANConfigEntry] = Field(
        default_factory=dict, description="Parameter metadata"
    )
    status: WiCANStatus | None = Field(
        None, description="Device status (optional, sent periodically)"
    )

    # Optional timestamp for future replay/buffer support
    timestamp: datetime | None = Field(
        None, description="Optional device timestamp for replay support"
    )

    @field_validator("autopid_data")
    @classmethod
    def validate_autopid_data(cls, v: dict[str, Any]) -> dict[str, float | int | None]:
        """Validate and normalize autopid_data values."""
        result = {}
        for key, value in v.items():
            if value is None:
                result[key] = None
            elif isinstance(value, (int, float)):
                result[key] = float(value)
            else:
                # Skip non-numeric values but log them
                continue
        return result


class IngestResult(BaseModel):
    """Schema for ingestion result response."""

    success: bool = Field(True, description="Whether ingestion succeeded")
    device_id: str = Field(..., description="Device ID from payload")
    is_new_device: bool = Field(False, description="Whether device was auto-discovered")
    is_linked: bool = Field(False, description="Whether device is linked to a vehicle")
    parameters_stored: int = Field(0, description="Number of parameters stored")
    session_status: str | None = Field(None, description="Session started/ended/active/none")
    skipped_duplicate: bool = Field(False, description="Whether payload was a duplicate")
    message: str | None = Field(None, description="Additional status message")


class IngestError(BaseModel):
    """Schema for ingestion error response."""

    success: bool = Field(False)
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code for client handling")
