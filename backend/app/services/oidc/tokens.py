"""OIDC token exchange and verification.

Functions for exchanging authorization codes for tokens, verifying ID tokens
using JWKS, and fetching user information from the provider's userinfo endpoint.
"""

import logging
from typing import Any

import httpx
from authlib.jose import JoseError, JsonWebKey, jwt

from app.exceptions import SSRFProtectionError
from app.utils.url_validation import validate_oidc_url

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


async def exchange_code_for_tokens(
    code: str,
    config: dict[str, str],
    metadata: dict[str, Any],
    redirect_uri: str,
) -> dict[str, Any] | None:
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
        logger.error("SSRF protection blocked token endpoint: %s - %s", token_endpoint, str(e))
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
                logger.error("Token exchange failed with status %s", response.status_code)
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
    config: dict[str, str],
    metadata: dict[str, Any],
    nonce: str,
) -> dict[str, Any] | None:
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
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    """Fetch user info from OIDC provider userinfo endpoint.

    Args:
        access_token: Access token from provider
        metadata: Provider metadata

    Returns:
        Userinfo claims or None if fetch fails
    """
    userinfo_endpoint = metadata.get("userinfo_endpoint")
    if not userinfo_endpoint:
        logger.warning("Provider metadata missing userinfo_endpoint, skipping userinfo fetch")
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
