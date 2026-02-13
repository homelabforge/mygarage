"""Pydantic schemas for API request/response validation."""

from app.schemas.fuel import (
    FuelRecordCreate,
    FuelRecordListResponse,
    FuelRecordResponse,
    FuelRecordUpdate,
)
from app.schemas.odometer import (
    OdometerRecordCreate,
    OdometerRecordListResponse,
    OdometerRecordResponse,
    OdometerRecordUpdate,
)
from app.schemas.vehicle import (
    TrailerDetailsCreate,
    TrailerDetailsResponse,
    TrailerDetailsUpdate,
    VehicleCreate,
    VehicleListResponse,
    VehicleResponse,
    VehicleUpdate,
)
from app.schemas.vin import (
    EngineInfo,
    TransmissionInfo,
    VINDecodeRequest,
    VINDecodeResponse,
)

__all__ = [
    "VINDecodeRequest",
    "VINDecodeResponse",
    "EngineInfo",
    "TransmissionInfo",
    "VehicleCreate",
    "VehicleUpdate",
    "VehicleResponse",
    "VehicleListResponse",
    "TrailerDetailsCreate",
    "TrailerDetailsUpdate",
    "TrailerDetailsResponse",
    "FuelRecordCreate",
    "FuelRecordUpdate",
    "FuelRecordResponse",
    "FuelRecordListResponse",
    "OdometerRecordCreate",
    "OdometerRecordUpdate",
    "OdometerRecordResponse",
    "OdometerRecordListResponse",
]
