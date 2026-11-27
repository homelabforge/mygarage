"""A vehicle's current odometer is the highest reading on its latest day.

An odometer does not run backwards within a day, so which source happened to
write its row first says nothing about which figure is current. The reads that
took the NEWEST row of the latest day reported a service visit's 50,000 km as
current when the tire it fitted had been mounted at 50,012 km earlier the same
day, and the new tire's distance then read as the odometer running backwards.

Every read of a current or latest odometer orders by date, then odometer, then
id. These tests seed the one shape that tells the two rules apart: on the
latest day, the higher reading has the OLDER id.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.models.odometer import OdometerRecord
from app.models.vehicle import Vehicle
from app.services.reminder_service import get_current_mileage
from app.services.tire_service import TireService
from app.services.widget_aggregation import WidgetAggregationService
from app.utils.odometer_sync import auto_sync_marker

DAY = date(2026, 6, 21)
EARLIER = DAY - timedelta(days=10)


@pytest_asyncio.fixture
async def vehicle(db_session, test_user):
    vin = f"CURODO{uuid.uuid4().hex[:11].upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Current odometer",
            vehicle_type="Car",
            year=2017,
            make="Skoda",
            model="Octavia",
        )
    )
    await db_session.commit()
    yield vin
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


@pytest_asyncio.fixture
async def mounted_then_serviced(client: AsyncClient, auth_headers, vehicle, db_session) -> int:
    """The latest day holds the tire mount's 50,012 km (older id) and a service
    visit's 50,000 km (newer id); ten days earlier a manual 49,000 km.

    The service row is seeded directly, as a service visit synced beside the
    tire's row would leave it. Returns the tire's id.
    """
    mounted = await client.post(
        f"/api/vehicles/{vehicle}/tires/create-and-mount",
        headers=auth_headers,
        json={
            "vin": vehicle,
            "position": "FL",
            "mounted_on": DAY.isoformat(),
            "mounted_odometer_km": "50012",
        },
    )
    assert mounted.status_code == 201, mounted.text
    db_session.add(
        OdometerRecord(
            vin=vehicle, date=EARLIER, odometer_km=Decimal("49000"), source="manual", notes="hand"
        )
    )
    await db_session.commit()
    db_session.add(
        OdometerRecord(
            vin=vehicle,
            date=DAY,
            odometer_km=Decimal("50000"),
            source="service_visit",
            notes=auto_sync_marker("service_visit", 987654),
        )
    )
    await db_session.commit()
    return mounted.json()["id"]


@pytest.mark.asyncio
class TestTheHighestReadingOfTheLatestDayIsCurrent:
    async def test_the_new_tires_distance_is_not_a_rollback(
        self, client: AsyncClient, auth_headers, vehicle, mounted_then_serviced, db_session
    ):
        assert await TireService(db_session)._current_odometer(vehicle) == Decimal("50012")
        listed = await client.get(f"/api/vehicles/{vehicle}/tires", headers=auth_headers)
        assert listed.status_code == 200, listed.text
        tire = next(t for t in listed.json()["tires"] if t["id"] == mounted_then_serviced)
        assert tire["distance_status"] == "complete"
        assert tire["distance_km"] == "0.00"

    async def test_the_vehicle_detail_shows_the_days_highest_reading(
        self, client: AsyncClient, auth_headers, vehicle, mounted_then_serviced
    ):
        detail = await client.get(f"/api/vehicles/{vehicle}/detail-stats", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["latest_odometer_km"] == "50012.00"
        assert detail.json()["latest_odometer_date"] == DAY.isoformat()

    async def test_reminders_read_the_days_highest_reading(
        self, vehicle, mounted_then_serviced, db_session
    ):
        assert await get_current_mileage(vehicle, db_session) == Decimal("50012")

    async def test_the_odometer_list_reports_the_days_highest_reading(
        self, client: AsyncClient, auth_headers, vehicle, mounted_then_serviced
    ):
        listed = await client.get(f"/api/vehicles/{vehicle}/odometer", headers=auth_headers)
        assert listed.status_code == 200, listed.text
        assert Decimal(str(listed.json()["latest_odometer_km"])) == Decimal("50012")

    async def test_the_widget_reads_the_days_highest_reading(
        self, vehicle, mounted_then_serviced, db_session
    ):
        widget = WidgetAggregationService(db_session)
        assert await widget._latest_odometer_reading(vehicle) == (Decimal("50012"), DAY)
        assert await widget._latest_odometer_km(vehicle) == 50012

    async def test_vehicle_analytics_total_runs_to_the_days_highest_reading(
        self, client: AsyncClient, auth_headers, vehicle, mounted_then_serviced
    ):
        analytics = await client.get(f"/api/analytics/vehicles/{vehicle}", headers=auth_headers)
        assert analytics.status_code == 200, analytics.text
        assert Decimal(str(analytics.json()["total_km_driven"])) == Decimal("1012")
