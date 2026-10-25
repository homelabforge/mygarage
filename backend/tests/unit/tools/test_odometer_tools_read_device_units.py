"""The odometer repair tools resolve a key's unit the way live ingest does (T7, F2-3).

After T7 a bare `ODOMETER` reads km unless the device's R12 row says
otherwise. A tool that only knew the key rule would call every legacy-miles
device "already metric" and skip it. Both tools also run before the first boot
of a new version, when `livelink_device_units` doesn't exist and migration 133
hasn't recorded anything, so they read those devices the way 133 will.
"""

from __future__ import annotations

import importlib
import sqlite3

import pytest

_SCHEMA = """
    CREATE TABLE livelink_devices (
        device_id TEXT, vin TEXT, odometer_unit TEXT, kind TEXT,
        odometer_param_key TEXT, created_at TEXT);
    CREATE TABLE vehicle_telemetry (
        vin TEXT, device_id TEXT, param_key TEXT, value REAL, timestamp TEXT);
    CREATE TABLE vehicle_telemetry_latest (
        vin TEXT, param_key TEXT, value REAL, timestamp TEXT);
    CREATE TABLE odometer_records (vin TEXT, date TEXT, odometer_km REAL, source TEXT);
"""

_UNITS = """
    CREATE TABLE livelink_device_units (
        device_id TEXT, param_key TEXT, unit TEXT, param_class TEXT, source TEXT);
"""


def _seed(path: str, *, with_units: bool, legacy: bool, booted: bool = True) -> None:
    """One unit-less WiCAN whose bare ODOMETER rows are still raw miles.

    `booted` records migration 133 as applied, as the first boot does.
    """
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA + (_UNITS if with_units else ""))
    if booted:
        conn.executescript(
            "CREATE TABLE schema_migrations (id INTEGER PRIMARY KEY, migration_name TEXT);"
            "INSERT INTO schema_migrations (migration_name) "
            "VALUES ('133_record_wican_legacy_odometer_unit');"
        )
    conn.execute(
        "INSERT INTO livelink_devices VALUES "
        "('devlegacy', 'VINLEGACY', NULL, 'wican', NULL, '2026-08-01 00:00:00')"
    )
    conn.executemany(
        "INSERT INTO vehicle_telemetry VALUES ('VINLEGACY', 'devlegacy', 'ODOMETER', ?, ?)",
        [(1000.0, "2026-09-01 10:00:00"), (1001.0, "2026-09-02 10:00:00")],
    )
    conn.execute(
        "INSERT INTO vehicle_telemetry_latest VALUES "
        "('VINLEGACY', 'ODOMETER', 1001.0, '2026-09-02 10:00:00')"
    )
    # A fuel record in km, well above the stored miles: still to convert.
    conn.execute("INSERT INTO odometer_records VALUES ('VINLEGACY', '2026-08-01', 1600.0, 'fuel')")
    if legacy:
        conn.execute(
            "INSERT INTO livelink_device_units VALUES "
            "('devlegacy', 'ODOMETER', 'mi', 'distance', 'legacy')"
        )
    conn.commit()
    conn.close()


def _run(module_name: str, path: str, monkeypatch, *extra: str) -> int:
    module = importlib.import_module(module_name)
    monkeypatch.setattr("sys.argv", [module_name, "--db", path, *extra])
    return module.main()


def test_normalize_converts_a_legacy_miles_device(tmp_path, monkeypatch, capsys):
    """Red against a T7 whose tool reads only the key rule."""
    path = str(tmp_path / "mygarage.db")
    _seed(path, with_units=True, legacy=True)

    assert _run("tools.normalize_telemetry_odometer_units", path, monkeypatch, "--apply") == 0

    conn = sqlite3.connect(path)
    values = [v for (v,) in conn.execute("SELECT value FROM vehicle_telemetry ORDER BY timestamp")]
    conn.close()
    assert values == [pytest.approx(1609.344), pytest.approx(1001 * 1.609344)]
    assert "devlegacy / ODOMETER" in capsys.readouterr().out


def test_normalize_skips_a_bare_odometer_with_no_row(tmp_path, monkeypatch, capsys):
    """After 133 has run, no legacy row means the live path reads it as km (it
    started reporting after the upgrade), so the tool agrees and leaves it be.
    Red on main, which read it as miles."""
    path = str(tmp_path / "mygarage.db")
    _seed(path, with_units=True, legacy=False)

    assert _run("tools.normalize_telemetry_odometer_units", path, monkeypatch) == 0

    assert "No odometer telemetry needs conversion." in capsys.readouterr().out


def test_normalize_converts_before_the_first_boot(tmp_path, monkeypatch, capsys):
    """No R12 table yet, so no legacy row: the tool reads the device the way
    133 will at first boot (miles), rather than by the km key rule (I1)."""
    path = str(tmp_path / "mygarage.db")
    _seed(path, with_units=False, legacy=False, booted=False)

    assert _run("tools.normalize_telemetry_odometer_units", path, monkeypatch, "--apply") == 0

    conn = sqlite3.connect(path)
    values = [v for (v,) in conn.execute("SELECT value FROM vehicle_telemetry ORDER BY timestamp")]
    conn.close()
    assert values == [pytest.approx(1609.344), pytest.approx(1001 * 1.609344)]
    assert "devlegacy / ODOMETER" in capsys.readouterr().out


def test_backfill_reads_a_legacy_row_as_miles(tmp_path, monkeypatch, capsys):
    """The record reconstruction converts with the same resolved unit. Red
    against a T7 whose tool reads only the key rule (it would plan 1,001 km)."""
    path = str(tmp_path / "mygarage.db")
    _seed(path, with_units=True, legacy=True)

    assert _run("tools.backfill_livelink_odometer", path, monkeypatch) == 0

    out = capsys.readouterr().out
    assert "1,609 km → 1,611 km" in out, out


def test_backfill_plans_miles_before_the_first_boot(tmp_path, monkeypatch, capsys):
    """As above, for the record reconstruction (I1)."""
    path = str(tmp_path / "mygarage.db")
    _seed(path, with_units=False, legacy=False, booted=False)

    assert _run("tools.backfill_livelink_odometer", path, monkeypatch) == 0

    out = capsys.readouterr().out
    assert "1,609 km → 1,611 km" in out, out


def test_backfill_vin_limits_the_refusal_too(tmp_path, monkeypatch, capsys):
    """`--vin` scoped the reconstruction but not the already-converted refusal,
    so another vehicle's converted history refused this one's run."""
    path = str(tmp_path / "mygarage.db")
    _seed(path, with_units=True, legacy=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO livelink_devices VALUES "
        "('devdone', 'VINDONE', 'mi', 'wican', NULL, '2026-08-01 00:00:00')"
    )
    conn.execute(
        "INSERT INTO vehicle_telemetry VALUES "
        "('VINDONE', 'devdone', 'ODOMETER', 1609.0, '2026-09-01 10:00:00')"
    )
    conn.execute("INSERT INTO odometer_records VALUES ('VINDONE', '2026-08-01', 1600.0, 'fuel')")
    conn.commit()
    conn.close()

    assert _run("tools.backfill_livelink_odometer", path, monkeypatch, "--vin", "VINLEGACY") == 0
    assert "1,609 km → 1,611 km" in capsys.readouterr().out

    # Unscoped, the converted vehicle still refuses the run.
    assert _run("tools.backfill_livelink_odometer", path, monkeypatch) == 2
