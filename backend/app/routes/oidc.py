"""OIDC authentication routes.

Provides endpoints for OIDC/OpenID Connect authentication flow:
- /api/auth/oidc/config - Get OIDC configuration (public)
- /api/auth/oidc/login - Initiate OIDC flow (redirects to provider)
- /api/auth/oidc/callback - Handle OIDC callback
- /api/auth/oidc/test - Test OIDC connection (admin only)
"""

import logging
import secrets
from datetime import UTC, datetime, timedelta

import httpx
from authlib.jose import JoseError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
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
from app.services.auth import create_access_token, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/oidc", tags=["oidc"])

# Initialize rate limiter for auth endpoints
limiter = Limiter(key_func=get_remote_address)


class OIDCConfigResponse(BaseModel):
    """OIDC configuration response (safe for frontend)."""

    enabled: bool
    provider_name: str
    issuer_url: str
    client_id: str
    scopes: str


class OIDCTestRequest(BaseModel):
    """OIDC connection test request."""

    issuer_url: str
    client_id: str
    client_secret: str


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

    # Determine base URL for redirect URI
    base_url = str(request.base_url).rstrip("/")
    # Handle reverse proxy headers
    if request.headers.get("x-forwarded-proto"):
        scheme = request.headers.get("x-forwarded-proto")
        host = request.headers.get("x-forwarded-host", request.headers.get("host"))
        base_url = f"{scheme}://{host}"

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

    # Exchange code for tokens
    redirect_uri = state_data["redirect_uri"]
    tokens = await oidc_service.exchange_code_for_tokens(
        code, config, metadata, redirect_uri
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
        user = await oidc_service.create_or_update_user_from_oidc(
            db, claims, userinfo, config
        )
    except Exception as e:
        # Import PendingLinkRequiredException here to avoid circular import
        from app.exceptions import PendingLinkRequiredException

        if isinstance(e, PendingLinkRequiredException):
            # Username match requires password verification
            logger.info("Pending link required for username: %s", e.username)

            # Create pending link token
            pending_token = await oidc_service.create_pending_link_token(
                db,
                e.username,
                e.claims,
                e.userinfo,
                e.config,
            )

            # Redirect to link account page with token
            # Respect X-Forwarded-Proto header from reverse proxy (Traefik)
            scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get("host", str(request.base_url.hostname))
            frontend_url = f"{scheme}://{host}"
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
            CSRFToken.expires_at <= datetime.now(UTC),
        )
    )

    # Generate CSRF token (Security Enhancement v2.10.0)
    csrf_token_value = secrets.token_urlsafe(48)  # 64-character token
    csrf_token = CSRFToken(
        token=csrf_token_value,
        user_id=user.id,
        expires_at=CSRFToken.get_expiry_time(hours=24),  # Same as JWT expiry
    )
    db.add(csrf_token)
    await db.commit()

    # Create MyGarage JWT token for the user with explicit expiration
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    jwt_token = create_access_token(
        data={"sub": str(user.id), "username": user.username},
        expires_delta=access_token_expires,
    )

    logger.info("OIDC login successful for user: %s", user.username)

    # Set httpOnly cookie and redirect with CSRF token (Security Enhancement v2.10.0)
    # Frontend needs CSRF token for state-changing requests
    # Respect X-Forwarded-Proto header from reverse proxy (Traefik)
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", str(request.base_url.hostname))
    frontend_url = f"{scheme}://{host}"
    redirect_url = f"{frontend_url}/auth/oidc/success?csrf_token={csrf_token_value}"

    redirect_response = RedirectResponse(
        url=redirect_url, status_code=status.HTTP_302_FOUND
    )
    redirect_response.set_cookie(
        key=settings.jwt_cookie_name,
        value=jwt_token,
        httponly=settings.jwt_cookie_httponly,
        secure=settings.jwt_cookie_secure,
        samesite=settings.jwt_cookie_samesite,
        max_age=settings.jwt_cookie_max_age,
    )

    return redirect_response


@router.post("/test")
async def test_oidc_connection(
    test_request: OIDCTestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test OIDC provider connection (admin only).

    Args:
        test_request: OIDC configuration to test

    Returns:
        Test results
    """
    # Only admins can test OIDC connection
    if not current_user or not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )

    # Convert test request to config dict
    config = {
        "issuer_url": test_request.issuer_url,
        "client_id": test_request.client_id,
        "client_secret": test_request.client_secret,
    }

    # Test connection
    result = await oidc_service.test_oidc_connection(config)

    return result


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
            timestamp=datetime.now(UTC),
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
        logger.warning("OIDC link attempt for inactive user: %s", user.username)
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
        timestamp=datetime.now(UTC),
    )
    db.add(audit_log)

    # Clean up expired CSRF tokens for this user
    await db.execute(
        delete(CSRFToken).where(
            CSRFToken.user_id == user.id,
            CSRFToken.expires_at <= datetime.now(UTC),
        )
    )

    # Generate CSRF token
    csrf_token_value = secrets.token_urlsafe(48)  # 64-character token
    csrf_token = CSRFToken(
        token=csrf_token_value,
        user_id=user.id,
        expires_at=CSRFToken.get_expiry_time(hours=24),  # Same as JWT expiry
    )
    db.add(csrf_token)
    await db.commit()

    # Create JWT token for the user
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    jwt_token = create_access_token(
        data={"sub": str(user.id), "username": user.username},
        expires_delta=access_token_expires,
    )

    logger.info("OIDC account linked successfully for user: %s", user.username)

    # Set httpOnly cookie
    response.set_cookie(
        key=settings.jwt_cookie_name,
        value=jwt_token,
        httponly=settings.jwt_cookie_httponly,
        secure=settings.jwt_cookie_secure,
        samesite=settings.jwt_cookie_samesite,
        max_age=settings.jwt_cookie_max_age,
    )

    # Return CSRF token and redirect URL
    return {
        "csrf_token": csrf_token_value,
        "redirect_url": "/",
    }
