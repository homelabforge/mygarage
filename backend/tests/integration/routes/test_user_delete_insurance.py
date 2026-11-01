"""Deleting a user takes their vehicles off a shared policy the way a vehicle delete does.

A policy is a household record. The FK cascade from a user delete drops their
vehicle's link but leaves the premium counting it, so the vehicles that stay
would no longer add up. A vehicle delete releases the vehicle first (the
premium drops by its share); a user delete has to do the same for each one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insurance import InsurancePolicy, InsurancePolicyVehicle
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.vehicle_service import VehicleService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass
class Household:
    a_id: int
    a_vins: list[str]
    b_vin: str
    policy_id: int


async def _user(db: AsyncSession, made_users: list[str], tag: str) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"ins_{tag}_{suffix}",
        email=f"ins-{tag}-{suffix}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    made_users.append(user.username)
    await db.flush()
    return user


async def _household(
    db: AsyncSession,
    made_users: list[str],
    premium: str,
    shares_a: tuple[str | None, ...],
    share_b: str | None,
) -> Household:
    """User A with a vehicle per entry in `shares_a`, user B with one, all on one policy."""
    a, b = await _user(db, made_users, "a"), await _user(db, made_users, "b")
    vins = []
    for owner in [a] * len(shares_a) + [b]:
        vin = "INS" + uuid.uuid4().hex[:14].upper()
        db.add(Vehicle(vin=vin, user_id=owner.id, nickname="Insured", vehicle_type="Car"))
        vins.append(vin)
    await db.flush()
    policy = InsurancePolicy(
        provider="C1 Mutual",
        policy_number=uuid.uuid4().hex[:10],
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        premium_amount=Decimal(premium),
        premium_frequency="Annual",
    )
    db.add(policy)
    await db.flush()
    for vin, share in zip(vins, (*shares_a, share_b), strict=True):
        db.add(
            InsurancePolicyVehicle(
                policy_id=policy.id,
                vin=vin,
                policy_type="Liability",
                premium_share=Decimal(share) if share else None,
            )
        )
    await db.commit()
    return Household(a_id=a.id, a_vins=vins[:-1], b_vin=vins[-1], policy_id=policy.id)


async def _left(
    db: AsyncSession, house: Household
) -> tuple[Decimal | None, list[tuple[str, Decimal | None]]]:
    """The policy's premium and its links after the delete, the vehicles named by role."""
    db.expire_all()
    premium = await db.scalar(
        select(InsurancePolicy.premium_amount).where(InsurancePolicy.id == house.policy_id)
    )
    links = (
        await db.execute(
            select(InsurancePolicyVehicle.vin, InsurancePolicyVehicle.premium_share).where(
                InsurancePolicyVehicle.policy_id == house.policy_id
            )
        )
    ).all()
    role = {**dict.fromkeys(house.a_vins, "A"), house.b_vin: "B"}
    return premium, sorted((role[vin], share) for vin, share in links)


@pytest.mark.parametrize(
    ("premium", "shares_a", "share_b", "premium_left", "share_b_left"),
    [
        ("1000.00", (None,), None, "500.00", None),
        ("1000.00", ("300.00",), "700.00", "700.00", "700.00"),
        # Each release has to see the one before it, or the second undoes the first.
        ("900.00", (None, None), None, "300.00", None),
    ],
    ids=["even split", "set shares", "two vehicles"],
)
async def test_deleting_a_user_releases_their_vehicles_like_vehicle_deletes(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    made_users: list[str],
    premium: str,
    shares_a: tuple[str | None, ...],
    share_b: str | None,
    premium_left: str,
    share_b_left: str | None,
) -> None:
    via_user = await _household(db_session, made_users, premium, shares_a, share_b)
    via_vehicle = await _household(db_session, made_users, premium, shares_a, share_b)
    try:
        response = await client.delete(f"/api/auth/users/{via_user.a_id}", headers=auth_headers)
        assert response.status_code == 204, response.text

        owner = await db_session.get(User, via_vehicle.a_id)
        assert owner is not None
        for vin in via_vehicle.a_vins:
            await VehicleService(db_session).delete_vehicle(vin, owner)

        expected = (Decimal(premium_left), [("B", Decimal(share_b_left) if share_b_left else None)])
        assert await _left(db_session, via_vehicle) == expected, "control: the vehicle delete"
        assert await _left(db_session, via_user) == expected
    finally:
        await db_session.rollback()
        await db_session.execute(
            delete(InsurancePolicy).where(
                InsurancePolicy.id.in_([via_user.policy_id, via_vehicle.policy_id])
            )
        )
        await db_session.commit()
