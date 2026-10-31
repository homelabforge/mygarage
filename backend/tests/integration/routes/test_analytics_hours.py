"""Integration tests for the hours-native analytics series (Task 7 of the
hours-usage-model plan): the engine-hours fuel-economy trend (l_per_hr +
cost_per_hr), the hours-accumulated-over-time series, and the
average_l_per_hr / average_cost_per_hr summary fields on
``GET /api/analytics/vehicles/{vin}``.

Uses isolated, uniquely-VINed vehicles rather than the shared ``test_vehicle``
fixture: the session-scoped test DB reuses that fixture's fixed VIN across
many other test files (several of which add ``HoursRecord``/``engine_hours``
fuel rows to it), which would make the exact ordering/averages assertions
here flaky.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelRecord, HoursRecord, Vehicle
from app.models.user import User
from app.services.auth import create_access_token


async def _isolated_vehicle(
    db_session: AsyncSession, *, vehicle_type: str = "Car"
) -> tuple[str, dict[str, str]]:
    """Create a throwaway non-admin owner + one vehicle isolated from the
    session-scoped DB's accumulated rows. Returns ``(vin, auth_headers)``.
    """
    suffix = uuid.uuid4().hex[:12]
    # Pre-computed argon2id hash (same constant the conftest user fixtures use).
    password_hash = (
        "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$"
        "hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
    )
    user = User(
        username=f"hrsan_{suffix}",
        email=f"hrsan_{suffix}@example.com",
        hashed_password=password_hash,
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # "HRSAN" + 12 hex chars = exactly 17 chars, no I/O/Q -> a valid unique VIN.
    vin = f"HRSAN{suffix.upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=user.id,
            nickname=f"Hours Analytics {suffix}",
            vehicle_type=vehicle_type,
        )
    )
    await db_session.commit()

    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return vin, {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
@pytest.mark.asyncio
class TestHoursEconomyTrendRoute:
    """GET /api/analytics/vehicles/{vin} -> hours_economy."""

    async def test_trend_points_ordered_with_correct_figures_and_averages(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Three full-tank fill-ups over engine_hours -> two scored intervals,
        in order, with hand-computed l_per_hr/cost_per_hr, feeding into
        average_l_per_hr/average_cost_per_hr."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 1),
                    engine_hours=Decimal("100.0"),
                    liters=Decimal("20.000"),
                    cost=Decimal("30.00"),
                    is_full_tank=True,
                ),
                # Δ=20h: l_per_hr = 15/20 = 0.75, cost_per_hr = 25/20 = 1.25
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 10),
                    engine_hours=Decimal("120.0"),
                    liters=Decimal("15.000"),
                    cost=Decimal("25.00"),
                    is_full_tank=True,
                ),
                # Δ=20h: l_per_hr = 10/20 = 0.50, cost_per_hr = 20/20 = 1.00
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 20),
                    engine_hours=Decimal("140.0"),
                    liters=Decimal("10.000"),
                    cost=Decimal("20.00"),
                    is_full_tank=True,
                ),
            ]
        )
        await db_session.commit()

        response = await client.get(f"/api/analytics/vehicles/{vin}", headers=headers)
        assert response.status_code == 200
        hours_economy = response.json()["hours_economy"]

        points = hours_economy["data_points"]
        assert len(points) == 2
        assert Decimal(str(points[0]["engine_hours"])) == Decimal("120.0")
        assert Decimal(str(points[0]["l_per_hr"])) == Decimal("0.75")
        assert Decimal(str(points[0]["cost_per_hr"])) == Decimal("1.25")
        assert Decimal(str(points[1]["engine_hours"])) == Decimal("140.0")
        assert Decimal(str(points[1]["l_per_hr"])) == Decimal("0.50")
        assert Decimal(str(points[1]["cost_per_hr"])) == Decimal("1.00")
        # Ordered chronologically.
        assert points[0]["date"] < points[1]["date"]

        # average_l_per_hr / average_cost_per_hr live where average_l_per_100km
        # lives on the distance side: mean(0.75, 0.50)=0.62, mean(1.25, 1.00)=1.12
        # (Decimal ROUND_HALF_EVEN).
        assert Decimal(str(hours_economy["average_l_per_hr"])) == Decimal("0.62")
        assert Decimal(str(hours_economy["average_cost_per_hr"])) == Decimal("1.12")
        assert Decimal(str(hours_economy["best_l_per_hr"])) == Decimal("0.50")
        assert Decimal(str(hours_economy["worst_l_per_hr"])) == Decimal("0.75")
        assert Decimal(str(hours_economy["recent_l_per_hr"])) == Decimal("0.50")
        assert Decimal(str(hours_economy["recent_cost_per_hr"])) == Decimal("1.00")

    async def test_zero_liters_endpoint_nulled_not_omitted(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A zero-liters full-tank interval keeps its point (cost_per_hr is
        real data) with l_per_hr nulled, matching the P3 backlog convention
        already proven at the service layer -- this asserts the SAME
        convention survives the route's JSON serialization."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=date(2026, 2, 1),
                    engine_hours=Decimal("50.0"),
                    liters=Decimal("10.000"),
                    cost=Decimal("15.00"),
                    is_full_tank=True,
                ),
                # Δ=10h, 0 liters -> l_per_hr None; cost_per_hr = 5/10 = 0.50
                FuelRecord(
                    vin=vin,
                    date=date(2026, 2, 5),
                    engine_hours=Decimal("60.0"),
                    liters=Decimal("0.000"),
                    cost=Decimal("5.00"),
                    is_full_tank=True,
                ),
            ]
        )
        await db_session.commit()

        response = await client.get(f"/api/analytics/vehicles/{vin}", headers=headers)
        assert response.status_code == 200
        hours_economy = response.json()["hours_economy"]

        points = hours_economy["data_points"]
        assert len(points) == 1, "the zero-liters endpoint is kept, not dropped"
        assert points[0]["l_per_hr"] is None
        assert Decimal(str(points[0]["cost_per_hr"])) == Decimal("0.50")

        assert hours_economy["average_l_per_hr"] is None
        assert Decimal(str(hours_economy["average_cost_per_hr"])) == Decimal("0.50")

    async def test_the_average_counts_the_hauling_tank_it_plots(
        self, client: AsyncClient, db_session: AsyncSession, test_sessionmaker
    ):
        """The trend's average comes from the tanks it plots, towing included,
        the way the distance trend's does (R3). The vehicle card keeps leaving
        hauling out."""
        vin, headers = await _isolated_vehicle(db_session)

        def fill(hours: str, liters: str, cost: str, *, hauling: bool = False) -> FuelRecord:
            return FuelRecord(
                vin=vin,
                date=date(2026, 3, int(Decimal(hours)) // 10),
                engine_hours=Decimal(hours),
                liters=Decimal(liters),
                cost=Decimal(cost),
                is_full_tank=True,
                is_hauling=hauling,
            )

        async with test_sessionmaker() as session:
            session.add_all(
                [
                    fill("100.0", "20.000", "40.00"),  # anchor
                    fill("120.0", "10.000", "20.00"),  # 20h: 0.50 L/hr, 1.00/hr
                    fill("130.0", "30.000", "60.00", hauling=True),  # 10h: 3.00 L/hr, 6.00/hr
                    fill("150.0", "10.000", "20.00"),  # 20h: 0.50 L/hr, 1.00/hr
                ]
            )
            await session.commit()

        response = await client.get(f"/api/analytics/vehicles/{vin}", headers=headers)
        assert response.status_code == 200, response.text
        hours_economy = response.json()["hours_economy"]

        assert len(hours_economy["data_points"]) == 3
        # 50 L over 50 h, and 100.00 over 50 h, across all three plotted tanks.
        assert Decimal(str(hours_economy["average_l_per_hr"])) == Decimal("1.00")
        assert Decimal(str(hours_economy["average_cost_per_hr"])) == Decimal("2.00")

        # Guard: the vehicle card still leaves the hauling tank out (20 L / 40 h),
        # and the trend's cached average didn't leak into it.
        stats = await client.get(f"/api/vehicles/{vin}/detail-stats", headers=headers)
        assert stats.status_code == 200, stats.text
        assert Decimal(str(stats.json()["average_l_per_hr"])) == Decimal("0.50")
        assert Decimal(str(stats.json()["average_cost_per_hr"])) == Decimal("1.00")

    async def test_unauthenticated_request_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        vin, _headers = await _isolated_vehicle(db_session)
        response = await client.get(f"/api/analytics/vehicles/{vin}")
        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
class TestHoursAccumulatedSeriesRoute:
    """GET /api/analytics/vehicles/{vin} -> hours_accumulated."""

    async def test_series_ordered_by_date_from_hours_records(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        vin, headers = await _isolated_vehicle(db_session)
        # Inserted out of date order to prove the route sorts, not just echoes
        # insertion order.
        db_session.add_all(
            [
                HoursRecord(vin=vin, date=date(2026, 3, 1), engine_hours=Decimal("50.0")),
                HoursRecord(vin=vin, date=date(2026, 1, 1), engine_hours=Decimal("10.0")),
                HoursRecord(vin=vin, date=date(2026, 2, 1), engine_hours=Decimal("30.0")),
            ]
        )
        await db_session.commit()

        response = await client.get(f"/api/analytics/vehicles/{vin}", headers=headers)
        assert response.status_code == 200
        series = response.json()["hours_accumulated"]

        assert len(series) == 3
        assert [p["date"] for p in series] == ["2026-01-01", "2026-02-01", "2026-03-01"]
        assert [Decimal(str(p["engine_hours"])) for p in series] == [
            Decimal("10.0"),
            Decimal("30.0"),
            Decimal("50.0"),
        ]


@pytest.mark.integration
@pytest.mark.asyncio
class TestHoursDistanceCoexistence:
    """A pure-distance vehicle returns null/empty hours series; a pure-hours
    vehicle returns null/empty MPG series; a dual vehicle returns both. The
    existing distance/MPG series must be completely unaffected."""

    async def test_pure_distance_vehicle_has_null_empty_hours_series(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Regression + null-convention check: a vehicle with only
        odometer-based fuel history gets a fully populated distance
        fuel_economy AND a null/empty hours_economy + hours_accumulated."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 1),
                    odometer_km=Decimal("10000.00"),
                    liters=Decimal("40.00"),
                    cost=Decimal("60.00"),
                    is_full_tank=True,
                ),
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 15),
                    odometer_km=Decimal("10500.00"),
                    liters=Decimal("35.00"),
                    cost=Decimal("52.00"),
                    is_full_tank=True,
                ),
            ]
        )
        await db_session.commit()

        response = await client.get(f"/api/analytics/vehicles/{vin}", headers=headers)
        assert response.status_code == 200
        data = response.json()

        # Distance series untouched: still populates normally.
        assert len(data["fuel_economy"]["data_points"]) == 1
        assert data["fuel_economy"]["average_l_per_100km"] is not None

        # Hours series naturally null/empty -- no engine_hours data at all.
        assert data["hours_economy"]["data_points"] == []
        assert data["hours_economy"]["average_l_per_hr"] is None
        assert data["hours_economy"]["average_cost_per_hr"] is None
        assert data["hours_accumulated"] == []

    async def test_pure_hours_vehicle_has_null_empty_mpg_series(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The mirror case: a vehicle with only engine_hours fuel history (no
        odometer readings at all) gets a fully populated hours_economy AND a
        null/empty distance fuel_economy."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=date(2026, 4, 1),
                    engine_hours=Decimal("200.0"),
                    liters=Decimal("20.000"),
                    cost=Decimal("30.00"),
                    is_full_tank=True,
                ),
                FuelRecord(
                    vin=vin,
                    date=date(2026, 4, 10),
                    engine_hours=Decimal("220.0"),
                    liters=Decimal("18.000"),
                    cost=Decimal("27.00"),
                    is_full_tank=True,
                ),
            ]
        )
        await db_session.commit()

        response = await client.get(f"/api/analytics/vehicles/{vin}", headers=headers)
        assert response.status_code == 200
        data = response.json()

        # Hours series populates normally.
        assert len(data["hours_economy"]["data_points"]) == 1
        assert data["hours_economy"]["average_l_per_hr"] is not None

        # Distance series naturally null/empty -- no odometer_km data at all.
        assert data["fuel_economy"]["data_points"] == []
        assert data["fuel_economy"]["average_l_per_100km"] is None

    async def test_dual_tracking_vehicle_returns_both_series(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A vehicle whose fuel records carry BOTH odometer_km and
        engine_hours gets both series populated in the same response."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=date(2026, 5, 1),
                    odometer_km=Decimal("5000.00"),
                    engine_hours=Decimal("300.0"),
                    liters=Decimal("25.000"),
                    cost=Decimal("38.00"),
                    is_full_tank=True,
                ),
                FuelRecord(
                    vin=vin,
                    date=date(2026, 5, 10),
                    odometer_km=Decimal("5400.00"),
                    engine_hours=Decimal("315.0"),
                    liters=Decimal("22.000"),
                    cost=Decimal("33.00"),
                    is_full_tank=True,
                ),
            ]
        )
        await db_session.commit()

        response = await client.get(f"/api/analytics/vehicles/{vin}", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert len(data["fuel_economy"]["data_points"]) == 1
        assert data["fuel_economy"]["average_l_per_100km"] is not None
        assert len(data["hours_economy"]["data_points"]) == 1
        assert data["hours_economy"]["average_l_per_hr"] is not None
