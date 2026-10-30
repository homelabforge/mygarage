"""Readable names for the shared canonical LiveLink keys (O-T7).

A new row used to get its key title-cased ("Coolant Tmp", "Engine Rpm"). These
are what it gets now, WiCAN and Torque alike. English on purpose: the backend
isn't translated, and a name someone set in the UI always wins.

Torque's own KFF names stay in `app/services/torque_pid_map.py`, since only
Torque sends those keys. Migration 139 holds a frozen copy of this table. A
row already on an older name from here reads as one someone set, so renaming
an entry later needs its own migration.
"""

READABLE_PARAM_NAMES: dict[str, str] = {
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
