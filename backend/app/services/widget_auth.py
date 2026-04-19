"""Widget API key authentication.

Provides token helpers (SHA-256 hashing, mirrors the LiveLink pattern) and
two FastAPI dependencies used by the /api/widget/* and /api/auth/me/widget-keys
surfaces:

- `require_widget_key` authenticates a widget request and returns (user, key).
  Raises 401 on every failure mode including auth_mode=none.
- `require_auth_enabled` raises 400 when auth_mode is 'none'. Key-management
  routes declare this BEFORE `get_current_active_user` so the 400 fires via
  dependency ordering rather than in-handler checks.
"""

# pyright: reportAssignmentType=false, reportAttributeAccessIssue=false

import hashlib
import logging
import secrets
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.widget_api_key import WidgetApiKey
from app.services.auth import get_auth_mode
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

WIDGET_KEY_PREFIX = "mgwk_"
WIDGET_KEY_RANDOM_BYTES = 32
DISPLAY_PREFIX_LEN = 12
LAST_USED_THROTTLE = timedelta(seconds=60)


def generate_widget_key() -> str:
    """Return a new plaintext widget key (shown to the user once)."""
    return f"{WIDGET_KEY_PREFIX}{secrets.token_urlsafe(WIDGET_KEY_RANDOM_BYTES)}"


def hash_widget_key(plaintext: str) -> str:
    """Return the SHA-256 hex digest of a widget key."""
    return hashlib.sha256(plaintext.encode()).hexdigest()


def display_prefix(plaintext: str) -> str:
    """Short public prefix shown in the UI to help users identify keys."""
    return plaintext[:DISPLAY_PREFIX_LEN]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing widget API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )


async def require_auth_enabled(db: AsyncSession = Depends(get_db)) -> None:
    """Reject with 400 when auth_mode is 'none'.

    Declared before `get_current_active_user` in key-management routes so the
    400 contract fires before the 401 auth dependency would.
    """
    if await get_auth_mode(db) == "none":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": "widget_keys_require_auth",
                "message": "Widget API keys require auth_mode=local or oidc.",
            },
        )


async def require_widget_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, WidgetApiKey]:
    """Authenticate a widget request and return (user, key).

    Every failure path returns the same 401 to avoid leaking which check
    failed. Updates `last_used_at` at most once per `LAST_USED_THROTTLE`
    window to prevent write amplification on 60-second polls.
    """
    if await get_auth_mode(db) == "none":
        raise _unauthorized()

    if not x_api_key or not x_api_key.startswith(WIDGET_KEY_PREFIX):
        raise _unauthorized()

    token_hash = hash_widget_key(x_api_key)
    key_stmt = select(WidgetApiKey).where(WidgetApiKey.key_hash == token_hash)
    key = (await db.execute(key_stmt)).scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        raise _unauthorized()

    user_stmt = select(User).where(User.id == key.user_id)
    user = (await db.execute(user_stmt)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise _unauthorized()

    now = utc_now()
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_THROTTLE:
        key.last_used_at = now
        await db.commit()

    return user, key
