"""Tire tracking business logic — readings, wear projection, reminder hooks."""

from __future__ import annotations

import datetime as dt
import logging
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.reminder import Reminder
from app.models.tire import Tire, TireMountPeriod, TireReading
from app.models.user import User
from app.schemas.tire import (
    MountPeriodResponse,
    TireCreate,
    TireCreateAndMountRequest,
    TireDismountRequest,
    TireListResponse,
    TireMountRequest,
    TireReadingCreate,
    TireReadingResponse,
    TireResponse,
    TireUpdate,
)
from app.services.tire_results import (
    DistanceResult,
    DistanceStatus,
    WearResult,
    WearStatus,
)
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


def distance_on_tire(tire: Tire, current_odometer: Decimal | None) -> DistanceResult:
    """Distance driven ON THIS TIRE, summed over its mount periods.

    This is the calculation the whole mount-period model exists for. The old
    one took the raw odometer delta between two readings, which for anyone
    running a second seasonal set counts the distance driven on the OTHER set.

    Args:
        tire: The tire, with `mount_periods` loaded.
        current_odometer: The vehicle's latest odometer reading, used as the
            upper bound of any period still open. None when the vehicle has no
            odometer record at all, which makes an open period unbounded.

    Returns:
        A `DistanceResult` whose `status` says why a figure is or is not
        available. Never a bare zero: "this tire has never rolled" and "this
        tire rolled zero kilometres" are different answers.
    """
    periods = list(tire.mount_periods or [])
    if not periods:
        return DistanceResult(status=DistanceStatus.NO_PERIODS)

    # A spare accrues nothing: it is in the trunk while the vehicle drives.
    rolling = [p for p in periods if p.position != "SPARE"]
    if not rolling:
        return DistanceResult(status=DistanceStatus.SPARE_ONLY)

    known = Decimal("0")
    earliest: dt.date | None = None
    contributed = 0
    blocking: list[int] = []

    for period in rolling:
        start = period.mounted_odometer_km
        end = (
            period.dismounted_odometer_km if period.dismounted_on is not None else current_odometer
        )
        if start is None or end is None:
            blocking.append(period.id)
            continue
        if end < start:
            return DistanceResult(
                status=DistanceStatus.ODOMETER_ROLLBACK,
                blocking_period_ids=[period.id],
            )
        known += end - start
        contributed += 1
        # Only a period that CONTRIBUTED can date the known figure, and its
        # `mounted_on` may still be null on a migrated assumed period.
        if period.mounted_on is not None:
            earliest = period.mounted_on if earliest is None else min(earliest, period.mounted_on)

    if contributed == 0:
        # Every migrated tire, on upgrade day. NOT `incomplete`: there is no
        # subtotal to show, and "0 km since an unknown date" is worse than
        # saying nothing.
        return DistanceResult(status=DistanceStatus.NOTHING_BOUNDED, blocking_period_ids=blocking)
    if blocking:
        return DistanceResult(
            status=DistanceStatus.INCOMPLETE,
            known_value=known,
            known_since=earliest,
            blocking_period_ids=blocking,
        )
    return DistanceResult(
        status=DistanceStatus.COMPLETE,
        all_time_value=known,
        known_value=known,
        known_since=earliest,
    )


def project_wear(
    tire: Tire,
    current_odometer: Decimal | None,
    readings: list[TireReading] | None = None,
) -> WearResult:
    """Estimate remaining tread life, with the reason when there is none.

    Two changes from the pre-v3.3.0 `_project_wear`, both of which were
    producing wrong or missing numbers in production:

    1. It is **period-aware**. The old one used the raw odometer delta between
       the two readings as distance driven on this tire. That is only correct
       for someone who has never had a second set, and it errs HIGH -- the
       dangerous direction. Where the mount history cannot support the figure
       it is now withheld (`UNVERIFIED_MOUNT_HISTORY`) rather than published
       with an "estimate" badge.

    2. It **sorts its own readings**. `_sync_low_tread_reminder` passed them
       unsorted, so `readings[0]` was the OLDEST, `tread_delta` came out
       negative, and the low-tread projection has been silently missing from
       every reminder. Selection moved inside so this surface and the reminder
       quote the same number by construction.

    Args:
        tire: The tire, with `mount_periods` loaded.
        current_odometer: The vehicle's latest odometer, for open periods.
        readings: Override for the reading list; defaults to the tire's own.
            Passed in by callers that already loaded them.

    Returns:
        A `WearResult`. Its `status` is exhaustive: every current null exit of
        the old function maps to a named member, so a caller can say WHICH
        input is missing instead of rendering one message for five states.
    """
    candidates = sorted(
        [r for r in (readings if readings is not None else tire.readings or [])],
        key=lambda r: r.recorded_at,
        reverse=True,
    )
    min_tread = tire.min_tread_mm

    if min_tread is None:
        # No 2.0 fallback: the 2.0 is a COLUMN default applied at insert, not
        # to a row that already holds null.
        return WearResult(status=WearStatus.NO_MINIMUM_SET)

    with_tread = [r for r in candidates if r.tread_depth_mm is not None]
    if len(with_tread) < 2:
        return WearResult(status=WearStatus.INSUFFICIENT_READINGS)

    newer, older = with_tread[0], with_tread[1]
    if newer.odometer_km is None or older.odometer_km is None:
        return WearResult(status=WearStatus.NO_READING_ODOMETERS)

    newer_tread, older_tread = newer.tread_depth_mm, older.tread_depth_mm
    if newer_tread is None or older_tread is None:  # pragma: no cover - filtered above
        return WearResult(status=WearStatus.INSUFFICIENT_READINGS)

    tread_delta = older_tread - newer_tread
    if tread_delta <= 0:
        # Flat or increasing tread. Distinct from "you have not driven on this
        # tire": the prompts differ, and the old code could not tell a caller
        # which of the two had happened.
        return WearResult(status=WearStatus.TREAD_NOT_DECREASING)

    # The distance is the tire's own, not the vehicle's odometer span.
    distance = distance_on_tire(tire, current_odometer)
    if distance.status is DistanceStatus.COMPLETE:
        km_delta = newer.odometer_km - older.odometer_km
    elif distance.status is DistanceStatus.NOTHING_BOUNDED:
        # The migrated shape. The raw delta is exactly the legacy calculation
        # this release exists to stop publishing.
        return WearResult(
            status=WearStatus.UNVERIFIED_MOUNT_HISTORY,
            blocking_period_ids=distance.blocking_period_ids,
        )
    else:
        return WearResult(
            status=WearStatus.NO_DISTANCE_ON_TIRE,
            blocking_period_ids=distance.blocking_period_ids,
        )

    if km_delta <= 0:
        return WearResult(status=WearStatus.NO_DISTANCE_ON_TIRE)

    remaining_tread = newer_tread - min_tread
    if remaining_tread <= 0:
        # At or past the threshold. This is the SAFETY case: it carries a
        # number and a date, and the reminder fires on it.
        return WearResult(
            status=WearStatus.AT_OR_BELOW_MINIMUM,
            km_remaining=Decimal("0"),
            wear_date=newer.recorded_at,
        )

    mm_per_km = tread_delta / km_delta
    km_left = remaining_tread / mm_per_km
    day_delta = (newer.recorded_at - older.recorded_at).days
    wear_date = None
    if day_delta > 0:
        km_per_day = km_delta / Decimal(day_delta)
        if km_per_day > 0:
            days_left = int(km_left / km_per_day)
            wear_date = newer.recorded_at + timedelta(days=max(days_left, 0))
    # `wear_date` stays None for same-day readings: the km figure is still
    # valid, so status is PROJECTED and the date is simply unavailable.
    return WearResult(
        status=WearStatus.PROJECTED,
        km_remaining=km_left.quantize(Decimal("0.1")),
        wear_date=wear_date,
    )


class TireService:
    """CRUD + wear projection + low-tread reminder hooks."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _current_odometer(self, vin: str) -> Decimal | None:
        """The vehicle's latest odometer reading, in canonical km.

        Used as the upper bound for any mount period still open. There is no
        odometer column on `Vehicle` -- it is a relationship -- so this is a
        query, and it legitimately returns None for a vehicle that has never
        had a reading. That is its own empty state, not a zero: every open
        period on such a vehicle is unbounded.
        """
        from app.models.odometer import OdometerRecord

        result = await self.db.execute(
            select(OdometerRecord.odometer_km)
            .where(OdometerRecord.vin == vin)
            .order_by(OdometerRecord.date.desc(), OdometerRecord.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _derived_installed_date(tire: Tire) -> dt.date | None:
        """The `mounted_on` of the earliest period THAT HAS ONE.

        Null when the earliest period is the migrated assumed one with an
        unknown start. Deliberately not `MIN(mounted_on)` over the non-null
        values only: that would skip the unknown and report a later REMOUNT
        date as the installation date, which reads as fact and is wrong.
        """
        periods = sorted(
            tire.mount_periods or [], key=lambda mp: (mp.mounted_on or dt.date.min, mp.id)
        )
        if not periods:
            return None
        return periods[0].mounted_on

    def _to_response(
        self,
        tire: Tire,
        include_readings: bool = True,
        current_odometer: Decimal | None = None,
    ) -> TireResponse:
        readings = sorted(
            list(tire.readings or []),
            key=lambda r: r.recorded_at,
            reverse=True,
        )
        wear = project_wear(tire, current_odometer, readings)
        distance = distance_on_tire(tire, current_odometer)
        below = bool(
            tire.tread_depth_mm is not None
            and tire.min_tread_mm is not None
            and tire.tread_depth_mm <= tire.min_tread_mm
        )
        payload = TireResponse.model_validate(tire)
        # Same wire names as before v3.3.0. A single-value result type would
        # have silently dropped `projected_wear_date`, which the tire card
        # renders beside the km figure.
        payload.projected_km_remaining = wear.km_remaining
        payload.projected_wear_date = wear.wear_date
        payload.wear_status = wear.status.value
        payload.distance_km = distance.all_time_value
        payload.known_distance_km = distance.known_value
        payload.known_distance_since = distance.known_since
        payload.distance_status = distance.status.value
        # Whichever result is blocked names the periods to act on. Distance
        # wins when both are: it is the more specific repair.
        payload.blocking_period_ids = distance.blocking_period_ids or wear.blocking_period_ids
        payload.installed_date = self._derived_installed_date(tire)
        payload.below_threshold = below
        payload.mount_periods = [
            MountPeriodResponse.model_validate(period)
            for period in sorted(
                tire.mount_periods or [], key=lambda mp: (mp.mounted_on or dt.date.min, mp.id)
            )
        ]
        if include_readings:
            payload.readings = [TireReadingResponse.model_validate(r) for r in readings]
        else:
            payload.readings = []
        return payload

    async def list_tires(
        self, vin: str, current_user: User, include_retired: bool = False
    ) -> TireListResponse:
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        try:
            await get_vehicle_or_403(vin, current_user, self.db)
            query = select(Tire).where(Tire.vin == vin)
            if not include_retired:
                # A retired tire is history, not inventory. It still appears in
                # analytics -- its final distance and wear are the most
                # complete data the app will ever have about it -- but it does
                # not belong in the list of tires you can act on.
                query = query.where(Tire.retired_on.is_(None))
            result = await self.db.execute(
                query.options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
                # Mounted tires first, then stored ones. `position` is
                # nullable now, and a bare ORDER BY sorts NULLs FIRST on
                # SQLite and LAST on PostgreSQL, so the two dialects would
                # disagree about the order of a user's own tire list.
                .order_by(Tire.position.is_(None), Tire.position)
            )
            tires = result.scalars().unique().all()
            current_odometer = await self._current_odometer(vin)
            responses = [self._to_response(t, current_odometer=current_odometer) for t in tires]
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

    async def create_tire(self, vin: str, data: TireCreate, current_user: User) -> TireResponse:
        """Create a tire. It is NOT mounted anywhere until you mount it.

        This replaced `upsert_tire`, and the change is the release's breaking
        one. Before v3.3.0 a tire WAS a corner: `POST /api/tires` carried a
        `position` and upserted by `(vin, position)`, so there was no way to
        own a tire that was off the vehicle -- a seasonal set had to be deleted
        and re-entered every six months, taking its readings with it.

        A tire is now a thing you own. Mounting is a separate operation with
        its own conflict semantics (that corner may be occupied), which is why
        it cannot be folded back into a create.

        A stale client still sending `position` gets a 422 naming the field,
        because `TireBase` forbids extras (D13). Pydantic's default is to
        ignore unknown fields, which here would silently create a SECOND,
        unmounted tire rather than updating the one at that corner.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            tire = Tire(vin=vin, **data.model_dump(exclude={"vin"}))
            self.db.add(tire)
            await self.db.commit()
            # Re-query rather than refresh(attribute_names=["readings"]).
            # updated_at is server-side onupdate=func.now(), so the flush leaves
            # it expired even with expire_on_commit=False; a partial refresh left
            # TireResponse to lazy-load it and the update path raised
            # MissingGreenlet -> 500 after the write had already committed.
            result = await self.db.execute(
                select(Tire)
                .where(Tire.id == tire.id)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
            tire = result.scalar_one()
            return await self._reload_and_sync(tire.id, vin)
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

    async def mount_tire(
        self, vin: str, tire_id: int, data: TireMountRequest, current_user: User
    ) -> TireResponse:
        """Mount a tire at a position, opening a mount period.

        **This is the only writer of `tires.position`** (D14), together with
        `dismount_tire`. Both representations -- the tire's current position
        and the open period's position -- are written here or neither is, so
        they cannot drift. An earlier design let a period's position be edited
        directly, which let the tire card and the reading history disagree
        about which corner a tire was on.

        Nothing at the database level prevents two tires on one vehicle from
        each holding an open period at FL: `tire_mount_periods` has no `vin`,
        so the constraint cannot be written there. It is enforced here, under
        the parent-tire row lock, and it has its own test because no index
        will catch it.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        tire = await self._get_tire_for_update(vin, tire_id)

        if tire.position is not None:
            raise HTTPException(
                status_code=409,
                detail=f"This tire is already mounted at {tire.position}. Dismount it first.",
            )

        occupant = (
            await self.db.execute(
                select(Tire).where(
                    Tire.vin == vin,
                    Tire.position == data.position,
                    Tire.id != tire.id,
                )
            )
        ).scalar_one_or_none()
        if occupant is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Another tire is already mounted at {data.position}.",
            )

        tire.position = data.position
        self.db.add(
            TireMountPeriod(
                tire_id=tire.id,
                position=data.position,
                mounted_on=data.mounted_on or utc_now().date(),
                mounted_odometer_km=data.mounted_odometer_km,
                is_assumed=False,
                notes=data.notes,
            )
        )
        await self.db.commit()
        # The reminder title names the position, so mounting changes it.
        return await self._reload_and_sync(tire.id, vin)

    async def dismount_tire(
        self, vin: str, tire_id: int, data: TireDismountRequest, current_user: User
    ) -> TireResponse:
        """Take a tire off the vehicle, closing its open period."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        tire = await self._get_tire_for_update(vin, tire_id)

        if tire.position is None:
            raise HTTPException(status_code=409, detail="This tire is not mounted.")

        open_period = (
            await self.db.execute(
                select(TireMountPeriod)
                .where(
                    TireMountPeriod.tire_id == tire.id,
                    TireMountPeriod.dismounted_on.is_(None),
                )
                .order_by(TireMountPeriod.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        tire.position = None
        if open_period is not None:
            open_period.dismounted_on = data.dismounted_on or utc_now().date()
            open_period.dismounted_odometer_km = data.dismounted_odometer_km
            if data.notes:
                open_period.notes = data.notes
        await self.db.commit()
        return await self._reload_response(tire.id, vin)

    async def create_and_mount(
        self, vin: str, data: TireCreateAndMountRequest, current_user: User
    ) -> TireResponse:
        """Create a tire and mount it, atomically.

        The conflict semantics are the MOUNT's: if the corner is occupied the
        whole operation fails and no tire is created. Doing the two calls by
        hand and losing the second would leave an orphan tire behind.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

        occupant = (
            await self.db.execute(
                select(Tire).where(Tire.vin == vin, Tire.position == data.position)
            )
        ).scalar_one_or_none()
        if occupant is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Another tire is already mounted at {data.position}.",
            )

        tire = Tire(
            vin=vin,
            position=data.position,
            **data.model_dump(exclude={"vin", "position", "mounted_on", "mounted_odometer_km"}),
        )
        self.db.add(tire)
        await self.db.flush()
        self.db.add(
            TireMountPeriod(
                tire_id=tire.id,
                position=data.position,
                mounted_on=data.mounted_on or utc_now().date(),
                mounted_odometer_km=data.mounted_odometer_km,
                is_assumed=False,
            )
        )
        await self.db.commit()
        return await self._reload_and_sync(tire.id, vin)

    async def _get_tire_for_update(self, vin: str, tire_id: int) -> Tire:
        """Load a tire, scoped to its vehicle, or 404."""
        tire = (
            await self.db.execute(
                select(Tire)
                .where(Tire.id == tire_id, Tire.vin == vin)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
        ).scalar_one_or_none()
        if tire is None:
            raise HTTPException(status_code=404, detail="Tire not found")
        return tire

    async def _reload_and_sync(self, tire_id: int, vin: str) -> TireResponse:
        """Reload, run the low-tread reminder sync, and serialise.

        The sync has to happen on every path that can change a tire's tread or
        its mounted state, not only on the reading path. A tire entered with a
        tread already below its threshold is exactly the case a user needs
        warned about, and the previous `upsert_tire` did sync it -- so the
        create/mount split had to carry that behaviour across rather than drop
        it silently.
        """
        tire = (
            await self.db.execute(
                select(Tire)
                .where(Tire.id == tire_id)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
        ).scalar_one()
        await self._sync_low_tread_reminder(tire)
        return await self._reload_response(tire_id, vin)

    async def _reload_response(self, tire_id: int, vin: str) -> TireResponse:
        """Re-query and serialise.

        Re-queried rather than refreshed: `updated_at` is a server-side
        onupdate, so a flush leaves it expired even with
        expire_on_commit=False, and a partial refresh left TireResponse to
        lazy-load it -- MissingGreenlet, a 500 after the write had committed.
        """
        tire = (
            await self.db.execute(
                select(Tire)
                .where(Tire.id == tire_id)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
        ).scalar_one()
        return self._to_response(tire, current_odometer=await self._current_odometer(vin))

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
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
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

    async def retire_tire(
        self, vin: str, tire_id: int, data: TireDismountRequest, current_user: User
    ) -> TireResponse:
        """Retire a tire: it comes off the vehicle and keeps everything.

        This is what a user means by "I replaced this tire", and before v3.3.0
        the only way to express it was DELETE -- which cascades through every
        reading and every mount period. Shipping the mount-period model beside
        an unchanged delete would mean the first thing someone does after
        collecting a season of data is erase it.

        Delete still exists, for a tire entered by mistake.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        tire = await self._get_tire_for_update(vin, tire_id)

        if tire.retired_on is not None:
            raise HTTPException(status_code=409, detail="This tire is already retired.")

        if tire.position is not None:
            # Close the open period and free the corner, so the replacement can
            # go where the old one was.
            open_period = (
                await self.db.execute(
                    select(TireMountPeriod)
                    .where(
                        TireMountPeriod.tire_id == tire.id,
                        TireMountPeriod.dismounted_on.is_(None),
                    )
                    .order_by(TireMountPeriod.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if open_period is not None:
                open_period.dismounted_on = data.dismounted_on or utc_now().date()
                open_period.dismounted_odometer_km = data.dismounted_odometer_km
            tire.position = None

        tire.retired_on = data.dismounted_on or utc_now().date()
        await self.db.commit()
        return await self._reload_response(tire.id, vin)

    async def delete_tire(self, vin: str, tire_id: int, current_user: User) -> None:
        """Permanently delete a tire and everything measured about it.

        For a tire entered by mistake. To replace a worn tire, RETIRE it: this
        cascades through `tire_readings` and `tire_mount_periods`.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        result = await self.db.execute(select(Tire).where(Tire.id == tire_id, Tire.vin == vin))
        tire = result.scalar_one_or_none()
        if not tire:
            raise HTTPException(status_code=404, detail="Tire not found")

        # Detach the reminders first, in the same transaction as the delete.
        # The composite FK `(tire_id, vin) -> tires(id, vin)` carries NO
        # ON DELETE action: a referential action applies to every column in the
        # FK, so SET NULL would try to null `vin` as well -- and `vin` is NOT
        # NULL, which makes SQLite reject the delete outright and retiring a
        # tire impossible. Measured. Nulling `tire_id` here keeps the reminder
        # as history and makes it inert: the sync never adopts a row whose
        # `tire_id` is null.
        await self.db.execute(
            update(Reminder)
            .where(Reminder.tire_id == tire_id, Reminder.vin == vin)
            .values(tire_id=None, source=None)
        )
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
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
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
                select(Tire)
                .where(Tire.id == tire_id)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
            tire = result.scalar_one()
            return await self._reload_and_sync(tire.id, vin)
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
            # `project_wear` sorts its own readings now. The old call passed
            # them unsorted, so `newer` was the OLDEST reading, `tread_delta`
            # came out negative, and this projection has been silently absent
            # from every low-tread reminder ever raised.
            wear = project_wear(tire, await self._current_odometer(tire.vin))
            km_left, wear_date = wear.km_remaining, wear.wear_date
            reminder = Reminder(
                vin=tire.vin,
                # Which tire, and that WE made this. The sync never adopts a
                # row whose `source` or `tire_id` is null, so a reminder a
                # human wrote with the same title is left alone, and a reminder
                # whose tire has been deleted becomes inert rather than
                # attaching itself to the next tire at that corner.
                tire_id=tire.id,
                source="low_tread",
                tread_depth_mm=tire.tread_depth_mm,
                tread_threshold_mm=tire.min_tread_mm,
                projected_distance_km=km_left,
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
