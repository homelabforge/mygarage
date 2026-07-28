from datetime import date as date_type
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    DEFRecord,
    Document,
    FuelRecord,
    Note,
    OdometerRecord,
    Reminder,
    ServiceVisit,
    Vehicle,
)
from app.models.user import User
from app.models.vehicle_share import VehicleShare
from app.schemas.dashboard import (
    DashboardResponse,
    FleetHealth,
    FleetNextDue,
    VehicleStatistics,
)
from app.services.auth import require_auth
from app.services.fuel_service import compute_full_tank_economy
from app.services.odometer_service import latest_odometer_km_and_date
from app.services.service_visit_service import service_visit_cost_load_options

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Photo directory configuration
PHOTO_DIR = Path("/data/photos")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


async def calculate_vehicle_stats(
    db: AsyncSession,
    vehicle: Vehicle,
    is_shared_with_me: bool = False,
    shared_by_username: str | None = None,
    share_permission: str | None = None,
) -> VehicleStatistics:
    """Calculate statistics for a single vehicle"""

    # Count records
    service_count = await db.scalar(
        select(func.count(ServiceVisit.id)).where(ServiceVisit.vin == vehicle.vin)
    )
    fuel_count = await db.scalar(
        select(func.count(FuelRecord.id)).where(FuelRecord.vin == vehicle.vin)
    )
    odometer_count = await db.scalar(
        select(func.count(OdometerRecord.id)).where(OdometerRecord.vin == vehicle.vin)
    )
    maintenance_count = await db.scalar(
        select(func.count(Reminder.id)).where(Reminder.vin == vehicle.vin)
    )
    document_count = await db.scalar(
        select(func.count(Document.id)).where(Document.vin == vehicle.vin)
    )
    note_count = await db.scalar(select(func.count(Note.id)).where(Note.vin == vehicle.vin))

    # Count photos from filesystem
    photo_count = 0
    vehicle_photo_dir = PHOTO_DIR / vehicle.vin
    if vehicle_photo_dir.exists():
        photo_count = sum(
            1
            for photo_file in vehicle_photo_dir.iterdir()
            if photo_file.is_file() and photo_file.suffix.lower() in ALLOWED_EXTENSIONS
        )

    # Get latest service date
    latest_service = await db.scalar(
        select(ServiceVisit.date)
        .where(ServiceVisit.vin == vehicle.vin)
        .order_by(ServiceVisit.date.desc())
        .limit(1)
    )

    # Get latest fuel date
    latest_fuel = await db.scalar(
        select(FuelRecord.date)
        .where(FuelRecord.vin == vehicle.vin)
        .order_by(FuelRecord.date.desc())
        .limit(1)
    )

    # Latest odometer reading (km) + its date — one deterministic fetch shared
    # with detail-stats (date DESC, id DESC tie-break; odometer_service). R2-B1.
    latest_odometer_km, latest_odometer_date = await latest_odometer_km_and_date(db, vehicle.vin)

    # Count upcoming and overdue reminders
    today = date_type.today()
    pending_reminders_result = await db.execute(
        select(Reminder).where(Reminder.vin == vehicle.vin, Reminder.status == "pending")
    )
    pending_reminders = pending_reminders_result.scalars().all()

    # Reuse the SAME fetched reading for the mileage-reminder evaluation so the
    # displayed reading and the mileage eval can never disagree — and so the
    # dashboard card and the detail hero agree on a same-date-reading vehicle. R2-B1.
    current_odometer_km = latest_odometer_km

    upcoming_count = 0
    overdue_count = 0
    for reminder in pending_reminders:
        is_overdue = False
        if reminder.due_date and reminder.due_date <= today:
            is_overdue = True
        if (
            reminder.due_mileage_km
            and current_odometer_km
            and current_odometer_km >= reminder.due_mileage_km
        ):
            is_overdue = True
        if is_overdue:
            overdue_count += 1
        else:
            upcoming_count += 1

    # Per-full-tank L/100km, anchored to the previous FULL tank with partial
    # fill-ups folded in (issue #113). Ordered by odometer ascending so the
    # last entries are the most recent.
    fuel_records_result = await db.execute(
        select(FuelRecord)
        .where(FuelRecord.vin == vehicle.vin)
        .where(FuelRecord.odometer_km.isnot(None))
        .order_by(FuelRecord.odometer_km.asc(), FuelRecord.date.asc())
    )
    fuel_records_list = list(fuel_records_result.scalars().all())
    l_per_100km_values = [value for _, value in compute_full_tank_economy(fuel_records_list)]

    average_l_per_100km: Decimal | None = None
    recent_l_per_100km: Decimal | None = None
    if l_per_100km_values:
        average_l_per_100km = round(sum(l_per_100km_values) / Decimal(len(l_per_100km_values)), 2)
        # Recent L/100km is the average of the last 3 full-tank fill-ups.
        recent_window = l_per_100km_values[-3:]
        recent_l_per_100km = round(sum(recent_window) / Decimal(len(recent_window)), 2)

    # Get main photo URL from Vehicle.main_photo field
    main_photo_url: str | None = None
    if vehicle.main_photo:
        # main_photo is stored as "VIN/filename.jpg"
        # Extract just the filename
        from pathlib import Path

        filename = Path(vehicle.main_photo).name
        main_photo_url = f"/api/vehicles/{vehicle.vin}/photos/{filename}"

    return VehicleStatistics(
        vin=vehicle.vin,
        year=vehicle.year,
        make=vehicle.make,
        model=vehicle.model,
        vehicle_type=vehicle.vehicle_type,
        main_photo_url=main_photo_url,
        usage_unit=vehicle.usage_unit,
        current_hours=vehicle.current_hours,
        total_service_records=service_count or 0,
        total_fuel_records=fuel_count or 0,
        total_odometer_records=odometer_count or 0,
        total_maintenance_items=maintenance_count or 0,
        total_documents=document_count or 0,
        total_notes=note_count or 0,
        total_photos=photo_count or 0,
        latest_service_date=latest_service,
        latest_fuel_date=latest_fuel,
        latest_odometer_km=latest_odometer_km,
        latest_odometer_date=latest_odometer_date,
        upcoming_maintenance_count=upcoming_count or 0,
        overdue_maintenance_count=overdue_count or 0,
        average_l_per_100km=average_l_per_100km,
        recent_l_per_100km=recent_l_per_100km,
        archived_at=vehicle.archived_at,
        archived_visible=vehicle.archived_visible,
        is_shared_with_me=is_shared_with_me,
        shared_by_username=shared_by_username,
        share_permission=share_permission,
    )


async def _fleet_next_due(
    db: AsyncSession, vins: list[str], vehicle_stats: list[VehicleStatistics]
) -> FleetNextDue | None:
    """Pick the single most-urgent pending reminder across the fleet (OQ1).

    Deterministic two-tier rule:

    1. **Dated reminders win.** Candidates with a ``due_date``, ordered
       ``due_date ASC, id ASC`` (the ``id`` tie-break is stable on SQLite AND
       PG; uses ``ix_reminders_due_date``). A ``due_date`` is a
       driver-independent absolute "when"; a mileage-to-date projection would
       need a per-vehicle daily-distance model MyGarage does not store, so a
       dated reminder always outranks a mileage-only one. Includes overdue
       dated reminders (a past date sorts first — the most urgent "next").
    2. **Mileage-only fallback.** Only when the fleet has no dated pending
       reminder: rank ``due_date IS NULL AND due_mileage_km IS NOT NULL``
       reminders by remaining distance to due — ``due_mileage_km − latest
       odometer(vin)`` from ``vehicle_stats`` — with vehicles that have no
       odometer reading sorted after those that do (falling back to
       ``due_mileage_km ASC``); final tie-break ``id ASC``.
    """
    dated = (
        await db.execute(
            select(
                Reminder.vin,
                Reminder.title,
                Reminder.due_date,
                Reminder.due_mileage_km,
            )
            .where(
                Reminder.vin.in_(vins),
                Reminder.status == "pending",
                Reminder.due_date.isnot(None),
            )
            .order_by(Reminder.due_date.asc(), Reminder.id.asc())
            .limit(1)
        )
    ).first()
    if dated is not None:
        return FleetNextDue(
            vin=dated[0],
            label=dated[1],
            due_date=dated[2],
            due_mileage_km=dated[3],  # passed through so the strip can show both
        )

    mileage_rows = (
        await db.execute(
            select(
                Reminder.id,
                Reminder.vin,
                Reminder.title,
                Reminder.due_mileage_km,
            ).where(
                Reminder.vin.in_(vins),
                Reminder.status == "pending",
                Reminder.due_date.is_(None),
                Reminder.due_mileage_km.isnot(None),
            )
        )
    ).all()
    if not mileage_rows:
        return None

    odo_by_vin = {s.vin: s.latest_odometer_km for s in vehicle_stats}
    # Plain tuples (id, vin, title, due_mileage_km) so the sort key is fully
    # typed without importing SQLAlchemy Row internals.
    candidates: list[tuple[int, str, str, Decimal]] = [
        (r[0], r[1], r[2], r[3]) for r in mileage_rows
    ]

    def _rank(item: tuple[int, str, str, Decimal]) -> tuple[int, Decimal, int]:
        odo = odo_by_vin.get(item[1])
        if odo is not None:
            # Has an odometer reading -> rank first (0), by remaining distance.
            return (0, item[3] - odo, item[0])
        # No reading -> rank after (1), by absolute due mileage.
        return (1, item[3], item[0])

    best = min(candidates, key=_rank)
    return FleetNextDue(
        vin=best[1],
        label=best[2],
        due_date=None,
        due_mileage_km=best[3],
    )


async def calculate_fleet_health(
    db: AsyncSession, vehicle_stats: list[VehicleStatistics]
) -> FleetHealth:
    """Fleet-wide health summary for the dashboard strip.

    Scope is the already-computed, already-authorized ``vehicle_stats`` — this
    never re-scopes or widens the fleet. Overdue reuses the per-vehicle counts
    verbatim (so the strip agrees with each card badge). Upcoming is the
    strictly-future 30-day pending window (``today < due_date <= today+30``) so
    a due-today reminder is Overdue only, never both. Spent-this-year mirrors
    the garage-analytics monthly-trend running-cost set (service + fuel + DEF),
    for records dated ``year_start <= date <= today`` (true YTD — a
    later-this-year record is NOT counted). Next-due is delegated to
    ``_fleet_next_due`` (dated reminders first, mileage-only fallback).

    All date filters are Date-column-vs-Python-date range comparisons, so the
    query is identical on SQLite (prod) and PostgreSQL (CI) — no EXTRACT /
    strftime (G8). Costs are Decimal, never float (G9).
    """
    today = date_type.today()
    year = today.year
    year_start = date_type(year, 1, 1)
    upcoming_end = today + timedelta(days=30)

    overdue_count = sum(s.overdue_maintenance_count for s in vehicle_stats)

    vins = [s.vin for s in vehicle_stats]
    if not vins:
        return FleetHealth(
            overdue_count=overdue_count,
            upcoming_30d_count=0,
            year=year,
            spent_this_year=Decimal("0.00"),
            next_due=None,
        )

    # Upcoming — pending reminders due strictly after today, within 30 days.
    # `> today` (not `>=`) keeps a due-today reminder Overdue-only (finding 6).
    upcoming_30d = await db.scalar(
        select(func.count(Reminder.id)).where(
            Reminder.vin.in_(vins),
            Reminder.status == "pending",
            Reminder.due_date.isnot(None),
            Reminder.due_date > today,
            Reminder.due_date <= upcoming_end,
        )
    )

    # Spent this year — service (property, so summed in Python) + fuel + DEF,
    # dated this year up to and including today (true YTD; finding 5).
    service_visits_result = await db.execute(
        select(ServiceVisit)
        .options(*service_visit_cost_load_options())
        .where(
            ServiceVisit.vin.in_(vins),
            ServiceVisit.date >= year_start,
            ServiceVisit.date <= today,
        )
    )
    service_spent = sum(
        (v.calculated_total_cost for v in service_visits_result.scalars().all()),
        Decimal("0.00"),
    )

    fuel_costs = await db.execute(
        select(FuelRecord.cost).where(
            FuelRecord.vin.in_(vins),
            FuelRecord.cost.isnot(None),
            FuelRecord.date >= year_start,
            FuelRecord.date <= today,
        )
    )
    fuel_spent = sum((c for c in fuel_costs.scalars().all() if c), Decimal("0.00"))

    def_costs = await db.execute(
        select(DEFRecord.cost).where(
            DEFRecord.vin.in_(vins),
            DEFRecord.cost.isnot(None),
            DEFRecord.date >= year_start,
            DEFRecord.date <= today,
        )
    )
    def_spent = sum((c for c in def_costs.scalars().all() if c), Decimal("0.00"))

    spent_this_year = service_spent + fuel_spent + def_spent

    next_due = await _fleet_next_due(db, vins, vehicle_stats)

    return FleetHealth(
        overdue_count=overdue_count,
        upcoming_30d_count=upcoming_30d or 0,
        year=year,
        spent_this_year=spent_this_year,
        next_due=next_due,
    )


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Get complete dashboard with statistics for all vehicles.

    For authenticated users: Shows owned vehicles + shared vehicles.
    For none-mode (auth disabled): Shows all active vehicles (legacy behavior).
    A no-token request in local/oidc now 401s at the dependency rather than
    falling through to the all-vehicles branch (fail-open closed, R1-H1 class).
    Shows active vehicles + archived vehicles where archived_visible=True.
    """
    vehicle_stats = []

    if current_user and not current_user.is_admin:
        # Non-admin user: get owned vehicles
        owned_result = await db.execute(
            select(Vehicle).where(
                Vehicle.user_id == current_user.id,
                (Vehicle.archived_at.is_(None))
                | ((Vehicle.archived_at.isnot(None)) & (Vehicle.archived_visible.is_(True))),
            )
        )
        owned_vehicles = owned_result.scalars().all()

        # Get stats for owned vehicles
        for vehicle in owned_vehicles:
            stats = await calculate_vehicle_stats(db, vehicle)
            vehicle_stats.append(stats)

        # Get shared vehicles
        shared_result = await db.execute(
            select(VehicleShare, Vehicle, User)
            .join(Vehicle, VehicleShare.vehicle_vin == Vehicle.vin)
            .join(User, Vehicle.user_id == User.id)
            .where(
                VehicleShare.user_id == current_user.id,
                (Vehicle.archived_at.is_(None))
                | ((Vehicle.archived_at.isnot(None)) & (Vehicle.archived_visible.is_(True))),
            )
        )
        shared_rows = shared_result.all()

        # Get stats for shared vehicles
        for share, vehicle, owner in shared_rows:
            stats = await calculate_vehicle_stats(
                db,
                vehicle,
                is_shared_with_me=True,
                shared_by_username=owner.username,
                share_permission=share.permission,
            )
            vehicle_stats.append(stats)
    else:
        # Admin or unauthenticated: get all vehicles (legacy behavior)
        result = await db.execute(
            select(Vehicle).where(
                (Vehicle.archived_at.is_(None))
                | ((Vehicle.archived_at.isnot(None)) & (Vehicle.archived_visible.is_(True)))
            )
        )
        vehicles = result.scalars().all()

        # Calculate statistics for each vehicle
        for vehicle in vehicles:
            stats = await calculate_vehicle_stats(db, vehicle)
            vehicle_stats.append(stats)

    # Calculate garage-wide totals
    total_service = sum(v.total_service_records for v in vehicle_stats)
    total_fuel = sum(v.total_fuel_records for v in vehicle_stats)
    total_maintenance_items = sum(v.total_maintenance_items for v in vehicle_stats)
    total_documents = sum(v.total_documents for v in vehicle_stats)
    total_notes = sum(v.total_notes for v in vehicle_stats)
    total_photos = sum(v.total_photos for v in vehicle_stats)

    fleet_health = await calculate_fleet_health(db, vehicle_stats)

    return DashboardResponse(
        total_vehicles=len(vehicle_stats),
        vehicles=vehicle_stats,
        total_service_records=total_service,
        total_fuel_records=total_fuel,
        total_maintenance_items=total_maintenance_items,
        total_documents=total_documents,
        total_notes=total_notes,
        total_photos=total_photos,
        fleet_health=fleet_health,
    )
