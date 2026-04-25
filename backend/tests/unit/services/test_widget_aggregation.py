"""Unit tests for WidgetAggregationService.

Focused on two risks Codex flagged:

1. Fan-out regression: counts across child tables must stay exact when a VIN
   has records in more than one child table. If the service ever migrates to
   a multi-LEFT-JOIN query, these tests catch the cartesian explosion.
2. MPG parity: the window-function/bounded-lookback MPG must produce the same
   numbers as `fuel_service.calculate_l_per_100km` (converted to MPG) +
   `get_previous_full_tank` given identical inputs, including every exclusion
   branch. Storage is metric (odometer_km/liters); the widget layer is the
   LEGACY-COMPAT surface that emits MPG/miles for clients that haven't
   migrated yet.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.document import Document
from app.models.fuel import FuelRecord
from app.models.note import Note
from app.models.odometer import OdometerRecord
from app.models.photo import VehiclePhoto
from app.models.reminder import Reminder
from app.models.service_visit import ServiceVisit
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.fuel_service import calculate_l_per_100km
from app.services.widget_aggregation import WidgetAggregationService


# Conversion helpers — all storage is metric, but legacy widget output is imperial.
def _mi_to_km(miles: float | int) -> Decimal:
    return Decimal(str(round(float(miles) * 1.60934, 2)))


def _gal_to_l(gallons: float | int | Decimal) -> Decimal:
    return Decimal(str(round(float(gallons) * 3.78541, 2)))


TEST_PASSWORD_HASH = (
    "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw"
    "$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
)


def _unique_vin() -> str:
    """Return a 17-char test VIN. Unique-per-test to avoid fixture collisions."""
    return ("WAG" + uuid.uuid4().hex)[:17].upper()


@pytest_asyncio.fixture
async def aggregation_user(db_session) -> User:
    """Owner of every vehicle seeded in these tests."""
    result = await db_session.execute(select(User).where(User.username == "widget_agg_user"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            username="widget_agg_user",
            email="widget_agg_user@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
    return user


async def _make_vehicle(db_session, user: User, **overrides) -> Vehicle:
    vehicle = Vehicle(
        vin=overrides.get("vin", _unique_vin()),
        nickname=overrides.get("nickname", "Test Vehicle"),
        vehicle_type=overrides.get("vehicle_type", "Car"),
        user_id=user.id,
        year=overrides.get("year", 2022),
        make=overrides.get("make", "Honda"),
        model=overrides.get("model", "Civic"),
        archived_at=overrides.get("archived_at"),
    )
    db_session.add(vehicle)
    await db_session.commit()
    await db_session.refresh(vehicle)
    return vehicle


class TestFanOutRegression:
    """If someone later rewrites summary() as a multi-LEFT-JOIN, these fail fast."""

    @pytest.mark.asyncio
    async def test_counts_are_exact_across_multiple_child_tables(
        self, db_session, aggregation_user
    ):
        vehicle = await _make_vehicle(db_session, aggregation_user)
        vin = vehicle.vin

        # Intentionally mismatched non-prime counts so a cartesian fan-out would
        # produce numbers that don't equal any of N, M, P, Q individually.
        n_service, n_fuel, n_docs, n_notes = 4, 6, 3, 5
        for i in range(n_service):
            db_session.add(ServiceVisit(vin=vin, date=date(2026, 1, 1) + timedelta(days=i)))
        for i in range(n_fuel):
            db_session.add(
                FuelRecord(
                    vin=vin,
                    date=date(2026, 2, 1) + timedelta(days=i),
                    odometer_km=_mi_to_km(10000 + i * 300),
                    liters=_gal_to_l(Decimal("10.0")),
                    price_per_unit=Decimal("3.50"),
                    cost=Decimal("35.00"),
                    is_full_tank=True,
                )
            )
        for i in range(n_docs):
            db_session.add(
                Document(
                    vin=vin,
                    title=f"doc {i}",
                    file_name=f"doc_{i}.pdf",
                    file_path=f"/fake/{i}.pdf",
                    file_size=100,
                    mime_type="application/pdf",
                )
            )
        for i in range(n_notes):
            db_session.add(
                Note(
                    vin=vin,
                    date=date(2026, 3, 1) + timedelta(days=i),
                    title=f"note {i}",
                    content="body",
                )
            )
        await db_session.commit()

        svc = WidgetAggregationService(db_session)
        summary = await svc.summary(aggregation_user.id, allowed_vins=None)

        assert summary.total_service_records == n_service
        assert summary.total_fuel_records == n_fuel
        assert summary.total_documents == n_docs
        assert summary.total_notes == n_notes
        assert summary.total_vehicles == 1

    @pytest.mark.asyncio
    async def test_per_vehicle_counts_are_exact(self, db_session, aggregation_user):
        vehicle = await _make_vehicle(db_session, aggregation_user)
        vin = vehicle.vin

        n_service, n_fuel = 3, 7
        for i in range(n_service):
            db_session.add(ServiceVisit(vin=vin, date=date(2026, 1, 1) + timedelta(days=i)))
        for i in range(n_fuel):
            db_session.add(
                FuelRecord(
                    vin=vin,
                    date=date(2026, 2, 1) + timedelta(days=i),
                    odometer_km=_mi_to_km(20000 + i * 300),
                    liters=_gal_to_l(Decimal("10.0")),
                    price_per_unit=Decimal("3.50"),
                    cost=Decimal("35.00"),
                    is_full_tank=True,
                )
            )
        await db_session.commit()

        svc = WidgetAggregationService(db_session)
        result = await svc.vehicle(aggregation_user.id, vin, allowed_vins=None)

        assert result is not None
        assert result.service_records == n_service
        assert result.fuel_records == n_fuel


class TestMpgParity:
    """Widget MPG must match fuel_service.calculate_mpg, branch by branch."""

    @pytest.mark.asyncio
    async def test_numeric_parity_with_calculate_mpg(self, db_session, aggregation_user):
        vehicle = await _make_vehicle(db_session, aggregation_user)
        vin = vehicle.vin

        # Three full-tank fills, monotonically increasing mileage. Two
        # calculable pairs -> recent = avg of 2 pairs, average = same here.
        records = [
            FuelRecord(
                vin=vin,
                date=date(2026, 1, 1),
                odometer_km=_mi_to_km(10000),
                liters=_gal_to_l(Decimal("10.0")),
                price_per_unit=Decimal("3.50"),
                cost=Decimal("35.00"),
                is_full_tank=True,
            ),
            FuelRecord(
                vin=vin,
                date=date(2026, 1, 15),
                odometer_km=_mi_to_km(10300),  # +300 mi / 10 gal = 30.0 MPG
                liters=_gal_to_l(Decimal("10.0")),
                price_per_unit=Decimal("3.50"),
                cost=Decimal("35.00"),
                is_full_tank=True,
            ),
            FuelRecord(
                vin=vin,
                date=date(2026, 1, 30),
                odometer_km=_mi_to_km(10620),  # +320 mi / 8 gal = 40.0 MPG
                liters=_gal_to_l(Decimal("8.0")),
                price_per_unit=Decimal("3.50"),
                cost=Decimal("28.00"),
                is_full_tank=True,
            ),
        ]
        for r in records:
            db_session.add(r)
        await db_session.commit()

        svc = WidgetAggregationService(db_session)
        result = await svc.vehicle(aggregation_user.id, vin, allowed_vins=None)

        # Reference: pairwise calculate_l_per_100km() on the same data,
        # converted back to MPG for the legacy widget contract.
        # 10000→10300 mi (30 MPG) → 7.84 L/100km
        # 10300→10620 mi (40 MPG) → 5.88 L/100km
        ref_newest = calculate_l_per_100km(records[2], records[1])
        ref_second = calculate_l_per_100km(records[1], records[0])
        assert ref_newest is not None
        assert ref_second is not None
        # Lower L/100km = better fuel economy
        assert ref_newest < ref_second

        assert result is not None
        # Widget averages L/100km first then converts to MPG, so the legacy
        # output is the MPG equivalent of the harmonic mean — not 35.0.
        # Two pairs at 30 MPG (7.84 L/100km) and 40 MPG (5.88 L/100km)
        # → mean L/100km ≈ 6.86 → MPG ≈ 34.3.
        assert result.recent_mpg == pytest.approx(34.3, abs=0.1)
        assert result.average_mpg == pytest.approx(34.3, abs=0.1)

    @pytest.mark.asyncio
    async def test_partial_tank_excluded(self, db_session, aggregation_user):
        """Non-full-tank records must not contribute to MPG — matches calculate_mpg guard."""
        vehicle = await _make_vehicle(db_session, aggregation_user)
        vin = vehicle.vin

        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 1),
                    odometer_km=_mi_to_km(10000),
                    liters=_gal_to_l(Decimal("10.0")),
                    price_per_unit=Decimal("3.50"),
                    cost=Decimal("35.00"),
                    is_full_tank=True,
                ),
                # Partial tank between the two full tanks — ignored.
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 10),
                    odometer_km=_mi_to_km(10100),
                    liters=_gal_to_l(Decimal("5.0")),
                    price_per_unit=Decimal("3.50"),
                    cost=Decimal("17.50"),
                    is_full_tank=False,
                ),
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 20),
                    odometer_km=_mi_to_km(
                        10300
                    ),  # Pair is (10300, 10000); +300 / 10 gal = 30.0 MPG
                    liters=_gal_to_l(Decimal("10.0")),
                    price_per_unit=Decimal("3.50"),
                    cost=Decimal("35.00"),
                    is_full_tank=True,
                ),
            ]
        )
        await db_session.commit()

        svc = WidgetAggregationService(db_session)
        result = await svc.vehicle(aggregation_user.id, vin, allowed_vins=None)
        assert result is not None
        assert result.recent_mpg == pytest.approx(30.0)

    @pytest.mark.asyncio
    async def test_zero_distance_pair_excluded(self, db_session, aggregation_user):
        """Pair with non-positive distance must return None, same as calculate_mpg."""
        vehicle = await _make_vehicle(db_session, aggregation_user)
        vin = vehicle.vin

        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 1),
                    odometer_km=_mi_to_km(10000),
                    liters=_gal_to_l(Decimal("10.0")),
                    price_per_unit=Decimal("3.50"),
                    cost=Decimal("35.00"),
                    is_full_tank=True,
                ),
                # Same mileage on the second record -> distance == 0 -> excluded.
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 10),
                    odometer_km=_mi_to_km(10000),
                    liters=_gal_to_l(Decimal("10.0")),
                    price_per_unit=Decimal("3.50"),
                    cost=Decimal("35.00"),
                    is_full_tank=True,
                ),
            ]
        )
        await db_session.commit()

        svc = WidgetAggregationService(db_session)
        result = await svc.vehicle(aggregation_user.id, vin, allowed_vins=None)
        assert result is not None
        assert result.recent_mpg is None
        assert result.average_mpg is None

    @pytest.mark.asyncio
    async def test_no_prior_record_returns_none(self, db_session, aggregation_user):
        """A single fill-up can't produce MPG, matching get_previous_full_tank → None."""
        vehicle = await _make_vehicle(db_session, aggregation_user)
        vin = vehicle.vin

        db_session.add(
            FuelRecord(
                vin=vin,
                date=date(2026, 1, 1),
                odometer_km=_mi_to_km(10000),
                liters=_gal_to_l(Decimal("10.0")),
                price_per_unit=Decimal("3.50"),
                cost=Decimal("35.00"),
                is_full_tank=True,
            )
        )
        await db_session.commit()

        svc = WidgetAggregationService(db_session)
        result = await svc.vehicle(aggregation_user.id, vin, allowed_vins=None)
        assert result is not None
        assert result.recent_mpg is None
        assert result.average_mpg is None

    @pytest.mark.asyncio
    async def test_average_bounded_to_last_10(self, db_session, aggregation_user):
        """Older fill-ups beyond the 10-record window must not drift the average.

        Seed 20 fill-ups with two distinct MPG values: the first 10 (newest by
        date) exercise 20 MPG and the last 10 exercise 10 MPG. Average MUST
        equal the newest block's value, not a blend.
        """
        vehicle = await _make_vehicle(db_session, aggregation_user)
        vin = vehicle.vin

        # Build newest-first so date ordering is clear, then insert.
        # Newest 10 pairs produce 20 MPG, next 10 produce 10 MPG.
        records = []
        # 10 older records at 10 MPG (100 mi step, 10 gal)
        # 11 newer records at 20 MPG (200 mi step, 10 gal)
        # → 10 pairs within the NEW block are all 20 MPG.
        # Transition pair (oldest-new -> newest-old) is outside the last-10 window,
        # so the average must stay 20 — proving the bound works.
        mileage = 50000
        day = date(2025, 1, 1)
        for _ in range(10):
            records.append(
                FuelRecord(
                    vin=vin,
                    date=day,
                    odometer_km=_mi_to_km(mileage),
                    liters=_gal_to_l(Decimal("10.0")),
                    price_per_unit=Decimal("3.50"),
                    cost=Decimal("35.00"),
                    is_full_tank=True,
                )
            )
            mileage += 100
            day += timedelta(days=30)
        for _ in range(11):
            records.append(
                FuelRecord(
                    vin=vin,
                    date=day,
                    odometer_km=_mi_to_km(mileage),
                    liters=_gal_to_l(Decimal("10.0")),
                    price_per_unit=Decimal("3.50"),
                    cost=Decimal("35.00"),
                    is_full_tank=True,
                )
            )
            mileage += 200
            day += timedelta(days=30)

        db_session.add_all(records)
        await db_session.commit()

        svc = WidgetAggregationService(db_session)
        result = await svc.vehicle(aggregation_user.id, vin, allowed_vins=None)
        assert result is not None
        # Recent 3 are all 20 MPG
        assert result.recent_mpg == pytest.approx(20.0)
        # Average bounded to last 10 → all 20 MPG; the older 10-MPG block is dropped.
        assert result.average_mpg == pytest.approx(20.0)


class TestScopingAndAccessChecks:
    """Ownership filter must be enforced at request time, per plan."""

    @pytest.mark.asyncio
    async def test_summary_does_not_count_other_users_vehicles(self, db_session, aggregation_user):
        # Session-scoped fixtures mean data from earlier tests persists; use a
        # baseline/delta comparison so we can run in any order.
        svc = WidgetAggregationService(db_session)
        baseline = await svc.summary(aggregation_user.id, allowed_vins=None)

        other = User(
            username=f"widget_agg_other_{uuid.uuid4().hex[:8]}",
            email=f"widget_agg_other_{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
        )
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)

        mine = await _make_vehicle(db_session, aggregation_user)
        theirs = await _make_vehicle(db_session, other)
        db_session.add(ServiceVisit(vin=mine.vin, date=date(2026, 1, 1)))
        db_session.add(ServiceVisit(vin=theirs.vin, date=date(2026, 1, 1)))
        await db_session.commit()

        after = await svc.summary(aggregation_user.id, allowed_vins=None)
        # Only MY service visit should be reflected in MY delta — theirs stays invisible.
        assert after.total_service_records - baseline.total_service_records == 1
        assert after.total_vehicles - baseline.total_vehicles == 1

    @pytest.mark.asyncio
    async def test_vehicle_returns_none_for_unowned_vin(self, db_session, aggregation_user):
        # A vehicle owned by someone else.
        other = User(
            username=f"widget_agg_other2_{uuid.uuid4().hex[:8]}",
            email=f"widget_agg_other2_{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
        )
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        theirs = await _make_vehicle(db_session, other)

        svc = WidgetAggregationService(db_session)
        result = await svc.vehicle(aggregation_user.id, theirs.vin, allowed_vins=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_vehicle_returns_none_when_outside_allowed_vins(
        self, db_session, aggregation_user
    ):
        vehicle = await _make_vehicle(db_session, aggregation_user)
        svc = WidgetAggregationService(db_session)
        # The key scope excludes this VIN even though the user owns it.
        result = await svc.vehicle(
            aggregation_user.id, vehicle.vin, allowed_vins=["1OTHERVIN00000000"]
        )
        assert result is None


class TestReminderClassification:
    """Mirrors the Python overdue derivation in routes/dashboard.py."""

    @pytest.mark.asyncio
    async def test_overdue_vs_upcoming_by_date_and_mileage(self, db_session, aggregation_user):
        vehicle = await _make_vehicle(db_session, aggregation_user)
        vin = vehicle.vin

        # Current odometer = 50000; reminders due at/under 50000 by mileage are overdue.
        db_session.add(
            OdometerRecord(
                vin=vin, date=date.today(), odometer_km=_mi_to_km(50000), source="manual"
            )
        )

        past = date.today() - timedelta(days=5)
        future = date.today() + timedelta(days=30)

        db_session.add_all(
            [
                Reminder(
                    vin=vin,
                    title="overdue by date",
                    reminder_type="date",
                    due_date=past,
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="overdue by mileage",
                    reminder_type="mileage",
                    due_mileage_km=_mi_to_km(40000),
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="upcoming",
                    reminder_type="date",
                    due_date=future,
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="upcoming mileage",
                    reminder_type="mileage",
                    due_mileage_km=_mi_to_km(60000),
                    status="pending",
                ),
                # A completed reminder must be ignored.
                Reminder(
                    vin=vin,
                    title="already done",
                    reminder_type="date",
                    due_date=past,
                    status="completed",
                ),
            ]
        )
        await db_session.commit()

        svc = WidgetAggregationService(db_session)
        result = await svc.vehicle(aggregation_user.id, vin, allowed_vins=None)
        assert result is not None
        assert result.overdue_maintenance == 2
        assert result.upcoming_maintenance == 2


class TestListVehicles:
    @pytest.mark.asyncio
    async def test_list_respects_scope(self, db_session, aggregation_user):
        v1 = await _make_vehicle(db_session, aggregation_user)
        v2 = await _make_vehicle(db_session, aggregation_user)

        svc = WidgetAggregationService(db_session)

        all_vehicles = await svc.list_vehicles(aggregation_user.id, allowed_vins=None)
        returned_vins = {v.vin for v in all_vehicles}
        assert v1.vin in returned_vins
        assert v2.vin in returned_vins

        scoped = await svc.list_vehicles(aggregation_user.id, allowed_vins=[v1.vin])
        assert [v.vin for v in scoped] == [v1.vin]


class TestPhotoCountFromDb:
    """V1 switched photo count from filesystem to photos table. Verify."""

    @pytest.mark.asyncio
    async def test_photos_counted_from_table(self, db_session, aggregation_user):
        vehicle = await _make_vehicle(db_session, aggregation_user)
        vin = vehicle.vin

        for i in range(3):
            db_session.add(VehiclePhoto(vin=vin, file_path=f"/fake/{vin}/p{i}.jpg"))
        await db_session.commit()

        svc = WidgetAggregationService(db_session)
        result = await svc.vehicle(aggregation_user.id, vin, allowed_vins=None)
        assert result is not None
        assert result.photos == 3
        summary = await svc.summary(aggregation_user.id, allowed_vins=None)
        assert summary.total_photos == 3


class TestArchiveVisibility:
    """Archived vehicles with archived_visible=False must not appear in widgets."""

    @pytest.mark.asyncio
    async def test_vehicle_lookup_excludes_hidden_archive(self, db_session, aggregation_user):
        from datetime import datetime

        hidden = await _make_vehicle(db_session, aggregation_user, archived_at=datetime(2026, 1, 1))
        hidden.archived_visible = False
        await db_session.commit()

        svc = WidgetAggregationService(db_session)
        result = await svc.vehicle(aggregation_user.id, hidden.vin, allowed_vins=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_excludes_hidden_archive(self, db_session, aggregation_user):
        from datetime import datetime

        hidden = await _make_vehicle(db_session, aggregation_user, archived_at=datetime(2026, 1, 1))
        hidden.archived_visible = False
        await db_session.commit()

        svc = WidgetAggregationService(db_session)
        vins = [v.vin for v in await svc.list_vehicles(aggregation_user.id, allowed_vins=None)]
        assert hidden.vin not in vins

    @pytest.mark.asyncio
    async def test_visible_archive_still_counted(self, db_session, aggregation_user):
        """Archived-but-visible must still appear (matches dashboard behavior)."""
        from datetime import datetime

        visible_archive = await _make_vehicle(
            db_session, aggregation_user, archived_at=datetime(2026, 1, 1)
        )
        # archived_visible defaults to True on the model.
        svc = WidgetAggregationService(db_session)
        result = await svc.vehicle(aggregation_user.id, visible_archive.vin, allowed_vins=None)
        assert result is not None

    @pytest.mark.asyncio
    async def test_summary_counts_only_visible_vehicles(self, db_session, aggregation_user):
        from datetime import datetime

        svc = WidgetAggregationService(db_session)
        baseline = await svc.summary(aggregation_user.id, allowed_vins=None)

        hidden = await _make_vehicle(db_session, aggregation_user, archived_at=datetime(2026, 1, 1))
        hidden.archived_visible = False
        await db_session.commit()

        after = await svc.summary(aggregation_user.id, allowed_vins=None)
        # Hidden archive adds nothing to totals.
        assert after.total_vehicles == baseline.total_vehicles
        assert after.archived_vehicles == baseline.archived_vehicles
