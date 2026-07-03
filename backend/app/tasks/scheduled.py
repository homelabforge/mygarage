# DEPLOYMENT CONTRACT: This scheduler is process-local (APScheduler).
# It MUST run in exactly one process. The SCHEDULER_ENABLED env var
# gates startup (fail-closed: scheduler won't start unless explicitly
# enabled). If you need horizontal scaling, only one replica should
# set SCHEDULER_ENABLED=true, or move to a dedicated worker process.

"""Scheduled tasks for MyGarage application."""

import asyncio
import logging
import os
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.fuel import has_def_capacity, is_diesel_vehicle
from app.database import AsyncSessionLocal
from app.models import (
    DEFRecord,
    InsurancePolicy,
    OdometerRecord,
    Recall,
    Vehicle,
    WarrantyRecord,
)
from app.services.notifications.dispatcher import NotificationDispatcher
from app.services.settings_service import SettingsService
from app.tasks.livelink_tasks import (
    check_device_offline_status,
    check_firmware_updates,
    check_session_timeouts,
    finalize_pending_offlines,
    generate_daily_summaries,
    prune_old_telemetry,
)
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Notification dedup cooldown (24 hours)
NOTIFICATION_COOLDOWN = timedelta(hours=24)


async def _get_setting(db: AsyncSession, key: str, default: str = "") -> str:
    """Get a setting value with a default fallback."""
    setting = await SettingsService.get(db, key)
    return setting.value if setting and setting.value else default


async def reset_daily_limits() -> None:
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


async def reset_monthly_limits() -> None:
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


async def check_expiring_documents() -> None:
    """Check for expiring insurance and warranties and send notifications.

    Runs daily at 9 AM UTC. Reads notify_insurance_days and notify_warranty_days
    settings. Uses 24-hour cooldown to prevent duplicate notifications.
    """
    async with AsyncSessionLocal() as db:
        try:
            dispatcher = NotificationDispatcher(db)
            if not await dispatcher._has_any_service_enabled():
                return

            notify_insurance_days = int(await _get_setting(db, "notify_insurance_days", "30"))
            notify_warranty_days = int(await _get_setting(db, "notify_warranty_days", "30"))

            today = date.today()
            now = utc_now()

            # Get all vehicles for name lookup
            vehicles_result = await db.execute(select(Vehicle))
            vehicles_dict = {v.vin: v for v in vehicles_result.scalars().all()}

            # Check insurance policies
            insurance_cutoff = today + timedelta(days=notify_insurance_days)
            insurance_result = await db.execute(
                select(InsurancePolicy).where(
                    InsurancePolicy.end_date >= today,
                    InsurancePolicy.end_date <= insurance_cutoff,
                )
            )
            for policy in insurance_result.scalars().all():
                # Dedup check
                if (
                    policy.last_notified_at
                    and (now - policy.last_notified_at) < NOTIFICATION_COOLDOWN
                ):
                    continue

                vehicle = vehicles_dict.get(policy.vin)
                vehicle_name = (
                    vehicle.nickname or f"{vehicle.year} {vehicle.make} {vehicle.model}"
                    if vehicle
                    else policy.vin
                )
                days_until = (policy.end_date - today).days

                await dispatcher.notify_insurance_expiring(
                    vehicle_name=vehicle_name,
                    policy_name=f"{policy.provider} - {policy.policy_type}",
                    days_until_expiry=days_until,
                )

                policy.last_notified_at = now

            # Check warranty records
            warranty_cutoff = today + timedelta(days=notify_warranty_days)
            warranty_result = await db.execute(
                select(WarrantyRecord).where(
                    WarrantyRecord.end_date.isnot(None),
                    WarrantyRecord.end_date >= today,
                    WarrantyRecord.end_date <= warranty_cutoff,
                )
            )
            for warranty in warranty_result.scalars().all():
                # Dedup check
                if (
                    warranty.last_notified_at
                    and (now - warranty.last_notified_at) < NOTIFICATION_COOLDOWN
                ):
                    continue

                if not warranty.end_date:
                    continue

                vehicle = vehicles_dict.get(warranty.vin)
                vehicle_name = (
                    vehicle.nickname or f"{vehicle.year} {vehicle.make} {vehicle.model}"
                    if vehicle
                    else warranty.vin
                )
                days_until = (warranty.end_date - today).days

                await dispatcher.notify_warranty_expiring(
                    vehicle_name=vehicle_name,
                    warranty_name=f"{warranty.warranty_type} Warranty",
                    days_until_expiry=days_until,
                )

                warranty.last_notified_at = now

            await db.commit()
            logger.info("Expiring documents notification check complete")

        except Exception as e:
            logger.error("Expiring documents check failed: %s", str(e))


async def check_odometer_milestones() -> None:
    """Check for odometer milestones and send notifications.

    Runs daily at 10 AM UTC. Checks each vehicle's latest odometer_km against
    milestone boundaries (every 10,000 km). Uses last_milestone_notified_km
    on the vehicle to prevent duplicate notifications.
    """
    MILESTONE_INTERVAL_KM = 10_000  # noqa: N806 — constant value, intentionally uppercased

    async with AsyncSessionLocal() as db:
        try:
            dispatcher = NotificationDispatcher(db)
            if not await dispatcher._has_any_service_enabled():
                return

            # Check if milestone notifications are enabled
            milestones_enabled = await _get_setting(db, "notify_milestones", "false")
            if milestones_enabled.lower() != "true":
                return

            vehicles_result = await db.execute(select(Vehicle).where(Vehicle.archived_at.is_(None)))
            vehicles = vehicles_result.scalars().all()

            for vehicle in vehicles:
                try:
                    # Get latest odometer_km
                    odo_result = await db.execute(
                        select(OdometerRecord.odometer_km)
                        .where(OdometerRecord.vin == vehicle.vin)
                        .order_by(OdometerRecord.date.desc())
                        .limit(1)
                    )
                    current_odometer_km = odo_result.scalar_one_or_none()
                    if not current_odometer_km:
                        continue

                    # Calculate the highest milestone crossed (integer-floor on km)
                    current_milestone = (
                        int(current_odometer_km) // MILESTONE_INTERVAL_KM
                    ) * MILESTONE_INTERVAL_KM
                    if current_milestone == 0:
                        continue

                    last_notified = int(vehicle.last_milestone_notified_km or 0)

                    if current_milestone > last_notified:
                        vehicle_name = (
                            vehicle.nickname or f"{vehicle.year} {vehicle.make} {vehicle.model}"
                        )
                        await dispatcher.notify_odometer_milestone(
                            vehicle_name=vehicle_name,
                            milestone=current_milestone,
                        )
                        vehicle.last_milestone_notified_km = current_milestone
                        logger.info(
                            "Milestone notification: %s reached %s km",
                            vehicle_name,
                            f"{current_milestone:,}",
                        )

                except Exception as e:
                    logger.error(
                        "Error checking milestones for %s: %s",
                        vehicle.vin,
                        str(e),
                    )

            await db.commit()
            logger.info("Odometer milestone check complete")

        except Exception as e:
            logger.error("Odometer milestone check failed: %s", str(e))


async def _get_def_low_threshold_percent(db: AsyncSession) -> int:
    """Read notify_def_low_threshold_percent, clamped to 1-99.

    Falls back to 25 when the setting is missing, empty, or non-numeric
    ("banana") — a garbage threshold must not brick the whole check.
    """
    raw = await _get_setting(db, "notify_def_low_threshold_percent", "25")
    try:
        value = int(raw)
    except TypeError, ValueError:
        return 25
    return max(1, min(99, value))


async def check_def_levels() -> None:
    """Check DEF (Diesel Exhaust Fluid) levels and send low-level notifications.

    Runs daily at 11 AM UTC. For each non-archived, diesel-capable vehicle
    with a configured DEF tank capacity, reads the latest fill_level (a 0-1
    fraction) and compares it against notify_def_low_threshold_percent.

    Uses crossing-based dedup via Vehicle.def_low_notified_at rather than a
    time cooldown: DEF depletes over weeks, so a 24h cooldown would either
    nag daily or (if long enough) swallow a genuine post-refill depletion.
    Crossing at/under the threshold notifies once and stamps; recovering
    above the threshold clears the stamp so the next dip re-notifies. The
    stamp only lands when at least one notification backend actually
    dispatched — an all-failed attempt (e.g. a transient Discord outage)
    leaves the vehicle unstamped so the next run retries instead of going
    silent until the next refill-and-dip cycle.
    """
    async with AsyncSessionLocal() as db:
        try:
            dispatcher = NotificationDispatcher(db)
            if not await dispatcher._has_any_service_enabled():
                return

            notify_def_low = await _get_setting(db, "notify_def_low", "false")
            if notify_def_low.lower() != "true":
                return

            threshold_percent = await _get_def_low_threshold_percent(db)

            vehicles_result = await db.execute(select(Vehicle).where(Vehicle.archived_at.is_(None)))
            vehicles = vehicles_result.scalars().all()

            for vehicle in vehicles:
                try:
                    if not is_diesel_vehicle(vehicle.fuel_type, vehicle.fuel_type_secondary):
                        continue
                    if not has_def_capacity(vehicle.def_tank_capacity_liters):
                        continue

                    def_result = await db.execute(
                        select(DEFRecord.fill_level, DEFRecord.date)
                        .where(DEFRecord.vin == vehicle.vin, DEFRecord.fill_level.is_not(None))
                        .order_by(DEFRecord.date.desc(), DEFRecord.id.desc())
                        .limit(1)
                    )
                    row = def_result.first()
                    if row is None:
                        continue

                    fill_level, record_date = row
                    percent = fill_level * 100

                    if percent <= threshold_percent:
                        if vehicle.def_low_notified_at is None:
                            vehicle_name = (
                                vehicle.nickname or f"{vehicle.year} {vehicle.make} {vehicle.model}"
                            )
                            remaining_liters = fill_level * vehicle.def_tank_capacity_liters
                            dispatch_results = await dispatcher.notify_def_low(
                                vehicle_name=vehicle_name,
                                vin=vehicle.vin,
                                percent=percent,
                                remaining_liters=remaining_liters,
                                as_of_date=record_date,
                            )
                            # Stamp only on at least one successful dispatch
                            # (mirrors TelemetryService.check_thresholds's
                            # cooldown guard) — an all-failed dict (e.g. a
                            # transient Discord outage) must not start the
                            # crossing-based dedup clock, or the alert stays
                            # silent until the tank refills and dips again,
                            # which can be weeks away.
                            if any(dispatch_results.values()):
                                vehicle.def_low_notified_at = utc_now()
                                logger.info(
                                    "DEF low notification: %s at %.1f%%",
                                    vehicle_name,
                                    percent,
                                )
                            else:
                                logger.warning(
                                    "DEF low notification dispatch failed for %s at "
                                    "%.1f%%; will retry next run",
                                    vehicle_name,
                                    percent,
                                )
                    elif vehicle.def_low_notified_at is not None:
                        # Recovery reset — the next dip below threshold re-notifies.
                        vehicle.def_low_notified_at = None

                except Exception as e:
                    logger.error(
                        "Error checking DEF level for %s: %s",
                        vehicle.vin,
                        str(e),
                    )

            await db.commit()
            logger.info("DEF level check complete")

        except Exception as e:
            logger.error("DEF level check failed: %s", str(e))


async def check_recalls_all_vehicles() -> None:
    """Auto-check NHTSA recalls for all vehicles.

    Runs weekly (Sunday 2 AM UTC). Checks nhtsa_auto_check setting,
    queries NHTSA for each vehicle, inserts new recalls, and sends
    notifications for any newly discovered recalls.
    """
    from app.services.nhtsa import NHTSAService

    async with AsyncSessionLocal() as db:
        try:
            # Check if auto-check is enabled
            auto_check = await _get_setting(db, "nhtsa_auto_check", "true")
            if auto_check.lower() != "true":
                logger.info("NHTSA auto-check disabled, skipping")
                return

            nhtsa = NHTSAService()
            dispatcher = NotificationDispatcher(db)

            # Get all active vehicles
            vehicles_result = await db.execute(select(Vehicle).where(Vehicle.archived_at.is_(None)))
            vehicles = vehicles_result.scalars().all()

            total_new = 0

            for vehicle in vehicles:
                try:
                    vehicle_name = (
                        vehicle.nickname or f"{vehicle.year} {vehicle.make} {vehicle.model}"
                    )

                    # Fetch recalls from NHTSA
                    recalls_data = await nhtsa.get_vehicle_recalls(vehicle.vin, db)

                    # Get existing campaign numbers for this vehicle
                    existing_result = await db.execute(
                        select(Recall.nhtsa_campaign_number).where(
                            Recall.vin == vehicle.vin,
                            Recall.nhtsa_campaign_number.isnot(None),
                        )
                    )
                    existing_campaigns = {r[0] for r in existing_result.fetchall()}

                    # Insert new recalls
                    new_count = 0
                    for recall_data in recalls_data:
                        campaign_num = recall_data.get("nhtsa_campaign_number") or recall_data.get(
                            "NHTSACampaignNumber"
                        )
                        if not campaign_num or campaign_num in existing_campaigns:
                            continue

                        recall = Recall(
                            vin=vehicle.vin,
                            nhtsa_campaign_number=campaign_num,
                            component=recall_data.get("Component") or recall_data.get("component"),
                            summary=recall_data.get("Summary") or recall_data.get("summary"),
                            consequence=recall_data.get("Consequence")
                            or recall_data.get("consequence"),
                            remedy=recall_data.get("Remedy") or recall_data.get("remedy"),
                        )
                        db.add(recall)
                        new_count += 1

                    if new_count > 0:
                        total_new += new_count
                        await dispatcher.notify_recall_detected(
                            vehicle_name=vehicle_name,
                            recall_count=new_count,
                        )
                        logger.info(
                            "Found %d new recall(s) for %s",
                            new_count,
                            vehicle_name,
                        )

                    # Rate limit: 2 seconds between vehicles
                    await asyncio.sleep(2)

                except Exception as e:
                    logger.error(
                        "Error checking recalls for %s: %s",
                        vehicle.vin,
                        str(e),
                    )

            # Update last check timestamp
            await SettingsService.set(db, "nhtsa_last_check", utc_now().isoformat())
            await db.commit()

            logger.info(
                "NHTSA recall check complete. Found %d new recall(s) across %d vehicle(s)",
                total_new,
                len(vehicles),
            )

        except Exception as e:
            logger.error("NHTSA recall check failed: %s", str(e))


async def check_reminder_notifications() -> None:
    """Check pending vehicle reminders and send notifications for due items."""
    logger.info("Running reminder notification check...")
    try:
        async with AsyncSessionLocal() as db:
            from app.services.reminder_service import check_due_reminders

            await check_due_reminders(db)
        logger.info("Reminder notification check completed")
    except Exception as e:
        logger.error("Reminder notification check failed: %s", str(e))


def start_scheduler() -> None:
    """Start the scheduled tasks.

    Only starts if SCHEDULER_ENABLED=true (explicit opt-in, fail-closed).

    Schedules:
        - Daily reset at midnight UTC for daily-limited providers
        - Monthly reset on 1st at midnight UTC for monthly-limited providers
        - Maintenance notification check at 8 AM UTC
        - Document expiration check at 9 AM UTC
        - Odometer milestone check at 10 AM UTC
        - DEF level check at 11 AM UTC
        - NHTSA recall check Sunday 2 AM UTC
        - LiveLink: Session timeout check every minute
        - LiveLink: Device offline check every 5 minutes
        - LiveLink: Pending offline finalization every 15 seconds
        - LiveLink: Daily summary generation at 1 AM UTC
        - LiveLink: Firmware check at 3 AM UTC
        - LiveLink: Telemetry pruning at 4 AM UTC
    """
    if os.environ.get("SCHEDULER_ENABLED", "").lower() != "true":
        logger.warning(
            "Scheduler disabled (SCHEDULER_ENABLED != 'true'). "
            "Background jobs will not run in this process."
        )
        return

    logger.info("Scheduler enabled — starting background jobs.")

    # Daily reset at midnight UTC
    scheduler.add_job(
        reset_daily_limits,
        "cron",
        hour=0,
        minute=0,
        id="reset_daily_limits",
        replace_existing=True,
    )

    # Monthly reset on 1st at midnight UTC
    scheduler.add_job(
        reset_monthly_limits,
        "cron",
        day=1,
        hour=0,
        minute=0,
        id="reset_monthly_limits",
        replace_existing=True,
    )

    # Reminder notification check at 8:00 AM UTC
    scheduler.add_job(
        check_reminder_notifications,
        "cron",
        hour=8,
        minute=0,
        id="check_reminder_notifications",
        replace_existing=True,
    )

    # Document expiration check at 9 AM UTC
    scheduler.add_job(
        check_expiring_documents,
        "cron",
        hour=9,
        minute=0,
        id="check_expiring_documents",
        replace_existing=True,
    )

    # Odometer milestone check at 10 AM UTC
    scheduler.add_job(
        check_odometer_milestones,
        "cron",
        hour=10,
        minute=0,
        id="check_odometer_milestones",
        replace_existing=True,
    )

    # DEF level check at 11 AM UTC
    scheduler.add_job(
        check_def_levels,
        "cron",
        hour=11,
        minute=0,
        id="check_def_levels",
        replace_existing=True,
    )

    # NHTSA recall check Sunday 2 AM UTC
    scheduler.add_job(
        check_recalls_all_vehicles,
        "cron",
        day_of_week="sun",
        hour=2,
        minute=0,
        id="check_recalls_all_vehicles",
        replace_existing=True,
    )

    # LiveLink tasks
    scheduler.add_job(
        check_session_timeouts,
        "interval",
        minutes=1,
        id="check_session_timeouts",
        replace_existing=True,
    )
    scheduler.add_job(
        check_device_offline_status,
        "interval",
        minutes=5,
        id="check_device_offline_status",
        replace_existing=True,
    )
    scheduler.add_job(
        finalize_pending_offlines,
        "interval",
        seconds=15,
        id="finalize_pending_offlines",
        replace_existing=True,
    )
    scheduler.add_job(
        generate_daily_summaries,
        "cron",
        hour=1,
        minute=0,
        id="generate_daily_summaries",
        replace_existing=True,
    )
    scheduler.add_job(
        check_firmware_updates,
        "cron",
        hour=3,
        minute=0,
        id="check_firmware_updates",
        replace_existing=True,
    )
    scheduler.add_job(
        prune_old_telemetry,
        "cron",
        hour=4,
        minute=0,
        id="prune_old_telemetry",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduled tasks started")


def stop_scheduler() -> None:
    """Stop the scheduled tasks."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduled tasks stopped")
