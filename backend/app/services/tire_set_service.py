"""Tire sets: naming a group of tires, and fitting it in one action.

D6 of the mount-period design says sets are UX grouping only, and this module
holds that line: nothing here computes distance, wear or position history.
`tire_mount_periods` remains the single source for all three, and a set is a
label plus one convenience operation.

The convenience is the whole point, though. Swapping a seasonal set by hand is
eight operations -- four dismounts and four mounts -- each carrying an odometer
the user has to retype, and each of which can be got wrong independently. Here
it is one call with one odometer.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tire import Tire, TireSet
from app.models.user import User
from app.schemas.tire import (
    TireListResponse,
    TireSetCreate,
    TireSetListResponse,
    TireSetMountRequest,
    TireSetResponse,
    TireSetUpdate,
)
from app.services.tire_service import (
    ODOMETER_SOURCE_SET,
    TireService,
    apply_mount_moves,
)
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_sync import sync_odometer_from_record

logger = logging.getLogger(__name__)


def remembered_position(tire: Tire) -> str | None:
    """The corner this tire was last on, or None if it has never been fitted.

    This is what makes a seasonal swap one action rather than a form: the
    periods already record where each tire sat, so asking the user again would
    be asking them to retype something the app knows.

    Read from the HIGHEST-id period rather than the latest `mounted_on`.
    Periods are append-only, so the highest id is the most recently RECORDED
    one, and a user entering last winter's history after the fact must not have
    that backfill outrank the mount they did this morning.

    Returns None for a tire with no periods at all -- a set entered straight
    into storage and never fitted. That is a refusal, not a corner to guess.
    """
    if tire.position is not None:
        return tire.position
    periods = list(tire.mount_periods or [])
    if not periods:
        return None
    return max(periods, key=lambda period: period.id).position


def _describe(tire: Tire) -> str:
    """Name a tire in an error a user has to act on.

    The brand is what is printed on the sidewall and on the card; the id is a
    fallback for a tire entered with nothing but a tread depth.
    """
    return tire.brand or f"Tire #{tire.id}"


class TireSetService:
    """CRUD for sets, plus the one operation that justifies them."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _to_response(tire_set: TireSet) -> TireSetResponse:
        """Serialise a set with its live membership.

        Retired tires are excluded from BOTH counts. A retired tire is history
        rather than inventory, so a set that still listed it would offer to fit
        a tire the user has thrown away, and its "3 of 4 fitted" would never
        reach 4.
        """
        members = [tire for tire in (tire_set.tires or []) if tire.retired_on is None]
        return TireSetResponse(
            id=tire_set.id,
            vin=tire_set.vin,
            name=tire_set.name,
            notes=tire_set.notes,
            created_at=tire_set.created_at,
            tire_ids=sorted(tire.id for tire in members),
            mounted_count=sum(1 for tire in members if tire.position is not None),
        )

    async def _get_set(self, vin: str, set_id: int) -> TireSet:
        """Load a set, scoped to its vehicle, or 404.

        Scoping every read through here is what stops one vehicle's set being
        renamed, deleted or fitted through another vehicle's URL. There is no
        database constraint doing it.
        """
        tire_set = (
            await self.db.execute(
                select(TireSet)
                .where(TireSet.id == set_id, TireSet.vin == vin)
                .options(selectinload(TireSet.tires).selectinload(Tire.mount_periods))
            )
        ).scalar_one_or_none()
        if tire_set is None:
            raise HTTPException(status_code=404, detail="Tire set not found")
        return tire_set

    async def list_sets(self, vin: str, current_user: User) -> TireSetListResponse:
        """Every set for a vehicle, oldest first."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)
        rows = (
            (
                await self.db.execute(
                    select(TireSet)
                    .where(TireSet.vin == vin)
                    .options(selectinload(TireSet.tires))
                    .order_by(TireSet.id)
                )
            )
            .scalars()
            .all()
        )
        sets = [self._to_response(row) for row in rows]
        return TireSetListResponse(sets=sets, total=len(sets))

    async def create_set(
        self, vin: str, data: TireSetCreate, current_user: User
    ) -> TireSetResponse:
        """Name a new, empty set.

        Empty on purpose: membership is written from the tire side, so there is
        exactly one writer for it.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        tire_set = TireSet(vin=vin, name=data.name, notes=data.notes)
        self.db.add(tire_set)
        await self.db.commit()
        await self.db.refresh(tire_set)
        return await self._reload(vin, tire_set.id)

    async def update_set(
        self, vin: str, set_id: int, data: TireSetUpdate, current_user: User
    ) -> TireSetResponse:
        """Rename a set, or change its notes."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        tire_set = await self._get_set(vin, set_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(tire_set, key, value)
        await self.db.commit()
        return await self._reload(vin, set_id)

    async def delete_set(self, vin: str, set_id: int, current_user: User) -> None:
        """Delete a set. Its tires survive, ungrouped.

        `tires.set_id` is ON DELETE SET NULL rather than CASCADE, and that is
        the difference between deleting a label and deleting four tires plus a
        season of readings.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        tire_set = await self._get_set(vin, set_id)
        # No explicit null-out. `TireSet.tires` is a plain one-to-many with no
        # delete cascade, so SQLAlchemy de-associates the loaded collection --
        # `UPDATE tires SET set_id = NULL` -- before the DELETE, on both
        # dialects and regardless of `PRAGMA foreign_keys`. The FK's ON DELETE
        # SET NULL is the backstop under a raw SQL delete. An explicit loop was
        # written here first and then removed: no mutation could kill it,
        # because the ORM was already doing the same work.
        await self.db.delete(tire_set)
        await self.db.commit()

    async def mount_set(
        self, vin: str, set_id: int, data: TireSetMountRequest, current_user: User
    ) -> TireListResponse:
        """Fit every tire in a set, each at the corner it was last on.

        All or nothing, for the same reason a rotation is: an arrangement that
        applied three of four moves is one nobody asked for and one the user
        would have to read back corner by corner to discover.

        Everything the incoming set displaces comes off in the same
        transaction, bounded by the same odometer, so the outgoing periods are
        closed rather than left open at a corner someone else now holds.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        tire_set = await self._get_set(vin, set_id)

        members = [tire for tire in (tire_set.tires or []) if tire.retired_on is None]
        if not members:
            raise HTTPException(
                status_code=409,
                detail=f"'{tire_set.name}' has no tires in it yet.",
            )

        destinations: dict[int, str] = {}
        unplaceable: list[Tire] = []
        for tire in members:
            position = remembered_position(tire)
            if position is None:
                unplaceable.append(tire)
            else:
                destinations[tire.id] = position
        if unplaceable:
            names = ", ".join(_describe(tire) for tire in unplaceable)
            raise HTTPException(
                status_code=409,
                detail=(
                    f"These tires have never been fitted, so there is no corner to put "
                    f"them back on: {names}. Mount them once, then the set remembers."
                ),
            )

        # Two members that were last on the same corner cannot both go back to
        # it. Caught here so the message names the corner, rather than mid-write
        # as an IntegrityError that names an index.
        seen: dict[str, Tire] = {}
        clashes: list[str] = []
        for tire in members:
            position = destinations[tire.id]
            if position in seen:
                clashes.append(f"{position} ({_describe(seen[position])} and {_describe(tire)})")
            seen[position] = tire
        if clashes:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Two tires in this set were last on the same corner: "
                    + "; ".join(clashes)
                    + ". Mount them individually to say where each one goes."
                ),
            )

        wanted = set(destinations.values())
        member_ids = {tire.id for tire in members}
        displaced = (
            (
                await self.db.execute(
                    select(Tire).where(
                        Tire.vin == vin,
                        Tire.position.in_(wanted),
                        Tire.id.notin_(member_ids),
                    )
                )
            )
            .scalars()
            .all()
        )

        # A member already sitting on its own destination is left alone. Taking
        # it off and putting it straight back would close a period and open an
        # identical one, splitting its history at a moment when nothing
        # happened to it.
        moving = [tire for tire in members if tire.position != destinations[tire.id]]
        when = data.mounted_on or utc_now().date()

        await apply_mount_moves(
            self.db,
            vacate=[*displaced, *[tire for tire in moving if tire.position is not None]],
            assign=[(tire, destinations[tire.id]) for tire in moving],
            when=when,
            odometer_km=data.odometer_km,
            notes=data.notes,
        )
        # ONE reading for the whole swap. Marked as a set fit rather than as a
        # per-tire operation, so deleting any one tire in the set does not take
        # the vehicle's odometer reading with it.
        await sync_odometer_from_record(
            self.db,
            vin,
            when,
            data.odometer_km,
            ODOMETER_SOURCE_SET,
            tire_set.id,
            commit=False,
        )
        await self.db.commit()
        logger.info(
            "Fitted tire set %s (%s tires) for %s",
            set_id,
            len(moving),
            sanitize_for_log(vin),
        )
        return await TireService(self.db).list_tires(vin, current_user)

    async def _reload(self, vin: str, set_id: int) -> TireSetResponse:
        """Re-read a set with its membership loaded, after a write."""
        return self._to_response(await self._get_set(vin, set_id))
