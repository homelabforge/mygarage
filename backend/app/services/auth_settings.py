"""The sign-in settings: one lock for every writer, and the SSO-mode rule (S1c-01, D3).

`auth_mode=oidc` with SSO off, or with no issuer URL or client ID, leaves an
instance nobody can sign in to. The UI orders its writes so it never gets
there, but the settings routes, the OIDC PUT and a settings restore can each
write the four keys, so the server refuses any write that would land there.

The rule is a check-then-write across rows two requests can both touch, so
every writer of the four keys takes `lock_auth_settings` first, then reads,
then checks. Without the lock, "turn SSO off" and "switch to SSO" could each
pass the check against the other's old value and both commit.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.services.settings_service import parse_bool
from app.services.vehicle_lock import is_lock_contention

logger = logging.getLogger(__name__)

#: The settings that decide whether SSO sign-in can work.
AUTH_KEYS: frozenset[str] = frozenset(
    {"auth_mode", "oidc_enabled", "oidc_issuer_url", "oidc_client_id"}
)

AUTH_LOCK_CONTRACT = (
    "lock_auth_settings must precede every write of a sign-in setting: call it once, "
    "after the route's authorization check, and before any settings read"
)

AUTH_LOCK_BUSY_DETAIL = "Another change to the sign-in settings is in progress. Try again."

#: One fixed key for the PG advisory lock, "mgauthst" as bytes. Not a row lock:
#: a missing auth_mode row would have nothing to lock (R9).
AUTH_SETTINGS_LOCK_KEY = int.from_bytes(b"mgauthst", "big")

SWITCH_TO_SSO_DETAIL = (
    "Turn on SSO and fill in its issuer URL and client ID before switching sign-in to SSO."
)
SSO_IN_USE_DETAIL = (
    "Sign-in is set to SSO. Switch sign-in to local or none before turning SSO off "
    "or clearing its issuer URL or client ID."
)


class AuthSettingsConflictError(Exception):
    """A write that would leave sign-in set to SSO without usable SSO.

    `detail` is the sentence the user sees.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def lock_auth_settings(db: AsyncSession) -> None:
    """Take the sign-in settings lock for the rest of this transaction.

    SQLite: `BEGIN IMMEDIATE`, with the same misplaced-call guard as
    `lock_vehicle_for_write`, so a call inside an open transaction is a
    RuntimeError naming the contract, not a 503. PostgreSQL:
    `pg_advisory_xact_lock` on one fixed key, released at commit or rollback.

    Raises:
        HTTPException: 503 when another writer holds the lock past the wait.
        RuntimeError: SQLite only, the driver is already inside a transaction.
    """
    dialect = db.get_bind().dialect.name
    try:
        if dialect == "sqlite":
            raw = await (await db.connection()).get_raw_connection()
            if raw.driver_connection.in_transaction:
                raise RuntimeError(AUTH_LOCK_CONTRACT)
            await db.execute(text("BEGIN IMMEDIATE"))
        else:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(CAST(:key AS BIGINT))"),
                {"key": AUTH_SETTINGS_LOCK_KEY},
            )
    except DBAPIError as exc:
        if not is_lock_contention(exc):
            raise
        logger.warning("Sign-in settings lock unavailable: %s", exc)
        raise HTTPException(status_code=503, detail=AUTH_LOCK_BUSY_DETAIL) from exc


def _sso_usable(values: Mapping[str, str | None]) -> bool:
    """Whether SSO is on and has a non-blank issuer URL and client ID."""
    return (
        parse_bool(values.get("oidc_enabled"), default=False)
        and bool((values.get("oidc_issuer_url") or "").strip())
        and bool((values.get("oidc_client_id") or "").strip())
    )


def _is_oidc(mode: str | None) -> bool:
    """Whether an `auth_mode` value means SSO, read the way the auth reader reads it."""
    return (mode or "").strip().lower() == "oidc"


async def ensure_sso_mode_usable(db: AsyncSession, pending: Mapping[str, str | None]) -> None:
    """Refuse a write that would leave `auth_mode=oidc` without usable SSO.

    Reads the stored four keys and overlays `pending`, the values the caller
    is about to write (None means the row goes away). A missing row counts as
    off or blank. Keys outside `AUTH_KEYS` are ignored. Selects columns, not
    rows, so a `Setting` the session loaded before the lock can't hand back a
    stale value.

    Raises:
        AuthSettingsConflictError: The result is SSO mode without usable SSO.
    """
    rows = await db.execute(
        select(Setting.key, Setting.stored_value).where(Setting.key.in_(AUTH_KEYS))
    )
    values: dict[str, str | None] = {key: value for key, value in rows.all()}
    values.update({key: value for key, value in pending.items() if key in AUTH_KEYS})
    if not _is_oidc(values.get("auth_mode")) or _sso_usable(values):
        return
    if "auth_mode" in pending and _is_oidc(pending["auth_mode"]):
        raise AuthSettingsConflictError(SWITCH_TO_SSO_DETAIL)
    raise AuthSettingsConflictError(SSO_IN_USE_DETAIL)
