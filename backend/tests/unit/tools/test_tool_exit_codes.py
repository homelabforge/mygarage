"""A dry run that found unconvertible data must not report success.

Both converters refuse a device whose odometer history mixes miles and
kilometres, because neither converting nor skipping is safe. They signal that
refusal with exit 2, and the upgrade note tells operators to run each tool as a
dry run first.

`normalize_telemetry_odometer_units.py` returned 0 from its dry-run branch
regardless, so a script gating `--apply` on the dry run's exit status would
greenlight the apply the dry run had just refused.
`fix_session_odometer_units.py` already returns `2 if mixed_devices else 0`
there; this pins both, so the correct one cannot regress to match the wrong one.
"""

import sqlite3

import pytest

_MIXED = (1000.0, 1609.0)  # ratio 1.609: a units discontinuity, inside [1.55, 1.67]


def _seed(db_path: str) -> None:
    """Two 'mi' devices: one with mixed history, one plainly convertible.

    Both are needed. With only the mixed device the plan is empty and the tool
    returns through its `if not plan` branch, which was already correct. The
    convertible device is what carries execution into the dry-run branch that
    was not.
    """
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE livelink_devices (
            device_id TEXT, vin TEXT, odometer_unit TEXT, kind TEXT);
        CREATE TABLE vehicle_telemetry (
            vin TEXT, device_id TEXT, param_key TEXT, value REAL, timestamp TEXT);
        CREATE TABLE vehicle_telemetry_latest (vin TEXT, param_key TEXT, value REAL);
        CREATE TABLE odometer_records (vin TEXT, date TEXT, odometer_km REAL);
        CREATE TABLE drive_sessions (
            device_id TEXT, started_at TEXT, start_odometer REAL,
            end_odometer REAL, distance_km REAL);
    """)
    conn.executemany(
        "INSERT INTO livelink_devices VALUES (?,?,?,?)",
        [("devmixed", "VINMIXED", "mi", "wican"), ("devplain", "VINPLAIN", "mi", "wican")],
    )
    conn.executemany(
        "INSERT INTO vehicle_telemetry VALUES (?,?,?,?,?)",
        [
            ("VINMIXED", "devmixed", "ODOMETER", _MIXED[0], "2026-09-01 10:00:00"),
            ("VINMIXED", "devmixed", "ODOMETER", _MIXED[1], "2026-09-01 10:01:00"),
            ("VINPLAIN", "devplain", "ODOMETER", 1000.0, "2026-09-01 10:00:00"),
            ("VINPLAIN", "devplain", "ODOMETER", 1001.0, "2026-09-01 10:01:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO vehicle_telemetry_latest VALUES (?,?,?)",
        [("VINMIXED", "ODOMETER", _MIXED[1]), ("VINPLAIN", "ODOMETER", 1001.0)],
    )
    # devplain's km records tower over its stored miles by the miles factor,
    # which is what marks it as still needing conversion.
    conn.executemany(
        "INSERT INTO odometer_records VALUES (?,?,?)",
        [("VINPLAIN", "2026-09-01", 1610.0), ("VINMIXED", "2026-09-01", 1610.0)],
    )
    conn.executemany(
        "INSERT INTO drive_sessions VALUES (?,?,?,?,?)",
        [
            ("devmixed", "2026-09-01 10:00:00", _MIXED[0], _MIXED[0], 0.0),
            ("devmixed", "2026-09-01 11:00:00", _MIXED[1], _MIXED[1], 0.0),
            ("devplain", "2026-09-01 10:00:00", 1000.0, 1001.0, 1.0),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def seeded_db(tmp_path):
    path = tmp_path / "mygarage.db"
    _seed(str(path))
    return str(path)


@pytest.mark.parametrize(
    "module_name",
    [
        "tools.normalize_telemetry_odometer_units",
        "tools.fix_session_odometer_units",
    ],
)
def test_dry_run_exits_2_when_it_refused_a_mixed_device(module_name, seeded_db, monkeypatch):
    """The refusal must reach the caller's exit status, not only the console."""
    import importlib

    module = importlib.import_module(module_name)
    monkeypatch.setattr("sys.argv", [module_name, "--db", seeded_db])

    assert module.main() == 2, (
        f"{module_name} reported success from a dry run that refused a mixed-unit device"
    )


@pytest.mark.parametrize(
    "module_name",
    [
        "tools.normalize_telemetry_odometer_units",
        "tools.fix_session_odometer_units",
    ],
)
def test_dry_run_exits_0_when_nothing_was_refused(module_name, tmp_path, monkeypatch):
    """The complement, so exit 2 means 'refused' rather than 'ran'."""
    import importlib
    import sqlite3 as s3

    path = str(tmp_path / "clean.db")
    _seed(path)
    # Remove the mixed device entirely; the convertible one remains.
    conn = s3.connect(path)
    for table in ("livelink_devices", "vehicle_telemetry", "drive_sessions"):
        conn.execute(f"DELETE FROM {table} WHERE device_id = 'devmixed'")
    conn.commit()
    conn.close()

    module = importlib.import_module(module_name)
    monkeypatch.setattr("sys.argv", [module_name, "--db", path])

    assert module.main() == 0
