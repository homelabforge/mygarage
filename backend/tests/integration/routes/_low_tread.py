"""Low-tread reminder helpers shared by the tire lifecycle and tire set suites."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminder import Reminder
from app.models.tire import Tire
from app.services import tire_service as tire_service_module


async def low_tread_rows(db_session: AsyncSession, vin: str) -> list[Reminder]:
    """Every reminder on the vehicle, as the requests committed them."""
    db_session.expire_all()
    return list(
        (
            await db_session.execute(
                select(Reminder).where(Reminder.vin == vin).order_by(Reminder.id)
            )
        )
        .scalars()
        .all()
    )


def fail_the_second_sync(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Make the second `sync_low_tread_reminder` call raise, after the first has written.

    Returns the tire ids the sync was called with, in call order.
    """
    real = tire_service_module.sync_low_tread_reminder
    calls: list[int] = []

    async def second_one_fails(db: AsyncSession, tire: Tire) -> bool:
        calls.append(tire.id)
        if len(calls) == 2:
            raise RuntimeError("sync failed")
        return await real(db, tire)

    monkeypatch.setattr(tire_service_module, "sync_low_tread_reminder", second_one_fails)
    return calls
