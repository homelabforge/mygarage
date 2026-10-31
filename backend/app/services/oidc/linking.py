"""OIDC account linking with password verification.

Functions for creating pending link tokens and validating them with password
verification to securely link OIDC accounts to existing local accounts
when the email or username claim matches an account that has a password.
Apart from a relink an admin armed on the account (see users.py), this is the
only way an email or username match ever links.
"""

import json
import logging
import secrets
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.oidc import SSO_ACCOUNT_DISABLED, SSOError
from app.exceptions import OIDCLoginRefusedError
from app.models.audit_log import AuditLog
from app.models.oidc_pending_link import OIDCPendingLink
from app.models.settings import Setting
from app.models.user import User
from app.services.auth import verify_password
from app.services.oidc.config import effective_oidc_value, get_oidc_config
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


async def _cleanup_expired_pending_links(db: AsyncSession) -> None:
    """Remove expired pending link tokens from database (older than expiration time).

    Args:
        db: Database session
    """
    cutoff = utc_now()
    await db.execute(delete(OIDCPendingLink).where(OIDCPendingLink.expires_at <= cutoff))
    await db.commit()


async def create_pending_link_token(
    db: AsyncSession,
    username: str,
    claims: dict[str, Any],
    userinfo: dict[str, Any] | None,
    config: dict[str, str],
) -> str:
    """Create a pending link token for a password-confirmed OIDC account link.

    This function creates a temporary token that allows a user to link their OIDC
    account to an existing local account by verifying their password. It's used
    when the email or username claim matched an account that has a password.

    Args:
        db: Database session
        username: The matched account's username (for an email match, not the claim's)
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
        created_at=utc_now(),
        expires_at=expires_at,
    )

    db.add(pending_link)
    await db.commit()

    logger.info(
        "Created pending link token for username: %s (expires in %s minutes)",
        sanitize_for_log(username),
        expire_minutes,
    )
    return token


async def validate_and_consume_pending_link(
    db: AsyncSession,
    token: str,
    password: str,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[User | None, str | None]:
    """Validate pending link token and link OIDC account to existing user.

    This function validates the pending link token, verifies the user's password,
    and links the OIDC account to the existing local account.

    Everything is re-checked here, since the account can change in the minutes
    the token lives. Security checks, in order:
    - Token exists and not expired
    - Attempt count < max attempts
    - User is active (before the password, and nothing is linked or counted)
    - User has password (not OIDC-only)
    - User not already linked to different oidc_subject
    - Password verification passes

    Every refusal deletes the pending link, except a wrong password with
    attempts left. A link is audited as ``oidc_account_linked`` in the same
    commit as the link and the token's delete, so one can't land without the
    other.

    Args:
        db: Database session
        token: Pending link token from URL
        password: Password provided by user
        ip_address: Where the link request came from, for the audit row
        user_agent: The link request's user agent, for the audit row

    Returns:
        Tuple of (User, error_message). If User is None, error_message contains
        specific error for display.

    Raises:
        OIDCLoginRefusedError: The matched account is disabled. The pending
            link is already deleted and committed when it's raised.
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
        logger.warning("Pending link token expired: %s", sanitize_for_log(pending_link.username))
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
        logger.warning(
            "Max password attempts exceeded for username: %s",
            sanitize_for_log(pending_link.username),
        )
        await db.delete(pending_link)
        await db.commit()
        return (None, "Too many failed attempts. Please log in again.")

    # Find user by username
    result = await db.execute(select(User).where(User.username == pending_link.username))
    user = result.scalar_one_or_none()

    if not user:
        logger.error("User not found for pending link: %s", sanitize_for_log(pending_link.username))
        await db.delete(pending_link)
        await db.commit()
        return (None, "Link expired, please log in again")

    # A disabled account is refused before its password is checked, so the answer
    # never depends on the password, and nothing gets linked or counted.
    if not user.is_active:
        username = user.username
        logger.warning("Pending link refused, account disabled: %s", sanitize_for_log(username))
        await db.delete(pending_link)
        await db.commit()
        raise OIDCLoginRefusedError(
            SSO_ACCOUNT_DISABLED, code=SSOError.ACCOUNT_DISABLED, username=username
        )

    # Security check: user must have a password (not OIDC-only)
    if user.hashed_password is None:
        logger.error(
            "Username match for OIDC-only user (no password): %s",
            sanitize_for_log(pending_link.username),
        )
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
            sanitize_for_log(pending_link.username),
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
            sanitize_for_log(pending_link.username),
            pending_link.attempt_count,
            max_attempts,
        )

        if remaining <= 0:
            await db.delete(pending_link)
            await db.commit()
            return (None, "Too many failed attempts. Please log in again.")

        return (None, f"Invalid password. {remaining} attempt(s) remaining.")

    # Password correct - link accounts
    logger.info(
        "Password verified, linking OIDC account to user: %s",
        sanitize_for_log(pending_link.username),
    )

    # Merge claims
    all_claims = {**claims}
    if userinfo:
        all_claims.update(userinfo)

    # The pending link stores claims, not config, so read the claim name now.
    name_claim = effective_oidc_value(await get_oidc_config(db), "full_name_claim")
    full_name = all_claims.get(name_claim, "")

    # Update user with OIDC information
    user.oidc_subject = sub
    user.oidc_provider = pending_link.provider_name
    user.auth_method = "oidc"  # Primary auth method is now OIDC
    if full_name:
        user.full_name = full_name
    user.last_login = utc_now()
    # They proved the account with its password, so an open relink isn't needed.
    user.oidc_relink_until = None

    db.add(
        AuditLog(
            user_id=user.id,
            username=user.username,
            action="oidc_account_linked",
            resource_type="user",
            resource_id=str(user.id),
            details={"provider": user.oidc_provider, "oidc_subject": user.oidc_subject},
            ip_address=ip_address,
            user_agent=user_agent,
            timestamp=utc_now(),
        )
    )

    # Delete pending link token (one-time use)
    await db.delete(pending_link)
    await db.commit()
    await db.refresh(user)

    logger.info(
        "Successfully linked OIDC account to existing user: %s", sanitize_for_log(user.username)
    )
    return (user, None)
