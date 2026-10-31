"""
Integration tests for analytics routes.

Tests vehicle analytics, garage analytics, vendor analytics,
seasonal analytics, and period comparison endpoints.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    FuelRecord,
    ServiceLineItem,
    ServiceVisit,
    SpotRental,
    SpotRentalBilling,
    Vehicle,
)
from app.models.insurance import InsurancePolicy, InsurancePolicyVehicle
from app.models.user import User
from app.services.auth import create_access_token


@pytest_asyncio.fixture
async def financing_vehicle(db_session: AsyncSession, test_user: dict[str, object]) -> dict:
    """A vehicle no other test writes to, so monthly/rolling assertions are exact."""
    vin = "1FTFW1ET5EKE00001"
    vehicle = await db_session.get(Vehicle, vin)
    if vehicle is None:
        vehicle = Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Financing Rollup Vehicle",
            vehicle_type="Car",
            year=2020,
            make="Ford",
            model="F-150",
            fuel_type="gas",
        )
        db_session.add(vehicle)
        await db_session.commit()
    return {"vin": vin, "name": "2020 Ford F-150"}


async def _make_fresh_vehicle(
    db_session: AsyncSession, test_user: dict[str, object], nickname: str
) -> dict:
    vin = "FIN" + uuid.uuid4().hex[:14].upper()
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname=nickname,
            vehicle_type="Car",
            year=2020,
            make="Ford",
            model="F-150",
            fuel_type="gas",
        )
    )
    await db_session.commit()
    return {"vin": vin}


@pytest_asyncio.fixture
async def financing_only_vehicle(db_session: AsyncSession, test_user: dict[str, object]) -> dict:
    """A dedicated vehicle with a freshly generated VIN, used only by
    test_average_rolling_and_trend_exclude_financing so its exact-value
    assertions can't be polluted by another test's leftover records on the
    shared, fixed-VIN financing_vehicle fixture."""
    return await _make_fresh_vehicle(db_session, test_user, "Financing Only Vehicle")


@pytest_asyncio.fixture
async def financing_and_fuel_vehicle(
    db_session: AsyncSession, test_user: dict[str, object]
) -> dict:
    """A dedicated vehicle with a freshly generated VIN, used only by
    test_averages_exclude_financing_only_months_but_not_running_cost_months so
    its exact months_tracked/average_monthly_cost assertions can't be polluted
    by another test's leftover records on the shared financing_vehicle."""
    return await _make_fresh_vehicle(db_session, test_user, "Financing And Fuel Vehicle")


@pytest_asyncio.fixture
async def financing_interleaved_vehicle(
    db_session: AsyncSession, test_user: dict[str, object]
) -> dict:
    """A dedicated vehicle for the rolling-average/trend test, whose exact
    figures would be thrown off by another test's records."""
    return await _make_fresh_vehicle(db_session, test_user, "Financing Interleaved Vehicle")


async def _add_financing(client, headers, vin, on, amount, category="lease_payment"):
    resp = await client.post(
        f"/api/vehicles/{vin}/financing-records",
        json={"vin": vin, "date": on, "amount": amount, "category": category},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleAnalyticsRoutes:
    """Test per-vehicle analytics endpoints."""

    async def test_get_vehicle_analytics(self, client: AsyncClient, auth_headers, test_vehicle):
        """Vehicle analytics endpoint returns 200 with expected structure."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == test_vehicle["vin"]
        assert "vehicle_name" in data
        assert "cost_analysis" in data
        assert "fuel_economy" in data
        assert "service_history" in data
        assert "predictions" in data

    async def test_get_vehicle_analytics_nonexistent_vin(self, client: AsyncClient, auth_headers):
        """Analytics for a nonexistent VIN returns 404."""
        response = await client.get(
            "/api/analytics/vehicles/00000000000000000",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_vehicle_analytics_unauthenticated(self, client: AsyncClient, test_vehicle):
        """Unauthenticated analytics request returns 401."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}",
        )

        assert response.status_code == 401

    async def test_get_vehicle_analytics_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Non-owner cannot access another user's vehicle analytics."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}",
            headers=non_admin_headers,
        )

        assert response.status_code == 403

    async def test_vehicle_analytics_excludes_financing_from_total_cost(
        self, client: AsyncClient, auth_headers, financing_vehicle
    ):
        vin = financing_vehicle["vin"]

        baseline = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        baseline_ca = baseline.json()["cost_analysis"]
        baseline_total = float(baseline_ca["total_cost"])
        baseline_financing = float(baseline_ca["total_financing_cost"])

        create_resp = await client.post(
            f"/api/vehicles/{vin}/financing-records",
            json={
                "vin": vin,
                "date": "2026-01-01",
                "amount": 450.00,
                "category": "lease_payment",
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201

        response = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        assert response.status_code == 200
        cost_analysis = response.json()["cost_analysis"]

        assert float(cost_analysis["total_financing_cost"]) == pytest.approx(
            baseline_financing + 450.00
        )
        assert float(cost_analysis["total_cost"]) == pytest.approx(baseline_total)


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleFinancingRollup:
    """Financing counts in the per-vehicle cost analysis."""

    async def test_monthly_breakdown_reports_financing_but_excludes_it_from_total_cost(
        self, client: AsyncClient, auth_headers, financing_vehicle
    ):
        vin = financing_vehicle["vin"]
        await _add_financing(client, auth_headers, vin, "2031-03-02", 1000.00, "upfront_fee")
        await _add_financing(client, auth_headers, vin, "2031-03-15", 450.00, "lease_payment")

        resp = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        assert resp.status_code == 200
        ca = resp.json()["cost_analysis"]

        march = [m for m in ca["monthly_breakdown"] if (m["year"], m["month"]) == (2031, 3)]
        assert len(march) == 1
        assert float(march[0]["total_financing_cost"]) == 1450.00
        assert march[0]["financing_count"] == 2
        assert float(march[0]["total_cost"]) == 0.00
        assert float(ca["total_cost"]) == pytest.approx(
            sum(float(m["total_cost"]) for m in ca["monthly_breakdown"])
        )

    async def test_average_rolling_and_trend_exclude_financing(
        self, client: AsyncClient, auth_headers, financing_only_vehicle
    ):
        vin = financing_only_vehicle["vin"]
        for on, amount in (("2032-01-10", 100.00), ("2032-02-10", 200.00), ("2032-03-10", 300.00)):
            await _add_financing(client, auth_headers, vin, on, amount)

        resp = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        ca = resp.json()["cost_analysis"]

        # Every tracked month is financing-only (no running-cost activity), so
        # months_tracked, average_monthly_cost, rolling averages and trend must
        # all degrade to their empty-data defaults, even though financing still
        # shows up in the monthly breakdown for the chart.
        assert ca["months_tracked"] == 0
        assert float(ca["average_monthly_cost"]) == 0.00
        assert float(ca["total_cost"]) == 0.00
        assert ca["rolling_avg_3m"] is None
        assert ca["trend_direction"] == "stable"
        assert ca["monthly_breakdown"][-1]["year"] == 2032
        march = next(m for m in ca["monthly_breakdown"] if (m["year"], m["month"]) == (2032, 3))
        assert float(march["total_financing_cost"]) == pytest.approx(300.00)

    async def test_averages_exclude_financing_only_months_but_not_running_cost_months(
        self, client: AsyncClient, auth_headers, financing_and_fuel_vehicle
    ):
        """A month with real fuel activity plus a separate financing-only
        month: the financing-only month must not dilute months_tracked or
        average_monthly_cost, but must still appear in monthly_breakdown."""
        vin = financing_and_fuel_vehicle["vin"]

        fuel_resp = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2038-04-05",
                "liters": 40.0,
                "cost": 60.00,
                "odometer_km": 10000.0,
                "is_full_tank": True,
            },
            headers=auth_headers,
        )
        assert fuel_resp.status_code == 201, fuel_resp.text

        await _add_financing(client, auth_headers, vin, "2038-05-15", 450.00)

        resp = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        ca = resp.json()["cost_analysis"]

        april = next(m for m in ca["monthly_breakdown"] if (m["year"], m["month"]) == (2038, 4))
        may = next(m for m in ca["monthly_breakdown"] if (m["year"], m["month"]) == (2038, 5))

        assert float(april["total_fuel_cost"]) == pytest.approx(60.00)
        assert float(may["total_financing_cost"]) == pytest.approx(450.00)
        assert float(may["total_cost"]) == 0.00

        assert ca["months_tracked"] == 1
        assert float(ca["average_monthly_cost"]) == pytest.approx(60.00)

    async def test_rolling_average_and_trend_skip_financing_only_months(
        self, client: AsyncClient, auth_headers, financing_interleaved_vehicle
    ):
        """Fuel in Jan, Mar and Apr, only a lease payment in Feb, May and Jun.
        Over the three running-cost months (100, 300, 500) the 3-month average
        is 300 and the trend is increasing. Counting the lease-only months as
        zero-cost months would give 166.67 and decreasing."""
        vin = financing_interleaved_vehicle["vin"]

        for on, cost, odometer in (
            ("2039-01-10", 100.00, 10000.0),
            ("2039-03-10", 300.00, 10500.0),
            ("2039-04-10", 500.00, 11000.0),
        ):
            fuel_resp = await client.post(
                f"/api/vehicles/{vin}/fuel",
                json={
                    "vin": vin,
                    "date": on,
                    "liters": 40.0,
                    "cost": cost,
                    "odometer_km": odometer,
                    "is_full_tank": True,
                },
                headers=auth_headers,
            )
            assert fuel_resp.status_code == 201, fuel_resp.text

        for on in ("2039-02-15", "2039-05-15", "2039-06-15"):
            await _add_financing(client, auth_headers, vin, on, 450.00)

        resp = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        ca = resp.json()["cost_analysis"]

        assert len(ca["monthly_breakdown"]) == 6
        assert ca["months_tracked"] == 3
        assert float(ca["average_monthly_cost"]) == pytest.approx(300.00)
        assert float(ca["rolling_avg_3m"]) == pytest.approx(300.00)
        assert ca["rolling_avg_6m"] is None
        assert ca["trend_direction"] == "increasing"

    async def test_cost_per_km_excludes_financing(
        self, client: AsyncClient, auth_headers, financing_vehicle
    ):
        vin = financing_vehicle["vin"]
        for on, km in (("2033-01-01", 1000.0), ("2033-02-01", 2000.0)):
            r = await client.post(
                f"/api/vehicles/{vin}/odometer",
                json={"vin": vin, "date": on, "odometer_km": km},
                headers=auth_headers,
            )
            assert r.status_code == 201, r.text

        baseline = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        baseline_cost_per_km = baseline.json()["cost_analysis"]["cost_per_km"]
        assert baseline_cost_per_km is not None

        await _add_financing(client, auth_headers, vin, "2033-01-15", 500.00)

        resp = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        ca = resp.json()["cost_analysis"]

        assert float(ca["total_financing_cost"]) >= 500.00
        assert ca["cost_per_km"] == baseline_cost_per_km


@pytest.mark.integration
@pytest.mark.asyncio
class TestGarageAnalyticsRoutes:
    """Test garage-level analytics endpoints."""

    async def test_get_garage_analytics(self, client: AsyncClient, auth_headers, test_vehicle):
        """Garage analytics returns 200 with expected structure."""
        response = await client.get(
            "/api/analytics/garage",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "total_costs" in data
        assert "cost_breakdown_by_category" in data
        assert "cost_by_vehicle" in data
        assert "monthly_trends" in data
        assert "vehicle_count" in data
        assert data["vehicle_count"] >= 1

    async def test_get_garage_analytics_unauthenticated(self, client: AsyncClient):
        """Unauthenticated garage analytics request returns 401."""
        response = await client.get("/api/analytics/garage")

        assert response.status_code == 401

    async def test_garage_analytics_includes_financing_total(
        self, client: AsyncClient, auth_headers, financing_vehicle
    ):
        vin = financing_vehicle["vin"]

        create_resp = await client.post(
            f"/api/vehicles/{vin}/financing-records",
            json={
                "vin": vin,
                "date": "2026-01-01",
                "amount": 600.00,
                "category": "loan_payment",
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201

        response = await client.get("/api/analytics/garage", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        assert float(data["total_costs"]["total_financing"]) >= 600.00

        financing_entries = [
            c for c in data["cost_breakdown_by_category"] if c["category"] == "Financing"
        ]
        assert len(financing_entries) == 1
        assert float(financing_entries[0]["amount"]) >= 600.00


@pytest.mark.integration
@pytest.mark.asyncio
class TestGarageFinancingRollup:
    """Financing counts in garage per-vehicle rows and monthly trends."""

    @staticmethod
    def _vehicle_row(data, vin):
        return next(v for v in data["cost_by_vehicle"] if v["vin"] == vin)

    async def test_cost_by_vehicle_reports_financing_but_excludes_it_from_total_cost(
        self, client: AsyncClient, auth_headers, financing_vehicle
    ):
        vin = financing_vehicle["vin"]
        before = self._vehicle_row(
            (await client.get("/api/analytics/garage", headers=auth_headers)).json(), vin
        )

        await _add_financing(client, auth_headers, vin, "2034-01-05", 455.00, "lease_payment")
        await _add_financing(client, auth_headers, vin, "2034-01-01", 90.00, "upfront_fee")

        after = self._vehicle_row(
            (await client.get("/api/analytics/garage", headers=auth_headers)).json(), vin
        )
        assert float(after["total_financing"]) == pytest.approx(
            float(before["total_financing"]) + 545.00
        )
        assert float(after["total_cost"]) == pytest.approx(float(before["total_cost"]))
        parts = sum(
            float(after[k])
            for k in (
                "total_maintenance",
                "total_upgrades",
                "total_inspection",
                "total_collision",
                "total_detailing",
                "total_fuel",
                "total_def",
            )
        )
        assert float(after["total_cost"]) == pytest.approx(parts)

    async def test_monthly_trends_include_financing(
        self, client: AsyncClient, auth_headers, financing_vehicle, monkeypatch
    ):
        # The trend only covers the 12 months up to today, so park today in June 2040.
        monkeypatch.setattr("app.routes.analytics.household_today", lambda: date(2040, 6, 25))
        vin = financing_vehicle["vin"]
        await _add_financing(client, auth_headers, vin, "2040-06-01", 400.00, "loan_payment")
        await _add_financing(client, auth_headers, vin, "2040-06-20", 100.00, "upfront_fee")

        data = (await client.get("/api/analytics/garage", headers=auth_headers)).json()

        june = [t for t in data["monthly_trends"] if t["month"] == "Jun 2040"]
        assert len(june) == 1
        assert float(june[0]["financing"]) == 500.00
        # total excludes financing — this month has no other costs.
        assert float(june[0]["total"]) == 0.00

    async def test_garage_rows_and_trends_agree_with_totals(
        self, client: AsyncClient, auth_headers, financing_vehicle
    ):
        vin = financing_vehicle["vin"]
        await _add_financing(client, auth_headers, vin, "2035-02-01", 250.00)

        data = (await client.get("/api/analytics/garage", headers=auth_headers)).json()

        assert float(data["total_costs"]["total_financing"]) == pytest.approx(
            sum(float(v["total_financing"]) for v in data["cost_by_vehicle"])
        )


@pytest.mark.integration
@pytest.mark.asyncio
class TestVendorAnalyticsRoutes:
    """Test vendor analytics endpoint."""

    async def test_get_vendor_analytics(self, client: AsyncClient, auth_headers, test_vehicle):
        """Vendor analytics returns 200 with expected structure."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/vendors",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "vendors" in data
        assert "total_vendors" in data
        assert isinstance(data["vendors"], list)

    async def test_get_vendor_analytics_nonexistent_vin(self, client: AsyncClient, auth_headers):
        """Vendor analytics for a nonexistent VIN returns 404."""
        response = await client.get(
            "/api/analytics/vehicles/00000000000000000/vendors",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_vendor_analytics_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Non-owner cannot access vendor analytics for another user's vehicle."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/vendors",
            headers=non_admin_headers,
        )

        assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
class TestSeasonalAnalyticsRoutes:
    """Test seasonal analytics endpoint."""

    async def test_get_seasonal_analytics(self, client: AsyncClient, auth_headers, test_vehicle):
        """Seasonal analytics returns 200 with expected structure."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/seasonal",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "seasons" in data
        assert isinstance(data["seasons"], list)

    async def test_get_seasonal_analytics_nonexistent_vin(self, client: AsyncClient, auth_headers):
        """Seasonal analytics for a nonexistent VIN returns 404."""
        response = await client.get(
            "/api/analytics/vehicles/00000000000000000/seasonal",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_seasonal_analytics_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Non-owner cannot access seasonal analytics for another user's vehicle."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/seasonal",
            headers=non_admin_headers,
        )

        assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
class TestPeriodComparisonRoutes:
    """Test period comparison endpoint."""

    async def test_compare_periods(self, client: AsyncClient, auth_headers, test_vehicle):
        """Period comparison returns 200 with expected structure."""
        params = {
            "period1_start": "2025-01-01",
            "period1_end": "2025-06-30",
            "period2_start": "2025-07-01",
            "period2_end": "2025-12-31",
        }
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/compare",
            params=params,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "period1_label" in data
        assert "period2_label" in data
        assert "period1_total_cost" in data
        assert "period2_total_cost" in data
        assert "cost_change_amount" in data
        assert "category_changes" in data

    async def test_compare_periods_with_labels(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Period comparison with custom labels uses supplied labels."""
        params = {
            "period1_start": "2025-01-01",
            "period1_end": "2025-06-30",
            "period2_start": "2025-07-01",
            "period2_end": "2025-12-31",
            "period1_label": "H1 2025",
            "period2_label": "H2 2025",
        }
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/compare",
            params=params,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["period1_label"] == "H1 2025"
        assert data["period2_label"] == "H2 2025"

    async def test_compare_periods_nonexistent_vin(self, client: AsyncClient, auth_headers):
        """Period comparison for a nonexistent VIN returns 404."""
        params = {
            "period1_start": "2025-01-01",
            "period1_end": "2025-06-30",
            "period2_start": "2025-07-01",
            "period2_end": "2025-12-31",
        }
        response = await client.get(
            "/api/analytics/vehicles/00000000000000000/compare",
            params=params,
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_compare_periods_missing_params(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Period comparison without required date params returns 422."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/compare",
            headers=auth_headers,
        )

        assert response.status_code == 422

    async def test_compare_periods_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Non-owner cannot compare periods for another user's vehicle."""
        params = {
            "period1_start": "2025-01-01",
            "period1_end": "2025-06-30",
            "period2_start": "2025-07-01",
            "period2_end": "2025-12-31",
        }
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/compare",
            params=params,
            headers=non_admin_headers,
        )

        assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
class TestAnalyticsDefConsistency:
    """The Analytics page and the DEF tab must agree on DEF consumption.

    The analytics route previously carried its own DEF formula (all purchase
    liters over the odometer span of ALL records, min 2 points) and asserted
    a rate on data the DEF endpoint judged insufficient. Both now go through
    DEFRecordService.get_def_analytics.
    """

    async def test_def_rate_matches_def_endpoint_verdict(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        from app.models.def_record import DEFRecord

        vin = test_vehicle["vin"]
        await db_session.execute(delete(DEFRecord).where(DEFRecord.vin == vin))
        # 2 purchases with odometer+liters + 3 odometer-only observations:
        # exactly the production shape that produced a phantom 2.7 gal/1,000 mi.
        db_session.add_all(
            [
                DEFRecord(
                    vin=vin,
                    date=date(2026, 2, 11),
                    odometer_km=Decimal("7898.64"),
                    liters=Decimal("9.464"),
                    cost=Decimal("22.60"),
                    entry_type="purchase",
                ),
                DEFRecord(
                    vin=vin,
                    date=date(2026, 2, 13),
                    odometer_km=Decimal("7958.19"),
                    liters=Decimal("9.464"),
                    cost=Decimal("22.60"),
                    entry_type="purchase",
                ),
                DEFRecord(
                    vin=vin,
                    date=date(2026, 3, 17),
                    odometer_km=Decimal("9144.27"),
                    fill_level=Decimal("0.85"),
                    entry_type="auto_fuel_sync",
                ),
                DEFRecord(
                    vin=vin,
                    date=date(2026, 5, 5),
                    odometer_km=Decimal("9968.25"),
                    fill_level=Decimal("0.75"),
                    entry_type="auto_fuel_sync",
                ),
                DEFRecord(
                    vin=vin,
                    date=date(2026, 6, 30),
                    odometer_km=Decimal("10845.34"),
                    fill_level=Decimal("0.75"),
                    entry_type="auto_fuel_sync",
                ),
            ]
        )
        await db_session.commit()

        response = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
        assert response.status_code == 200
        def_analysis = response.json()["def_analysis"]
        assert def_analysis is not None
        assert def_analysis["record_count"] == 5
        # Only 2 records carry odometer+liters -> below the 3-record minimum:
        # no consumption rate may be asserted (parity with the DEF tab).
        assert def_analysis["liters_per_1000_km"] is None, (
            "analytics page asserted a DEF rate the DEF endpoint judges "
            "insufficient - duplicate formula is back"
        )
        assert def_analysis["data_confidence"] == "insufficient"

        await db_session.execute(delete(DEFRecord).where(DEFRecord.vin == vin))
        await db_session.commit()


# Copied from tests/conftest.py so these owners skip the argon2 work.
_PASSWORD_HASH = (
    "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$"
    "hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
)


async def _seed(test_sessionmaker: async_sessionmaker[AsyncSession], *rows: object) -> None:
    """Write through a session of its own, so the route reads them cold."""
    async with test_sessionmaker() as session:
        session.add_all(rows)
        await session.commit()


async def _isolated_owner(
    test_sessionmaker: async_sessionmaker[AsyncSession], *, vehicle_type: str = "Car"
) -> tuple[str, dict[str, str]]:
    """A fresh non-admin owner with one vehicle, so the garage is only theirs.

    The admin test user sees every vehicle in the shared database, and other
    modules leave records all over the calendar.
    """
    suffix = uuid.uuid4().hex[:12]
    # "ANZRO" + 12 hex chars = 17, and hex never has I, O or Q.
    vin = f"ANZRO{suffix.upper()}"
    async with test_sessionmaker() as session:
        user = User(
            username=f"anz_{suffix}",
            email=f"anz_{suffix}@example.com",
            hashed_password=_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
        )
        session.add(user)
        await session.flush()
        session.add(
            Vehicle(
                vin=vin,
                user_id=user.id,
                nickname=f"Analytics {suffix}",
                vehicle_type=vehicle_type,
                year=2020,
                make="Ford",
                model="F-150",
            )
        )
        await session.commit()
        token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return vin, {"Authorization": f"Bearer {token}"}


def _fuel(vin: str, on: date, cost: str) -> FuelRecord:
    return FuelRecord(
        vin=vin, date=on, liters=Decimal("40.000"), cost=Decimal(cost), is_full_tank=True
    )


@pytest.mark.integration
@pytest.mark.asyncio
class TestZeroCostRecordsCount:
    """A recorded $0 is a real record; only a missing cost is skipped (R1)."""

    async def test_a_zero_spot_rental_billing_counts_in_average_and_trend(
        self, client: AsyncClient, test_sessionmaker
    ):
        vin, headers = await _isolated_owner(test_sessionmaker, vehicle_type="FifthWheel")
        rental = SpotRental(vin=vin, check_in_date=date(2026, 1, 1))
        rental.billings.extend(
            [
                SpotRentalBilling(billing_date=date(2026, 1, 5), total=Decimal("100.00")),
                SpotRentalBilling(billing_date=date(2026, 2, 5), total=Decimal("0.00")),
            ]
        )
        await _seed(test_sessionmaker, rental)

        response = await client.get(f"/api/analytics/vehicles/{vin}", headers=headers)
        assert response.status_code == 200, response.text
        spot = response.json()["spot_rental_analysis"]

        assert Decimal(str(spot["monthly_average"])) == Decimal("50.00")
        assert [(m["year"], m["month"]) for m in spot["monthly_trend"]] == [
            (2026, 1),
            (2026, 2),
        ]

    async def test_a_zero_cost_line_counts_in_the_service_type_breakdown(
        self, client: AsyncClient, test_sessionmaker
    ):
        vin, headers = await _isolated_owner(test_sessionmaker)
        visits = []
        for on, cost in ((date(2026, 1, 10), "50.00"), (date(2026, 4, 10), "0.00")):
            visit = ServiceVisit(vin=vin, date=on)
            visit.line_items.append(ServiceLineItem(description="Oil change", cost=Decimal(cost)))
            visits.append(visit)
        await _seed(test_sessionmaker, *visits)

        response = await client.get(f"/api/analytics/vehicles/{vin}", headers=headers)
        assert response.status_code == 200, response.text
        rows = response.json()["cost_analysis"]["service_type_breakdown"]

        oil = next(r for r in rows if r["service_type"] == "Oil change")
        assert oil["count"] == 2
        assert oil["last_service_date"] == "2026-04-10"
        assert Decimal(str(oil["total_cost"])) == Decimal("50.00")
        assert Decimal(str(oil["average_cost"])) == Decimal("25.00")


# Today for the garage window tests, so a month boundary can't flake them.
_GARAGE_TODAY = date(2026, 8, 15)
_GARAGE_WINDOW = [
    "Sep 2025",
    "Oct 2025",
    "Nov 2025",
    "Dec 2025",
    "Jan 2026",
    "Feb 2026",
    "Mar 2026",
    "Apr 2026",
    "May 2026",
    "Jun 2026",
    "Jul 2026",
    "Aug 2026",
]


@pytest.mark.integration
@pytest.mark.asyncio
class TestGarageMonthlyTrendWindow:
    """The garage trend is the 12 calendar months ending this month (D1)."""

    @pytest.fixture(autouse=True)
    def _pin_today(self, monkeypatch):
        monkeypatch.setattr("app.routes.analytics.household_today", lambda: _GARAGE_TODAY)

    async def test_the_trend_is_the_twelve_months_ending_this_month(
        self, client: AsyncClient, test_sessionmaker
    ):
        vin, headers = await _isolated_owner(test_sessionmaker)
        await _seed(
            test_sessionmaker,
            _fuel(vin, date(2026, 9, 10), "70.00"),  # next month: a typo, say
            _fuel(vin, date(2025, 7, 10), "30.00"),  # 13 months back
            _fuel(vin, date(2026, 8, 5), "40.00"),  # this month
        )

        data = (await client.get("/api/analytics/garage", headers=headers)).json()
        trends = data["monthly_trends"]

        assert [t["month"] for t in trends] == _GARAGE_WINDOW
        assert Decimal(trends[-1]["fuel"]) == Decimal("40.00")
        assert all(Decimal(t["fuel"]) == 0 for t in trends[:-1])
        # Out of the chart, still in the money.
        assert Decimal(data["total_costs"]["total_fuel"]) == Decimal("140.00")
        row = next(v for v in data["cost_by_vehicle"] if v["vin"] == vin)
        assert Decimal(row["total_fuel"]) == Decimal("140.00")

    async def test_a_quiet_garage_still_gets_every_month(
        self, client: AsyncClient, test_sessionmaker
    ):
        vin, headers = await _isolated_owner(test_sessionmaker)
        await _seed(test_sessionmaker, _fuel(vin, date(2026, 3, 10), "25.00"))

        trends = (await client.get("/api/analytics/garage", headers=headers)).json()[
            "monthly_trends"
        ]

        assert [t["month"] for t in trends] == _GARAGE_WINDOW
        others = ("service", "def_cost", "insurance", "financing")
        for t in trends:
            expected = Decimal("25.00") if t["month"] == "Mar 2026" else Decimal(0)
            assert Decimal(t["fuel"]) == expected
            assert Decimal(t["total"]) == expected
            assert all(Decimal(t[f]) == 0 for f in others)

    async def test_the_monthly_total_leaves_insurance_out(
        self, client: AsyncClient, test_sessionmaker
    ):
        vin, headers = await _isolated_owner(test_sessionmaker)
        policy = InsurancePolicy(
            provider="Progressive",
            policy_number=f"P-{vin}",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            premium_amount=Decimal("100.00"),
            premium_frequency="Monthly",
        )
        policy.vehicle_links.append(InsurancePolicyVehicle(vin=vin, policy_type="Full Coverage"))
        await _seed(test_sessionmaker, policy, _fuel(vin, date(2026, 8, 5), "40.00"))

        try:
            trends = (await client.get("/api/analytics/garage", headers=headers)).json()[
                "monthly_trends"
            ]
            august = next(t for t in trends if t["month"] == "Aug 2026")

            assert Decimal(august["insurance"]) > 0
            assert Decimal(august["total"]) == Decimal("40.00")
        finally:
            async with test_sessionmaker() as session:
                await session.execute(
                    delete(InsurancePolicy).where(InsurancePolicy.id == policy.id)
                )
                await session.commit()
