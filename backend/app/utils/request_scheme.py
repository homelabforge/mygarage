"""Request scheme resolution utilities for cookie security and redirect URLs.

Centralizes scheme detection from proxy headers and request context.
Used by auth routes (cookie Secure flag) and OIDC routes (redirect URLs).
"""

import logging
import os

from fastapi import Request

logger = logging.getLogger(__name__)


def get_request_scheme(request: Request) -> str:
    """Resolve the effective scheme (http/https) from request context.

    Checks X-Forwarded-Proto first (set by reverse proxies like Traefik/nginx),
    then falls back to request.url.scheme from the ASGI server.

    Trust model:
        X-Forwarded-Proto is trusted by default. Spoofing this header on a
        direct HTTP connection can only cause self-denial-of-service (cookie
        gets Secure=True, browser drops it). It cannot weaken security because
        setting the Secure flag "too high" never exposes cookies — it only
        prevents them from being stored.

    Defensive parsing:
        - Lowercased and stripped
        - Comma-separated values: first value wins (leftmost = client-facing proxy)
        - Only "https" is accepted as truthy; everything else resolves to "http"

    Args:
        request: The incoming FastAPI/Starlette request.

    Returns:
        "https" if HTTPS is detected, "http" otherwise.
    """
    forwarded_proto = request.headers.get("x-forwarded-proto")

    if forwarded_proto:
        # Take first value if comma-separated (multi-proxy chains)
        scheme = forwarded_proto.split(",")[0].strip().lower()
        if scheme == "https":
            return "https"
        return "http"

    # Fall back to ASGI server's reported scheme
    return str(request.url.scheme).lower()


def get_cookie_secure(request: Request) -> bool:
    """Determine the cookie Secure flag for the current request.

    Priority:
        1. Explicit JWT_COOKIE_SECURE env var — operator override, no auto-detection.
        2. Auto-detect via get_request_scheme() — True if HTTPS detected.

    The env var is read directly (not via settings.jwt_cookie_secure) to cleanly
    distinguish "operator explicitly chose" from "auto-detect from request".
    settings.jwt_cookie_secure conflates both into a single bool with no way
    to tell which path produced the value.

    Args:
        request: The incoming FastAPI/Starlette request.

    Returns:
        True if the cookie should have the Secure flag, False otherwise.
    """
    env_value = os.getenv("JWT_COOKIE_SECURE")

    if env_value is not None:
        normalized = env_value.strip().lower()
        if normalized in ("true", "1", "yes"):
            logger.debug("Cookie secure flag: True (explicit env override)")
            return True
        if normalized in ("false", "0", "no"):
            logger.debug("Cookie secure flag: False (explicit env override)")
            return False
        # Unrecognized value (including "auto") falls through to detection

    scheme = get_request_scheme(request)
    secure = scheme == "https"
    logger.debug("Cookie secure flag: %s (auto-detected scheme=%s)", secure, scheme)
    return secure
