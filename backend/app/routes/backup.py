"""Backup API endpoints for settings and full data backup/restore."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services.auth import require_auth
from app.services.backup_service import BackupService

router = APIRouter(prefix="/api/backup", tags=["Backup"])
logger = logging.getLogger(__name__)

# Backup directory configuration
BACKUP_DIR = settings.data_dir / "backups"
DATABASE_PATH = Path(settings.database_url.replace("sqlite+aiosqlite:///", ""))


def get_backup_service() -> BackupService:
    """Get backup service instance."""
    return BackupService(
        backup_dir=BACKUP_DIR, database_path=DATABASE_PATH, data_dir=settings.data_dir
    )


@router.get("/stats")
async def get_stats(
    current_user: User | None = Depends(require_auth),
) -> dict[str, Any]:
    """Get database and backup statistics.

    Returns:
        Statistics about database and backups including sizes, counts, and paths.
    """
    try:
        backup_service = get_backup_service()
        db_stats = backup_service.get_database_stats()

        settings_backups = backup_service.get_backup_files("settings")
        full_backups = backup_service.get_backup_files("full")

        settings_backup_size = sum(b["size_bytes"] for b in settings_backups)
        full_backup_size = sum(b["size_bytes"] for b in full_backups)

        return {
            "database": db_stats,
            "settings_backups": {
                "count": len(settings_backups),
                "total_size_mb": round(settings_backup_size / 1024 / 1024, 4),
            },
            "full_backups": {
                "count": len(full_backups),
                "total_size_mb": round(full_backup_size / 1024 / 1024, 2),
            },
            "backup_directory": str(BACKUP_DIR),
            "wal_mode_enabled": Path(f"{DATABASE_PATH}-wal").exists(),
        }
    except OSError as e:
        logger.error("File system error getting stats: %s", e)
        raise HTTPException(status_code=500, detail="Error accessing backup files")


@router.get("/list")
async def list_backups(
    backup_type: str = "all", current_user: User | None = Depends(require_auth)
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
    current_user: User | None = Depends(require_auth),
) -> dict[str, Any]:
    """Create a new backup of all settings.

    Args:
        db: Database session

    Returns:
        Metadata about the created backup file
    """
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
    current_user: User | None = Depends(require_auth),
) -> dict[str, Any]:
    """Create a full backup including database and all uploaded files.

    This may take several minutes depending on the size of your data.

    Returns:
        Metadata about the created backup file
    """
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
    except OSError as e:
        logger.error("File system error creating full backup: %s", e)
        raise HTTPException(status_code=500, detail="Error creating backup archive")


@router.get("/download/{filename}")
async def download_backup(filename: str, current_user: User | None = Depends(require_auth)):
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
    current_user: User | None = Depends(require_auth),
) -> dict[str, Any]:
    """Restore settings from a backup file.

    This creates a safety backup before restoring.

    Args:
        filename: Name of the backup file to restore from
        db: Database session

    Returns:
        Success message with details about restore operation
    """
    try:
        backup_service = get_backup_service()

        # Determine backup type from filename
        if filename.endswith(".json"):
            # Settings backup
            details = await backup_service.restore_settings_backup(filename, db)

            return {
                "success": True,
                "message": f"Settings restored successfully from {filename}",
                "details": details,
            }
        elif filename.endswith(".tar.gz"):
            # Full backup
            details = await backup_service.restore_full_backup(filename)

            return {
                "success": True,
                "message": f"Full backup restored successfully from {filename}",
                "details": details,
                "warning": "Application restart may be required for changes to take effect.",
            }
        else:
            raise HTTPException(status_code=400, detail="Invalid backup file type")

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


@router.post("/upload")
async def upload_backup(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> dict[str, Any]:
    """Upload and save a backup file.

    Args:
        file: Uploaded backup file
        db: Database session (for validation)

    Returns:
        Metadata about the uploaded backup file
    """
    try:
        backup_service = get_backup_service()
        backup_service.ensure_backup_dir()

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

        # Sanitize filename
        import os
        from datetime import datetime

        safe_filename = os.path.basename(file.filename)

        # Add timestamp if filename already exists
        backup_path = BACKUP_DIR / safe_filename
        if backup_path.exists():
            timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            if safe_filename.endswith(".json"):
                name_part = safe_filename.replace(".json", "")
                safe_filename = f"{name_part}-uploaded-{timestamp}.json"
            else:
                name_part = safe_filename.replace(".tar.gz", "")
                safe_filename = f"{name_part}-uploaded-{timestamp}.tar.gz"
            backup_path = BACKUP_DIR / safe_filename

        # Now read and validate file content
        content = await file.read()

        # Validate JSON backups
        if safe_filename.endswith(".json"):
            import json

            try:
                backup_data = json.loads(content)
                if "settings" not in backup_data or not isinstance(backup_data["settings"], list):
                    raise HTTPException(status_code=400, detail="Invalid backup file structure")
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON file")

        # Write to backup directory
        with open(backup_path, "wb") as f:
            f.write(content)

        logger.info("Uploaded backup: %s", safe_filename)

        # Get file stats
        stat = backup_path.stat()
        backup_type = "settings" if safe_filename.endswith(".json") else "full"

        return {
            "success": True,
            "message": "Backup uploaded successfully",
            "backup": {
                "filename": safe_filename,
                "type": backup_type,
                "size_mb": round(stat.st_size / 1024 / 1024, 4 if backup_type == "settings" else 2),
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
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
    filename: str, current_user: User | None = Depends(require_auth)
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
