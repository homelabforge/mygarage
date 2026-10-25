"""Pre-storage telemetry value validation.

Rejects physically impossible values and detects unreasonable rate-of-change.
Based on WiCAN Discussion #198 findings about partial ECU wakes producing garbage.
"""

import logging
from collections import OrderedDict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_telemetry import VehicleTelemetry

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

#: The last reading the rate check accepted, per (device, vehicle, key): the
#: baseline for the next one. Not the newest raw row, which a storage interval
#: thins to one every few minutes, so most frames skipped the check (wave B
#: review M-1). In memory: a restart loses it, and the check falls back to the
#: device's newest raw row. Least recently used goes first past the cap, which
#: is far more keys than a homelab's devices send.
ACCEPTED_READINGS_MAX = 4096
_ACCEPTED: OrderedDict[tuple[str, str, str], tuple[float, datetime]] = OrderedDict()


def remember_accepted(
    device_id: str, vin: str, param_key: str, value: float, sample_at: datetime
) -> None:
    """Make an accepted reading the device's baseline, unless a newer one already is.

    A replay landing after live frames isn't the device's last reading.
    """
    key = (device_id, vin, param_key)
    sample = sample_at.replace(tzinfo=None) if sample_at.tzinfo is not None else sample_at
    held = _ACCEPTED.get(key)
    if held is None or sample >= held[1]:
        _ACCEPTED[key] = (value, sample)
    _ACCEPTED.move_to_end(key)
    while len(_ACCEPTED) > ACCEPTED_READINGS_MAX:
        _ACCEPTED.popitem(last=False)


def forget_accepted_readings() -> None:
    """Drop every baseline, as a restart does. For tests."""
    _ACCEPTED.clear()


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
        *,
        device_id: str,
        sample_at: datetime,
    ) -> tuple[bool, str | None]:
        """Check if a value's rate of change from the previous value is reasonable.

        Measured between the two readings' own timestamps, not from now: a
        replayed reading an hour old isn't a jump from what the vehicle said
        eight seconds ago. A sample at or before the latest one isn't the next
        reading, so it isn't rate-checked at all.

        The previous value is this device's own last accepted reading
        (`remember_accepted`), not the vehicle's latest: two devices on one car
        would rate-check each other (B6-6), and the latest table has no device
        column. After a restart, until the device's next reading, it's the
        device's newest stored row.

        Args:
            vin: Vehicle VIN
            param_key: Parameter key
            param_class: Parameter class
            value: New value
            device_id: The device the reading came from
            sample_at: The reading's own timestamp

        Returns:
            (True, None) if valid or check not applicable, (False, reason) if rejected
        """
        if not param_class or param_class not in RATE_OF_CHANGE_LIMITS:
            return True, None

        held = _ACCEPTED.get((device_id, vin, param_key))
        if held is not None:
            prev_value, prev_timestamp = held
        else:
            # A seek on the dedup index, newest first.
            result = await self.db.execute(
                select(VehicleTelemetry)
                .where(
                    VehicleTelemetry.device_id == device_id,
                    VehicleTelemetry.param_key == param_key,
                    VehicleTelemetry.vin == vin,
                )
                .order_by(VehicleTelemetry.timestamp.desc())
                .limit(1)
            )
            latest = result.scalar_one_or_none()
            if not latest:
                return True, None  # No previous value to compare
            prev_value, prev_timestamp = latest.value, latest.timestamp

        sample = sample_at.replace(tzinfo=None) if sample_at.tzinfo is not None else sample_at
        if prev_timestamp.tzinfo is not None:
            prev_timestamp = prev_timestamp.replace(tzinfo=None)
        time_delta = (sample - prev_timestamp).total_seconds()

        if time_delta <= 0 or time_delta > RATE_CHECK_MAX_AGE_SECONDS:
            return True, None  # Not the next reading, or too far apart to compare

        # Calculate rate of change
        value_delta = abs(value - prev_value)
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
        *,
        device_id: str,
        sample_at: datetime,
    ) -> tuple[dict[str, float | int | str | None], list[dict[str, object]]]:
        """Validate a batch of telemetry values.

        Args:
            vin: Vehicle VIN
            autopid_data: Raw parameter values
            parameters_cache: Cached parameter definitions (from get_all_parameters)
            device_id: The device the batch came from, for the rate check
            sample_at: The batch's own timestamp, for the rate check

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
                device_id=device_id,
                sample_at=sample_at,
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
            if param_class in RATE_OF_CHANGE_LIMITS:
                remember_accepted(device_id, vin, param_key, float(value), sample_at)

        if rejected:
            logger.warning(
                "Rejected %d/%d telemetry values for VIN %s: %s",
                len(rejected),
                len(autopid_data),
                vin,
                ", ".join(f"{r['param_key']}={r['value']} ({r['reason']})" for r in rejected),
            )

        return valid_data, rejected
