"""Give LiveLink parameters still on their auto name the readable one (O-T7, P2A-2).

A new row used to get its key title-cased ("Coolant Tmp", "Engine Rpm"), and
Torque's own PIDs only got their names at the next upload ("Kff1238"). This
renames the rows still on that auto name, or on no name, to the readable ones,
and moves KFF1207/KFF1208 off the shipped "(L/100 km)" names, which the upload
rule reads as names someone set. Any other name stays.

It also logs a WARNING for each Torque device on `mi` with TORQUE_ODOMETER as
its odometer: that total is always km, so its history may be stored 1.609x
high. It writes nothing for them; the repair tool does, once someone looks.

Not FATAL: a failed rename leaves today's names, and the next upload still
moves a row off its auto name.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Engine, bindparam, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

#: app/constants/param_names.py READABLE_PARAM_NAMES as of 139, frozen.
_READABLE: dict[str, str] = {
    "COOLANT_TMP": "Coolant temperature",
    "ENGINE_RPM": "Engine RPM",
    "ENGINE_LOAD": "Engine load",
    "INTAKE_PRESSURE": "Intake manifold pressure",
    "INTAKE_TEMP": "Intake air temperature",
    "TIMING_ADVANCE": "Timing advance",
    "MAF": "Mass air flow",
    "THROTTLE": "Throttle position",
    "RUN_TIME": "Engine run time",
    "FUEL": "Fuel level",
    "CONTROL_MODULE_VOLTAGE": "Control module voltage",
    "AMBIENT_TEMP": "Ambient air temperature",
    "OIL_TEMP": "Engine oil temperature",
    "SPEED": "Speed",
    "TORQUE_ODOMETER": "Odometer (Torque)",
}

#: The title case a new row of each got before, written out (str.title() output).
_TITLES_D2: dict[str, str] = {
    "COOLANT_TMP": "Coolant Tmp",
    "ENGINE_RPM": "Engine Rpm",
    "ENGINE_LOAD": "Engine Load",
    "INTAKE_PRESSURE": "Intake Pressure",
    "INTAKE_TEMP": "Intake Temp",
    "TIMING_ADVANCE": "Timing Advance",
    "MAF": "Maf",
    "THROTTLE": "Throttle",
    "RUN_TIME": "Run Time",
    "FUEL": "Fuel",
    "CONTROL_MODULE_VOLTAGE": "Control Module Voltage",
    "AMBIENT_TEMP": "Ambient Temp",
    "OIL_TEMP": "Oil Temp",
    "SPEED": "Speed",
    "TORQUE_ODOMETER": "Torque Odometer",
}

#: app/services/torque_pid_map.py TORQUE_PID_NAMES as of 139, with the TQ-L4 spelling.
_KFF_NAMES: dict[str, str] = {
    "KFF1201": "Instant economy (mpg)",
    "KFF1202": "Turbo boost",
    "KFF1203": "Instant economy (km/L)",
    "KFF1204": "Trip distance",
    "KFF1205": "Trip economy (mpg)",
    "KFF1206": "Trip economy (km/L)",
    "KFF1207": "Instant economy (L/100km)",
    "KFF1208": "Trip economy (L/100km)",
    "KFF1220": "Acceleration X",
    "KFF1221": "Acceleration Y",
    "KFF1222": "Acceleration Z",
    "KFF1223": "Acceleration total",
    "KFF1225": "Engine torque",
    "KFF1226": "Wheel horsepower",
    "KFF1238": "OBD adapter voltage",
    "KFF1239": "GPS accuracy",
    "KFF123A": "GPS satellites",
    "KFF1249": "Air-fuel ratio, measured",
    "KFF124D": "Air-fuel ratio, commanded",
    "KFF1269": "Volumetric efficiency",
    "KFF1271": "Trip fuel used",
}

#: str.title() capitalises after a digit, hence Kff123A, not Kff123a.
_TITLES_KFF: dict[str, str] = {
    "KFF1201": "Kff1201",
    "KFF1202": "Kff1202",
    "KFF1203": "Kff1203",
    "KFF1204": "Kff1204",
    "KFF1205": "Kff1205",
    "KFF1206": "Kff1206",
    "KFF1207": "Kff1207",
    "KFF1208": "Kff1208",
    "KFF1220": "Kff1220",
    "KFF1221": "Kff1221",
    "KFF1222": "Kff1222",
    "KFF1223": "Kff1223",
    "KFF1225": "Kff1225",
    "KFF1226": "Kff1226",
    "KFF1238": "Kff1238",
    "KFF1239": "Kff1239",
    "KFF123A": "Kff123A",
    "KFF1249": "Kff1249",
    "KFF124D": "Kff124D",
    "KFF1269": "Kff1269",
    "KFF1271": "Kff1271",
}

#: The names these two shipped with, before TQ-L4.
_SHIPPED: dict[str, str] = {
    "KFF1207": "Instant economy (L/100 km)",
    "KFF1208": "Trip economy (L/100 km)",
}

_TOOL = "backend/tools/repair_wican_odometer_unit.py"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    # hide_parameters: a failed statement's message leaves out its bound values.
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}", hide_parameters=True)
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}", hide_parameters=True)


def _old_names(key: str) -> list[str]:
    """The names a row of `key` can be on and still count as auto, minus the new one."""
    new = _READABLE.get(key) or _KFF_NAMES[key]
    olds = [(_TITLES_D2 | _TITLES_KFF)[key]]
    if key in _SHIPPED:
        olds.append(_SHIPPED[key])
    # SPEED's title is already its readable name, so only a missing one moves.
    return [n for n in olds if n != new]


def _rename(engine: Engine) -> None:
    """Rename every row of 139's keys still on no name, its title case or a shipped name."""
    if not inspect(engine).has_table("livelink_parameters"):
        logger.info("139: livelink_parameters missing; nothing to rename")
        return
    with_olds = text(
        "UPDATE livelink_parameters SET display_name = :new WHERE param_key = :k"
        " AND (display_name IS NULL OR display_name IN :olds)"
    ).bindparams(bindparam("olds", expanding=True))
    only_null = text(
        "UPDATE livelink_parameters SET display_name = :new"
        " WHERE param_key = :k AND display_name IS NULL"
    )
    renamed = 0
    with engine.begin() as conn:
        for key, new in (_READABLE | _KFF_NAMES).items():
            olds = _old_names(key)
            if olds:
                result = conn.execute(with_olds, {"new": new, "k": key, "olds": olds})
            else:
                result = conn.execute(only_null, {"new": new, "k": key})
            renamed += result.rowcount
    logger.info("139: renamed %d parameter(s) to their readable name", renamed)


def _warn_torque_miles(engine: Engine) -> None:
    """One WARNING per Torque device reading TORQUE_ODOMETER as miles (D1b). Writes nothing."""
    inspector = inspect(engine)
    if not inspector.has_table("livelink_devices"):
        logger.info("139: livelink_devices missing; no Torque odometer to check")
        return
    columns = {c["name"] for c in inspector.get_columns("livelink_devices")}
    if not {"kind", "odometer_unit", "odometer_param_key"} <= columns:
        logger.info("139: livelink_devices has no odometer columns; nothing to check")
        return
    with engine.connect() as conn:
        device_ids = conn.execute(
            text(
                "SELECT device_id FROM livelink_devices WHERE kind = 'torque'"
                " AND odometer_unit = 'mi' AND odometer_param_key = 'TORQUE_ODOMETER'"
                " ORDER BY device_id"
            )
        ).scalars()
        for device_id in device_ids:
            logger.warning(
                "139: Torque device %s reads TORQUE_ODOMETER as miles, but Torque sends it"
                " in km, so its odometer history may be 1.609x high. Check it with"
                " `%s --device-id %s --key TORQUE_ODOMETER --to km` (dry run by default)",
                device_id,
                _TOOL,
                device_id,
            )


def upgrade(engine: Engine | None = None) -> None:
    """Rename the auto-named rows and warn about Torque odometers on miles.

    Each part logs its own failure so the other, and the migrations after it,
    still run.
    """
    if engine is None:
        engine = _get_fallback_engine()
    try:
        _rename(engine)
    except (SQLAlchemyError, ValueError) as e:
        logger.error("139: parameter names not updated, they stay: %s", e, exc_info=True)
    try:
        _warn_torque_miles(engine)
    except (SQLAlchemyError, ValueError) as e:
        logger.error("139: Torque odometer check failed: %s", e, exc_info=True)


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 139 is forward-only.")


if __name__ == "__main__":
    upgrade()
