"""Startup recomputes the trips migration 130 listed, but not in maintenance mode (#223).

The integration client never runs the lifespan, so this drives it through
TestClient, as test_trusted_proxy_lifespan.py does, with init_db and the
settings bootstrap stubbed out.
"""

from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError
from starlette.testclient import TestClient

from app import main as app_main
from app.config import settings
from app.services import auth, session_repair, settings_init
from app.tasks import scheduled


class _StopStartupError(Exception):
    """Raised by a stub, so startup ends there."""


def _stub_startup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("data_dir", "attachments_dir", "photos_dir", "documents_dir"):
        monkeypatch.setattr(settings, name, tmp_path / name)

    async def _nothing(*_args: object) -> None:
        return None

    async def _local(_db: object) -> str:
        return "local"

    monkeypatch.setattr(app_main, "init_db", _nothing)
    monkeypatch.setattr(settings_init, "initialize_default_settings", _nothing)
    monkeypatch.setattr(auth, "get_auth_mode", _local)


def test_startup_recomputes_the_listed_trips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_startup(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "maintenance_mode", False)
    calls: list[object] = []

    async def _repair(db: object) -> int:
        calls.append(db)
        raise _StopStartupError

    monkeypatch.setattr(session_repair, "recompute_pending_sessions", _repair)

    with pytest.raises(_StopStartupError):
        with TestClient(app_main.app):
            pass
    assert len(calls) == 1


def test_a_failed_repair_is_caught_and_the_scheduler_starts_after_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A database error keeps the list for the next start but doesn't stop
    this one, and the repair runs before the scheduler starts."""
    _stub_startup(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "maintenance_mode", False)
    order: list[str] = []

    async def _repair(_db: object) -> int:
        order.append("repair")
        raise OperationalError("SELECT settings", {}, Exception("boom"))

    def _scheduler() -> None:
        order.append("scheduler")
        raise _StopStartupError

    monkeypatch.setattr(session_repair, "recompute_pending_sessions", _repair)
    monkeypatch.setattr(scheduled, "start_scheduler", _scheduler)

    with pytest.raises(_StopStartupError):
        with TestClient(app_main.app):
            pass
    assert order == ["repair", "scheduler"]


def test_maintenance_mode_leaves_the_list_for_later(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_startup(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "maintenance_mode", True)
    calls: list[object] = []

    async def _repair(db: object) -> int:
        calls.append(db)
        return 0

    monkeypatch.setattr(session_repair, "recompute_pending_sessions", _repair)

    with TestClient(app_main.app):
        pass
    assert calls == []
