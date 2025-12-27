"""Pydantic schemas for API request/response validation."""

from app.schemas.vin import (
    VINDecodeRequest,
    VINDecodeResponse,
    EngineInfo,
    TransmissionInfo,
)
from app.schemas.vehicle import (
    VehicleCreate,
    VehicleUpdate,
    VehicleResponse,
    VehicleListResponse,
    TrailerDetailsCreate,
    TrailerDetailsUpdate,
    TrailerDetailsResponse,
)
from app.schemas.service import (
    ServiceRecordCreate,
    ServiceRecordUpdate,
    ServiceRecordResponse,
    ServiceRecordListResponse,
)
from app.schemas.fuel import (
    FuelRecordCreate,
    FuelRecordUpdate,
    FuelRecordResponse,
    FuelRecordListResponse,
)
from app.schemas.odometer import (
    OdometerRecordCreate,
    OdometerRecordUpdate,
    OdometerRecordResponse,
    OdometerRecordListResponse,
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
    "ServiceRecordCreate",
    "ServiceRecordUpdate",
    "ServiceRecordResponse",
    "ServiceRecordListResponse",
    "FuelRecordCreate",
    "FuelRecordUpdate",
    "FuelRecordResponse",
    "FuelRecordListResponse",
    "OdometerRecordCreate",
    "OdometerRecordUpdate",
    "OdometerRecordResponse",
    "OdometerRecordListResponse",
]
