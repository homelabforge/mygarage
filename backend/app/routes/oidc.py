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
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from joserfc.errors import JoseError
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.oidc import SSO_ACCOUNT_DISABLED, SSOError
from app.database import get_db
from app.exceptions import OIDCLoginRefusedError, PendingLinkRequiredError, SSRFProtectionError
from app.models.audit_log import USER_AGENT_MAX_LENGTH, AuditLog
from app.models.csrf_token import CSRFToken
from app.models.user import User
from app.services import oidc as oidc_service
from app.services.auth import create_access_token, get_current_admin_user, get_current_user
from app.services.oidc.config import effective_oidc_value
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log
from app.utils.request_scheme import get_cookie_secure, get_external_base_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/oidc", tags=["oidc"])


def _external_base(request: Request) -> str:
    """Scheme+host+prefix for URLs the browser/IdP will hit (#107).

    Thin alias over the shared helper, which the LiveLink/Torque ingest URLs
    also use — the resolution rule lives in one place.
    """
    return get_external_base_url(request)


def _frontend_base(request: Request) -> str:
    """Scheme+host+prefix for frontend redirects (#107)."""
    return _external_base(request)


def _to_login(request: Request, code: SSOError) -> RedirectResponse:
    """Send the browser back to the login page with why SSO didn't sign it in.

    The login start and the callback are full-page navigations, so this is what
    the person sees instead of a page of JSON. Only the code goes in the URL,
    and no cookie is set.
    """
    return RedirectResponse(
        f"{_frontend_base(request)}/login?sso_error={code.value}",
        status_code=status.HTTP_302_FOUND,
    )


# The IdP's error text is free-form and goes to the log, so it's cut short.
_IDP_ERROR_LOG_LENGTH = 200

# One shot per process, module-level so tests can reset it. No await between
# the check and the set, so one event loop can't log it twice.
_warned_blank_redirect_uri = False


def _warn_if_redirect_uri_blank(config: dict[str, str]) -> None:
    """Warn once when SSO's callback URL is coming from the request (A-15).

    With ``oidc_redirect_uri`` blank, the login route builds the base URL from
    X-Forwarded-Host or Host (``_external_base``) and ``create_authorization_url``
    only appends the callback path, so a forged header becomes the redirect_uri
    the IdP is asked to send the code to. Only an IdP that skips exact matching
    accepts that, so it's a nudge to pin the setting, not a refusal.
    """
    global _warned_blank_redirect_uri
    if _warned_blank_redirect_uri or config.get("redirect_uri", "").strip():
        return
    _warned_blank_redirect_uri = True
    logger.warning(
        "oidc_redirect_uri is blank, so SSO builds its callback URL from each request's "
        "X-Forwarded-Host or Host header. Set it in Settings > System > Configure OIDC > "
        "Callback URL to your public callback URL and register exactly that URL at your "
        "identity provider, never a wildcard (see SECURITY.md). Logged once."
    )


# Initialize rate limiter for auth endpoints
limiter = Limiter(key_func=get_remote_address)


def _request_origin(request: Request) -> tuple[str | None, str]:
    """The request's client IP and user agent, as the audit rows record them.

    The user agent is cut to the audit column's length, since PostgreSQL refuses
    a longer one and that would fail the commit it rides in.
    """
    ip_address = request.client.host if request.client else None
    return ip_address, request.headers.get("user-agent", "")[:USER_AGENT_MAX_LENGTH]


async def _audit_login_refused(
    db: AsyncSession,
    request: Request,
    reason: str,
    username: str | None,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    """Record a refused SSO login and commit it.

    The caller refuses the login right after, with a redirect or a 403, and
    ``get_db`` rolls back on the 403's exception, so the row only survives
    because it's committed here. Anything the refused step left uncommitted is
    rolled back first, so this commit carries the audit row and nothing else.

    Args:
        db: Database session
        request: The request, for the IP and user agent
        reason: Why the login was refused (the refusal's message)
        username: The matched account's username, or None if none matched
        details: The refusal's extra keys for the row; ``reason`` always wins
    """
    await db.rollback()
    ip_address, user_agent = _request_origin(request)
    db.add(
        AuditLog(
            user_id=None,
            username=username,
            action="oidc_login_refused",
            details={**(details or {}), "reason": reason},
            success=0,
            ip_address=ip_address,
            user_agent=user_agent,
            timestamp=utc_now(),
        )
    )
    await db.commit()


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

    `redirect_uri` pins the SSO callback URL; "" builds it from each request.
    PUT leaves it alone when the field is left out.
    """

    enabled: bool = False
    provider_name: str = ""
    issuer_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
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
        scopes=effective_oidc_value(config, "scopes"),
    )


def _checked_redirect_uri(raw: str) -> str:
    """The callback URL to store: stripped, and blank or an absolute http(s) URL.

    The path isn't checked, since a proxy may rewrite it (users.py already warns
    on a missing root_path prefix).

    Raises:
        HTTPException 422: If it's neither blank nor an absolute http(s) URL
    """
    value = raw.strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        absolute = parts.scheme in ("http", "https") and bool(parts.netloc)
    except ValueError:
        absolute = False
    if not absolute:
        raise HTTPException(status_code=422, detail="redirect_uri must be an absolute http(s) URL")
    return value


@router.get("/config/admin", response_model=OIDCAdminConfig)
async def get_oidc_admin_config(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """Get the full admin OIDC configuration (admin-only).

    Returns the canonical shape per plan §5.4; client_secret is masked with the
    literal "********" placeholder when stored.
    """
    # current_user is None only when auth_mode == "none" (auth disabled), which
    # this endpoint allows — same as every other admin surface. Gating it instead
    # deadlocks bootstrap: Settings -> System PUTs this endpoint before the batch
    # that carries auth_mode, so enabling auth would require auth. Nothing leaks
    # either way — the secret is masked here, and GET /api/settings is already
    # open in that mode.
    config = await oidc_service.get_oidc_config(db)
    return OIDCAdminConfig(
        enabled=config.get("enabled", "false").lower() == "true",
        provider_name=config.get("provider_name", ""),
        issuer_url=config.get("issuer_url", ""),
        client_id=config.get("client_id", ""),
        client_secret=oidc_service.display_mask_secret(config.get("client_secret", "")),
        redirect_uri=config.get("redirect_uri", ""),
        scopes=effective_oidc_value(config, "scopes"),
        auto_create_users=(config.get("auto_create_users", "true").lower() == "true"),
        admin_group=config.get("admin_group", ""),
        username_claim=effective_oidc_value(config, "username_claim"),
        email_claim=effective_oidc_value(config, "email_claim"),
        full_name_claim=effective_oidc_value(config, "full_name_claim"),
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
      - `redirect_uri` left out preserves the stored value; sent, it's stripped and
        must be an absolute http(s) URL or blank, else a 422 and nothing is written
    """
    # current_user is None only when auth_mode == "none" (auth disabled), which
    # this endpoint allows — see the GET above for why gating it deadlocks bootstrap.

    # Left out, the stored pin stays, so an older client can't wipe it. Checked
    # here, not on the model: the GET builds that model from what's stored.
    redirect_update: dict[str, str] = {}
    if "redirect_uri" in payload.model_fields_set:
        redirect_update["redirect_uri"] = _checked_redirect_uri(payload.redirect_uri)

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
            "scopes": payload.scopes.strip(),
            "auto_create_users": "true" if payload.auto_create_users else "false",
            "admin_group": payload.admin_group,
            "username_claim": payload.username_claim.strip(),
            "email_claim": payload.email_claim.strip(),
            "full_name_claim": payload.full_name_claim.strip(),
            **redirect_update,
        },
    )

    logger.info(
        "OIDC admin configuration updated by user %s",
        sanitize_for_log(current_user.username) if current_user else "<auth disabled>",
    )
    return {"message": "OIDC configuration updated successfully"}


@router.get("/login")
@limiter.limit(settings.rate_limit_auth)
async def oidc_login(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Initiate OIDC authentication flow.

    Redirects user to OIDC provider for authentication. The browser gets here by
    full-page navigation, so a failure redirects to the login page with
    ``?sso_error=failed`` instead of answering with JSON.

    Query Parameters:
        redirect_to: Optional URL to redirect to after successful login

    Returns:
        Redirect to OIDC provider authorization endpoint, or to the login page
    """
    # Get OIDC configuration
    config = await oidc_service.get_oidc_config(db)

    # Check if OIDC is enabled
    if config.get("enabled", "false").lower() != "true":
        logger.warning("OIDC login started while OIDC authentication is not enabled")
        return _to_login(request, SSOError.FAILED)

    # Validate configuration
    issuer_url = config.get("issuer_url", "").strip()
    client_id = config.get("client_id", "").strip()

    if not issuer_url or not client_id:
        logger.warning("OIDC login started but OIDC is missing its issuer_url or client_id")
        return _to_login(request, SSOError.FAILED)

    # Fetch provider metadata. Either failure is already logged by the service.
    try:
        metadata = await oidc_service.get_provider_metadata(issuer_url)
    except SSRFProtectionError:
        return _to_login(request, SSOError.FAILED)
    if not metadata:
        return _to_login(request, SSOError.FAILED)

    # Determine base URL for redirect URI (scheme/host/prefix, #107)
    base_url = _external_base(request)

    # Create authorization URL
    try:
        auth_url, state = await oidc_service.create_authorization_url(
            db, config, metadata, base_url
        )
    except httpx.TimeoutException:
        logger.error("OIDC provider timeout creating authorization URL")
        return _to_login(request, SSOError.FAILED)
    except httpx.ConnectError:
        logger.error("Cannot connect to OIDC provider")
        return _to_login(request, SSOError.FAILED)
    except JoseError as e:
        logger.error("OIDC JWT error creating authorization URL: %s", e)
        return _to_login(request, SSOError.FAILED)
    except (ValueError, KeyError) as e:
        logger.error("OIDC configuration error: %s", e)
        return _to_login(request, SSOError.FAILED)

    _warn_if_redirect_uri_blank(config)
    logger.info("Redirecting to OIDC provider for authentication (state: %s)", state)
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
@limiter.limit(settings.rate_limit_auth)
async def oidc_callback(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Handle OIDC callback from provider.

    Anything that doesn't sign the person in redirects to the login page with
    ``?sso_error=<code>`` (an ``SSOError`` value) and sets no cookie. A refusal
    is audited first.

    Query Parameters:
        code: Authorization code from provider
        state: State parameter for CSRF protection
        error: The provider's error, when it sends one instead of a code

    Returns:
        Redirect to the frontend: the OIDC success page with the auth cookie set,
        the link account page, or the login page
    """
    logger.info("Received OIDC callback (state: %s)", sanitize_for_log(state))

    # The IdP sends ?error= and no code when the person cancels or it refuses.
    if error or not code or not state:
        if state:
            # Spend it, so a sign-in that ends here doesn't leave it live for 10 minutes.
            await oidc_service.validate_and_consume_state(db, state)
        if error:
            description = request.query_params.get("error_description", "")
            logger.warning(
                "OIDC provider returned an error: %s (%s)",
                sanitize_for_log(error[:_IDP_ERROR_LOG_LENGTH]),
                sanitize_for_log(description[:_IDP_ERROR_LOG_LENGTH]),
            )
        else:
            logger.warning("OIDC callback is missing its code or state")
        cancelled = error == "access_denied"
        return _to_login(request, SSOError.CANCELLED if cancelled else SSOError.FAILED)

    # Validate and consume state from database. state.py logs a bad one.
    state_data = await oidc_service.validate_and_consume_state(db, state)
    if not state_data:
        return _to_login(request, SSOError.EXPIRED)

    # Get OIDC configuration
    config = await oidc_service.get_oidc_config(db)
    issuer_url = config.get("issuer_url", "").strip()

    # Fetch provider metadata. Each provider step below logs its own failure.
    try:
        metadata = await oidc_service.get_provider_metadata(issuer_url)
    except SSRFProtectionError:
        return _to_login(request, SSOError.FAILED)
    if not metadata:
        return _to_login(request, SSOError.FAILED)

    # Exchange code for tokens (with PKCE verifier from stored state)
    redirect_uri = state_data["redirect_uri"]
    code_verifier = state_data.get("code_verifier")
    tokens = await oidc_service.exchange_code_for_tokens(
        code, config, metadata, redirect_uri, code_verifier=code_verifier
    )
    if not tokens:
        return _to_login(request, SSOError.FAILED)

    # Verify ID token
    id_token = tokens.get("id_token")
    if not id_token:
        logger.error("OIDC provider did not return an ID token")
        return _to_login(request, SSOError.FAILED)

    nonce = state_data["nonce"]
    claims = await oidc_service.verify_id_token(id_token, config, metadata, nonce)
    if not claims:
        return _to_login(request, SSOError.FAILED)

    # Fetch userinfo (optional, provides additional claims)
    access_token = tokens.get("access_token")
    userinfo = None
    if access_token:
        userinfo = await oidc_service.get_userinfo(access_token, metadata)

    # Create or update user from OIDC claims. Anything other than these two
    # exceptions propagates untouched. The origin goes along for the audit row
    # an armed relink writes.
    ip_address, user_agent = _request_origin(request)
    try:
        user = await oidc_service.create_or_update_user_from_oidc(
            db, claims, userinfo, config, ip_address=ip_address, user_agent=user_agent
        )
    except PendingLinkRequiredError as e:
        # Email or username matched a password account, so confirm it with that password first
        logger.info("Pending link required for username: %s", sanitize_for_log(e.username))

        # Create pending link token
        pending_token = await oidc_service.create_pending_link_token(
            db,
            e.username,
            e.claims,
            e.userinfo,
            e.config,
        )

        # Redirect to link account page with token (#107: prefix-aware). The token
        # rides in the fragment, which a browser never sends to a server, so proxy
        # and access logs never see it.
        frontend_url = _frontend_base(request)
        redirect_url = f"{frontend_url}/auth/link-account#token={pending_token}"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    except OIDCLoginRefusedError as e:
        await _audit_login_refused(db, request, e.message, e.username, details=e.details)
        return _to_login(request, e.code)

    # None means the claims had no subject or no email, which the service logged.
    if not user:
        return _to_login(request, SSOError.FAILED)

    # Backstop: the service refuses a disabled account itself, so this only
    # fires when an admin disables it while the login is in flight.
    if not user.is_active:
        await _audit_login_refused(db, request, SSO_ACCOUNT_DISABLED, user.username)
        return _to_login(request, SSOError.ACCOUNT_DISABLED)

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
    # Frontend needs CSRF token for state-changing requests (#107: prefix-aware).
    # Fragment, not query, for the same reason as the link token above.
    frontend_url = _frontend_base(request)
    redirect_url = f"{frontend_url}/auth/oidc/success#csrf_token={csrf_token_value}"

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


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Answer a request that went over its rate limit.

    The SSO start and the callback are full-page navigations, so a limited one
    goes back to the login page with ``?sso_error=rate_limited``, like every
    other SSO failure. Every other route gets slowapi's JSON 429, as before.

    Args:
        request: The limited request
        exc: slowapi's exception for the limit it hit

    Returns:
        A redirect to the login page, or slowapi's 429
    """
    # Match on the route's endpoint, not the path. Behind a subpath the path
    # carries the prefix, but the endpoint is the same function either way.
    endpoint = request.scope.get("endpoint")
    if endpoint is oidc_login or endpoint is oidc_callback:
        return _to_login(request, SSOError.RATE_LIMITED)
    return _rate_limit_exceeded_handler(request, exc)


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

    This endpoint is called after an OIDC login whose email or username matches
    an existing account that has a password and no OIDC link. The user must
    enter that account's password to link the accounts.

    Security:
    - Rate limited (5/minute via settings.rate_limit_auth)
    - Max 3 password attempts per token (configured in settings)
    - Token expires after 5 minutes (configured in settings)
    - A disabled account is refused before the password is checked
    - Audited (success, failure and refusal); the link's own row commits with it
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
    # Validate and consume pending link token. A link writes its own audit row.
    ip_address, user_agent = _request_origin(request)
    try:
        user, error_message = await oidc_service.validate_and_consume_pending_link(
            db,
            link_request.token,
            link_request.password,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except OIDCLoginRefusedError as e:
        # A disabled target, refused before its password was checked
        await _audit_login_refused(db, request, e.message, e.username, details=e.details)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)

    if user is None:
        # Failed - create audit log
        audit_log = AuditLog(
            user_id=None,
            action="oidc_link_failed",
            details={"reason": error_message},
            ip_address=ip_address,
            user_agent=user_agent,
            timestamp=utc_now(),
        )
        db.add(audit_log)
        await db.commit()

        logger.warning("OIDC link failed: %s", error_message)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_message,
        )

    # Backstop: the link step refuses a disabled account up front, so this only
    # fires when an admin disables it while the link is being committed. The link
    # and its audit row are already in, so this just refuses the login.
    if not user.is_active:
        logger.warning("OIDC link attempt for inactive user: %s", sanitize_for_log(user.username))
        await _audit_login_refused(db, request, SSO_ACCOUNT_DISABLED, user.username)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=SSO_ACCOUNT_DISABLED)

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
