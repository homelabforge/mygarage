"""Every service-visit write is one transaction under the vehicle lock (G5a-07, D2).

The visit, its odometer/hours sync and the reminder reconcile commit together.
A failed sync or reconcile used to be logged after the visit had already
committed, so the visit stayed with stale reminders or no reading. Now it
fails the write and nothing lands. Each test calls the service on
`db_session` and reads back through a fresh session.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.vehicle import Vehicle
from app.schemas.maintenance import MaintenanceRuleCreate
from app.schemas.service_visit import (
    ServiceLineItemCreate,
    ServiceVisitCreate,
    ServiceVisitUpdate,
)
from app.services import maintenance_service
from app.services import service_visit_service as svs_module
from app.services.service_visit_service import ServiceVisitService
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.odometer_sync import auto_sync_marker

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PREFIX = "SVAT"


@pytest_asyncio.fixture
async def vin(db_session: AsyncSession, test_user: dict[str, object]) -> AsyncIterator[str]:
    """A vehicle of this file's own, deleted afterwards with everything under it."""
    value = (PREFIX + uuid.uuid4().hex.upper())[:17]
    db_session.add(
        Vehicle(
            vin=value,
            user_id=test_user["id"],
            nickname="Atomic",
            vehicle_type="Car",
        )
    )
    await db_session.commit()
    yield value
    await db_session.rollback()
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.like(f"{PREFIX}%")))
    await db_session.commit()


async def _async_boom(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("boom")


def _visit_data(**overrides: Any) -> ServiceVisitCreate:
    data: dict[str, Any] = {
        "date": dt.date(2026, 6, 13),
        "odometer_km": Decimal("10000"),
        "engine_hours": Decimal("100"),
        "notes": "original",
        "line_items": [ServiceLineItemCreate(description="Oil Change", cost=Decimal("40"))],
    }
    data.update(overrides)
    return ServiceVisitCreate(**data)


async def _existing_visit(db_session: AsyncSession, vin: str) -> tuple[int, int]:
    """A committed visit with one line item, written the normal way."""
    visit = await ServiceVisitService(db_session).create_service_visit(vin, _visit_data(), None)
    return visit.id, visit.line_items[0].id


async def _visit_count(maker: async_sessionmaker[AsyncSession], vin: str) -> int:
    async with maker() as read:
        return (
            await read.execute(
                select(func.count()).select_from(ServiceVisit).where(ServiceVisit.vin == vin)
            )
        ).scalar_one()


async def _reading_counts(maker: async_sessionmaker[AsyncSession], vin: str) -> tuple[int, int]:
    """How many odometer and hours rows the vehicle has, read in a fresh session."""
    async with maker() as read:
        odo = (
            await read.execute(
                select(func.count()).select_from(OdometerRecord).where(OdometerRecord.vin == vin)
            )
        ).scalar_one()
        hours = (
            await read.execute(
                select(func.count()).select_from(HoursRecord).where(HoursRecord.vin == vin)
            )
        ).scalar_one()
    return odo, hours


async def _visit_row(maker: async_sessionmaker[AsyncSession], visit_id: int) -> ServiceVisit | None:
    async with maker() as read:
        return await read.get(ServiceVisit, visit_id)


async def _item_ids(maker: async_sessionmaker[AsyncSession], visit_id: int) -> set[int]:
    async with maker() as read:
        return set(
            (
                await read.execute(
                    select(ServiceLineItem.id).where(ServiceLineItem.visit_id == visit_id)
                )
            ).scalars()
        )


# ============================================================================
#  A failed reconcile fails the write
# ============================================================================


class TestAFailedReconcileFailsTheWrite:
    async def test_create(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        vin: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(maintenance_service, "reconcile_vehicle_unlocked", _async_boom)
        with pytest.raises(RuntimeError):
            await ServiceVisitService(db_session).create_service_visit(vin, _visit_data(), None)
        await db_session.rollback()
        # No reading either. Mutation: commit=True on the odometer sync goes red here.
        assert await _reading_counts(test_sessionmaker, vin) == (0, 0)
        # main: the visit committed before the reconcile and stays
        assert await _visit_count(test_sessionmaker, vin) == 0

    async def test_update(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        vin: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        visit_id, _ = await _existing_visit(db_session, vin)
        monkeypatch.setattr(maintenance_service, "reconcile_vehicle_unlocked", _async_boom)
        with pytest.raises(RuntimeError):
            await ServiceVisitService(db_session).update_service_visit(
                vin,
                visit_id,
                ServiceVisitUpdate(notes="edited", odometer_km=Decimal("12000")),
                None,
            )
        await db_session.rollback()
        row = await _visit_row(test_sessionmaker, visit_id)
        assert row is not None
        # main: the edit committed before the reconcile
        assert row.notes == "original"
        assert row.odometer_km == Decimal("10000")

    async def test_delete(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        vin: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        visit_id, _ = await _existing_visit(db_session, vin)
        monkeypatch.setattr(maintenance_service, "reconcile_vehicle_unlocked", _async_boom)
        with pytest.raises(RuntimeError):
            await ServiceVisitService(db_session).delete_service_visit(vin, visit_id, None)
        await db_session.rollback()
        # main: the delete committed before the reconcile
        assert await _visit_row(test_sessionmaker, visit_id) is not None

    async def test_add_line_item(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        vin: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        visit_id, item_id = await _existing_visit(db_session, vin)
        monkeypatch.setattr(maintenance_service, "reconcile_vehicle_unlocked", _async_boom)
        with pytest.raises(RuntimeError):
            await ServiceVisitService(db_session).add_line_item(
                vin, visit_id, ServiceLineItemCreate(description="Wipers"), None
            )
        await db_session.rollback()
        # main: the new item committed before the reconcile
        assert await _item_ids(test_sessionmaker, visit_id) == {item_id}

    async def test_delete_line_item(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        vin: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        visit_id, item_id = await _existing_visit(db_session, vin)
        added = await ServiceVisitService(db_session).add_line_item(
            vin, visit_id, ServiceLineItemCreate(description="Wipers"), None
        )
        # A plain int: the rollback below expires `added`.
        added_id = added.id
        monkeypatch.setattr(maintenance_service, "reconcile_vehicle_unlocked", _async_boom)
        with pytest.raises(RuntimeError):
            await ServiceVisitService(db_session).delete_line_item(vin, visit_id, added_id, None)
        await db_session.rollback()
        # main: the delete committed before the reconcile
        assert await _item_ids(test_sessionmaker, visit_id) == {item_id, added_id}


# ============================================================================
#  A failed sync fails the write
# ============================================================================


class TestAFailedSyncFailsTheWrite:
    async def test_create(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        vin: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(svs_module, "sync_hours_from_record", _async_boom)
        with pytest.raises(RuntimeError):
            await ServiceVisitService(db_session).create_service_visit(vin, _visit_data(), None)
        await db_session.rollback()
        # The odometer sync ran before the hours one blew up, and it goes too.
        # Mutation: commit=True on the odometer sync goes red here.
        assert await _reading_counts(test_sessionmaker, vin) == (0, 0)
        # main: the sync failure was logged and the visit stayed
        assert await _visit_count(test_sessionmaker, vin) == 0

    async def test_update(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        vin: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        visit_id, _ = await _existing_visit(db_session, vin)
        monkeypatch.setattr(svs_module, "sync_hours_from_record", _async_boom)
        with pytest.raises(RuntimeError):
            await ServiceVisitService(db_session).update_service_visit(
                vin,
                visit_id,
                ServiceVisitUpdate(notes="edited", engine_hours=Decimal("150")),
                None,
            )
        await db_session.rollback()
        row = await _visit_row(test_sessionmaker, visit_id)
        assert row is not None
        # main: the edit stayed with its hours row out of step
        assert row.notes == "original"
        assert row.engine_hours == Decimal("100")


# ============================================================================
#  Delete and delete-item lock before their first read
# ============================================================================


@pytest.fixture
def order(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """One list the lock and the first read both append to, in call order."""
    calls: list[str] = []
    real_lock = lock_vehicle_for_write
    real_get = ServiceVisitService.get_service_visit

    async def recording_lock(db: AsyncSession, vin: str) -> None:
        calls.append("lock")
        await real_lock(db, vin)

    async def recording_get(self: ServiceVisitService, *args: Any, **kwargs: Any) -> ServiceVisit:
        calls.append("get_service_visit")
        return await real_get(self, *args, **kwargs)

    monkeypatch.setattr(svs_module, "lock_vehicle_for_write", recording_lock)
    monkeypatch.setattr(ServiceVisitService, "get_service_visit", recording_get)
    return calls


class TestLockBeforeTheFirstRead:
    async def test_delete_visit(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        vin: str,
        order: list[str],
    ) -> None:
        visit_id, _ = await _existing_visit(db_session, vin)
        order.clear()
        await ServiceVisitService(db_session).delete_service_visit(vin, visit_id, None)
        # main: ["get_service_visit"], no lock at all
        assert order[:2] == ["lock", "get_service_visit"]
        assert order.count("lock") == 1
        assert await _visit_row(test_sessionmaker, visit_id) is None

    async def test_delete_line_item(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        vin: str,
        order: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        visit_id, item_id = await _existing_visit(db_session, vin)
        added = await ServiceVisitService(db_session).add_line_item(
            vin, visit_id, ServiceLineItemCreate(description="Wipers"), None
        )
        # The line-item lookup goes through execute too; record it by entity.
        real_execute = db_session.execute

        async def recording_execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
            descriptions: list[dict[str, Any]] = (
                getattr(statement, "column_descriptions", None) or []
            )
            if descriptions and descriptions[0].get("entity") is ServiceLineItem:
                order.append("line_item_lookup")
            return await real_execute(statement, *args, **kwargs)

        monkeypatch.setattr(db_session, "execute", recording_execute)
        order.clear()
        await ServiceVisitService(db_session).delete_line_item(vin, visit_id, added.id, None)
        # main: ["get_service_visit", "line_item_lookup"], no lock at all
        assert order[0] == "lock"
        assert "line_item_lookup" in order
        assert order.count("lock") == 1
        assert await _item_ids(test_sessionmaker, visit_id) == {item_id}


# ============================================================================
#  Guard: a normal create still writes everything
# ============================================================================


class TestNormalCreateGuard:
    async def test_create_writes_odometer_hours_and_completes_the_reminder(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        vin: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Guard: odometer row, hours row and the completed reminder, all in one commit.

        The commit count is a guard on this branch only (main committed the
        visit and its readings separately). Mutation: a commit after
        persist_visit_rows makes it two and this goes red.
        """
        service = ServiceVisitService(db_session)
        older = await service.create_service_visit(
            vin,
            _visit_data(date=dt.date(2026, 3, 16), odometer_km=Decimal("8000")),
            None,
        )
        await lock_vehicle_for_write(db_session, vin)
        rule = await maintenance_service.create_rule(
            db_session,
            vin,
            MaintenanceRuleCreate(
                title="Oil Change",
                maintenance_type="engine_oil_filter",
                interval_km=Decimal("8000"),
                interval_months=6,
            ),
        )
        await db_session.commit()
        rule_id = rule.id
        async with test_sessionmaker() as read:
            before = (
                await read.execute(
                    select(Reminder).where(
                        Reminder.rule_id == rule_id, Reminder.status == "pending"
                    )
                )
            ).scalar_one()
        assert before.line_item_id == older.line_items[0].id

        commits = 0
        real_commit = db_session.commit

        async def counting_commit() -> None:
            nonlocal commits
            commits += 1
            await real_commit()

        monkeypatch.setattr(db_session, "commit", counting_commit)
        visit = await service.create_service_visit(vin, _visit_data(), None)
        monkeypatch.setattr(db_session, "commit", real_commit)
        assert commits == 1
        visit_id, item_id = visit.id, visit.line_items[0].id

        async with test_sessionmaker() as read:
            odo = (
                await read.execute(
                    select(OdometerRecord).where(
                        OdometerRecord.vin == vin,
                        OdometerRecord.notes == auto_sync_marker("service_visit", visit_id),
                    )
                )
            ).scalar_one()
            assert odo.odometer_km == Decimal("10000")
            hours = (
                await read.execute(
                    select(HoursRecord).where(HoursRecord.service_visit_id == visit_id)
                )
            ).scalar_one()
            assert hours.engine_hours == Decimal("100")
            done = await read.get(Reminder, before.id)
            assert done is not None
            assert done.status == "done"
            assert done.completed_line_item_id == item_id
            successor = (
                await read.execute(
                    select(Reminder).where(
                        Reminder.rule_id == rule_id, Reminder.status == "pending"
                    )
                )
            ).scalar_one()
            assert successor.line_item_id == item_id
