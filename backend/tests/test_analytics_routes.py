"""Integration tests for analytics API routes."""

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pymupdf
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.def_record import DEFRecord
from app.models.financing import FinancingRecord
from app.models.fuel import FuelRecord
from app.models.insurance import InsurancePolicy, InsurancePolicyVehicle
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.tax import TaxRecord
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vendor import Vendor
from app.services.auth import create_access_token
from app.utils.household_time import household_today
from tests._users import TEST_PASSWORD_HASH


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract all text from PDF bytes using PyMuPDF."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()  # pyright: ignore[reportOperatorIssue]  # get_text() with no option returns str
    doc.close()
    return text


@dataclass(frozen=True)
class SeededVehicle:
    """What the seed wrote, so tests can assert against it."""

    vin: str
    nickname: str
    vendor_name: str


def _fuel(vin: str, on: date, cost: str, odometer_km: str | None = None) -> FuelRecord:
    return FuelRecord(
        vin=vin,
        date=on,
        liters=Decimal("40.000"),
        cost=Decimal(cost),
        odometer_km=Decimal(odometer_km) if odometer_km else None,
        is_full_tank=True,
    )


@pytest_asyncio.fixture
async def seeded_vehicle(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    test_user: dict[str, object],
) -> AsyncGenerator[SeededVehicle]:
    """A fresh vehicle with a known spend, deleted afterwards with all of it.

    One service visit and one fill-up in Feb 2024 (120.00) and again in May 2024
    (200.00), both visits at one named shop. These tests used to borrow whatever
    vehicle had leftovers, so they skipped on a clean DB and asserted nothing.
    """
    suffix = uuid.uuid4().hex[:14].upper()
    seed = SeededVehicle(
        vin=f"ANL{suffix}",
        nickname=f"Seed {suffix[:6]}",
        vendor_name=f"Shop {suffix[:8]}",
    )
    # Its own session, so the routes read the rows cold.
    async with test_sessionmaker() as session:
        vendor = Vendor(name=seed.vendor_name)
        session.add(vendor)
        session.add(
            Vehicle(
                vin=seed.vin,
                user_id=test_user["id"],
                nickname=seed.nickname,
                vehicle_type="Car",
                year=2019,
                make="Toyota",
                model="Tacoma",
            )
        )
        for on, description, cost, odometer in (
            (date(2024, 2, 10), "Oil change", "80.00", "20000.00"),
            (date(2024, 5, 10), "Brake pads", "150.00", "21000.00"),
        ):
            visit = ServiceVisit(vin=seed.vin, date=on, odometer_km=Decimal(odometer))
            visit.vendor = vendor
            visit.line_items.append(ServiceLineItem(description=description, cost=Decimal(cost)))
            session.add(visit)
        session.add_all(
            [
                _fuel(seed.vin, date(2024, 2, 20), "40.00", "20300.00"),
                _fuel(seed.vin, date(2024, 5, 20), "50.00", "21400.00"),
            ]
        )
        await session.commit()

    yield seed

    # A failed request can leave the shared session mid-transaction.
    await db_session.rollback()
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == seed.vin))
    await db_session.execute(delete(Vendor).where(Vendor.name == seed.vendor_name))
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.analytics
@pytest.mark.asyncio
class TestAnalyticsEndpoints:
    """Test analytics API endpoints with real database data."""

    async def test_get_vehicle_analytics_success(
        self,
        client: AsyncClient,
        seeded_vehicle: SeededVehicle,
        auth_headers: dict,
    ):
        """The cost analysis adds up the seeded visits and fill-ups."""
        response = await client.get(
            f"/api/analytics/vehicles/{seeded_vehicle.vin}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == seeded_vehicle.vin
        assert data["vehicle_name"] == "2019 Toyota Tacoma"

        cost_analysis = data["cost_analysis"]
        assert Decimal(str(cost_analysis["total_service_cost"])) == Decimal("230.00")
        assert Decimal(str(cost_analysis["total_fuel_cost"])) == Decimal("90.00")
        assert Decimal(str(cost_analysis["total_cost"])) == Decimal("320.00")
        assert cost_analysis["service_count"] == 2
        assert cost_analysis["fuel_count"] == 2
        assert cost_analysis["months_tracked"] == 2
        assert Decimal(str(cost_analysis["average_monthly_cost"])) == Decimal("160.00")
        assert [
            (m["year"], m["month"], Decimal(str(m["total_cost"])))
            for m in cost_analysis["monthly_breakdown"]
        ] == [(2024, 2, Decimal("120.00")), (2024, 5, Decimal("200.00"))]
        assert {
            row["service_type"]: Decimal(str(row["total_cost"]))
            for row in cost_analysis["service_type_breakdown"]
        } == {"Oil change": Decimal("80.00"), "Brake pads": Decimal("150.00")}

    async def test_get_vehicle_analytics_invalid_vin(self, client: AsyncClient, auth_headers: dict):
        """Test getting analytics for non-existent vehicle."""
        response = await client.get("/api/analytics/vehicles/INVALIDVIN123", headers=auth_headers)

        assert response.status_code == 404

    async def test_get_vendor_analytics(
        self,
        client: AsyncClient,
        seeded_vehicle: SeededVehicle,
        auth_headers: dict,
    ):
        """Both seeded visits roll up under the one shop; fuel stays out."""
        response = await client.get(
            f"/api/analytics/vehicles/{seeded_vehicle.vin}/vendors",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total_vendors"] == 1
        assert data["most_used_vendor"] == seeded_vehicle.vendor_name
        assert data["highest_spending_vendor"] == seeded_vehicle.vendor_name
        [vendor] = data["vendors"]
        assert vendor["vendor_name"] == seeded_vehicle.vendor_name
        assert Decimal(str(vendor["total_spent"])) == Decimal("230.00")
        assert Decimal(str(vendor["average_cost"])) == Decimal("115.00")
        assert vendor["service_count"] == 2
        assert vendor["service_types"] == ["Brake pads", "Oil change"]
        assert vendor["last_service_date"] == "2024-05-10"

    async def test_get_seasonal_analytics(
        self,
        client: AsyncClient,
        seeded_vehicle: SeededVehicle,
        auth_headers: dict,
    ):
        """February lands in winter and May in spring, visits and fuel both."""
        response = await client.get(
            f"/api/analytics/vehicles/{seeded_vehicle.vin}/seasonal",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert [
            (s["season"], Decimal(str(s["total_cost"])), s["service_count"])
            for s in data["seasons"]
        ] == [
            ("Winter", Decimal("120.00"), 2),
            ("Spring", Decimal("200.00"), 2),
            ("Summer", Decimal("0.00"), 0),
            ("Fall", Decimal("0.00"), 0),
        ]
        assert Decimal(str(data["annual_average"])) == Decimal("80.00")
        assert data["highest_cost_season"] == "Spring"

    async def test_compare_periods(
        self,
        client: AsyncClient,
        seeded_vehicle: SeededVehicle,
        auth_headers: dict,
    ):
        """Q1 2024 holds the February spend and Q2 the May spend."""
        response = await client.get(
            f"/api/analytics/vehicles/{seeded_vehicle.vin}/compare",
            params={
                "period1_start": "2024-01-01",
                "period1_end": "2024-03-31",
                "period2_start": "2024-04-01",
                "period2_end": "2024-06-30",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["period1_label"] == "Jan 2024 - Mar 2024"
        assert data["period2_label"] == "Apr 2024 - Jun 2024"
        assert Decimal(str(data["period1_total_cost"])) == Decimal("120.00")
        assert Decimal(str(data["period2_total_cost"])) == Decimal("200.00")
        assert Decimal(str(data["cost_change_amount"])) == Decimal("80.00")
        assert Decimal(str(data["cost_change_percent"])) == Decimal("66.67")
        assert data["period1_service_count"] == 1
        assert data["period2_service_count"] == 1
        assert {
            c["category"]: (Decimal(str(c["period1_value"])), Decimal(str(c["period2_value"])))
            for c in data["category_changes"]
        } == {
            "Oil change": (Decimal("80.00"), Decimal("0.00")),
            "Brake pads": (Decimal("0.00"), Decimal("150.00")),
        }

    async def test_compare_periods_missing_params(
        self, client: AsyncClient, test_vehicle: dict, auth_headers: dict
    ):
        """Test period comparison with missing parameters."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/compare",
            params={
                "period1_start": "2024-01-01",
                # Missing other required params
            },
            headers=auth_headers,
        )

        # Should return 422 for validation error
        assert response.status_code == 422

    async def test_export_analytics_pdf(
        self,
        client: AsyncClient,
        seeded_vehicle: SeededVehicle,
        auth_headers: dict,
    ):
        """The vehicle PDF carries the seeded vehicle and its shop."""
        response = await client.get(
            f"/api/analytics/vehicles/{seeded_vehicle.vin}/export",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment" in response.headers.get("content-disposition", "")
        assert response.content[:5] == b"%PDF-"

        text = _extract_pdf_text(response.content)
        assert "2019 Toyota Tacoma" in text
        assert seeded_vehicle.vendor_name in text

    async def test_export_analytics_pdf_includes_pending_hours_reminder(
        self,
        client: AsyncClient,
        seeded_vehicle: SeededVehicle,
        auth_headers: dict,
    ):
        """A pending hours reminder on the vehicle must render in the
        exported PDF's "Upcoming Reminders" section, proving
        `reminders_data` is wired end-to-end from the route (not just at
        the PDF-builder-function level). The reminder goes with the vehicle."""
        vin = seeded_vehicle.vin

        create_resp = await client.post(
            f"/api/vehicles/{vin}/reminders",
            json={
                "title": "Hydraulic fluid change",
                "reminder_type": "hours",
                "due_hours": 500.0,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201

        response = await client.get(
            f"/api/analytics/vehicles/{vin}/export",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.content[:5] == b"%PDF-"

        text = _extract_pdf_text(response.content)
        assert "Upcoming Reminders" in text
        assert "Hydraulic fluid change" in text
        assert "500.0 hr" in text

    async def test_export_garage_analytics_pdf(
        self,
        client: AsyncClient,
        seeded_vehicle: SeededVehicle,
        auth_headers: dict,
    ):
        """The garage PDF lists the seeded vehicle in its cost table."""
        response = await client.get(
            "/api/analytics/garage/export",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment" in response.headers.get("content-disposition", "")
        assert response.content[:5] == b"%PDF-"

        # The table wraps a name across lines, so compare without whitespace.
        squashed = "".join(_extract_pdf_text(response.content).split())
        assert "".join(seeded_vehicle.nickname.split()) in squashed

    async def test_garage_analytics(self, client: AsyncClient, test_user: User, auth_headers: dict):
        """Test garage-wide analytics endpoint."""
        response = await client.get("/api/analytics/garage", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert "total_costs" in data
        assert "cost_breakdown_by_category" in data
        assert "cost_by_vehicle" in data
        assert "monthly_trends" in data
        assert "vehicle_count" in data

        # Validate total_costs structure
        total_costs = data["total_costs"]
        assert "total_garage_value" in total_costs
        assert "total_maintenance" in total_costs
        assert "total_fuel" in total_costs


@pytest.mark.integration
@pytest.mark.analytics
@pytest.mark.asyncio
async def test_a_reading_added_after_a_read_shows_on_the_next_one(
    client: AsyncClient, own_vehicle: Vehicle, auth_headers: dict
):
    """An hours reading saved through its own route shows on the very next read.

    The hours routes never cleared the analytics cache, so once the cache keyed
    on the VIN alone the series stayed stale for 10 minutes.
    """
    vin = own_vehicle.vin
    url = f"/api/analytics/vehicles/{vin}"

    before = await client.get(url, headers=auth_headers)
    assert before.status_code == 200, before.text
    assert before.json()["hours_accumulated"] == []

    added = await client.post(
        f"/api/vehicles/{vin}/hours",
        json={"vin": vin, "date": "2024-04-01", "engine_hours": 120.5},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text

    after = await client.get(url, headers=auth_headers)
    assert [
        (p["date"], Decimal(str(p["engine_hours"]))) for p in after.json()["hours_accumulated"]
    ] == [("2024-04-01", Decimal("120.5"))]


@pytest.mark.integration
@pytest.mark.analytics
@pytest.mark.asyncio
async def test_a_fill_up_written_behind_the_routes_shows_on_the_next_read(
    client: AsyncClient,
    seeded_vehicle: SeededVehicle,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    auth_headers: dict,
):
    """Nothing caches the analytics, so a write no route saw still shows at once.

    It used to be held in a 10 minute cache that only some writes cleared.
    """
    vin = seeded_vehicle.vin

    response1 = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
    assert response1.status_code == 200
    assert Decimal(str(response1.json()["cost_analysis"]["total_cost"])) == Decimal("320.00")

    async with test_sessionmaker() as session:
        session.add(_fuel(vin, date(2024, 8, 15), "30.00"))
        await session.commit()

    response2 = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
    assert response2.status_code == 200
    # The part the extra fill-up moves, not the whole payload.
    assert Decimal(str(response2.json()["cost_analysis"]["total_cost"])) == Decimal("350.00")


@pytest.mark.integration
@pytest.mark.analytics
@pytest.mark.asyncio
async def test_anomaly_detection(
    client: AsyncClient,
    seeded_vehicle: SeededVehicle,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    auth_headers: dict,
):
    """One 2000.00 month among eight quiet ones is flagged, and only that one.

    Detection needs a 2-sigma outlier, which two months can never be, so the
    test adds six 50.00 months and the spike to the seed.
    """
    vin = seeded_vehicle.vin
    async with test_sessionmaker() as session:
        session.add_all([_fuel(vin, date(2023, month, 10), "50.00") for month in range(1, 7)])
        session.add(_fuel(vin, date(2023, 7, 10), "2000.00"))
        await session.commit()

    response = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)

    assert response.status_code == 200
    [anomaly] = response.json()["cost_analysis"]["anomalies"]
    assert anomaly["month"] == "2023-07"
    assert Decimal(str(anomaly["amount"])) == Decimal("2000.00")
    # Nine months, 2620.00 in all.
    assert float(anomaly["baseline"]) == pytest.approx(2620 / 9)
    assert anomaly["severity"] == "critical"


@pytest.mark.integration
@pytest.mark.analytics
@pytest.mark.asyncio
async def test_analytics_pdf_requests_full_anomaly_history(
    client: AsyncClient, test_vehicle, auth_headers: dict, monkeypatch
):
    """The PDF must ask for every anomaly, not the default display window.

    `export_analytics_pdf` calls `get_vehicle_analytics` as a plain function, so
    an omitted `anomaly_range` binds the fastapi Query OBJECT rather than its
    default string. Every `== "3m"` test then fails and
    `filter_anomalies_to_window` falls through to its 12-month else branch, which
    silently drops older anomalies from the report. Changing the Query default
    alone does not fix that: the argument has to be passed here.
    """
    from app.routes import analytics as analytics_routes

    seen: dict[str, object] = {}
    original = analytics_routes.get_vehicle_analytics

    async def _spy(vin, *args, **kwargs):
        seen.update(kwargs)
        return await original(vin, *args, **kwargs)

    monkeypatch.setattr(analytics_routes, "get_vehicle_analytics", _spy)

    response = await client.get(
        f"/api/analytics/vehicles/{test_vehicle['vin']}/export",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.content[:4] == b"%PDF"
    assert seen.get("anomaly_range") == "all", (
        "the PDF path must pass anomaly_range explicitly; a bound Query object "
        "silently means 12 months"
    )


@dataclass(frozen=True)
class MixedGarage:
    """A one-user garage holding every kind of spend."""

    headers: dict[str, str]
    vins: tuple[str, str]


# Running costs the mixed garage should report: service in two categories,
# fuel and DEF on the first car, one fill-up on the second.
MIXED_RUNNING = Decimal("100.00") + Decimal("250.00") + Decimal("60.00") + Decimal("15.50")
MIXED_RUNNING += Decimal("40.00")
# What sits beside them and must stay out: insurance, tax, financing.
MIXED_OTHER = Decimal("120.00") + Decimal("80.00") + Decimal("300.00")


@pytest_asyncio.fixture
async def mixed_garage(db_session: AsyncSession) -> AsyncGenerator[MixedGarage]:
    """A fresh non-admin user who owns just these two cars, so the totals are ours."""
    suffix = uuid.uuid4().hex[:14].upper()
    username = f"runcost_{suffix[:8].lower()}"
    vin_a, vin_b = f"RCA{suffix}", f"RCB{suffix}"
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=TEST_PASSWORD_HASH,
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()
    for vin, nickname in ((vin_a, "Runner"), (vin_b, "Spare")):
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=user.id,
                nickname=f"{nickname} {suffix[:4]}",
                vehicle_type="Car",
                year=2020,
                make="Ford",
                model="Ranger",
            )
        )
    await db_session.flush()
    for category, cost in (("Maintenance", "100.00"), ("Upgrades", "250.00")):
        visit = ServiceVisit(vin=vin_a, date=date(2024, 3, 1), service_category=category)
        visit.line_items.append(ServiceLineItem(description=category, cost=Decimal(cost)))
        db_session.add(visit)
    db_session.add_all(
        [
            _fuel(vin_a, date(2024, 3, 5), "60.00"),
            _fuel(vin_b, date(2024, 3, 6), "40.00"),
            DEFRecord(
                vin=vin_a, date=date(2024, 3, 7), liters=Decimal("9.000"), cost=Decimal("15.50")
            ),
            TaxRecord(vin=vin_a, date=date(2024, 3, 8), amount=Decimal("80.00")),
            FinancingRecord(
                vin=vin_a, date=date(2024, 3, 9), amount=Decimal("300.00"), category="loan_payment"
            ),
        ]
    )
    # A finished term, so the whole premium has accrued.
    start = household_today() - timedelta(days=200)
    policy = InsurancePolicy(
        provider="Progressive",
        policy_number=f"P-{suffix[:6]}",
        start_date=start,
        end_date=start + timedelta(days=182),
        premium_amount=Decimal("120.00"),
        premium_frequency="Semi-Annual",
    )
    policy.vehicle_links.append(InsurancePolicyVehicle(vin=vin_a, policy_type="Liability"))
    db_session.add(policy)
    await db_session.commit()
    policy_id = policy.id
    token = create_access_token(data={"sub": str(user.id), "username": username})

    yield MixedGarage(headers={"Authorization": f"Bearer {token}"}, vins=(vin_a, vin_b))

    await db_session.rollback()
    await db_session.execute(delete(InsurancePolicy).where(InsurancePolicy.id == policy_id))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_([vin_a, vin_b])))
    await db_session.execute(delete(User).where(User.username == username))
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.analytics
@pytest.mark.asyncio
async def test_garage_running_cost_is_service_fuel_and_def(
    client: AsyncClient, mixed_garage: MixedGarage
):
    """One number for the PDF: service + fuel + DEF, same as the per-vehicle Total."""
    response = await client.get("/api/analytics/garage", headers=mixed_garage.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    totals = body["total_costs"]

    # The fixture really did land insurance, tax and financing.
    assert Decimal(totals["total_insurance"]) == Decimal("120.00")
    assert Decimal(totals["total_taxes"]) == Decimal("80.00")
    assert Decimal(totals["total_financing"]) == Decimal("300.00")

    # The category totals and the per-vehicle Totals must count the same thing.
    categories = (
        "total_maintenance",
        "total_upgrades",
        "total_inspection",
        "total_collision",
        "total_detailing",
        "total_fuel",
        "total_def",
    )
    by_category = sum((Decimal(totals[k]) for k in categories), Decimal("0"))
    by_vehicle = sum((Decimal(v["total_cost"]) for v in body["cost_by_vehicle"]), Decimal("0"))
    assert by_category == by_vehicle == MIXED_RUNNING

    assert Decimal(totals["total_running_cost"]) == MIXED_RUNNING


@pytest.mark.integration
@pytest.mark.analytics
@pytest.mark.asyncio
async def test_garage_pdf_shows_the_running_cost_not_the_all_in_sum(
    client: AsyncClient, mixed_garage: MixedGarage
):
    """The KPI card prints the route's running cost, not everything added up."""
    response = await client.get("/api/analytics/garage/export", headers=mixed_garage.headers)
    assert response.status_code == 200, response.text

    text = " ".join(_extract_pdf_text(response.content).split())
    assert "RUNNING COST" in text
    assert "OPERATING COST" not in text
    assert f"${MIXED_RUNNING:,.2f}" in text
    assert f"${MIXED_RUNNING + MIXED_OTHER:,.2f}" not in text
