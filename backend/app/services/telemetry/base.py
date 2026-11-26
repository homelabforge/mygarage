"""What every TelemetryService mixin shares: the session, and stubs for each other."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_parameter import LiveLinkParameter


class TelemetryBase:
    """The session, plus typed stubs for methods one mixin calls on another.

    The stubs only exist so pyright can see them. TelemetryService lists this
    class last, so the real methods win.
    """

    db: AsyncSession

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    async def get_parameter(self, param_key: str) -> LiveLinkParameter | None:
        """Lives on TelemetryParametersMixin."""
        raise NotImplementedError

    def _is_odometer_param(self, param_key: str, declared: str | None = None) -> bool:
        """Lives on TelemetryOdometerMixin."""
        raise NotImplementedError
