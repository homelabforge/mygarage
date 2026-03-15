"""OIDC account linking with password verification.

Functions for creating pending link tokens and validating them with password
verification to securely link OIDC accounts to existing local accounts
when only username (not email) matches.
"""

import json
import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.oidc_pending_link import OIDCPendingLink
from app.models.settings import Setting
from app.models.user import User
from app.services.auth import verify_password

logger = logging.getLogger(__name__)


async def _cleanup_expired_pending_links(db: AsyncSession) -> None:
    """Remove expired pending link tokens from database (older than expiration time).

    Args:
        db: Database session
    """
    cutoff = datetime.now(UTC)
    await db.execute(delete(OIDCPendingLink).where(OIDCPendingLink.expires_at <= cutoff))
    await db.commit()


async def create_pending_link_token(
    db: AsyncSession,
    username: str,
    claims: dict[str, Any],
    userinfo: dict[str, Any] | None,
    config: dict[str, str],
) -> str:
    """Create pending link token for username-based OIDC account linking.

    This function creates a temporary token that allows a user to link their OIDC
    account to an existing local account by verifying their password.

    Args:
        db: Database session
        username: The matched username requiring verification
        claims: ID token claims from OIDC provider
        userinfo: Optional userinfo endpoint claims
        config: OIDC configuration

    Returns:
        64-character URL-safe token string
    """
    # Clean up expired tokens first
    await _cleanup_expired_pending_links(db)

    # Generate cryptographically random token
    token = secrets.token_urlsafe(48)  # 48 bytes = 64 URL-safe chars

    # Get expiration from settings (default 5 minutes)
    expire_minutes = int(config.get("link_token_expire_minutes", "5"))
    expires_at = OIDCPendingLink.get_expiry_time(expire_minutes)

    # Get provider name
    provider_name = config.get("provider_name", "OIDC Provider")

    # Serialize claims as JSON (convert to dict for JSON storage)
    oidc_claims_json = json.dumps(claims)
    userinfo_claims_json = json.dumps(userinfo) if userinfo else None

    # Create pending link record
    pending_link = OIDCPendingLink(
        token=token,
        username=username,
        oidc_claims=oidc_claims_json,
        userinfo_claims=userinfo_claims_json,
        provider_name=provider_name,
        attempt_count=0,
        created_at=datetime.now(UTC),
        expires_at=expires_at,
    )

    db.add(pending_link)
    await db.commit()

    logger.info(
        "Created pending link token for username: %s (expires in %s minutes)",
        username,
        expire_minutes,
    )
    return token


async def validate_and_consume_pending_link(
    db: AsyncSession,
    token: str,
    password: str,
) -> tuple[User | None, str | None]:
    """Validate pending link token and link OIDC account to existing user.

    This function validates the pending link token, verifies the user's password,
    and links the OIDC account to the existing local account.

    Security checks:
    - Token exists and not expired
    - Attempt count < max attempts
    - User has password (not OIDC-only)
    - User not already linked to different oidc_subject
    - Password verification passes

    Args:
        db: Database session
        token: Pending link token from URL
        password: Password provided by user

    Returns:
        Tuple of (User, error_message). If User is None, error_message contains
        specific error for display.
    """
    # Clean up expired tokens first
    await _cleanup_expired_pending_links(db)

    # Find pending link by token
    result = await db.execute(select(OIDCPendingLink).where(OIDCPendingLink.token == token))
    pending_link = result.scalar_one_or_none()

    if not pending_link:
        logger.warning("Pending link token not found or expired: %s...", token[:16])
        return (None, "Link expired, please log in again")

    # Check if expired
    if pending_link.is_expired():
        logger.warning("Pending link token expired: %s", pending_link.username)
        await db.delete(pending_link)
        await db.commit()
        return (None, "Link expired, please log in again")

    # Get max attempts from settings (need to fetch from DB)
    result = await db.execute(
        select(Setting).where(Setting.key == "oidc_link_max_password_attempts")
    )
    setting = result.scalar_one_or_none()
    max_attempts = int(setting.value) if setting and setting.value else 3

    # Check attempt count
    if pending_link.attempt_count >= max_attempts:
        logger.warning("Max password attempts exceeded for username: %s", pending_link.username)
        await db.delete(pending_link)
        await db.commit()
        return (None, "Too many failed attempts. Please log in again.")

    # Find user by username
    result = await db.execute(select(User).where(User.username == pending_link.username))
    user = result.scalar_one_or_none()

    if not user:
        logger.error("User not found for pending link: %s", pending_link.username)
        await db.delete(pending_link)
        await db.commit()
        return (None, "Link expired, please log in again")

    # Security check: user must have a password (not OIDC-only)
    if user.hashed_password is None:
        logger.error("Username match for OIDC-only user (no password): %s", pending_link.username)
        await db.delete(pending_link)
        await db.commit()
        return (None, "Link expired, please log in again")

    # Deserialize claims
    claims = json.loads(pending_link.oidc_claims)
    userinfo = json.loads(pending_link.userinfo_claims) if pending_link.userinfo_claims else None
    sub = claims.get("sub")

    if not sub:
        logger.error("Pending link missing 'sub' claim")
        await db.delete(pending_link)
        await db.commit()
        return (None, "Link expired, please log in again")

    # Security check: user not already linked to different OIDC account
    if user.oidc_subject and user.oidc_subject != sub:
        logger.error(
            "Username conflict: %s already linked to different OIDC account",
            pending_link.username,
        )
        await db.delete(pending_link)
        await db.commit()
        return (
            None,
            "Account already linked to different provider. Please contact support.",
        )

    # Verify password
    if not verify_password(password, user.hashed_password):
        # Increment attempt count
        pending_link.attempt_count += 1
        await db.commit()

        remaining = max_attempts - pending_link.attempt_count
        logger.warning(
            "Invalid password attempt for username: %s (%s/%s)",
            pending_link.username,
            pending_link.attempt_count,
            max_attempts,
        )

        if remaining <= 0:
            await db.delete(pending_link)
            await db.commit()
            return (None, "Too many failed attempts. Please log in again.")

        return (None, f"Invalid password. {remaining} attempt(s) remaining.")

    # Password correct - link accounts
    logger.info("Password verified, linking OIDC account to user: %s", pending_link.username)

    # Merge claims
    all_claims = {**claims}
    if userinfo:
        all_claims.update(userinfo)

    # Extract full name if available
    name_claim = "name"
    full_name = all_claims.get(name_claim, "")

    # Update user with OIDC information
    user.oidc_subject = sub
    user.oidc_provider = pending_link.provider_name
    user.auth_method = "oidc"  # Primary auth method is now OIDC
    if full_name:
        user.full_name = full_name
    user.last_login = datetime.now(UTC)

    # Delete pending link token (one-time use)
    await db.delete(pending_link)
    await db.commit()
    await db.refresh(user)

    logger.info("Successfully linked OIDC account to existing user: %s", user.username)
    return (user, None)
