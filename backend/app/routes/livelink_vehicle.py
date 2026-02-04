"""Vehicle-specific LiveLink endpoints for status, telemetry, sessions, and DTCs."""

import csv
import io
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.drive_session import (
    DriveSessionDetailResponse,
    DriveSessionListResponse,
    DriveSessionResponse,
)
from app.schemas.dtc import (
    DTCClearRequest,
    DTCClearResponse,
    VehicleDTCListResponse,
    VehicleDTCResponse,
    VehicleDTCUpdate,
)
from app.schemas.telemetry import (
    TelemetryLatestValue,
    TelemetryQueryResponse,
    TelemetrySeriesResponse,
    VehicleLiveLinkStatus,
)
from app.services.auth import require_auth
from app.services.dtc_service import DTCService
from app.services.livelink_service import LiveLinkService
from app.services.session_service import SessionService
from app.services.telemetry_service import TelemetryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/livelink", tags=["Vehicle LiveLink"])


async def verify_vehicle_exists(db: AsyncSession, vin: str) -> Vehicle:
    """Verify vehicle exists and return it."""
    vin = vin.upper().strip()
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle with VIN {vin} not found")
    return vehicle


# =============================================================================
# Status Endpoint (for live dashboard polling)
# =============================================================================


@router.get("/status", response_model=VehicleLiveLinkStatus)
async def get_vehicle_livelink_status(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get live status for a vehicle's LiveLink connection.

    This endpoint is polled every 5 seconds by the frontend for live updates.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Returns:**
    - Device status (online/offline)
    - ECU status
    - Last seen timestamp
    - Current session info
    - Latest telemetry values

    **Security:**
    - Requires authentication
    """
    await verify_vehicle_exists(db, vin)
    vin = vin.upper().strip()

    livelink_service = LiveLinkService(db)
    telemetry_service = TelemetryService(db)
    session_service = SessionService(db)

    # Get linked device
    device = await livelink_service.get_device_by_vin(vin)

    # Get latest telemetry values
    latest_values = await telemetry_service.get_latest_values(vin)
    all_params = await telemetry_service.get_all_parameters()

    # Build latest values with thresholds
    latest_with_thresholds = []
    for lv in latest_values:
        param = all_params.get(lv.param_key)
        in_warning = False
        warning_min = None
        warning_max = None

        if param:
            warning_min = param.warning_min
            warning_max = param.warning_max
            if warning_min is not None and lv.value < warning_min:
                in_warning = True
            if warning_max is not None and lv.value > warning_max:
                in_warning = True

        latest_with_thresholds.append(
            TelemetryLatestValue(
                param_key=lv.param_key,
                value=lv.value,
                unit=param.unit if param else None,
                display_name=param.display_name if param else lv.param_key,
                timestamp=lv.timestamp,
                warning_min=warning_min,
                warning_max=warning_max,
                in_warning=in_warning,
            )
        )

    # Get current session info
    current_session_id = None
    session_started_at = None
    session_duration_seconds = None

    if device and device.current_session_id:
        current_session = await session_service.get_session(device.current_session_id)
        if current_session:
            current_session_id = current_session.id
            session_started_at = current_session.started_at
            if session_started_at:
                session_duration_seconds = int(
                    (datetime.now(session_started_at.tzinfo) - session_started_at).total_seconds()
                )

    return VehicleLiveLinkStatus(
        vin=vin,
        device_id=device.device_id if device else None,
        device_status=device.device_status if device else "offline",
        ecu_status=device.ecu_status if device else "unknown",
        last_seen=device.last_seen if device else None,
        battery_voltage=device.battery_voltage if device else None,
        rssi=device.rssi if device else None,
        current_session_id=current_session_id,
        session_started_at=session_started_at,
        session_duration_seconds=session_duration_seconds,
        latest_values=latest_with_thresholds,
    )


# =============================================================================
# Telemetry Endpoints
# =============================================================================


@router.get("/telemetry", response_model=TelemetryQueryResponse)
async def get_vehicle_telemetry(
    vin: str,
    start: datetime = Query(..., description="Start of time range"),
    end: datetime = Query(..., description="End of time range"),
    param_keys: str | None = Query(None, description="Comma-separated parameter keys"),
    limit: int = Query(10000, ge=1, le=100000, description="Max data points per parameter"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get historical telemetry data for a vehicle.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **start**: Start timestamp (required)
    - **end**: End timestamp (required)
    - **param_keys**: Comma-separated list of parameter keys (optional, all if not specified)
    - **limit**: Maximum data points per parameter (default 10000)

    **Security:**
    - Requires authentication
    """
    await verify_vehicle_exists(db, vin)
    vin = vin.upper().strip()

    telemetry_service = TelemetryService(db)

    # Parse param_keys
    keys_list = None
    if param_keys:
        keys_list = [k.strip() for k in param_keys.split(",") if k.strip()]

    # Query telemetry
    telemetry_data = await telemetry_service.get_telemetry_range(
        vin=vin,
        start=start,
        end=end,
        param_keys=keys_list,
        limit=limit,
    )

    # Group by param_key and calculate stats
    all_params = await telemetry_service.get_all_parameters()
    series_by_key: dict[str, list] = {}

    for point in telemetry_data:
        if point.param_key not in series_by_key:
            series_by_key[point.param_key] = []
        series_by_key[point.param_key].append({"timestamp": point.timestamp, "value": point.value})

    # Build response series
    series = []
    total_points = 0
    for param_key, data_points in series_by_key.items():
        param = all_params.get(param_key)
        values = [p["value"] for p in data_points]

        series.append(
            TelemetrySeriesResponse(
                param_key=param_key,
                display_name=param.display_name if param else param_key,
                unit=param.unit if param else None,
                data=data_points,
                min_value=min(values) if values else None,
                max_value=max(values) if values else None,
                avg_value=sum(values) / len(values) if values else None,
            )
        )
        total_points += len(data_points)

    return TelemetryQueryResponse(
        vin=vin,
        start=start,
        end=end,
        series=series,
        total_points=total_points,
    )


# =============================================================================
# Session Endpoints
# =============================================================================


@router.get("/sessions", response_model=DriveSessionListResponse)
async def list_vehicle_sessions(
    vin: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    start: datetime | None = Query(None, description="Filter sessions starting after this time"),
    end: datetime | None = Query(None, description="Filter sessions ending before this time"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get drive sessions for a vehicle.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **limit**: Max results (default 50)
    - **offset**: Pagination offset
    - **start**: Filter by start time
    - **end**: Filter by end time

    **Security:**
    - Requires authentication
    """
    await verify_vehicle_exists(db, vin)
    vin = vin.upper().strip()

    session_service = SessionService(db)

    sessions = await session_service.get_vehicle_sessions(
        vin=vin,
        limit=limit,
        offset=offset,
        start=start,
        end=end,
    )
    total = await session_service.get_session_count(vin)

    return DriveSessionListResponse(
        sessions=[DriveSessionResponse.model_validate(s) for s in sessions],
        total=total,
    )


@router.get("/sessions/{session_id}", response_model=DriveSessionDetailResponse)
async def get_session_detail(
    vin: str,
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get detailed information about a drive session.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **session_id**: Session ID

    **Security:**
    - Requires authentication
    """
    await verify_vehicle_exists(db, vin)
    vin = vin.upper().strip()

    session_service = SessionService(db)
    session = await session_service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    if session.vin != vin:
        raise HTTPException(status_code=404, detail="Session does not belong to this vehicle")

    # Get additional details
    telemetry_service = TelemetryService(db)

    # Get parameters recorded during session
    if session.started_at and session.ended_at:
        telemetry_data = await telemetry_service.get_telemetry_range(
            vin=vin,
            start=session.started_at,
            end=session.ended_at,
            limit=1,  # Just need to know what params exist
        )
        parameters_recorded = list({t.param_key for t in telemetry_data})
        data_points_count = len(
            await telemetry_service.get_telemetry_range(
                vin=vin, start=session.started_at, end=session.ended_at
            )
        )
    else:
        parameters_recorded = []
        data_points_count = 0

    # Get DTCs that appeared/cleared during session
    # This is a simplified implementation
    dtcs_appeared = []
    dtcs_cleared = []

    return DriveSessionDetailResponse(
        id=session.id,
        vin=session.vin,
        device_id=session.device_id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        duration_seconds=session.duration_seconds,
        start_odometer=session.start_odometer,
        end_odometer=session.end_odometer,
        distance_km=session.distance_km,
        avg_speed=session.avg_speed,
        max_speed=session.max_speed,
        avg_rpm=session.avg_rpm,
        max_rpm=session.max_rpm,
        avg_coolant_temp=session.avg_coolant_temp,
        max_coolant_temp=session.max_coolant_temp,
        avg_throttle=session.avg_throttle,
        max_throttle=session.max_throttle,
        avg_fuel_level=session.avg_fuel_level,
        fuel_used_estimate=session.fuel_used_estimate,
        created_at=session.created_at,
        parameters_recorded=parameters_recorded,
        data_points_count=data_points_count,
        dtcs_appeared=dtcs_appeared,
        dtcs_cleared=dtcs_cleared,
    )


# =============================================================================
# DTC Endpoints
# =============================================================================


@router.get("/dtcs", response_model=VehicleDTCListResponse)
async def list_vehicle_dtcs(
    vin: str,
    include_cleared: bool = Query(False, description="Include cleared DTCs"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get DTCs for a vehicle.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **include_cleared**: Include cleared DTCs (default false)
    - **limit**: Max results

    **Security:**
    - Requires authentication
    """
    await verify_vehicle_exists(db, vin)
    vin = vin.upper().strip()

    dtc_service = DTCService(db)

    if include_cleared:
        dtcs = await dtc_service.get_dtc_history(vin, include_active=True, limit=limit)
    else:
        dtcs = await dtc_service.get_active_dtcs(vin)

    counts = await dtc_service.get_dtc_counts(vin)

    # Enrich with lookup data
    enriched = []
    for dtc in dtcs:
        enriched_data = await dtc_service.enrich_dtc_response(dtc)
        enriched.append(VehicleDTCResponse(**enriched_data))

    return VehicleDTCListResponse(
        dtcs=enriched,
        total=len(enriched),
        active_count=counts["active"],
        critical_count=counts["critical"],
    )


@router.get("/dtcs/{dtc_id}", response_model=VehicleDTCResponse)
async def get_dtc_detail(
    vin: str,
    dtc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get detailed information about a DTC.

    **Security:**
    - Requires authentication
    """
    await verify_vehicle_exists(db, vin)

    dtc_service = DTCService(db)

    # Get DTC by ID
    from app.models.vehicle_dtc import VehicleDTC

    result = await db.execute(select(VehicleDTC).where(VehicleDTC.id == dtc_id))
    dtc = result.scalar_one_or_none()

    if not dtc:
        raise HTTPException(status_code=404, detail=f"DTC {dtc_id} not found")

    if dtc.vin.upper() != vin.upper():
        raise HTTPException(status_code=404, detail="DTC does not belong to this vehicle")

    enriched = await dtc_service.enrich_dtc_response(dtc)
    return VehicleDTCResponse(**enriched)


@router.put("/dtcs/{dtc_id}", response_model=VehicleDTCResponse)
async def update_dtc(
    vin: str,
    dtc_id: int,
    updates: VehicleDTCUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Update a DTC (user notes, custom description/severity).

    **Security:**
    - Requires authentication
    """
    await verify_vehicle_exists(db, vin)

    dtc_service = DTCService(db)

    # Verify DTC belongs to vehicle
    from app.models.vehicle_dtc import VehicleDTC

    result = await db.execute(select(VehicleDTC).where(VehicleDTC.id == dtc_id))
    dtc = result.scalar_one_or_none()

    if not dtc or dtc.vin.upper() != vin.upper():
        raise HTTPException(status_code=404, detail=f"DTC {dtc_id} not found for this vehicle")

    # Update
    updated = await dtc_service.update_dtc(
        dtc_id=dtc_id,
        description=updates.description,
        severity=updates.severity,
        user_notes=updates.user_notes,
    )

    enriched = await dtc_service.enrich_dtc_response(updated)
    return VehicleDTCResponse(**enriched)


@router.post("/dtcs/{dtc_id}/clear", response_model=DTCClearResponse)
async def clear_dtc(
    vin: str,
    dtc_id: int,
    request: DTCClearRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Mark a DTC as cleared.

    **Security:**
    - Requires authentication
    """
    await verify_vehicle_exists(db, vin)

    # Verify DTC belongs to vehicle
    from app.models.vehicle_dtc import VehicleDTC

    result = await db.execute(select(VehicleDTC).where(VehicleDTC.id == dtc_id))
    dtc = result.scalar_one_or_none()

    if not dtc or dtc.vin.upper() != vin.upper():
        raise HTTPException(status_code=404, detail=f"DTC {dtc_id} not found for this vehicle")

    dtc_service = DTCService(db)
    cleared = await dtc_service.clear_dtc(dtc_id, notes=request.notes)

    return DTCClearResponse(
        success=True,
        dtc_id=dtc_id,
        code=cleared.code,
        cleared_at=cleared.cleared_at,
    )


# =============================================================================
# Export Endpoints
# =============================================================================


@router.get("/export/telemetry")
async def export_telemetry(
    vin: str,
    start: datetime = Query(..., description="Start of export range"),
    end: datetime = Query(..., description="End of export range"),
    format: str = Query("csv", description="Export format: csv or json"),
    param_keys: str | None = Query(None, description="Comma-separated parameter keys"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Export telemetry data as CSV or JSON.

    **Query Parameters:**
    - **start**: Start timestamp
    - **end**: End timestamp
    - **format**: 'csv' or 'json' (default csv)
    - **param_keys**: Comma-separated parameter keys (optional)

    **Security:**
    - Requires authentication
    """
    await verify_vehicle_exists(db, vin)
    vin = vin.upper().strip()

    telemetry_service = TelemetryService(db)

    keys_list = None
    if param_keys:
        keys_list = [k.strip() for k in param_keys.split(",") if k.strip()]

    telemetry_data = await telemetry_service.get_telemetry_range(
        vin=vin,
        start=start,
        end=end,
        param_keys=keys_list,
        limit=100000,
    )

    if format.lower() == "json":
        # JSON export
        export_data = [
            {
                "timestamp": t.timestamp.isoformat(),
                "param_key": t.param_key,
                "value": t.value,
            }
            for t in telemetry_data
        ]

        return StreamingResponse(
            iter([json.dumps(export_data, indent=2)]),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=telemetry_{vin}_{start.date()}_{end.date()}.json"
            },
        )

    # CSV export
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "param_key", "value"])

    for t in telemetry_data:
        writer.writerow([t.timestamp.isoformat(), t.param_key, t.value])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=telemetry_{vin}_{start.date()}_{end.date()}.csv"
        },
    )


@router.get("/export/sessions")
async def export_sessions(
    vin: str,
    start: datetime | None = Query(None, description="Filter by start time"),
    end: datetime | None = Query(None, description="Filter by end time"),
    format: str = Query("csv", description="Export format: csv or json"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Export drive sessions as CSV or JSON.

    **Query Parameters:**
    - **start**: Filter sessions starting after this time
    - **end**: Filter sessions ending before this time
    - **format**: 'csv' or 'json' (default csv)

    **Security:**
    - Requires authentication
    """
    await verify_vehicle_exists(db, vin)
    vin = vin.upper().strip()

    session_service = SessionService(db)

    sessions = await session_service.get_vehicle_sessions(
        vin=vin,
        limit=1000,
        start=start,
        end=end,
    )

    if format.lower() == "json":
        export_data = [
            {
                "id": s.id,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                "duration_seconds": s.duration_seconds,
                "distance_km": s.distance_km,
                "avg_speed": s.avg_speed,
                "max_speed": s.max_speed,
                "avg_rpm": s.avg_rpm,
                "max_rpm": s.max_rpm,
            }
            for s in sessions
        ]

        return StreamingResponse(
            iter([json.dumps(export_data, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=sessions_{vin}.json"},
        )

    # CSV export
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "started_at",
            "ended_at",
            "duration_seconds",
            "distance_km",
            "avg_speed",
            "max_speed",
            "avg_rpm",
            "max_rpm",
        ]
    )

    for s in sessions:
        writer.writerow(
            [
                s.id,
                s.started_at.isoformat() if s.started_at else "",
                s.ended_at.isoformat() if s.ended_at else "",
                s.duration_seconds or "",
                s.distance_km or "",
                s.avg_speed or "",
                s.max_speed or "",
                s.avg_rpm or "",
                s.max_rpm or "",
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sessions_{vin}.csv"},
    )
