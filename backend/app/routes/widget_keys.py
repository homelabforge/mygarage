"""User-scoped widget API key management.

Mounted at `/api/auth/me/widget-keys` to match the existing `/me` surface
(profile, password change, etc.) — keys belong to the authenticated user,
not to an admin-level system settings page.

The 400 vs 401 contract for auth_mode=none is enforced by dependency order:
`require_auth_enabled` is declared before `get_current_active_user` so a
misconfigured install fails loudly with a specific "widget_keys_require_auth"
detail instead of a generic 401.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.widget_api_key import WidgetApiKey
from app.schemas.widget_key import (
    WidgetKeyCreate,
    WidgetKeyCreated,
    WidgetKeyList,
    WidgetKeySummary,
)
from app.services.auth import get_current_active_user
from app.services.widget_auth import (
    display_prefix,
    generate_widget_key,
    hash_widget_key,
    require_auth_enabled,
)
from app.utils.datetime_utils import utc_now

router = APIRouter(prefix="/api/auth/me/widget-keys", tags=["widget-keys"])


def _to_summary(key: WidgetApiKey) -> WidgetKeySummary:
    return WidgetKeySummary(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        scope=key.scope,
        allowed_vins=key.allowed_vins,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WidgetKeyCreated)
async def create_widget_key(
    payload: WidgetKeyCreate,
    _: None = Depends(require_auth_enabled),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetKeyCreated:
    """Create a widget key for the current user.

    The plaintext secret is returned ONCE in this response. Only the SHA-256
    hash plus an 8-char display prefix are persisted; the full value is not
    retrievable after this call.
    """
    secret = generate_widget_key()
    key = WidgetApiKey(
        user_id=current_user.id,
        name=payload.name,
        key_hash=hash_widget_key(secret),
        key_prefix=display_prefix(secret),
        scope=payload.scope,
        allowed_vins=payload.allowed_vins,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    summary = _to_summary(key)
    return WidgetKeyCreated(**summary.model_dump(), secret=secret)


@router.get("", response_model=WidgetKeyList)
async def list_widget_keys(
    _: None = Depends(require_auth_enabled),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetKeyList:
    """List the current user's widget keys (metadata only, never secrets).

    Revoked keys remain in the list with `revoked_at` populated so the user
    retains an audit trail of previously-issued keys.
    """
    stmt = (
        select(WidgetApiKey)
        .where(WidgetApiKey.user_id == current_user.id)
        .order_by(WidgetApiKey.created_at.desc())
    )
    keys = (await db.execute(stmt)).scalars().all()
    return WidgetKeyList(keys=[_to_summary(k) for k in keys])


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_widget_key(
    key_id: int,
    _: None = Depends(require_auth_enabled),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-revoke a widget key by setting `revoked_at`.

    Returns 404 (not 403) for keys owned by another user to avoid confirming
    existence. Revoking an already-revoked key is a no-op and still returns
    204 — idempotent from the client's perspective.
    """
    stmt = select(WidgetApiKey).where(
        WidgetApiKey.id == key_id,
        WidgetApiKey.user_id == current_user.id,
    )
    key = (await db.execute(stmt)).scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if key.revoked_at is None:
        key.revoked_at = utc_now()
        await db.commit()
