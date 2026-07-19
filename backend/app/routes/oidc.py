"""OIDC authentication routes.

Provides endpoints for OIDC/OpenID Connect authentication flow:
- /api/auth/oidc/config - Get OIDC configuration (public)
- /api/auth/oidc/login - Initiate OIDC flow (redirects to provider)
- /api/auth/oidc/callback - Handle OIDC callback
- /api/auth/oidc/test - Test OIDC connection (admin only)
"""

import logging
import secrets
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from joserfc.errors import JoseError
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.csrf_token import CSRFToken
from app.models.user import User
from app.services import oidc as oidc_service
from app.services.auth import create_access_token, get_current_admin_user, get_current_user
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log
from app.utils.request_scheme import get_cookie_secure, get_request_scheme

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/oidc", tags=["oidc"])


def _external_base(request: Request) -> str:
    """Scheme+host+prefix for URLs the browser/IdP will hit (#107)."""
    scheme = get_request_scheme(request)
    host = request.headers.get("x-forwarded-host", request.headers.get("host")) or str(
        request.base_url.hostname
    )
    return f"{scheme}://{host}{settings.root_path}"


def _frontend_base(request: Request) -> str:
    """Scheme+host+prefix for frontend redirects (#107)."""
    return _external_base(request)


# Initialize rate limiter for auth endpoints
limiter = Limiter(key_func=get_remote_address)


class OIDCConfigResponse(BaseModel):
    """OIDC configuration response (safe for frontend)."""

    enabled: bool
    provider_name: str
    issuer_url: str
    client_id: str
    scopes: str


class OIDCAdminConfig(BaseModel):
    """Full admin OIDC configuration (canonical homelab OIDC settings contract).

    `client_secret` follows the §5.4(3) wire convention:
      - GET returns the literal "********" placeholder when stored, "" otherwise.
      - PUT with empty string OR the placeholder preserves the stored value.
    """

    enabled: bool = False
    provider_name: str = ""
    issuer_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: str = "openid profile email"
    auto_create_users: bool = True
    admin_group: str = ""
    username_claim: str = "preferred_username"
    email_claim: str = "email"
    full_name_claim: str = "name"


class OIDCTestRequest(BaseModel):
    """OIDC connection test request."""

    issuer_url: str
    client_id: str
    client_secret: str


class OIDCTestResult(BaseModel):
    """Canonical OIDC test result per plan §5.4(4)."""

    ok: bool
    error: str | None = None
    detail: str | None = None
    issuer: str | None = None
    algorithms_supported: list[str] | None = None


class LinkOIDCAccountRequest(BaseModel):
    """Request to link OIDC account with password verification."""

    token: str
    password: str


@router.get("/config", response_model=OIDCConfigResponse)
async def get_oidc_config(db: AsyncSession = Depends(get_db)):
    """Get OIDC configuration (safe for frontend, no secrets).

    Returns:
        OIDC configuration without sensitive data
    """
    config = await oidc_service.get_oidc_config(db)

    return OIDCConfigResponse(
        enabled=config.get("enabled", "false").lower() == "true",
        provider_name=config.get("provider_name", ""),
        issuer_url=config.get("issuer_url", ""),
        client_id=config.get("client_id", ""),
        scopes=config.get("scopes", "openid profile email"),
    )


@router.get("/config/admin", response_model=OIDCAdminConfig)
async def get_oidc_admin_config(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """Get the full admin OIDC configuration (admin-only).

    Returns the canonical shape per plan §5.4; client_secret is masked with the
    literal "********" placeholder when stored.

    ``current_user`` is None only when auth_mode == "none" (auth disabled), which
    this endpoint allows — same as every other admin surface. Gating it instead
    deadlocks bootstrap: Settings → System PUTs this endpoint before the batch
    that carries ``auth_mode``, so enabling auth would require auth. Nothing
    leaks either way — the secret is masked here, and GET /api/settings is
    already open in that mode.
    """
    config = await oidc_service.get_oidc_config(db)
    return OIDCAdminConfig(
        enabled=config.get("enabled", "false").lower() == "true",
        provider_name=config.get("provider_name", ""),
        issuer_url=config.get("issuer_url", ""),
        client_id=config.get("client_id", ""),
        client_secret=oidc_service.display_mask_secret(config.get("client_secret", "")),
        scopes=config.get("scopes") or "openid profile email",
        auto_create_users=(config.get("auto_create_users", "true").lower() == "true"),
        admin_group=config.get("admin_group", ""),
        username_claim=config.get("username_claim") or "preferred_username",
        email_claim=config.get("email_claim") or "email",
        full_name_claim=config.get("full_name_claim") or "name",
    )


@router.put("/config/admin")
async def put_oidc_admin_config(
    payload: OIDCAdminConfig,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """Update the admin OIDC configuration (admin-only).

    Enforces the §5.4 wire contract:
      - empty `client_secret` (or the masked placeholder) preserves the stored value
      - issuer_url has trailing slash + whitespace stripped before persisting

    ``current_user`` is None only when auth_mode == "none" (auth disabled), which
    this endpoint allows — see the GET above for why gating it deadlocks bootstrap.
    """
    # §5.4(2): preserve stored secret when caller sends empty/placeholder.
    client_secret = payload.client_secret
    if not client_secret or oidc_service.is_masked_secret(client_secret):
        config = await oidc_service.get_oidc_config(db)
        client_secret = config.get("client_secret", "")

    # §5.4(1): normalize issuer URL.
    issuer_url = payload.issuer_url.strip().rstrip("/")

    await oidc_service.write_oidc_config(
        db,
        {
            "enabled": "true" if payload.enabled else "false",
            "provider_name": payload.provider_name,
            "issuer_url": issuer_url,
            "client_id": payload.client_id,
            "client_secret": client_secret,
            "scopes": payload.scopes,
            "auto_create_users": "true" if payload.auto_create_users else "false",
            "admin_group": payload.admin_group,
            "username_claim": payload.username_claim,
            "email_claim": payload.email_claim,
            "full_name_claim": payload.full_name_claim,
        },
    )

    logger.info(
        "OIDC admin configuration updated by user %s",
        sanitize_for_log(current_user.username) if current_user else "<auth disabled>",
    )
    return {"message": "OIDC configuration updated successfully"}


@router.get("/login")
async def oidc_login(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Initiate OIDC authentication flow.

    Redirects user to OIDC provider for authentication.

    Query Parameters:
        redirect_to: Optional URL to redirect to after successful login

    Returns:
        Redirect to OIDC provider authorization endpoint
    """
    # Get OIDC configuration
    config = await oidc_service.get_oidc_config(db)

    # Check if OIDC is enabled
    if config.get("enabled", "false").lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OIDC authentication is not enabled",
        )

    # Validate configuration
    issuer_url = config.get("issuer_url", "").strip()
    client_id = config.get("client_id", "").strip()

    if not issuer_url or not client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC is not properly configured (missing issuer_url or client_id)",
        )

    # Fetch provider metadata
    metadata = await oidc_service.get_provider_metadata(issuer_url)
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch OIDC provider metadata",
        )

    # Determine base URL for redirect URI (scheme/host/prefix, #107)
    base_url = _external_base(request)

    # Create authorization URL
    try:
        auth_url, state = await oidc_service.create_authorization_url(
            db, config, metadata, base_url
        )
    except httpx.TimeoutException:
        logger.error("OIDC provider timeout creating authorization URL")
        raise HTTPException(status_code=504, detail="OIDC provider request timed out")
    except httpx.ConnectError:
        logger.error("Cannot connect to OIDC provider")
        raise HTTPException(status_code=503, detail="Cannot connect to OIDC provider")
    except JoseError as e:
        logger.error("OIDC JWT error creating authorization URL: %s", e)
        raise HTTPException(status_code=401, detail="OIDC authentication error")
    except (ValueError, KeyError) as e:
        logger.error("OIDC configuration error: %s", e)
        raise HTTPException(status_code=500, detail="OIDC configuration error")

    logger.info("Redirecting to OIDC provider for authentication (state: %s)", state)
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
async def oidc_callback(
    code: str,
    state: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Handle OIDC callback from provider.

    Query Parameters:
        code: Authorization code from provider
        state: State parameter for CSRF protection

    Returns:
        Redirect to frontend with JWT token in URL fragment
    """
    logger.info("Received OIDC callback (state: %s)", state)

    # Validate and consume state from database
    state_data = await oidc_service.validate_and_consume_state(db, state)
    if not state_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter",
        )

    # Get OIDC configuration
    config = await oidc_service.get_oidc_config(db)
    issuer_url = config.get("issuer_url", "").strip()

    # Fetch provider metadata
    metadata = await oidc_service.get_provider_metadata(issuer_url)
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch OIDC provider metadata",
        )

    # Exchange code for tokens (with PKCE verifier from stored state)
    redirect_uri = state_data["redirect_uri"]
    code_verifier = state_data.get("code_verifier")
    tokens = await oidc_service.exchange_code_for_tokens(
        code, config, metadata, redirect_uri, code_verifier=code_verifier
    )
    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to exchange authorization code for tokens",
        )

    # Verify ID token
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Provider did not return ID token",
        )

    nonce = state_data["nonce"]
    claims = await oidc_service.verify_id_token(id_token, config, metadata, nonce)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to verify ID token",
        )

    # Fetch userinfo (optional, provides additional claims)
    access_token = tokens.get("access_token")
    userinfo = None
    if access_token:
        userinfo = await oidc_service.get_userinfo(access_token, metadata)

    # Create or update user from OIDC claims
    try:
        user = await oidc_service.create_or_update_user_from_oidc(db, claims, userinfo, config)
    except Exception as e:
        # Import PendingLinkRequiredError here to avoid circular import
        from app.exceptions import PendingLinkRequiredError

        if isinstance(e, PendingLinkRequiredError):
            # Username match requires password verification
            logger.info("Pending link required for username: %s", sanitize_for_log(e.username))

            # Create pending link token
            pending_token = await oidc_service.create_pending_link_token(
                db,
                e.username,
                e.claims,
                e.userinfo,
                e.config,
            )

            # Redirect to link account page with token (#107: prefix-aware)
            frontend_url = _frontend_base(request)
            redirect_url = f"{frontend_url}/auth/link-account?token={pending_token}"

            logger.info("Redirecting to link account page: %s", redirect_url)
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
        else:
            # Re-raise other exceptions
            raise

    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create or update user from OIDC claims",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    # Clean up expired CSRF tokens for this user
    await db.execute(
        delete(CSRFToken).where(
            CSRFToken.user_id == user.id,
            CSRFToken.expires_at <= utc_now(),
        )
    )

    # Generate CSRF token (Security Enhancement v2.10.0)
    csrf_token_value = secrets.token_urlsafe(48)  # 64-character token
    csrf_token = CSRFToken(
        token=csrf_token_value,
        user_id=user.id,
        expires_at=CSRFToken.get_expiry_time(),
    )
    db.add(csrf_token)
    await db.commit()

    # Create MyGarage JWT token for the user with explicit expiration
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    jwt_token = create_access_token(
        data={"sub": str(user.id), "username": user.username},
        expires_delta=access_token_expires,
    )

    logger.info("OIDC login successful for user: %s", sanitize_for_log(user.username))

    # Set httpOnly cookie and redirect with CSRF token (Security Enhancement v2.10.0)
    # Frontend needs CSRF token for state-changing requests (#107: prefix-aware)
    frontend_url = _frontend_base(request)
    redirect_url = f"{frontend_url}/auth/oidc/success?csrf_token={csrf_token_value}"

    redirect_response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    redirect_response.set_cookie(
        key=settings.jwt_cookie_name,
        value=jwt_token,
        httponly=settings.jwt_cookie_httponly,
        secure=get_cookie_secure(request),
        samesite=settings.jwt_cookie_samesite,
        max_age=settings.jwt_cookie_max_age,
    )

    return redirect_response


@router.post("/test", response_model=OIDCTestResult)
async def test_oidc_connection(
    test_request: OIDCTestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test OIDC provider connection (admin only).

    Returns the canonical `{ok, error, detail, issuer, algorithms_supported}` envelope
    per plan §5.4(4).
    """
    if not current_user or not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )

    # §5.4(2): empty/placeholder secret falls back to the stored value so admins can test before saving.
    client_secret = test_request.client_secret
    if not client_secret or oidc_service.is_masked_secret(client_secret):
        stored = await oidc_service.get_oidc_config(db)
        client_secret = stored.get("client_secret", "")

    issuer_url = test_request.issuer_url.strip().rstrip("/")

    config = {
        "issuer_url": issuer_url,
        "client_id": test_request.client_id,
        "client_secret": client_secret,
    }

    raw = await oidc_service.test_oidc_connection(config)

    if raw.get("success"):
        metadata = raw.get("metadata") or {}
        return OIDCTestResult(
            ok=True,
            issuer=metadata.get("issuer") or issuer_url,
            algorithms_supported=metadata.get("id_token_signing_alg_values_supported") or [],
        )

    if not raw.get("provider_reachable"):
        error_code = "unreachable"
    elif not raw.get("metadata_valid"):
        error_code = "invalid_metadata"
    elif not raw.get("endpoints_found"):
        error_code = "missing_endpoints"
    else:
        error_code = "discovery_failed"

    errors = raw.get("errors") or []
    return OIDCTestResult(
        ok=False,
        error=error_code,
        detail="; ".join(errors) if errors else None,
    )


@router.post("/link-account")
@limiter.limit(settings.rate_limit_auth)
async def link_oidc_account(
    request: Request,
    response: Response,
    link_request: LinkOIDCAccountRequest,
    db: AsyncSession = Depends(get_db),
):
    """Link OIDC account to existing local account with password verification.

    This endpoint is called after OIDC login when a username match is found
    but no OIDC link exists. The user must verify their password to link
    the accounts.

    Security:
    - Rate limited (5/minute via settings.rate_limit_auth)
    - Max 3 password attempts per token (configured in settings)
    - Token expires after 5 minutes (configured in settings)
    - Audited (success and failure)
    - CSRF protected (middleware)

    Args:
        link_request: Token and password for verification
        request: FastAPI request for audit logging
        response: FastAPI response for setting cookies
        db: Database session

    Returns:
        JSON with CSRF token and redirect URL

    Raises:
        HTTPException: 401 if token invalid/expired or password wrong
        HTTPException: 403 if user account is disabled
    """
    # Validate and consume pending link token
    user, error_message = await oidc_service.validate_and_consume_pending_link(
        db,
        link_request.token,
        link_request.password,
    )

    if user is None:
        # Failed - create audit log
        audit_log = AuditLog(
            user_id=None,
            action="oidc_link_failed",
            details=error_message,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", ""),
            timestamp=utc_now(),
        )
        db.add(audit_log)
        await db.commit()

        logger.warning("OIDC link failed: %s", error_message)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_message,
        )

    # Check if user is active
    if not user.is_active:
        logger.warning("OIDC link attempt for inactive user: %s", sanitize_for_log(user.username))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    # Success - create audit log
    audit_log = AuditLog(
        user_id=user.id,
        action="oidc_account_linked",
        details=f"Linked OIDC account to username: {user.username}, provider: {user.oidc_provider}, oidc_subject: {user.oidc_subject}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", ""),
        timestamp=utc_now(),
    )
    db.add(audit_log)

    # Clean up expired CSRF tokens for this user
    await db.execute(
        delete(CSRFToken).where(
            CSRFToken.user_id == user.id,
            CSRFToken.expires_at <= utc_now(),
        )
    )

    # Generate CSRF token
    csrf_token_value = secrets.token_urlsafe(48)  # 64-character token
    csrf_token = CSRFToken(
        token=csrf_token_value,
        user_id=user.id,
        expires_at=CSRFToken.get_expiry_time(),
    )
    db.add(csrf_token)
    await db.commit()

    # Create JWT token for the user
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    jwt_token = create_access_token(
        data={"sub": str(user.id), "username": user.username},
        expires_delta=access_token_expires,
    )

    logger.info("OIDC account linked successfully for user: %s", sanitize_for_log(user.username))

    # Set httpOnly cookie
    response.set_cookie(
        key=settings.jwt_cookie_name,
        value=jwt_token,
        httponly=settings.jwt_cookie_httponly,
        secure=get_cookie_secure(request),
        samesite=settings.jwt_cookie_samesite,
        max_age=settings.jwt_cookie_max_age,
    )

    # Return CSRF token and redirect URL
    return {
        "csrf_token": csrf_token_value,
        "redirect_url": "/",
    }
