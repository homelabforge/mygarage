"""Backup service for settings and full data backups."""

import asyncio
import contextlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlparse
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import restore_staging
from app.services.oidc.config import OIDC_REDIRECT_URI_KEY, checked_redirect_uri
from app.services.settings_service import SettingsService
from app.utils.default_unit_prefs import (
    DEFAULT_UNIT_PREFS_KEY,
    validate_default_unit_prefs_value,
)
from app.utils.household_time import EFFECTIVE_TIMEZONE_KEY, TIMEZONE_SETTING_KEY
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class BackupService:
    """Service for creating and managing backups."""

    _SQLITE_DB_ENTRIES = ("mygarage.db", "mygarage.db-wal", "mygarage.db-shm")
    _SAFE_FILE_ENTRIES = {*_SQLITE_DB_ENTRIES, "mygarage.pgdump"}
    _SAFE_DIR_ROOTS = {"photos", "documents", "attachments"}

    def __init__(
        self,
        backup_dir: Path,
        database_path: Path | None,
        data_dir: Path,
        database_url: str | None = None,
        is_sqlite: bool = True,
    ):
        """Initialize backup service.

        Args:
            backup_dir: Directory to store backups
            database_path: Path to SQLite database file (None for PostgreSQL)
            data_dir: Path to data directory containing photos, documents, etc.
            database_url: Database connection URL (needed for pg_dump)
            is_sqlite: Whether the database is SQLite
        """
        self.backup_dir = backup_dir
        self.database_path = database_path
        self.data_dir = data_dir
        self.database_url = database_url
        self.is_sqlite = is_sqlite

    def ensure_backup_dir(self):
        """Ensure backup directory exists."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _parse_pg_url(self) -> dict[str, str]:
        """Parse PostgreSQL connection parameters from the database URL.

        Returns:
            Dictionary with host, port, user, password, dbname
        """
        if not self.database_url:
            raise RuntimeError("No database URL configured for PostgreSQL backup")

        # Convert asyncpg URL to standard format for parsing
        url = self.database_url.replace("postgresql+asyncpg://", "postgresql://")
        parsed = urlparse(url)

        return {
            "host": parsed.hostname or "localhost",
            "port": str(parsed.port or 5432),
            "user": unquote(parsed.username or "postgres"),
            "password": unquote(parsed.password or ""),
            # 2.1's engine decodes the database name too, so pg_dump has to match it.
            "dbname": unquote(parsed.path.lstrip("/")) or "mygarage",
        }

    def _snapshot_sqlite(self, output_path: Path) -> None:
        """Write a consistent point-in-time snapshot of the SQLite database.

        Uses the SQLite Online Backup API instead of copying the live file:
        a raw copy of a WAL-mode database misses committed rows that still
        live in the -wal sidecar and can tear entirely if a checkpoint runs
        mid-copy. The snapshot is self-contained — restoring it never
        depends on wal/shm files.
        """
        if not self.database_path:
            raise RuntimeError("No SQLite database path configured for snapshot")

        # Quote the path so a #, ? or % in it stays part of the path, not the URI.
        source = sqlite3.connect(f"file:{quote(str(self.database_path))}?mode=ro", uri=True)
        try:
            dest = sqlite3.connect(output_path)
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()

    def _pg_dump(self, output_path: Path) -> None:
        """Run pg_dump to create a PostgreSQL database dump.

        Args:
            output_path: Path to write the dump file

        Raises:
            RuntimeError: If pg_dump fails
        """
        pg = self._parse_pg_url()
        env = {**os.environ, "PGPASSWORD": pg["password"]}

        try:
            subprocess.run(
                [
                    "pg_dump",
                    "-h",
                    pg["host"],
                    "-p",
                    pg["port"],
                    "-U",
                    pg["user"],
                    "-d",
                    pg["dbname"],
                    "--format=custom",
                    "-f",
                    str(output_path),
                ],
                env=env,
                check=True,
                capture_output=True,
                timeout=300,
            )
            logger.info("pg_dump completed successfully: %s", output_path)
        except FileNotFoundError:
            raise RuntimeError(
                "pg_dump not found. Ensure postgresql-client is installed in the container."
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace")
            logger.error("pg_dump failed: %s", stderr)
            raise RuntimeError(f"Database backup failed: {stderr[:500]}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Database backup timed out after 5 minutes")

    def get_database_stats(self, db_size_bytes: int | None = None) -> dict[str, Any]:
        """Get database statistics.

        Args:
            db_size_bytes: Pre-queried database size in bytes (for PostgreSQL,
                          queried via SQL in the route handler)

        Returns:
            Dictionary with database statistics
        """
        if self.is_sqlite:
            if self.database_path is None:
                # In-memory: nothing on disk to size, but it's still SQLite, not PostgreSQL.
                return {"path": "in-memory", "size_mb": 0, "last_modified": None, "exists": False}
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
        else:
            # PostgreSQL: use pre-queried size from route handler
            size_mb = round(db_size_bytes / (1024 * 1024), 2) if db_size_bytes else 0.0
            return {
                "path": "PostgreSQL",
                "size_mb": size_mb,
                "last_modified": None,
                "exists": True,
            }

    def get_backup_files(self, backup_type: str = "all") -> list[dict[str, Any]]:
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
                            "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
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
                            "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            "is_safety": "safety" in backup_file.name.lower(),
                        }
                    )

        except Exception as e:
            logger.error("Error listing backup files: %s", e)

        # Sort by created date (newest first)
        backups.sort(key=lambda x: x["created"], reverse=True)
        return backups

    async def create_settings_backup(self, db: AsyncSession) -> dict[str, Any]:
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

    async def create_full_backup(self) -> dict[str, Any]:
        """Create a full backup including database and all uploaded files.

        For SQLite: archives a consistent snapshot of the database file (none for in-memory).
        For PostgreSQL: runs pg_dump and archives the dump file.

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
            if self.is_sqlite:
                # SQLite: archive a consistent Online-Backup-API snapshot, not
                # the live file. The snapshot is self-contained, so no -wal or
                # -shm members are needed (restore still accepts them from
                # older archives).
                if self.database_path is None:
                    logger.warning("in-memory SQLite has no file to back up")
                elif self.database_path.exists():
                    with tempfile.TemporaryDirectory() as tmpdir:
                        snapshot_path = Path(tmpdir) / "mygarage.db"
                        self._snapshot_sqlite(snapshot_path)
                        tar.add(snapshot_path, arcname="mygarage.db")
                    logger.info("Added database snapshot to backup: %s", self.database_path)
            else:
                # PostgreSQL: run pg_dump to temp file, add to archive
                with tempfile.TemporaryDirectory() as tmpdir:
                    dump_path = Path(tmpdir) / "mygarage.pgdump"
                    self._pg_dump(dump_path)
                    tar.add(dump_path, arcname="mygarage.pgdump")
                    logger.info("Added PostgreSQL dump to backup")

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
    ) -> dict[str, Any]:
        """Restore settings from a backup file.

        Args:
            filename: Name of backup file to restore
            db: Database session
            create_safety: Whether to create a safety backup first

        Returns:
            Details about restore operation
        """
        # A name in the backup folder, as download and delete take it: `../` can't reach past it.
        backup_path = self.validate_filename(filename)

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path.name}")

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
        with open(backup_path) as f:
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
                    logger.warning("Skipping setting with no key during restore")
                    continue

                # ★ THE FOURTH WRITER OF A SETTINGS VALUE, and the only one that
                # is not on `app.routes.settings.router`. That router refuses a
                # `default_unit_prefs` the reader could not use, on all three of
                # its write paths; an uploaded backup reaches
                # `SettingsService.set` directly, so a hand-edited or pre-093
                # file was a back door onto the exact row that validator exists
                # to protect. `parse_default_unit_prefs` degrades WHOLE and only
                # logs, so an unreadable value here silently hands every
                # anonymous client the imperial preset: on a UK or metric
                # instance, about a 20 percent error in every volume, price per
                # volume and fuel economy, with a success response on top.
                #
                # SKIPPED, NOT FATAL. A restore that aborts partway leaves the
                # instance half-configured, which is worse than one row not
                # coming back; the row reseeds from
                # `default_unit_prefs_for_instance` on the next boot if it is
                # missing, and keeps its current value if it is not.
                if key == EFFECTIVE_TIMEZONE_KEY:
                    logger.warning(
                        "Skipping %s during restore: computed, never stored",
                        sanitize_for_log(key),
                    )
                    continue

                if key == TIMEZONE_SETTING_KEY and value:
                    try:
                        ZoneInfo(value)
                    except Exception:
                        logger.warning(
                            "Skipping %s during restore: not a valid IANA time zone",
                            sanitize_for_log(key),
                        )
                        continue

                # The SSO settings re-send this pin with every save, so a bad
                # one would 422 all of them, the auth-mode switch included.
                if key == OIDC_REDIRECT_URI_KEY:
                    try:
                        checked_redirect_uri(value or "")
                    except ValueError:
                        logger.warning(
                            "Skipping %s during restore: not a blank or absolute http(s) URL",
                            sanitize_for_log(key),
                        )
                        continue

                if key == DEFAULT_UNIT_PREFS_KEY:
                    try:
                        validate_default_unit_prefs_value(value)
                    except ValueError as exc:
                        logger.warning(
                            "Skipping %s during restore: value %s",
                            sanitize_for_log(key),
                            sanitize_for_log(str(exc)),
                        )
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
                logger.error("Error restoring setting %s: %s", setting_data.get("key"), e)
                # Continue with other settings

        await db.commit()

        logger.info("Restored %s settings from %s", restored_count, sanitize_for_log(filename))

        return {
            "restored_count": restored_count,
            "safety_backup": safety_filename,
            "source_backup": filename,
        }

    async def restore_full_backup(
        self, filename: str, create_safety: bool = True
    ) -> dict[str, Any]:
        """Stage a full backup (SQLite only); MyGarage swaps it in at its next start.

        Nothing live changes here but the new safety backup. PostgreSQL restores with
        pg_restore instead.

        Raises:
            RuntimeError: on PostgreSQL
            ValueError: in-memory SQLite, a bad name, a media folder on another filesystem,
                a live database the safety archive can't read, an archive tarfile can't read,
                an unexpected entry or no mygarage.db in it, or a database SQLite can't open
                or finds damaged
            FileNotFoundError: no such backup in the backup folder
            RestoreInProgressError: a restore is half applied (defensive)
        """
        if not self.is_sqlite:
            raise RuntimeError(
                "PostgreSQL restore is not supported via the API. "
                "Use pg_restore during a maintenance window."
            )
        if self.database_path is None:
            raise ValueError("In-memory SQLite has no database file to restore into")
        # A name in the backup folder, as download and delete take it: `../` can't reach past it.
        backup_path = self.validate_filename(filename)
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path.name}")
        self._refuse_media_on_another_filesystem()
        # Seconds to minutes of tar, gzip and SQLite work: in a thread, so the app keeps answering.
        return await asyncio.to_thread(
            self._stage_full_backup, backup_path, self.database_path, create_safety
        )

    def _refuse_media_on_another_filesystem(self) -> None:
        """The start swaps folders by renaming them, which can't cross filesystems: refuse that layout now."""
        device = os.stat(self.data_dir).st_dev
        for name in restore_staging.MEDIA_DIRS:
            folder = self.data_dir / name
            if folder.exists() and os.stat(folder).st_dev != device:
                raise ValueError(
                    f"{folder} is on a different filesystem from {self.data_dir}. A full restore "
                    "swaps folders by renaming them, so they have to share one; restore this "
                    "backup by hand instead."
                )

    def _stage_full_backup(
        self, backup_path: Path, database_file: Path, create_safety: bool
    ) -> dict[str, Any]:
        """The restore's blocking half. Under the restore lock, so two restores never interleave.

        A refusal before the discard (the safety archive) keeps an earlier staging; one after it
        (the archive's own checks) leaves nothing staged. The safety archive is also the gate: a
        live database the backup API can't read is refused here, not at the start.
        """
        with restore_staging.restore_lock(self.data_dir):
            safety_filename = None
            if create_safety:
                timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
                safety_filename = f"mygarage-full-safety-{timestamp}.tar.gz"
                try:
                    self._write_safety_archive(self.backup_dir / safety_filename)
                except sqlite3.Error as exc:
                    raise ValueError(
                        f"The current database can't be read for the safety backup: {exc}"
                    ) from exc
            logger.info("Staging full backup %s", sanitize_for_log(backup_path.name))
            # A second restore before the restart replaces the first.
            restore_staging.discard_pending_restore(self.data_dir, database_file)
            try:
                self._stage_archive(backup_path, database_file)
                restore_staging.write_manifest(
                    self.data_dir, source_backup=backup_path.name, database_file=database_file
                )
            except Exception:
                # Half a staging is no staging; don't leave one for the next start to find.
                restore_staging.discard_pending_restore(self.data_dir, database_file)
                raise
        logger.info("Staged %s; it applies at the next start", sanitize_for_log(backup_path.name))
        return {
            "safety_backup": safety_filename,
            "source_backup": backup_path.name,
            "message": "Restore staged. Restart MyGarage to finish.",
        }

    def _write_safety_archive(self, archive: Path) -> None:
        """Archive the live data: a snapshot of the database and the three folders.

        The snapshot goes through the SQLite backup API, never a file copy, which under WAL
        misses committed rows. Published durably from a temporary name, so the name only ever
        shows a complete archive that's on disk. A write that fails takes its temporary file
        with it; only a kill leaves one, and the next start writes over it.
        """
        self.ensure_backup_dir()
        partial = archive.with_name(archive.name + ".partial")
        try:
            with tarfile.open(partial, "w:gz") as tar:
                if self.database_path is not None and self.database_path.exists():
                    with tempfile.TemporaryDirectory() as tmpdir:
                        snapshot_path = Path(tmpdir) / "mygarage.db"
                        self._snapshot_sqlite(snapshot_path)
                        tar.add(snapshot_path, arcname="mygarage.db")
                for dir_name in restore_staging.MEDIA_DIRS:
                    dir_path = self.data_dir / dir_name
                    if dir_path.exists() and any(dir_path.iterdir()):
                        tar.add(dir_path, arcname=dir_name)
            restore_staging.publish_file(partial, archive)
        except BaseException:
            # A request's archive is named by the second, so each failed one would leave
            # another .partial behind that nothing lists or cleans up. The cleanup never
            # hides the real error.
            with contextlib.suppress(OSError):
                restore_staging.discard_partial(partial)
            raise
        # Named by the manifest at a start, so sanitized like any name read from disk.
        logger.info("Created safety backup: %s", sanitize_for_log(archive.name))

    def _write_prerestore_archive(self, filename: str) -> None:
        """Archive the data a restore is about to replace, unless it's already there.

        The apply calls this only before its applying marker is down. An archive that's
        already there is kept: if the marker was deleted by hand after the live -wal went,
        it is the only copy of those rows.
        """
        archive = self.validate_filename(filename)
        if not archive.exists():
            self._write_safety_archive(archive)

    def apply_pending_restore(self) -> str | None:
        """Swap in a restore staged by restore_full_backup. Call before anything opens the database."""
        return restore_staging.apply_pending_restore(
            self.data_dir,
            self.database_path,
            backup_dir=self.backup_dir,
            before_swap=self._write_prerestore_archive,
        )

    def pending_restore(self) -> dict[str, str | None] | None:
        """The staged restore, for the Backup tab: its backup's name and when it was staged."""
        return restore_staging.pending_restore(self.data_dir)

    async def cancel_pending_restore(self) -> None:
        """Throw the staged restore away.

        Raises:
            FileNotFoundError: nothing is staged
            RestoreInProgressError: a restore is half applied
        """
        cancelled = await asyncio.to_thread(
            restore_staging.cancel_pending_restore, self.data_dir, self.database_path
        )
        if not cancelled:
            raise FileNotFoundError("No restore is staged")

    def _stage_archive(self, backup_path: Path, database_file: Path) -> None:
        """Check the archive and stage its database and folders, touching nothing live."""
        staging = self.data_dir / restore_staging.STAGING_DIRNAME
        work = staging / "database"
        try:
            with tarfile.open(backup_path, "r:gz") as tar:
                members = tar.getmembers()
                self._validate_backup_members(members)
                names = {"/".join(self._normalize_member_parts(m.name)) for m in members}
                if "mygarage.db" not in names:
                    raise ValueError("This backup has no SQLite database (mygarage.db) to restore")
                # All three, empty if the archive has none: a full restore replaces every folder.
                for name in restore_staging.MEDIA_DIRS:
                    (staging / name).mkdir(parents=True, exist_ok=True)
                for member in members:
                    parts = self._normalize_member_parts(member.name)
                    if "/".join(parts) in ("mygarage.db", "mygarage.db-wal"):
                        # Archive names on purpose: SQLite finds a WAL by its database's name.
                        self._safe_extract_member(tar, member, work, parts)
                    elif parts[0] in self._SAFE_DIR_ROOTS:
                        self._safe_extract_member(
                            tar, member, staging, parts, skip_links_to_no_file=True
                        )
                    # Left out: mygarage.db-shm (a dead process's WAL index; SQLite rebuilds it
                    # from the WAL) and mygarage.pgdump (PostgreSQL's).
        except (tarfile.TarError, EOFError, KeyError, RecursionError) as exc:
            # None of these is an OSError or a ValueError, so without this a truncated file is a
            # 500. KeyError and RecursionError get here from a database member that links to no
            # file. A media one is skipped, but skipping this one could stage an empty database.
            raise ValueError("This backup can't be read as a tar.gz archive") from exc
        self._fold_and_check(work / "mygarage.db")
        shutil.move(work / "mygarage.db", restore_staging.pending_database(database_file))
        shutil.rmtree(work)

    @staticmethod
    def _fold_and_check(database: Path) -> None:
        """Fold any WAL into the file itself, then refuse it if SQLite finds damage.

        integrity_check, not quick_check: only the full check compares each index with its
        table, and a torn raw copy breaks exactly that.
        """
        try:
            conn = sqlite3.connect(database)
            try:
                mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()
                problems = [row[0] for row in conn.execute("PRAGMA integrity_check")]
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"The backup's database can't be opened: {exc}") from exc
        if mode != ("delete",):
            raise ValueError(f"The backup's database kept its write-ahead log ({mode})")
        if problems != ["ok"]:
            raise ValueError(
                f"The backup's database failed SQLite's integrity check: {problems[0]}"
            )

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

        logger.info("Deleted backup: %s", sanitize_for_log(filename))

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _normalize_member_parts(self, member_name: str) -> list[str]:
        """Normalize tar member names to POSIX parts without '.' entries."""
        if not member_name:
            return []
        path = PurePosixPath(member_name)
        parts = [str(part) for part in path.parts if part not in ("", ".")]
        return parts

    def _validate_backup_members(self, members: list[tarfile.TarInfo]) -> None:
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
        target_parts: list[str],
        *,
        skip_links_to_no_file: bool = False,
    ) -> None:
        """Safely extract member to destination ensuring it stays inside root.

        skip_links_to_no_file leaves out a link that doesn't lead to a file in the archive, with
        a WARNING, instead of failing: the backup writer keeps a media symlink as a link, and
        its target was never in the backup.
        """
        destination_root = destination_root.resolve()
        target_path = destination_root.joinpath(*target_parts).resolve()

        if not str(target_path).startswith(str(destination_root)):
            raise ValueError(f"Unsafe extraction path for {member.name}")

        if member.isdir():
            target_path.mkdir(parents=True, exist_ok=True)
            return

        # A link comes out as a copy of what it points at; the restore never makes links.
        is_link = member.issym() or member.islnk()
        try:
            extracted = tar.extractfile(member)
        except KeyError, RecursionError:
            # tarfile reads a link through its target: KeyError when that isn't in the archive,
            # RecursionError when the links loop.
            if not (skip_links_to_no_file and is_link):
                raise
            extracted = None
        if extracted is None and skip_links_to_no_file and is_link:
            logger.warning(
                "Left %s out of the restore: it links to %s, which isn't a file in the backup",
                sanitize_for_log(member.name),
                sanitize_for_log(member.linkname),
            )
            return
        if extracted is None:
            raise ValueError(f"Failed to read {member.name} from archive")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with extracted, open(target_path, "wb") as dest_file:
            shutil.copyfileobj(extracted, dest_file)
