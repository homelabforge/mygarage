"""Parameter registry half of TelemetryService: lookup, auto-register, naming."""

import logging
from collections.abc import Mapping

from sqlalchemy import select

from app.constants.param_names import READABLE_PARAM_NAMES
from app.models.livelink_parameter import DISPLAY_NAME_MAX_LENGTH, LiveLinkParameter
from app.services.telemetry.base import TelemetryBase
from app.services.telemetry.helpers import _refuse_if_in_maintenance
from app.utils.autopid_normalizer import canonical_param_key, infer_param_class

logger = logging.getLogger(__name__)


def _title_case(param_key: str) -> str:
    """The name a new row got before the readable table, and still gets for any other key."""
    return param_key.replace("_", " ").title()


class TelemetryParametersMixin(TelemetryBase):
    """Parameter definitions: get, register, classify and name them."""

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
    ) -> LiveLinkParameter:
        """Get or create a parameter definition.

        Wrapper for auto_register_parameter for route compatibility.
        """
        return await self.auto_register_parameter(param_key, unit, param_class, display_name)

    async def fill_declared_units(self, units: Mapping[str, str]) -> None:
        """Give rows that exist and have no unit the one a source declared.

        Creates nothing: a parameter is registered when its first value arrives,
        with the unit app/services/declared_units.py kept for it.
        """
        _refuse_if_in_maintenance("fill_declared_units")
        rows = await self.db.execute(
            select(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(list(units)))
        )
        for param in rows.scalars():
            if not param.unit:
                param.unit = units[param.param_key]

    async def auto_register_parameter(
        self,
        param_key: str,
        unit: str | None = None,
        param_class: str | None = None,
        display_name: str | None = None,
    ) -> LiveLinkParameter:
        """Auto-register a new parameter from WiCAN config block.

        Returns existing parameter if already registered.

        A source's `display_name` names a new row, and an existing one still on
        its auto name; a name someone set stays. It is cut to the column's
        width: PostgreSQL refuses a longer one where SQLite stores it (TQ-L2).
        With no source name, a shared key falls back to its readable one
        (`_format_display_name` for a new row, `_adopt_readable_name` for an
        existing one).
        """
        if display_name is not None:
            display_name = display_name[:DISPLAY_NAME_MAX_LENGTH]
        # Explicit config class always wins; otherwise fall back to the
        # conservative catalog inference so MQTT-discovered params (which
        # arrive with an empty config block) still get validator range/rate
        # coverage. NOTE: the catalog matches on short substrings (e.g.
        # PRES, TEMP) and a future PID could false-positive (e.g. a
        # hypothetical COMPRESSOR key contains PRES), so extend
        # `_PARAM_CLASS_PATTERNS` conservatively.
        resolved_class = param_class or infer_param_class(param_key)

        existing = await self.get_parameter(param_key)
        if existing:
            # Update metadata if provided and not already set
            if unit and not existing.unit:
                existing.unit = unit
            self._adopt_readable_name(existing, display_name)
            if not existing.param_class and resolved_class:
                existing.param_class = resolved_class
                # Only recompute category when it's unset or still the
                # "other" default: category is user-editable in the admin
                # UI, and a hand-tuned value must survive the class backfill.
                if not existing.category or existing.category == "other":
                    existing.category = self._classify_param(resolved_class, param_key)
            return existing

        # Create new parameter
        category = self._classify_param(resolved_class, param_key)
        display_name = display_name or self._format_display_name(param_key)

        # Defaults for brand-new rows only; existing rows keep whatever a user
        # has set.
        #
        # Every new parameter starts on the dashboard. The Live tab has always
        # drawn every reading, and hiding one is now an explicit per-reading
        # switch in the integrations settings, not a class default nobody chose
        # (migration 114 reset the rows this used to decide).
        #
        # The class list governs only archive_only, which keeps a parameter out
        # of the chart picker. It predates config-driven sources, when every
        # class came from a WiCAN config block, so a new source whose headline
        # reading has a new class is unchartable by default. That is what
        # happened to the Mopeka preset until `propane` was added.
        chartable = resolved_class in (
            "speed",
            "frequency",
            "temperature",
            "voltage",
            "battery",
            "propane",
        )
        show_on_dashboard = True
        archive_only = not chartable

        param = LiveLinkParameter(
            param_key=param_key,
            display_name=display_name,
            unit=unit,
            param_class=resolved_class,
            category=category,
            show_on_dashboard=show_on_dashboard,
            archive_only=archive_only,
            storage_interval_seconds=0,  # Store all by default
        )
        self.db.add(param)
        await self.db.flush()

        logger.info("Auto-registered new parameter: %s", param_key)
        return param

    def _classify_param(self, param_class: str | None, param_key: str) -> str:
        """Classify a parameter into a category based on its class.

        WiCAN files every % reading under `percentage`, so that class goes by
        key instead: fuel, then state of charge or battery, else engine.
        """
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
        elif class_lower == "percentage":
            key = canonical_param_key(param_key)
            if "FUEL" in key:
                return "fuel"
            if "SOC" in key or "BATT" in key:
                return "electrical"
            return "engine"  # throttle, pedal, load
        else:
            return "other"

    @staticmethod
    def _format_display_name(param_key: str) -> str:
        """Format a parameter key into a display name: its readable one, else the title case."""
        return READABLE_PARAM_NAMES.get(param_key) or _title_case(param_key)

    @staticmethod
    def _adopt_readable_name(param: LiveLinkParameter, name: str | None = None) -> None:
        """Give a row still on its auto name `name`, or its key's readable name.

        Auto means no name, the old title case or the readable one; anything
        else is a name someone set and stays. One rule for every ingest path.
        """
        key: str = param.param_key
        current: str | None = param.display_name
        readable = READABLE_PARAM_NAMES.get(key)
        # WiCAN never names a reading and Torque only its KFF ones, so without
        # the fallback a row on "Coolant Tmp" would never move.
        name = name or readable
        # Skip a row already on it, so a frame doesn't dirty every row it carries.
        if name and current != name and current in (None, _title_case(key), readable):
            param.display_name = name
