"""Secret key generation and management.

A leaf module: `app.config` imports it at module load (the JWT key is
`Settings.secret_key`'s default factory), so it must not import `app.config`.
`app.utils.settings_crypto` imports its key-file writers from here for the
same reason; the reverse direction would be a circular import.

This runs at `app.config` import, before `app.main` configures logging, so an
INFO from here would be lost. The outcome goes to `KEY_SOURCE` instead, and the
lifespan logs it. WARNING and ERROR still reach stderr through logging's
last-resort handler.

Every key-file writer fills the file under an exclusive ``flock`` and only
when it holds nothing, then returns what's on disk. So when two processes race
(two starts, or a CLI tool next to the app), whoever locks first writes and the
other reads that key back: nobody keeps a key in memory that isn't the file's.
On a mount that can't lock at all, the fill goes ahead unlocked with a WARNING,
as it did before the lock existed.
"""

import contextlib
import errno
import fcntl
import logging
import os
import secrets
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

type KeySource = Literal["loaded", "generated", "memory"]

DEFAULT_KEY_FILE = Path("/data/secret.key")
#: The file name inside the data directory (`MYGARAGE_DATA_DIR`).
KEY_FILE_NAME = "secret.key"

#: The file the last get_or_create_secret_key call used, for the lifespan's log.
KEY_FILE: Path = DEFAULT_KEY_FILE

# What the last get_or_create_secret_key call did. Stays "memory" when
# MYGARAGE_SECRET_KEY is set, because pydantic never calls the default factory
# then; the lifespan checks the env var first.
KEY_SOURCE: KeySource = "memory"

# Opening a key file someone else may be filling: never create it, never follow
# a symlink, and never truncate (that would wipe a key another filler just wrote).
_OPEN_EXISTING = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC


# What flock raises on a mount with no advisory locks (NFSv3 without lockd, some
# FUSE or 9p setups). Our LOCK_EX is always a valid operation, so EINVAL here
# means the filesystem said no, not a bug in the call.
_LOCKS_UNSUPPORTED = frozenset(
    {errno.ENOLCK, errno.EOPNOTSUPP, errno.ENOTSUP, errno.ENOSYS, errno.EINVAL}
)


def _lock_if_supported(fd: int) -> None:
    """Take ``LOCK_EX`` on ``fd``, or carry on without it where the mount can't lock."""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError as e:
        if e.errno not in _LOCKS_UNSUPPORTED:
            raise
        # The key files were written unlocked before the lock existed, and a
        # lone start is still fine. Only two processes starting at once could
        # each write a key, so say so rather than fall back to a memory key.
        logger.warning(
            "This filesystem doesn't support file locks (%s), so the key file is "
            "written without one. Two processes starting at the same moment could "
            "each write a different key.",
            os.strerror(e.errno),
        )


def _read_fd(fd: int) -> bytes:
    """Everything in the file behind ``fd``, from the start."""
    chunks: list[bytes] = []
    offset = 0
    while chunk := os.pread(fd, 4096, offset):
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def _locked_fill(fd: int, content: str) -> str:
    """Write ``content`` into the file behind ``fd`` if it holds no key, under ``LOCK_EX``.

    The caller opened ``fd`` and closes it, which also drops the lock. A file
    that's blank after a strip gets ``content`` written as is, at the start;
    one that holds anything else is left alone.

    Returns:
        The key now on disk, stripped: ours if we wrote it, theirs if not.

    On a mount that can't lock at all the fill goes ahead unlocked, with a
    WARNING; any other lock failure raises.

    Raises:
        OSError: The lock, the read or the write failed. A failed write leaves
            the file empty, so the next start fills it again.
        UnicodeDecodeError: The file holds something that isn't UTF-8 text.
    """
    data = content.encode("ascii")
    _lock_if_supported(fd)
    existing = _read_fd(fd).decode("utf-8").strip()
    if existing:
        return existing
    try:
        os.ftruncate(fd, 0)
        written = 0
        while written < len(data):
            # codeql[py/clear-text-storage-sensitive-data] - Key files (the JWT key, the settings
            # encryption keyring) must persist across restarts; written owner-only (0600) in /data.
            written += os.pwrite(fd, data[written:], written)
        os.fsync(fd)
    except BaseException:
        # Half a key reads as a broken one forever; an empty file gets refilled.
        with contextlib.suppress(OSError):
            os.ftruncate(fd, 0)
        raise
    return content.strip()


def create_key_file(path: Path, content: str) -> str:
    """Create a key file that holds ``content``, readable by its owner only.

    The file is created with ``O_EXCL`` and mode 0600 in a single ``open``, so
    there is no moment when it exists with the umask's mode, and an existing
    file (or a symlink, dangling or not) is never overwritten. A missing parent
    directory is created. The write happens under an exclusive lock; if it
    fails, the file is left empty rather than removed, since a racing process
    may already be waiting on it.

    Args:
        path: Where to create the file.
        content: The text to write (ASCII key material), as is.

    Returns:
        The key on disk, stripped. Normally ``content`` stripped; a process that
        filled the empty file first wins (see ``fill_after_create_race``).

    Raises:
        FileExistsError: Something already exists at ``path``.
        OSError: The directory or the file couldn't be created or written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        return _locked_fill(fd, content)
    finally:
        os.close(fd)


def fill_after_create_race(path: Path, content: str) -> str:
    """The key in a file another process created first, filling it if it's still empty.

    For a ``create_key_file`` that raised ``FileExistsError``. The winner may
    not have written yet, so reading the file could find nothing; filling it
    under the lock instead means one of us writes and the other reads that back.

    Returns:
        The key on disk, stripped.

    Raises:
        OSError: The file can't be opened or written.
        UnicodeDecodeError: It holds something that isn't UTF-8 text.
    """
    fd = os.open(path, _OPEN_EXISTING)
    try:
        return _locked_fill(fd, content)
    finally:
        os.close(fd)


def _create_or_join(path: Path, content: str) -> str:
    """Create the key file, or use the one a racing process created first."""
    try:
        return create_key_file(path, content)
    except FileExistsError:
        return fill_after_create_race(path, content)


def fill_empty_key_file(path: Path, content: str) -> str:
    """Write ``content`` into the existing, empty key file at ``path``.

    In place, not unlink-and-create: a single-file bind mount can't be
    unlinked (EBUSY), which used to leave an in-memory key. If another process
    filled it since we read it, its key is kept and returned.

    A symlink is still replaced, since writing through it would land somewhere
    else, and so is a file we can't open for writing. Both of those unlink and
    create outside any lock, so two processes that both take one of them can
    each make a file, and one ends up with a key that isn't on disk.

    Returns:
        The key on disk, stripped.

    Raises:
        OSError: The file can't be opened, replaced or written.
        UnicodeDecodeError: It now holds something that isn't UTF-8 text.
    """
    if path.is_symlink():
        path.unlink(missing_ok=True)
        return _create_or_join(path, content)
    try:
        fd = os.open(path, _OPEN_EXISTING)
    except PermissionError:
        # Not ours to write (a root-owned 0644 file in our directory): the
        # old unlink-and-create still works there.
        path.unlink(missing_ok=True)
        return _create_or_join(path, content)
    try:
        try:
            os.fchmod(fd, 0o600)
        except PermissionError:
            # A file someone else owns but made writable (a chmod 666 bind
            # mount): keep the key rather than fall back to memory.
            logger.warning("Could not make %s owner-only; writing the key anyway", path)
        return _locked_fill(fd, content)
    finally:
        os.close(fd)


def _read_key(path: Path) -> str | None:
    """The stripped contents of ``path``, or None when it doesn't exist."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


def _carry_over_legacy_key(key_file: Path) -> str | None:
    """The key from ``/data/secret.key`` when the data dir moved and has none yet.

    Before B2-6 the key was always at ``/data/secret.key``, whatever
    ``MYGARAGE_DATA_DIR`` said. Copying it to the new place keeps every
    session signed in. None when there is nothing to carry over.
    """
    if key_file == DEFAULT_KEY_FILE:
        return None
    try:
        legacy = _read_key(DEFAULT_KEY_FILE)
    except OSError, ValueError:
        return None
    if not legacy:
        return None
    key = _create_or_join(key_file, legacy + "\n")
    if key == legacy:
        logger.warning("Copied the secret key from %s to %s", DEFAULT_KEY_FILE, key_file)
    return key


def _resolve_secret_key(key_file: Path) -> tuple[str, KeySource]:
    """Read, create or fall back to a JWT key, and say which happened."""
    try:
        existing = _read_key(key_file)
        if existing:
            return existing, "loaded"
        if existing is None:
            carried = _carry_over_legacy_key(key_file)
            if carried:
                return carried, "loaded"
        candidate = secrets.token_urlsafe(32)
        if existing is None:
            key = _create_or_join(key_file, candidate + "\n")
        else:
            key = fill_empty_key_file(key_file, candidate + "\n")
        if key != candidate:
            # Another process got its key in first: that one's on disk, so use it.
            return key, "loaded"
        if existing is not None:
            logger.warning("Secret key file at %s was empty; generated a new key", key_file)
        return key, "generated"

    except (OSError, ValueError) as e:
        # ValueError covers a file that isn't UTF-8 (UnicodeDecodeError).
        reason = e if isinstance(e, OSError) else "the file is not UTF-8 text"
        logger.error("Could not read or write the secret key file %s: %s", key_file, reason)
        logger.warning("Using temporary in-memory secret key (will change on restart)")
        return secrets.token_urlsafe(32), "memory"


def get_or_create_secret_key(key_file: Path = DEFAULT_KEY_FILE) -> str:
    """Get the persisted JWT signing key, creating it on first use.

    Records the outcome in ``KEY_SOURCE``: "loaded" when the file already held a
    key, "generated" when this call wrote a new one, "memory" when the file
    couldn't be read or written.

    Args:
        key_file: Path to the secret key file. `app.config` passes
            ``<data_dir>/secret.key``, so `MYGARAGE_DATA_DIR` moves it (B2-6).

    Returns:
        The secret key as a string.

    Note:
        Falls back to an in-memory key if the file can't be used. The key then
        changes on restart, which logs every user out. That is acceptable for a
        JWT key; the settings encryption key never does this.
    """
    global KEY_SOURCE, KEY_FILE
    KEY_FILE = key_file  # pyright: ignore[reportConstantRedefinition]
    key, KEY_SOURCE = _resolve_secret_key(key_file)  # pyright: ignore[reportConstantRedefinition]
    return key
