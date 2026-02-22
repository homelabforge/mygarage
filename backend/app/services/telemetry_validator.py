"""Pre-storage telemetry value validation.

Rejects physically impossible values and detects unreasonable rate-of-change.
Based on WiCAN Discussion #198 findings about partial ECU wakes producing garbage.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_telemetry import VehicleTelemetryLatest

logger = logging.getLogger(__name__)

# Acceptable value ranges per parameter class
PARAM_CLASS_RANGES: dict[str, tuple[float, float]] = {
    "temperature": (-50.0, 250.0),
    "speed": (0.0, 350.0),
    "frequency": (0.0, 15000.0),  # RPM
    "percentage": (0.0, 100.0),  # throttle, fuel level, load
    "power_factor": (0.0, 100.0),  # throttle position
    "voltage": (0.0, 500.0),
    "battery": (0.0, 500.0),
    "pressure": (0.0, 10000.0),  # kPa
    "distance": (0.0, 2000000.0),  # km
}

# Max allowed value change per second per parameter class
RATE_OF_CHANGE_LIMITS: dict[str, float] = {
    "temperature": 5.0,  # degrees C per second
    "speed": 15.0,  # km/h per second (~1.5g)
    "frequency": 2000.0,  # RPM per second
    "percentage": 50.0,  # per second
    "power_factor": 50.0,  # per second
    "voltage": 2.0,  # volts per second
    "battery": 2.0,  # volts per second
    "pressure": 500.0,  # kPa per second
}

# Max time gap (seconds) to consider for rate-of-change check.
# If previous value is older than this, skip the check (likely a new session).
RATE_CHECK_MAX_AGE_SECONDS = 120.0


class TelemetryValidator:
    """Validates telemetry values before storage.

    Checks against per-class ranges and rate-of-change limits.
    Unknown parameter classes bypass all validation.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize with database session for rate-of-change lookups."""
        self.db = db

    def validate_range(
        self,
        param_class: str | None,
        value: float,
    ) -> tuple[bool, str | None]:
        """Check if a value is within the acceptable range for its class.

        Args:
            param_class: The parameter class (e.g., "temperature", "speed")
            value: The value to validate

        Returns:
            (True, None) if valid, (False, reason) if rejected
        """
        if not param_class or param_class not in PARAM_CLASS_RANGES:
            return True, None

        min_val, max_val = PARAM_CLASS_RANGES[param_class]
        if value < min_val or value > max_val:
            return False, (f"value {value} outside {param_class} range [{min_val}, {max_val}]")

        return True, None

    async def validate_rate_of_change(
        self,
        vin: str,
        param_key: str,
        param_class: str | None,
        value: float,
    ) -> tuple[bool, str | None]:
        """Check if a value's rate of change from the previous value is reasonable.

        Args:
            vin: Vehicle VIN
            param_key: Parameter key
            param_class: Parameter class
            value: New value

        Returns:
            (True, None) if valid or check not applicable, (False, reason) if rejected
        """
        if not param_class or param_class not in RATE_OF_CHANGE_LIMITS:
            return True, None

        # Get the most recent value for this parameter
        result = await self.db.execute(
            select(VehicleTelemetryLatest).where(
                VehicleTelemetryLatest.vin == vin,
                VehicleTelemetryLatest.param_key == param_key,
            )
        )
        latest = result.scalar_one_or_none()
        if not latest:
            return True, None  # No previous value to compare

        # Calculate time delta
        now = datetime.now(UTC)
        prev_timestamp = latest.timestamp
        if prev_timestamp.tzinfo is None:
            prev_timestamp = prev_timestamp.replace(tzinfo=UTC)
        time_delta = (now - prev_timestamp).total_seconds()

        if time_delta <= 0 or time_delta > RATE_CHECK_MAX_AGE_SECONDS:
            return True, None  # Stale data or same timestamp, skip check

        # Calculate rate of change
        value_delta = abs(value - latest.value)
        rate = value_delta / time_delta
        max_rate = RATE_OF_CHANGE_LIMITS[param_class]

        if rate > max_rate:
            return False, (
                f"rate of change {rate:.1f}/s exceeds {param_class} limit "
                f"{max_rate}/s (delta={value_delta:.1f} in {time_delta:.1f}s)"
            )

        return True, None

    async def validate_batch(
        self,
        vin: str,
        autopid_data: dict[str, float | int | str | None],
        parameters_cache: dict[str, object],
    ) -> tuple[dict[str, float | int | str | None], list[dict[str, object]]]:
        """Validate a batch of telemetry values.

        Args:
            vin: Vehicle VIN
            autopid_data: Raw parameter values
            parameters_cache: Cached parameter definitions (from get_all_parameters)

        Returns:
            Tuple of (valid_data, rejected_list) where rejected_list contains
            dicts with param_key, value, and reason.
        """
        valid_data: dict[str, float | int | str | None] = {}
        rejected: list[dict[str, object]] = []

        for param_key, value in autopid_data.items():
            # Pass through non-numeric values (None, strings like DTCs)
            if value is None or isinstance(value, str):
                valid_data[param_key] = value
                continue

            # Get parameter class from cache
            param = parameters_cache.get(param_key)
            param_class = getattr(param, "param_class", None) if param else None

            # Range check
            is_valid, reason = self.validate_range(param_class, float(value))
            if not is_valid:
                rejected.append(
                    {
                        "param_key": param_key,
                        "value": value,
                        "reason": reason,
                    }
                )
                continue

            # Rate-of-change check
            is_valid, reason = await self.validate_rate_of_change(
                vin,
                param_key,
                param_class,
                float(value),
            )
            if not is_valid:
                rejected.append(
                    {
                        "param_key": param_key,
                        "value": value,
                        "reason": reason,
                    }
                )
                continue

            valid_data[param_key] = value

        if rejected:
            logger.warning(
                "Rejected %d/%d telemetry values for VIN %s: %s",
                len(rejected),
                len(autopid_data),
                vin,
                ", ".join(f"{r['param_key']}={r['value']} ({r['reason']})" for r in rejected),
            )

        return valid_data, rejected
