"""Session service for drive session detection and management."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle_telemetry import VehicleTelemetry
from app.utils.datetime_utils import utc_now
from app.utils.odometer_units import is_odometer_param_key

logger = logging.getLogger(__name__)

# Possible OBD2 parameter names for vehicle speed (different WiCAN firmware/configs)
SPEED_PARAM_KEYS = ["SPEED", "0D-VehicleSpeed", "0D-VEHICLESPEED"]


class SessionService:
    """Service for drive session detection and aggregation."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    # =========================================================================
    # Session Detection
    # =========================================================================

    async def handle_ecu_status_change(
        self,
        device: LiveLinkDevice,
        new_ecu_status: str,
        timestamp: datetime,
    ) -> DriveSession | None:
        """Handle ECU status transition for session detection.

        Args:
            device: The device reporting the status
            new_ecu_status: New ECU status (online/offline)
            timestamp: When the status changed

        Returns:
            DriveSession if session started/ended, None otherwise
        """
        if not device.vin:
            return None  # Device not linked to vehicle

        old_status = device.ecu_status or "unknown"

        # ECU went online -> start new session
        if old_status != "online" and new_ecu_status == "online":
            return await self.start_session(device, timestamp)

        # ECU went offline -> end current session
        if old_status == "online" and new_ecu_status == "offline":
            if device.current_session_id:
                return await self.end_session(device, timestamp)

        return None

    async def handle_ecu_online(self, vin: str, device_id: str) -> DriveSession | None:
        """Handle ECU coming online - convenience method for route.

        Args:
            vin: Vehicle VIN
            device_id: Device ID

        Returns:
            DriveSession if a new session was started
        """
        device = await self._get_device(device_id)
        if not device or device.vin != vin:
            return None

        return await self.handle_ecu_status_change(
            device=device,
            new_ecu_status="online",
            timestamp=utc_now(),
        )

    async def handle_ecu_offline(self, vin: str, device_id: str) -> DriveSession | None:
        """Handle ECU going offline - convenience method for route.

        Args:
            vin: Vehicle VIN
            device_id: Device ID

        Returns:
            DriveSession if a session was ended
        """
        device = await self._get_device(device_id)
        if not device or device.vin != vin:
            return None

        return await self.handle_ecu_status_change(
            device=device,
            new_ecu_status="offline",
            timestamp=utc_now(),
        )

    async def _get_device(self, device_id: str) -> LiveLinkDevice | None:
        """Get a device by ID."""
        result = await self.db.execute(
            select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
        )
        return result.scalar_one_or_none()

    async def start_session(
        self,
        device: LiveLinkDevice,
        timestamp: datetime,
    ) -> DriveSession:
        """Start a new drive session.

        Args:
            device: The device starting the session
            timestamp: Session start time

        Returns:
            The new DriveSession
        """
        if not device.vin:
            raise ValueError("Device must be linked to start a session")

        # End any existing session first
        if device.current_session_id:
            await self.end_session(device, timestamp)

        # Get start odometer if available
        start_odometer = await self._get_current_odometer(device.vin)

        # Create new session
        session = DriveSession(
            vin=device.vin,
            device_id=device.device_id,
            started_at=timestamp,
            start_odometer=start_odometer,
        )
        self.db.add(session)
        await self.db.flush()

        # Update device with current session
        device.current_session_id = session.id
        device.ecu_status = "online"

        logger.info(
            "Started drive session %d for vehicle %s (device %s)",
            session.id,
            device.vin,
            device.device_id,
        )
        return session

    async def end_session(
        self,
        device: LiveLinkDevice,
        timestamp: datetime,
    ) -> DriveSession | None:
        """End the current drive session and calculate aggregates.

        Args:
            device: The device ending the session
            timestamp: Session end time

        Returns:
            The ended DriveSession, or None if no active session
        """
        if not device.current_session_id:
            return None

        # Get the current session
        result = await self.db.execute(
            select(DriveSession).where(DriveSession.id == device.current_session_id)
        )
        session = result.scalar_one_or_none()

        if not session:
            device.current_session_id = None
            return None

        # Calculate session duration
        session.ended_at = timestamp
        if session.started_at:
            # Ensure both datetimes are naive UTC for subtraction
            started = session.started_at
            if started.tzinfo is not None:
                started = started.replace(tzinfo=None)
            ended = timestamp
            if ended.tzinfo is not None:
                ended = ended.replace(tzinfo=None)
            duration = (ended - started).total_seconds()
            session.duration_seconds = int(duration)

        # Get end odometer
        if device.vin:
            session.end_odometer = await self._get_current_odometer(device.vin)

        # Calculate distance
        if session.start_odometer and session.end_odometer:
            session.distance_km = session.end_odometer - session.start_odometer

        # GPS fallback: Torque trips have no odometer PID -> derive distance from the breadcrumb.
        if session.distance_km is None:
            from app.services.location_service import LocationService  # local import avoids cycle

            points = await LocationService(self.db).get_trip_points(session.vin, session.id)
            if len(points) >= 2:
                coords = [(float(p.latitude), float(p.longitude)) for p in points]
                session.distance_km = float(LocationService.haversine_km(coords))

        # Calculate aggregates from telemetry
        await self._calculate_session_aggregates(session)
        await self._calculate_driving_insights(session)

        # Clear device's current session
        device.current_session_id = None
        device.ecu_status = "offline"

        logger.info(
            "Ended drive session %d for vehicle %s (duration: %d seconds)",
            session.id,
            device.vin,
            session.duration_seconds or 0,
        )
        return session

    async def resolve_torque_session(
        self,
        device: LiveLinkDevice,
        torque_session_id: str | None,
        timestamp: datetime,
    ) -> DriveSession | None:
        """Find-or-create a DriveSession for a Torque `session` id. Replay/out-of-order safe."""
        device.last_seen = utc_now().replace(
            tzinfo=None
        )  # server clock drives inactivity finalize (R1-H7)
        started = timestamp.replace(tzinfo=None) if timestamp.tzinfo is not None else timestamp

        if torque_session_id is None:
            if not device.current_session_id:
                return None
            return (
                await self.db.execute(
                    select(DriveSession).where(DriveSession.id == device.current_session_id)
                )
            ).scalar_one_or_none()

        existing = (
            await self.db.execute(
                select(DriveSession).where(
                    DriveSession.device_id == device.device_id,
                    DriveSession.external_session_id == torque_session_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            # Replay/continuation of a KNOWN session id: append data only. Never move the
            # current-session pointer (a late older-session packet must not drag it backward)
            # and never finalize anything (a late packet must not end the active trip). (R1-H2, R2-H1)
            return existing

        # NEW (first-seen) session id. Decide whether it is the newest drive or a late straggler
        # from an OLDER drive whose first packet arrived after a newer trip went active (R3-H1).
        current = None
        if device.current_session_id:
            current = (
                await self.db.execute(
                    select(DriveSession).where(DriveSession.id == device.current_session_id)
                )
            ).scalar_one_or_none()
        is_newer = current is None or current.started_at is None or started >= current.started_at

        if not is_newer:
            # Chronologically-older first-seen session: record it as an already-closed trip so it
            # never leaks open, and do NOT finalize or unseat the active newer trip. (R3-H1)
            session = DriveSession(
                vin=device.vin,
                device_id=device.device_id,
                started_at=started,
                ended_at=started,
                duration_seconds=0,
                external_session_id=torque_session_id,
            )
            self.db.add(session)
            await self.db.flush()
            return session

        # Newest drive: finalize the prior (older) open session so it does not leak open, THEN
        # open the new one and advance the pointer.
        if device.current_session_id:
            await self.end_session(
                device, utc_now().replace(tzinfo=None)
            )  # server-now end >= prior start (R2-H1, R2-H2)
        # Deliberately do NOT set start_odometer here. _get_current_odometer() is VIN-scoped,
        # not device-scoped, so on a vehicle with BOTH a WiCAN dongle and a Torque source it
        # would attribute the co-located WiCAN device's odometer to this Torque trip. Torque
        # has no odometer PID at all -> leave start_odometer None so end_session's odometer-
        # delta gate never fires, forcing distance to come from the GPS breadcrumb fallback.
        session = DriveSession(
            vin=device.vin,
            device_id=device.device_id,
            started_at=started,
            external_session_id=torque_session_id,
        )
        self.db.add(session)
        await self.db.flush()
        device.current_session_id = session.id
        return session

    async def _get_current_odometer(self, vin: str) -> float | None:
        """Get the current odometer reading from latest telemetry, in kilometres.

        Matching is by key *shape*, not an exact name list: the standard SAE
        J1979 key is `A6-ODOMETER`, and an exact-match list that omitted it left
        every session on a standard-PID device with no odometer and no distance.

        No conversion happens here. `TelemetryService.store_telemetry`
        normalises the odometer to canonical km on the way in, so the stored
        latest value is already metric and converting again would square the
        factor. Test `test_ingest_then_session_converts_exactly_once` drives
        ingest and session together and fails if this starts converting.
        """
        from app.models.vehicle_telemetry import VehicleTelemetryLatest

        result = await self.db.execute(
            select(VehicleTelemetryLatest.param_key, VehicleTelemetryLatest.value).where(
                VehicleTelemetryLatest.vin == vin
            )
        )
        for param_key, value in result.all():
            if value is not None and is_odometer_param_key(param_key):
                return float(value)
        return None

    async def _calculate_session_aggregates(self, session: DriveSession) -> None:
        """Calculate aggregate statistics for a session from telemetry data."""
        if not session.started_at or not session.ended_at:
            return

        # Define which parameters to aggregate.
        # Each entry maps to a list of possible param_key names to check,
        # since different WiCAN firmware/configs use different naming conventions
        # (e.g. OBD2 PID-prefixed "0D-VehicleSpeed" vs generic "SPEED").
        aggregate_mappings = {
            "speed": (SPEED_PARAM_KEYS, "avg_speed", "max_speed"),
            "rpm": (["ENGINE_RPM", "0C-EngineRPM", "0C-ENGINERPM"], "avg_rpm", "max_rpm"),
            "coolant": (
                ["COOLANT_TMP", "05-EngineCoolantTemp", "05-ENGINECOOLANTTEMP"],
                "avg_coolant_temp",
                "max_coolant_temp",
            ),
            "throttle": (
                ["THROTTLE", "11-ThrottlePosition", "11-THROTTLEPOSITION"],
                "avg_throttle",
                "max_throttle",
            ),
            "fuel": (["FUEL", "2F-FuelTankLevel", "2F-FUELTANKLEVEL"], "avg_fuel_level", None),
        }

        for _, (param_keys, avg_attr, max_attr) in aggregate_mappings.items():
            stats = await self._get_param_stats_multi(
                session.vin, param_keys, session.started_at, session.ended_at
            )
            count = stats.get("count")
            if count and count > 0:
                if avg_attr:
                    setattr(session, avg_attr, stats["avg"])
                if max_attr:
                    setattr(session, max_attr, stats["max"])

    async def _calculate_driving_insights(self, session: DriveSession) -> None:
        """Derive idle time and harsh accel/brake counts from SPEED samples.

        Idle: consecutive samples below 5 km/h contribute their Δt.
        Harsh accel/brake: |Δv/Δt| above ~3.5 m/s² (≈12.6 km/h per second).

        NOTE: This currently loads all SPEED rows into Python. A future optimization
        could use SQL window functions (LAG) to compute deltas in the database, but
        that change requires test coverage to catch regressions.
        """
        if not session.started_at or not session.ended_at:
            return

        upper_keys = [k.upper() for k in SPEED_PARAM_KEYS]
        result = await self.db.execute(
            select(VehicleTelemetry.timestamp, VehicleTelemetry.value)
            .where(VehicleTelemetry.vin == session.vin)
            .where(func.upper(VehicleTelemetry.param_key).in_(upper_keys))
            .where(VehicleTelemetry.timestamp >= session.started_at)
            .where(VehicleTelemetry.timestamp <= session.ended_at)
            .order_by(VehicleTelemetry.timestamp.asc())
        )
        rows = list(result.all())
        if len(rows) < 2:
            session.idle_seconds = 0
            session.harsh_accel_count = 0
            session.harsh_brake_count = 0
            return

        idle_seconds = 0.0
        harsh_accel = 0
        harsh_brake = 0
        idle_threshold_kmh = 5.0
        harsh_ms2 = 3.5  # m/s²
        # Convert km/h/s to m/s²: 1 km/h/s = 1000/3600 m/s² ≈ 0.2778
        harsh_kmh_per_s = harsh_ms2 / (1000.0 / 3600.0)

        prev_ts, prev_speed = rows[0]
        for ts, speed in rows[1:]:
            if prev_ts is None or ts is None or speed is None or prev_speed is None:
                prev_ts, prev_speed = ts, speed
                continue
            dt = (ts - prev_ts).total_seconds()
            if dt <= 0 or dt > 120:
                prev_ts, prev_speed = ts, speed
                continue
            if float(prev_speed) < idle_threshold_kmh and float(speed) < idle_threshold_kmh:
                idle_seconds += dt
            dv_dt = (float(speed) - float(prev_speed)) / dt
            if dv_dt >= harsh_kmh_per_s:
                harsh_accel += 1
            elif dv_dt <= -harsh_kmh_per_s:
                harsh_brake += 1
            prev_ts, prev_speed = ts, speed

        session.idle_seconds = int(round(idle_seconds))
        session.harsh_accel_count = harsh_accel
        session.harsh_brake_count = harsh_brake

    async def _get_param_stats_multi(
        self,
        vin: str,
        param_keys: list[str],
        start: datetime,
        end: datetime,
    ) -> dict[str, float | None]:
        """Get stats for a parameter during a time range.

        Accepts multiple possible param_key names and matches any of them
        (case-insensitive) to handle different WiCAN naming conventions.
        """
        upper_keys = [k.upper() for k in param_keys]
        result = await self.db.execute(
            select(
                func.min(VehicleTelemetry.value),
                func.max(VehicleTelemetry.value),
                func.avg(VehicleTelemetry.value),
                func.count(VehicleTelemetry.id),
            )
            .where(VehicleTelemetry.vin == vin)
            .where(func.upper(VehicleTelemetry.param_key).in_(upper_keys))
            .where(VehicleTelemetry.timestamp >= start)
            .where(VehicleTelemetry.timestamp <= end)
        )
        row = result.first()
        if not row:
            return {"min": None, "max": None, "avg": None, "count": 0}

        return {
            "min": row[0],
            "max": row[1],
            "avg": row[2],
            "count": row[3] or 0,
        }

    # =========================================================================
    # Timeout Detection
    # =========================================================================

    async def check_session_timeouts(self, timeout_minutes: int = 5) -> list[DriveSession]:
        """Check for sessions that have timed out due to no data.

        This is called periodically by the background task to detect
        sessions where the device lost connection without proper ECU offline.

        Args:
            timeout_minutes: Minutes of inactivity before timeout

        Returns:
            List of sessions that were closed due to timeout
        """
        cutoff = utc_now().replace(tzinfo=None) - timedelta(minutes=timeout_minutes)
        closed_sessions = []

        # Find devices with active sessions that haven't been seen recently
        result = await self.db.execute(
            select(LiveLinkDevice)
            .where(LiveLinkDevice.current_session_id.isnot(None))
            .where(LiveLinkDevice.last_seen < cutoff)
        )
        stale_devices = result.scalars().all()

        for device in stale_devices:
            # End the session at the last seen time
            last_seen = device.last_seen or utc_now().replace(tzinfo=None)
            session = await self.end_session(device, last_seen)
            if session:
                closed_sessions.append(session)
                logger.info(
                    "Closed session %d for device %s due to timeout",
                    session.id,
                    device.device_id,
                )

        if closed_sessions:
            await self.db.commit()

        return closed_sessions

    # =========================================================================
    # Query Methods
    # =========================================================================

    async def get_session(self, session_id: int) -> DriveSession | None:
        """Get a session by ID."""
        result = await self.db.execute(select(DriveSession).where(DriveSession.id == session_id))
        return result.scalar_one_or_none()

    async def get_vehicle_sessions(
        self,
        vin: str,
        limit: int = 50,
        offset: int = 0,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[DriveSession]:
        """Get sessions for a vehicle."""
        query = (
            select(DriveSession)
            .where(DriveSession.vin == vin)
            .order_by(DriveSession.started_at.desc())
        )

        if start:
            query = query.where(DriveSession.started_at >= start)
        if end:
            query = query.where(DriveSession.ended_at <= end)

        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_session_count(self, vin: str) -> int:
        """Get total session count for a vehicle."""
        result = await self.db.execute(
            select(func.count(DriveSession.id)).where(DriveSession.vin == vin)
        )
        row = result.first()
        return row[0] if row else 0

    async def get_current_session(self, device: LiveLinkDevice) -> DriveSession | None:
        """Get the current active session for a device."""
        if not device.current_session_id:
            return None

        result = await self.db.execute(
            select(DriveSession).where(DriveSession.id == device.current_session_id)
        )
        return result.scalar_one_or_none()
