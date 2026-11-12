"""
Integration tests for the ownership statistics block on vehicle analytics.

The block mirrors an at-a-glance summary (Overall / Fuel-Ups / Services &
Expenses). Every figure is checked against arithmetic done by hand from a small
fixture, so a change to what is counted, or to the denominator, fails here.
"""

import datetime as dt
import uuid
from collections.abc import AsyncGenerator
from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelRecord, OdometerRecord, ServiceVisit, Vehicle
from app.models.insurance import InsurancePolicy, InsurancePolicyVehicle
from app.models.service_line_item import ServiceLineItem
from app.models.tax import TaxRecord
from app.utils.household_time import household_today


def _dec(value: str | None) -> Decimal:
    assert value is not None
    return Decimal(value)


class _Garage:
    """Makes the vehicles and policies a test needs and deletes them afterwards.

    Policies are household-wide, so one left behind would land in every later
    test's insurance totals.
    """

    def __init__(self, db: AsyncSession, user: dict[str, object]) -> None:
        self.db = db
        self.user = user
        self.vins: list[str] = []
        self.policy_ids: list[int] = []

    async def vehicle(
        self,
        *,
        vehicle_type: str = "Car",
        purchase_price: Decimal | None = Decimal("1000.00"),
        purchase_days_ago: int | None = 100,
    ) -> str:
        today = household_today()
        vin = "STA" + uuid.uuid4().hex[:14].upper()
        self.db.add(
            Vehicle(
                vin=vin,
                user_id=self.user["id"],
                nickname="Statistics Vehicle",
                vehicle_type=vehicle_type,
                year=2012,
                make="Chevrolet",
                model="Cruze",
                fuel_type="gas",
                purchase_price=purchase_price,
                purchase_date=today - timedelta(days=purchase_days_ago)
                if purchase_days_ago is not None
                else None,
            )
        )
        await self.db.commit()
        self.vins.append(vin)
        return vin

    async def policy(
        self,
        vin: str,
        *,
        number: str,
        start: dt.date,
        end: dt.date,
        premium: Decimal,
        frequency: str,
    ) -> None:
        policy = InsurancePolicy(
            provider="Test Insurer",
            policy_number=number,
            start_date=start,
            end_date=end,
            premium_amount=premium,
            premium_frequency=frequency,
        )
        self.db.add(policy)
        await self.db.flush()
        self.policy_ids.append(policy.id)
        self.db.add(
            InsurancePolicyVehicle(
                policy_id=policy.id, vin=vin, policy_type="Full Coverage", premium_share=premium
            )
        )
        await self.db.commit()

    async def cleanup(self) -> None:
        # A failed request can leave the session mid-transaction.
        await self.db.rollback()
        if self.policy_ids:
            await self.db.execute(
                delete(InsurancePolicy).where(InsurancePolicy.id.in_(self.policy_ids))
            )
        for vin in self.vins:
            stored = await self.db.get(Vehicle, vin)
            if stored is not None:
                await self.db.delete(stored)
        await self.db.commit()


@pytest_asyncio.fixture
async def garage(db_session: AsyncSession, test_user: dict[str, object]) -> AsyncGenerator[_Garage]:
    made = _Garage(db_session, test_user)
    yield made
    await made.cleanup()


@pytest_asyncio.fixture
async def stats_vehicle(db_session: AsyncSession, garage: _Garage) -> str:
    """A vehicle with fuel, one service, one registration and one live policy.

    Fills (day offset, odometer km, litres, cost) give prices per litre of
    1.00, 1.20, 1.10 and 1.20, a 1,600 km span, 115 L and $127.00 of fuel.
    """
    vin = await garage.vehicle()
    today = household_today()

    for days_ago, odo, liters, cost in [
        (90, "1000.00", "40.000", "40.00"),
        (60, "1500.00", "20.000", "24.00"),
        (30, "2100.00", "30.000", "33.00"),
        (5, "2600.00", "25.000", "30.00"),
    ]:
        db_session.add(
            FuelRecord(
                vin=vin,
                date=today - timedelta(days=days_ago),
                odometer_km=Decimal(odo),
                liters=Decimal(liters),
                cost=Decimal(cost),
                is_full_tank=True,
            )
        )

    visit = ServiceVisit(vin=vin, date=today - timedelta(days=45))
    db_session.add(visit)
    await db_session.flush()
    db_session.add(
        ServiceLineItem(visit_id=visit.id, description="Oil change", cost=Decimal("50.00"))
    )

    db_session.add(
        TaxRecord(
            vin=vin,
            date=today - timedelta(days=80),
            tax_type="Registration",
            amount=Decimal("30.00"),
        )
    )
    await db_session.commit()

    # A 180-day term, 100 days elapsed. Accrual counts "up to and including
    # today", so 101 of the 180 days: 180 * 101 / 180 = 101.00.
    await garage.policy(
        vin,
        number="P-1",
        start=today - timedelta(days=100),
        end=today + timedelta(days=80),
        premium=Decimal("180.00"),
        frequency="Semi-Annual",
    )
    return vin


@pytest.mark.asyncio
class TestOwnershipStatistics:
    async def _stats(self, client: AsyncClient, auth_headers, vin: str) -> dict:
        resp = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        stats = resp.json()["statistics"]
        assert stats is not None
        return stats

    async def test_overall_block(self, client: AsyncClient, auth_headers, stats_vehicle: str):
        s = await self._stats(client, auth_headers, stats_vehicle)

        # running = service 50 + fuel 127 + insurance 101 + registration 30
        assert _dec(s["total_running_cost"]) == Decimal("308.00")
        assert _dec(s["purchase_price"]) == Decimal("1000.00")
        assert _dec(s["total_ownership_cost"]) == Decimal("1308.00")
        assert s["days_owned"] == 100
        assert _dec(s["km_driven"]) == Decimal("1600.00")
        assert _dec(s["km_per_day"]) == Decimal("16")
        assert _dec(s["running_cost_per_day"]) == Decimal("3.08")
        assert _dec(s["ownership_cost_per_day"]) == Decimal("13.08")
        assert _dec(s["running_cost_per_km"]) == pytest.approx(Decimal("0.1925"))
        assert _dec(s["ownership_cost_per_km"]) == pytest.approx(Decimal("0.8175"))

    async def test_fuel_block(self, client: AsyncClient, auth_headers, stats_vehicle: str):
        s = await self._stats(client, auth_headers, stats_vehicle)

        assert s["fuel_count"] == 4
        assert _dec(s["fuel_total_cost"]) == Decimal("127.00")
        assert _dec(s["fuel_total_liters"]) == Decimal("115.000")
        # price per litre: 1.00, 1.20, 1.10, 1.20 (a plain mean, like the source app)
        assert _dec(s["avg_price_per_liter"]) == pytest.approx(Decimal("1.125"))
        assert _dec(s["min_price_per_liter"]) == pytest.approx(Decimal("1.00"))
        assert _dec(s["max_price_per_liter"]) == pytest.approx(Decimal("1.20"))
        assert _dec(s["last_price_per_liter"]) == pytest.approx(Decimal("1.20"))
        assert _dec(s["fuel_cost_per_km"]) == pytest.approx(Decimal("127") / Decimal("1600"))
        assert _dec(s["fuel_cost_per_day"]) == pytest.approx(Decimal("1.27"))
        assert _dec(s["km_per_currency_unit"]) == pytest.approx(Decimal("1600") / Decimal("127"))
        assert _dec(s["avg_cost_per_fillup"]) == pytest.approx(Decimal("31.75"))
        assert _dec(s["avg_liters_per_fillup"]) == pytest.approx(Decimal("28.75"))
        assert _dec(s["avg_km_per_fillup"]) == pytest.approx(Decimal("400"))
        # first fill 90 days ago, last 5 days ago: 85 days over 3 intervals
        assert _dec(s["avg_days_per_fillup"]) == pytest.approx(Decimal("85") / Decimal("3"))
        assert _dec(s["liters_per_day"]) == pytest.approx(Decimal("115") / Decimal("85"))

    async def test_expenses_block_is_everything_but_fuel(
        self, client: AsyncClient, auth_headers, stats_vehicle: str
    ):
        s = await self._stats(client, auth_headers, stats_vehicle)

        # service 50 + insurance 101 + registration 30
        assert _dec(s["expenses_total_cost"]) == Decimal("181.00")
        assert _dec(s["expenses_cost_per_day"]) == Decimal("1.81")
        assert _dec(s["expenses_cost_per_km"]) == pytest.approx(Decimal("181") / Decimal("1600"))
        # the three blocks must partition the running total
        assert _dec(s["expenses_total_cost"]) + _dec(s["fuel_total_cost"]) == _dec(
            s["total_running_cost"]
        )

    async def test_agrees_with_the_cost_card(
        self, client: AsyncClient, auth_headers, stats_vehicle: str
    ):
        """Built on the cost card's own figures, which are left unchanged."""
        resp = await client.get(f"/api/analytics/vehicles/{stats_vehicle}", headers=auth_headers)
        body = resp.json()
        ca, s = body["cost_analysis"], body["statistics"]
        # The card's running cost is fuel + service; the block adds insurance 101 + registration 30.
        assert _dec(ca["total_cost"]) == Decimal("177.00")
        assert _dec(s["total_running_cost"]) == _dec(ca["total_cost"]) + Decimal("131.00")
        assert _dec(s["fuel_total_cost"]) == _dec(ca["total_fuel_cost"])
        # Same distance span as the card's per-km rate.
        assert _dec(ca["cost_per_km"]) * _dec(s["km_driven"]) == pytest.approx(
            _dec(ca["total_cost"])
        )

    async def test_ownership_absent_without_purchase_price(
        self, client: AsyncClient, auth_headers, garage: _Garage
    ):
        vin = await garage.vehicle(purchase_price=None)
        s = await self._stats(client, auth_headers, vin)
        assert s["total_ownership_cost"] is None
        assert s["ownership_cost_per_km"] is None
        assert s["fuel_count"] == 0
        assert s["avg_price_per_liter"] is None

    async def test_sold_price_is_subtracted(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession, garage: _Garage
    ):
        vin = await garage.vehicle()
        vehicle = await db_session.get(Vehicle, vin)
        assert vehicle is not None
        vehicle.sold_price = Decimal("400.00")
        vehicle.sold_date = household_today() - timedelta(days=10)
        await db_session.commit()

        s = await self._stats(client, auth_headers, vin)
        assert _dec(s["total_ownership_cost"]) == Decimal("600.00")
        assert s["days_owned"] == 90  # stops at the sale, not today

    async def test_not_present_for_a_trailer(
        self, client: AsyncClient, auth_headers, garage: _Garage
    ):
        vin = await garage.vehicle(vehicle_type="Trailer")
        resp = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["statistics"] is None
        assert resp.json()["statistics_as_paid"] is None

    async def test_charging_and_propane_stay_out_of_per_fill_figures(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession, stats_vehicle: str
    ):
        """A PHEV's charging and an RV's propane are fuel spend, not fill-ups."""
        today = household_today()
        db_session.add(
            FuelRecord(
                vin=stats_vehicle,
                date=today - timedelta(days=20),
                kwh=Decimal("40.000"),
                cost=Decimal("20.00"),
            )
        )
        db_session.add(
            FuelRecord(
                vin=stats_vehicle,
                date=today - timedelta(days=15),
                propane_liters=Decimal("20.000"),
                cost=Decimal("15.00"),
            )
        )
        await db_session.commit()

        s = await self._stats(client, auth_headers, stats_vehicle)
        # Totals take every kind of fuel, like the cost card: 127 + 20 + 15.
        assert _dec(s["fuel_total_cost"]) == Decimal("162.00")
        # Per-fill figures stay on the four gasoline fills.
        assert s["fuel_count"] == 4
        assert _dec(s["avg_cost_per_fillup"]) == pytest.approx(Decimal("31.75"))
        assert _dec(s["avg_price_per_liter"]) == pytest.approx(Decimal("1.125"))

    async def test_a_fill_with_no_or_zero_cost_still_counts(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession, stats_vehicle: str
    ):
        today = household_today()
        for days_ago, cost in ((20, Decimal("0.00")), (15, None)):
            db_session.add(
                FuelRecord(
                    vin=stats_vehicle,
                    date=today - timedelta(days=days_ago),
                    liters=Decimal("10.000"),
                    cost=cost,
                    is_full_tank=True,
                )
            )
        await db_session.commit()

        s = await self._stats(client, auth_headers, stats_vehicle)
        assert s["fuel_count"] == 6
        assert _dec(s["fuel_total_liters"]) == Decimal("135.000")
        # Prices skip the unpriced fill; the free one is a real price of 0.
        assert _dec(s["min_price_per_liter"]) == Decimal("0")
        assert _dec(s["avg_price_per_liter"]) == pytest.approx(Decimal("4.5") / Decimal("5"))
        assert _dec(s["avg_cost_per_fillup"]) == pytest.approx(Decimal("127") / Decimal("5"))
        assert _dec(s["last_price_per_liter"]) == pytest.approx(Decimal("1.20"))

    async def test_a_vehicle_archived_as_sold_reads_its_sale(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession, stats_vehicle: str
    ):
        vehicle = await db_session.get(Vehicle, stats_vehicle)
        assert vehicle is not None
        vehicle.archive_sale_price = Decimal("400.00")
        vehicle.archive_sale_date = household_today() - timedelta(days=10)
        await db_session.commit()

        s = await self._stats(client, auth_headers, stats_vehicle)
        assert _dec(s["sold_price"]) == Decimal("400.00")
        assert s["days_owned"] == 90
        # 50 + 127 + 30 + 91 days of insurance, + 1000 purchase - 400 sale
        assert _dec(s["total_ownership_cost"]) == Decimal("898.00")

    @pytest.mark.parametrize("earliest", ["fuel", "service", "odometer"])
    async def test_days_owned_without_a_purchase_date_starts_at_the_first_record(
        self,
        client: AsyncClient,
        auth_headers,
        db_session: AsyncSession,
        garage: _Garage,
        earliest: str,
    ):
        vin = await garage.vehicle(purchase_days_ago=None)
        today = household_today()
        # Whichever kind of record is oldest starts the clock; the others are newer.
        ago = {"fuel": 90, "service": 120, "odometer": 60} | {earliest: 150}
        db_session.add(
            FuelRecord(
                vin=vin,
                date=today - timedelta(days=ago["fuel"]),
                liters=Decimal("40.000"),
                cost=Decimal("40.00"),
            )
        )
        db_session.add(ServiceVisit(vin=vin, date=today - timedelta(days=ago["service"])))
        db_session.add(
            OdometerRecord(
                vin=vin, date=today - timedelta(days=ago["odometer"]), odometer_km=Decimal("900")
            )
        )
        await db_session.commit()

        s = await self._stats(client, auth_headers, vin)
        assert s["days_owned"] == 150

    async def test_a_sale_entered_ahead_of_time_stops_at_today(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession, stats_vehicle: str
    ):
        vehicle = await db_session.get(Vehicle, stats_vehicle)
        assert vehicle is not None
        vehicle.sold_price = Decimal("400.00")
        vehicle.sold_date = household_today() + timedelta(days=60)
        await db_session.commit()

        s = await self._stats(client, auth_headers, stats_vehicle)
        assert s["days_owned"] == 100
        # The same 101 days of insurance as an unsold vehicle, not 161.
        assert _dec(s["total_running_cost"]) == Decimal("308.00")

    async def test_distance_is_the_cost_card_span(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession, stats_vehicle: str
    ):
        """Charging carries an odometer the card counts, so the block must too."""
        db_session.add(
            FuelRecord(
                vin=stats_vehicle,
                date=household_today() - timedelta(days=2),
                odometer_km=Decimal("3000.00"),
                kwh=Decimal("40.000"),
                cost=Decimal("20.00"),
            )
        )
        await db_session.commit()

        resp = await client.get(f"/api/analytics/vehicles/{stats_vehicle}", headers=auth_headers)
        body = resp.json()
        assert _dec(body["cost_analysis"]["km_driven"]) == Decimal("2000.00")
        assert _dec(body["statistics"]["km_driven"]) == Decimal("2000.00")


@pytest.mark.asyncio
class TestInsuranceAsPaid:
    """The same block with each started term's premium counted in full."""

    async def _both(self, client: AsyncClient, auth_headers, vin: str) -> tuple[dict, dict]:
        resp = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["statistics"] is not None and body["statistics_as_paid"] is not None
        return body["statistics"], body["statistics_as_paid"]

    async def test_counts_the_whole_term(
        self, client: AsyncClient, auth_headers, stats_vehicle: str
    ):
        accrued, paid = await self._both(client, auth_headers, stats_vehicle)

        # accrued: service 50 + fuel 127 + registration 30 + 101 of the 180 premium
        assert _dec(accrued["total_running_cost"]) == Decimal("308.00")
        # as paid: the same, with the whole 180 premium
        assert _dec(paid["total_running_cost"]) == Decimal("387.00")
        assert _dec(paid["total_ownership_cost"]) == Decimal("1387.00")
        assert _dec(paid["expenses_total_cost"]) == Decimal("260.00")
        assert _dec(paid["running_cost_per_day"]) == Decimal("3.87")
        assert _dec(paid["expenses_cost_per_km"]) == pytest.approx(Decimal("260") / Decimal("1600"))

    async def test_only_insurance_differs(
        self, client: AsyncClient, auth_headers, stats_vehicle: str
    ):
        accrued, paid = await self._both(client, auth_headers, stats_vehicle)
        same = [
            "purchase_price", "days_owned", "km_driven", "km_per_day", "fuel_count",
            "fuel_total_cost", "fuel_total_liters", "fuel_cost_per_km", "fuel_cost_per_day",
            "avg_price_per_liter", "avg_cost_per_fillup",
        ]  # fmt: skip
        for key in same:
            assert accrued[key] == paid[key], key

    async def test_a_sold_vehicle_subtracts_the_sale_on_both_bases(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession, stats_vehicle: str
    ):
        vehicle = await db_session.get(Vehicle, stats_vehicle)
        assert vehicle is not None
        vehicle.sold_price = Decimal("400.00")
        vehicle.sold_date = household_today() - timedelta(days=10)
        await db_session.commit()

        accrued, paid = await self._both(client, auth_headers, stats_vehicle)
        # running cost + 1000 purchase - 400 sale; only insurance differs. Cover
        # stops counting at the sale: 91 of the 180 days (100 days ago up to and
        # including the sale 10 days ago), where today would have given 101. As
        # paid, the term began before the sale, so it counts whole either way.
        assert _dec(accrued["total_ownership_cost"]) == Decimal("898.00")
        assert _dec(paid["total_ownership_cost"]) == Decimal("987.00")
        assert _dec(accrued["sold_price"]) == _dec(paid["sold_price"]) == Decimal("400.00")
        assert accrued["days_owned"] == paid["days_owned"] == 90

    async def test_a_term_that_has_not_started_is_not_counted(
        self, client: AsyncClient, auth_headers, garage: _Garage, stats_vehicle: str
    ):
        today = household_today()
        await garage.policy(
            stats_vehicle,
            number="P-2",
            start=today + timedelta(days=10),
            end=today + timedelta(days=190),
            premium=Decimal("90.00"),
            frequency="Semi-Annual",
        )

        accrued, paid = await self._both(client, auth_headers, stats_vehicle)
        assert _dec(accrued["total_running_cost"]) == Decimal("308.00")
        assert _dec(paid["total_running_cost"]) == Decimal("387.00")

    async def test_an_active_monthly_policy_counts_only_the_months_that_have_begun(
        self, client: AsyncClient, auth_headers, garage: _Garage, stats_vehicle: str
    ):
        """A twelve-month policy paid monthly is not twelve payments on day one,
        and the renewal queued behind it has not begun at all."""
        today = household_today()
        start = today - timedelta(days=70)  # 70 days in: the third monthly period has begun
        end = start + timedelta(days=365)
        for number, s, e in (
            ("P-M1", start, end),
            ("P-M2", end, end + timedelta(days=365)),  # the renewal
        ):
            await garage.policy(
                stats_vehicle,
                number=number,
                start=s,
                end=e,
                premium=Decimal("10.00"),
                frequency="Monthly",
            )

        accrued, paid = await self._both(client, auth_headers, stats_vehicle)
        # accrued: 308 from the fixture + 71 of 365 days of the $120 term = 23.34
        assert _dec(accrued["total_running_cost"]) == Decimal("331.34")
        # as paid: 387 from the fixture + three $10 payments; the other nine and
        # the whole renewal are not counted yet
        assert _dec(paid["total_running_cost"]) == Decimal("417.00")
        assert _dec(paid["expenses_total_cost"]) == Decimal("290.00")

    async def test_cover_that_ended_early_is_not_counted_in_full(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession, stats_vehicle: str
    ):
        from sqlalchemy import select

        link = (
            await db_session.execute(
                select(InsurancePolicyVehicle).where(InsurancePolicyVehicle.vin == stats_vehicle)
            )
        ).scalar_one()
        # Cover ends 90 days into a 180-day term: half the premium, on both bases.
        link.effective_to = household_today() - timedelta(days=10)
        await db_session.commit()

        accrued, paid = await self._both(client, auth_headers, stats_vehicle)
        assert _dec(accrued["total_running_cost"]) == Decimal("297.00")  # 177 + 90 + 30
        assert _dec(paid["total_running_cost"]) == Decimal("297.00")

    async def test_same_when_there_is_no_insurance(
        self, client: AsyncClient, auth_headers, garage: _Garage
    ):
        vin = await garage.vehicle()
        accrued, paid = await self._both(client, auth_headers, vin)
        assert accrued == paid
