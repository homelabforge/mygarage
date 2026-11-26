"""Module-level helpers the TelemetryService facade and its mixins both call."""

import logging

from app.services.livelink_sources.base import StoragePolicy

logger = logging.getLogger(__name__)


class MaintenanceModeError(RuntimeError):
    """Raised when a telemetry write is attempted during maintenance mode.

    The upgrade procedure for the odometer repair tools needs a window in which
    no new reading lands: a single reading arriving mid-repair recreates the
    mixed-unit state the tools refuse to run against.

    This lives on the writers rather than only on the routes because two rounds
    of review found an entry point the route gate did not cover -- first the
    admin SD backfill route, then `POST /api/livelink/mqtt/restart`, which
    writes nothing itself but starts the MQTT subscriber. MQTT is not a route,
    the scheduler is not a route, and the next ingest path need not be one
    either. Enumerating entry points is a floor; this is the choke point they
    all pass through.
    """


def _refuse_if_in_maintenance(operation: str) -> None:
    """Raise if maintenance mode is on.

    Args:
        operation: Name of the write being attempted, for the log and message.

    Raises:
        MaintenanceModeError: If ``settings.maintenance_mode`` is set.
    """
    from app.config import settings

    if settings.maintenance_mode:
        logger.warning("Maintenance mode: refused %s", operation)
        raise MaintenanceModeError(
            f"{operation} refused: MyGarage is in maintenance mode and is not accepting telemetry."
        )


def _delegates_to_store_telemetry(policy: StoragePolicy) -> bool:
    """Whether `store_readings` hands this policy's batch to `store_telemetry`."""
    return policy.sync_odometer or policy.observe_movement
