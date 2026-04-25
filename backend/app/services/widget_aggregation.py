"""Aggregation queries that back /api/widget/* endpoints.

Built deliberately separate from `routes/dashboard.py` / `calculate_vehicle_stats`,
which performs many serial queries plus a filesystem scan per vehicle — fine for
an interactive dashboard load, wasteful when homepage polls every 60 seconds.

Design rules:

1. **No fan-out joins.** Joining `service_visits + fuel_records + documents +
   notes + photos + vehicle_reminders` in one query would multiply COUNT/MAX
   values via the classic aggregate-fan-out bug. Each child table gets its own
   indexed, scoped query instead.
2. **Request-time ownership filter.** `allowed_vins` on the key is a filter
   only; every lookup re-derives the VIN set from current `vehicles.user_id`
   ownership so transfer/archive changes invalidate access immediately.
3. **MPG parity with `calculate_mpg`.** Recent = last 3 full-tank fill-ups,
   average bounded to last 10. Fetched via a single indexed query; pairwise
   MPG is computed in Python for portability and to mirror the existing
   `calculate_mpg` guards exactly.
"""

# pyright: reportAssignmentType=false, reportAttributeAccessIssue=false

from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.fuel import FuelRecord
from app.models.note import Note
from app.models.odometer import OdometerRecord
from app.models.photo import VehiclePhoto
from app.models.reminder import Reminder
from app.models.service_visit import ServiceVisit
from app.models.vehicle import Vehicle
from app.schemas.widget import (
    WidgetSummary,
    WidgetVehicle,
    WidgetVehicleRef,
)
from app.utils.units import UnitConverter

RECENT_MPG_WINDOW = 3
AVERAGE_MPG_WINDOW = 10


def _vehicle_label(vehicle: Vehicle) -> str:
    """Human-readable label (falls back to VIN if year/make/model missing)."""
    parts = [str(vehicle.year)] if vehicle.year else []
    if vehicle.make:
        parts.append(vehicle.make)
    if vehicle.model:
        parts.append(vehicle.model)
    return " ".join(parts) if parts else vehicle.vin


def _visible_vehicle_filter():
    """Visibility predicate matching dashboard UI: active OR archived-but-visible.

    Archived vehicles with `archived_visible=False` are hidden from the user's
    dashboard ([routes/dashboard.py:204-208]); widgets follow the same rule so
    polled data mirrors what the user actually sees.
    """
    return or_(Vehicle.archived_at.is_(None), Vehicle.archived_visible.is_(True))


class WidgetAggregationService:
    """SQL-first widget data access scoped to a single user."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------------------------
    # Ownership scoping
    # -------------------------------------------------------------------------

    async def _effective_vins(self, user_id: int, allowed_vins: list[str] | None) -> list[str]:
        """Currently-owned, user-visible VINs the key is allowed to see.

        Re-derived per request so ownership transfers and archive visibility
        changes invalidate access without any key-side bookkeeping. Archived
        vehicles with `archived_visible=False` are excluded to match the
        dashboard UI's filter.
        """
        stmt = (
            select(Vehicle.vin).where(Vehicle.user_id == user_id).where(_visible_vehicle_filter())
        )
        if allowed_vins is not None:
            stmt = stmt.where(Vehicle.vin.in_(allowed_vins))
        return list((await self.db.execute(stmt)).scalars().all())

    # -------------------------------------------------------------------------
    # Summary (garage-wide)
    # -------------------------------------------------------------------------

    async def summary(self, user_id: int, allowed_vins: list[str] | None) -> WidgetSummary:
        """Return aggregate counts across all vehicles the key can see."""
        # archived_vehicles counts only archived-but-visible rows; hidden
        # archives are not part of the user's garage view so they don't count.
        vehicles_stmt = (
            select(
                func.count().label("total"),
                func.sum(case((Vehicle.archived_at.is_(None), 1), else_=0)).label("active"),
                func.sum(case((Vehicle.archived_at.is_not(None), 1), else_=0)).label("archived"),
            )
            .where(Vehicle.user_id == user_id)
            .where(_visible_vehicle_filter())
        )
        if allowed_vins is not None:
            vehicles_stmt = vehicles_stmt.where(Vehicle.vin.in_(allowed_vins))
        row = (await self.db.execute(vehicles_stmt)).one()
        total_vehicles = int(row.total or 0)
        active_vehicles = int(row.active or 0)
        archived_vehicles = int(row.archived or 0)

        vins = await self._effective_vins(user_id, allowed_vins)
        if not vins:
            return WidgetSummary(
                total_vehicles=total_vehicles,
                active_vehicles=active_vehicles,
                archived_vehicles=archived_vehicles,
                total_overdue_maintenance=0,
                total_upcoming_maintenance=0,
                total_service_records=0,
                total_fuel_records=0,
                total_documents=0,
                total_notes=0,
                total_photos=0,
            )

        total_service = await self._scalar_count(ServiceVisit.vin, vins)
        total_fuel = await self._scalar_count(FuelRecord.vin, vins)
        total_documents = await self._scalar_count(Document.vin, vins)
        total_notes = await self._scalar_count(Note.vin, vins)
        total_photos = await self._scalar_count(VehiclePhoto.vin, vins)
        overdue, upcoming = await self._reminder_totals(vins)

        return WidgetSummary(
            total_vehicles=total_vehicles,
            active_vehicles=active_vehicles,
            archived_vehicles=archived_vehicles,
            total_overdue_maintenance=overdue,
            total_upcoming_maintenance=upcoming,
            total_service_records=total_service,
            total_fuel_records=total_fuel,
            total_documents=total_documents,
            total_notes=total_notes,
            total_photos=total_photos,
        )

    # -------------------------------------------------------------------------
    # Vehicle list (discovery)
    # -------------------------------------------------------------------------

    async def list_vehicles(
        self, user_id: int, allowed_vins: list[str] | None
    ) -> list[WidgetVehicleRef]:
        """Minimal VIN + label list for UI discovery.

        Excludes archived vehicles with `archived_visible=False`.
        """
        stmt = select(Vehicle).where(Vehicle.user_id == user_id).where(_visible_vehicle_filter())
        if allowed_vins is not None:
            stmt = stmt.where(Vehicle.vin.in_(allowed_vins))
        vehicles = (await self.db.execute(stmt)).scalars().all()
        return [WidgetVehicleRef(vin=v.vin, label=_vehicle_label(v)) for v in vehicles]

    # -------------------------------------------------------------------------
    # Single vehicle
    # -------------------------------------------------------------------------

    async def vehicle(
        self, user_id: int, vin: str, allowed_vins: list[str] | None
    ) -> WidgetVehicle | None:
        """Per-vehicle rollup. Returns None if VIN is not owned/allowed.

        The route maps None → 404 (not 403) to avoid confirming existence.
        """
        stmt = (
            select(Vehicle)
            .where(Vehicle.vin == vin, Vehicle.user_id == user_id)
            .where(_visible_vehicle_filter())
        )
        if allowed_vins is not None:
            stmt = stmt.where(Vehicle.vin.in_(allowed_vins))
        vehicle = (await self.db.execute(stmt)).scalar_one_or_none()
        if vehicle is None:
            return None

        service_count, last_service_date = await self._count_and_latest(
            ServiceVisit.vin, ServiceVisit.date, vin
        )
        fuel_count, last_fuel_date = await self._count_and_latest(
            FuelRecord.vin, FuelRecord.date, vin
        )
        documents = await self._scalar_count(Document.vin, [vin])
        notes = await self._scalar_count(Note.vin, [vin])
        photos = await self._scalar_count(VehiclePhoto.vin, [vin])

        odometer, odometer_date = await self._latest_odometer(vin)
        recent_mpg, average_mpg = await self._mpg(vin)
        overdue, upcoming = await self._reminder_counts(vin)

        return WidgetVehicle(
            label=_vehicle_label(vehicle),
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            odometer=odometer,
            odometer_date=odometer_date,
            recent_mpg=recent_mpg,
            average_mpg=average_mpg,
            upcoming_maintenance=upcoming,
            overdue_maintenance=overdue,
            service_records=service_count,
            fuel_records=fuel_count,
            last_service_date=last_service_date,
            last_fuel_date=last_fuel_date,
            documents=documents,
            notes=notes,
            photos=photos,
        )

    # -------------------------------------------------------------------------
    # Internal query helpers (each hits a single indexed path)
    # -------------------------------------------------------------------------

    async def _scalar_count(self, column, vins: list[str]) -> int:
        if not vins:
            return 0
        stmt = select(func.count()).where(column.in_(vins))
        return int((await self.db.execute(stmt)).scalar_one() or 0)

    async def _count_and_latest(self, vin_col, date_col, vin: str) -> tuple[int, date_type | None]:
        stmt = select(func.count(), func.max(date_col)).where(vin_col == vin)
        count, latest = (await self.db.execute(stmt)).one()
        return int(count or 0), latest

    async def _latest_odometer(self, vin: str) -> tuple[int | None, date_type | None]:
        """Return latest odometer reading for `vin` as imperial miles + date.

        LEGACY-COMPAT: storage column is now `odometer_km` (Decimal). The widget
        endpoints predate v3 and must keep returning miles to avoid breaking
        pre-v3 dashboard clients. We convert at the read boundary.
        """
        stmt = (
            select(OdometerRecord.odometer_km, OdometerRecord.date)
            .where(OdometerRecord.vin == vin)
            .order_by(OdometerRecord.date.desc(), OdometerRecord.id.desc())
            .limit(1)
        )
        row = (await self.db.execute(stmt)).first()
        if row is None:
            return None, None
        miles = UnitConverter.km_to_miles(row.odometer_km)
        return (int(round(miles)) if miles is not None else None), row.date

    async def _latest_odometer_km(self, vin: str) -> int | None:
        """Internal: latest odometer reading for `vin` in km (for SQL comparisons)."""
        stmt = (
            select(OdometerRecord.odometer_km)
            .where(OdometerRecord.vin == vin)
            .order_by(OdometerRecord.date.desc(), OdometerRecord.id.desc())
            .limit(1)
        )
        row = (await self.db.execute(stmt)).first()
        if row is None or row.odometer_km is None:
            return None
        return int(row.odometer_km)

    async def _reminder_counts(self, vin: str) -> tuple[int, int]:
        """Return (overdue, upcoming) for a single VIN."""
        current_odometer_km = await self._latest_odometer_km(vin)
        overdue, upcoming = await self._overdue_upcoming([vin], current_odometer_km)
        return overdue, upcoming

    async def _reminder_totals(self, vins: list[str]) -> tuple[int, int]:
        """Sum overdue and upcoming pending reminders across `vins`.

        Overdue derivation per reminder:
          (due_date <= today) OR (due_mileage_km <= latest odometer_km for that VIN)
        Each VIN's current odometer_km comes from a separate latest-odometer query;
        the reminder query then filters with a per-VIN comparison.
        """
        if not vins:
            return 0, 0

        # Per-VIN latest odometer_km for mileage-based overdue checks.
        odometer_by_vin: dict[str, int] = {}
        for vin in vins:
            current_km = await self._latest_odometer_km(vin)
            if current_km is not None:
                odometer_by_vin[vin] = current_km

        overdue_total = 0
        upcoming_total = 0
        for vin in vins:
            current_odometer_km = odometer_by_vin.get(vin)
            overdue, upcoming = await self._overdue_upcoming([vin], current_odometer_km)
            overdue_total += overdue
            upcoming_total += upcoming
        return overdue_total, upcoming_total

    async def _overdue_upcoming(
        self, vins: list[str], current_odometer_km: int | None
    ) -> tuple[int, int]:
        """Classify pending reminders for the given VIN(s).

        A reminder counts as overdue when either its due_date is on or before
        today, or its due_mileage_km is at or below the vehicle's current
        odometer_km. Everything else pending counts as upcoming. Matches the
        Python derivation in `routes/dashboard.py`.
        """
        if not vins:
            return 0, 0
        today = date_type.today()
        stmt = select(Reminder.due_date, Reminder.due_mileage_km).where(
            Reminder.vin.in_(vins), Reminder.status == "pending"
        )
        rows = (await self.db.execute(stmt)).all()
        overdue = 0
        upcoming = 0
        for due_date, due_mileage_km in rows:
            is_overdue = False
            if due_date is not None and due_date <= today:
                is_overdue = True
            if (
                due_mileage_km is not None
                and current_odometer_km is not None
                and current_odometer_km >= due_mileage_km
            ):
                is_overdue = True
            if is_overdue:
                overdue += 1
            else:
                upcoming += 1
        return overdue, upcoming

    async def _mpg(self, vin: str) -> tuple[float | None, float | None]:
        """Return (recent_mpg, average_mpg) bounded to last 10 full-tank fill-ups.

        LEGACY-COMPAT: source columns are now `odometer_km` and `liters`. Per-pair
        consumption is computed in metric (L/100km) and converted to MPG only at
        the response boundary so the legacy widget keys continue to read in MPG.

        Behavioral parity with `fuel_service.calculate_mpg` +
        `get_previous_full_tank`:
          - Only consecutive full-tank records count
          - Needs prior odometer_km and liters > 0
          - Skip pairs where distance <= 0
        We fetch 11 rows (one more than AVERAGE_MPG_WINDOW) so we can form up
        to 10 consecutive pairs.
        """
        fetch_limit = AVERAGE_MPG_WINDOW + 1
        stmt = (
            select(FuelRecord.odometer_km, FuelRecord.liters, FuelRecord.date)
            .where(
                FuelRecord.vin == vin,
                FuelRecord.is_full_tank.is_(True),
                FuelRecord.odometer_km.is_not(None),
            )
            .order_by(FuelRecord.date.desc(), FuelRecord.id.desc())
            .limit(fetch_limit)
        )
        rows = (await self.db.execute(stmt)).all()
        # rows[0] is newest. Pair i uses rows[i] (current) and rows[i+1] (prev full tank).
        pair_l100km: list[Decimal] = []
        for i in range(len(rows) - 1):
            cur_km, cur_liters, _ = rows[i]
            prev_km, _, _ = rows[i + 1]
            if cur_liters is None or cur_km is None or prev_km is None:
                continue
            if cur_liters <= 0:
                continue
            distance_km = cur_km - prev_km
            if distance_km <= 0:
                continue
            # liters per 100 km
            pair_l100km.append((cur_liters / Decimal(str(distance_km))) * Decimal("100"))

        if not pair_l100km:
            return None, None

        recent_slice = pair_l100km[:RECENT_MPG_WINDOW]
        average_slice = pair_l100km[:AVERAGE_MPG_WINDOW]
        recent_l100km = sum(recent_slice) / len(recent_slice)
        average_l100km = sum(average_slice) / len(average_slice)

        recent_mpg = UnitConverter.l100km_to_mpg(recent_l100km)
        average_mpg = UnitConverter.l100km_to_mpg(average_l100km)
        recent = float(round(Decimal(str(recent_mpg)), 2)) if recent_mpg is not None else None
        average = float(round(Decimal(str(average_mpg)), 2)) if average_mpg is not None else None
        return recent, average
