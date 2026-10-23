"""Bringing every stored secret setting up to the current key (D5a).

``encrypt_secret_rows`` is the encrypt step: it encrypts plaintext secret rows,
re-encrypts rows under an older key id, leaves current-key rows alone, and lists
the rows that can't be decrypted. It flushes and leaves the commit to its
caller, so the backup preflight can run it inside its own transaction.

``sweep_secret_settings`` runs it once at every start. It is idempotent and
never fatal: plaintext rows keep reading, so a failed sweep just leaves them for
the next start. That makes it the backstop for anything that writes the raw
column without the model's setter: a raw-SQL migration, a Core ``insert()`` or
``update()``, an old settings backup, a full-backup swap.

``ensure_secrets_encrypted`` runs it before every backup the app writes (R1-H1):
a failed sweep leaves plaintext rows behind, and every backup copies the
database, so a backup that would carry plaintext is refused instead.

Every write goes through ``Setting.value``, the single place secrets are
encrypted. Logs name setting keys and counts, never values or ciphertext.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.utils.secret_setting_keys import SECRET_SETTING_KEYS
from app.utils.settings_crypto import (
    CIPHERTEXT_PREFIX,
    ENV_KEY,
    DecryptStatus,
    SettingsKeyUnavailable,
    current_kid,
    decrypt,
)

logger = logging.getLogger(__name__)


class PlaintextSecretsRemain(Exception):  # noqa: N818 - the name the plan and later tasks use
    """A backup was refused: some secret settings are still stored as plaintext (R1-H1).

    Deliberately not a ``RuntimeError``: the full-backup route maps those to a
    500, and this must stay a 503 (R2-2). ``register_error_handlers`` maps it.
    Names setting keys only, never a value.

    Attributes:
        keys: The secret setting keys still stored as plaintext, sorted.
    """

    def __init__(self, keys: tuple[str, ...], *, keyring_unavailable: bool = True) -> None:
        """Build the refusal for these keys.

        Args:
            keys: The plaintext secret setting keys, sorted.
            keyring_unavailable: Why they stayed plaintext. True says how to fix
                the key; False means encrypting them failed with a key at hand.
        """
        self.keys = keys
        fix = (
            f"Set {ENV_KEY} to a valid key, or make the data directory writable so a key "
            "can be generated, then try again."
            if keyring_unavailable
            else "Encrypting them failed; check the server log, then try again."
        )
        super().__init__(
            "Backups are refused while these secret settings are stored unencrypted: "
            f"{', '.join(keys)}. A backup, and the safety backup a restore writes first, "
            f"would copy them in the clear. {fix}"
        )


@dataclass(frozen=True, slots=True)
class SweepReport:
    """What one pass over the secret rows did, by setting key name (each sorted).

    Attributes:
        encrypted: Plaintext rows now stored as current-key ciphertext.
        rekeyed: Rows moved from an older key id to the current one.
        unreadable: Rows holding ciphertext that can't be decrypted, left as they are.
    """

    encrypted: tuple[str, ...] = ()
    rekeyed: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()

    @property
    def changed(self) -> int:
        """How many rows were rewritten (encrypted plus re-keyed)."""
        return len(self.encrypted) + len(self.rekeyed)


async def encrypt_secret_rows(db: AsyncSession) -> SweepReport:
    """Encrypt plaintext secret rows and re-key old ones, in the caller's transaction.

    Each secret row is classified by decrypting its stored value. Plaintext is
    encrypted and an older key id is re-encrypted, both through the model's
    setter; a current-key row and a blank one are left alone; one that can't be
    decrypted is listed and left byte-identical. Every secret row gets
    ``encrypted = True``. The changes are flushed, not committed, and no
    PRAGMA runs.

    Args:
        db: The session to work in. The caller commits or rolls back.

    Returns:
        The rows encrypted, re-keyed and unreadable, by key name.

    Raises:
        SettingsKeyUnavailable: A plaintext row needs encrypting and there is no
            usable keyring. Raised by the first such write, before any row in
            the session has changed.
    """
    rows = (
        (await db.execute(select(Setting).where(Setting.key.in_(SECRET_SETTING_KEYS))))
        .scalars()
        .all()
    )
    kid = current_kid()
    to_encrypt: list[tuple[Setting, str]] = []
    to_rekey: list[tuple[Setting, str]] = []
    unreadable: list[str] = []
    for row in rows:
        stored = row.stored_value
        if not stored:
            continue
        result = decrypt(row.key, stored)
        if result.status is DecryptStatus.LEGACY:
            to_encrypt.append((row, stored))
        elif result.status is DecryptStatus.UNREADABLE:
            unreadable.append(row.key)
        elif result.kid != kid and result.plaintext is not None:
            to_rekey.append((row, result.plaintext))

    # Plaintext first: without a keyring the first of these raises, and nothing has changed yet.
    for row, plaintext in (*to_encrypt, *to_rekey):
        row.value = plaintext
    for row in rows:
        if not row.encrypted:
            row.encrypted = True
    await db.flush()
    return SweepReport(
        encrypted=tuple(sorted(row.key for row, _ in to_encrypt)),
        rekeyed=tuple(sorted(row.key for row, _ in to_rekey)),
        unreadable=tuple(sorted(unreadable)),
    )


async def sweep_secret_settings(db: AsyncSession) -> SweepReport:
    """The startup sweep: run ``encrypt_secret_rows``, commit, and scrub SQLite's leftovers.

    With no usable keyring it logs an ERROR and writes nothing. On SQLite the
    writes run with ``secure_delete`` on, so the freed plaintext cells are
    zeroed, and when a row changed a ``wal_checkpoint(TRUNCATE)`` follows the
    commit, so the old pages don't linger in the WAL. A busy checkpoint is a
    WARNING. A database error is logged and swallowed, leaving the rows as they
    were for the next start. Never raises for either.

    Logs one line, ``Encrypted N, re-keyed M, unreadable: <keys>``: an ERROR
    when some secret is unreadable, INFO otherwise.

    Args:
        db: A session of its own; it is committed here.

    Returns:
        What changed. Empty when the keyring is unavailable or the sweep failed.
    """
    if current_kid() is None:
        logger.error(
            "The settings encryption key is unavailable, so the secret settings were left as "
            "they are: plaintext ones stay plaintext. The next start tries again."
        )
        return SweepReport()

    sqlite = db.get_bind().dialect.name == "sqlite"
    try:
        report = await _encrypt_and_commit(db, sqlite=sqlite)
    except SQLAlchemyError as exc:
        # The message would carry the bound parameters, ciphertext included: name the type only.
        logger.error(
            "Encrypting the secret settings failed (%s), so they were left as they are. "
            "The next start tries again.",
            type(exc).__name__,
        )
        await _rollback_quietly(db)
        return SweepReport()

    if sqlite and report.changed:
        await _checkpoint_wal(db)

    unreadable = ", ".join(report.unreadable) or "none"
    if report.unreadable:
        logger.error(
            "Encrypted %d, re-keyed %d, unreadable: %s. They read as unset until their key "
            "is back in the keyring or they are re-entered.",
            len(report.encrypted),
            len(report.rekeyed),
            unreadable,
        )
    else:
        logger.info(
            "Encrypted %d, re-keyed %d, unreadable: %s",
            len(report.encrypted),
            len(report.rekeyed),
            unreadable,
        )
    return report


async def _encrypt_and_commit(db: AsyncSession, *, sqlite: bool) -> SweepReport:
    """Run the encrypt step (``secure_delete`` on, on SQLite) and commit."""
    report = await _encrypt_securely(db, sqlite=sqlite)
    await db.commit()
    return report


async def _encrypt_securely(db: AsyncSession, *, sqlite: bool) -> SweepReport:
    """Run the encrypt step; on SQLite with ``secure_delete`` on for its writes. No commit.

    ``secure_delete`` zeroes freed content as each statement runs, so the old
    plaintext doesn't survive in a freed cell, where a backup's page-by-page
    snapshot would copy it. It is turned back to its previous value after the
    flush, on the same connection (the session holds one until the commit),
    rather than left on a pooled one. Not on a failed flush: the session then
    refuses any statement until it is rolled back, and trying would hide the
    real error. That leaves it on for one pooled connection, which costs only
    speed. A missing keyring is raised before the flush, so it is turned back
    then too.
    """
    if not sqlite:
        return await encrypt_secret_rows(db)
    previous = int((await db.execute(text("PRAGMA secure_delete"))).scalar_one())
    await db.execute(text("PRAGMA secure_delete=ON"))
    try:
        report = await encrypt_secret_rows(db)
    except SettingsKeyUnavailable:
        await db.execute(text(f"PRAGMA secure_delete={previous}"))
        raise
    await db.execute(text(f"PRAGMA secure_delete={previous}"))
    return report


async def ensure_secrets_encrypted(db: AsyncSession) -> SweepReport:
    """The backup preflight: encrypt every plaintext secret row and commit, or refuse (R1-H1).

    Runs the sweep's encrypt step, then re-checks the raw column: when any
    non-empty secret row still lacks the ``enc:v1:`` prefix (no usable keyring,
    a failed write, or a row written under the step), nothing is committed and
    ``PlaintextSecretsRemain`` is raised. Otherwise it **commits before
    returning**: the snapshot (the SQLite backup API, or ``pg_dump``) reads
    through another connection and sees only committed rows, so a flushed but
    uncommitted encrypt would leave the archive holding plaintext.

    Ciphertext that can't be decrypted is no reason to refuse: it is copied as
    stored, so a missing keyring with no plaintext rows lets the backup go on.

    Call it before the route's ``try``, so no broad ``except`` there can turn
    the refusal into another status.

    Args:
        db: The request's session. Committed on success, rolled back on refusal.

    Returns:
        What the encrypt step changed.

    Raises:
        PlaintextSecretsRemain: A plaintext secret row would end up in the backup.
        SQLAlchemyError: The encrypt step failed and left no plaintext behind.
    """
    sqlite = db.get_bind().dialect.name == "sqlite"
    try:
        report = await _encrypt_securely(db, sqlite=sqlite)
        remaining = await _plaintext_secret_keys(db)
        if remaining:
            raise PlaintextSecretsRemain(remaining, keyring_unavailable=current_kid() is None)
        await db.commit()
    except PlaintextSecretsRemain:
        await _rollback_quietly(db)
        raise
    except SettingsKeyUnavailable as exc:
        await _rollback_quietly(db)
        raise PlaintextSecretsRemain(await _plaintext_secret_keys(db)) from exc
    except SQLAlchemyError as exc:
        # Its message would carry the bound parameters: name the type only.
        logger.error(
            "Encrypting the secret settings before a backup failed (%s)", type(exc).__name__
        )
        await _rollback_quietly(db)
        remaining = await _plaintext_secret_keys(db)
        if remaining:
            raise PlaintextSecretsRemain(
                remaining, keyring_unavailable=current_kid() is None
            ) from exc
        raise

    if sqlite and report.changed:
        await _checkpoint_wal(db)
    if report.changed:
        logger.info(
            "Encrypted %d and re-keyed %d secret settings before writing a backup",
            len(report.encrypted),
            len(report.rekeyed),
        )
    return report


async def _plaintext_secret_keys(db: AsyncSession) -> tuple[str, ...]:
    """The secret keys whose raw column is non-empty and not ciphertext, sorted.

    A column select, so it reads the database (flushed rows included), not the
    identity map. The prefix is compared in Python: SQL ``LIKE`` is
    case-insensitive on SQLite.
    """
    rows = await db.execute(
        select(Setting.key, Setting.stored_value).where(Setting.key.in_(SECRET_SETTING_KEYS))
    )
    return tuple(
        sorted(
            key for key, stored in rows.all() if stored and not stored.startswith(CIPHERTEXT_PREFIX)
        )
    )


async def _checkpoint_wal(db: AsyncSession) -> None:
    """Fold the WAL into the database file and truncate it. Never raises."""
    try:
        row = (await db.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))).one()
        await db.commit()
    except SQLAlchemyError as exc:
        logger.warning(
            "The WAL checkpoint after encrypting the secret settings failed (%s); the old "
            "values stay in the WAL until a later checkpoint.",
            type(exc).__name__,
        )
        await _rollback_quietly(db)
        return
    if row[0]:
        logger.warning(
            "The WAL checkpoint after encrypting the secret settings was busy (another "
            "connection is reading); the old values stay in the WAL until a later checkpoint."
        )


async def _rollback_quietly(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except SQLAlchemyError as exc:
        logger.warning("Rolling back the secret settings sweep failed (%s)", type(exc).__name__)
