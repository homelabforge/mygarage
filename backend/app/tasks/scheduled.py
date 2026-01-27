"""Scheduled tasks for MyGarage application."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import AsyncSessionLocal
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def reset_daily_limits():
    """Reset daily API limits for providers (TomTom, Yelp).

    Runs daily at midnight UTC.
    """
    async with AsyncSessionLocal() as db:
        for provider in ["tomtom", "yelp"]:
            try:
                await SettingsService.set(db, f"{provider}_api_usage", "0")
                logger.info("Reset daily usage for provider: %s", provider)
            except Exception as e:
                logger.error("Failed to reset usage for %s: %s", provider, str(e))


async def reset_monthly_limits():
    """Reset monthly API limits for providers (Google Places, Foursquare).

    Runs on the 1st of each month at midnight UTC.
    """
    async with AsyncSessionLocal() as db:
        for provider in ["google_places", "foursquare"]:
            try:
                await SettingsService.set(db, f"{provider}_api_usage", "0")
                logger.info("Reset monthly usage for provider: %s", provider)
            except Exception as e:
                logger.error("Failed to reset usage for %s: %s", provider, str(e))


def start_scheduler():
    """Start the scheduled tasks.

    Schedules:
        - Daily reset at midnight UTC for daily-limited providers
        - Monthly reset on 1st at midnight UTC for monthly-limited providers
    """
    # Daily reset at midnight UTC
    scheduler.add_job(reset_daily_limits, "cron", hour=0, minute=0)

    # Monthly reset on 1st at midnight UTC
    scheduler.add_job(reset_monthly_limits, "cron", day=1, hour=0, minute=0)

    scheduler.start()
    logger.info("Scheduled tasks started")


def stop_scheduler():
    """Stop the scheduled tasks."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduled tasks stopped")
