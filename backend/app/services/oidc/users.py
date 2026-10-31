"""OIDC login resolution and authorization URL building.

Functions for resolving an SSO login to a MyGarage account and creating users
from OIDC claims (with group-based admin role mapping), as well as constructing
the OIDC authorization URL for initiating the login flow.

Only the OIDC subject logs straight into an existing account. An email or
username match never links by itself: it offers the password-link page for the
matched account, or refuses the login when that account can't be confirmed. The
exception is a relink an admin armed on the account (``oidc_relink_until``),
which the next matching SSO login spends to link it.
"""

import base64
import hashlib
import logging
import secrets
from typing import Any, cast
from urllib.parse import urlencode

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.oidc import SSO_ACCOUNT_DISABLED, SSOError
from app.exceptions import OIDCLoginRefusedError, PendingLinkRequiredError
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.settings_service import parse_bool
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log
from app.utils.unit_resolution import new_user_unit_kwargs

from .config import effective_oidc_value
from .state import store_oidc_state

logger = logging.getLogger(__name__)

# Refusal messages, shown to the person signing in. A disabled account gets
# SSO_ACCOUNT_DISABLED.
_EMAIL_LINKED_ELSEWHERE = (
    "This email belongs to an account that is linked to a different sign-in. "
    "Ask an administrator to allow an SSO relink for it."
)
_EMAIL_NO_PASSWORD = (
    "An account with this email exists but has no password to confirm it. "
    "Ask an administrator to allow an SSO relink for it."
)
_USERNAME_LINKED_ELSEWHERE = (
    "This username belongs to an account that is linked to a different sign-in. "
    "Ask an administrator to allow an SSO relink for it."
)
_USERNAME_NO_PASSWORD = (
    "An account with this username exists but has no password to confirm it. "
    "Ask an administrator to allow an SSO relink for it."
)
_NO_ACCOUNT = (
    "No MyGarage account matches this sign-in, and automatic account creation is off. "
    "Ask an administrator to create your account."
)


async def _consume_armed_relink(
    db: AsyncSession,
    user: User,
    sub: str,
    provider_name: str,
    full_name: str,
    *,
    ip_address: str | None,
    user_agent: str | None,
) -> bool:
    """Link the account to this sub if an admin armed a relink on it, spending the arm.

    One conditional UPDATE links it and disarms it together, so an arm links once
    even when two SSO logins race for it, and an expired one links nothing. The
    link is audited as ``oidc_relink_used`` in the same commit.

    Args:
        db: Database session
        user: The account the email or username matched
        sub: The claimant's OIDC subject
        provider_name: The configured provider name
        full_name: The name claim, or empty to keep the account's
        ip_address: Where the sign-in came from, for the audit row
        user_agent: The sign-in's user agent, for the audit row

    Returns:
        True if the account is now linked to ``sub``, False if nothing was armed.
    """
    if user.oidc_relink_until is None:
        return False

    old_subject = user.oidc_subject
    now = utc_now()
    values: dict[str, Any] = {
        "oidc_subject": sub,
        "oidc_provider": provider_name,
        "auth_method": "oidc",
        "last_login": now,
        "oidc_relink_until": None,
    }
    if full_name:
        values["full_name"] = full_name
    result = await db.execute(
        update(User)
        .where(User.id == user.id, User.oidc_relink_until > now)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult[Any], result).rowcount != 1:
        # Expired, or spent or revoked since this login read the row.
        return False

    # Who used it and from where, so an admin can tell the user's own sign-in
    # from someone else's.
    db.add(
        AuditLog(
            user_id=user.id,
            username=user.username,
            action="oidc_relink_used",
            resource_type="user",
            resource_id=str(user.id),
            details={"old_subject": old_subject, "new_subject": sub},
            success=1,
            ip_address=ip_address,
            user_agent=user_agent,
            timestamp=now,
        )
    )
    await db.commit()
    await db.refresh(user)
    logger.info("OIDC relink approved by an admin was used: %s", sanitize_for_log(user.username))
    return True


def generate_state() -> str:
    """Generate a secure random state parameter for OIDC flow.

    Returns:
        Random state string
    """
    return secrets.token_urlsafe(32)


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and its S256 code_challenge (RFC 7636).

    Returns:
        Tuple of (code_verifier, code_challenge) where the challenge is the
        base64url(SHA-256(verifier)) with padding stripped.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


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
    # Generate state, nonce, and PKCE verifier/challenge (RFC 7636 S256)
    state = generate_state()
    nonce = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_pair()

    # Determine redirect URI
    redirect_uri = config.get("redirect_uri", "").strip()
    if not redirect_uri:
        # Auto-generate redirect URI (already prefix-aware: base_url includes
        # settings.root_path when the caller built it via oidc.py's
        # _external_base, #107)
        redirect_uri = f"{base_url.rstrip('/')}/api/auth/oidc/callback"
    elif settings.root_path and settings.root_path not in redirect_uri:
        # A manually-configured redirect_uri is used verbatim (admin's
        # responsibility per settings_init.py help text) — but warn loudly
        # since a missing subpath prefix here means an opaque IdP callback
        # mismatch at login time (#107).
        logger.warning(
            "Configured oidc_redirect_uri (%s) does not include the "
            "MYGARAGE_ROOT_PATH prefix (%s); the IdP callback will likely "
            "fail under this subpath. Update the setting to include the prefix.",
            redirect_uri,
            settings.root_path,
        )

    # Store state for validation in database
    await store_oidc_state(db, state, redirect_uri, nonce, code_verifier=code_verifier)

    # Build authorization URL
    auth_endpoint = metadata.get("authorization_endpoint")
    if not auth_endpoint:
        raise ValueError("Provider metadata missing authorization_endpoint")

    scopes = effective_oidc_value(config, "scopes")

    # Build query parameters
    params = {
        "client_id": config.get("client_id", ""),
        "response_type": "code",
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    # Construct URL
    auth_url = f"{auth_endpoint}?{urlencode(params)}"

    logger.debug("Created OIDC authorization URL for state: %s...", state[:16])
    return auth_url, state


async def create_or_update_user_from_oidc(
    db: AsyncSession,
    claims: dict[str, Any],
    userinfo: dict[str, Any] | None,
    config: dict[str, str],
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> User | None:
    """Resolve an SSO login to a MyGarage account, creating one if allowed.

    Strategy:
    1. A user with this oidc_subject logs in, and their name, provider and
       last_login are refreshed. A disabled account is refused. Any open
       relink is cancelled, since the sign-in it was for already works.
    2. A user with this email. In order: a disabled account is refused; an
       account with an unexpired admin-armed relink is linked to this subject
       and disarmed; an account already linked to a different subject is
       refused; an account with a password goes to the password-link page for
       its own username; an account with no password is refused. Only the armed
       relink writes to the row. The IdP's email-verified flag is not read, since
       the IdP verifying an address doesn't prove who owns the MyGarage account.
    3. A user with this username: a disabled account is refused; an armed
       relink links it as in step 2; an SSO-only account, or one linked to a
       different subject, is refused; otherwise the password-link page.
    4. No match: create the user if auto_create is enabled, else refuse.

    Every refusal is raised before anything on the matched row is assigned.

    Args:
        db: Database session
        claims: ID token claims
        userinfo: Optional userinfo claims
        config: OIDC configuration
        ip_address: The sign-in's IP, recorded if it uses an armed relink
        user_agent: The sign-in's user agent, recorded the same way

    Returns:
        User object, or None when the claims have no subject or no email

    Raises:
        PendingLinkRequiredError: An email or username match needs the matched
            account's password before it can be linked.
        OIDCLoginRefusedError: The matched account can't be signed into this way,
            or nothing matched and auto-create is off.
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
    username_claim = effective_oidc_value(config, "username_claim")
    email_claim = effective_oidc_value(config, "email_claim")
    name_claim = effective_oidc_value(config, "full_name_claim")

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

    # Step 1: subject match. A disabled account is refused before the row is touched.
    result = await db.execute(select(User).where(User.oidc_subject == sub))
    user = result.scalar_one_or_none()

    if user:
        if not user.is_active:
            logger.warning(
                "OIDC login refused, account disabled: %s", sanitize_for_log(user.username)
            )
            raise OIDCLoginRefusedError(
                SSO_ACCOUNT_DISABLED, code=SSOError.ACCOUNT_DISABLED, username=user.username
            )

        logger.info("Found existing OIDC user: %s", sanitize_for_log(user.username))
        user.full_name = full_name or user.full_name
        user.last_login = utc_now()
        user.oidc_provider = provider_name
        # Their sign-in works, so a relink left open is only a way in for someone else.
        user.oidc_relink_until = None
        await db.commit()
        await db.refresh(user)
        return user

    # Step 2: email match. The email only says which account to offer, it never
    # proves the claimant owns it, so the row is only written when an admin armed
    # a relink on it.
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user:
        if not user.is_active:
            logger.warning(
                "OIDC login refused, email matched a disabled account: %s",
                sanitize_for_log(user.username),
            )
            raise OIDCLoginRefusedError(
                SSO_ACCOUNT_DISABLED, code=SSOError.ACCOUNT_DISABLED, username=user.username
            )

        if await _consume_armed_relink(
            db,
            user,
            sub,
            provider_name,
            full_name,
            ip_address=ip_address,
            user_agent=user_agent,
        ):
            return user

        # Step 1 didn't find this sub, so any subject here belongs to someone else.
        if user.oidc_subject:
            logger.warning(
                "OIDC login refused, email matched an account linked to a different subject: %s",
                sanitize_for_log(user.username),
            )
            raise OIDCLoginRefusedError(
                _EMAIL_LINKED_ELSEWHERE,
                code=SSOError.EMAIL_LINKED_ELSEWHERE,
                username=user.username,
            )

        if user.hashed_password is None:
            logger.warning(
                "OIDC login refused, email matched an account with no password: %s",
                sanitize_for_log(user.username),
            )
            raise OIDCLoginRefusedError(
                _EMAIL_NO_PASSWORD, code=SSOError.EMAIL_NO_PASSWORD, username=user.username
            )

        # The pending link finds its target by username, so it has to be this
        # account's, not whatever the claim says.
        logger.info(
            "Email match requires password verification: %s", sanitize_for_log(user.username)
        )
        raise PendingLinkRequiredError(
            username=user.username, claims=claims, userinfo=userinfo, config=config
        )

    # Step 3: username match, which also needs the account's password to link.
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user:
        if not user.is_active:
            logger.warning(
                "OIDC login refused, username matched a disabled account: %s",
                sanitize_for_log(user.username),
            )
            raise OIDCLoginRefusedError(
                SSO_ACCOUNT_DISABLED, code=SSOError.ACCOUNT_DISABLED, username=user.username
            )

        if await _consume_armed_relink(
            db,
            user,
            sub,
            provider_name,
            full_name,
            ip_address=ip_address,
            user_agent=user_agent,
        ):
            return user

        if user.hashed_password is None:
            logger.warning(
                "OIDC login refused, username matched an account with no password: %s",
                sanitize_for_log(user.username),
            )
            raise OIDCLoginRefusedError(
                _USERNAME_NO_PASSWORD, code=SSOError.USERNAME_NO_PASSWORD, username=user.username
            )

        if user.oidc_subject and user.oidc_subject != sub:
            logger.warning(
                "OIDC login refused, username matched an account linked to a different subject: %s",
                sanitize_for_log(user.username),
            )
            raise OIDCLoginRefusedError(
                _USERNAME_LINKED_ELSEWHERE,
                code=SSOError.USERNAME_LINKED_ELSEWHERE,
                username=user.username,
            )

        logger.info(
            "Username match requires password verification: %s", sanitize_for_log(user.username)
        )
        raise PendingLinkRequiredError(
            username=user.username, claims=claims, userinfo=userinfo, config=config
        )

    # Step 4: no match. Refused like the others when auto-create is off, so it's audited too.
    # A missing setting falls back to "true", so on; a blank one is off (R4).
    auto_create = parse_bool(config.get("auto_create_users", "true"), default=False)
    if not auto_create:
        logger.warning(
            "User not found for email %s and auto-create is disabled", sanitize_for_log(email)
        )
        # No account to name in the audit row, so it names who the sign-in claimed to be.
        raise OIDCLoginRefusedError(
            _NO_ACCOUNT,
            code=SSOError.NO_ACCOUNT,
            details={"claimed_email": email, "claimed_username": username or None},
        )

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
    unit_kwargs = await new_user_unit_kwargs(db)
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
        **unit_kwargs,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("Created new OIDC user: %s (admin=%s)", sanitize_for_log(user.username), is_admin)
    return user
