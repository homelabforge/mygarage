"""A full restore is staged while MyGarage runs and swapped in at the next start.

The running app's database can't be swapped out under it: the scheduler, the MQTT subscriber,
the Telegram poller and the request hold pooled connections, and one that still has the old WAL
open can write, or checkpoint old pages, into the new file. So the restore only stages, and the
lifespan swaps it in before anything opens the database. That relies on MyGarage being one
process (Dockerfile: --workers 1, which APScheduler needs too): the lock below keeps restore
operations apart, not another process's database connections.

The layout is a contract between the process that stages and the one that applies, which is a
newer version if the image was updated before the restart:

    <data_dir>/.restore-pending/manifest.json      written last: no manifest, no restore
    <data_dir>/.restore-pending/applying           down from before the first live change until
                                                   after the last: the live data may be half swapped
    <data_dir>/.restore-pending/<folder>           photos, documents, attachments
    <data_dir>/.restore-pending/previous/<folder>  a live folder, set aside mid-swap
    <database file, resolved>.restore-pending      the staged database, one self-contained file
    <data_dir>/.restore-pending.lock               never deleted

Every change is on disk before the next step relies on it. A file's fsync doesn't persist its
name, so the folder holding the name is fsynced too.
"""

import fcntl
import json
import logging
import os
import shutil
import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from app.utils.backup_names import backup_stamp
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

STAGING_DIRNAME = ".restore-pending"
MANIFEST_NAME = "manifest.json"
APPLYING_NAME = "applying"
MANIFEST_FORMAT = 1
MEDIA_DIRS = ("photos", "documents", "attachments")
_PENDING_SUFFIX = ".restore-pending"
_LOCK_NAME = ".restore-pending.lock"


class RestoreInProgressError(RuntimeError):
    """This start can't get past a staged restore; a person has to step in, and its files must stay."""


def pending_database(database_file: Path) -> Path:
    """Where a staged database waits: beside the real file, so the swap is one rename.

    Resolved, because SQLite names the WAL after the real file, and os.replace onto a
    symlink would swap out the link instead of the database.
    """
    target = database_file.resolve()
    return target.with_name(target.name + _PENDING_SUFFIX)


@contextmanager
def restore_lock(data_dir: Path) -> Generator[None]:
    """Staging, cancelling and applying never interleave, not even between threads.

    flock belongs to the open file, not the process, so two threads that each open the lock
    file exclude each other (fcntl.lockf wouldn't). It keeps restore operations apart and
    nothing else: a second MyGarage process would still be unsafe, so there's only ever one.
    """
    with open(data_dir / _LOCK_NAME, "a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield  # closing the file lets the lock go


def _fsync_file(path: Path) -> None:
    """Flush a file's contents to disk."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    """Flush a folder's entries to disk: a file's fsync doesn't persist its name."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace(src: Path, dst: Path) -> None:
    """Rename, then persist both folders before anything relies on it."""
    os.replace(src, dst)
    _fsync_dir(dst.parent)
    if src.parent != dst.parent:
        _fsync_dir(src.parent)


def _unlink(path: Path) -> None:
    """Delete a file and persist that, if it's there; a second call does nothing."""
    if not path.exists() and not path.is_symlink():
        return
    path.unlink()
    _fsync_dir(path.parent)


def _mkdir(path: Path) -> None:
    """Make a folder and persist its name, if it isn't there."""
    if path.is_dir():
        return
    path.mkdir()
    _fsync_dir(path.parent)


def _remove_tree(path: Path) -> None:
    """Delete a folder and everything in it, and persist that."""
    if not path.exists():
        return
    shutil.rmtree(path)
    _fsync_dir(path.parent)


def _fsync_tree(root: Path) -> None:
    """Flush every file and folder under root, deepest first, then root itself."""
    for folder, _subfolders, files in os.walk(root, topdown=False):
        for name in files:
            _fsync_file(Path(folder) / name)
        _fsync_dir(Path(folder))


def publish_file(partial: Path, final: Path) -> None:
    """Give a fully written file its final name, durably: its contents, the rename, its folder."""
    _fsync_file(partial)
    _replace(partial, final)


def discard_partial(partial: Path) -> None:
    """Drop what a failed write left under its temporary name, and persist that."""
    _unlink(partial)


def _write_json(path: Path, data: dict[str, object]) -> None:
    """Write JSON under a temporary name and publish it, so the name only ever shows a whole file."""
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(data, indent=2))
    publish_file(partial, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    """A JSON object from a file, or None when it can't be read as one."""
    try:
        data = json.loads(path.read_text())
    except OSError, ValueError:
        return None
    # A JSON object's keys are always strings.
    return cast("dict[str, Any]", data) if isinstance(data, dict) else None


def write_manifest(data_dir: Path, *, source_backup: str, database_file: Path) -> None:
    """Mark the staging complete: the last step, once everything it vouches for is on disk.

    That's every staged file and folder, the staging folder's own name, and the staged
    database with the folder it sits in, which can be outside data_dir. It also names the
    safety archive the start writes before the swap, so a start that dies and runs again
    looks for the same file.
    """
    staging = data_dir / STAGING_DIRNAME
    staged_db = pending_database(database_file)
    _fsync_tree(staging)
    _fsync_dir(data_dir)
    _fsync_file(staged_db)
    _fsync_dir(staged_db.parent)
    _write_json(
        staging / MANIFEST_NAME,
        {
            "format": MANIFEST_FORMAT,
            "source_backup": source_backup,
            "staged_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "database": str(database_file.resolve()),
            "prerestore_backup": f"mygarage-full-safety-prerestore-{backup_stamp()}.tar.gz",
        },
    )


def pending_restore(data_dir: Path) -> dict[str, str | None] | None:
    """The staged restore the Backup tab shows, or None.

    A manifest that can't be read still counts, with no details, so the tab can offer Cancel.
    """
    manifest_path = data_dir / STAGING_DIRNAME / MANIFEST_NAME
    if not manifest_path.exists():
        return None
    manifest = _read_json(manifest_path) or {}
    source = manifest.get("source_backup")
    staged_at = manifest.get("staged_at")
    return {
        "source_backup": source if isinstance(source, str) else None,
        "staged_at": staged_at if isinstance(staged_at, str) else None,
    }


def discard_pending_restore(data_dir: Path, database_file: Path | None) -> bool:
    """Throw a staged restore away; True if there was one.

    Refused while a restore is half applied, when the staging holds the only copy of what was
    swapped out. The manifest goes first and durably, so a discard cut short still reads as no
    restore. The staged database the manifest names goes too, in case the setting changed.
    """
    staging = data_dir / STAGING_DIRNAME
    if (staging / APPLYING_NAME).exists():
        raise RestoreInProgressError(
            "A restore was interrupted while it was being applied, so its files can't be thrown "
            "away. MyGarage's start-up log says how to finish it or go back."
        )
    recorded = (_read_json(staging / MANIFEST_NAME) or {}).get("database")
    staged_dbs: set[Path] = {pending_database(database_file)} if database_file else set()
    if isinstance(recorded, str):
        staged_dbs.add(pending_database(Path(recorded)))
    found = staging.exists() or any(path.exists() for path in staged_dbs)
    _unlink(staging / MANIFEST_NAME)
    for staged_db in sorted(staged_dbs):
        _unlink(staged_db)
    _remove_tree(staging)
    return found


def cancel_pending_restore(data_dir: Path, database_file: Path | None) -> bool:
    """Throw the staged restore away before the restart; False if none is staged."""
    staging = data_dir / STAGING_DIRNAME
    if not (staging / MANIFEST_NAME).exists() and not (staging / APPLYING_NAME).exists():
        return False  # nothing to cancel, and no lock file made
    with restore_lock(data_dir):
        if not (staging / MANIFEST_NAME).exists() and not (staging / APPLYING_NAME).exists():
            return False
        source = (_read_json(staging / MANIFEST_NAME) or {}).get("source_backup", "unknown")
        discard_pending_restore(data_dir, database_file)
    logger.info("Cancelled the staged restore of %s", sanitize_for_log(str(source)))
    return True


def _swap_folder(staged: Path, live: Path, aside: Path) -> None:
    """Put a staged folder where the live one is; the live one waits in `aside` until the staging goes."""
    if not staged.exists():
        return  # an earlier start already moved it in
    if live.exists() or live.is_symlink():
        _mkdir(aside.parent)
        _replace(live, aside)
    _replace(staged, live)


def _stuck(message: str) -> RestoreInProgressError:
    """Log what a person has to do, and hand back the error that stops the start."""
    logger.error("%s", message)
    return RestoreInProgressError(message)


def _cannot_finish(
    staging: Path, reason: str, finish: str, target: Path | None = None
) -> RestoreInProgressError:
    """A half-applied restore this start can't finish, and what a person has to do about it.

    The marker says what it was applying; the manifest does when the marker is gone. With both
    gone, the archive goes by its name pattern and the database is the one MyGarage opens now.
    """
    info = _read_json(staging / APPLYING_NAME) or _read_json(staging / MANIFEST_NAME) or {}
    # Both files sit on disk, so their names go through sanitize_for_log before the log.
    prerestore = sanitize_for_log(
        info.get("prerestore_backup", "the mygarage-full-safety-prerestore archive")
    )
    database = info.get("database") or (str(target) if target else None)
    staged_db = f" and {sanitize_for_log(database)}{_PENDING_SUFFIX}" if database else ""
    return _stuck(
        "A restore was being applied when MyGarage last stopped, and this start can't finish it: "
        f"{reason}. Its files are kept, and MyGarage won't start until this is settled. "
        f"{finish}To go back to the data from just before the restore instead: delete "
        f"{staging}{staged_db}, start MyGarage with MYGARAGE_MAINTENANCE_MODE=1, restore "
        f"{prerestore} from Settings > Backup & Restore, then restart without maintenance mode."
    )


def _cannot_begin(staging: Path, staged_db: Path, reason: object) -> RestoreInProgressError:
    """A staged restore that failed before its first live change: nothing to undo, two ways on."""
    return _stuck(
        f"A staged restore couldn't begin at this start: {reason}. Nothing live was touched, and "
        "MyGarage won't start until this is settled. To apply it, fix that and start MyGarage "
        f"again. To cancel it instead, delete {staging} and {staged_db}, then start MyGarage."
    )


def _staged_items(staging: Path, target: Path) -> list[Path]:
    """What a staging holds until the swap takes it: the staged database and the three folders."""
    return [pending_database(target), *(staging / name for name in MEDIA_DIRS)]


def _partly_staged(staging: Path, target: Path) -> bool:
    """Some of the staging is there and some isn't. Without the marker, only a broken staging looks so."""
    present = [path.exists() for path in _staged_items(staging, target)]
    return any(present) and not all(present)


def _only_cleanup_left(staging: Path, target: Path | None) -> bool:
    """Folders set aside and nothing left to swap in: a restore went in and its cleanup got cut short."""
    if not (staging / "previous").exists():
        return False
    staged = _staged_items(staging, target) if target else [staging / n for n in MEDIA_DIRS]
    return not any(path.exists() for path in staged)


def apply_pending_restore(
    data_dir: Path,
    database_file: Path | None,
    *,
    backup_dir: Path,
    before_swap: Callable[[str], None],
) -> str | None:
    """Swap a staged restore in before anything opens the database; returns its backup's name.

    before_swap writes the pre-restore safety archive under the name it's given. It runs only
    while the applying marker isn't down, so the archive never holds a half-swapped state.
    Every step after it is on disk before the next, and checks what's already done, so a start
    killed partway finishes the job on the next one. Anything this start can't get past raises
    RestoreInProgressError with what a person has to do, and keeps every file.
    """
    staging = data_dir / STAGING_DIRNAME
    staged_db = pending_database(database_file) if database_file else None
    if not staging.exists() and not (staged_db is not None and staged_db.exists()):
        return None  # the usual start: no lock, nothing written
    with restore_lock(data_dir):
        manifest_path = staging / MANIFEST_NAME
        applying = staging / APPLYING_NAME
        manifest = _read_json(manifest_path)
        target = database_file.resolve() if database_file else None
        finish = ""
        if manifest is None:
            reason = (
                "its manifest can't be read" if manifest_path.exists() else "its manifest is gone"
            )
        elif manifest.get("format") != MANIFEST_FORMAT:
            reason = f"its manifest is in another version's format ({manifest.get('format')!r})"
            finish = "To finish it, start the MyGarage version that staged it. "
        elif not isinstance(manifest.get("prerestore_backup"), str):
            reason = "its manifest doesn't name a safety archive"
        elif target is None or manifest.get("database") != str(target):
            recorded = sanitize_for_log(str(manifest.get("database")))
            reason = f"it is for {recorded}, and MyGarage now opens {target or 'no database file'}"
            finish = f"To finish it, point MYGARAGE_DATABASE_URL at {recorded} again and start MyGarage. "
        elif not applying.exists() and _partly_staged(staging, target):
            if (staging / "previous").exists():
                # Folders were set aside, so the swap had begun and someone deleted the marker:
                # half swapped, not a broken staging.
                raise _cannot_finish(
                    staging, "its swap had begun, but its applying marker is gone", ""
                )
            reason = "part of its staging is missing (the staged database or a staged folder)"
        else:
            return _swap_in(data_dir, staging, manifest, target, backup_dir, before_swap)
        if applying.exists():
            # Half swapped: serving would mix old and new data, and dropping the staging would lose
            # what was swapped out. Stop the start and keep every file.
            raise _cannot_finish(staging, reason, finish)
        if (staging / "previous").exists() and not _only_cleanup_left(staging, target):
            # Folders set aside and some still staged: half swapped, with the marker deleted by
            # hand and the manifest no help either. Same as above, never a cleanup or a discard.
            raise _cannot_finish(
                staging,
                f"its swap had begun, but its applying marker is gone and {reason}",
                "",
                target,
            )
        if not manifest_path.exists():
            if not staging.exists():
                # Only a staged database, and no staging here: what a moved data folder looks like.
                logger.error(
                    "A staged database is waiting at %s, but %s holds no staging for it. If "
                    "MYGARAGE_DATA_DIR changed since the restore, set it back and restart; "
                    "otherwise delete that file.",
                    staged_db,
                    data_dir,
                )
                return None
            # Checked before the discard takes the evidence with it.
            applied = _only_cleanup_left(staging, target)
            try:
                discarded = discard_pending_restore(data_dir, database_file)
            except OSError as exc:
                raise _stuck(
                    f"A leftover restore staging in {staging} can't be removed: {exc}. Delete it by "
                    "hand and start MyGarage again."
                ) from exc
            if applied:
                # The restore is in. Saying it was discarded would send someone to restore it again.
                logger.info("Removed the leftover staging of an applied restore")
            elif discarded:
                logger.warning("Discarded an unfinished restore; the current data stays")
            return None
        logger.error(
            "Not applying the staged restore in %s: %s. It stays staged: fix that and restart, "
            "or cancel it in Settings > Backup & Restore.",
            staging,
            reason,
        )
        return None


def _swap_in(
    data_dir: Path,
    staging: Path,
    manifest: dict[str, Any],
    target: Path,
    backup_dir: Path,
    before_swap: Callable[[str], None],
) -> str:
    """Swap a checked staging in, under the restore lock."""
    source = str(manifest.get("source_backup"))
    prerestore = str(manifest["prerestore_backup"])
    applying = staging / APPLYING_NAME
    staged_db = pending_database(target)
    if not applying.exists() and not any(path.exists() for path in _staged_items(staging, target)):
        # Everything is swapped and the marker is gone: a start died during the cleanup.
        _finish_cleanup(staging, source)
        return source
    if not applying.exists():
        try:
            # The data this restore replaces goes into a safety archive, on disk, before anything
            # changes. Then the marker tells every later start the live data may be half swapped.
            before_swap(prerestore)
            _write_json(
                applying,
                {"database": str(target), "source_backup": source, "prerestore_backup": prerestore},
            )
        except (OSError, sqlite3.Error, ValueError) as exc:
            # ValueError: a hand-edited archive name that validate_filename refuses.
            raise _cannot_begin(staging, staged_db, exc) from exc
    elif not (backup_dir / prerestore).exists():
        # Written now, it would file the half-swapped data as "before the restore".
        shown = sanitize_for_log(prerestore)
        raise _cannot_finish(
            staging,
            f"its pre-restore safety archive {shown} is missing from {backup_dir}",
            f"To finish it, put {shown} back and start MyGarage again. ",
        )
    try:
        if staged_db.exists():
            # A stale WAL is replayed over whatever file sits beside it, so it goes first.
            for suffix in ("-wal", "-shm"):
                _unlink(Path(f"{target}{suffix}"))
            _replace(staged_db, target)
        for name in MEDIA_DIRS:
            _swap_folder(staging / name, data_dir / name, staging / "previous" / name)
        # All swapped: the marker goes first, then the manifest, then the rest.
        _unlink(applying)
    except OSError as exc:
        raise _cannot_finish(
            staging, str(exc), "To finish it, fix that and start MyGarage again. "
        ) from exc
    _finish_cleanup(staging, source)
    logger.info(
        "Applied the staged restore of %s; the data it replaced is in %s",
        sanitize_for_log(source),
        sanitize_for_log(prerestore),
    )
    return source


def _finish_cleanup(staging: Path, source: str) -> None:
    """Drop the manifest, then what's left of the staging, once everything is swapped."""
    try:
        _unlink(staging / MANIFEST_NAME)
        _remove_tree(staging)
    except OSError as exc:
        raise _stuck(
            f"The restore of {sanitize_for_log(source)} is in place, but this start couldn't "
            f"remove what's left of its staging: {exc}. Delete {staging} by hand and start "
            "MyGarage again."
        ) from exc
