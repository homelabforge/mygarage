"""Two writers racing on one insurance policy serialise instead of overspending it.

The allocation invariant (the vehicles' explicit shares may not exceed the
policy premium) is a check-then-write across SEVERAL rows, so it cannot be a
database constraint. Two requests that each validate against the other's stale
rows would both pass and together commit shares the premium cannot cover. This
is the proof that `InsuranceService._lock` stops that.

Lives in `tests/integration/` so CI runs it under PostgreSQL as well as SQLite.
Two real connections: `client` hands ONE session to every request and so
cannot race.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.models.insurance import InsurancePolicy, InsurancePolicyVehicle
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.insurance import PolicyVehicleUpdate
from app.services.insurance_service import InsuranceService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

RAM, MIRAGE = "INSRACE0000000001", "INSRACE0000000002"


async def _seed(db_session, test_user) -> tuple[User, int, int, int]:
    await db_session.execute(delete(InsurancePolicy))
    for vin in (RAM, MIRAGE):
        if (await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))).first() is None:
            db_session.add(
                Vehicle(vin=vin, user_id=test_user["id"], nickname=vin[-3:], vehicle_type="Car")
            )
    policy = InsurancePolicy(
        provider="Progressive",
        policy_number="P-RACE",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 1),
        premium_amount=Decimal("600.00"),
        premium_frequency="Semi-Annual",
    )
    ram = InsurancePolicyVehicle(vin=RAM, policy_type="Full Coverage")
    mirage = InsurancePolicyVehicle(vin=MIRAGE, policy_type="Liability")
    policy.vehicle_links.extend([ram, mirage])
    db_session.add(policy)
    await db_session.commit()
    user = await db_session.get(User, test_user["id"])
    return user, policy.id, ram.id, mirage.id


async def _set_share(sessionmaker, user: User, policy_id: int, link_id: int, share: str):
    async with sessionmaker() as db:
        return await InsuranceService(db).update_link(
            policy_id, link_id, PolicyVehicleUpdate(premium_share=Decimal(share)), user
        )


async def test_two_racing_share_edits_cannot_together_overspend_the_premium(
    db_session, test_user, test_sessionmaker, monkeypatch
):
    user, policy_id, ram_id, mirage_id = await _seed(db_session, test_user)
    try:
        # Each edit is valid ALONE (400 of a 600 premium, the other vehicle still
        # on the even split). Together they are 800. Hold each racer after it has
        # loaded the policy so both would read before either writes; with the
        # lock in place the loser blocks before it can read at all.
        original = InsuranceService._load_readable

        async def slow(self, pid, access):
            policy = await original(self, pid, access)
            await asyncio.sleep(1.0)
            return policy

        monkeypatch.setattr(InsuranceService, "_load_readable", slow)

        results = await asyncio.gather(
            _set_share(test_sessionmaker, user, policy_id, ram_id, "400.00"),
            _set_share(test_sessionmaker, user, policy_id, mirage_id, "400.00"),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, BaseException)]
        refusals = [r for r in results if isinstance(r, HTTPException)]
        others = [
            r for r in results if isinstance(r, BaseException) and not isinstance(r, HTTPException)
        ]
        assert others == [], f"unexpected exception types: {others!r}"
        assert len(successes) == 1, "exactly one edit may win"
        assert len(refusals) == 1 and refusals[0].status_code == 422

        async with test_sessionmaker() as db:
            shares = (
                (
                    await db.execute(
                        select(InsurancePolicyVehicle.premium_share).where(
                            InsurancePolicyVehicle.policy_id == policy_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        explicit = sum((s for s in shares if s is not None), Decimal("0"))
        assert explicit <= Decimal("600.00"), f"shares {shares} overspend the premium"
    finally:
        monkeypatch.undo()
        await db_session.execute(delete(InsurancePolicy))
        await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_([RAM, MIRAGE])))
        await db_session.commit()
