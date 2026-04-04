"""OIDC user creation and authorization URL building.

Functions for creating/updating users from OIDC claims, including email-based
account linking and group-based admin role mapping, as well as constructing
the OIDC authorization URL for initiating the login flow.
"""

import logging
import secrets
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log

from .state import store_oidc_state

logger = logging.getLogger(__name__)


def generate_state() -> str:
    """Generate a secure random state parameter for OIDC flow.

    Returns:
        Random state string
    """
    return secrets.token_urlsafe(32)


async def create_authorization_url(
    db: AsyncSession,
    config: dict[str, str],
    metadata: dict[str, Any],
    base_url: str,
) -> tuple[str, str]:
    """Create OIDC authorization URL.

    Args:
        db: Database session
        config: OIDC configuration from database
        metadata: Provider metadata
        base_url: Application base URL (e.g., https://mygarage.example.com)

    Returns:
        Tuple of (authorization_url, state)
    """
    # Generate state and nonce
    state = generate_state()
    nonce = secrets.token_urlsafe(32)

    # Determine redirect URI
    redirect_uri = config.get("redirect_uri", "").strip()
    if not redirect_uri:
        # Auto-generate redirect URI
        redirect_uri = f"{base_url.rstrip('/')}/api/auth/oidc/callback"

    # Store state for validation in database
    await store_oidc_state(db, state, redirect_uri, nonce)

    # Build authorization URL
    auth_endpoint = metadata.get("authorization_endpoint")
    if not auth_endpoint:
        raise ValueError("Provider metadata missing authorization_endpoint")

    scopes = config.get("scopes", "openid profile email")

    # Build query parameters
    params = {
        "client_id": config.get("client_id", ""),
        "response_type": "code",
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
    }

    # Construct URL
    auth_url = f"{auth_endpoint}?{urlencode(params)}"

    logger.info("Created OIDC authorization URL for state: %s", state)
    return auth_url, state


async def create_or_update_user_from_oidc(
    db: AsyncSession,
    claims: dict[str, Any],
    userinfo: dict[str, Any] | None,
    config: dict[str, str],
) -> User | None:
    """Create or update user from OIDC claims.

    Strategy:
    1. Check if user exists with matching oidc_subject
    2. If not, check if user exists with matching email (account linking)
    3. If still not found and auto_create is enabled, create new user
    4. Update user with latest claims

    Args:
        db: Database session
        claims: ID token claims
        userinfo: Optional userinfo claims
        config: OIDC configuration

    Returns:
        User object or None if creation/update fails
    """
    # Extract claims using configured claim names
    sub = claims.get("sub")
    if not sub:
        logger.error("ID token missing 'sub' claim")
        return None

    # Merge claims and userinfo (userinfo takes precedence)
    all_claims = {**claims}
    if userinfo:
        all_claims.update(userinfo)

    # Extract user info from claims
    username_claim = config.get("username_claim", "preferred_username")
    email_claim = config.get("email_claim", "email")
    name_claim = config.get("name_claim", "name")

    username = all_claims.get(
        username_claim,
        all_claims.get("preferred_username", all_claims.get("email", "")),
    ).split("@")[0]
    email = all_claims.get(email_claim, "")
    full_name = all_claims.get(name_claim, "")

    if not email:
        logger.error("OIDC claims missing email (claim: %s)", email_claim)
        return None

    provider_name = config.get("provider_name", "OIDC Provider")

    # Check if user exists with this oidc_subject
    result = await db.execute(select(User).where(User.oidc_subject == sub))
    user = result.scalar_one_or_none()

    if user:
        # Update existing OIDC user
        logger.info("Found existing OIDC user: %s", sanitize_for_log(user.username))
        user.full_name = full_name or user.full_name
        user.last_login = utc_now()
        user.oidc_provider = provider_name
        await db.commit()
        await db.refresh(user)
        return user

    # Check for existing user with matching email (account linking)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user:
        # Link OIDC to existing local account
        logger.info("Linking OIDC account to existing user: %s", sanitize_for_log(user.username))
        user.oidc_subject = sub
        user.oidc_provider = provider_name
        user.auth_method = "oidc"  # Primary auth method is now OIDC
        user.full_name = full_name or user.full_name
        user.last_login = utc_now()
        await db.commit()
        await db.refresh(user)
        return user

    # Check for existing user with matching username (requires password verification)
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user:
        # Username match found but no OIDC link exists
        if user.hashed_password is None:
            # OIDC-only user (no password) - raise explicit error
            logger.error(
                "Username match for OIDC-only user (no password): %s", sanitize_for_log(username)
            )
            raise ValueError(
                f"Username '{username}' exists as SSO-only account. Contact support to link this account."
            )
        elif user.oidc_subject and user.oidc_subject != sub:
            # Already linked to different OIDC account - conflict
            logger.error(
                "Username conflict: %s already linked to different OIDC account",
                sanitize_for_log(username),
            )
            raise ValueError(
                f"Username '{username}' is already linked to a different account. Please contact support."
            )
        else:
            # Valid candidate for username-based linking - requires password verification
            logger.info(
                "Username match requires password verification: %s", sanitize_for_log(username)
            )
            from app.exceptions import PendingLinkRequiredError

            raise PendingLinkRequiredError(
                username=username, claims=claims, userinfo=userinfo, config=config
            )

    # Check if auto-create is enabled
    auto_create = config.get("auto_create_users", "true").lower() == "true"
    if not auto_create:
        logger.warning(
            "User not found for email %s and auto-create is disabled", sanitize_for_log(email)
        )
        return None

    # Create new user from OIDC claims
    logger.info("Creating new user from OIDC claims: %s", sanitize_for_log(email))

    # Determine if user should be admin based on groups
    is_admin = False
    admin_group = config.get("admin_group", "").strip()
    if admin_group:
        groups = all_claims.get("groups", [])
        if isinstance(groups, list) and admin_group in groups:
            is_admin = True
            logger.info("User is member of admin group '%s'", admin_group)

    # Check if this is the first user (auto-admin)
    result = await db.execute(select(User))
    existing_users = result.scalars().all()
    if not existing_users:
        is_admin = True
        logger.info("First user - granting admin privileges")

    # Ensure unique username
    base_username = username
    counter = 1
    while True:
        result = await db.execute(select(User).where(User.username == username))
        if not result.scalar_one_or_none():
            break
        username = f"{base_username}{counter}"
        counter += 1

    # Create user (no password required for OIDC-only users)
    user = User(
        username=username,
        email=email,
        hashed_password=None,  # OIDC users don't need password
        full_name=full_name,
        is_admin=is_admin,
        is_active=True,
        oidc_subject=sub,
        oidc_provider=provider_name,
        auth_method="oidc",
        last_login=utc_now(),
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("Created new OIDC user: %s (admin=%s)", sanitize_for_log(user.username), is_admin)
    return user
