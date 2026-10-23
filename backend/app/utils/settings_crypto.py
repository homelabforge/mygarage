"""Encryption at rest for secret settings.

The only module that touches the settings encryption keys or ciphertext.

Primitive: AES-256-GCM with a random 96-bit nonce per encryption, and the
setting's key name as the associated data. A ciphertext copied onto another row
(the LLM key pasted into ``slack_webhook_url``, say) fails to open instead of
being sent somewhere new.

Stored format: ``enc:v1:<kid>:<base64url(nonce || ciphertext+tag)>``, where
``kid`` is the first 8 hex characters of SHA-256 over the raw key bytes. ASCII
only, so it fits ``Text`` on SQLite and PostgreSQL alike.

RENAMING A SECRET SETTING KEY: because the key name is the associated data, a
migration that renames a secret key by moving the row (DELETE plus INSERT, or an
UPDATE of ``key``, as migration 118 did for non-secret keys) orphans its
ciphertext: it no longer opens under the new name. Rename a secret key by
decrypting it under the old name and encrypting it under the new one, never by
moving the stored value.

Keyring sources, in order; the first one present wins, even when it is broken:

1. ``MYGARAGE_SETTINGS_KEY``: the keys themselves.
2. ``MYGARAGE_SETTINGS_KEY_FILE``: an absolute path to a file holding them
   (Docker secrets). A relative value is refused. Its value is never echoed,
   absolute or not: logs and errors name the variable instead.
3. ``settings.data_dir / "settings.key"``: generated on first use when neither
   env var is set and the file doesn't exist.

Each source holds one or more base64url-encoded 32-byte keys separated by commas
or newlines. The first encrypts; the rest only decrypt, which is how a key is
rotated. A source that is present but malformed (or a ``_FILE`` path that
doesn't exist) makes the keyring unavailable. It never falls through to a
lower-priority source, and never generates a key over a file that exists. An
empty env var counts as unset.

When the keyring is unavailable, ``encrypt`` raises ``SettingsKeyUnavailable``,
legacy plaintext still reads, and ciphertext reads as unreadable. There is never
an ephemeral key: a key that can't be persisted would encrypt secrets that the
next restart can't open.

Only a loaded keyring is cached. While unavailable, every access retries (one
stat and one read), so fixing the source takes effect without a restart. Logs
name sources and setting key names, never keys, plaintext or ciphertext.
"""

import base64
import binascii
import hashlib
import logging
import os
import re
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings
from app.utils.secret_key import create_key_file

__all__ = [
    "CIPHERTEXT_PREFIX",
    "DecryptResult",
    "DecryptStatus",
    "ENV_KEY",
    "ENV_KEY_FILE",
    "KEY_FILE_NAME",
    "SettingsKeyUnavailable",
    "_reset_keyring_for_tests",
    "current_kid",
    "decrypt",
    "encrypt",
    "is_ciphertext",
]

logger = logging.getLogger(__name__)

CIPHERTEXT_PREFIX = "enc:v1:"
ENV_KEY = "MYGARAGE_SETTINGS_KEY"
ENV_KEY_FILE = "MYGARAGE_SETTINGS_KEY_FILE"
KEY_FILE_NAME = "settings.key"

_KEY_BYTES = 32
_NONCE_BYTES = 12
_TAG_BYTES = 16
_KID_RE = re.compile(r"[0-9a-f]{8}")
_B64URL_RE = re.compile(r"[A-Za-z0-9_-]+={0,2}")
_KEY_SEPARATORS = re.compile(r"[,\r\n]")


class SettingsKeyUnavailable(Exception):  # noqa: N818 - the name the plan and later tasks use
    """No usable settings encryption key, so a secret can't be written.

    Deliberately not a ``RuntimeError``: callers with an ``except RuntimeError``
    (the full-backup route) must not turn it into a 500.

    Attributes:
        source: The key source that was tried: an env var's name (never its
            value), or the data dir's key file path, which comes from app config.
        reason: Why it isn't usable. Never contains key material.
    """

    def __init__(self, source: str, reason: str) -> None:
        """Build the exception from the source tried and why it failed."""
        self.source = source
        self.reason = reason
        super().__init__(
            f"The settings encryption key is unavailable ({source}: {reason}). "
            f"{_fix_advice(source)}"
        )


def _fix_advice(source: str) -> str:
    """What fixes an unavailable keyring, by the source that broke (F-6).

    A broken env var wins over the data dir, so a key generated there would be
    ignored: only the data dir's own key file is fixed by making it writable.
    """
    if source == ENV_KEY:
        return f"Set {ENV_KEY} to a valid key."
    if source == ENV_KEY_FILE:
        return f"Point {ENV_KEY_FILE} at the absolute path of a readable file holding a valid key."
    return (
        f"Set {ENV_KEY} to a valid key, or make the data directory writable so a key "
        "can be generated."
    )


class DecryptStatus(StrEnum):
    """What ``decrypt`` found in a stored value."""

    DECRYPTED = "decrypted"
    """Ciphertext that opened under a key in the keyring."""
    LEGACY = "legacy"
    """No ``enc:v1:`` prefix: plaintext written before encryption existed."""
    UNREADABLE = "unreadable"
    """Ciphertext that can't be opened: unknown kid, wrong key name, tampered or
    malformed, or no keyring at all."""


@dataclass(frozen=True, slots=True)
class DecryptResult:
    """The outcome of ``decrypt``.

    Attributes:
        status: Which of the three cases applies.
        plaintext: The value for DECRYPTED and LEGACY; None for UNREADABLE.
        kid: The key id named in the ciphertext, when it has a well-formed one
            (also for UNREADABLE); None for LEGACY.
    """

    status: DecryptStatus
    plaintext: str | None
    kid: str | None = None

    @property
    def unreadable(self) -> bool:
        """True when the stored value is ciphertext that couldn't be opened."""
        return self.status is DecryptStatus.UNREADABLE


@dataclass(frozen=True, slots=True)
class _Keyring:
    source: str
    current_kid: str
    keys: dict[str, AESGCM]


@dataclass(frozen=True, slots=True)
class _Unavailable:
    source: str
    reason: str


class _MalformedSourceError(ValueError):
    """A key source is present but doesn't hold valid keys. Carries no key material."""


_lock = threading.Lock()
_keyring: _Keyring | None = None
_unavailable_logged = False
_unreadable_logged: set[tuple[str, str | None]] = set()


def _kid_of(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:8]


def _b64url_decode(text: str) -> bytes:
    """Strict base64url decode, padding optional. Raises ValueError."""
    if not _B64URL_RE.fullmatch(text):
        raise ValueError("not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except binascii.Error as e:
        raise ValueError("not base64url") from e


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _parse_keys(source: str, text: str) -> _Keyring:
    """Parse a key source's contents into a keyring. Raises _MalformedSourceError."""
    entries = [entry.strip() for entry in _KEY_SEPARATORS.split(text)]
    entries = [entry for entry in entries if entry]
    if not entries:
        raise _MalformedSourceError("it holds no keys")
    keys: dict[str, AESGCM] = {}
    kids: list[str] = []
    for position, entry in enumerate(entries, start=1):
        try:
            raw = _b64url_decode(entry)
        except ValueError:
            raw = b""
        if len(raw) != _KEY_BYTES:
            raise _MalformedSourceError(
                f"key {position} of {len(entries)} is not a base64url-encoded {_KEY_BYTES}-byte key"
            )
        kid = _kid_of(raw)
        kids.append(kid)
        keys.setdefault(kid, AESGCM(raw))
    return _Keyring(source=source, current_kid=kids[0], keys=keys)


def _read_key_file(source: str, path: Path) -> _Keyring | _Unavailable:
    """Load the keyring from a file that is expected to exist."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return _Unavailable(source, "the file does not exist")
    except OSError as e:
        return _Unavailable(source, f"the file can't be read ({e.strerror or type(e).__name__})")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        return _Unavailable(source, "the file is not ASCII text")
    try:
        return _parse_keys(source, text)
    except _MalformedSourceError as e:
        return _Unavailable(source, str(e))


def _generate_key_file(source: str, path: Path) -> _Keyring | _Unavailable:
    """Create the data-dir key file with a new key, then load it back from disk."""
    try:
        create_key_file(path, _b64url_encode(os.urandom(_KEY_BYTES)) + "\n")
    except FileExistsError:
        # Another process created it first; whatever it wrote is the key now.
        pass
    except OSError as e:
        return _Unavailable(
            source, f"a new key file can't be created ({e.strerror or type(e).__name__})"
        )
    else:
        logger.warning(
            "Generated a new settings encryption key at %s. Keep a copy: without it, "
            "the secrets stored in this database can't be read.",
            path,
        )
    return _read_key_file(source, path)


def _load() -> _Keyring | _Unavailable:
    """Resolve the keyring from the first present source. Never raises."""
    env_value = os.environ.get(ENV_KEY, "").strip()
    if env_value:
        try:
            return _parse_keys(ENV_KEY, env_value)
        except _MalformedSourceError as e:
            return _Unavailable(ENV_KEY, str(e))

    file_value = os.environ.get(ENV_KEY_FILE, "").strip()
    if file_value:
        # The source is the variable's name, never its value (R1-H1). A key pasted here
        # instead of into MYGARAGE_SETTINGS_KEY is the likely mistake, and a key in
        # standard base64 can start with "/", so not even an absolute-looking value is
        # safe to name in a log, an exception or a 503.
        file_path = Path(file_value)
        if not file_path.is_absolute():
            return _Unavailable(ENV_KEY_FILE, "it is not an absolute path")
        return _read_key_file(ENV_KEY_FILE, file_path)

    path = settings.data_dir / KEY_FILE_NAME
    source = str(path)
    try:
        # lstat, so a dangling symlink counts as present rather than as a reason to generate.
        path.lstat()
    except FileNotFoundError:
        return _generate_key_file(source, path)
    except OSError as e:
        return _Unavailable(source, f"the file can't be checked ({e.strerror or type(e).__name__})")
    return _read_key_file(source, path)


def _get_keyring() -> _Keyring | _Unavailable:
    """The cached keyring, or a fresh load attempt. Only a loaded keyring is cached."""
    global _keyring, _unavailable_logged
    cached = _keyring
    if cached is not None:
        return cached
    with _lock:
        if _keyring is not None:
            return _keyring
        result = _load()
        if isinstance(result, _Keyring):
            _keyring = result
            _unavailable_logged = False
            logger.info(
                "Settings encryption key loaded from %s (%d key%s, current id %s)",
                result.source,
                len(result.keys),
                "" if len(result.keys) == 1 else "s",
                result.current_kid,
            )
        elif not _unavailable_logged:
            _unavailable_logged = True
            logger.error(
                "Settings encryption key unavailable from %s: %s. Secret settings can't be "
                "saved, and encrypted ones read as unreadable, until it is fixed. %s Logged "
                "once; fixing it needs no restart.",
                result.source,
                result.reason,
                _fix_advice(result.source),
            )
        return result


def encrypt(name: str, plaintext: str) -> str:
    """Encrypt a secret setting's value under the current key.

    Args:
        name: The setting key name, bound in as the associated data.
        plaintext: The value to encrypt.

    Returns:
        The stored form, ``enc:v1:<kid>:<payload>``.

    Raises:
        SettingsKeyUnavailable: There is no usable keyring.
    """
    keyring = _get_keyring()
    if isinstance(keyring, _Unavailable):
        raise SettingsKeyUnavailable(keyring.source, keyring.reason)
    nonce = os.urandom(_NONCE_BYTES)
    sealed = keyring.keys[keyring.current_kid].encrypt(
        nonce, plaintext.encode("utf-8"), name.encode("utf-8")
    )
    return f"{CIPHERTEXT_PREFIX}{keyring.current_kid}:{_b64url_encode(nonce + sealed)}"


def _unreadable(name: str, kid: str | None, why: str) -> DecryptResult:
    """Build an UNREADABLE result, logging once per (setting key, kid) per process."""
    marker = (name, kid)
    if marker not in _unreadable_logged:
        _unreadable_logged.add(marker)
        logger.warning(
            "Secret setting %s can't be decrypted (key id %s): %s. It reads as unset until "
            "the right key is added back to the keyring or the value is re-entered.",
            name,
            kid or "none",
            why,
        )
    return DecryptResult(DecryptStatus.UNREADABLE, None, kid)


def decrypt(name: str, stored: str) -> DecryptResult:
    """Read a stored secret setting value. Never raises.

    Args:
        name: The setting key name the value is stored under (the associated data).
        stored: The raw stored value.

    Returns:
        DECRYPTED with the plaintext; LEGACY with the value as is when it has no
        ``enc:v1:`` prefix (this needs no keyring); or UNREADABLE with no
        plaintext when the ciphertext can't be opened for any reason.
    """
    if not stored.startswith(CIPHERTEXT_PREFIX):
        return DecryptResult(DecryptStatus.LEGACY, stored)

    kid_part, sep, payload = stored[len(CIPHERTEXT_PREFIX) :].partition(":")
    kid = kid_part if _KID_RE.fullmatch(kid_part) else None
    if kid is None or not sep:
        return _unreadable(name, kid, "the stored value is malformed")
    try:
        blob = _b64url_decode(payload)
    except ValueError:
        return _unreadable(name, kid, "the stored value is malformed")
    if len(blob) < _NONCE_BYTES + _TAG_BYTES:
        return _unreadable(name, kid, "the stored value is malformed")

    keyring = _get_keyring()
    if isinstance(keyring, _Unavailable):
        # The keyring's own ERROR already covers this; nothing per key.
        return DecryptResult(DecryptStatus.UNREADABLE, None, kid)
    key = keyring.keys.get(kid)
    if key is None:
        return _unreadable(name, kid, "no key in the keyring has this id")
    try:
        raw = key.decrypt(blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], name.encode("utf-8"))
        plaintext = raw.decode("utf-8")
    except InvalidTag:
        return _unreadable(name, kid, "it was tampered with or belongs to another setting")
    except UnicodeDecodeError:
        return _unreadable(name, kid, "it does not decode as text")
    return DecryptResult(DecryptStatus.DECRYPTED, plaintext, kid)


def is_ciphertext(stored: str | None) -> bool:
    """True when a stored value carries the ``enc:v1:`` prefix (well-formed or not)."""
    return stored is not None and stored.startswith(CIPHERTEXT_PREFIX)


def current_kid() -> str | None:
    """The id of the key that ``encrypt`` uses now, or None when the keyring is unavailable."""
    keyring = _get_keyring()
    return keyring.current_kid if isinstance(keyring, _Keyring) else None


def _reset_keyring_for_tests() -> None:
    """Forget the cached keyring and the once-only log flags, as a restart would.

    For the test suite only: tests that swap key sources call it before and
    after, and restore the environment in teardown.
    """
    global _keyring, _unavailable_logged
    with _lock:
        _keyring = None
        _unavailable_logged = False
        _unreadable_logged.clear()
