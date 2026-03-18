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

from app.database import AsyncSessionLocal
from app.models import (
    InsurancePolicy,
    MaintenanceScheduleItem,
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


async def check_maintenance_notifications() -> None:
    """Check maintenance schedule items and send notifications.

    Runs daily at 8 AM UTC. Reads notify_service_days and notify_service_miles
    settings to determine thresholds. Uses 24-hour cooldown per status to
    prevent duplicate notifications.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Check if service notifications are enabled
            dispatcher = NotificationDispatcher(db)
            if not await dispatcher._has_any_service_enabled():
                return

            # Read threshold settings
            notify_service_days = int(await _get_setting(db, "notify_service_days", "30"))
            notify_service_miles = int(await _get_setting(db, "notify_service_miles", "500"))

            # Get all vehicles
            vehicles_result = await db.execute(select(Vehicle).where(Vehicle.archived_at.is_(None)))
            vehicles = vehicles_result.scalars().all()

            now = utc_now()
            today = date.today()

            for vehicle in vehicles:
                try:
                    vehicle_name = (
                        vehicle.nickname or f"{vehicle.year} {vehicle.make} {vehicle.model}"
                    )

                    # Get current mileage
                    odo_result = await db.execute(
                        select(OdometerRecord.mileage)
                        .where(OdometerRecord.vin == vehicle.vin)
                        .order_by(OdometerRecord.date.desc())
                        .limit(1)
                    )
                    current_mileage = odo_result.scalar_one_or_none()

                    # Get schedule items
                    items_result = await db.execute(
                        select(MaintenanceScheduleItem).where(
                            MaintenanceScheduleItem.vin == vehicle.vin
                        )
                    )
                    items = items_result.scalars().all()

                    for item in items:
                        status = item.calculate_status(today, current_mileage)

                        # Skip items that are on_track or never_performed with no intervals
                        if status == "on_track":
                            continue
                        if (
                            status == "never_performed"
                            and not item.interval_months
                            and not item.interval_miles
                        ):
                            continue

                        # Dedup check: skip if same status notified within cooldown
                        if (
                            item.last_notified_status == status
                            and item.last_notified_at
                            and (now - item.last_notified_at) < NOTIFICATION_COOLDOWN
                        ):
                            continue

                        # Calculate days/miles for message
                        next_date = item.next_due_date
                        days_until = (next_date - today).days if next_date else None

                        if status == "overdue":
                            days_overdue = abs(days_until) if days_until is not None else 0
                            await dispatcher.notify_service_overdue(
                                vehicle_name=vehicle_name,
                                service_type=item.name,
                                days_overdue=days_overdue,
                            )
                        elif status in ("due_soon", "never_performed"):
                            days_left = (
                                days_until if days_until is not None else notify_service_days
                            )
                            # Only notify if within threshold
                            if days_left <= notify_service_days:
                                await dispatcher.notify_service_due(
                                    vehicle_name=vehicle_name,
                                    service_type=item.name,
                                    days_until_due=days_left,
                                )
                            elif current_mileage and item.next_due_mileage:
                                miles_left = item.next_due_mileage - current_mileage
                                if 0 < miles_left <= notify_service_miles:
                                    await dispatcher.notify_service_due(
                                        vehicle_name=vehicle_name,
                                        service_type=item.name,
                                        days_until_due=days_left,
                                    )
                                else:
                                    continue
                            else:
                                continue

                        # Update notification tracking
                        item.last_notified_at = now
                        item.last_notified_status = status

                except Exception as e:
                    logger.error(
                        "Error checking maintenance for vehicle %s: %s",
                        vehicle.vin,
                        str(e),
                    )

            await db.commit()
            logger.info("Maintenance notification check complete")

        except Exception as e:
            logger.error("Maintenance notification check failed: %s", str(e))


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

    Runs daily at 10 AM UTC. Checks each vehicle's latest mileage against
    milestone boundaries (every 10,000 miles). Uses last_milestone_notified
    on the vehicle to prevent duplicate notifications.
    """
    milestone_interval = 10_000

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
                    # Get latest mileage
                    odo_result = await db.execute(
                        select(OdometerRecord.mileage)
                        .where(OdometerRecord.vin == vehicle.vin)
                        .order_by(OdometerRecord.date.desc())
                        .limit(1)
                    )
                    current_mileage = odo_result.scalar_one_or_none()
                    if not current_mileage:
                        continue

                    # Calculate the highest milestone crossed
                    current_milestone = (current_mileage // milestone_interval) * milestone_interval
                    if current_milestone == 0:
                        continue

                    last_notified = vehicle.last_milestone_notified or 0

                    if current_milestone > last_notified:
                        vehicle_name = (
                            vehicle.nickname or f"{vehicle.year} {vehicle.make} {vehicle.model}"
                        )
                        await dispatcher.notify_odometer_milestone(
                            vehicle_name=vehicle_name,
                            milestone=current_milestone,
                        )
                        vehicle.last_milestone_notified = current_milestone
                        logger.info(
                            "Milestone notification: %s reached %s miles",
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

    # Maintenance notification check at 8 AM UTC
    scheduler.add_job(
        check_maintenance_notifications,
        "cron",
        hour=8,
        minute=0,
        id="check_maintenance_notifications",
        replace_existing=True,
    )

    # Reminder notification check at 8:15 AM UTC (offset from maintenance check)
    scheduler.add_job(
        check_reminder_notifications,
        "cron",
        hour=8,
        minute=15,
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
