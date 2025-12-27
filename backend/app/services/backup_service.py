"""Backup service for settings and full data backups."""

import os
import json
import tarfile
import shutil
import logging
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class BackupService:
    """Service for creating and managing backups."""

    _SAFE_FILE_ENTRIES = {"mygarage.db", "mygarage.db-wal", "mygarage.db-shm"}
    _SAFE_DIR_ROOTS = {"photos", "documents", "attachments"}

    def __init__(self, backup_dir: Path, database_path: Path, data_dir: Path):
        """Initialize backup service.

        Args:
            backup_dir: Directory to store backups
            database_path: Path to SQLite database file
            data_dir: Path to data directory containing photos, documents, etc.
        """
        self.backup_dir = backup_dir
        self.database_path = database_path
        self.data_dir = data_dir

    def ensure_backup_dir(self):
        """Ensure backup directory exists."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def get_database_stats(self) -> Dict[str, Any]:
        """Get database file statistics.

        Returns:
            Dictionary with database statistics
        """
        try:
            if self.database_path.exists():
                stat = self.database_path.stat()
                return {
                    "path": str(self.database_path),
                    "size_mb": round(stat.st_size / 1024 / 1024, 2),
                    "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "exists": True,
                }
            return {
                "path": str(self.database_path),
                "size_mb": 0,
                "last_modified": None,
                "exists": False,
            }
        except Exception as e:
            logger.error("Error getting database stats: %s", e)
            return {
                "path": str(self.database_path),
                "size_mb": 0,
                "last_modified": None,
                "exists": False,
                "error": str(e),
            }

    def get_backup_files(self, backup_type: str = "all") -> List[Dict[str, Any]]:
        """Get list of backup files with metadata.

        Args:
            backup_type: Type of backups to list - "settings", "full", or "all"

        Returns:
            List of backup file metadata
        """
        self.ensure_backup_dir()
        backups = []

        try:
            # Get settings backups (JSON files)
            if backup_type in ["settings", "all"]:
                for backup_file in self.backup_dir.glob("mygarage-settings-*.json"):
                    stat = backup_file.stat()
                    backups.append(
                        {
                            "filename": backup_file.name,
                            "type": "settings",
                            "size_mb": round(stat.st_size / 1024 / 1024, 4),
                            "size_bytes": stat.st_size,
                            "created": datetime.fromtimestamp(
                                stat.st_mtime
                            ).isoformat(),
                            "is_safety": "safety" in backup_file.name.lower(),
                        }
                    )

            # Get full backups (tar.gz files)
            if backup_type in ["full", "all"]:
                for backup_file in self.backup_dir.glob("mygarage-full-*.tar.gz"):
                    stat = backup_file.stat()
                    backups.append(
                        {
                            "filename": backup_file.name,
                            "type": "full",
                            "size_mb": round(stat.st_size / 1024 / 1024, 2),
                            "size_bytes": stat.st_size,
                            "created": datetime.fromtimestamp(
                                stat.st_mtime
                            ).isoformat(),
                            "is_safety": "safety" in backup_file.name.lower(),
                        }
                    )

        except Exception as e:
            logger.error("Error listing backup files: %s", e)

        # Sort by created date (newest first)
        backups.sort(key=lambda x: x["created"], reverse=True)
        return backups

    async def create_settings_backup(self, db: AsyncSession) -> Dict[str, Any]:
        """Create a backup of all settings.

        Args:
            db: Database session

        Returns:
            Metadata about created backup
        """
        self.ensure_backup_dir()

        # Get all settings from database
        settings = await SettingsService.get_all(db)

        # Build backup data structure
        backup_data = {
            "version": "2.0",
            "type": "settings",
            "exported_at": datetime.now().isoformat(),
            "settings": [
                {
                    "key": s.key,
                    "value": s.value,
                    "category": s.category,
                    "description": s.description,
                    "encrypted": s.encrypted,
                }
                for s in settings
            ],
        }

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        filename = f"mygarage-settings-{timestamp}.json"
        backup_path = self.backup_dir / filename

        # Write backup file
        with open(backup_path, "w") as f:
            json.dump(backup_data, f, indent=2)

        logger.info("Created settings backup: %s", filename)

        # Get file stats
        stat = backup_path.stat()

        return {
            "filename": filename,
            "type": "settings",
            "size_mb": round(stat.st_size / 1024 / 1024, 4),
            "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }

    async def create_full_backup(self) -> Dict[str, Any]:
        """Create a full backup including database and all uploaded files.

        Returns:
            Metadata about created backup
        """
        self.ensure_backup_dir()

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        filename = f"mygarage-full-{timestamp}.tar.gz"
        backup_path = self.backup_dir / filename

        logger.info("Creating full backup: %s", filename)

        # Create tar.gz archive
        with tarfile.open(backup_path, "w:gz") as tar:
            # Add database file
            if self.database_path.exists():
                tar.add(self.database_path, arcname="mygarage.db")
                logger.info("Added database to backup: %s", self.database_path)

            # Add WAL file if it exists (for SQLite WAL mode)
            wal_path = Path(str(self.database_path) + "-wal")
            if wal_path.exists():
                tar.add(wal_path, arcname="mygarage.db-wal")
                logger.info("Added WAL file to backup: %s", wal_path)

            # Add SHM file if it exists (for SQLite WAL mode)
            shm_path = Path(str(self.database_path) + "-shm")
            if shm_path.exists():
                tar.add(shm_path, arcname="mygarage.db-shm")
                logger.info("Added SHM file to backup: %s", shm_path)

            # Add photos directory if it exists
            photos_dir = self.data_dir / "photos"
            if photos_dir.exists() and any(photos_dir.iterdir()):
                tar.add(photos_dir, arcname="photos")
                logger.info("Added photos directory to backup")

            # Add documents directory if it exists
            documents_dir = self.data_dir / "documents"
            if documents_dir.exists() and any(documents_dir.iterdir()):
                tar.add(documents_dir, arcname="documents")
                logger.info("Added documents directory to backup")

            # Add attachments directory if it exists
            attachments_dir = self.data_dir / "attachments"
            if attachments_dir.exists() and any(attachments_dir.iterdir()):
                tar.add(attachments_dir, arcname="attachments")
                logger.info("Added attachments directory to backup")

        logger.info("Created full backup: %s", filename)

        # Get file stats
        stat = backup_path.stat()

        return {
            "filename": filename,
            "type": "full",
            "size_mb": round(stat.st_size / 1024 / 1024, 2),
            "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }

    async def restore_settings_backup(
        self, filename: str, db: AsyncSession, create_safety: bool = True
    ) -> Dict[str, Any]:
        """Restore settings from a backup file.

        Args:
            filename: Name of backup file to restore
            db: Database session
            create_safety: Whether to create a safety backup first

        Returns:
            Details about restore operation
        """
        backup_path = self.backup_dir / filename

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {filename}")

        # Create safety backup first if requested
        safety_filename = None
        if create_safety:
            timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            safety_filename = f"mygarage-settings-safety-{timestamp}.json"

            # Get current settings for safety backup
            current_settings = await SettingsService.get_all(db)
            safety_data = {
                "version": "2.0",
                "type": "settings",
                "exported_at": datetime.now().isoformat(),
                "note": f"Safety backup created before restoring from {filename}",
                "settings": [
                    {
                        "key": s.key,
                        "value": s.value,
                        "category": s.category,
                        "description": s.description,
                        "encrypted": s.encrypted,
                    }
                    for s in current_settings
                ],
            }

            safety_path = self.backup_dir / safety_filename
            with open(safety_path, "w") as f:
                json.dump(safety_data, f, indent=2)

            logger.info("Created safety backup: %s", safety_filename)

        # Read and validate backup file
        with open(backup_path, "r") as f:
            backup_data = json.load(f)

        # Validate backup structure
        if "settings" not in backup_data:
            raise ValueError("Invalid backup file structure: missing 'settings' key")

        if not isinstance(backup_data["settings"], list):
            raise ValueError("Invalid backup file format: 'settings' must be a list")

        # Restore settings
        restored_count = 0
        for setting_data in backup_data["settings"]:
            try:
                key = setting_data.get("key")
                value = setting_data.get("value")

                if not key:
                    logger.warning("Skipping setting with no key: %s", setting_data)
                    continue

                # Update setting in database
                await SettingsService.set(
                    db,
                    key,
                    value,
                    category=setting_data.get("category"),
                    description=setting_data.get("description"),
                    encrypted=setting_data.get("encrypted"),
                )
                restored_count += 1

            except Exception as e:
                logger.error(
                    "Error restoring setting %s: %s", setting_data.get("key"), e
                )
                # Continue with other settings

        await db.commit()

        logger.info("Restored %s settings from %s", restored_count, filename)

        return {
            "restored_count": restored_count,
            "safety_backup": safety_filename,
            "source_backup": filename,
        }

    async def restore_full_backup(
        self, filename: str, create_safety: bool = True
    ) -> Dict[str, Any]:
        """Restore from a full backup file.

        WARNING: This will overwrite the current database and all files!

        Args:
            filename: Name of backup file to restore
            create_safety: Whether to create a safety backup first

        Returns:
            Details about restore operation
        """
        backup_path = self.backup_dir / filename

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {filename}")

        # Create safety backup of current database first if requested
        safety_filename = None
        if create_safety:
            timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            safety_filename = f"mygarage-full-safety-{timestamp}.tar.gz"
            safety_path = self.backup_dir / safety_filename

            logger.info("Creating safety backup: %s", safety_filename)

            with tarfile.open(safety_path, "w:gz") as tar:
                if self.database_path.exists():
                    tar.add(self.database_path, arcname="mygarage.db")

                # Also backup current files
                for dir_name in ["photos", "documents", "attachments"]:
                    dir_path = self.data_dir / dir_name
                    if dir_path.exists() and any(dir_path.iterdir()):
                        tar.add(dir_path, arcname=dir_name)

            logger.info("Created safety backup: %s", safety_filename)

        # Extract backup
        logger.info("Restoring full backup from: %s", filename)

        with tarfile.open(backup_path, "r:gz") as tar:
            members = tar.getmembers()
            self._validate_backup_members(members)

            # Clear existing directories only after validation succeeds
            for dir_name in self._SAFE_DIR_ROOTS:
                target_dir = self.data_dir / dir_name
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                target_dir.mkdir(parents=True, exist_ok=True)

            for member in members:
                normalized_parts = self._normalize_member_parts(member.name)
                if not normalized_parts:
                    continue

                normalized_name = "/".join(normalized_parts)
                root = normalized_parts[0]

                if normalized_name in self._SAFE_FILE_ENTRIES:
                    destination_root = self.database_path.parent
                elif root in self._SAFE_DIR_ROOTS:
                    destination_root = self.data_dir
                else:
                    continue

                self._safe_extract_member(
                    tar,
                    member,
                    destination_root,
                    normalized_parts,
                )

        logger.info("Successfully restored full backup from %s", filename)

        return {
            "safety_backup": safety_filename,
            "source_backup": filename,
            "message": "Full backup restored successfully. Application restart may be required.",
        }

    def validate_filename(self, filename: str) -> Path:
        """Validate and sanitize filename to prevent path traversal.

        Args:
            filename: Filename to validate

        Returns:
            Safe path to backup file

        Raises:
            ValueError: If filename is invalid or unsafe
        """
        # Remove any path separators
        safe_name = os.path.basename(filename)

        # Check file extension
        if not (safe_name.endswith(".json") or safe_name.endswith(".tar.gz")):
            raise ValueError("Invalid file type. Must be .json or .tar.gz")

        # Check for suspicious patterns
        if ".." in safe_name or "/" in safe_name or "\\" in safe_name:
            raise ValueError("Invalid filename")

        backup_path = self.backup_dir / safe_name

        # Ensure the resolved path is within backup directory
        if not str(backup_path.resolve()).startswith(str(self.backup_dir.resolve())):
            raise ValueError("Invalid file path")

        return backup_path

    def delete_backup(self, filename: str) -> None:
        """Delete a backup file.

        Safety backups cannot be deleted to prevent accidental data loss.

        Args:
            filename: Name of backup file to delete

        Raises:
            ValueError: If trying to delete a safety backup
            FileNotFoundError: If backup file doesn't exist
        """
        # Prevent deletion of safety backups
        if "safety" in filename.lower():
            raise ValueError(
                "Cannot delete safety backups. They are created automatically during restore operations."
            )

        backup_path = self.validate_filename(filename)

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {filename}")

        # Delete the file
        backup_path.unlink()

        logger.info("Deleted backup: %s", filename)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _normalize_member_parts(self, member_name: str) -> List[str]:
        """Normalize tar member names to POSIX parts without '.' entries."""
        if not member_name:
            return []
        path = PurePosixPath(member_name)
        parts = [str(part) for part in path.parts if part not in ("", ".")]
        return parts

    def _validate_backup_members(self, members: List[tarfile.TarInfo]) -> None:
        """Ensure every tar entry stays within the expected directories."""
        for member in members:
            parts = self._normalize_member_parts(member.name)
            if not parts:
                raise ValueError("Invalid member name in backup archive")
            if any(part == ".." for part in parts):
                raise ValueError(f"Unsafe relative path detected: {member.name}")

            normalized_name = "/".join(parts)
            root = parts[0]

            if normalized_name in self._SAFE_FILE_ENTRIES:
                continue

            if root in self._SAFE_DIR_ROOTS:
                continue

            raise ValueError(f"Unexpected entry in backup archive: {member.name}")

    def _safe_extract_member(
        self,
        tar: tarfile.TarFile,
        member: tarfile.TarInfo,
        destination_root: Path,
        target_parts: List[str],
    ) -> None:
        """Safely extract member to destination ensuring it stays inside root."""
        destination_root = destination_root.resolve()
        target_path = destination_root.joinpath(*target_parts).resolve()

        if not str(target_path).startswith(str(destination_root)):
            raise ValueError(f"Unsafe extraction path for {member.name}")

        if member.isdir():
            target_path.mkdir(parents=True, exist_ok=True)
            return

        target_path.parent.mkdir(parents=True, exist_ok=True)
        extracted = tar.extractfile(member)
        if extracted is None:
            raise ValueError(f"Failed to read {member.name} from archive")

        with extracted, open(target_path, "wb") as dest_file:
            shutil.copyfileobj(extracted, dest_file)
