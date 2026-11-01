"""
Unit tests for hours_service — the ONE canonical "latest engine hours" helper.

Every consumer (detail-stats, hero/card, reminders, widget, analytics, PDF)
must call ``latest_engine_hours_and_date`` — see the hours-usage-model plan
§1. A physical hour-meter is monotonic, so "current" means the MAX reading
on record, not the most recently dated one; ties break to newest date, then
highest id.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HoursRecord, Vehicle
from app.models.fuel import FuelRecord
from app.services.hours_service import latest_engine_hours_and_date, set_manual_current_hours

# clean_hours_records is a shared fixture in tests/unit/conftest.py (also
# used by tests/unit/utils/test_hours_sync.py).


async def _add_hours_record(
    db_session: AsyncSession, vin: str, reading_date: date, engine_hours: Decimal
) -> HoursRecord:
    record = HoursRecord(vin=vin, date=reading_date, engine_hours=engine_hours, source="manual")
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


@pytest.mark.unit
@pytest.mark.asyncio
class TestLatestEngineHoursAndDate:
    """Test the deterministic latest-hours selection."""

    async def test_empty_vehicle_returns_none_none(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        engine_hours, reading_date = await latest_engine_hours_and_date(
            db_session, test_vehicle["vin"]
        )
        assert engine_hours is None
        assert reading_date is None

    async def test_returns_max_reading_even_when_later_date_is_lower(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        """Non-monotonic history: a later date with a LOWER reading must lose.

        e.g. a correction/manual backdated entry shouldn't make "current
        hours" appear to go backwards — the highest physical reading wins.
        """
        vin = test_vehicle["vin"]
        await _add_hours_record(db_session, vin, date(2024, 1, 1), Decimal("500.0"))
        await _add_hours_record(db_session, vin, date(2024, 6, 1), Decimal("120.0"))

        engine_hours, reading_date = await latest_engine_hours_and_date(db_session, vin)

        assert engine_hours == Decimal("500.0")
        assert reading_date == date(2024, 1, 1)

    async def test_tie_on_engine_hours_breaks_to_newest_date(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        vin = test_vehicle["vin"]
        await _add_hours_record(db_session, vin, date(2024, 1, 1), Decimal("300.0"))
        await _add_hours_record(db_session, vin, date(2024, 3, 1), Decimal("300.0"))

        engine_hours, reading_date = await latest_engine_hours_and_date(db_session, vin)

        assert engine_hours == Decimal("300.0")
        assert reading_date == date(2024, 3, 1)

    async def test_tie_on_engine_hours_and_date_resolves_to_one_deterministic_row(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        """A full (engine_hours, date) tie across multiple ids never raises and
        always returns exactly that tied value pair (id DESC is the final,
        deterministic tie-break — unobservable in the return shape here since
        both candidate rows carry identical engine_hours/date, but the query
        must resolve to a SINGLE row, not error on multiple matches)."""
        vin = test_vehicle["vin"]
        await _add_hours_record(db_session, vin, date(2024, 4, 1), Decimal("400.0"))
        await _add_hours_record(db_session, vin, date(2024, 4, 1), Decimal("400.0"))

        engine_hours, reading_date = await latest_engine_hours_and_date(db_session, vin)

        assert engine_hours == Decimal("400.0")
        assert reading_date == date(2024, 4, 1)

    async def test_other_vehicle_readings_do_not_leak(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        """The helper is vin-scoped — a higher reading on another vin must not win."""
        vin = test_vehicle["vin"]
        other_vin = "1FTFW1ET1EFA00001"

        # HoursRecord.vin FKs to vehicles.vin (FK enforcement is ON in tests,
        # mirroring prod's PRAGMA foreign_keys=ON), so the other vin needs a
        # real parent row.
        other_vehicle = Vehicle(vin=other_vin, nickname="Other Vehicle", vehicle_type="Car")
        db_session.add(other_vehicle)
        await db_session.commit()

        await _add_hours_record(db_session, vin, date(2024, 1, 1), Decimal("50.0"))
        await _add_hours_record(db_session, other_vin, date(2024, 1, 1), Decimal("9999.0"))

        engine_hours, reading_date = await latest_engine_hours_and_date(db_session, vin)

        assert engine_hours == Decimal("50.0")
        assert reading_date == date(2024, 1, 1)

        # Cleanup — HoursRecord/Vehicle FK is ON DELETE CASCADE, so removing
        # the vehicle takes its hours row with it.
        await db_session.delete(other_vehicle)
        await db_session.commit()


@pytest.mark.unit
@pytest.mark.asyncio
class TestSetManualCurrentHours:
    """R2-H1: the current_hours-retirement interception target.

    ``services/vehicle_service.py`` pops ``current_hours`` out of the
    create/update setattr path and routes it here instead, so a submitted
    reading lands in the authoritative ``hours_records`` history that
    ``latest_engine_hours_and_date`` derives "current" from.
    """

    async def test_creates_todays_manual_row_when_absent(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        vin = test_vehicle["vin"]
        record = await set_manual_current_hours(db_session, vin, Decimal("123.5"))
        await db_session.commit()

        assert record.vin == vin
        assert record.date == date.today()
        assert record.engine_hours == Decimal("123.5")
        assert record.source == "manual"
        assert record.fuel_record_id is None
        assert record.service_visit_id is None

        latest, latest_date = await latest_engine_hours_and_date(db_session, vin)
        assert latest == Decimal("123.5")
        assert latest_date == date.today()

    async def test_repeated_same_day_call_updates_the_same_row_not_a_second(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        """The idempotency guarantee: PUT twice same day -> ONE row, updated.

        Two vehicle-update calls on the same day must never proliferate
        manual hours rows.
        """
        vin = test_vehicle["vin"]
        first = await set_manual_current_hours(db_session, vin, Decimal("100.0"))
        await db_session.commit()
        second = await set_manual_current_hours(db_session, vin, Decimal("150.0"))
        await db_session.commit()

        assert first.id == second.id
        assert second.engine_hours == Decimal("150.0")

        rows = (
            (
                await db_session.execute(
                    select(HoursRecord).where(
                        HoursRecord.vin == vin, HoursRecord.source == "manual"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].engine_hours == Decimal("150.0")

        # A third call the same day still updates the SAME single row.
        third = await set_manual_current_hours(db_session, vin, Decimal("175.3"))
        await db_session.commit()
        assert third.id == first.id
        rows_after_third = (
            (
                await db_session.execute(
                    select(HoursRecord).where(
                        HoursRecord.vin == vin, HoursRecord.source == "manual"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows_after_third) == 1
        assert rows_after_third[0].engine_hours == Decimal("175.3")

    async def test_does_not_match_or_overwrite_a_synced_row_same_day(
        self, db_session: AsyncSession, own_vehicle
    ):
        """A fuel-synced row on the SAME day carries a non-null FK, so the
        manual upsert's identity filter (both FKs null) must not match it —
        it creates its OWN manual row instead, leaving the synced row alone."""
        vin = own_vehicle.vin
        fuel = FuelRecord(vin=vin, date=date.today(), liters=Decimal("10.000"))
        db_session.add(fuel)
        await db_session.commit()

        synced = HoursRecord(
            vin=vin,
            date=date.today(),
            engine_hours=Decimal("50.0"),
            source="fuel",
            fuel_record_id=fuel.id,
        )
        db_session.add(synced)
        await db_session.commit()

        manual = await set_manual_current_hours(db_session, vin, Decimal("60.0"))
        await db_session.commit()

        assert manual.id != synced.id
        assert manual.source == "manual"

        rows = (
            (await db_session.execute(select(HoursRecord).where(HoursRecord.vin == vin)))
            .scalars()
            .all()
        )
        assert len(rows) == 2
        synced_row = next(r for r in rows if r.id == synced.id)
        assert synced_row.engine_hours == Decimal("50.0"), "synced row must be untouched"

    async def test_tolerates_multiple_same_day_manual_rows(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        """Regression: the manual-hours CRUD endpoint (POST
        /api/vehicles/{vin}/hours) has no same-day uniqueness guard, so a
        user can log TWO manual readings dated today before ever touching
        the vehicle-update current_hours upsert. The old
        ``scalar_one_or_none()`` lookup raised ``MultipleResultsFound`` the
        moment it saw both rows — an unhandled 500 on a core vehicle CRUD
        path. It must instead deterministically pick the NEWEST (highest
        id) of the two, update it in place, and not create a third row."""
        vin = test_vehicle["vin"]
        older = await _add_hours_record(db_session, vin, date.today(), Decimal("10.0"))
        newer = await _add_hours_record(db_session, vin, date.today(), Decimal("20.0"))
        assert newer.id > older.id

        updated = await set_manual_current_hours(db_session, vin, Decimal("30.0"))
        await db_session.commit()

        assert updated.id == newer.id, "the newest same-day manual row must be the one updated"
        assert updated.engine_hours == Decimal("30.0")

        rows = (
            (
                await db_session.execute(
                    select(HoursRecord).where(
                        HoursRecord.vin == vin, HoursRecord.source == "manual"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2, "no third row should be created"
        older_row = next(r for r in rows if r.id == older.id)
        assert older_row.engine_hours == Decimal("10.0"), "the older row must be left untouched"

    async def test_commit_true_commits_and_refreshes(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        """The commit flag mirrors hours_sync's contract: True commits+refreshes
        within its own unit of work (default False composes into a caller's
        transaction — see vehicle_service.py's create/update paths)."""
        vin = test_vehicle["vin"]
        record = await set_manual_current_hours(db_session, vin, Decimal("42.0"), commit=True)

        assert record.id is not None
        latest, _ = await latest_engine_hours_and_date(db_session, vin)
        assert latest == Decimal("42.0")
