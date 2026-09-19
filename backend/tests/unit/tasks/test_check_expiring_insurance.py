"""The expiry job notifies about a household policy ONCE, and only while it matters."""

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insurance import InsurancePolicy, InsurancePolicyVehicle
from app.models.vehicle import Vehicle
from app.tasks import scheduled
from app.utils.datetime_utils import utc_now
from app.utils.household_time import household_today

pytestmark = [pytest.mark.asyncio]

RAM, MIRAGE, SOLD = "INSEXPIRE00000001", "INSEXPIRE00000002", "INSEXPIRE00000003"


class _PassthroughSessionContext:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


@pytest_asyncio.fixture
async def sent(db_session: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch):
    """Three vehicles (one archived), a stub dispatcher, and the calls it got."""
    await db_session.execute(delete(InsurancePolicy))
    for vin, nickname, archived in (
        (RAM, "Ram", False),
        (MIRAGE, "Mirage", False),
        (SOLD, "Sold", True),
    ):
        vehicle = (
            await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))
        ).scalar_one_or_none()
        if vehicle is None:
            vehicle = Vehicle(
                vin=vin, user_id=test_user["id"], nickname=nickname, vehicle_type="Car"
            )
            db_session.add(vehicle)
        vehicle.archived_at = utc_now() if archived else None
    await db_session.commit()

    calls: list[dict] = []

    class _Dispatcher:
        def __init__(self, _db) -> None:
            pass

        async def _has_any_service_enabled(self) -> bool:
            return True

        async def notify_insurance_expiring(self, **kwargs):
            calls.append(kwargs)
            return {"discord": True}

        async def notify_warranty_expiring(self, **kwargs):
            return {"discord": True}

    monkeypatch.setattr(scheduled, "NotificationDispatcher", _Dispatcher)
    monkeypatch.setattr(
        scheduled, "AsyncSessionLocal", lambda: _PassthroughSessionContext(db_session)
    )
    yield calls
    await db_session.execute(delete(InsurancePolicy))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_([RAM, MIRAGE, SOLD])))
    await db_session.commit()


def _expiring(*vins: str, number: str = "P-1", **over) -> InsurancePolicy:
    today = household_today()
    policy = InsurancePolicy(
        provider="Progressive",
        policy_number=number,
        start_date=today - timedelta(days=170),
        end_date=today + timedelta(days=10),
        **over,
    )
    for vin in vins:
        policy.vehicle_links.append(InsurancePolicyVehicle(vin=vin, policy_type="Full Coverage"))
    return policy


async def test_a_three_vehicle_policy_is_one_notification_naming_the_live_vehicles(
    db_session, sent
):
    db_session.add(_expiring(RAM, MIRAGE, SOLD))
    await db_session.commit()

    await scheduled.check_expiring_documents()

    assert len(sent) == 1, "one per POLICY, not one per vehicle"
    assert sent[0]["vehicle_name"] == "Ram, Mirage"
    assert sent[0]["policy_name"] == "Progressive #P-1"
    assert sent[0]["days_until_expiry"] == 10


async def test_a_policy_covering_only_archived_vehicles_is_silent(db_session, sent):
    db_session.add(_expiring(SOLD))
    await db_session.commit()

    await scheduled.check_expiring_documents()

    assert sent == []


async def test_a_policy_with_no_vehicles_still_expires(db_session, sent):
    db_session.add(_expiring(number="UMBRELLA"))
    await db_session.commit()

    await scheduled.check_expiring_documents()

    assert [c["policy_name"] for c in sent] == ["Progressive #UMBRELLA"]


async def test_a_policy_whose_renewal_is_already_entered_stops_asking(db_session, sent):
    old = _expiring(RAM)
    db_session.add(old)
    await db_session.flush()
    today = household_today()
    db_session.add(
        InsurancePolicy(
            provider="Progressive",
            policy_number="P-1",
            start_date=old.end_date,
            end_date=today + timedelta(days=190),
            previous_policy_id=old.id,
        )
    )
    await db_session.commit()

    await scheduled.check_expiring_documents()

    assert sent == [], "entering the next term early is how the user says it is handled"
