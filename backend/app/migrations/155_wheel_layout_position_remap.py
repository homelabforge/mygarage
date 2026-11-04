"""Move existing two-wheelers onto F/R and pin four on no-wheel types with data (#272).

Only vehicles following their type (no stored `wheel_layout`) are touched.

Bikes: per axle, tire rows and brake rows each on their own, an axle that used
exactly one code moves to F or R and its pending low-tread reminders get
retitled. An axle with two codes is left for the user (D3). An F already next
to an FL counts as two, so nothing collides on uq_tires_vin_position.

No-wheel types (Boat and friends) with any tire or brake row get pinned to
`four`, so their tabs don't vanish on upgrade (D6).

FATAL, and `upgrade(conn)` so the rewrite and the stamp commit together. The
type lists are frozen here on purpose, not read from app.constants.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, bindparam, inspect, text

FATAL = True

logger = logging.getLogger(__name__)

_TWO_WHEEL_TYPES = ("Motorcycle", "Bicycle", "EBike")
_NO_WHEEL_TYPES = ("Boat", "Snowmobile", "Generator", "SmallEngine", "Attachment")

# Target code and the two-corner codes it replaces, per axle.
_AXLES = (("F", ("FL", "FR")), ("R", ("RL", "RR")))

_TIRE_TABLES = ("tires", "tire_mount_periods", "tire_readings")
_BRAKE_TABLES = ("brake_jobs", "brake_measurements", "brake_reminder_marks")
# Any of these on a no-wheel type means its tabs have something to show.
_DATA_TABLES = ("tires", "brake_axles", *_BRAKE_TABLES)

_LOW_TREAD_SOURCE = "low_tread"


def _vin_filter(table: str) -> str:
    """WHERE fragment tying a family table's rows to `:vin`."""
    # Mount periods have no vin of their own, so they go through their tire.
    if table == "tire_mount_periods":
        return "tire_id IN (SELECT id FROM tires WHERE vin = :vin)"
    return "vin = :vin"


def _pin_no_wheel_types(conn: Connection, tables: set[str]) -> int:
    """Pin `four` on a no-wheel type that already has tire or brake rows."""
    present = [t for t in _DATA_TABLES if t in tables]
    if not present:
        return 0
    has_data = " OR ".join(
        f"EXISTS (SELECT 1 FROM {t} WHERE {t}.vin = vehicles.vin)" for t in present
    )
    stmt = text(
        "UPDATE vehicles SET wheel_layout = 'four'"
        " WHERE wheel_layout IS NULL AND vehicle_type IN :types"
        f" AND ({has_data})"
    ).bindparams(bindparam("types", expanding=True))
    return conn.execute(stmt, {"types": list(_NO_WHEEL_TYPES)}).rowcount


def _codes_used(conn: Connection, vin: str, family: list[str], codes: tuple[str, ...]) -> set[str]:
    """Which of `codes` any of the family's tables uses for this vin."""
    used: set[str] = set()
    for table in family:
        stmt = text(
            f"SELECT DISTINCT position FROM {table}"
            f" WHERE {_vin_filter(table)} AND position IN :codes"
        ).bindparams(bindparam("codes", expanding=True))
        used.update(conn.execute(stmt, {"vin": vin, "codes": list(codes)}).scalars())
    return used


def _retitle_low_tread(conn: Connection, vin: str, old: str, new: str) -> int:
    """Give this vin's pending low-tread reminders at `old` the new corner."""
    # The tire is the scope: the composite FK keeps a reminder's vin equal to
    # its tire's, and one whose tire was deleted is history and stays put.
    return conn.execute(
        text(
            "UPDATE vehicle_reminders SET title = :new_title"
            " WHERE source = :source AND status = 'pending' AND title = :old_title"
            " AND tire_id IN (SELECT id FROM tires WHERE vin = :vin)"
        ),
        {
            "vin": vin,
            "source": _LOW_TREAD_SOURCE,
            "old_title": f"Tire tread low ({old})",
            "new_title": f"Tire tread low ({new})",
        },
    ).rowcount


def _remap_family(conn: Connection, vin: str, family: list[str], retitle: bool) -> int:
    """Move each axle that used exactly one code to F/R. Returns rows moved."""
    moved = 0
    for target, corners in _AXLES:
        used = _codes_used(conn, vin, family, (target, *corners))
        # Only the target there already moves F onto F, which is harmless.
        if len(used) != 1:
            continue
        (old,) = used
        for table in family:
            moved += conn.execute(
                text(
                    f"UPDATE {table} SET position = :new"
                    f" WHERE {_vin_filter(table)} AND position = :old"
                ),
                {"vin": vin, "old": old, "new": target},
            ).rowcount
        if retitle:
            _retitle_low_tread(conn, vin, old, target)
    return moved


def _remap_vehicle(conn: Connection, vin: str, tables: set[str]) -> int:
    """Remap one two-wheeler's tire rows and brake rows, each family on its own."""
    tire_family = [t for t in _TIRE_TABLES if t in tables]
    brake_family = [t for t in _BRAKE_TABLES if t in tables]
    retitle = "vehicle_reminders" in tables
    moved = _remap_family(conn, vin, tire_family, retitle) if tire_family else 0
    if brake_family:
        moved += _remap_family(conn, vin, brake_family, retitle=False)
    return moved


def upgrade(conn: Connection) -> None:
    """Pin the no-wheel types with data, then remap the two-wheelers, on the runner's connection."""
    tables = set(inspect(conn).get_table_names())
    if "vehicles" not in tables:
        logger.info("155: vehicles missing; nothing to do")
        return

    pinned = _pin_no_wheel_types(conn, tables)

    bikes = conn.execute(
        text(
            "SELECT vin FROM vehicles WHERE wheel_layout IS NULL AND vehicle_type IN :types"
            " ORDER BY vin"
        ).bindparams(bindparam("types", expanding=True)),
        {"types": list(_TWO_WHEEL_TYPES)},
    ).scalars()
    moved = 0
    for vin in list(bikes):
        moved += _remap_vehicle(conn, vin, tables)

    logger.info(
        "155: pinned %d no-wheel vehicle(s) to four, moved %d two-wheeler row(s) to F/R",
        pinned,
        moved,
    )


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 155 is forward-only.")
