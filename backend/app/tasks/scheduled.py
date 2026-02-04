"""Scheduled tasks for MyGarage application."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import AsyncSessionLocal
from app.services.settings_service import SettingsService
from app.tasks.livelink_tasks import (
    check_device_offline_status,
    check_firmware_updates,
    check_session_timeouts,
    generate_daily_summaries,
    prune_old_telemetry,
)

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
        - LiveLink: Session timeout check every minute
        - LiveLink: Device offline check every 5 minutes
        - LiveLink: Daily summary generation at 1 AM UTC
        - LiveLink: Firmware check at 3 AM UTC
        - LiveLink: Telemetry pruning at 4 AM UTC
    """
    # Daily reset at midnight UTC
    scheduler.add_job(reset_daily_limits, "cron", hour=0, minute=0)

    # Monthly reset on 1st at midnight UTC
    scheduler.add_job(reset_monthly_limits, "cron", day=1, hour=0, minute=0)

    # LiveLink tasks
    # Check for stale sessions every minute
    scheduler.add_job(check_session_timeouts, "interval", minutes=1)

    # Check for offline devices every 5 minutes
    scheduler.add_job(check_device_offline_status, "interval", minutes=5)

    # Generate daily summaries at 1 AM UTC
    scheduler.add_job(generate_daily_summaries, "cron", hour=1, minute=0)

    # Check for firmware updates at 3 AM UTC
    scheduler.add_job(check_firmware_updates, "cron", hour=3, minute=0)

    # Prune old telemetry at 4 AM UTC
    scheduler.add_job(prune_old_telemetry, "cron", hour=4, minute=0)

    scheduler.start()
    logger.info("Scheduled tasks started")


def stop_scheduler():
    """Stop the scheduled tasks."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduled tasks stopped")
