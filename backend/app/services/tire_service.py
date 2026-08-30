"""Tire tracking business logic — readings, wear projection, reminder hooks."""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.reminder import Reminder
from app.models.tire import Tire, TireReading
from app.models.user import User
from app.schemas.tire import (
    TIRE_POSITIONS,
    TireCreate,
    TireListResponse,
    TireReadingCreate,
    TireReadingResponse,
    TireResponse,
    TireUpdate,
)
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


def _project_wear(
    readings: list[TireReading],
    min_tread: Decimal | None,
) -> tuple[Decimal | None, object | None]:
    """Estimate km remaining and wear date from the two most recent readings.

    Requires two readings with odometer and decreasing tread. Returns
    ``(projected_km_remaining, projected_wear_date)``.
    """
    if min_tread is None or len(readings) < 2:
        return None, None
    newer, older = readings[0], readings[1]
    if (
        newer.odometer_km is None
        or older.odometer_km is None
        or newer.tread_depth_mm is None
        or older.tread_depth_mm is None
    ):
        return None, None
    km_delta = newer.odometer_km - older.odometer_km
    tread_delta = older.tread_depth_mm - newer.tread_depth_mm
    if km_delta <= 0 or tread_delta <= 0:
        return None, None
    remaining_tread = newer.tread_depth_mm - min_tread
    if remaining_tread <= 0:
        return Decimal("0"), newer.recorded_at
    mm_per_km = tread_delta / km_delta
    km_left = remaining_tread / mm_per_km
    day_delta = (newer.recorded_at - older.recorded_at).days
    wear_date = None
    if day_delta > 0:
        km_per_day = km_delta / Decimal(day_delta)
        if km_per_day > 0:
            days_left = int(km_left / km_per_day)
            wear_date = newer.recorded_at + timedelta(days=max(days_left, 0))
    return km_left.quantize(Decimal("0.1")), wear_date


class TireService:
    """CRUD + wear projection + low-tread reminder hooks."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _to_response(self, tire: Tire, include_readings: bool = True) -> TireResponse:
        readings = sorted(
            list(tire.readings or []),
            key=lambda r: r.recorded_at,
            reverse=True,
        )
        km_left, wear_date = _project_wear(readings, tire.min_tread_mm)
        below = bool(
            tire.tread_depth_mm is not None
            and tire.min_tread_mm is not None
            and tire.tread_depth_mm <= tire.min_tread_mm
        )
        payload = TireResponse.model_validate(tire)
        payload.projected_km_remaining = km_left
        payload.projected_wear_date = wear_date
        payload.below_threshold = below
        if include_readings:
            payload.readings = [TireReadingResponse.model_validate(r) for r in readings]
        else:
            payload.readings = []
        return payload

    async def list_tires(self, vin: str, current_user: User) -> TireListResponse:
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        try:
            await get_vehicle_or_403(vin, current_user, self.db)
            result = await self.db.execute(
                select(Tire)
                .where(Tire.vin == vin)
                .options(selectinload(Tire.readings))
                .order_by(Tire.position)
            )
            tires = result.scalars().unique().all()
            responses = [self._to_response(t) for t in tires]
            return TireListResponse(tires=responses, total=len(responses))
        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "DB error listing tires for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def upsert_tire(self, vin: str, data: TireCreate, current_user: User) -> TireResponse:
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        if data.position not in TIRE_POSITIONS:
            raise HTTPException(status_code=400, detail="Invalid tire position")
        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            result = await self.db.execute(
                select(Tire)
                .where(Tire.vin == vin, Tire.position == data.position)
                .options(selectinload(Tire.readings))
            )
            tire = result.scalar_one_or_none()
            if tire is None:
                # Create: schema defaults are meaningful, so take the full model.
                tire = Tire(vin=vin, **data.model_dump(exclude={"vin"}))
                self.db.add(tire)
            else:
                # Update: only touch what the caller actually sent. A full
                # model_dump wrote every field including unset defaults, so
                # re-saving a position erased brand, model, size and DOT code
                # and reset the custom wear threshold.
                for key, value in data.model_dump(
                    exclude={"vin", "position"}, exclude_unset=True
                ).items():
                    setattr(tire, key, value)
            await self.db.commit()
            # Re-query rather than refresh(attribute_names=["readings"]).
            # updated_at is server-side onupdate=func.now(), so the flush leaves
            # it expired even with expire_on_commit=False; a partial refresh left
            # TireResponse to lazy-load it and the update path raised
            # MissingGreenlet -> 500 after the write had already committed.
            result = await self.db.execute(
                select(Tire).where(Tire.id == tire.id).options(selectinload(Tire.readings))
            )
            tire = result.scalar_one()
            await self._sync_low_tread_reminder(tire)
            return self._to_response(tire)
        except HTTPException:
            raise
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "DB error upserting tire for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_tire(
        self, vin: str, tire_id: int, data: TireUpdate, current_user: User
    ) -> TireResponse:
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            result = await self.db.execute(
                select(Tire)
                .where(Tire.id == tire_id, Tire.vin == vin)
                .options(selectinload(Tire.readings))
            )
            tire = result.scalar_one_or_none()
            if not tire:
                raise HTTPException(status_code=404, detail="Tire not found")
            for key, value in data.model_dump(exclude_unset=True).items():
                setattr(tire, key, value)
            await self.db.commit()
            await self.db.refresh(tire)
            await self._sync_low_tread_reminder(tire)
            return self._to_response(tire)
        except HTTPException:
            raise
        except OperationalError as e:
            await self.db.rollback()
            logger.error("DB error updating tire %s: %s", tire_id, sanitize_for_log(e))
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_tire(self, vin: str, tire_id: int, current_user: User) -> None:
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        result = await self.db.execute(select(Tire).where(Tire.id == tire_id, Tire.vin == vin))
        tire = result.scalar_one_or_none()
        if not tire:
            raise HTTPException(status_code=404, detail="Tire not found")
        await self.db.delete(tire)
        await self.db.commit()

    async def add_reading(
        self,
        vin: str,
        tire_id: int,
        data: TireReadingCreate,
        current_user: User,
    ) -> TireResponse:
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            result = await self.db.execute(
                select(Tire)
                .where(Tire.id == tire_id, Tire.vin == vin)
                .options(selectinload(Tire.readings))
            )
            tire = result.scalar_one_or_none()
            if not tire:
                raise HTTPException(status_code=404, detail="Tire not found")

            reading = TireReading(
                tire_id=tire.id,
                vin=vin,
                position=tire.position,
                recorded_at=data.recorded_at,
                odometer_km=data.odometer_km,
                tread_depth_mm=data.tread_depth_mm,
                pressure_kpa=data.pressure_kpa,
                notes=data.notes,
            )
            self.db.add(reading)
            # Only the newest observation defines current state. A backdated
            # backfill previously overwrote a worn tire's tread with an old
            # healthy value, recomputed below_threshold from it, and completed a
            # genuinely needed low-tread reminder.
            #
            # Deliberately NOT falling back to tire.updated_at when history is
            # empty: that column is onupdate=func.now(), so an unrelated edit
            # would bump it to today and silently refuse a reading dated
            # yesterday. The upsert-supplied tread carries no measurement date,
            # so the first dated reading wins. Closing that gap needs a
            # tread_measured_at column, which needs a migration.
            #
            # Each measurement is carried across only when the reading actually
            # supplies it. Tread used to be assigned unconditionally, which was
            # harmless only while the column was NOT NULL. Since 094 a
            # pressure-only reading (#152: a slow leak, no tread gauge) would
            # otherwise null the parent tire's tread, and an unknown tread is
            # not a measurement of a healthy one: `below_threshold` would drop
            # to False and `_sync_low_tread_reminder` would mark a live
            # low-tread reminder done. Logging a pressure would have silently
            # dismissed the warning that the tire is worn out.
            recorded_dates = [r.recorded_at for r in (tire.readings or [])]
            if not recorded_dates or data.recorded_at >= max(recorded_dates):
                if data.tread_depth_mm is not None:
                    tire.tread_depth_mm = data.tread_depth_mm
                if data.pressure_kpa is not None:
                    tire.pressure_kpa = data.pressure_kpa
            await self.db.commit()
            await self.db.refresh(tire)
            result = await self.db.execute(
                select(Tire).where(Tire.id == tire_id).options(selectinload(Tire.readings))
            )
            tire = result.scalar_one()
            await self._sync_low_tread_reminder(tire)
            return self._to_response(tire)
        except HTTPException:
            raise
        except OperationalError as e:
            await self.db.rollback()
            logger.error("DB error adding tire reading %s: %s", tire_id, sanitize_for_log(e))
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def _sync_low_tread_reminder(self, tire: Tire) -> None:
        """Create or complete a pending 'Tire tread low (POS)' reminder.

        Hooks into the existing ``vehicle_reminders`` table so the calendar,
        notifications scheduler, and HA bridge all see low tread without a
        separate notification channel.
        """
        title = f"Tire tread low ({tire.position})"
        # THREE states, not two. `not below` used to conflate "measured, and it
        # is fine" with "we do not know", which was safe only while a tread was
        # mandatory everywhere. It is not: `Tire.tread_depth_mm` has been
        # nullable since 085 (clear the field in the edit drawer and the upsert
        # writes an explicit null), and since 094 a reading may omit one too.
        # Only a MEASUREMENT above the threshold may complete a live safety
        # reminder; an unknown tread leaves it exactly as it was.
        #
        # `known` and `below` are derived in ONE branch rather than each
        # repeating the None checks: two copies of one predicate can drift
        # apart, and a `below` that outlives its `known` is precisely the defect
        # this code exists to prevent. A branch rather than
        # `known and tread <= limit` because pyright does not carry a
        # `is not None` narrowing through an intermediate flag.
        tread = tire.tread_depth_mm
        limit = tire.min_tread_mm
        if tread is None or limit is None:
            known = False
            below = False
        else:
            known = True
            below = tread <= limit
        result = await self.db.execute(
            select(Reminder).where(
                Reminder.vin == tire.vin,
                Reminder.title == title,
                Reminder.status == "pending",
            )
        )
        existing = result.scalar_one_or_none()

        if below and existing is None:
            due = utc_now().date()
            km_left, wear_date = _project_wear(list(tire.readings or []), tire.min_tread_mm)
            reminder = Reminder(
                vin=tire.vin,
                title=title,
                reminder_type="date" if wear_date is None else "both",
                due_date=wear_date or due,
                due_mileage_km=None,
                status="pending",
                notes=(
                    f"Tread {tire.tread_depth_mm} mm ≤ threshold {tire.min_tread_mm} mm."
                    + (f" ~{km_left} km remaining." if km_left is not None else "")
                ),
            )
            self.db.add(reminder)
            await self.db.commit()
        elif known and not below and existing is not None:
            existing.status = "done"
            await self.db.commit()
