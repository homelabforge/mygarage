"""The odometer repair tools resolve a key's unit the way live ingest does (T7, F2-3).

After T7 a bare `ODOMETER` reads km unless the device's R12 row says
otherwise. A tool that only knew the key rule would call every legacy-miles
device "already metric" and skip it. Both tools also run before the first boot
of a new version, when `livelink_device_units` doesn't exist yet.
"""

from __future__ import annotations

import importlib
import sqlite3

import pytest

_SCHEMA = """
    CREATE TABLE livelink_devices (device_id TEXT, vin TEXT, odometer_unit TEXT, kind TEXT);
    CREATE TABLE vehicle_telemetry (
        vin TEXT, device_id TEXT, param_key TEXT, value REAL, timestamp TEXT);
    CREATE TABLE vehicle_telemetry_latest (vin TEXT, param_key TEXT, value REAL);
    CREATE TABLE odometer_records (vin TEXT, date TEXT, odometer_km REAL, source TEXT);
"""

_UNITS = """
    CREATE TABLE livelink_device_units (
        device_id TEXT, param_key TEXT, unit TEXT, param_class TEXT, source TEXT);
"""


def _seed(path: str, *, with_units: bool, legacy: bool) -> None:
    """One unit-less WiCAN whose bare ODOMETER rows are still raw miles."""
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA + (_UNITS if with_units else ""))
    conn.execute("INSERT INTO livelink_devices VALUES ('devlegacy', 'VINLEGACY', NULL, 'wican')")
    conn.executemany(
        "INSERT INTO vehicle_telemetry VALUES ('VINLEGACY', 'devlegacy', 'ODOMETER', ?, ?)",
        [(1000.0, "2026-09-01 10:00:00"), (1001.0, "2026-09-02 10:00:00")],
    )
    conn.execute("INSERT INTO vehicle_telemetry_latest VALUES ('VINLEGACY', 'ODOMETER', 1001.0)")
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
    """Without a legacy row the live path reads it as km, so the tool agrees
    and leaves it be. Red on main, which read it as miles."""
    path = str(tmp_path / "mygarage.db")
    _seed(path, with_units=True, legacy=False)

    assert _run("tools.normalize_telemetry_odometer_units", path, monkeypatch) == 0

    assert "No odometer telemetry needs conversion." in capsys.readouterr().out


def test_normalize_runs_before_the_units_table_exists(tmp_path, monkeypatch, capsys):
    """Regression guard: a database from before the first boot has no R12 table."""
    path = str(tmp_path / "mygarage.db")
    _seed(path, with_units=False, legacy=False)

    assert _run("tools.normalize_telemetry_odometer_units", path, monkeypatch) == 0


def test_backfill_reads_a_legacy_row_as_miles(tmp_path, monkeypatch, capsys):
    """The record reconstruction converts with the same resolved unit. Red
    against a T7 whose tool reads only the key rule (it would plan 1,001 km)."""
    path = str(tmp_path / "mygarage.db")
    _seed(path, with_units=True, legacy=True)

    assert _run("tools.backfill_livelink_odometer", path, monkeypatch) == 0

    out = capsys.readouterr().out
    assert "1,609 km → 1,611 km" in out, out


def test_backfill_runs_before_the_units_table_exists(tmp_path, monkeypatch, capsys):
    """Regression guard: as above, no R12 table yet."""
    path = str(tmp_path / "mygarage.db")
    _seed(path, with_units=False, legacy=False)

    assert _run("tools.backfill_livelink_odometer", path, monkeypatch) == 0
