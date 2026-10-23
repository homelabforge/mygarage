"""Startup runs the secret settings sweep, after maintenance mode's stop, and never dies of it (D5a).

Driven through TestClient like test_session_repair_lifespan.py, with init_db,
the settings bootstrap and the sweep itself stubbed out. What the sweep does
is pinned in tests/integration/test_settings_secrets_sweep.py.
"""

import logging
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import main as app_main
from app.config import settings
from app.services import auth, session_repair, settings_init, settings_secrets


class _StopStartupError(Exception):
    """Raised by a stub, so startup ends there."""


def _stub_startup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, order: list[str]) -> None:
    for name in ("data_dir", "attachments_dir", "photos_dir", "documents_dir"):
        monkeypatch.setattr(settings, name, tmp_path / name)

    async def _nothing(*_args: object) -> None:
        return None

    async def _local(_db: object) -> str:
        return "local"

    async def _repair(_db: object) -> int:
        order.append("repair")
        raise _StopStartupError

    monkeypatch.setattr(app_main, "init_db", _nothing)
    monkeypatch.setattr(settings_init, "initialize_default_settings", _nothing)
    monkeypatch.setattr(auth, "get_auth_mode", _local)
    monkeypatch.setattr(session_repair, "recompute_pending_sessions", _repair)


def test_startup_sweeps_once_before_the_session_repair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    order: list[str] = []
    _stub_startup(monkeypatch, tmp_path, order)
    monkeypatch.setattr(settings, "maintenance_mode", False)

    async def _sweep(_db: object) -> settings_secrets.SweepReport:
        order.append("sweep")
        return settings_secrets.SweepReport()

    monkeypatch.setattr(settings_secrets, "sweep_secret_settings", _sweep)

    with pytest.raises(_StopStartupError):
        with TestClient(app_main.app):
            pass
    assert order == ["sweep", "repair"]


def test_a_sweep_that_raises_does_not_stop_the_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The sweep swallows its own database errors; this is the guard for a bug in it.
    The log names the exception type only, since its text could hold a value."""
    order: list[str] = []
    _stub_startup(monkeypatch, tmp_path, order)
    monkeypatch.setattr(settings, "maintenance_mode", False)

    async def _sweep(_db: object) -> settings_secrets.SweepReport:
        order.append("sweep")
        raise ValueError("enc:v1:0011aabb:some-ciphertext")

    monkeypatch.setattr(settings_secrets, "sweep_secret_settings", _sweep)

    with caplog.at_level(logging.ERROR, logger="app.main"):
        with pytest.raises(_StopStartupError):
            with TestClient(app_main.app):
                pass
    assert order == ["sweep", "repair"]
    assert "ValueError" in caplog.text
    assert "some-ciphertext" not in caplog.text


def test_maintenance_mode_skips_the_sweep(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    order: list[str] = []
    _stub_startup(monkeypatch, tmp_path, order)
    monkeypatch.setattr(settings, "maintenance_mode", True)

    async def _sweep(_db: object) -> settings_secrets.SweepReport:
        order.append("sweep")
        return settings_secrets.SweepReport()

    monkeypatch.setattr(settings_secrets, "sweep_secret_settings", _sweep)

    with TestClient(app_main.app):
        pass
    assert order == []
