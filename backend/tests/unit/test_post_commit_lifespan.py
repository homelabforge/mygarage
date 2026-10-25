"""Shutdown drains the post-commit queue, after ingest has stopped (wave B review M-2).

Driven through TestClient like test_session_repair_lifespan.py, with the
startup stubbed out so the app starts against nothing.
"""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import main as app_main
from app.config import settings
from app.services import auth, post_commit, session_repair, settings_init, settings_secrets
from app.services.telegram_poller import telegram_poller
from app.tasks import livelink_tasks, scheduled


def test_shutdown_drains_post_commit_jobs_after_mqtt_stops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Red on f3a8b81c: nothing waited for them, so a notice still being sent
    was destroyed with the loop. After the subscriber stops, so no new job
    lands behind the drain."""
    for name in ("data_dir", "attachments_dir", "photos_dir", "documents_dir"):
        monkeypatch.setattr(settings, name, tmp_path / name)
    monkeypatch.setattr(settings, "maintenance_mode", False)
    order: list[str] = []

    async def _nothing(*_args: object) -> None:
        return None

    async def _local(_db: object) -> str:
        return "local"

    async def _no_sweep(_db: object) -> settings_secrets.SweepReport:
        return settings_secrets.SweepReport()

    async def _no_repair(_db: object) -> int:
        return 0

    async def _mqtt_stop() -> None:
        order.append("mqtt stopped")

    async def _shutdown(timeout: float) -> None:
        order.append("drained")

    monkeypatch.setattr(app_main, "init_db", _nothing)
    monkeypatch.setattr(settings_secrets, "sweep_secret_settings", _no_sweep)
    monkeypatch.setattr(settings_init, "initialize_default_settings", _nothing)
    monkeypatch.setattr(auth, "get_auth_mode", _local)
    monkeypatch.setattr(session_repair, "recompute_pending_sessions", _no_repair)
    monkeypatch.setattr(scheduled, "start_scheduler", lambda: None)
    monkeypatch.setattr(scheduled, "stop_scheduler", lambda: None)
    monkeypatch.setattr(livelink_tasks, "start_mqtt_subscriber", _nothing)
    monkeypatch.setattr(livelink_tasks, "stop_mqtt_subscriber", _mqtt_stop)
    monkeypatch.setattr(telegram_poller, "start", _nothing)
    monkeypatch.setattr(telegram_poller, "stop", _nothing)
    monkeypatch.setattr(post_commit, "shutdown", _shutdown)

    with TestClient(app_main.app):
        pass

    assert order == ["mqtt stopped", "drained"]
