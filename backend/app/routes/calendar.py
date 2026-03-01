"""Calendar routes for MyGarage API."""

from datetime import date, timedelta
from io import StringIO
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import (
    InsurancePolicy,
    MaintenanceScheduleItem,
    OdometerRecord,
    ServiceVisit,
    Vehicle,
    WarrantyRecord,
)
from app.models.user import User
from app.schemas.calendar import CalendarEvent, CalendarResponse, CalendarSummary
from app.services.auth import require_auth

router = APIRouter(prefix="/api", tags=["calendar"])


UrgencyLevel = Literal["overdue", "high", "medium", "low", "historical"]


def calculate_urgency(event_date: date, is_overdue: bool) -> UrgencyLevel:
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
    start_date: date | None = Query(None, description="Start date filter (default: 1 month ago)"),
    end_date: date | None = Query(None, description="End date filter (default: 1 year ahead)"),
    vehicle_vins: str | None = Query(None, description="Comma-separated VINs to filter by"),
    event_types: str | None = Query(
        None, description="Comma-separated event types (maintenance,insurance,warranty,service)"
    ),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> CalendarResponse:
    """Get calendar events aggregated from maintenance schedule, insurance, and warranties."""

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
        else ["maintenance", "insurance", "warranty", "service"]
    )

    # Get all vehicles for nickname lookup
    vehicles_result = await db.execute(select(Vehicle))
    vehicles_dict = {v.vin: v for v in vehicles_result.scalars().all()}

    events = []
    today = date.today()

    # Fetch maintenance schedule items
    if "maintenance" in type_list:
        schedule_query = select(MaintenanceScheduleItem)

        if vin_list:
            schedule_query = schedule_query.where(MaintenanceScheduleItem.vin.in_(vin_list))

        schedule_result = await db.execute(schedule_query)
        schedule_items = schedule_result.scalars().all()

        # Get current mileage per vehicle for status calculation
        vehicle_mileage: dict[str, int | None] = {}
        for item in schedule_items:
            if item.vin not in vehicle_mileage:
                odo_result = await db.execute(
                    select(OdometerRecord.mileage)
                    .where(OdometerRecord.vin == item.vin)
                    .order_by(OdometerRecord.date.desc())
                    .limit(1)
                )
                vehicle_mileage[item.vin] = odo_result.scalar_one_or_none()

        for item in schedule_items:
            vehicle = vehicles_dict.get(item.vin)
            current_mileage = vehicle_mileage.get(item.vin)
            status = item.calculate_status(today, current_mileage)

            # Determine the event date
            event_date = item.next_due_date
            is_estimated = False
            due_mileage = item.next_due_mileage

            # If no date-based interval but has mileage interval, estimate from mileage
            if event_date is None and due_mileage is not None:
                event_date = await estimate_date_from_mileage(item.vin, due_mileage, db)
                is_estimated = event_date is not None

            # If still no date, use today for never_performed items (needs attention)
            if event_date is None:
                if status == "never_performed":
                    event_date = today
                else:
                    continue

            # Filter by date range
            if event_date < start_date or event_date > end_date:
                continue

            # Map status to urgency
            urgency: UrgencyLevel
            if status == "overdue":
                urgency = "overdue"
            elif status == "due_soon":
                days_until = (event_date - today).days
                urgency = "high" if days_until <= 7 else "medium"
            elif status == "never_performed":
                urgency = "medium"
            else:
                urgency = "low"

            # Determine if recurring (has intervals)
            is_recurring = bool(item.interval_months or item.interval_miles)

            # Calculate days/miles until due
            days_until_due = (event_date - today).days
            miles_until_due = None
            if due_mileage is not None and current_mileage is not None:
                miles_until_due = due_mileage - current_mileage

            events.append(
                CalendarEvent(
                    id=f"maintenance-{item.id}",
                    type="maintenance",
                    title=item.name,
                    description=f"{item.component_category} - {item.item_type}",
                    date=event_date,
                    vehicle_vin=item.vin,
                    vehicle_nickname=vehicle.nickname if vehicle else None,
                    vehicle_color=None,
                    urgency=urgency,
                    is_recurring=is_recurring,
                    is_completed=False,
                    is_estimated=is_estimated,
                    category="maintenance",
                    notes=None,
                    due_mileage=due_mileage,
                    status=status,
                    days_until_due=days_until_due,
                    miles_until_due=miles_until_due,
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
            is_overdue = bool(warranty.end_date and warranty.end_date < today)

            events.append(
                CalendarEvent(
                    id=f"warranty-{warranty.id}",
                    type="warranty",
                    title=f"{warranty.warranty_type} Warranty Expiration",
                    description=f"{warranty.provider or 'N/A'}"
                    + (f" - {warranty.policy_number}" if warranty.policy_number else ""),
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
        service_query = (
            select(ServiceVisit)
            .options(selectinload(ServiceVisit.line_items))
            .options(selectinload(ServiceVisit.vendor))
            .where(
                ServiceVisit.date >= start_date,
                ServiceVisit.date <= end_date,
            )
        )

        if vin_list:
            service_query = service_query.where(ServiceVisit.vin.in_(vin_list))

        service_result = await db.execute(service_query)
        visits = service_result.scalars().all()

        for visit in visits:
            vehicle = vehicles_dict.get(visit.vin)
            # Build title from first line item description, or notes, or category
            title = "Service"
            if visit.line_items:
                title = visit.line_items[0].description
            elif visit.notes:
                title = visit.notes

            vendor_name = visit.vendor.name if visit.vendor else None
            description = f"{visit.service_category or 'Service'}"
            if vendor_name:
                description += f" - {vendor_name}"

            events.append(
                CalendarEvent(
                    id=f"service-{visit.id}",
                    type="service",
                    title=title,
                    description=description,
                    date=visit.date,
                    vehicle_vin=visit.vin,
                    vehicle_nickname=vehicle.nickname if vehicle else None,
                    vehicle_color=None,
                    urgency="historical",  # Historical events don't have urgency
                    is_recurring=False,
                    is_completed=True,  # Service history is always completed
                    is_estimated=False,
                    category="history",
                    notes=visit.notes,
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
        if not e.is_completed and e.date >= today and e.date <= today + timedelta(days=7)
    )
    upcoming_30_count = sum(
        1
        for e in events
        if not e.is_completed and e.date >= today and e.date <= today + timedelta(days=30)
    )

    summary = CalendarSummary(
        total=len(events),
        overdue=overdue_count,
        upcoming_7_days=upcoming_7_count,
        upcoming_30_days=upcoming_30_count,
    )

    return CalendarResponse(events=events, summary=summary)


async def calculate_average_miles_per_day(vin: str, db: AsyncSession) -> float | None:
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


async def estimate_date_from_mileage(vin: str, due_mileage: int, db: AsyncSession) -> date | None:
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
