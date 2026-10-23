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
from app.utils.settings_crypto import DecryptStatus, current_kid, decrypt

logger = logging.getLogger(__name__)


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
    """Run the encrypt step and commit; on SQLite with ``secure_delete`` on for its writes.

    ``secure_delete`` zeroes freed content as each statement runs, so it is
    turned back to its previous value after the flush, on the same connection
    (the session holds one until the commit), rather than left on a pooled one.
    Not on a failed flush: the session then refuses any statement until it is
    rolled back, and trying would hide the real error. That leaves it on for
    one pooled connection, which costs only speed.
    """
    if not sqlite:
        report = await encrypt_secret_rows(db)
        await db.commit()
        return report
    previous = int((await db.execute(text("PRAGMA secure_delete"))).scalar_one())
    await db.execute(text("PRAGMA secure_delete=ON"))
    report = await encrypt_secret_rows(db)
    await db.execute(text(f"PRAGMA secure_delete={previous}"))
    await db.commit()
    return report


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
