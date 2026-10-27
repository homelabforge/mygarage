"""Backup times go out as naive UTC, like every other stamp the API serves.

They were `datetime.fromtimestamp(mtime)`, the container's local clock, and the
frontend reads a naive stamp as UTC, so a container with a TZ showed every
backup hours off. Each test runs with the process clock five hours west of UTC.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services.backup_service import BackupService
from app.services.settings_service import SettingsService
from app.utils.datetime_utils import utc_now

pytestmark = pytest.mark.usefixtures("local_clock_off_utc")

#: 18:30 UTC, a moment five hours from the local clock the fixture sets.
MTIME = datetime(2026, 7, 15, 18, 30, tzinfo=UTC).timestamp()
SERVED = "2026-07-15T18:30:00"


def _service(tmp_path: Path, db_path: Path | None = None) -> BackupService:
    data_dir = tmp_path / "data"
    for sub in ("photos", "documents", "attachments"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    return BackupService(
        backup_dir=tmp_path / "backups",
        database_path=db_path,
        data_dir=data_dir,
        is_sqlite=True,
    )


def _just_now(served: str) -> bool:
    return abs(datetime.fromisoformat(served) - utc_now()) < timedelta(minutes=1)


def test_the_backup_list_serves_utc(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.ensure_backup_dir()
    for name in ("mygarage-settings-a.json", "mygarage-full-a.tar.gz"):
        path = service.backup_dir / name
        path.write_bytes(b"{}")
        os.utime(path, (MTIME, MTIME))

    assert [b["created"] for b in service.get_backup_files()] == [SERVED, SERVED]


def test_the_database_stats_serve_utc(tmp_path: Path) -> None:
    db = tmp_path / "mygarage.db"
    db.write_bytes(b"")
    os.utime(db, (MTIME, MTIME))

    assert _service(tmp_path, db).get_database_stats()["last_modified"] == SERVED


async def test_a_new_settings_backup_serves_utc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_settings(_db: object) -> list[object]:
        return []

    monkeypatch.setattr(SettingsService, "get_all", staticmethod(no_settings))
    created = (await _service(tmp_path).create_settings_backup(db=None))["created"]  # type: ignore[arg-type]
    assert _just_now(created), created


async def test_a_new_full_backup_serves_utc(tmp_path: Path) -> None:
    created = (await _service(tmp_path).create_full_backup())["created"]
    assert _just_now(created), created
