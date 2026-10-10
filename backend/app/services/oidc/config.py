"""OIDC configuration and provider metadata discovery.

Functions for loading OIDC settings from the database and fetching
provider metadata via the standard OpenID Connect discovery endpoint.
"""

import datetime as dt
import logging
import unicodedata
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import SSRFProtectionError
from app.models.settings import Setting
from app.utils.url_validation import validate_oidc_url

logger = logging.getLogger(__name__)

#: What an unset or blank setting means. Blank used to reach the IdP as
#: `scope=`, or look up the claim '' and find no email for anyone.
OIDC_DEFAULTS: dict[str, str] = {
    "scopes": "openid profile email",
    "username_claim": "preferred_username",
    "email_claim": "email",
    "full_name_claim": "name",
}

#: The settings row that pins SSO's callback URL.
OIDC_REDIRECT_URI_KEY = "oidc_redirect_uri"


def checked_redirect_uri(raw: str) -> str:
    """The SSO callback pin to store: stripped, and blank or an absolute http(s) URL.

    Absolute means an http or https scheme and a host. Whitespace or a control
    character anywhere inside is refused too: urlsplit drops tabs and newlines
    before it parses, so it saw a fine URL while the raw value got stored. The
    path isn't checked, since a proxy may rewrite it (create_authorization_url
    already warns on a missing root_path prefix). Every writer of the row calls
    this: the SSO settings PUT, the settings routes and the settings restore.

    Raises:
        ValueError: If it's neither blank nor an absolute http(s) URL
    """
    value = raw.strip()
    if not value:
        return ""
    rule = "must be blank or an absolute http(s) URL"
    if any(ch.isspace() or unicodedata.category(ch) == "Cc" for ch in value):
        raise ValueError(rule)
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise ValueError(rule) from exc
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(rule)
    return value


def provider_json(
    response: httpx.Response, what: str, *, level: int = logging.ERROR
) -> dict[str, Any] | None:
    """The provider's response body as a JSON object, or None when it isn't one.

    Logs why at ``level``, so a caller can just return the None.

    Args:
        response: The provider's response, already status-checked
        what: What the response is, for the log line
        level: The log level for a body that can't be used

    Returns:
        The decoded object, or None when the body isn't JSON or isn't an object
    """
    try:
        doc = response.json()
    except ValueError:
        logger.log(level, "%s response is not valid JSON", what)
        return None
    if not isinstance(doc, dict):
        logger.log(level, "%s response is not a JSON object", what)
        return None
    return cast(dict[str, Any], doc)


def effective_oidc_value(config: dict[str, str], key: str) -> str:
    """The setting login actually uses: the stripped value, or the default when blank.

    `full_name_claim` falls back to `name_claim` before "name". The admin page
    writes the first, but `name_claim` has been seeded since the first release
    and an instance may only have that one.
    """
    value = config.get(key, "").strip()
    if not value and key == "full_name_claim":
        value = config.get("name_claim", "").strip()
    return value or OIDC_DEFAULTS[key]


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


async def write_oidc_config(db: AsyncSession, payload: dict[str, str]) -> None:
    """Atomically persist OIDC settings.

    Keys are stored with the `oidc_` prefix in the generic settings table.
    Caller is responsible for enforcing the §5.4 contract (mask handling,
    issuer rstrip, etc.) — this is the raw KV writer.
    """
    now = dt.datetime.now()
    for clean_key, value in payload.items():
        full_key = f"oidc_{clean_key}"
        result = await db.execute(select(Setting).where(Setting.key == full_key))
        setting = result.scalar_one_or_none()
        if setting is not None:
            setting.value = value
            setting.updated_at = now
        else:
            db.add(Setting(key=full_key, value=value, updated_at=now))
    await db.commit()


async def get_provider_metadata(issuer_url: str) -> dict[str, Any] | None:
    """Fetch OIDC provider metadata from well-known endpoint.

    Args:
        issuer_url: OIDC issuer URL

    Returns:
        Provider metadata dictionary, or None if the fetch fails or the document
        isn't a JSON object

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
        validated_discovery = validate_oidc_url(discovery_url)
    except (SSRFProtectionError, ValueError) as e:
        # Don't log the full URL - it could contain secrets in query params
        logger.error("SSRF protection blocked OIDC discovery URL: %s", str(e))
        raise SSRFProtectionError(f"Invalid OIDC discovery URL: {e}")

    try:
        async with httpx.AsyncClient() as client:
            # The issuer is admin config by design, and validate_oidc_url is the SSRF guard.
            # Fetch the URL it parsed, not the raw string, so the two can't drift.
            response = await client.get(validated_discovery.geturl(), timeout=10.0)
            response.raise_for_status()
            metadata = provider_json(response, "OIDC metadata")
            if metadata is not None:
                logger.info("Successfully fetched OIDC metadata")
            return metadata  # Intentional fallback: None when it isn't a JSON object

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
    except httpx.HTTPError as e:
        logger.error("OIDC metadata request failed: %s", type(e).__name__)
        return None  # Intentional fallback
