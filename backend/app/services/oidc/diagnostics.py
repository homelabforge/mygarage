"""OIDC connection diagnostics.

Functions for testing OIDC provider connectivity and configuration
to help administrators troubleshoot setup issues.
"""

import logging
from typing import Any

import httpx

from .config import get_provider_metadata

logger = logging.getLogger(__name__)


async def test_oidc_connection(config: dict[str, str]) -> dict[str, Any]:
    """Test OIDC provider connection and configuration.

    Args:
        config: OIDC configuration to test

    Returns:
        Dictionary with test results
    """
    result: dict[str, Any] = {
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
            result["errors"].append(f"Missing endpoints: {', '.join(missing_endpoints)}")
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
