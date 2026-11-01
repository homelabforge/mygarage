"""
Integration tests for backup routes.

Tests backup CRUD operations, upload, download, and restore functionality.
Every test in the class works in a tmp backup folder and a tmp SQLite file,
never the app's real data directory.
"""

import gzip
import json
import sqlite3
import tarfile
from datetime import datetime, tzinfo
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Self
from uuid import UUID

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.utils import backup_names
from tests.integration._secret_helpers import Keep

RESTORE_PROBE = "__backup_route_restore_probe__"


def _one_value_db(path: Path, value: str) -> None:
    """A SQLite file with one row, for the restore route tests."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE audit_rows (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO audit_rows (id, v) VALUES (1, ?)", (value,))
    conn.commit()
    conn.close()


def _values(path: Path) -> list[tuple[str]]:
    """The rows of a database made by _one_value_db, read-only."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT v FROM audit_rows").fetchall()
    finally:
        conn.close()


def _full_restore_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, sqlite: bool
) -> tuple[Path, Path]:
    """Point the backup routes at tmp_path: a live SQLite file, a data folder and one archive.

    Patched, not read from the app's engine, so this runs the same on the PG sidecar.
    """
    from app.config import settings
    from app.routes import backup as backup_routes

    data_dir = tmp_path / "data"
    for name in ("photos", "documents", "attachments"):
        (data_dir / name).mkdir(parents=True)
    db = tmp_path / "garage.db"
    _one_value_db(db, "live")
    source = tmp_path / "source.db"
    _one_value_db(source, "restored")
    backups = tmp_path / "backups"
    backups.mkdir()
    with tarfile.open(backups / "mygarage-full-route.tar.gz", "w:gz") as tar:
        tar.add(source, arcname="mygarage.db")
    monkeypatch.setattr(backup_routes, "BACKUP_DIR", backups)
    monkeypatch.setattr(backup_routes, "DATABASE_PATH", db if sqlite else None)
    monkeypatch.setattr(backup_routes, "is_sqlite", sqlite)
    monkeypatch.setattr(settings, "data_dir", data_dir)
    return data_dir, db


class _FrozenClock(datetime):
    """Every `now()` lands in the same second, as two quick uploads do."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        return cls(2026, 11, 1, 12, 0, 0, tzinfo=tz)


# What _FrozenClock stamps a backup name with.
FROZEN_STAMP = "2026-11-01-120000"

# Every way a backup gets written, and the name each had when names went by
# the second alone.
SETTINGS_UPLOAD = ("a.json", json.dumps({"version": "1.0.0", "settings": []}).encode())
FULL_UPLOAD = ("a.tar.gz", gzip.compress(b"full"))
BACKUP_WRITERS = {
    "create": ("/api/backup/create", None, "mygarage-settings-{}.json"),
    "create-full": ("/api/backup/create-full", None, "mygarage-full-{}.tar.gz"),
    "upload-settings": (
        "/api/backup/upload",
        SETTINGS_UPLOAD,
        "mygarage-settings-uploaded-{}.json",
    ),
    "upload-full": ("/api/backup/upload", FULL_UPLOAD, "mygarage-full-uploaded-{}.tar.gz"),
}


async def _write_backup(client: AsyncClient, headers: dict[str, str], writer: str) -> Response:
    url, upload, _ = BACKUP_WRITERS[writer]
    if upload is None:
        return await client.post(url, headers=headers)
    name, content = upload
    return await client.post(
        url, headers=headers, files={"file": (name, BytesIO(content), "application/octet-stream")}
    )


def _seed_one_of_each(backup_dir: Path) -> None:
    """One settings and one full backup on disk, for the list filters."""
    (backup_dir / "mygarage-settings-seeded.json").write_text('{"settings": []}')
    (backup_dir / "mygarage-full-seeded.tar.gz").write_bytes(gzip.compress(b"seeded"))


@pytest.mark.integration
@pytest.mark.asyncio
class TestBackupRoutes:
    """Test backup API endpoints."""

    @pytest.fixture(autouse=True)
    def backup_dir(
        self, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> Path:
        """Point the routes at a tmp backup folder and a tmp SQLite file.

        Not tmp_path, so a test that patches its own folder in still finds it empty.
        is_sqlite too, so a full backup snapshots the file on the PG sidecar instead of pg_dump.
        """
        from app.routes import backup as backup_routes

        root = tmp_path_factory.mktemp("backup-routes")
        db = root / "mygarage.db"
        _one_value_db(db, "live")
        backups = root / "backups"
        backups.mkdir()
        monkeypatch.setattr(backup_routes, "BACKUP_DIR", backups)
        monkeypatch.setattr(backup_routes, "DATABASE_PATH", db)
        monkeypatch.setattr(backup_routes, "is_sqlite", True)
        return backups

    async def test_get_stats(self, client: AsyncClient, auth_headers, backup_dir: Path):
        """Test getting backup statistics."""
        response = await client.get(
            "/api/backup/stats",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "database" in data
        assert "settings_backups" in data
        assert "full_backups" in data
        assert "backup_directory" in data
        assert "wal_mode_enabled" in data
        assert "count" in data["settings_backups"]
        assert "total_size_mb" in data["settings_backups"]
        assert data["backup_directory"] == str(backup_dir)

    async def test_list_backups_all(self, client: AsyncClient, auth_headers, backup_dir: Path):
        """Test listing all backups."""
        _seed_one_of_each(backup_dir)

        response = await client.get(
            "/api/backup/list?backup_type=all",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert sorted(b["type"] for b in data["backups"]) == ["full", "settings"]

    async def test_list_backups_settings(self, client: AsyncClient, auth_headers, backup_dir: Path):
        """Test listing settings backups only."""
        _seed_one_of_each(backup_dir)

        response = await client.get(
            "/api/backup/list?backup_type=settings",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert sorted(b["type"] for b in data["backups"]) == ["settings"]

    async def test_list_backups_full(self, client: AsyncClient, auth_headers, backup_dir: Path):
        """Test listing full backups only."""
        _seed_one_of_each(backup_dir)

        response = await client.get(
            "/api/backup/list?backup_type=full",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert sorted(b["type"] for b in data["backups"]) == ["full"]

    async def test_create_settings_backup(
        self, client: AsyncClient, auth_headers, backup_dir: Path
    ):
        """Test creating a settings backup."""
        response = await client.post(
            "/api/backup/create",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "backup" in data
        assert "filename" in data["backup"]
        assert data["backup"]["filename"].startswith("mygarage-settings-")
        assert data["backup"]["filename"].endswith(".json")
        written = json.loads((backup_dir / data["backup"]["filename"]).read_text())
        assert isinstance(written["settings"], list)

    async def test_create_full_backup(
        self, client: AsyncClient, auth_headers, backup_dir: Path, tmp_path: Path
    ):
        """Test creating a full backup."""
        response = await client.post(
            "/api/backup/create-full",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "backup" in data
        assert "filename" in data["backup"]
        assert data["backup"]["filename"].startswith("mygarage-full-")
        assert data["backup"]["filename"].endswith(".tar.gz")
        # The archive holds a snapshot of the tmp database the fixture made.
        with tarfile.open(backup_dir / data["backup"]["filename"]) as tar:
            tar.extract("mygarage.db", tmp_path, filter="data")
        assert _values(tmp_path / "mygarage.db") == [("live",)]

    async def test_download_backup(self, client: AsyncClient, auth_headers, backup_dir: Path):
        """Test downloading a backup file."""
        # First create a settings backup
        create_response = await client.post(
            "/api/backup/create",
            headers=auth_headers,
        )
        assert create_response.status_code == 200
        filename = create_response.json()["backup"]["filename"]

        # Download it
        response = await client.get(
            f"/api/backup/download/{filename}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/json"
        assert response.content == (backup_dir / filename).read_bytes()

    async def test_download_backup_not_found(self, client: AsyncClient, auth_headers):
        """Test downloading non-existent backup."""
        response = await client.get(
            "/api/backup/download/nonexistent-backup.json",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_download_backup_path_traversal(self, client: AsyncClient, auth_headers):
        """Test path traversal prevention in download."""
        response = await client.get(
            "/api/backup/download/../../../etc/passwd",
            headers=auth_headers,
        )

        # Should be blocked - either 400, 403, or 404
        assert response.status_code in [400, 403, 404]

    async def test_upload_settings_backup(
        self, client: AsyncClient, auth_headers, backup_dir: Path
    ):
        """Test uploading a settings backup."""
        # Create valid settings backup content
        backup_content = json.dumps(
            {"version": "1.0.0", "settings": [{"key": "test_key", "value": "test_value"}]}
        )

        response = await client.post(
            "/api/backup/upload",
            headers=auth_headers,
            files={
                "file": ("test-backup.json", BytesIO(backup_content.encode()), "application/json")
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "backup" in data
        assert data["backup"]["type"] == "settings"
        assert data["backup"]["filename"].endswith(".json")
        assert (backup_dir / data["backup"]["filename"]).read_text() == backup_content

    @pytest.mark.usefixtures("local_clock_off_utc")
    async def test_an_uploaded_backup_serves_its_time_in_utc(
        self, client: AsyncClient, auth_headers, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """The upload answer's `created` was the container's local clock, which
        the frontend reads as UTC, so it showed hours off under a TZ."""
        from datetime import datetime, timedelta

        from app.routes import backup as backup_routes
        from app.utils.datetime_utils import utc_now

        monkeypatch.setattr(backup_routes, "BACKUP_DIR", tmp_path)
        content = json.dumps({"version": "1.0.0", "settings": []}).encode()
        response = await client.post(
            "/api/backup/upload",
            headers=auth_headers,
            files={"file": ("up.json", BytesIO(content), "application/json")},
        )

        assert response.status_code == 200, response.text
        created = datetime.fromisoformat(response.json()["backup"]["created"])
        assert abs(created - utc_now()) < timedelta(minutes=1), created

    async def test_upload_invalid_json(self, client: AsyncClient, auth_headers):
        """Test uploading invalid JSON backup."""
        response = await client.post(
            "/api/backup/upload",
            headers=auth_headers,
            files={"file": ("test-backup.json", BytesIO(b"not valid json"), "application/json")},
        )

        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["detail"]

    async def test_upload_invalid_structure(self, client: AsyncClient, auth_headers):
        """Test uploading JSON with invalid structure."""
        invalid_backup = json.dumps({"wrong": "structure"})

        response = await client.post(
            "/api/backup/upload",
            headers=auth_headers,
            files={
                "file": ("test-backup.json", BytesIO(invalid_backup.encode()), "application/json")
            },
        )

        assert response.status_code == 400
        assert "Invalid backup file structure" in response.json()["detail"]

    @pytest.mark.parametrize(
        ("content", "detail"),
        [
            (b"5", "Invalid backup file structure"),
            (b"null", "Invalid backup file structure"),
            (b'"settings"', "Invalid backup file structure"),
            (b'{"settings": [], "note": "\xff"}', "Invalid JSON file"),
            (b'{"settings": [], "n": ' + b"9" * 4301 + b"}", "Invalid JSON file"),
        ],
        ids=["top-level-number", "top-level-null", "top-level-string", "not-utf8", "huge-int"],
    )
    async def test_upload_unreadable_settings_file_is_a_400_and_writes_nothing(
        self,
        client: AsyncClient,
        auth_headers,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        content: bytes,
        detail: str,
    ):
        # These used to get past the JSONDecodeError catch or the "in" check and 500.
        from app.routes import backup as backup_routes

        monkeypatch.setattr(backup_routes, "BACKUP_DIR", tmp_path)
        response = await client.post(
            "/api/backup/upload",
            headers=auth_headers,
            files={"file": ("test-backup.json", BytesIO(content), "application/json")},
        )

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == detail
        assert list(tmp_path.iterdir()) == []

    async def test_upload_invalid_file_type(
        self, client: AsyncClient, auth_headers, backup_dir: Path
    ):
        """Test uploading unsupported file type."""
        response = await client.post(
            "/api/backup/upload",
            headers=auth_headers,
            files={"file": ("test.txt", BytesIO(b"text content"), "text/plain")},
        )

        assert response.status_code == 400
        assert "Invalid file type" in response.json()["detail"]
        assert list(backup_dir.iterdir()) == []

    async def test_delete_backup(self, client: AsyncClient, auth_headers, backup_dir: Path):
        """Test deleting a backup."""
        # First create a backup
        create_response = await client.post(
            "/api/backup/create",
            headers=auth_headers,
        )
        assert create_response.status_code == 200
        filename = create_response.json()["backup"]["filename"]

        # Delete it
        response = await client.delete(
            f"/api/backup/{filename}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify it's deleted
        download_response = await client.get(
            f"/api/backup/download/{filename}",
            headers=auth_headers,
        )
        assert download_response.status_code == 404
        assert not (backup_dir / filename).exists()

    async def test_delete_backup_not_found(self, client: AsyncClient, auth_headers):
        """Test deleting non-existent backup."""
        response = await client.delete(
            "/api/backup/nonexistent-backup.json",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_delete_backup_path_traversal(self, client: AsyncClient, auth_headers):
        """Test path traversal prevention in delete."""
        response = await client.delete(
            "/api/backup/../../../etc/passwd",
            headers=auth_headers,
        )

        # Should be blocked - either 400, 403, or 404
        assert response.status_code in [400, 403, 404]

    async def test_restore_settings_backup(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession, keep_rows: Keep
    ):
        """A settings backup puts back the value it was taken with.

        It writes every row in the shared test database (auth_mode and the secrets
        included), so they all go back as stored when the test ends.
        """
        await keep_rows(*(await db_session.scalars(select(Setting.key))).all(), RESTORE_PROBE)
        db_session.add(Setting(key=RESTORE_PROBE, value="before"))
        await db_session.commit()

        create_response = await client.post(
            "/api/backup/create",
            headers=auth_headers,
        )
        assert create_response.status_code == 200
        filename = create_response.json()["backup"]["filename"]
        probe = await db_session.get(Setting, RESTORE_PROBE)
        assert probe is not None
        probe.value = "after"
        await db_session.commit()

        # Restore it
        response = await client.post(
            f"/api/backup/restore/{filename}",
            headers=auth_headers,
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["success"] is True
        assert data["details"]["source_backup"] == filename
        db_session.expire_all()
        restored = await db_session.get(Setting, RESTORE_PROBE)
        assert restored is not None and restored.value == "before"

    async def test_restore_backup_not_found(self, client: AsyncClient, auth_headers):
        """Test restoring from non-existent backup."""
        response = await client.post(
            "/api/backup/restore/nonexistent-backup.json",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_restore_invalid_file_type(self, client: AsyncClient, auth_headers):
        """Test restoring from invalid file type."""
        response = await client.post(
            "/api/backup/restore/some-file.txt",
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "Invalid backup file type" in response.json()["detail"]

    async def test_a_full_restore_is_staged_and_says_to_restart(
        self, client: AsyncClient, auth_headers, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """The route stages, and says for certain that a restart finishes it."""
        _, db = _full_restore_setup(tmp_path, monkeypatch, sqlite=True)

        response = await client.post(
            "/api/backup/restore/mygarage-full-route.tar.gz", headers=auth_headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["message"] == "Restore staged. Restart MyGarage to finish."
        assert body["warning"] == (
            "Until it restarts, MyGarage keeps running on the current data, "
            "and anything changed before the restart is replaced by the backup."
        )
        assert body["details"]["safety_backup"].startswith("mygarage-full-safety-")
        assert _values(db) == [("live",)]
        assert _values(Path(f"{db}.restore-pending")) == [("restored",)]

    async def test_the_stats_show_a_staged_restore_until_it_is_cancelled(
        self, client: AsyncClient, auth_headers, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """The tab's stats say which backup is staged and when; Cancel drops it and the live data stays."""
        data_dir, db = _full_restore_setup(tmp_path, monkeypatch, sqlite=True)

        before = await client.get("/api/backup/stats", headers=auth_headers)
        assert before.status_code == 200, before.text
        assert before.json()["restore_pending"] is None
        staged = await client.post(
            "/api/backup/restore/mygarage-full-route.tar.gz", headers=auth_headers
        )
        assert staged.status_code == 200, staged.text
        pending = (await client.get("/api/backup/stats", headers=auth_headers)).json()
        assert pending["restore_pending"]["source_backup"] == "mygarage-full-route.tar.gz"
        assert pending["restore_pending"]["staged_at"].endswith("+00:00")

        cancelled = await client.delete("/api/backup/restore/pending", headers=auth_headers)

        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["message"] == "Restore cancelled; the current data stays."
        after = (await client.get("/api/backup/stats", headers=auth_headers)).json()
        assert after["restore_pending"] is None
        assert not (data_dir / ".restore-pending").exists()
        assert not Path(f"{db}.restore-pending").exists()
        assert _values(db) == [("live",)]

    async def test_cancel_with_nothing_staged_is_a_404(
        self, client: AsyncClient, auth_headers, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """A stale tab finds out the restore is gone: cancelled elsewhere, or applied by a restart."""
        _full_restore_setup(tmp_path, monkeypatch, sqlite=True)

        response = await client.delete("/api/backup/restore/pending", headers=auth_headers)

        assert response.status_code == 404
        assert response.json()["detail"] == "No restore is staged"

    async def test_cancel_and_restore_are_refused_while_a_restore_is_half_applied(
        self, client: AsyncClient, auth_headers, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """With the applying marker down, the staging holds what was swapped out: 409, and it all stays.

        A guard; mutant: drop the 409 mapping (the refusal escapes as a server error).
        """
        data_dir, db = _full_restore_setup(tmp_path, monkeypatch, sqlite=True)
        staged = await client.post(
            "/api/backup/restore/mygarage-full-route.tar.gz", headers=auth_headers
        )
        assert staged.status_code == 200, staged.text
        (data_dir / ".restore-pending" / "applying").write_text("{}")

        cancel = await client.delete("/api/backup/restore/pending", headers=auth_headers)
        again = await client.post(
            "/api/backup/restore/mygarage-full-route.tar.gz", headers=auth_headers
        )

        assert cancel.status_code == 409, cancel.text
        assert again.status_code == 409, again.text
        assert (data_dir / ".restore-pending" / "manifest.json").exists()
        assert Path(f"{db}.restore-pending").exists()

    async def test_a_full_restore_on_postgresql_is_still_refused(
        self, client: AsyncClient, auth_headers, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """PostgreSQL restores with pg_restore, and nothing is staged.

        A guard; mutant: drop the route's 501 (the service's RuntimeError escapes instead).
        """
        data_dir, _ = _full_restore_setup(tmp_path, monkeypatch, sqlite=False)

        response = await client.post(
            "/api/backup/restore/mygarage-full-route.tar.gz", headers=auth_headers
        )

        assert response.status_code == 501
        assert not (data_dir / ".restore-pending").exists()

    async def test_backup_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot access backup endpoints."""
        # Test stats
        response = await client.get("/api/backup/stats")
        assert response.status_code == 401

        # Test list
        response = await client.get("/api/backup/list")
        assert response.status_code == 401

        # Test create
        response = await client.post("/api/backup/create")
        assert response.status_code == 401

        # Test download
        response = await client.get("/api/backup/download/test.json")
        assert response.status_code == 401

    async def test_backup_stats_structure(self, client: AsyncClient, auth_headers):
        """Test backup stats response structure."""
        created = await client.post("/api/backup/create", headers=auth_headers)
        assert created.status_code == 200, created.text

        response = await client.get(
            "/api/backup/stats",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Check database stats
        assert "database" in data
        db_stats = data["database"]
        assert "size_mb" in db_stats or "exists" in db_stats

        # Check backup counts
        assert data["settings_backups"]["count"] == 1
        assert data["full_backups"]["count"] == 0

    async def test_backup_list_contains_created_backups(self, client: AsyncClient, auth_headers):
        """Test that created backups appear in list."""
        # Create a settings backup
        create_response = await client.post(
            "/api/backup/create",
            headers=auth_headers,
        )
        assert create_response.status_code == 200
        filename = create_response.json()["backup"]["filename"]

        # List backups
        list_response = await client.get(
            "/api/backup/list?backup_type=settings",
            headers=auth_headers,
        )

        assert list_response.status_code == 200
        backups = list_response.json()["backups"]
        assert [b["filename"] for b in backups] == [filename]

    async def test_upload_tar_gz_backup(self, client: AsyncClient, auth_headers, backup_dir: Path):
        """Test uploading a tar.gz backup file."""
        # Create minimal tar.gz content (just header, not valid archive)
        # This tests the file type validation, not actual tar content
        tar_content = gzip.compress(b"test content")

        response = await client.post(
            "/api/backup/upload",
            headers=auth_headers,
            files={"file": ("test-backup.tar.gz", BytesIO(tar_content), "application/gzip")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["backup"]["type"] == "full"
        assert data["backup"]["filename"].endswith(".tar.gz")
        assert (backup_dir / data["backup"]["filename"]).read_bytes() == tar_content

    @pytest.mark.parametrize("writer", sorted(BACKUP_WRITERS))
    async def test_two_backups_in_the_same_second_keep_both(
        self,
        client: AsyncClient,
        auth_headers,
        backup_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        writer: str,
    ):
        """Names went by the second, so the second backup overwrote the first."""
        monkeypatch.setattr(backup_names, "datetime", _FrozenClock)
        names = []
        for _ in range(2):
            response = await _write_backup(client, auth_headers, writer)
            assert response.status_code == 200, response.text
            names.append(response.json()["backup"]["filename"])

        assert names[0] != names[1]
        # The freeze really applied, so both landed in the one second.
        assert all(FROZEN_STAMP in name for name in names), names
        assert sorted(p.name for p in backup_dir.iterdir()) == sorted(names)

    @pytest.mark.parametrize("writer", sorted(BACKUP_WRITERS))
    async def test_a_backup_leaves_a_file_with_its_by_the_second_name_alone(
        self,
        client: AsyncClient,
        auth_headers,
        backup_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        writer: str,
    ):
        """An older backup made in the same second keeps its bytes; the new one lands beside it."""
        monkeypatch.setattr(backup_names, "datetime", _FrozenClock)
        existing = backup_dir / BACKUP_WRITERS[writer][2].format(FROZEN_STAMP)
        existing.write_bytes(b"an earlier backup")

        response = await _write_backup(client, auth_headers, writer)

        assert response.status_code == 200, response.text
        new_name = response.json()["backup"]["filename"]
        assert new_name != existing.name
        assert FROZEN_STAMP in new_name
        assert (backup_dir / new_name).is_file()
        assert existing.read_bytes() == b"an earlier backup"

    @pytest.mark.parametrize("writer", sorted(BACKUP_WRITERS))
    async def test_a_clash_on_the_whole_name_fails_instead_of_overwriting(
        self,
        client: AsyncClient,
        auth_headers,
        backup_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        writer: str,
    ):
        """Pin the suffix too, so the next name is already taken: refuse, never clobber."""
        monkeypatch.setattr(backup_names, "datetime", _FrozenClock)
        monkeypatch.setattr(backup_names, "uuid", SimpleNamespace(uuid4=lambda: UUID(int=0)))
        taken = backup_dir / BACKUP_WRITERS[writer][2].format(f"{FROZEN_STAMP}-00000000")
        taken.write_bytes(b"an earlier backup")

        response = await _write_backup(client, auth_headers, writer)

        assert response.status_code == 500, response.text
        assert taken.read_bytes() == b"an earlier backup"
        assert [p.name for p in backup_dir.iterdir()] == [taken.name]

    async def test_backup_non_admin_forbidden(self, client: AsyncClient, non_admin_headers):
        """Test that non-admin users get 403 on all backup endpoints."""
        # GET /stats
        response = await client.get("/api/backup/stats", headers=non_admin_headers)
        assert response.status_code == 403

        # POST /create
        response = await client.post("/api/backup/create", headers=non_admin_headers)
        assert response.status_code == 403

        # GET /list
        response = await client.get("/api/backup/list", headers=non_admin_headers)
        assert response.status_code == 403

        # GET /download
        response = await client.get("/api/backup/download/test.json", headers=non_admin_headers)
        assert response.status_code == 403

        # POST /restore
        response = await client.post("/api/backup/restore/test.json", headers=non_admin_headers)
        assert response.status_code == 403

        # DELETE /restore/pending
        response = await client.delete("/api/backup/restore/pending", headers=non_admin_headers)
        assert response.status_code == 403

        # DELETE
        response = await client.delete("/api/backup/test.json", headers=non_admin_headers)
        assert response.status_code == 403

        # POST /upload
        response = await client.post(
            "/api/backup/upload",
            headers=non_admin_headers,
            files={"file": ("test.json", BytesIO(b"{}"), "application/json")},
        )
        assert response.status_code == 403

        # POST /create-full
        response = await client.post("/api/backup/create-full", headers=non_admin_headers)
        assert response.status_code == 403
