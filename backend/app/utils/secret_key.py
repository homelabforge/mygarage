"""Secret key generation and management.

A leaf module: `app.config` imports it at module load (the JWT key is
`Settings.secret_key`'s default factory), so it must not import `app.config`.
`app.utils.settings_crypto` imports `create_key_file` from here for the same
reason; the reverse direction would be a circular import.

This runs at `app.config` import, before `app.main` configures logging, so an
INFO from here would be lost. The outcome goes to `KEY_SOURCE` instead, and the
lifespan logs it. WARNING and ERROR still reach stderr through logging's
last-resort handler.
"""

import logging
import os
import secrets
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

type KeySource = Literal["loaded", "generated", "memory"]

DEFAULT_KEY_FILE = Path("/data/secret.key")

# What the last get_or_create_secret_key call did. Stays "memory" when
# MYGARAGE_SECRET_KEY is set, because pydantic never calls the default factory
# then; the lifespan checks the env var first.
KEY_SOURCE: KeySource = "memory"


def create_key_file(path: Path, content: str) -> None:
    """Create a key file that holds ``content``, readable by its owner only.

    The file is created with ``O_EXCL`` and mode 0600 in a single ``open``, so
    there is no moment when it exists with the umask's mode, and an existing
    file (or a symlink, dangling or not) is never overwritten. A missing parent
    directory is created. If the write fails after the file was created, the
    partial file is removed, so a later start doesn't find a truncated key.

    Args:
        path: Where to create the file.
        content: The text to write (ASCII key material).

    Raises:
        FileExistsError: Something already exists at ``path``.
        OSError: The directory or the file couldn't be created or written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            # codeql[py/clear-text-storage-sensitive-data] - Key files (the JWT key, the settings
            # encryption keyring) must persist across restarts; written owner-only (0600) in /data.
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _read_key(path: Path) -> str | None:
    """The stripped contents of ``path``, or None when it doesn't exist."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


def _resolve_secret_key(key_file: Path) -> tuple[str, KeySource]:
    """Read, create or fall back to a JWT key, and say which happened."""
    try:
        existing = _read_key(key_file)
        if existing:
            return existing, "loaded"
        if existing is not None:
            logger.warning("Secret key file at %s is empty, generating a new key", key_file)
            key_file.unlink()

        secret_key = secrets.token_urlsafe(32)
        try:
            create_key_file(key_file, secret_key + "\n")
        except FileExistsError:
            # Another process created it between the read and the write: use theirs.
            winner = _read_key(key_file)
            if not winner:
                raise
            return winner, "loaded"
        return secret_key, "generated"

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
        key_file: Path to the secret key file (default: /data/secret.key).

    Returns:
        The secret key as a string.

    Note:
        Falls back to an in-memory key if the file can't be used. The key then
        changes on restart, which logs every user out. That is acceptable for a
        JWT key; the settings encryption key never does this.
    """
    global KEY_SOURCE
    key, KEY_SOURCE = _resolve_secret_key(key_file)  # pyright: ignore[reportConstantRedefinition]
    return key
