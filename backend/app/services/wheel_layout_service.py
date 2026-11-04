"""Which corners a live vehicle has, for the tire and brake writers (#272).

Only NEW placements are held to the layout. A tire or brake row already
sitting off it (the type changed, or the user picked another layout) stays
listed, editable and movable, so nobody's data gets stranded.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.wheel_layouts import WheelLayout, default_wheel_layout, resolve_wheel_layout
from app.models.vehicle import Vehicle
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


async def vehicle_wheel_layout(db: AsyncSession, vin: str) -> WheelLayout:
    """The layout this vehicle has: its stored choice, or its type's default.

    Not a gate. Every caller has already passed the vehicle's access check, so
    this only reads two columns of a row the caller may see.
    """
    row = (
        await db.execute(
            select(Vehicle.wheel_layout, Vehicle.vehicle_type).where(Vehicle.vin == vin)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return resolve_wheel_layout(row.wheel_layout, row.vehicle_type, vin=vin)


def refuse_off_layout(
    layout: WheelLayout, positions: Iterable[str], kind: Literal["tire", "brake"]
) -> None:
    """422 on the first position the layout doesn't have, before anything is written."""
    allowed: tuple[str, ...] = layout.tire_positions if kind == "tire" else layout.brake_positions
    for position in positions:
        if position not in allowed:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{position} isn't a {kind} position on this vehicle's wheel layout "
                    f"({layout.id})."
                ),
            )


async def keep_wheel_tabs(db: AsyncSession, vin: str) -> None:
    """Pin `four` on an automatic no-wheel vehicle that an import just gave tires or brakes.

    Same rule as migration 155 (D7): a Boat restored with tire history would
    otherwise hide the tab holding it. The import route only needs a
    write-share, and that's fine here: this is derived visibility state, like
    `main_photo` in photos.py. Picking a layout on purpose (the vehicle PUT)
    stays owner-only. Flushed because the session doesn't autoflush and the
    brake reminder pass reloads the vehicle with `populate_existing`.
    """
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.vin == vin))).scalar_one_or_none()
    if vehicle is None or vehicle.wheel_layout is not None:
        return
    if default_wheel_layout(vehicle.vehicle_type) != "none":
        return
    vehicle.wheel_layout = "four"
    await db.flush()
    logger.info(
        "Pinned wheel layout four on %s: an import brought tires or brakes",
        sanitize_for_log(vin),
    )
