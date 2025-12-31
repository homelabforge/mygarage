"""OIDC/OpenID Connect authentication service.

This service handles OAuth2/OIDC authentication flow with support for:
- Generic OIDC provider support (Authentik, Keycloak, Auth0, Okta, etc.)
- Email-based account linking (links OIDC to existing local accounts)
- Automatic user creation from OIDC claims
- Group-based admin role mapping
- Provider metadata discovery
- Token validation and user info retrieval
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportArgumentType=false

import logging
import secrets
from typing import Optional, Dict, Any
from datetime import datetime, timezone

import httpx
from authlib.jose import jwt, JsonWebKey, JoseError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.settings import Setting
from app.models.oidc_state import OIDCState
from app.utils.url_validation import validate_oidc_url
from app.exceptions import SSRFProtectionError

logger = logging.getLogger(__name__)


def mask_secret(secret: str, show_chars: int = 4) -> str:
    """Mask a secret value for safe logging.

    Shows only the first and last few characters of a secret,
    masking the middle portion. This allows for debugging while
    protecting sensitive data from log exposure.

    Args:
        secret: The secret string to mask
        show_chars: Number of characters to show at start and end (default: 4)

    Returns:
        Masked string in format "abc****...****xyz"

    Examples:
        >>> mask_secret("very_secret_client_id_12345")
        "very****...****2345"
        >>> mask_secret("short")
        "****"
    """
    if not secret or len(secret) <= show_chars * 2:
        return "****"
    return f"{secret[:show_chars]}****...****{secret[-show_chars:]}"


async def _cleanup_expired_states(db: AsyncSession):
    """Remove expired OIDC states from database (older than 10 minutes).

    Args:
        db: Database session
    """
    from sqlalchemy import delete

    cutoff = datetime.now(timezone.utc)
    await db.execute(delete(OIDCState).where(OIDCState.expires_at <= cutoff))
    await db.commit()


async def _cleanup_expired_pending_links(db: AsyncSession):
    """Remove expired pending link tokens from database (older than expiration time).

    Args:
        db: Database session
    """
    from sqlalchemy import delete
    from app.models.oidc_pending_link import OIDCPendingLink

    cutoff = datetime.now(timezone.utc)
    await db.execute(
        delete(OIDCPendingLink).where(OIDCPendingLink.expires_at <= cutoff)
    )
    await db.commit()


async def get_oidc_config(db: AsyncSession) -> Dict[str, str]:
    """Get OIDC configuration from database settings.

    Returns:
        Dictionary with OIDC configuration values
    """
    result = await db.execute(select(Setting).where(Setting.key.like("oidc_%")))
    settings = result.scalars().all()

    config = {}
    for setting in settings:
        # Remove 'oidc_' prefix for cleaner keys
        key = setting.key.replace("oidc_", "")
        config[key] = setting.value or ""

    return config


async def get_provider_metadata(issuer_url: str) -> Optional[Dict[str, Any]]:
    """Fetch OIDC provider metadata from well-known endpoint.

    Args:
        issuer_url: OIDC issuer URL

    Returns:
        Provider metadata dictionary or None if fetch fails

    Raises:
        SSRFProtectionError: If issuer_url fails SSRF validation (private IPs, localhost, etc.)
    """
    # Ensure issuer URL doesn't have trailing slash
    issuer_url = issuer_url.rstrip("/")

    # SECURITY: Validate issuer URL against SSRF attacks (CWE-918)
    # This prevents attackers from accessing internal services, cloud metadata endpoints,
    # or other private resources by manipulating the OIDC issuer URL
    try:
        validate_oidc_url(issuer_url)
    except (SSRFProtectionError, ValueError) as e:
        # Don't log the full URL - it could contain secrets in query params
        logger.error("SSRF protection blocked OIDC issuer URL: %s", str(e))
        raise SSRFProtectionError(f"Invalid OIDC issuer URL: {e}")

    # Try standard OIDC discovery endpoint
    discovery_url = f"{issuer_url}/.well-known/openid-configuration"

    # SECURITY: Validate discovery URL as well (defense in depth)
    try:
        validate_oidc_url(discovery_url)
    except (SSRFProtectionError, ValueError) as e:
        # Don't log the full URL - it could contain secrets in query params
        logger.error("SSRF protection blocked OIDC discovery URL: %s", str(e))
        raise SSRFProtectionError(f"Invalid OIDC discovery URL: {e}")

    try:
        async with httpx.AsyncClient() as client:
            # codeql[py/partial-ssrf] - URL validated by validate_oidc_url above
            response = await client.get(discovery_url, timeout=10.0)
            response.raise_for_status()
            metadata = response.json()

            logger.info("Successfully fetched OIDC metadata")
            return metadata

    except httpx.TimeoutException:
        logger.error("OIDC metadata request timeout")
        return None  # Intentional fallback: metadata fetch is optional
    except httpx.ConnectError as e:
        # Don't log the full URL - it could contain secrets in query params
        logger.error("Cannot connect to OIDC provider: %s", str(e))
        return None  # Intentional fallback: allow graceful degradation
    except httpx.HTTPStatusError as e:
        logger.error("OIDC provider returned error: %s", str(e))
        return None  # Intentional fallback


def generate_state() -> str:
    """Generate a secure random state parameter for OIDC flow.

    Returns:
        Random state string
    """
    return secrets.token_urlsafe(32)


async def store_oidc_state(db: AsyncSession, state: str, redirect_uri: str, nonce: str):
    """Store OIDC state in database for validation after callback.

    Replaces in-memory storage for multi-worker reliability and persistence
    across container restarts.

    Args:
        db: Database session
        state: State parameter
        redirect_uri: Redirect URI used in auth request
        nonce: Nonce value for ID token validation
    """
    await _cleanup_expired_states(db)

    oidc_state = OIDCState(
        state=state,
        nonce=nonce,
        redirect_uri=redirect_uri,
        created_at=datetime.now(timezone.utc),
        expires_at=OIDCState.get_expiry_time(minutes=10),
    )
    db.add(oidc_state)
    await db.commit()
    logger.debug("Stored OIDC state: %s...", state[:16])


async def validate_and_consume_state(
    db: AsyncSession, state: str
) -> Optional[Dict[str, Any]]:
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
        logger.warning("Invalid or expired OIDC state: %s...", state[:16])
        return None

    if oidc_state.is_expired():
        logger.warning("OIDC state expired: %s...", state[:16])
        await db.delete(oidc_state)
        await db.commit()
        return None

    # Convert to dictionary for compatibility with existing code
    state_data = {
        "redirect_uri": oidc_state.redirect_uri,
        "nonce": oidc_state.nonce,
        "created_at": oidc_state.created_at,
    }

    # Delete state (one-time use)
    await db.delete(oidc_state)
    await db.commit()

    logger.debug("Validated and consumed OIDC state: %s...", state[:16])
    return state_data


async def create_authorization_url(
    db: AsyncSession,
    config: Dict[str, str],
    metadata: Dict[str, Any],
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
    from urllib.parse import urlencode

    auth_url = f"{auth_endpoint}?{urlencode(params)}"

    logger.info("Created OIDC authorization URL for state: %s", state)
    return auth_url, state


async def exchange_code_for_tokens(
    code: str,
    config: Dict[str, str],
    metadata: Dict[str, Any],
    redirect_uri: str,
) -> Optional[Dict[str, Any]]:
    """Exchange authorization code for tokens.

    Args:
        code: Authorization code from callback
        config: OIDC configuration
        metadata: Provider metadata
        redirect_uri: Redirect URI used in auth request (must match)

    Returns:
        Token response dictionary or None if exchange fails
    """
    token_endpoint = metadata.get("token_endpoint")
    if not token_endpoint:
        logger.error("Provider metadata missing token_endpoint")
        return None

    # SECURITY: Validate token endpoint URL against SSRF attacks
    try:
        validate_oidc_url(token_endpoint)
    except (SSRFProtectionError, ValueError) as e:
        logger.error(
            "SSRF protection blocked token endpoint: %s - %s", token_endpoint, str(e)
        )
        return None

    # Prepare token request
    client_secret = config.get("client_secret", "")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": config.get("client_id", ""),
        "client_secret": client_secret,
    }

    try:
        async with httpx.AsyncClient() as client:
            logger.info("Exchanging authorization code for tokens")
            # codeql[py/clear-text-logging-sensitive-data] - client_secret is masked via mask_secret()
            logger.debug("Using client_secret: %s", mask_secret(client_secret))

            # codeql[py/partial-ssrf] - URL validated by validate_oidc_url above
            response = await client.post(
                token_endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )

            # Log response details for debugging
            if response.status_code != 200:
                logger.error(
                    "Token exchange failed with status %s", response.status_code
                )
                logger.error("Response body: %s", response.text)

            response.raise_for_status()
            tokens = response.json()

            logger.info("Successfully exchanged authorization code for tokens")
            return tokens

    except httpx.HTTPStatusError as e:
        logger.error("HTTP error during token exchange: %s", e.response.status_code)
        logger.error("Response body: %s", e.response.text)
        # Don't log request data - it contains authorization code and redirect_uri
        logger.error("Token exchange failed - check OIDC provider configuration")
        return None  # Intentional fallback
    except httpx.TimeoutException:
        logger.error("Token exchange request timed out")
        return None  # Intentional fallback
    except httpx.ConnectError as e:
        logger.error("Cannot connect to OIDC provider for token exchange: %s", str(e))
        return None  # Intentional fallback


async def verify_id_token(
    id_token: str,
    config: Dict[str, str],
    metadata: Dict[str, Any],
    nonce: str,
) -> Optional[Dict[str, Any]]:
    """Verify and decode ID token from OIDC provider.

    Args:
        id_token: JWT ID token from provider
        config: OIDC configuration
        metadata: Provider metadata
        nonce: Expected nonce value

    Returns:
        Decoded ID token claims or None if validation fails
    """
    try:
        # Get JWKS URI
        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            logger.error("Provider metadata missing jwks_uri")
            return None

        # SECURITY: Validate JWKS URI against SSRF attacks
        try:
            validate_oidc_url(jwks_uri)
        except (SSRFProtectionError, ValueError) as e:
            logger.error("SSRF protection blocked JWKS URI: %s - %s", jwks_uri, str(e))
            return None

        # Fetch JWKS
        async with httpx.AsyncClient() as client:
            # codeql[py/partial-ssrf] - URL validated by validate_oidc_url above
            response = await client.get(jwks_uri, timeout=10.0)
            response.raise_for_status()
            jwks = response.json()

        # Create key set
        key_set = JsonWebKey.import_key_set(jwks)

        # Decode and verify ID token
        claims = jwt.decode(
            id_token,
            key_set,
            claims_options={
                "iss": {"essential": True, "value": config.get("issuer_url", "")},
                "aud": {"essential": True, "value": config.get("client_id", "")},
                "nonce": {"essential": True, "value": nonce},
            },
        )
        claims.validate()

        logger.info("Successfully verified ID token for subject: %s", claims.get("sub"))
        return dict(claims)

    except JoseError as e:
        logger.error("ID token verification failed: %s", str(e))
        return None  # Intentional fallback: invalid token
    except httpx.TimeoutException:
        logger.error("JWKS fetch timed out during ID token verification")
        return None  # Intentional fallback
    except httpx.ConnectError as e:
        logger.error("Cannot fetch JWKS for ID token verification: %s", str(e))
        return None  # Intentional fallback


async def get_userinfo(
    access_token: str,
    metadata: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Fetch user info from OIDC provider userinfo endpoint.

    Args:
        access_token: Access token from provider
        metadata: Provider metadata

    Returns:
        Userinfo claims or None if fetch fails
    """
    userinfo_endpoint = metadata.get("userinfo_endpoint")
    if not userinfo_endpoint:
        logger.warning(
            "Provider metadata missing userinfo_endpoint, skipping userinfo fetch"
        )
        return None

    # SECURITY: Validate userinfo endpoint URL against SSRF attacks
    try:
        validate_oidc_url(userinfo_endpoint)
    except (SSRFProtectionError, ValueError) as e:
        logger.error(
            "SSRF protection blocked userinfo endpoint: %s - %s",
            userinfo_endpoint,
            str(e),
        )
        return None

    try:
        async with httpx.AsyncClient() as client:
            # codeql[py/partial-ssrf] - URL validated by validate_oidc_url above
            response = await client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
            response.raise_for_status()
            userinfo = response.json()

            logger.info("Successfully fetched userinfo from provider")
            return userinfo

    except httpx.TimeoutException:
        logger.warning("Userinfo request timed out (non-critical)")
        return None  # Intentional fallback: userinfo is optional
    except httpx.ConnectError as e:
        logger.warning("Cannot connect to userinfo endpoint (non-critical): %s", str(e))
        return None  # Intentional fallback
    except httpx.HTTPStatusError as e:
        logger.warning("Userinfo endpoint returned error (non-critical): %s", str(e))
        return None  # Intentional fallback


async def create_or_update_user_from_oidc(
    db: AsyncSession,
    claims: Dict[str, Any],
    userinfo: Optional[Dict[str, Any]],
    config: Dict[str, str],
) -> Optional[User]:
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
        logger.info("Found existing OIDC user: %s", user.username)
        user.full_name = full_name or user.full_name
        user.last_login = datetime.now(timezone.utc)
        user.oidc_provider = provider_name
        await db.commit()
        await db.refresh(user)
        return user

    # Check for existing user with matching email (account linking)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user:
        # Link OIDC to existing local account
        logger.info("Linking OIDC account to existing user: %s", user.username)
        user.oidc_subject = sub
        user.oidc_provider = provider_name
        user.auth_method = "oidc"  # Primary auth method is now OIDC
        user.full_name = full_name or user.full_name
        user.last_login = datetime.now(timezone.utc)
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
                "Username match for OIDC-only user (no password): %s", username
            )
            raise ValueError(
                f"Username '{username}' exists as SSO-only account. Contact support to link this account."
            )
        elif user.oidc_subject and user.oidc_subject != sub:
            # Already linked to different OIDC account - conflict
            logger.error(
                "Username conflict: %s already linked to different OIDC account",
                username,
            )
            raise ValueError(
                f"Username '{username}' is already linked to a different account. Please contact support."
            )
        else:
            # Valid candidate for username-based linking - requires password verification
            logger.info("Username match requires password verification: %s", username)
            from app.exceptions import PendingLinkRequiredException

            raise PendingLinkRequiredException(
                username=username, claims=claims, userinfo=userinfo, config=config
            )

    # Check if auto-create is enabled
    auto_create = config.get("auto_create_users", "true").lower() == "true"
    if not auto_create:
        logger.warning("User not found for email %s and auto-create is disabled", email)
        return None

    # Create new user from OIDC claims
    logger.info("Creating new user from OIDC claims: %s", email)

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
        last_login=datetime.now(timezone.utc),
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("Created new OIDC user: %s (admin=%s)", user.username, is_admin)
    return user


async def create_pending_link_token(
    db: AsyncSession,
    username: str,
    claims: Dict[str, Any],
    userinfo: Optional[Dict[str, Any]],
    config: Dict[str, str],
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
    from app.models.oidc_pending_link import OIDCPendingLink

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
    import json

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
        created_at=datetime.now(timezone.utc),
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
) -> tuple[Optional[User], Optional[str]]:
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
    from app.models.oidc_pending_link import OIDCPendingLink
    from app.services.auth import verify_password
    import json

    # Clean up expired tokens first
    await _cleanup_expired_pending_links(db)

    # Find pending link by token
    result = await db.execute(
        select(OIDCPendingLink).where(OIDCPendingLink.token == token)
    )
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
        logger.warning(
            "Max password attempts exceeded for username: %s", pending_link.username
        )
        await db.delete(pending_link)
        await db.commit()
        return (None, "Too many failed attempts. Please log in again.")

    # Find user by username
    result = await db.execute(
        select(User).where(User.username == pending_link.username)
    )
    user = result.scalar_one_or_none()

    if not user:
        logger.error("User not found for pending link: %s", pending_link.username)
        await db.delete(pending_link)
        await db.commit()
        return (None, "Link expired, please log in again")

    # Security check: user must have a password (not OIDC-only)
    if user.hashed_password is None:
        logger.error(
            "Username match for OIDC-only user (no password): %s", pending_link.username
        )
        await db.delete(pending_link)
        await db.commit()
        return (None, "Link expired, please log in again")

    # Deserialize claims
    claims = json.loads(pending_link.oidc_claims)
    userinfo = (
        json.loads(pending_link.userinfo_claims)
        if pending_link.userinfo_claims
        else None
    )
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
    logger.info(
        "Password verified, linking OIDC account to user: %s", pending_link.username
    )

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
    user.last_login = datetime.now(timezone.utc)

    # Delete pending link token (one-time use)
    await db.delete(pending_link)
    await db.commit()
    await db.refresh(user)

    logger.info("Successfully linked OIDC account to existing user: %s", user.username)
    return (user, None)


async def test_oidc_connection(config: Dict[str, str]) -> Dict[str, Any]:
    """Test OIDC provider connection and configuration.

    Args:
        config: OIDC configuration to test

    Returns:
        Dictionary with test results
    """
    result = {
        "success": False,
        "provider_reachable": False,
        "metadata_valid": False,
        "endpoints_found": False,
        "errors": [],
    }

    issuer_url = config.get("issuer_url", "").strip()
    if not issuer_url:
        result["errors"].append("Issuer URL is required")
        return result

    try:
        # Fetch metadata
        metadata = await get_provider_metadata(issuer_url)
        if not metadata:
            result["errors"].append("Failed to fetch provider metadata")
            return result

        result["provider_reachable"] = True
        result["metadata_valid"] = True

        # Check required endpoints
        required_endpoints = ["authorization_endpoint", "token_endpoint", "jwks_uri"]
        missing_endpoints = [ep for ep in required_endpoints if not metadata.get(ep)]

        if missing_endpoints:
            result["errors"].append(
                f"Missing endpoints: {', '.join(missing_endpoints)}"
            )
            return result

        result["endpoints_found"] = True
        result["success"] = True

        # Add metadata info
        result["metadata"] = {
            "issuer": metadata.get("issuer"),
            "authorization_endpoint": metadata.get("authorization_endpoint"),
            "token_endpoint": metadata.get("token_endpoint"),
            "userinfo_endpoint": metadata.get("userinfo_endpoint"),
            "supported_scopes": metadata.get("scopes_supported", []),
        }

    except httpx.TimeoutException:
        result["errors"].append("Connection test timed out")
    except httpx.ConnectError as e:
        result["errors"].append(f"Cannot connect to OIDC provider: {e}")
    except httpx.HTTPStatusError as e:
        result["errors"].append(f"OIDC provider returned error: {e}")

    return result
