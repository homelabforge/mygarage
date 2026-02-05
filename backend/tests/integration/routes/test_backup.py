"""
Integration tests for backup routes.

Tests backup CRUD operations, upload, download, and restore functionality.

Note: Many tests require filesystem write access to the backup directory.
Tests that require this are marked with pytest.mark.skipif when the
backup directory is not writable (common in CI environments).
"""

import json
import os
from io import BytesIO
from pathlib import Path

import pytest
from httpx import AsyncClient

# Check if we have write access to the data directory
# Tests that need filesystem access will be skipped if not writable
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    test_file = DATA_DIR / ".write_test"
    test_file.touch()
    test_file.unlink()
    HAS_WRITE_ACCESS = True
except (PermissionError, OSError):
    HAS_WRITE_ACCESS = False


requires_write_access = pytest.mark.skipif(
    not HAS_WRITE_ACCESS, reason="Test requires write access to data directory"
)


@pytest.mark.integration
@pytest.mark.asyncio
class TestBackupRoutes:
    """Test backup API endpoints."""

    @requires_write_access
    async def test_get_stats(self, client: AsyncClient, auth_headers):
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

    @requires_write_access
    async def test_list_backups_all(self, client: AsyncClient, auth_headers):
        """Test listing all backups."""
        response = await client.get(
            "/api/backup/list?backup_type=all",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "backups" in data
        assert isinstance(data["backups"], list)

    @requires_write_access
    async def test_list_backups_settings(self, client: AsyncClient, auth_headers):
        """Test listing settings backups only."""
        response = await client.get(
            "/api/backup/list?backup_type=settings",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "backups" in data
        assert isinstance(data["backups"], list)

    @requires_write_access
    async def test_list_backups_full(self, client: AsyncClient, auth_headers):
        """Test listing full backups only."""
        response = await client.get(
            "/api/backup/list?backup_type=full",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "backups" in data
        assert isinstance(data["backups"], list)

    @requires_write_access
    async def test_create_settings_backup(self, client: AsyncClient, auth_headers):
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

    @requires_write_access
    async def test_create_full_backup(self, client: AsyncClient, auth_headers):
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

    @requires_write_access
    async def test_download_backup(self, client: AsyncClient, auth_headers):
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
        # Verify it's valid JSON
        json.loads(response.content)

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

    @requires_write_access
    async def test_upload_settings_backup(self, client: AsyncClient, auth_headers):
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

    @requires_write_access
    async def test_upload_invalid_json(self, client: AsyncClient, auth_headers):
        """Test uploading invalid JSON backup."""
        response = await client.post(
            "/api/backup/upload",
            headers=auth_headers,
            files={"file": ("test-backup.json", BytesIO(b"not valid json"), "application/json")},
        )

        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["detail"]

    @requires_write_access
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

    @requires_write_access
    async def test_upload_invalid_file_type(self, client: AsyncClient, auth_headers):
        """Test uploading unsupported file type."""
        response = await client.post(
            "/api/backup/upload",
            headers=auth_headers,
            files={"file": ("test.txt", BytesIO(b"text content"), "text/plain")},
        )

        assert response.status_code == 400
        assert "Invalid file type" in response.json()["detail"]

    @requires_write_access
    async def test_delete_backup(self, client: AsyncClient, auth_headers):
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

    @requires_write_access
    async def test_restore_settings_backup(self, client: AsyncClient, auth_headers):
        """Test restoring from a settings backup."""
        # First create a settings backup
        create_response = await client.post(
            "/api/backup/create",
            headers=auth_headers,
        )
        assert create_response.status_code == 200
        filename = create_response.json()["backup"]["filename"]

        # Restore it
        response = await client.post(
            f"/api/backup/restore/{filename}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "details" in data

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

    @requires_write_access
    async def test_backup_stats_structure(self, client: AsyncClient, auth_headers):
        """Test backup stats response structure."""
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
        assert data["settings_backups"]["count"] >= 0
        assert data["full_backups"]["count"] >= 0

    @requires_write_access
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
        filenames = [b["filename"] for b in backups]
        assert filename in filenames

    @requires_write_access
    async def test_upload_tar_gz_backup(self, client: AsyncClient, auth_headers):
        """Test uploading a tar.gz backup file."""
        # Create minimal tar.gz content (just header, not valid archive)
        # This tests the file type validation, not actual tar content
        import gzip

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
