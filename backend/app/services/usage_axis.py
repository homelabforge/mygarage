"""Which reading a tire's figures run on: the odometer or the hour meter (#217).

Storage stays parallel (odometer columns and hour columns side by side). The
rules don't: every tire history rule and every distance, interval and wear
function reads its bounds through a `UsageAxis`, defaulting to `DISTANCE`.
Pure, no session.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal

from app.models.tire import TireMountPeriod, TireReading
from app.utils.hours_formatting import format_hours
from app.utils.hours_tolerance import hours_above, hours_below
from app.utils.odometer_tolerance import odometer_above, odometer_below
from app.utils.unit_adapters import ADAPTERS, UnitAdapter
from app.utils.usage_tracking import tracks_distance, tracks_hours

UsageKind = Literal["distance", "hours"]
DistanceFormatter = Callable[[Decimal], str]


def distance_formatter(adapter: UnitAdapter) -> DistanceFormatter:
    """Render a canonical km odometer for a message, in `adapter`'s unit.

    One decimal place, trailing zeros dropped, rather than the adapter's own
    display precision: a message says one odometer is below another, and at
    whole miles 16,093.4 km and 16,094 km both print as 10,000 mi.
    """

    def render(value: Decimal) -> str:
        display = adapter.to_display(value)
        assert display is not None
        shown = display.quantize(Decimal("0.1")).normalize()
        return f"{shown:,f} {adapter.label}"

    return render


format_km: DistanceFormatter = distance_formatter(ADAPTERS["km"])


@dataclass(frozen=True)
class UsageAxis:
    """One usage axis, with the formatter its messages use for a figure."""

    kind: UsageKind
    fmt: Callable[[Decimal], str]

    def with_fmt(self, fmt: Callable[[Decimal], str]) -> UsageAxis:
        """The same axis, rendering figures with `fmt`."""
        return replace(self, fmt=fmt)

    @property
    def is_hours(self) -> bool:
        """Whether this is the hour meter."""
        return self.kind == "hours"

    def mounted(self, period: TireMountPeriod) -> Decimal | None:
        """Where the period starts on this axis."""
        return period.mounted_hours if self.is_hours else period.mounted_odometer_km

    def dismounted(self, period: TireMountPeriod) -> Decimal | None:
        """Where the period ends on this axis."""
        return period.dismounted_hours if self.is_hours else period.dismounted_odometer_km

    def reading(self, reading: TireReading) -> Decimal | None:
        """Where the vehicle stood on this axis when the reading was taken."""
        return reading.engine_hours if self.is_hours else reading.odometer_km

    def below(self, a: Decimal, b: Decimal) -> bool:
        """`a` below `b`, outside this axis's same-reading band."""
        return hours_below(a, b) if self.is_hours else odometer_below(a, b)

    def above(self, a: Decimal, b: Decimal) -> bool:
        """`a` above `b`, outside this axis's same-reading band."""
        return hours_above(a, b) if self.is_hours else odometer_above(a, b)

    @property
    def zero(self) -> Decimal:
        """A zero with the column's scale, so it serialises like any other figure."""
        return Decimal("0.0") if self.is_hours else Decimal("0.00")

    @property
    def meter(self) -> str:
        """The instrument, as a message names it."""
        return "hour meter" if self.is_hours else "odometer"

    @property
    def mount_reading(self) -> str:
        """The mount figure, as a message names it."""
        return "mount hours" if self.is_hours else "mount odometer"

    @property
    def quantity(self) -> str:
        """What a period covers on this axis, as a message names it."""
        return "hours" if self.is_hours else "distance"

    @property
    def reversed_code(self) -> str:
        """Fault code for a period whose bounds run backwards."""
        return "reversed_hours" if self.is_hours else "reversed_odometer"

    @property
    def overlapping_code(self) -> str:
        """Fault code for two periods claiming the same stretch."""
        return "overlapping_hours" if self.is_hours else "overlapping_odometer"

    @property
    def contradicts_code(self) -> str:
        """Fault code for a reading whose figure and date disagree with a period."""
        return "contradicts_reading_hours" if self.is_hours else "contradicts_reading"


DISTANCE = UsageAxis("distance", format_km)
HOURS = UsageAxis("hours", format_hours)


@dataclass(frozen=True)
class VehicleAxes:
    """The axes one vehicle's tires run on, for one request.

    `primary` is what distance and wear are computed on: distance whenever the
    vehicle tracks it (tread wears with distance rolled, and an hour meter also
    counts idling). `captured` is every axis it tracks, recorded and checked
    on each write.
    """

    primary: UsageAxis
    captured: tuple[UsageAxis, ...]

    def tracks(self, kind: UsageKind) -> bool:
        """Whether the vehicle records this axis."""
        return any(axis.kind == kind for axis in self.captured)

    @classmethod
    def for_vehicle(
        cls,
        usage_unit: str | None,
        secondary_usage_enabled: bool | None,
        format_distance: DistanceFormatter = format_km,
    ) -> VehicleAxes:
        """The axes for a vehicle's usage settings, distance first."""
        captured: list[UsageAxis] = []
        if tracks_distance(usage_unit, secondary_usage_enabled):
            captured.append(DISTANCE.with_fmt(format_distance))
        if tracks_hours(usage_unit, secondary_usage_enabled):
            captured.append(HOURS)
        return cls(primary=captured[0], captured=tuple(captured))

    @classmethod
    def distance_only(cls, format_distance: DistanceFormatter = format_km) -> VehicleAxes:
        """Just the odometer, for callers that don't know the vehicle."""
        axis = DISTANCE.with_fmt(format_distance)
        return cls(primary=axis, captured=(axis,))
