"""Security middleware for MyGarage application."""

import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.database import get_db
from app.models.csrf_token import CSRFToken


def is_test_mode() -> bool:
    """Check if running in test mode (disables CSRF validation)."""
    return os.getenv("MYGARAGE_TEST_MODE", "").lower() == "true"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        # Content Security Policy - Strengthened to remove 'unsafe-inline' from scripts
        # Note: style-src still allows 'unsafe-inline' for Tailwind CSS and dynamic styles
        # If inline styles need to be removed in future, use CSS-in-JS with nonces
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "  # Removed 'unsafe-inline' - Vite bundles all scripts
            "style-src 'self' 'unsafe-inline'; "  # Keep for Tailwind/dynamic styles
            "img-src 'self' data: blob: https://tile.openstreetmap.org https://a.tile.openstreetmap.org https://b.tile.openstreetmap.org https://c.tile.openstreetmap.org https://cdnjs.cloudflare.com; "  # Allow OSM tiles and Leaflet icons
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-src 'self' blob:; "
            "frame-ancestors 'self'; "
            "object-src 'none'; "  # Block plugins like Flash
            "base-uri 'self'; "  # Prevent base tag injection
            "form-action 'self'; "  # Restrict form submissions
        )

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking (allow same-origin for PDF viewer iframes)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"

        # XSS Protection (legacy, but doesn't hurt)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions Policy (formerly Feature-Policy)
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )

        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add unique request ID to each request for tracing."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Generate unique request ID
        request_id = str(uuid.uuid4())

        # Add to request state so it can be used in logging
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """CSRF protection middleware using synchronizer token pattern.

    Validates CSRF tokens on state-changing operations (POST/PUT/PATCH/DELETE).
    Tokens are generated on login and validated against the database.

    Exempt routes:
    - /api/auth/login (token generation happens here)
    - /api/auth/oidc/* (OIDC flow has its own state protection)
    - /api/health (public health check)
    - /api/backup/* (protected by JWT auth, idempotent operations)
    - /api/settings/batch (user preferences, protected by JWT auth)
    - GET/HEAD/OPTIONS (safe methods)
    """

    # Routes that don't require CSRF protection
    EXEMPT_PATHS = [
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/logout",  # Protected by JWT auth, idempotent operation
        "/api/auth/oidc/",
        "/api/health",
        "/api/settings/public",  # Public settings endpoint
        "/api/backup/",  # Backup routes (protected by JWT auth, no user input)
        "/api/settings/batch",  # User preferences (protected by JWT auth, auto-save)
    ]

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip CSRF validation in test mode (test DB session not accessible from middleware)
        if is_test_mode():
            return await call_next(request)

        # Skip CSRF check for safe methods
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        # Skip CSRF check for exempt paths
        if any(request.url.path.startswith(path) for path in self.EXEMPT_PATHS):
            return await call_next(request)

        # Check if auth is disabled - skip CSRF validation
        try:
            from app.services.auth import get_auth_mode

            db_generator = get_db()
            db = await anext(db_generator)
            try:
                auth_mode = await get_auth_mode(db)
                if auth_mode == "none":
                    # Auth disabled, skip CSRF validation
                    return await call_next(request)
            finally:
                await db_generator.aclose()
        except Exception:
            # If we can't check auth mode, proceed with CSRF validation
            pass

        # Get CSRF token from header
        csrf_token = request.headers.get("X-CSRF-Token")

        if not csrf_token:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF token missing. Include X-CSRF-Token header with your request."
                },
            )

        # Validate CSRF token against database
        try:
            # Get database session
            db_generator = get_db()
            db = await anext(db_generator)
            try:
                # Find valid token
                result = await db.execute(
                    select(CSRFToken).where(
                        CSRFToken.token == csrf_token,
                        CSRFToken.expires_at > datetime.now(UTC),
                    )
                )
                token_record = result.scalar_one_or_none()

                if not token_record:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "Invalid or expired CSRF token. Please login again."
                        },
                    )

                # Token is valid, process request
                # Store user_id in request state for use in route handlers
                request.state.csrf_validated_user_id = token_record.user_id
            finally:
                await db_generator.aclose()

                # Note: Cleanup of expired tokens is handled during login
                # No need to do it on every request (performance optimization)

        except Exception as e:
            return JSONResponse(
                status_code=500, content={"detail": f"CSRF validation error: {str(e)}"}
            )

        return await call_next(request)
