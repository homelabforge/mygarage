"""Wheel layouts (#272): which tire and brake corners a vehicle has.

A vehicle stores a layout id, or NULL for "whatever its type usually has".
The position codes live here, not in the schemas, because the schemas import
this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, TypeIs, get_args

from app.utils.lenient_vocab import warn_once
from app.utils.logging_utils import sanitize_for_log

WheelLayoutId = Literal["four", "two", "trike_2f1r", "trike_1f2r", "dually", "none"]
#: F and R are a two-wheeler's (or a trike's single) wheel. FL never means "front".
TirePosition = Literal["FL", "FR", "RL", "RR", "F", "R", "RLO", "RLI", "RRI", "RRO", "SPARE"]
#: A dually's inner and outer rear tires share one brake, so no RLO-style codes here.
BrakePosition = Literal["FL", "FR", "RL", "RR", "F", "R"]

_WHEEL_LAYOUT_IDS: frozenset[str] = frozenset(get_args(WheelLayoutId))


@dataclass(frozen=True)
class WheelLayout:
    """One layout's corners, in the order the UI lists them."""

    id: WheelLayoutId
    tire_positions: tuple[TirePosition, ...]
    brake_positions: tuple[BrakePosition, ...]
    rotates: bool


# Rotation patterns only know four corners, so only `four` rotates.
WHEEL_LAYOUTS: Mapping[WheelLayoutId, WheelLayout] = MappingProxyType(
    {
        "four": WheelLayout(
            "four", ("FL", "FR", "RL", "RR", "SPARE"), ("FL", "FR", "RL", "RR"), rotates=True
        ),
        "two": WheelLayout("two", ("F", "R"), ("F", "R"), rotates=False),
        "trike_2f1r": WheelLayout(
            "trike_2f1r", ("FL", "FR", "R"), ("FL", "FR", "R"), rotates=False
        ),
        "trike_1f2r": WheelLayout(
            "trike_1f2r", ("F", "RL", "RR"), ("F", "RL", "RR"), rotates=False
        ),
        "dually": WheelLayout(
            "dually",
            ("FL", "FR", "RLO", "RLI", "RRI", "RRO", "SPARE"),
            ("FL", "FR", "RL", "RR"),
            rotates=False,
        ),
        "none": WheelLayout("none", (), (), rotates=False),
    }
)

BRAKE_AXLE_OF: Mapping[BrakePosition, Literal["front", "rear"]] = MappingProxyType(
    {"FL": "front", "FR": "front", "F": "front", "RL": "rear", "RR": "rear", "R": "rear"}
)

_TWO_WHEEL_TYPES: frozenset[str] = frozenset({"Motorcycle", "Bicycle", "EBike"})
_NO_WHEEL_TYPES: frozenset[str] = frozenset(
    {"Boat", "Snowmobile", "Generator", "SmallEngine", "Attachment"}
)


def default_wheel_layout(vehicle_type: str | None) -> WheelLayoutId:
    """The layout a vehicle type gets when none is stored. Unknown or NULL is `four`."""
    if vehicle_type in _TWO_WHEEL_TYPES:
        return "two"
    if vehicle_type in _NO_WHEEL_TYPES:
        return "none"
    return "four"


def _is_layout_id(value: str) -> TypeIs[WheelLayoutId]:
    return value in _WHEEL_LAYOUT_IDS


def resolve_wheel_layout(stored: str | None, vehicle_type: str | None) -> WheelLayout:
    """The stored layout, or the type's default when it's NULL or one we don't know.

    A restore or a downgrade can leave a layout this build doesn't know. That
    reads as the default and gets logged once, rather than 500ing the vehicle.
    """
    if stored is not None and _is_layout_id(stored):
        return WHEEL_LAYOUTS[stored]
    fallback = default_wheel_layout(vehicle_type)
    if stored is not None:
        warn_once(
            "Vehicle",
            "wheel_layout",
            stored,
            fallback,
            lambda: f"vehicle_type={sanitize_for_log(vehicle_type)}",
        )
    return WHEEL_LAYOUTS[fallback]
