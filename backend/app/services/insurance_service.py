"""Household insurance policies: business logic and the access rules.

A policy is not a vehicle-owned row, so `get_vehicle_or_403` alone cannot guard
it. Access DERIVES from the vehicles a policy covers (decision D1-B):

- READ: admin, the creator, or read access to at least one covered vehicle.
  The response lists only the links the caller may read; the rest are a count.
- WRITE (policy details, delete, renew, replace, and anything that moves money
  between vehicles): admin, the creator, or write access to EVERY covered
  vehicle. Attaching a vehicle or changing a share changes every sibling's
  computed share, so those are policy writes, not vehicle writes.
- A link's NON-financial details need write on that vehicle and read on the
  policy.
- `auth_mode=none` (`current_user is None`) has full access, mirroring
  `get_vehicle_or_403`.

Every route goes through `_Access`, so these rules live in one place.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insurance import InsurancePolicy, InsurancePolicyField, InsurancePolicyVehicle
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.schemas.insurance import (
    InsurancePolicyCreate,
    InsurancePolicyRenew,
    InsurancePolicyReplace,
    InsurancePolicyResponse,
    InsurancePolicyUpdate,
    NamedField,
    PolicyHistoryEntry,
    PolicyStatus,
    PolicyVehicleCreate,
    PolicyVehicleResponse,
    PolicyVehicleUpdate,
    PolicyVehicleUpsert,
)
from app.services.auth import get_vehicle_or_403
from app.services.vehicle_lock import LOCK_BUSY_DETAIL, is_lock_contention
from app.utils.household_time import household_today
from app.utils.insurance_shares import (
    AllocationError,
    effective_shares,
    rescale_shares,
    validate_allocation,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

#: Link columns that move money between the vehicles on a policy.
_FINANCIAL_LINK_FIELDS = frozenset({"premium_share", "effective_to"})


@dataclass
class _Access:
    """What one caller may touch, resolved once per request."""

    everything: bool
    user_id: int | None
    read_vins: set[str] = field(default_factory=set)
    write_vins: set[str] = field(default_factory=set)

    def can_read_vin(self, vin: str) -> bool:
        return self.everything or vin in self.read_vins

    def can_write_vin(self, vin: str) -> bool:
        return self.everything or vin in self.write_vins

    def _is_creator(self, policy: InsurancePolicy) -> bool:
        return self.user_id is not None and policy.created_by_user_id == self.user_id

    def can_read(self, policy: InsurancePolicy) -> bool:
        if self.everything or self._is_creator(policy):
            return True
        return any(link.vin in self.read_vins for link in policy.vehicle_links)

    def can_write(self, policy: InsurancePolicy) -> bool:
        if self.everything or self._is_creator(policy):
            return True
        links = policy.vehicle_links
        return bool(links) and all(link.vin in self.write_vins for link in links)


def policy_status(
    policy: InsurancePolicy, today: date, successor_starts: dict[int, date]
) -> PolicyStatus:
    """Upcoming, active or expired.

    A policy is active THROUGH its end date, as it always has been. The one
    refinement is the shared boundary day of two adjacent terms: once a
    successor has started, the old term reads expired that day. The successor
    clause applies on that day only, so a mis-chained or concurrent policy can
    never be hidden while it is still in force.
    """
    if policy.start_date > today:
        return "upcoming"
    if policy.end_date < today:
        return "expired"
    successor_start = successor_starts.get(policy.id)
    if policy.end_date == today and successor_start is not None and successor_start <= today:
        return "expired"
    return "active"


def _vehicle_name(vehicle: Vehicle | None, vin: str) -> str:
    if vehicle is None:
        return vin
    if vehicle.nickname:
        return vehicle.nickname
    parts = [str(p) for p in (vehicle.year, vehicle.make, vehicle.model) if p]
    return " ".join(parts) or vin


class InsuranceService:
    """Service for household insurance policies."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ access

    async def _resolve_access(self, current_user: User | None) -> _Access:
        if current_user is None or current_user.is_admin:
            return _Access(everything=True, user_id=getattr(current_user, "id", None))

        owned = (
            (await self.db.execute(select(Vehicle.vin).where(Vehicle.user_id == current_user.id)))
            .scalars()
            .all()
        )
        shares = (
            await self.db.execute(
                select(VehicleShare.vehicle_vin, VehicleShare.permission).where(
                    VehicleShare.user_id == current_user.id
                )
            )
        ).all()
        read_vins = set(owned) | {vin for vin, _ in shares}
        write_vins = set(owned) | {vin for vin, permission in shares if permission == "write"}
        return _Access(
            everything=False, user_id=current_user.id, read_vins=read_vins, write_vins=write_vins
        )

    async def _lock(self, policy_id: int | None = None) -> None:
        """Serialise this policy's writers for the rest of the transaction.

        The allocation invariant is a check-then-write across SEVERAL rows (the
        policy's premium and every link's share), so two requests that each
        validate against the other's stale rows could both commit and leave
        shares exceeding the premium. SQLite: `BEGIN IMMEDIATE`, the database
        write lock, before any read (a caller already inside a transaction,
        such as an import holding the vehicle lock, holds it already).
        PostgreSQL: `FOR UPDATE` on the policy row.
        """
        try:
            if self.db.get_bind().dialect.name == "sqlite":
                raw = await (await self.db.connection()).get_raw_connection()
                if not raw.driver_connection.in_transaction:
                    await self.db.execute(text("BEGIN IMMEDIATE"))
            elif policy_id is not None:
                await self.db.execute(
                    text("SELECT id FROM insurance_policies WHERE id = :id FOR UPDATE"),
                    {"id": policy_id},
                )
        except DBAPIError as exc:
            if not is_lock_contention(exc):
                raise
            raise HTTPException(status_code=503, detail=LOCK_BUSY_DETAIL) from exc

    async def access_for(self, current_user: User | None) -> _Access:
        """The caller's resolved access, for code outside this service that must
        apply the same rules (the importers)."""
        return await self._resolve_access(current_user)

    async def _load(self, policy_id: int) -> InsurancePolicy:
        result = await self.db.execute(
            select(InsurancePolicy)
            .where(InsurancePolicy.id == policy_id)
            .execution_options(populate_existing=True)
        )
        policy = result.scalar_one_or_none()
        if policy is None:
            raise HTTPException(status_code=404, detail="Insurance policy not found")
        return policy

    async def _load_readable(self, policy_id: int, access: _Access) -> InsurancePolicy:
        policy = await self._load(policy_id)
        if not access.can_read(policy):
            # 404, not 403: a policy the caller cannot see does not exist for them.
            raise HTTPException(status_code=404, detail="Insurance policy not found")
        return policy

    async def _load_writable(self, policy_id: int, access: _Access) -> InsurancePolicy:
        policy = await self._load_readable(policy_id, access)
        if not access.can_write(policy):
            raise HTTPException(
                status_code=403,
                detail="Editing this policy needs write access to every vehicle it covers",
            )
        return policy

    # --------------------------------------------------------------- responses

    async def _successor_starts(self) -> dict[int, date]:
        rows = await self.db.execute(
            select(InsurancePolicy.previous_policy_id, InsurancePolicy.start_date).where(
                InsurancePolicy.previous_policy_id.is_not(None)
            )
        )
        starts: dict[int, date] = {}
        for previous_id, start in rows.all():
            if previous_id not in starts or start < starts[previous_id]:
                starts[previous_id] = start
        return starts

    async def _vehicles_by_vin(self, vins: set[str]) -> dict[str, Vehicle]:
        if not vins:
            return {}
        result = await self.db.execute(select(Vehicle).where(Vehicle.vin.in_(vins)))
        return {v.vin: v for v in result.scalars().all()}

    def _link_responses(
        self, policy: InsurancePolicy, access: _Access, vehicles: dict[str, Vehicle]
    ) -> tuple[list[PolicyVehicleResponse], int]:
        shares = effective_shares(
            policy.premium_amount, [(link.id, link.premium_share) for link in policy.vehicle_links]
        )
        visible: list[PolicyVehicleResponse] = []
        hidden = 0
        for link in policy.vehicle_links:
            if not access.can_read_vin(link.vin):
                hidden += 1
                continue
            visible.append(
                PolicyVehicleResponse(
                    id=link.id,
                    vin=link.vin,
                    vehicle_name=_vehicle_name(vehicles.get(link.vin), link.vin),
                    policy_type=link.policy_type,
                    premium_share=link.premium_share,
                    effective_share=shares.get(link.id),
                    deductible=link.deductible,
                    coverage_limits=link.coverage_limits,
                    notes=link.notes,
                    effective_to=link.effective_to,
                    fields=[NamedField.model_validate(f) for f in link.fields],
                    can_edit=access.can_write_vin(link.vin),
                )
            )
        return visible, hidden

    async def _respond_many(
        self, policies: list[InsurancePolicy], access: _Access
    ) -> list[InsurancePolicyResponse]:
        today = household_today()
        successor_starts = await self._successor_starts()
        vehicles = await self._vehicles_by_vin(
            {link.vin for policy in policies for link in policy.vehicle_links}
        )
        responses = []
        for policy in policies:
            links, hidden = self._link_responses(policy, access, vehicles)
            responses.append(
                InsurancePolicyResponse(
                    id=policy.id,
                    provider=policy.provider,
                    policy_number=policy.policy_number,
                    start_date=policy.start_date,
                    end_date=policy.end_date,
                    premium_amount=policy.premium_amount,
                    premium_frequency=policy.premium_frequency,
                    notes=policy.notes,
                    status=policy_status(policy, today, successor_starts),
                    previous_policy_id=policy.previous_policy_id,
                    has_successor=policy.id in successor_starts,
                    created_by_user_id=policy.created_by_user_id,
                    created_at=policy.created_at,
                    fields=[NamedField.model_validate(f) for f in policy.fields],
                    vehicles=links,
                    other_vehicle_count=hidden,
                    can_edit=access.can_write(policy),
                )
            )
        return responses

    async def _respond(self, policy_id: int, access: _Access) -> InsurancePolicyResponse:
        policy = await self._load(policy_id)
        return (await self._respond_many([policy], access))[0]

    # ------------------------------------------------------------------- reads

    async def list_policies(
        self,
        current_user: User | None,
        vin: str | None = None,
        status: str = "current",
    ) -> list[InsurancePolicyResponse]:
        """Policies the caller may see. `status`: current (active + upcoming),
        active, upcoming, expired or all."""
        access = await self._resolve_access(current_user)
        query = select(InsurancePolicy).order_by(
            InsurancePolicy.end_date.desc(), InsurancePolicy.id.desc()
        )
        if vin is not None:
            vin = vin.upper().strip()
            await get_vehicle_or_403(vin, current_user, self.db)
            query = query.join(InsurancePolicyVehicle).where(InsurancePolicyVehicle.vin == vin)
        policies = [
            p for p in (await self.db.execute(query)).scalars().unique() if access.can_read(p)
        ]
        responses = await self._respond_many(policies, access)
        if status == "all":
            return responses
        wanted = {"active", "upcoming"} if status == "current" else {status}
        return [r for r in responses if r.status in wanted]

    async def list_policies_for_vin(
        self, vin: str, current_user: User | None
    ) -> list[InsurancePolicyResponse]:
        """Every policy, past and present, that covers one vehicle."""
        return await self.list_policies(current_user, vin=vin, status="all")

    async def read_policy(
        self, policy_id: int, current_user: User | None
    ) -> InsurancePolicyResponse:
        access = await self._resolve_access(current_user)
        policy = await self._load_readable(policy_id, access)
        return (await self._respond_many([policy], access))[0]

    async def history(self, policy_id: int, current_user: User | None) -> list[PolicyHistoryEntry]:
        """The whole chain this policy belongs to, oldest term first."""
        access = await self._resolve_access(current_user)
        requested = await self._load_readable(policy_id, access)

        chain = [requested]
        seen = {requested.id}
        cursor = requested
        while cursor.previous_policy_id is not None and cursor.previous_policy_id not in seen:
            cursor = await self._load(cursor.previous_policy_id)
            seen.add(cursor.id)
            chain.insert(0, cursor)
        cursor = requested
        while True:
            successor = (
                await self.db.execute(
                    select(InsurancePolicy)
                    .where(InsurancePolicy.previous_policy_id == cursor.id)
                    .order_by(InsurancePolicy.start_date, InsurancePolicy.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if successor is None or successor.id in seen:
                break
            seen.add(successor.id)
            chain.append(successor)
            cursor = successor

        readable = [p for p in chain if access.can_read(p)]
        responses = await self._respond_many(readable, access)
        entries: list[PolicyHistoryEntry] = []
        prior: InsurancePolicyResponse | None = None
        for response in responses:
            change: Decimal | None = None
            if (
                prior is not None
                and prior.premium_amount is not None
                and response.premium_amount is not None
                and prior.premium_frequency == response.premium_frequency
            ):
                change = response.premium_amount - prior.premium_amount
            entries.append(
                PolicyHistoryEntry(
                    id=response.id,
                    provider=response.provider,
                    policy_number=response.policy_number,
                    start_date=response.start_date,
                    end_date=response.end_date,
                    premium_amount=response.premium_amount,
                    premium_frequency=response.premium_frequency,
                    status=response.status,
                    premium_change=change,
                    vehicles=response.vehicles,
                    is_current=response.id == requested.id,
                )
            )
            prior = response
        return entries

    async def attachable_vehicles(self, current_user: User | None) -> dict[str, str]:
        """VIN -> display name of every vehicle the caller could put on a policy,
        which takes WRITE access; a document parse uses it to mark its matches."""
        access = await self._resolve_access(current_user)
        query = select(Vehicle).where(Vehicle.archived_at.is_(None))
        vehicles = (await self.db.execute(query)).scalars().all()
        return {v.vin: _vehicle_name(v, v.vin) for v in vehicles if access.can_write_vin(v.vin)}

    # ------------------------------------------------------------------ helpers

    def _check_allocation(self, policy: InsurancePolicy) -> None:
        try:
            validate_allocation(
                policy.premium_amount, [link.premium_share for link in policy.vehicle_links]
            )
        except AllocationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @staticmethod
    def _set_fields(
        policy: InsurancePolicy,
        link: InsurancePolicyVehicle | None,
        fields: list[NamedField],
    ) -> None:
        """Replace the named fields at one level (the policy, or one link)."""
        for existing in list(policy.all_fields):
            if existing.policy_vehicle is link and (
                link is not None or existing.policy_vehicle_id is None
            ):
                policy.all_fields.remove(existing)
        for order, item in enumerate(fields):
            policy.all_fields.append(
                InsurancePolicyField(
                    policy_vehicle=link,
                    label=item.label.strip(),
                    value=item.value,
                    sort_order=order,
                )
            )

    async def _new_link(
        self,
        policy: InsurancePolicy,
        data: PolicyVehicleCreate | PolicyVehicleUpsert,
        current_user: User | None,
    ) -> InsurancePolicyVehicle:
        vin = data.vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        if any(existing.vin == vin for existing in policy.vehicle_links):
            raise HTTPException(status_code=409, detail="That vehicle is already on this policy")
        link = InsurancePolicyVehicle(
            vin=vin,
            policy_type=data.policy_type,
            premium_share=data.premium_share,
            deductible=data.deductible,
            coverage_limits=data.coverage_limits,
            notes=data.notes,
            effective_to=getattr(data, "effective_to", None),
        )
        policy.vehicle_links.append(link)
        if data.fields:
            self._set_fields(policy, link, data.fields)
        return link

    async def _commit(self, action: str) -> None:
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            logger.error("Constraint violation %s: %s", action, sanitize_for_log(exc))
            raise HTTPException(status_code=409, detail="Duplicate or invalid insurance data")

    async def _has_successor(self, policy_id: int) -> bool:
        found = await self.db.execute(
            select(InsurancePolicy.id).where(InsurancePolicy.previous_policy_id == policy_id)
        )
        return found.first() is not None

    # --------------------------------------------------------------- mutations

    async def create_policy(
        self, data: InsurancePolicyCreate, current_user: User | None
    ) -> InsurancePolicyResponse:
        access = await self._resolve_access(current_user)
        policy = InsurancePolicy(
            provider=data.provider.strip(),
            policy_number=data.policy_number.strip(),
            start_date=data.start_date,
            end_date=data.end_date,
            premium_amount=data.premium_amount,
            premium_frequency=data.premium_frequency,
            notes=data.notes,
            created_by_user_id=access.user_id,
        )
        self.db.add(policy)
        for vehicle in data.vehicles:
            await self._new_link(policy, vehicle, current_user)
        self._set_fields(policy, None, data.fields)
        self._check_allocation(policy)
        await self._commit("creating insurance policy")
        logger.info("Created insurance policy %s", policy.id)
        return await self._respond(policy.id, access)

    async def update_policy(
        self, policy_id: int, data: InsurancePolicyUpdate, current_user: User | None
    ) -> InsurancePolicyResponse:
        await self._lock(policy_id)
        access = await self._resolve_access(current_user)
        policy = await self._load_writable(policy_id, access)
        changes = data.model_dump(exclude_unset=True)
        fields = changes.pop("fields", None)
        vehicles = changes.pop("vehicles", None)
        strategy = changes.pop("share_strategy", None)

        old_total = policy.premium_amount
        for name, value in changes.items():
            setattr(policy, name, value.strip() if isinstance(value, str) else value)
        if policy.end_date < policy.start_date:
            raise HTTPException(status_code=422, detail="end_date must not be before start_date")

        if vehicles is not None:
            await self._apply_vehicles(policy, data.vehicles or [], access, current_user)
        elif "premium_amount" in changes and policy.premium_amount != old_total:
            links = policy.vehicle_links
            if links and all(link.premium_share is not None for link in links):
                if strategy is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Every vehicle has a fixed share, so changing the premium needs "
                        "share_strategy: 'rescale' to keep the proportions or 'reset_even' "
                        "to split evenly",
                    )
                pairs = [(link.id, link.premium_share) for link in links]
                rescaled = (
                    rescale_shares(pairs, old_total, policy.premium_amount)
                    if strategy == "rescale"
                    else {link.id: None for link in links}
                )
                for link in links:
                    link.premium_share = rescaled[link.id]

        if fields is not None:
            self._set_fields(policy, None, data.fields or [])
        self._check_allocation(policy)
        await self._commit("updating insurance policy")
        return await self._respond(policy.id, access)

    async def _apply_vehicles(
        self,
        policy: InsurancePolicy,
        wanted: list[PolicyVehicleUpsert],
        access: _Access,
        current_user: User | None,
    ) -> None:
        """Make the policy's vehicles exactly `wanted` (the form's full state).

        Saving the total and every share in one request is what lets a user add
        a third vehicle AND raise the premium without an intermediate state
        that breaks the allocation invariant.
        """
        vins = [item.vin.upper().strip() for item in wanted]
        if len(set(vins)) != len(vins):
            raise HTTPException(status_code=422, detail="A vehicle can be on a policy only once")

        existing = {link.vin: link for link in policy.vehicle_links}
        for vin, link in existing.items():
            if vin not in vins:
                if not access.can_write_vin(vin):
                    raise HTTPException(
                        status_code=403, detail="Removing a vehicle needs write access to it"
                    )
                policy.vehicle_links.remove(link)

        for item in wanted:
            vin = item.vin.upper().strip()
            link = existing.get(vin)
            if link is None:
                await self._new_link(policy, item, current_user)
                continue
            unchanged = (
                link.policy_type == item.policy_type
                and link.premium_share == item.premium_share
                and link.deductible == item.deductible
                and (link.coverage_limits or None) == (item.coverage_limits or None)
                and (link.notes or None) == (item.notes or None)
                and link.effective_to == item.effective_to
                and (
                    item.fields is None
                    or [(f.label, f.value) for f in link.fields]
                    == [(f.label.strip(), f.value) for f in item.fields]
                )
            )
            if unchanged:
                # The form always sends the whole list. A creator with only READ
                # access to one covered vehicle must still be able to fix the
                # provider's name, so an untouched vehicle needs no write access.
                continue
            if not access.can_write_vin(vin):
                raise HTTPException(
                    status_code=403, detail="Editing a vehicle's coverage needs write access to it"
                )
            link.policy_type = item.policy_type
            link.premium_share = item.premium_share
            link.deductible = item.deductible
            link.coverage_limits = item.coverage_limits
            link.notes = item.notes
            link.effective_to = item.effective_to
            if item.fields is not None:
                self._set_fields(policy, link, item.fields)
        self._check_effective_to(policy)

    @staticmethod
    def _check_effective_to(policy: InsurancePolicy) -> None:
        for link in policy.vehicle_links:
            if link.effective_to is not None and not (
                policy.start_date <= link.effective_to <= policy.end_date
            ):
                raise HTTPException(
                    status_code=422,
                    detail="A vehicle's removal date must fall within the policy term",
                )

    async def delete_policy(self, policy_id: int, current_user: User | None) -> None:
        await self._lock(policy_id)
        access = await self._resolve_access(current_user)
        policy = await self._load_writable(policy_id, access)
        await self.db.delete(policy)
        await self._commit("deleting insurance policy")
        logger.info("Deleted insurance policy %s", policy_id)

    async def attach_vehicle(
        self, policy_id: int, data: PolicyVehicleCreate, current_user: User | None
    ) -> InsurancePolicyResponse:
        """Add one vehicle. Its explicit share GROWS the policy premium by the
        same amount, which leaves every sibling's effective share untouched. A
        vehicle attached WITHOUT a share joins the even split, which by
        definition re-divides whatever the unset siblings were sharing; that is
        a policy write, which is what this method requires."""
        await self._lock(policy_id)
        access = await self._resolve_access(current_user)
        policy = await self._load_writable(policy_id, access)
        link = await self._new_link(policy, data, current_user)
        if link.premium_share is not None and policy.premium_amount is not None:
            policy.premium_amount = policy.premium_amount + link.premium_share
        self._check_allocation(policy)
        await self._commit("attaching a vehicle to an insurance policy")
        return await self._respond(policy.id, access)

    async def update_link(
        self,
        policy_id: int,
        link_id: int,
        data: PolicyVehicleUpdate,
        current_user: User | None,
    ) -> InsurancePolicyResponse:
        await self._lock(policy_id)
        access = await self._resolve_access(current_user)
        policy = await self._load_readable(policy_id, access)
        link = next((item for item in policy.vehicle_links if item.id == link_id), None)
        if link is None or not access.can_read_vin(link.vin):
            raise HTTPException(status_code=404, detail="That vehicle is not on this policy")

        changes = data.model_dump(exclude_unset=True)
        fields = changes.pop("fields", None)
        if _FINANCIAL_LINK_FIELDS & changes.keys() and not access.can_write(policy):
            raise HTTPException(
                status_code=403,
                detail="Changing a vehicle's share or removal date moves money between "
                "vehicles, so it needs write access to the whole policy",
            )
        await get_vehicle_or_403(link.vin, current_user, self.db, require_write=True)

        if "policy_type" in changes and changes["policy_type"] is None:
            changes.pop("policy_type")
        for name, value in changes.items():
            setattr(link, name, value)
        if fields is not None:
            self._set_fields(policy, link, data.fields or [])
        self._check_effective_to(policy)
        self._check_allocation(policy)
        await self._commit("updating a vehicle on an insurance policy")
        return await self._respond(policy.id, access)

    async def detach_vehicle(
        self, policy_id: int, link_id: int, current_user: User | None
    ) -> InsurancePolicyResponse:
        """Remove one vehicle, and its effective share from the policy premium,
        so every remaining vehicle keeps exactly the share it had."""
        await self._lock(policy_id)
        access = await self._resolve_access(current_user)
        policy = await self._load_writable(policy_id, access)
        link = next((item for item in policy.vehicle_links if item.id == link_id), None)
        if link is None:
            raise HTTPException(status_code=404, detail="That vehicle is not on this policy")
        await get_vehicle_or_403(link.vin, current_user, self.db, require_write=True)

        share = effective_shares(
            policy.premium_amount, [(item.id, item.premium_share) for item in policy.vehicle_links]
        ).get(link.id)
        policy.vehicle_links.remove(link)
        if share is not None and policy.premium_amount is not None:
            policy.premium_amount = max(policy.premium_amount - share, Decimal("0"))
        self._check_allocation(policy)
        await self._commit("detaching a vehicle from an insurance policy")
        return await self._respond(policy.id, access)

    async def release_vehicle(self, vin: str) -> int:
        """Take a vehicle off every policy it is on. Returns how many. No commit.

        For a TRANSFER: policy access derives from the covered vehicles, so a
        vehicle that kept its links would hand its new owner the old owner's
        policies. Each policy's premium drops by the vehicle's effective share,
        so every vehicle that stays keeps exactly the share it had. The caller
        has already authorized the transfer itself.
        """
        # The same serialisation as every other writer: this rewrites premiums,
        # and an import or an edit racing it would validate against stale money.
        # SQLite takes the database write lock; elsewhere the rows are locked by
        # the SELECT itself (`with_for_update` compiles away on SQLite).
        await self._lock()
        policies = (
            (
                await self.db.execute(
                    select(InsurancePolicy)
                    .join(InsurancePolicyVehicle)
                    .where(InsurancePolicyVehicle.vin == vin)
                    .with_for_update(of=InsurancePolicy)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .unique()
            .all()
        )
        for policy in policies:
            shares = effective_shares(
                policy.premium_amount,
                [(item.id, item.premium_share) for item in policy.vehicle_links],
            )
            for link in [item for item in policy.vehicle_links if item.vin == vin]:
                share = shares.get(link.id)
                policy.vehicle_links.remove(link)
                if share is not None and policy.premium_amount is not None:
                    policy.premium_amount = max(policy.premium_amount - share, Decimal("0"))
        return len(policies)

    # ---------------------------------------------------------- renew / replace

    async def renew(
        self, policy_id: int, data: InsurancePolicyRenew, current_user: User | None
    ) -> InsurancePolicyResponse:
        """Create the next term. The old term is never modified."""
        await self._lock(policy_id)
        access = await self._resolve_access(current_user)
        old = await self._load_writable(policy_id, access)
        if await self._has_successor(old.id):
            raise HTTPException(
                status_code=409, detail="This policy already has a following term or replacement"
            )

        sent = data.model_fields_set
        start = data.start_date or old.end_date
        end = data.end_date or (start + (old.end_date - old.start_date))
        if end < start:
            raise HTTPException(status_code=422, detail="end_date must not be before start_date")
        total = data.premium_amount if "premium_amount" in sent else old.premium_amount

        carried = [link for link in old.vehicle_links if link.effective_to is None]
        # Proportions are taken against what the CARRIED vehicles cost, not the
        # old premium: a vehicle that left mid-term took its share with it, and
        # scaling a survivor's 400 by 700/600 when only 400 of that 600 is still
        # on the policy would ask for 466.67 of a 700 premium it alone covers.
        old_effective = effective_shares(
            old.premium_amount, [(link.id, link.premium_share) for link in old.vehicle_links]
        )
        carried_base = sum(
            (old_effective[link.id] or Decimal("0") for link in carried), Decimal("0")
        )
        pairs = [(link.id, link.premium_share) for link in carried]
        nothing_changed = total == old.premium_amount and len(carried) == len(old.vehicle_links)
        shares = dict(pairs) if nothing_changed else rescale_shares(pairs, carried_base, total)

        new = InsurancePolicy(
            provider=old.provider,
            policy_number=old.policy_number,
            start_date=start,
            end_date=end,
            premium_amount=total,
            premium_frequency=(
                data.premium_frequency if "premium_frequency" in sent else old.premium_frequency
            ),
            notes=data.notes if "notes" in sent else old.notes,
            created_by_user_id=access.user_id,
            previous_policy_id=old.id,
        )
        self.db.add(new)
        for link in carried:
            copy = InsurancePolicyVehicle(
                vin=link.vin,
                policy_type=link.policy_type,
                premium_share=shares[link.id],
                deductible=link.deductible,
                coverage_limits=link.coverage_limits,
                notes=link.notes,
            )
            new.vehicle_links.append(copy)
            self._set_fields(new, copy, [NamedField.model_validate(f) for f in link.fields])
        policy_level = [NamedField.model_validate(f) for f in old.fields]
        for order, item in enumerate(policy_level):
            new.all_fields.append(
                InsurancePolicyField(label=item.label, value=item.value, sort_order=order)
            )
        self._check_allocation(new)
        await self._commit("renewing insurance policy")
        logger.info("Renewed insurance policy %s as %s", old.id, new.id)
        return await self._respond(new.id, access)

    async def replace(
        self, policy_id: int, data: InsurancePolicyReplace, current_user: User | None
    ) -> InsurancePolicyResponse:
        """Switch insurers: a new policy takes over this one's vehicles. The new
        insurer's coverages differ, so only the vehicles and their coverage type
        carry over, on an even split."""
        await self._lock(policy_id)
        access = await self._resolve_access(current_user)
        old = await self._load_writable(policy_id, access)
        if await self._has_successor(old.id):
            raise HTTPException(
                status_code=409, detail="This policy already has a following term or replacement"
            )
        if data.end_old_on is not None:
            if not (old.start_date <= data.end_old_on <= old.end_date):
                raise HTTPException(
                    status_code=422, detail="end_old_on must fall within the old policy's term"
                )
            old.end_date = data.end_old_on
            for link in old.vehicle_links:
                if link.effective_to is not None and link.effective_to > old.end_date:
                    link.effective_to = None

        wanted = None if data.vins is None else {v.upper().strip() for v in data.vins}
        new = InsurancePolicy(
            provider=data.provider.strip(),
            policy_number=data.policy_number.strip(),
            start_date=data.start_date,
            end_date=data.end_date,
            premium_amount=data.premium_amount,
            premium_frequency=data.premium_frequency,
            notes=data.notes,
            created_by_user_id=access.user_id,
            previous_policy_id=old.id,
        )
        self.db.add(new)
        if data.vehicles is not None:
            # The form's full vehicle list: the new insurer's coverages, entered
            # in the same step. Each vehicle needs write access, as on create.
            for vehicle in data.vehicles:
                await self._new_link(new, vehicle, current_user)
        else:
            for link in old.vehicle_links:
                if link.effective_to is not None and data.end_old_on is None:
                    continue
                if wanted is not None and link.vin not in wanted:
                    continue
                new.vehicle_links.append(
                    InsurancePolicyVehicle(vin=link.vin, policy_type=link.policy_type)
                )
        self._check_allocation(new)
        await self._commit("replacing insurance policy")
        logger.info("Replaced insurance policy %s with %s", old.id, new.id)
        return await self._respond(new.id, access)
