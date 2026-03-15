"""OIDC configuration and provider metadata discovery.

Functions for loading OIDC settings from the database and fetching
provider metadata via the standard OpenID Connect discovery endpoint.
"""

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import SSRFProtectionError
from app.models.settings import Setting
from app.utils.url_validation import validate_oidc_url

logger = logging.getLogger(__name__)


async def get_oidc_config(db: AsyncSession) -> dict[str, str]:
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


async def get_provider_metadata(issuer_url: str) -> dict[str, Any] | None:
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
