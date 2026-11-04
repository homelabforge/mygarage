"""OIDC state management for authorization flow.

Functions for storing, validating, and consuming OIDC state parameters
used to prevent CSRF attacks during the OAuth2/OIDC authorization flow.
"""

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.oidc_state import OIDCState
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


async def _cleanup_expired_states(db: AsyncSession) -> None:
    """Remove expired OIDC states from database (older than 10 minutes).

    Args:
        db: Database session
    """
    cutoff = utc_now()
    await db.execute(delete(OIDCState).where(OIDCState.expires_at <= cutoff))
    await db.commit()


async def store_oidc_state(
    db: AsyncSession,
    state: str,
    redirect_uri: str,
    nonce: str,
    code_verifier: str | None = None,
) -> None:
    """Store OIDC state in database for validation after callback.

    Replaces in-memory storage for multi-worker reliability and persistence
    across container restarts.

    Args:
        db: Database session
        state: State parameter
        redirect_uri: Redirect URI used in auth request
        nonce: Nonce value for ID token validation
        code_verifier: PKCE code_verifier to be sent in token exchange
    """
    await _cleanup_expired_states(db)

    oidc_state = OIDCState(
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        created_at=utc_now(),
        expires_at=OIDCState.get_expiry_time(minutes=10),
    )
    db.add(oidc_state)
    await db.commit()
    logger.debug("Stored OIDC state: %s...", state[:16])


async def validate_and_consume_state(db: AsyncSession, state: str) -> dict[str, Any] | None:
    """Validate and consume OIDC state from database (one-time use).

    Args:
        db: Database session
        state: State parameter from callback

    Returns:
        State data if valid, None otherwise
    """
    await _cleanup_expired_states(db)

    # Find and validate state
    result = await db.execute(select(OIDCState).where(OIDCState.state == state))
    oidc_state = result.scalar_one_or_none()

    if not oidc_state:
        logger.warning("Invalid or expired OIDC state: %s...", sanitize_for_log(state[:16]))
        return None

    if oidc_state.is_expired():
        logger.warning("OIDC state expired: %s...", sanitize_for_log(state[:16]))
        await db.delete(oidc_state)
        await db.commit()
        return None

    # Convert to dictionary for compatibility with existing code
    state_data = {
        "redirect_uri": oidc_state.redirect_uri,
        "nonce": oidc_state.nonce,
        "code_verifier": oidc_state.code_verifier,
        "created_at": oidc_state.created_at,
    }

    # Delete state (one-time use)
    await db.delete(oidc_state)
    await db.commit()

    logger.debug("Validated and consumed OIDC state: %s...", sanitize_for_log(state[:16]))
    return state_data
