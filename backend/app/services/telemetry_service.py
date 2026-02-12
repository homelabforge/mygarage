"""Telemetry service for LiveLink data ingestion and storage."""

import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OdometerRecord
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import LiveLinkParameter
from app.models.vehicle_telemetry import (
    TelemetryDailySummary,
    VehicleTelemetry,
    VehicleTelemetryLatest,
)
from app.services.settings_service import SettingsService
from app.utils.units import UnitConverter

# PIDs that represent odometer readings (case-insensitive matching)
ODOMETER_PID_PATTERNS = [
    "A6-",  # Standard OBD2 PID 0xA6 (166)
    "ODOMETER",
    "ODO",
    "MILEAGE",
    "DISTANCE_TOTAL",
    "TOTAL_DISTANCE",
]

# Regex to detect standard OBD2 PID-prefixed param keys (e.g. "A6-Odometer", "0D-VehicleSpeed").
# Standard OBD2 PIDs always report in metric units per SAE J1979.
_OBD2_PID_PREFIX_RE = re.compile(r"^[0-9A-Fa-f]{1,2}-")

logger = logging.getLogger(__name__)


class TelemetryService:
    """Service for telemetry data ingestion and storage."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    # =========================================================================
    # Payload Hash / Deduplication
    # =========================================================================

    @staticmethod
    def compute_payload_hash(autopid_data: dict[str, Any]) -> str:
        """Compute a hash of the autopid_data for deduplication.

        Uses sorted JSON serialization to ensure consistent hashing.
        """
        # Sort keys and round floats for consistent hashing
        normalized = {}
        for key, value in sorted(autopid_data.items()):
            if isinstance(value, float):
                # Round to 2 decimal places to handle float precision
                normalized[key] = round(value, 2)
            else:
                normalized[key] = value

        serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]  # First 16 chars

    async def is_duplicate_payload(self, device_id: str, payload_hash: str) -> bool:
        """Check if payload is a duplicate based on hash.

        Returns True if the hash matches the device's last_payload_hash.
        """
        result = await self.db.execute(
            select(LiveLinkDevice.last_payload_hash).where(LiveLinkDevice.device_id == device_id)
        )
        row = result.first()
        if not row or not row[0]:
            return False

        return row[0] == payload_hash

    async def update_payload_hash(self, device_id: str, payload_hash: str) -> None:
        """Update the device's last_payload_hash."""
        await self.db.execute(
            text(
                "UPDATE livelink_devices SET last_payload_hash = :hash WHERE device_id = :device_id"
            ).bindparams(hash=payload_hash, device_id=device_id)
        )

    # =========================================================================
    # Parameter Management
    # =========================================================================

    async def get_parameter(self, param_key: str) -> LiveLinkParameter | None:
        """Get a parameter by key."""
        result = await self.db.execute(
            select(LiveLinkParameter).where(LiveLinkParameter.param_key == param_key)
        )
        return result.scalar_one_or_none()

    async def get_all_parameters(self) -> dict[str, LiveLinkParameter]:
        """Get all parameters as a dict keyed by param_key."""
        result = await self.db.execute(select(LiveLinkParameter))
        return {p.param_key: p for p in result.scalars().all()}

    async def get_or_create_parameter(
        self,
        param_key: str,
        display_name: str | None = None,
        unit: str | None = None,
        param_class: str | None = None,
    ) -> LiveLinkParameter | None:
        """Get or create a parameter definition.

        Wrapper for auto_register_parameter for route compatibility.
        """
        return await self.auto_register_parameter(param_key, unit, param_class)

    async def auto_register_parameter(
        self,
        param_key: str,
        unit: str | None = None,
        param_class: str | None = None,
    ) -> LiveLinkParameter:
        """Auto-register a new parameter from WiCAN config block.

        Returns existing parameter if already registered.
        """
        existing = await self.get_parameter(param_key)
        if existing:
            # Update metadata if provided and not already set
            if unit and not existing.unit:
                existing.unit = unit
            if param_class and not existing.param_class:
                existing.param_class = param_class
                existing.category = self._classify_param(param_class)
            return existing

        # Create new parameter
        category = self._classify_param(param_class)
        display_name = self._format_display_name(param_key)

        # Set sensible defaults based on class
        show_on_dashboard = param_class in (
            "speed",
            "frequency",
            "temperature",
            "voltage",
            "battery",
        )
        archive_only = not show_on_dashboard

        param = LiveLinkParameter(
            param_key=param_key,
            display_name=display_name,
            unit=unit,
            param_class=param_class,
            category=category,
            show_on_dashboard=show_on_dashboard,
            archive_only=archive_only,
            storage_interval_seconds=0,  # Store all by default
        )
        self.db.add(param)
        await self.db.flush()

        logger.info("Auto-registered new parameter: %s", param_key)
        return param

    def _classify_param(self, param_class: str | None) -> str:
        """Classify a parameter into a category based on its class."""
        if not param_class:
            return "other"

        class_lower = param_class.lower()
        if class_lower in ("temperature",):
            return "temperature"
        elif class_lower in ("speed", "distance"):
            return "engine"
        elif class_lower in ("frequency",):  # RPM
            return "engine"
        elif class_lower in ("voltage", "battery"):
            return "electrical"
        elif class_lower in ("pressure", "vacuum"):
            return "engine"
        elif class_lower in ("power_factor",):  # Throttle, load
            return "engine"
        else:
            return "other"

    def _format_display_name(self, param_key: str) -> str:
        """Format a parameter key into a display name."""
        # Replace underscores with spaces and title case
        return param_key.replace("_", " ").title()

    def _is_odometer_param(self, param_key: str) -> bool:
        """Check if a parameter key represents an odometer reading."""
        param_upper = param_key.upper()
        for pattern in ODOMETER_PID_PATTERNS:
            if pattern.upper() in param_upper:
                return True
        return False

    async def _sanitize_odometer_value(self, vin: str, value: float) -> float | None:
        """Sanitize an odometer value, returning None if invalid.

        Applies the same sanity checks as _sync_odometer_from_telemetry:
        - Absolute cap at 1 million miles
        - Reject unreasonable jumps (>10,000 from existing max)
        - Reject negative/zero values

        Returns:
            Sanitized value if valid, None if should be rejected
        """
        mileage = int(round(value))

        # Reject zero/negative
        if mileage <= 0:
            return None

        # Absolute cap at 1 million miles
        if mileage > 1_000_000:
            logger.warning(
                "Rejected odometer %d for %s: exceeds 1M mile cap",
                mileage,
                vin[:8],
            )
            return None

        # Query max existing mileage to check for unreasonable jumps
        max_result = await self.db.execute(
            select(func.max(OdometerRecord.mileage)).where(OdometerRecord.vin == vin)
        )
        max_mileage = max_result.scalar() or 0

        # Reject values that are unreasonably higher than existing max
        # (prevents overflow values like 0xFFFFFF from being displayed)
        if max_mileage > 0 and mileage > max_mileage + 10_000:
            logger.warning(
                "Rejected odometer %d for %s: unreasonable jump from %d",
                mileage,
                vin[:8],
                max_mileage,
            )
            return None

        return float(mileage)

    # =========================================================================
    # Telemetry Storage
    # =========================================================================

    async def store_telemetry(
        self,
        vin: str,
        device_id: str,
        autopid_data: dict[str, float | int | None],
        config: dict[str, dict[str, str | None]],
        timestamp: datetime | None = None,
    ) -> int:
        """Store telemetry data from a WiCAN payload.

        Args:
            vin: Vehicle VIN
            device_id: Device ID
            autopid_data: Parameter values from payload
            config: Parameter metadata from payload
            timestamp: Optional device timestamp (defaults to now)

        Returns:
            Number of parameters stored to historical table
        """
        if timestamp is None:
            timestamp = datetime.now(UTC)

        received_at = datetime.now(UTC)

        # Get all parameters to check storage intervals
        parameters = await self.get_all_parameters()

        stored_count = 0

        for param_key, value in autopid_data.items():
            if value is None:
                continue

            # Auto-register parameter if not exists
            param_config = config.get(param_key, {})
            param = parameters.get(param_key)
            if not param:
                unit = param_config.get("unit") if param_config else None
                param_class = param_config.get("class") if param_config else None
                param = await self.auto_register_parameter(param_key, unit, param_class)
                parameters[param_key] = param

            # Check if this is an odometer parameter and apply sanity checks
            is_odometer = self._is_odometer_param(param_key)
            if is_odometer:
                sanitized_value = await self._sanitize_odometer_value(vin, float(value))
                if sanitized_value is None:
                    # Invalid odometer value - skip storing to latest but may still log to historical
                    continue
                value = sanitized_value

            # Always update latest value (for live dashboard)
            await self._upsert_latest_value(vin, param_key, float(value), timestamp, received_at)

            # Check storage interval for historical storage
            if param.storage_interval_seconds > 0:
                should_store = await self._should_store_historical(
                    vin, param_key, param.storage_interval_seconds
                )
                if not should_store:
                    continue

            # Store to historical table
            try:
                telemetry = VehicleTelemetry(
                    vin=vin,
                    device_id=device_id,
                    param_key=param_key,
                    value=float(value),
                    timestamp=timestamp,
                    received_at=received_at,
                )
                self.db.add(telemetry)
                stored_count += 1
            except IntegrityError:
                # Duplicate (same device_id, param_key, timestamp) - skip
                pass

        # Check for odometer reading and sync
        await self._sync_odometer_from_telemetry(vin, autopid_data, timestamp)

        return stored_count

    async def _sync_odometer_from_telemetry(
        self,
        vin: str,
        autopid_data: dict[str, float | int | None],
        timestamp: datetime,
    ) -> None:
        """Sync odometer record from telemetry if odometer PID is present.

        Only creates one record per day to avoid spamming the odometer table.
        Records are marked with source='livelink'.
        """
        # Find odometer value in telemetry
        odometer_value: float | None = None
        odometer_key: str | None = None

        for param_key, value in autopid_data.items():
            if value is None:
                continue

            # Check if this is an odometer parameter
            param_upper = param_key.upper()
            for pattern in ODOMETER_PID_PATTERNS:
                if pattern.upper() in param_upper:
                    odometer_value = float(value)
                    odometer_key = param_key
                    break
            if odometer_value is not None:
                break

        if odometer_value is None or odometer_key is None:
            return  # No odometer PID found

        # Standard OBD2 PIDs (e.g. A6-Odometer) report in metric per SAE J1979.
        # Convert to the system's distance unit if needed.
        if _OBD2_PID_PREFIX_RE.match(odometer_key):
            distance_setting = await SettingsService.get(self.db, "distance_unit")
            distance_unit = distance_setting.value if distance_setting else "miles"
            if distance_unit == "miles":
                converted = UnitConverter.km_to_miles(odometer_value)
                if converted is None:
                    return
                logger.debug(
                    "Converting OBD2 odometer %.1f km → %.1f mi for %s",
                    odometer_value,
                    converted,
                    vin[:8],
                )
                odometer_value = converted

        mileage = int(round(odometer_value))
        if mileage <= 0:
            return  # Invalid odometer reading

        # Sanity check: absolute cap at 1 million miles (no vehicle reaches this)
        if mileage > 1_000_000:
            logger.warning(
                "Rejected odometer %d for %s: exceeds 1M mile cap",
                mileage,
                vin[:8],
            )
            return

        # Query max existing mileage for this VIN to avoid duplicate values
        max_result = await self.db.execute(
            select(func.max(OdometerRecord.mileage)).where(OdometerRecord.vin == vin)
        )
        max_mileage = max_result.scalar() or 0

        # Sanity check: reject unreasonable jumps (prevents overflow values like 0xFFFFFF)
        if max_mileage > 0 and mileage > max_mileage + 10_000:
            logger.warning(
                "Rejected odometer %d for %s: unreasonable jump from %d",
                mileage,
                vin[:8],
                max_mileage,
            )
            return

        # Only proceed if this is a new higher reading
        if mileage <= max_mileage:
            return  # Skip - not a new higher reading than existing records

        # Cap date to today (don't allow future dates from device clock issues)
        today = date_type.today()
        record_date = min(timestamp.date(), today) if timestamp else today

        result = await self.db.execute(
            select(OdometerRecord).where(
                OdometerRecord.vin == vin,
                OdometerRecord.date == record_date,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Only update if this is a LiveLink record (don't overwrite manual entries)
            if existing.source == "livelink":
                existing.mileage = mileage
                existing.notes = f"Auto-updated from LiveLink ({odometer_key})"
            # else: manual entry, don't overwrite
        else:
            # Create new odometer record
            odometer_record = OdometerRecord(
                vin=vin,
                date=record_date,
                mileage=mileage,
                source="livelink",
                notes=f"Auto-recorded from LiveLink ({odometer_key})",
            )
            self.db.add(odometer_record)
            logger.info(
                "Created odometer record for %s: %d from %s",
                vin[:8],
                mileage,
                odometer_key,
            )

    async def _upsert_latest_value(
        self,
        vin: str,
        param_key: str,
        value: float,
        timestamp: datetime,
        received_at: datetime,
    ) -> None:
        """Upsert a value into the latest values cache table."""
        # Use SQLite's INSERT OR REPLACE
        stmt = sqlite_insert(VehicleTelemetryLatest).values(
            vin=vin,
            param_key=param_key,
            value=value,
            timestamp=timestamp,
            received_at=received_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["vin", "param_key"],
            set_={
                "value": value,
                "timestamp": timestamp,
                "received_at": received_at,
            },
        )
        await self.db.execute(stmt)

    async def _should_store_historical(
        self, vin: str, param_key: str, interval_seconds: int
    ) -> bool:
        """Check if we should store a historical value based on storage interval.

        Returns True if no recent value exists or last value is older than interval.
        """
        result = await self.db.execute(
            select(VehicleTelemetry.timestamp)
            .where(VehicleTelemetry.vin == vin)
            .where(VehicleTelemetry.param_key == param_key)
            .order_by(VehicleTelemetry.timestamp.desc())
            .limit(1)
        )
        row = result.first()
        if not row:
            return True

        last_timestamp = row[0]
        if not last_timestamp:
            return True

        # Ensure both are timezone-aware for comparison
        now = datetime.now(UTC)
        if last_timestamp.tzinfo is None:
            last_timestamp = last_timestamp.replace(tzinfo=UTC)

        seconds_since_last = (now - last_timestamp).total_seconds()
        return seconds_since_last >= interval_seconds

    # =========================================================================
    # Query Methods
    # =========================================================================

    async def get_latest_values(self, vin: str) -> list[VehicleTelemetryLatest]:
        """Get all latest telemetry values for a vehicle."""
        result = await self.db.execute(
            select(VehicleTelemetryLatest)
            .where(VehicleTelemetryLatest.vin == vin)
            .order_by(VehicleTelemetryLatest.param_key)
        )
        return list(result.scalars().all())

    async def get_telemetry_range(
        self,
        vin: str,
        start: datetime,
        end: datetime,
        param_keys: list[str] | None = None,
        limit: int = 10000,
    ) -> list[VehicleTelemetry]:
        """Query historical telemetry for a time range."""
        query = (
            select(VehicleTelemetry)
            .where(VehicleTelemetry.vin == vin)
            .where(VehicleTelemetry.timestamp >= start)
            .where(VehicleTelemetry.timestamp <= end)
        )

        if param_keys:
            query = query.where(VehicleTelemetry.param_key.in_(param_keys))

        query = query.order_by(VehicleTelemetry.timestamp).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_telemetry_stats(
        self,
        vin: str,
        param_key: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, float | None]:
        """Get min/max/avg stats for a parameter in a time range."""
        result = await self.db.execute(
            select(
                func.min(VehicleTelemetry.value),
                func.max(VehicleTelemetry.value),
                func.avg(VehicleTelemetry.value),
                func.count(VehicleTelemetry.id),
            )
            .where(VehicleTelemetry.vin == vin)
            .where(VehicleTelemetry.param_key == param_key)
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
    # Retention / Cleanup
    # =========================================================================

    async def prune_old_telemetry(self, retention_days: int) -> int:
        """Delete telemetry older than retention period.

        Returns count of deleted rows.
        """
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        # Count first for logging
        count_result = await self.db.execute(
            select(func.count(VehicleTelemetry.id)).where(VehicleTelemetry.timestamp < cutoff)
        )
        count_row = count_result.first()
        to_delete = count_row[0] if count_row else 0

        if to_delete > 0:
            await self.db.execute(
                delete(VehicleTelemetry).where(VehicleTelemetry.timestamp < cutoff)
            )
            await self.db.commit()
            logger.info("Pruned %d telemetry records older than %d days", to_delete, retention_days)

        return to_delete

    async def get_telemetry_row_count(self) -> int:
        """Get total row count for health monitoring."""
        result = await self.db.execute(select(func.count(VehicleTelemetry.id)))
        row = result.first()
        return row[0] if row else 0

    # =========================================================================
    # Daily Aggregation
    # =========================================================================

    async def generate_daily_summary(self, date: datetime, vin: str | None = None) -> int:
        """Generate daily summary aggregates for a specific date.

        Args:
            date: The date to aggregate (uses midnight UTC)
            vin: Optional specific VIN (None = all vehicles)

        Returns:
            Number of summary records created/updated
        """
        # Normalize to midnight UTC
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        # Build query for raw telemetry
        query = (
            select(
                VehicleTelemetry.vin,
                VehicleTelemetry.param_key,
                func.min(VehicleTelemetry.value),
                func.max(VehicleTelemetry.value),
                func.avg(VehicleTelemetry.value),
                func.count(VehicleTelemetry.id),
            )
            .where(VehicleTelemetry.timestamp >= day_start)
            .where(VehicleTelemetry.timestamp < day_end)
            .group_by(VehicleTelemetry.vin, VehicleTelemetry.param_key)
        )

        if vin:
            query = query.where(VehicleTelemetry.vin == vin)

        result = await self.db.execute(query)
        rows = result.fetchall()

        count = 0
        for row in rows:
            stmt = sqlite_insert(TelemetryDailySummary).values(
                vin=row[0],
                param_key=row[1],
                date=day_start,
                min_value=row[2],
                max_value=row[3],
                avg_value=row[4],
                sample_count=row[5],
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["vin", "param_key", "date"],
                set_={
                    "min_value": row[2],
                    "max_value": row[3],
                    "avg_value": row[4],
                    "sample_count": row[5],
                },
            )
            await self.db.execute(stmt)
            count += 1

        await self.db.commit()
        return count

    # =========================================================================
    # Simple Value Storage (for route compatibility)
    # =========================================================================

    async def store_value(
        self,
        vin: str,
        device_id: str,
        param_key: str,
        value: float,
    ) -> bool:
        """Store a single telemetry value.

        Returns True if stored to historical table, False if skipped due to interval.
        Always updates the latest value cache.
        """
        timestamp = datetime.now(UTC)
        received_at = timestamp

        # Get parameter for storage interval check
        param = await self.get_parameter(param_key)

        # Always update latest value
        await self._upsert_latest_value(vin, param_key, value, timestamp, received_at)

        # Check storage interval
        if param and param.storage_interval_seconds > 0:
            should_store = await self._should_store_historical(
                vin, param_key, param.storage_interval_seconds
            )
            if not should_store:
                return False

        # Store to historical table
        try:
            telemetry = VehicleTelemetry(
                vin=vin,
                device_id=device_id,
                param_key=param_key,
                value=value,
                timestamp=timestamp,
                received_at=received_at,
            )
            self.db.add(telemetry)
            return True
        except IntegrityError:
            return False

    async def check_thresholds(
        self,
        vin: str,
        param_key: str,
        value: float,
    ) -> None:
        """Check if a value exceeds parameter thresholds and send notifications.

        Respects alert cooldown to prevent notification spam.
        """
        param = await self.get_parameter(param_key)
        if not param:
            return

        # Check if value is outside thresholds
        alert_type = None
        threshold_value = None

        if param.warning_max is not None and value > param.warning_max:
            alert_type = "max"
            threshold_value = param.warning_max
        elif param.warning_min is not None and value < param.warning_min:
            alert_type = "min"
            threshold_value = param.warning_min

        if not alert_type or threshold_value is None:
            return

        # Check cooldown - get last alert time from param metadata
        # For now, we'll skip cooldown logic and let the dispatcher handle it
        # The dispatcher already has a mechanism for this

        # Get vehicle name for notification
        from app.models.vehicle import Vehicle

        result = await self.db.execute(
            select(Vehicle.year, Vehicle.make, Vehicle.model).where(Vehicle.vin == vin)
        )
        row = result.first()
        if row:
            vehicle_name = f"{row[0]} {row[1]} {row[2]}"
        else:
            vehicle_name = f"Vehicle ({vin[:8]}...)"

        # Send notification
        from app.services.notifications.dispatcher import NotificationDispatcher

        dispatcher = NotificationDispatcher(self.db)
        await dispatcher.notify_livelink_threshold_alert(
            vehicle_name=vehicle_name,
            parameter_name=param.display_name or param_key,
            value=value,
            threshold_type=alert_type,
            threshold_value=threshold_value,
            unit=param.unit,
        )
