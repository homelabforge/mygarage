"""Backup API endpoints for settings and full data backup/restore."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import engine, get_db, is_sqlite, sqlite_database_path
from app.models.user import User
from app.services.auth import get_current_admin_user
from app.services.auth_settings import AuthSettingsConflictError
from app.services.backup_service import BackupService
from app.services.restore_staging import RestoreInProgressError
from app.services.settings_secrets import ensure_secrets_encrypted
from app.utils.datetime_utils import utc_from_timestamp
from app.utils.logging_utils import sanitize_for_log

router = APIRouter(prefix="/api/backup", tags=["Backup"])
logger = logging.getLogger(__name__)

# Backup directory configuration
BACKUP_DIR = settings.data_dir / "backups"

# SQLite: the file the engine opens (2.1 decodes the URL, so not the raw string);
# PostgreSQL: no file path needed
DATABASE_PATH: Path | None = sqlite_database_path(engine.url) if is_sqlite else None


def get_backup_service() -> BackupService:
    """Get backup service instance."""
    return BackupService(
        backup_dir=BACKUP_DIR,
        database_path=DATABASE_PATH,
        data_dir=settings.data_dir,
        database_url=settings.database_url,
        is_sqlite=is_sqlite,
    )


def _skipped_secrets_warning(keys: list[str]) -> str:
    """The restore's warning for secret keys it left alone. Names keys only.

    Args:
        keys: The skipped secret setting keys, sorted.

    Returns:
        An English sentence the Backup tab appends to the success message.
    """
    return (
        f"These secret settings were not restored and keep their current values: "
        f"{', '.join(keys)}. The backup's copy can't be decrypted with the settings keys "
        "configured now, or no settings key is available to encrypt it. Re-enter them in "
        "Settings, or add the key the backup was made under and restore again."
    )


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Get database and backup statistics.

    Returns:
        Statistics about database and backups including sizes, counts, and paths.
    """
    try:
        backup_service = get_backup_service()

        # For PostgreSQL, query DB size via SQL and pass it in
        db_size_bytes: int | None = None
        if not is_sqlite:
            size_result = await db.execute(text("SELECT pg_database_size(current_database())"))
            db_size_bytes = size_result.scalar() or 0

        db_stats = backup_service.get_database_stats(db_size_bytes=db_size_bytes)

        settings_backups = backup_service.get_backup_files("settings")
        full_backups = backup_service.get_backup_files("full")

        settings_backup_size = sum(b["size_bytes"] for b in settings_backups)
        full_backup_size = sum(b["size_bytes"] for b in full_backups)

        return {
            "database": {
                **db_stats,
                "is_sqlite": is_sqlite,
                "database_engine": "sqlite" if is_sqlite else "postgresql",
            },
            "is_sqlite": is_sqlite,
            "database_engine": "sqlite" if is_sqlite else "postgresql",
            "settings_backups": {
                "count": len(settings_backups),
                "total_size_mb": round(settings_backup_size / 1024 / 1024, 4),
            },
            "full_backups": {
                "count": len(full_backups),
                "total_size_mb": round(full_backup_size / 1024 / 1024, 2),
            },
            "backup_directory": str(BACKUP_DIR),
            "wal_mode_enabled": (Path(f"{DATABASE_PATH}-wal").exists() if DATABASE_PATH else False),
            "restore_pending": backup_service.pending_restore(),
        }
    except OSError as e:
        logger.error("File system error getting stats: %s", e)
        raise HTTPException(status_code=500, detail="Error accessing backup files")


@router.get("/list")
async def list_backups(
    backup_type: str = "all", current_user: User | None = Depends(get_current_admin_user)
) -> dict[str, Any]:
    """List all available backup files.

    Args:
        backup_type: Type of backups to list - "settings", "full", or "all"

    Returns:
        List of backup files with metadata (filename, type, size, created date).
    """
    try:
        backup_service = get_backup_service()
        backups = backup_service.get_backup_files(backup_type)
        return {"backups": backups}
    except OSError as e:
        logger.error("File system error listing backups: %s", e)
        raise HTTPException(status_code=500, detail="Error accessing backup directory")


@router.post("/create")
async def create_settings_backup(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Create a new backup of all settings.

    Secret settings are written as their stored ciphertext. 503 while one is
    still stored as plaintext and can't be encrypted first.

    Args:
        db: Database session

    Returns:
        Metadata about the created backup file
    """
    # Before the try: its excepts must not see the refusal (R2-2).
    await ensure_secrets_encrypted(db)
    try:
        backup_service = get_backup_service()
        backup_info = await backup_service.create_settings_backup(db)

        return {
            "success": True,
            "message": "Settings backup created successfully",
            "backup": backup_info,
        }
    except PermissionError as e:
        logger.error("Permission denied creating settings backup: %s", e)
        raise HTTPException(
            status_code=403,
            detail="Permission denied: cannot write to backup directory",
        )
    except OSError as e:
        logger.error("File system error creating settings backup: %s", e)
        raise HTTPException(status_code=500, detail="Error writing backup file")


@router.post("/create-full")
async def create_full_backup(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Create a full backup including database and all uploaded files.

    This may take several minutes depending on the size of your data. 503 while
    a secret setting is still stored as plaintext and can't be encrypted first:
    the archive copies the database.

    Args:
        db: Database session, for the preflight only

    Returns:
        Metadata about the created backup file
    """
    # Before the try, whose `except RuntimeError` would turn the refusal into a 500 (R2-2).
    # It commits, so the snapshot's own connection sees the encrypted rows.
    await ensure_secrets_encrypted(db)
    try:
        backup_service = get_backup_service()
        backup_info = await backup_service.create_full_backup()

        return {
            "success": True,
            "message": "Full backup created successfully",
            "backup": backup_info,
        }
    except PermissionError as e:
        logger.error("Permission denied creating full backup: %s", e)
        raise HTTPException(
            status_code=403,
            detail="Permission denied: cannot write to backup directory",
        )
    except RuntimeError as e:
        logger.error("Backup creation error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    except OSError as e:
        logger.error("File system error creating full backup: %s", e)
        raise HTTPException(status_code=500, detail="Error creating backup archive")


@router.get("/download/{filename}")
async def download_backup(
    filename: str, current_user: User | None = Depends(get_current_admin_user)
):
    """Download a specific backup file.

    Args:
        filename: Name of the backup file to download

    Returns:
        Backup file as downloadable file
    """
    try:
        backup_service = get_backup_service()
        backup_path = backup_service.validate_filename(filename)

        if not backup_path.exists():
            raise HTTPException(status_code=404, detail="Backup file not found")

        # Determine media type based on file extension
        if filename.endswith(".json"):
            media_type = "application/json"
        elif filename.endswith(".tar.gz"):
            media_type = "application/gzip"
        else:
            media_type = "application/octet-stream"

        return FileResponse(
            path=backup_path,
            media_type=media_type,
            filename=filename,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Backup file not found")
    except PermissionError as e:
        logger.error("Permission denied downloading backup: %s", e)
        raise HTTPException(status_code=403, detail="Permission denied: cannot read backup file")
    except OSError as e:
        logger.error("File system error downloading backup: %s", e)
        raise HTTPException(status_code=500, detail="Error reading backup file")


@router.post("/restore/{filename}")
async def restore_backup(
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Restore a settings backup now, or stage a full backup for the next start.

    Either way a safety backup comes first. A full restore is SQLite only and finishes when MyGarage
    restarts. 503 while a secret setting is still stored as plaintext and can't be encrypted first,
    since the safety backup would copy it.

    409 when a settings backup would leave sign-in set to SSO without usable SSO; nothing is
    restored then.

    A settings restore that skipped secret keys (ciphertext no key in the keyring opens, or
    plaintext with no keyring to encrypt it) lists them in `details.skipped_secret_keys` and names
    them in `warning`; those keys keep their current values.

    Args:
        filename: Name of the backup file to restore from
        db: Database session

    Returns:
        Success message with details about restore operation
    """
    # Before the try: its broad excepts must not see the refusal (R2-2).
    await ensure_secrets_encrypted(db)
    try:
        backup_service = get_backup_service()

        # Determine backup type from filename
        if filename.endswith(".json"):
            # Settings backup (works on all backends)
            details = await backup_service.restore_settings_backup(filename, db)

            response: dict[str, Any] = {
                "success": True,
                "message": f"Settings restored successfully from {filename}",
                "details": details,
            }
            if skipped := details["skipped_secret_keys"]:
                response["warning"] = _skipped_secrets_warning(skipped)
            return response
        elif filename.endswith(".tar.gz"):
            # Full backup restore — guard PostgreSQL
            if not is_sqlite:
                raise HTTPException(
                    status_code=501,
                    detail=(
                        "PostgreSQL restore is not supported via the API. "
                        "To restore, stop the application and run: "
                        "pg_restore --clean --if-exists --no-owner --no-privileges "
                        "-d <dbname> mygarage.pgdump"
                    ),
                )

            details = await backup_service.restore_full_backup(filename)

            return {
                "success": True,
                "message": "Restore staged. Restart MyGarage to finish.",
                "details": details,
                "warning": (
                    "Until it restarts, MyGarage keeps running on the current data, "
                    "and anything changed before the restart is replaced by the backup."
                ),
            }
        else:
            raise HTTPException(status_code=400, detail="Invalid backup file type")

    except HTTPException:
        raise
    except RestoreInProgressError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except AuthSettingsConflictError as e:
        raise HTTPException(status_code=409, detail=e.detail)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        logger.error("Permission denied restoring backup: %s", e)
        raise HTTPException(
            status_code=403, detail="Permission denied: cannot write to data directory"
        )
    except OSError as e:
        logger.error("File system error restoring backup: %s", e)
        raise HTTPException(status_code=500, detail="Error restoring backup files")


@router.delete("/restore/pending")
async def cancel_pending_restore(
    current_user: User | None = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Cancel a full restore staged for the next start; the current data stays.

    404 when nothing is staged, so a stale Backup tab finds out the restore was cancelled
    elsewhere or already applied by a restart. 409 while a restore is half applied.
    """
    try:
        await get_backup_service().cancel_pending_restore()
    except RestoreInProgressError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except OSError as e:
        logger.error("File system error cancelling the staged restore: %s", e)
        raise HTTPException(status_code=500, detail="Error removing the staged restore")
    return {"success": True, "message": "Restore cancelled; the current data stays."}


@router.post("/upload")
async def upload_backup(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Upload and save a backup file.

    Args:
        file: Uploaded backup file
        db: Database session (for validation)

    Returns:
        Metadata about the uploaded backup file
    """
    from datetime import datetime

    try:
        backup_service = get_backup_service()
        backup_service.ensure_backup_dir()

        # Validate filename exists
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")

        # Validate file type
        if not (file.filename.endswith(".json") or file.filename.endswith(".tar.gz")):
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Must be .json (settings) or .tar.gz (full backup)",
            )

        # Check file size BEFORE reading into memory to prevent DoS
        max_backup_size = 100 * 1024 * 1024  # 100MB max for backups
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()
        file.file.seek(0)  # Seek back to beginning

        if file_size > max_backup_size:
            raise HTTPException(
                status_code=413,
                detail=f"File size exceeds maximum of {max_backup_size // (1024 * 1024)}MB",
            )

        # Determine backup type and generate standardized filename
        # This ensures uploaded files appear in the backup list
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        if file.filename.endswith(".json"):
            backup_type = "settings"
            safe_filename = f"mygarage-settings-uploaded-{timestamp}.json"
        else:
            backup_type = "full"
            safe_filename = f"mygarage-full-uploaded-{timestamp}.tar.gz"

        backup_path = BACKUP_DIR / safe_filename

        # Now read and validate file content
        content = await file.read()

        # Validate JSON backups
        if backup_type == "settings":
            import json

            # ValueError, not JSONDecodeError: non-UTF-8 bytes and an int past
            # 4300 digits raise its other subclasses.
            try:
                backup_data = json.loads(content)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid JSON file")
            # The shape the restore checks for, so a bad file never lands in the list.
            if not isinstance(backup_data, dict) or not isinstance(
                backup_data.get("settings"), list
            ):
                raise HTTPException(status_code=400, detail="Invalid backup file structure")

        # Write to backup directory
        with open(backup_path, "wb") as f:
            f.write(content)

        logger.info(
            "Uploaded backup: %s (original: %s)", safe_filename, sanitize_for_log(file.filename)
        )

        # Get file stats
        stat = backup_path.stat()

        return {
            "success": True,
            "message": "Backup uploaded successfully",
            "backup": {
                "filename": safe_filename,
                "type": backup_type,
                "size_mb": round(stat.st_size / 1024 / 1024, 4 if backup_type == "settings" else 2),
                "created": utc_from_timestamp(stat.st_mtime).isoformat(),
            },
        }
    except HTTPException:
        raise
    except PermissionError as e:
        logger.error("Permission denied uploading backup: %s", e)
        raise HTTPException(
            status_code=403,
            detail="Permission denied: cannot write to backup directory",
        )
    except OSError as e:
        logger.error("File system error uploading backup: %s", e)
        raise HTTPException(status_code=500, detail="Error saving backup file")


@router.delete("/{filename}")
async def delete_backup(
    filename: str, current_user: User | None = Depends(get_current_admin_user)
) -> dict[str, Any]:
    """Delete a backup file.

    Safety backups cannot be deleted to prevent accidental data loss.

    Args:
        filename: Name of the backup file to delete

    Returns:
        Success message
    """
    try:
        backup_service = get_backup_service()
        backup_service.delete_backup(filename)

        return {"success": True, "message": f"Backup {filename} deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        logger.error("Permission denied deleting backup: %s", e)
        raise HTTPException(status_code=403, detail="Permission denied: cannot delete backup file")
    except OSError as e:
        logger.error("File system error deleting backup: %s", e)
        raise HTTPException(status_code=500, detail="Error deleting backup file")
