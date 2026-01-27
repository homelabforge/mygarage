"""POI Provider usage tracking middleware."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


async def increment_provider_usage(
    db: AsyncSession,
    provider_name: str,
) -> None:
    """Increment API usage counter for provider.

    Args:
        db: Database session
        provider_name: Provider to increment usage for

    Side effects:
        - Updates {provider_name}_api_usage setting
        - Logs warning at 90% of limit
        - Auto-disables provider when limit exceeded
    """
    # Get current usage
    usage_setting = await SettingsService.get(db, f"{provider_name}_api_usage")
    current_usage = int(usage_setting.value) if usage_setting else 0
    new_usage = current_usage + 1

    # Update usage
    await SettingsService.set(db, f"{provider_name}_api_usage", str(new_usage))

    # Provider-specific limits
    limits = {
        "tomtom": 2500,  # Daily limit
        "yelp": 5000,  # Daily limit
        # google_places and foursquare have no free tier daily limits
    }

    limit = limits.get(provider_name)
    if not limit:
        return  # No limit to check

    # Warn at 90%
    if new_usage >= limit * 0.9 and new_usage < limit:
        logger.warning(
            "Provider %s usage at %d/%d (90%% threshold)",
            provider_name,
            new_usage,
            limit,
        )

    # Auto-disable at limit
    if new_usage >= limit:
        logger.error(
            "Provider %s exceeded limit (%d/%d), disabling provider",
            provider_name,
            new_usage,
            limit,
        )
        await SettingsService.set(db, f"{provider_name}_enabled", "false")


async def get_provider_usage(
    db: AsyncSession,
    provider_name: str,
) -> dict[str, int | None | float]:
    """Get current usage stats for provider.

    Args:
        db: Database session
        provider_name: Provider to get stats for

    Returns:
        Dictionary with usage, limit, and percentage fields
    """
    usage_setting = await SettingsService.get(db, f"{provider_name}_api_usage")
    usage = int(usage_setting.value) if usage_setting else 0

    limits = {
        "tomtom": 2500,
        "yelp": 5000,
    }

    limit = limits.get(provider_name)

    return {
        "usage": usage,
        "limit": limit,
        "percentage": (usage / limit * 100) if limit else None,
    }
