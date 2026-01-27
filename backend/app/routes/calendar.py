"""Calendar routes for MyGarage API."""

from datetime import date, timedelta
from io import StringIO
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    InsurancePolicy,
    OdometerRecord,
    Reminder,
    ServiceRecord,
    Vehicle,
    WarrantyRecord,
)
from app.models.user import User
from app.schemas.calendar import CalendarEvent, CalendarResponse, CalendarSummary
from app.services.auth import require_auth

router = APIRouter(prefix="/api", tags=["calendar"])


def calculate_urgency(event_date: date, is_overdue: bool) -> str:
    """Calculate urgency level based on date."""
    if is_overdue:
        return "overdue"

    days_until = (event_date - date.today()).days

    if days_until <= 7:
        return "high"
    elif days_until <= 30:
        return "medium"
    else:
        return "low"


@router.get("/calendar", response_model=CalendarResponse)
async def get_calendar_events(
    start_date: date | None = Query(
        None, description="Start date filter (default: 1 month ago)"
    ),
    end_date: date | None = Query(
        None, description="End date filter (default: 1 year ahead)"
    ),
    vehicle_vins: str | None = Query(
        None, description="Comma-separated VINs to filter by"
    ),
    event_types: str | None = Query(
        None, description="Comma-separated event types (reminder,insurance,warranty)"
    ),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> CalendarResponse:
    """Get calendar events aggregated from reminders, insurance, and warranties."""

    # Set default date range if not provided
    if start_date is None:
        start_date = date.today() - timedelta(days=30)
    if end_date is None:
        end_date = date.today() + timedelta(days=365)

    # Parse filters
    vin_list = vehicle_vins.split(",") if vehicle_vins else None
    type_list = (
        event_types.split(",")
        if event_types
        else ["reminder", "insurance", "warranty", "service"]
    )

    # Get all vehicles for nickname lookup
    vehicles_result = await db.execute(select(Vehicle))
    vehicles_dict = {v.vin: v for v in vehicles_result.scalars().all()}

    events = []
    today = date.today()

    # Fetch reminders with due_date
    if "reminder" in type_list:
        # Fetch date-based reminders
        reminder_query = select(Reminder).where(
            Reminder.due_date.isnot(None),
            Reminder.due_date >= start_date,
            Reminder.due_date <= end_date,
        )

        if vin_list:
            reminder_query = reminder_query.where(Reminder.vin.in_(vin_list))

        reminders_result = await db.execute(reminder_query)
        reminders = reminders_result.scalars().all()

        for reminder in reminders:
            vehicle = vehicles_dict.get(reminder.vin)
            is_overdue = reminder.due_date < today and not reminder.is_completed

            events.append(
                CalendarEvent(
                    id=f"reminder-{reminder.id}",
                    type="reminder",
                    title=reminder.description,
                    description=reminder.notes,
                    date=reminder.due_date,
                    vehicle_vin=reminder.vin,
                    vehicle_nickname=vehicle.nickname if vehicle else None,
                    vehicle_color=None,  # Will be added in vehicle color feature
                    urgency=calculate_urgency(reminder.due_date, is_overdue),
                    is_recurring=reminder.is_recurring,
                    is_completed=reminder.is_completed,
                    is_estimated=False,
                    category="maintenance",
                    notes=reminder.notes,
                    due_mileage=reminder.due_mileage,
                )
            )

        # Fetch mileage-based reminders and estimate dates
        mileage_reminder_query = select(Reminder).where(
            Reminder.due_mileage.isnot(None),
            Reminder.due_date.is_(None),  # Only mileage-based (no date set)
        )

        if vin_list:
            mileage_reminder_query = mileage_reminder_query.where(
                Reminder.vin.in_(vin_list)
            )

        mileage_reminders_result = await db.execute(mileage_reminder_query)
        mileage_reminders = mileage_reminders_result.scalars().all()

        for reminder in mileage_reminders:
            vehicle = vehicles_dict.get(reminder.vin)

            # Estimate date from mileage
            estimated_date = await estimate_date_from_mileage(
                reminder.vin, reminder.due_mileage, db
            )

            if estimated_date and start_date <= estimated_date <= end_date:
                is_overdue = estimated_date < today and not reminder.is_completed

                events.append(
                    CalendarEvent(
                        id=f"reminder-{reminder.id}",
                        type="reminder",
                        title=f"{reminder.description} (est.)",
                        description=reminder.notes,
                        date=estimated_date,
                        vehicle_vin=reminder.vin,
                        vehicle_nickname=vehicle.nickname if vehicle else None,
                        vehicle_color=None,
                        urgency=calculate_urgency(estimated_date, is_overdue),
                        is_recurring=reminder.is_recurring,
                        is_completed=reminder.is_completed,
                        is_estimated=True,  # Mark as estimated
                        category="maintenance",
                        notes=reminder.notes,
                        due_mileage=reminder.due_mileage,
                    )
                )

    # Fetch insurance policies
    if "insurance" in type_list:
        insurance_query = select(InsurancePolicy).where(
            InsurancePolicy.end_date >= start_date,
            InsurancePolicy.end_date <= end_date,
        )

        if vin_list:
            insurance_query = insurance_query.where(InsurancePolicy.vin.in_(vin_list))

        insurance_result = await db.execute(insurance_query)
        insurance_policies = insurance_result.scalars().all()

        for policy in insurance_policies:
            vehicle = vehicles_dict.get(policy.vin)
            is_overdue = policy.end_date < today

            events.append(
                CalendarEvent(
                    id=f"insurance-{policy.id}",
                    type="insurance",
                    title=f"{policy.provider} - {policy.policy_type} Renewal",
                    description=f"Policy #{policy.policy_number}",
                    date=policy.end_date,
                    vehicle_vin=policy.vin,
                    vehicle_nickname=vehicle.nickname if vehicle else None,
                    vehicle_color=None,
                    urgency=calculate_urgency(policy.end_date, is_overdue),
                    is_recurring=True,  # Insurance typically renews annually
                    is_completed=False,
                    is_estimated=False,
                    category="legal",
                    notes=None,
                    due_mileage=None,
                )
            )

    # Fetch warranties
    if "warranty" in type_list:
        warranty_query = select(WarrantyRecord).where(
            WarrantyRecord.end_date.isnot(None),
            WarrantyRecord.end_date >= start_date,
            WarrantyRecord.end_date <= end_date,
        )

        if vin_list:
            warranty_query = warranty_query.where(WarrantyRecord.vin.in_(vin_list))

        warranty_result = await db.execute(warranty_query)
        warranties = warranty_result.scalars().all()

        for warranty in warranties:
            vehicle = vehicles_dict.get(warranty.vin)
            is_overdue = warranty.end_date < today

            events.append(
                CalendarEvent(
                    id=f"warranty-{warranty.id}",
                    type="warranty",
                    title=f"{warranty.warranty_type} Warranty Expiration",
                    description=f"{warranty.provider or 'N/A'}"
                    + (
                        f" - {warranty.policy_number}" if warranty.policy_number else ""
                    ),
                    date=warranty.end_date,
                    vehicle_vin=warranty.vin,
                    vehicle_nickname=vehicle.nickname if vehicle else None,
                    vehicle_color=None,
                    urgency=calculate_urgency(warranty.end_date, is_overdue),
                    is_recurring=False,
                    is_completed=False,
                    is_estimated=False,
                    category="legal",
                    notes=None,
                    due_mileage=None,
                )
            )

    # Fetch service history (past records only for historical context)
    if "service" in type_list:
        service_query = select(ServiceRecord).where(
            ServiceRecord.date >= start_date,
            ServiceRecord.date <= end_date,
        )

        if vin_list:
            service_query = service_query.where(ServiceRecord.vin.in_(vin_list))

        service_result = await db.execute(service_query)
        services = service_result.scalars().all()

        for service in services:
            vehicle = vehicles_dict.get(service.vin)

            events.append(
                CalendarEvent(
                    id=f"service-{service.id}",
                    type="service",
                    title=service.service_type,  # Now holds specific service
                    description=f"{service.service_category or 'Service'}"
                    + (f" - {service.vendor_name}" if service.vendor_name else ""),
                    date=service.date,
                    vehicle_vin=service.vin,
                    vehicle_nickname=vehicle.nickname if vehicle else None,
                    vehicle_color=None,
                    urgency="historical",  # Historical events don't have urgency
                    is_recurring=False,
                    is_completed=True,  # Service history is always completed
                    is_estimated=False,
                    category="history",
                    notes=service.notes if hasattr(service, "notes") else None,
                    due_mileage=None,
                )
            )

    # Sort events by date
    events.sort(key=lambda e: e.date)

    # Calculate summary statistics
    overdue_count = sum(1 for e in events if e.urgency == "overdue")
    upcoming_7_count = sum(
        1
        for e in events
        if not e.is_completed
        and e.date >= today
        and e.date <= today + timedelta(days=7)
    )
    upcoming_30_count = sum(
        1
        for e in events
        if not e.is_completed
        and e.date >= today
        and e.date <= today + timedelta(days=30)
    )

    summary = CalendarSummary(
        total=len(events),
        overdue=overdue_count,
        upcoming_7_days=upcoming_7_count,
        upcoming_30_days=upcoming_30_count,
    )

    return CalendarResponse(events=events, summary=summary)


async def calculate_average_miles_per_day(
    vin: str, db: AsyncSession
) -> float | None:
    """Calculate average miles per day for a vehicle based on odometer history."""
    # Get last 30 days of odometer readings (or all if less than 30 days of data)
    odometer_query = (
        select(OdometerRecord)
        .where(OdometerRecord.vin == vin)
        .order_by(desc(OdometerRecord.date))
        .limit(30)
    )

    result = await db.execute(odometer_query)
    records = result.scalars().all()

    if len(records) < 2:
        # Not enough data to calculate average
        return None

    # Calculate miles per day using oldest and newest records
    oldest = records[-1]
    newest = records[0]

    days_diff = (newest.date - oldest.date).days
    miles_diff = newest.mileage - oldest.mileage

    if days_diff == 0 or miles_diff < 0:
        return None

    return miles_diff / days_diff


async def estimate_date_from_mileage(
    vin: str, due_mileage: int, db: AsyncSession
) -> date | None:
    """Estimate due date for a mileage-based reminder."""
    # Get current mileage
    odometer_query = (
        select(OdometerRecord)
        .where(OdometerRecord.vin == vin)
        .order_by(desc(OdometerRecord.date))
        .limit(1)
    )

    result = await db.execute(odometer_query)
    current_record = result.scalar_one_or_none()

    if not current_record:
        return None

    current_mileage = current_record.mileage
    miles_remaining = due_mileage - current_mileage

    if miles_remaining <= 0:
        # Already past due
        return date.today()

    # Get average miles per day
    avg_miles_per_day = await calculate_average_miles_per_day(vin, db)

    if not avg_miles_per_day or avg_miles_per_day <= 0:
        # Can't estimate without average
        return None

    # Calculate estimated days until due
    days_until_due = int(miles_remaining / avg_miles_per_day)

    return date.today() + timedelta(days=days_until_due)


@router.get("/calendar/export")
async def export_calendar_ical(
    start_date: date | None = Query(None, description="Start date filter"),
    end_date: date | None = Query(None, description="End date filter"),
    vehicle_vins: str | None = Query(None, description="Comma-separated VINs"),
    event_types: str | None = Query(None, description="Comma-separated event types"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
):
    """Export calendar events as iCal format."""
    # Get events using existing function logic
    calendar_response = await get_calendar_events(
        start_date=start_date,
        end_date=end_date,
        vehicle_vins=vehicle_vins,
        event_types=event_types,
        db=db,
    )

    # Generate iCal format
    ical = StringIO()
    ical.write("BEGIN:VCALENDAR\r\n")
    ical.write("VERSION:2.0\r\n")
    ical.write("PRODID:-//MyGarage//Vehicle Maintenance Calendar//EN\r\n")
    ical.write("CALSCALE:GREGORIAN\r\n")
    ical.write("X-WR-CALNAME:MyGarage Maintenance\r\n")
    ical.write("X-WR-TIMEZONE:UTC\r\n")

    for event in calendar_response.events:
        ical.write("BEGIN:VEVENT\r\n")
        ical.write(f"UID:{event.id}@mygarage.local\r\n")
        ical.write(f"DTSTART;VALUE=DATE:{event.date.strftime('%Y%m%d')}\r\n")
        ical.write(f"SUMMARY:{event.title}\r\n")

        if event.description:
            # Escape special characters in description
            desc = (
                event.description.replace("\\", "\\\\")
                .replace(",", "\\,")
                .replace(";", "\\;")
                .replace("\n", "\\n")
            )
            ical.write(f"DESCRIPTION:{desc}\r\n")

        # Add vehicle info to location
        vehicle_info = event.vehicle_nickname or event.vehicle_vin
        ical.write(f"LOCATION:{vehicle_info}\r\n")

        # Add category
        ical.write(f"CATEGORIES:{event.type.upper()}\r\n")

        # Add status based on completion
        if event.is_completed:
            ical.write("STATUS:COMPLETED\r\n")
        elif event.urgency == "overdue":
            ical.write("STATUS:CONFIRMED\r\n")
            ical.write("PRIORITY:1\r\n")  # High priority for overdue
        else:
            ical.write("STATUS:CONFIRMED\r\n")

        # Add recurrence rule if recurring
        if event.is_recurring:
            ical.write("RRULE:FREQ=YEARLY\r\n")  # Default to yearly

        ical.write("END:VEVENT\r\n")

    ical.write("END:VCALENDAR\r\n")

    return Response(
        content=ical.getvalue(),
        media_type="text/calendar",
        headers={
            "Content-Disposition": f"attachment; filename=mygarage-calendar-{date.today().strftime('%Y%m%d')}.ics"
        },
    )
