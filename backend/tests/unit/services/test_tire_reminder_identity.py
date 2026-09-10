"""Low-tread reminders belong to a tire, not to a title string.

The defect: `_sync_low_tread_reminder` selected on `vin + title + status`
while the comment three lines above claimed it never adopts a row whose
`source` or `tire_id` is null. There was no such predicate, so a reminder a
human wrote titled "Tire tread low (FL)" was adopted, and completed, by the
sync. `Tire.position` is also nullable since migration 097, so a stored tire
produced the literal title "Tire tread low (None)", which two stored tires
then collided on.

Separately, the sync wrote `reminder_type="both"` with `due_mileage_km=None`,
which `ReminderCreate`'s validator rejects. The ORM insert bypasses that
validator, so the row landed and then refused every ordinary edit with a 422
the user could not clear.

Per-test vehicle, per the convention in
`tests/integration/routes/test_tires.py`: the suite shares one database with
no per-test rollback, so a shared VIN makes these tests order-dependent.

`_sync` re-queries the tire with `readings` and `mount_periods` eagerly
loaded before calling the service method directly, mirroring how
`TireService` loads a tire before its own `_sync_low_tread_reminder` calls.
Both relationships are `lazy="select"` on the model, and calling the sync
against a tire that still only has attributes from `add`/`refresh` raises
`MissingGreenlet` the moment `project_wear` or the response path touches
either one under async SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.models.reminder import Reminder
from app.models.tire import Tire, TireMountPeriod, TireReading
from app.models.vehicle import Vehicle
from app.schemas.reminder import ReminderCreate
from app.services.tire_service import TireService

# No `pytestmark`: pytest.ini sets `asyncio_mode = auto`.


@pytest_asyncio.fixture
async def vin(db_session, test_user):
    plate = f"TIREREM{uuid.uuid4().hex[:10].upper()}"
    db_session.add(
        Vehicle(
            vin=plate,
            user_id=test_user["id"],
            nickname="Reminder identity",
            vehicle_type="Car",
            year=2020,
            make="Honda",
            model="Accord",
        )
    )
    await db_session.commit()
    yield plate
    await db_session.execute(delete(Reminder).where(Reminder.vin == plate))
    await db_session.execute(delete(Tire).where(Tire.vin == plate))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == plate))
    await db_session.commit()


async def _tire(db_session, vin: str, *, position: str | None, tread: str) -> Tire:
    tire = Tire(
        vin=vin,
        position=position,
        tread_depth_mm=Decimal(tread),
        min_tread_mm=Decimal("2.0"),
    )
    db_session.add(tire)
    await db_session.commit()
    await db_session.refresh(tire)
    return tire


async def _pending(db_session, vin: str) -> list[Reminder]:
    return list(
        (
            await db_session.execute(
                select(Reminder)
                .where(Reminder.vin == vin, Reminder.status == "pending")
                .order_by(Reminder.id)
            )
        )
        .scalars()
        .all()
    )


async def _sync(db_session, tire: Tire) -> None:
    """Call the sync the way the service itself does: relationships loaded.

    `tire` as handed back by `add`/`commit`/`refresh` carries only column
    attributes. `_sync_low_tread_reminder` calls `project_wear`, which reads
    `tire.readings`, and a caller that goes on to build a response also reads
    `tire.mount_periods`; both are `lazy="select"` on the ORM model, so an
    unloaded access under the async engine raises `MissingGreenlet` instead
    of lazy-loading. Re-querying with `selectinload` first is what
    `tire_service.py` does before every one of its own calls into this
    method.
    """
    result = await db_session.execute(
        select(Tire)
        .where(Tire.id == tire.id)
        .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
    )
    loaded = result.scalar_one()
    await TireService(db_session)._sync_low_tread_reminder(loaded)


class TestAForeignReminderIsLeftAlone:
    async def test_a_human_authored_reminder_is_not_adopted(self, db_session, vin):
        db_session.add(
            Reminder(
                vin=vin,
                title="Tire tread low (FL)",
                reminder_type="date",
                due_date=date(2026, 12, 1),
                status="pending",
            )
        )
        await db_session.commit()

        tire = await _tire(db_session, vin, position="FL", tread="1.5")
        await _sync(db_session, tire)

        rows = await _pending(db_session, vin)
        assert len(rows) == 2
        assert [r.tire_id for r in rows] == [None, tire.id]
        assert rows[1].source == "low_tread"

    async def test_a_human_authored_reminder_is_not_completed(self, db_session, vin):
        db_session.add(
            Reminder(
                vin=vin,
                title="Tire tread low (FL)",
                reminder_type="date",
                due_date=date(2026, 12, 1),
                status="pending",
            )
        )
        await db_session.commit()

        tire = await _tire(db_session, vin, position="FL", tread="8.0")
        await _sync(db_session, tire)

        rows = await _pending(db_session, vin)
        assert len(rows) == 1
        assert rows[0].tire_id is None


class TestTheOwnedReminderFollowsTheTire:
    async def test_a_position_change_keeps_one_reminder(self, db_session, vin):
        tire = await _tire(db_session, vin, position="FL", tread="1.5")
        await _sync(db_session, tire)
        first = (await _pending(db_session, vin))[0]

        tire.position = "FR"
        await db_session.commit()
        await _sync(db_session, tire)

        rows = await _pending(db_session, vin)
        assert len(rows) == 1
        assert rows[0].id == first.id
        assert rows[0].title == "Tire tread low (FR)"

    async def test_a_stale_none_title_is_repaired(self, db_session, vin):
        tire = await _tire(db_session, vin, position="FL", tread="1.5")
        db_session.add(
            Reminder(
                vin=vin,
                tire_id=tire.id,
                source="low_tread",
                title="Tire tread low (None)",
                reminder_type="date",
                due_date=date(2026, 12, 1),
                status="pending",
            )
        )
        await db_session.commit()

        await _sync(db_session, tire)

        rows = await _pending(db_session, vin)
        assert len(rows) == 1
        assert rows[0].title == "Tire tread low (FL)"

    async def test_duplicate_owned_reminders_reconcile_to_one(self, db_session, vin):
        tire = await _tire(db_session, vin, position="FL", tread="1.5")
        for _ in range(2):
            db_session.add(
                Reminder(
                    vin=vin,
                    tire_id=tire.id,
                    source="low_tread",
                    title="Tire tread low (FL)",
                    reminder_type="date",
                    due_date=date(2026, 12, 1),
                    status="pending",
                )
            )
        await db_session.commit()

        await _sync(db_session, tire)

        assert len(await _pending(db_session, vin)) == 1


class TestStoredTires:
    async def test_two_stored_tires_get_their_own_reminders(self, db_session, vin):
        first = await _tire(db_session, vin, position=None, tread="1.5")
        second = await _tire(db_session, vin, position=None, tread="1.5")
        await _sync(db_session, first)
        await _sync(db_session, second)

        rows = await _pending(db_session, vin)
        assert len(rows) == 2
        assert {r.tire_id for r in rows} == {first.id, second.id}
        assert all("None" not in r.title for r in rows)


class TestTheReminderIsEditableAfterwards:
    async def test_a_low_tread_reminder_is_a_date_reminder(self, db_session, vin):
        """`km_remaining` is a distance REMAINING, not an absolute odometer
        target, so there is nothing to put in `due_mileage_km`. The sync
        wrote type "both" with a null mileage, which `ReminderCreate`
        rejects. The ORM insert bypasses that validator, so the row landed
        and then refused every ordinary edit with a 422 the user could not
        clear.

        The tire's own scalar tread (1.5) is at or below its 2.0 minimum, so
        C7 resolves this as `AT_OR_BELOW_MINIMUM` before the rate projection
        is ever reached; the two bounded readings below are inert for this
        path. `wear_date` comes from the newest tread-bearing reading's
        `recorded_at` rather than a resolved km-per-day figure, and is still
        non-null, which is what used to produce "both".
        """
        tire = await _tire(db_session, vin, position="FL", tread="1.5")
        db_session.add(
            TireMountPeriod(
                tire_id=tire.id,
                position="FL",
                mounted_on=date(2026, 1, 1),
                mounted_odometer_km=Decimal("9000"),
            )
        )
        for day, odo, tread in (
            (date(2026, 1, 2), "10000", "6.0"),
            (date(2026, 6, 1), "12000", "1.5"),
        ):
            db_session.add(
                TireReading(
                    tire_id=tire.id,
                    vin=vin,
                    position="FL",
                    recorded_at=day,
                    odometer_km=Decimal(odo),
                    tread_depth_mm=Decimal(tread),
                )
            )
        await db_session.commit()
        await db_session.refresh(tire)

        await _sync(db_session, tire)

        reminder = (await _pending(db_session, vin))[0]
        assert reminder.reminder_type == "date"
        assert reminder.due_mileage_km is None

        # The row must survive the ordinary write schema, which is what a
        # user edit goes through.
        ReminderCreate.model_validate(
            {
                "vin": reminder.vin,
                "title": reminder.title,
                "reminder_type": reminder.reminder_type,
                "due_date": reminder.due_date,
                "due_mileage_km": reminder.due_mileage_km,
            }
        )


class TestPreExistingInvalidRowsAreRepaired:
    """PR #161 review, finding 2. `test_a_low_tread_reminder_is_a_date_reminder`
    above only proves a NEWLY created row comes out correct: the constructor
    that sets `reminder_type="date"` and `due_mileage_km=None` runs in the
    CREATE branch (`below and existing is None`) alone. A pending row left
    over from a pre-C10 release still carries `reminder_type="both"` with a
    null `due_mileage_km`, which `ReminderCreate` rejects, and because that
    row already exists this release's editability fix never touches it --
    every later branch only sets `status` or `title`. So an upgrading owner
    with an existing low-tread reminder still gets a 422 on an ordinary
    edit, even though the CHANGELOG says this is fixed.
    """

    async def test_a_pending_both_type_reminder_is_normalized_on_sync(self, db_session, vin):
        tire = await _tire(db_session, vin, position="FL", tread="1.5")
        db_session.add(
            Reminder(
                vin=vin,
                tire_id=tire.id,
                source="low_tread",
                title="Tire tread low (FL)",
                reminder_type="both",
                due_date=date(2026, 12, 1),
                due_mileage_km=None,
                status="pending",
            )
        )
        await db_session.commit()

        # The tire stays below threshold across this sync and the title
        # already matches, so neither the create nor the rename branch
        # would touch this row on its own -- the normalization has to run
        # independently of both.
        await _sync(db_session, tire)

        rows = await _pending(db_session, vin)
        assert len(rows) == 1
        reminder = rows[0]
        assert reminder.reminder_type == "date"
        assert reminder.due_mileage_km is None

        # Proves editability, not just field values: the row must survive
        # the same write schema an ordinary user PUT goes through.
        ReminderCreate.model_validate(
            {
                "vin": reminder.vin,
                "title": reminder.title,
                "reminder_type": reminder.reminder_type,
                "due_date": reminder.due_date,
                "due_mileage_km": reminder.due_mileage_km,
            }
        )
