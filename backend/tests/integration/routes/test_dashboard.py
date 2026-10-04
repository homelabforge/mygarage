"""
Integration tests for dashboard routes.

Tests dashboard aggregation and statistics endpoints.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DEFRecord,
    FuelRecord,
    HoursRecord,
    OdometerRecord,
    Reminder,
    ServiceVisit,
    Vehicle,
)


async def _isolated_fleet(db_session: AsyncSession) -> tuple[str, dict[str, str]]:
    """Create a throwaway non-admin owner + one vehicle and return
    ``(vin, auth_headers)`` whose ``/api/dashboard`` fleet is EXACTLY that vehicle.

    The integration test DB is session-scoped and accumulates rows across files
    (e.g. ``test_calendar`` seeds an "Overdue Brake Check" reminder), so the
    admin fleet (all vehicles) and the shared ``non_admin_user`` fleet are both
    polluted for whichever test runs later. A fresh, uniquely-named owner with a
    single vehicle isolates the fleet to this test's seeded rows, which is what
    keeps the exact fleet-wide assertions (Upcoming count, Next-due winner) both
    valid and discriminating.
    """
    import uuid

    from app.models.user import User
    from app.services.auth import create_access_token

    suffix = uuid.uuid4().hex[:12]
    # Pre-computed argon2id hash (same constant the conftest user fixtures use).
    password_hash = (
        "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$"
        "hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
    )
    user = User(
        username=f"fleet_{suffix}",
        email=f"fleet_{suffix}@example.com",
        hashed_password=password_hash,
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # "FLEET" + 12 hex chars = exactly 17 chars, no I/O/Q -> a valid unique VIN.
    vin = f"FLEET{suffix.upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=user.id,
            nickname=f"Fleet {suffix}",
            vehicle_type="Car",
        )
    )
    await db_session.commit()

    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return vin, {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
@pytest.mark.asyncio
class TestDashboardRoutes:
    """Test dashboard API endpoints."""

    async def test_get_dashboard(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test getting dashboard with authenticated user."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "total_vehicles" in data
        assert "vehicles" in data
        assert isinstance(data["vehicles"], list)

    async def test_dashboard_response_structure(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that dashboard response has correct structure."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify main fields
        assert "total_vehicles" in data
        assert "total_service_records" in data
        assert "total_fuel_records" in data
        assert "total_maintenance_items" in data
        assert "total_documents" in data
        assert "total_notes" in data
        assert "total_photos" in data
        assert "vehicles" in data

        # Verify types
        assert isinstance(data["total_vehicles"], int)
        assert isinstance(data["total_service_records"], int)
        assert isinstance(data["vehicles"], list)

    async def test_dashboard_vehicle_statistics(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test vehicle statistics in dashboard."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Should have at least the test vehicle
        assert data["total_vehicles"] >= 1

        # Find our test vehicle
        test_vehicle_stats = None
        for vehicle in data["vehicles"]:
            if vehicle["vin"] == test_vehicle["vin"]:
                test_vehicle_stats = vehicle
                break

        assert test_vehicle_stats is not None
        # Verify vehicle statistics structure
        assert "vin" in test_vehicle_stats
        assert "total_service_records" in test_vehicle_stats
        assert "total_fuel_records" in test_vehicle_stats
        assert "total_odometer_records" in test_vehicle_stats
        assert "total_maintenance_items" in test_vehicle_stats
        assert "total_documents" in test_vehicle_stats
        assert "total_notes" in test_vehicle_stats
        assert "total_photos" in test_vehicle_stats
        assert "upcoming_maintenance_count" in test_vehicle_stats
        assert "overdue_maintenance_count" in test_vehicle_stats

    async def test_pure_distance_vehicle_has_null_hours_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Part A: a vehicle with no hours_records rows must never leak an
        hours figure — latest_hours/average_l_per_hr/average_cost_per_hr stay
        null and secondary_usage_enabled defaults false on the garage-list
        VehicleStatistics card."""
        vin, headers = await _isolated_fleet(db_session)
        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        card = next(v for v in response.json()["vehicles"] if v["vin"] == vin)
        assert card["latest_hours"] is None
        assert card["average_l_per_hr"] is None
        assert card["average_cost_per_hr"] is None
        assert card["secondary_usage_enabled"] is False

    async def test_dashboard_hours_reminder_overdue_is_counted(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Phase 6b: a pure `hours` reminder (due_hours, no due_date) with
        current_hours >= due_hours counts toward overdue_maintenance_count,
        exactly like a mileage reminder does today."""
        vin, headers = await _isolated_fleet(db_session)
        db_session.add(HoursRecord(vin=vin, date=date.today(), engine_hours=Decimal("600.0")))
        db_session.add(
            Reminder(
                vin=vin,
                title="Dashboard Hours Overdue Test",
                reminder_type="hours",
                due_hours=Decimal("500.0"),
                status="pending",
            )
        )
        await db_session.commit()

        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        card = next(v for v in response.json()["vehicles"] if v["vin"] == vin)
        assert card["overdue_maintenance_count"] == 1
        assert card["upcoming_maintenance_count"] == 0

    async def test_dashboard_hours_reminder_not_yet_due_is_not_overdue(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A pure hours reminder below its target is upcoming, not overdue."""
        vin, headers = await _isolated_fleet(db_session)
        db_session.add(HoursRecord(vin=vin, date=date.today(), engine_hours=Decimal("100.0")))
        db_session.add(
            Reminder(
                vin=vin,
                title="Dashboard Hours Not Due Test",
                reminder_type="hours",
                due_hours=Decimal("500.0"),
                status="pending",
            )
        )
        await db_session.commit()

        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        card = next(v for v in response.json()["vehicles"] if v["vin"] == vin)
        assert card["overdue_maintenance_count"] == 0
        assert card["upcoming_maintenance_count"] == 1

    async def test_dashboard_mixed_date_mileage_hours_reminders_all_evaluated(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Regression: date, mileage, AND hours reminders on the SAME vehicle
        each evaluate independently and correctly — the new hours branch
        doesn't cross-contaminate the pre-existing date/mileage checks."""
        vin, headers = await _isolated_fleet(db_session)
        db_session.add(OdometerRecord(vin=vin, date=date.today(), odometer_km=Decimal("60000")))
        db_session.add(HoursRecord(vin=vin, date=date.today(), engine_hours=Decimal("50.0")))
        db_session.add_all(
            [
                Reminder(
                    vin=vin,
                    title="Overdue by date",
                    reminder_type="date",
                    due_date=date.today() - timedelta(days=1),
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="Not overdue by mileage",
                    reminder_type="mileage",
                    due_mileage_km=Decimal("100000"),
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="Overdue by hours",
                    reminder_type="hours",
                    due_hours=Decimal("40.0"),
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="Not overdue by hours",
                    reminder_type="hours",
                    due_hours=Decimal("500.0"),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        card = next(v for v in response.json()["vehicles"] if v["vin"] == vin)
        # 2 overdue (date + hours), 2 upcoming (mileage + hours).
        assert card["overdue_maintenance_count"] == 2
        assert card["upcoming_maintenance_count"] == 2

    async def test_dashboard_fetches_current_hours_once_per_vehicle(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        """No N+1: latest_engine_hours_and_date is called exactly once per
        vehicle regardless of how many pending hours reminders it has —
        dashboard.py already fetches it once for the `latest_hours` display
        figure and must reuse that SAME reading for the reminder evaluation,
        not re-query per reminder."""
        import app.routes.dashboard as dashboard_module

        vin, headers = await _isolated_fleet(db_session)
        db_session.add(HoursRecord(vin=vin, date=date.today(), engine_hours=Decimal("500.0")))
        db_session.add_all(
            [
                Reminder(
                    vin=vin,
                    title="A",
                    reminder_type="hours",
                    due_hours=Decimal("100.0"),
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="B",
                    reminder_type="hours",
                    due_hours=Decimal("200.0"),
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="C",
                    reminder_type="hours",
                    due_hours=Decimal("999.0"),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        calls: dict[str, int] = {"n": 0}
        original = dashboard_module.latest_engine_hours_and_date

        async def counting(db, vin_arg):
            calls["n"] += 1
            return await original(db, vin_arg)

        monkeypatch.setattr(dashboard_module, "latest_engine_hours_and_date", counting)

        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        assert calls["n"] == 1

    async def test_dashboard_after_adding_service_visit(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that dashboard reflects new service visits."""
        # Get initial dashboard
        initial_response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        initial_data = initial_response.json()

        # Add a service visit
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json={
                "date": "2024-06-15",
                "odometer_km": 88513.7,
                "service_category": "Maintenance",
                "notes": "Dashboard Test Service",
                "line_items": [
                    {"description": "Dashboard Test", "cost": 100.00},
                ],
            },
            headers=auth_headers,
        )

        # Get updated dashboard
        updated_response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        updated_data = updated_response.json()

        # Total service records should have increased
        assert updated_data["total_service_records"] >= initial_data["total_service_records"]

    async def test_dashboard_after_adding_fuel_record(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that dashboard reflects new fuel records."""
        # Add a fuel record
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/fuel",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-06-15",
                "odometer_km": 90123.04,
                "liters": 47.318,
                "cost": 43.75,
                "fuel_type": "Regular",
            },
            headers=auth_headers,
        )

        # Get dashboard
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Total fuel records should include our new record
        assert data["total_fuel_records"] >= 1

    async def test_dashboard_maintenance_counts(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
    ):
        """Test that dashboard tracks maintenance schedule counts correctly."""
        # Create an upcoming reminder
        item_upcoming = Reminder(
            vin=test_vehicle["vin"],
            title="Dashboard upcoming item",
            reminder_type="date",
            due_date=date.today() + timedelta(days=15),
            status="pending",
        )
        db_session.add(item_upcoming)

        # Create an overdue reminder
        item_overdue = Reminder(
            vin=test_vehicle["vin"],
            title="Dashboard overdue item",
            reminder_type="date",
            due_date=date.today() - timedelta(days=30),
            status="pending",
        )
        db_session.add(item_overdue)
        await db_session.commit()

        # Get dashboard
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Find our test vehicle
        test_vehicle_stats = None
        for vehicle in data["vehicles"]:
            if vehicle["vin"] == test_vehicle["vin"]:
                test_vehicle_stats = vehicle
                break

        assert test_vehicle_stats is not None
        # Should have overdue count
        assert test_vehicle_stats["overdue_maintenance_count"] >= 1

    async def test_dashboard_latest_dates(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that dashboard tracks latest service/fuel dates."""
        # Add a service visit with known date
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json={
                "date": "2024-07-15",
                "odometer_km": 96560.4,
                "service_category": "Maintenance",
                "notes": "Latest Date Test",
                "line_items": [
                    {"description": "Latest Date Test Service", "cost": 50.00},
                ],
            },
            headers=auth_headers,
        )

        # Get dashboard
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Find our test vehicle
        test_vehicle_stats = None
        for vehicle in data["vehicles"]:
            if vehicle["vin"] == test_vehicle["vin"]:
                test_vehicle_stats = vehicle
                break

        assert test_vehicle_stats is not None
        # latest_service_date should be set
        assert test_vehicle_stats["latest_service_date"] is not None

    async def test_dashboard_unauthenticated(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users can access dashboard (legacy behavior)."""
        # Uses optional_auth, so should work without auth
        response = await client.get("/api/dashboard")

        # Should return 200 or 401 depending on auth settings
        assert response.status_code in [200, 401]

    async def test_dashboard_totals_match_vehicle_sums(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that dashboard totals match sum of vehicle statistics."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Calculate sums from vehicles
        vehicle_service_sum = sum(v["total_service_records"] for v in data["vehicles"])
        vehicle_fuel_sum = sum(v["total_fuel_records"] for v in data["vehicles"])
        vehicle_maintenance_sum = sum(v["total_maintenance_items"] for v in data["vehicles"])
        vehicle_document_sum = sum(v["total_documents"] for v in data["vehicles"])
        vehicle_note_sum = sum(v["total_notes"] for v in data["vehicles"])
        vehicle_photo_sum = sum(v["total_photos"] for v in data["vehicles"])

        # Totals should match sums
        assert data["total_service_records"] == vehicle_service_sum
        assert data["total_fuel_records"] == vehicle_fuel_sum
        assert data["total_maintenance_items"] == vehicle_maintenance_sum
        assert data["total_documents"] == vehicle_document_sum
        assert data["total_notes"] == vehicle_note_sum
        assert data["total_photos"] == vehicle_photo_sum

    async def test_dashboard_vehicle_info(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that dashboard includes vehicle identifying information."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Find our test vehicle
        test_vehicle_stats = None
        for vehicle in data["vehicles"]:
            if vehicle["vin"] == test_vehicle["vin"]:
                test_vehicle_stats = vehicle
                break

        assert test_vehicle_stats is not None
        # Should have vehicle identification fields
        assert "vin" in test_vehicle_stats
        assert "year" in test_vehicle_stats
        assert "make" in test_vehicle_stats
        assert "model" in test_vehicle_stats

    async def test_dashboard_shared_vehicle_fields(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that vehicle stats include sharing-related fields."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Find any vehicle
        if data["vehicles"]:
            vehicle = data["vehicles"][0]
            # Should have sharing-related fields (even if not shared)
            assert "is_shared_with_me" in vehicle
            assert "shared_by_username" in vehicle
            assert "share_permission" in vehicle

    async def test_dashboard_fleet_health_structure(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """fleet_health carries the full contract, the current year, JSON types."""
        response = await client.get("/api/dashboard", headers=auth_headers)
        assert response.status_code == 200
        fh = response.json()["fleet_health"]

        assert set(fh.keys()) == {
            "overdue_count",
            "upcoming_30d_count",
            "year",
            "spent_this_year",
            "next_due",
        }
        assert isinstance(fh["overdue_count"], int)
        assert isinstance(fh["upcoming_30d_count"], int)
        assert fh["year"] == date.today().year
        # Decimal serializes to a JSON string.
        assert isinstance(fh["spent_this_year"], str)

    async def test_dashboard_vehicle_type_is_exact(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Each vehicle stat carries the EXACT vehicle_type, not merely the key."""
        response = await client.get("/api/dashboard", headers=auth_headers)
        assert response.status_code == 200
        stat = next(v for v in response.json()["vehicles"] if v["vin"] == test_vehicle["vin"])
        # test_vehicle is created with vehicle_type="Car" (conftest). A default
        # None would fail here, so the field is genuinely populated.
        assert stat["vehicle_type"] == "Car"

    async def test_fleet_health_spent_this_year_is_ytd_scoped(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
    ):
        """Spent = service + fuel + DEF dated year_start..today; prior-year AND
        later-this-year records are both excluded (true YTD)."""
        vin = test_vehicle["vin"]
        today = date.today()

        before = Decimal(
            (await client.get("/api/dashboard", headers=auth_headers)).json()["fleet_health"][
                "spent_this_year"
            ]
        )

        db_session.add_all(
            [
                # In range (dated today): service 100 + fuel 40 + DEF 20 = 160.
                ServiceVisit(
                    vin=vin,
                    date=today,
                    service_category="Maintenance",
                    shop_supplies=Decimal("100.00"),
                ),
                FuelRecord(vin=vin, date=today, cost=Decimal("40.00")),
                DEFRecord(vin=vin, date=today, cost=Decimal("20.00")),
                # Prior calendar year — excluded.
                FuelRecord(vin=vin, date=date(today.year - 1, 6, 1), cost=Decimal("999.00")),
                # Later THIS year (future) — excluded by the `<= today` upper
                # bound. This is the record the old `< next_year_start` range
                # wrongly counted (review finding 5).
                ServiceVisit(
                    vin=vin,
                    date=today + timedelta(days=1),
                    service_category="Maintenance",
                    shop_supplies=Decimal("777.00"),
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/dashboard", headers=auth_headers)
        assert response.status_code == 200
        after = Decimal(response.json()["fleet_health"]["spent_this_year"])

        assert after - before == Decimal("160.00")

    async def test_fleet_health_upcoming_excludes_today_and_far(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """upcoming_30d_count = strictly-future within 30 days; a due-today
        reminder is Overdue only, never double-counted (review finding 6)."""
        vin, headers = await _isolated_fleet(db_session)
        today = date.today()
        db_session.add_all(
            [
                Reminder(
                    vin=vin,
                    title="Due today",
                    reminder_type="date",
                    due_date=today,
                    status="pending",
                ),  # overdue, NOT upcoming
                Reminder(
                    vin=vin,
                    title="In 10 days",
                    reminder_type="date",
                    due_date=today + timedelta(days=10),
                    status="pending",
                ),  # upcoming
                Reminder(
                    vin=vin,
                    title="In 30 days",
                    reminder_type="date",
                    due_date=today + timedelta(days=30),
                    status="pending",
                ),  # upcoming (boundary)
                Reminder(
                    vin=vin,
                    title="In 31 days",
                    reminder_type="date",
                    due_date=today + timedelta(days=31),
                    status="pending",
                ),  # excluded
                Reminder(
                    vin=vin,
                    title="Overdue 3d",
                    reminder_type="date",
                    due_date=today - timedelta(days=3),
                    status="pending",
                ),  # overdue
                Reminder(
                    vin=vin,
                    title="In 5 days, snoozed",
                    reminder_type="date",
                    due_date=today + timedelta(days=5),
                    snoozed_until=today + timedelta(days=20),
                    status="pending",
                ),  # out of every count until the snooze ends
            ]
        )
        await db_session.commit()

        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        data = response.json()
        fh = data["fleet_health"]
        card = next(v for v in data["vehicles"] if v["vin"] == vin)

        # The card: overdue (today, -3d), pending (10d, 30d, 31d), due soon (10d, 30d).
        assert card["overdue_maintenance_count"] == 2
        assert card["upcoming_maintenance_count"] == 3
        assert card["due_soon_maintenance_count"] == 2
        # The strip is the sum of the badges: due-today is Overdue once, never
        # also Upcoming; 31d and the snoozed one are in neither.
        assert fh["overdue_count"] == sum(v["overdue_maintenance_count"] for v in data["vehicles"])
        assert fh["upcoming_30d_count"] == sum(
            v["due_soon_maintenance_count"] for v in data["vehicles"]
        )
        assert fh["overdue_count"] == 2
        assert fh["upcoming_30d_count"] == 2

    async def test_due_soon_uses_the_usage_projection_for_mileage_reminders(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A mileage reminder is due soon when the odometer is projected to reach
        it within 30 days at the last 90 days' rate, the same date the reminders
        list shows; a calendar date and the projection both count, earliest wins."""
        vin, headers = await _isolated_fleet(db_session)
        today = date.today()
        db_session.add_all(
            [
                # 100 km/day over the last 60 days.
                OdometerRecord(
                    vin=vin, date=today - timedelta(days=60), odometer_km=Decimal("50000")
                ),
                OdometerRecord(vin=vin, date=today, odometer_km=Decimal("56000")),
                Reminder(
                    vin=vin,
                    title="Oil, 1,000 km out: 10 days",
                    reminder_type="mileage",
                    due_mileage_km=Decimal("57000"),
                    status="pending",
                ),  # due soon
                Reminder(
                    vin=vin,
                    title="Timing belt, 14,000 km out: 140 days",
                    reminder_type="mileage",
                    due_mileage_km=Decimal("70000"),
                    status="pending",
                ),  # pending only
                Reminder(
                    vin=vin,
                    title="Brake fluid, dated in 90 days but 2,000 km out: 20 days",
                    reminder_type="smart",
                    due_date=today + timedelta(days=90),
                    due_mileage_km=Decimal("58000"),
                    status="pending",
                ),  # due soon: the projection comes first
            ]
        )
        # A second vehicle of the same owner, with one dated reminder due soon,
        # proves the strip SUMS the cards (2 + 1) rather than reading one of them.
        import uuid

        from sqlalchemy import select

        owner_id = await db_session.scalar(select(Vehicle.user_id).where(Vehicle.vin == vin))
        vin2 = f"FLEET{uuid.uuid4().hex[:12].upper()}"
        db_session.add_all(
            [
                Vehicle(vin=vin2, user_id=owner_id, nickname="Fleet second", vehicle_type="Car"),
                Reminder(
                    vin=vin2,
                    title="Dated in 10 days",
                    reminder_type="date",
                    due_date=today + timedelta(days=10),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        data = response.json()
        card = next(v for v in data["vehicles"] if v["vin"] == vin)

        assert card["overdue_maintenance_count"] == 0
        assert card["upcoming_maintenance_count"] == 3
        assert card["due_soon_maintenance_count"] == 2
        assert sum(v["due_soon_maintenance_count"] for v in data["vehicles"]) == 3
        assert data["fleet_health"]["upcoming_30d_count"] == 3

    async def test_due_soon_without_a_usage_rate_needs_a_date(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """One odometer reading gives no rate, so a mileage-only reminder has no
        expected date. Created beside today's reading, it is 0% along its span, so
        the D2 fallback doesn't make it due soon either."""
        vin, headers = await _isolated_fleet(db_session)
        db_session.add_all(
            [
                OdometerRecord(vin=vin, date=date.today(), odometer_km=Decimal("56000")),
                Reminder(
                    vin=vin,
                    title="Oil, 100 km out, rate unknown",
                    reminder_type="mileage",
                    due_mileage_km=Decimal("56100"),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        data = response.json()
        card = next(v for v in data["vehicles"] if v["vin"] == vin)

        assert card["upcoming_maintenance_count"] == 1
        assert card["due_soon_maintenance_count"] == 0

    async def test_fleet_health_next_due_picks_soonest_dated(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """next_due is the pending dated reminder with the earliest due_date."""
        vin, headers = await _isolated_fleet(db_session)
        today = date.today()
        db_session.add_all(
            [
                Reminder(
                    vin=vin,
                    title="Oil change soon",
                    reminder_type="date",
                    due_date=today + timedelta(days=5),
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="Tire rotation later",
                    reminder_type="date",
                    due_date=today + timedelta(days=40),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        next_due = response.json()["fleet_health"]["next_due"]
        assert next_due is not None
        assert next_due["label"] == "Oil change soon"
        assert next_due["vin"] == vin
        assert next_due["due_date"] == (today + timedelta(days=5)).isoformat()

    async def test_fleet_health_next_due_excludes_completed_and_undated(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Completed reminders and reminders with neither date nor mileage never
        win Next-due (review finding 7)."""
        vin, headers = await _isolated_fleet(db_session)
        today = date.today()
        db_session.add_all(
            [
                # Earliest date but completed -> ignored.
                Reminder(
                    vin=vin,
                    title="Done early",
                    reminder_type="date",
                    due_date=today + timedelta(days=1),
                    # 'done', not 'completed': check_reminder_status has always
                    # been (pending, done, dismissed) in the migrated schema, and
                    # nothing in the app writes "completed". This fixture only
                    # passed because the ORM declared no CHECK, so create_all
                    # databases accepted a value production rejects.
                    status="done",
                ),
                # No due_date and no due_mileage -> not a candidate at all.
                Reminder(
                    vin=vin,
                    title="No schedule",
                    reminder_type="date",
                    due_date=None,
                    due_mileage_km=None,
                    status="pending",
                ),
                # The real soonest pending dated reminder.
                Reminder(
                    vin=vin,
                    title="Real next",
                    reminder_type="date",
                    due_date=today + timedelta(days=7),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        next_due = response.json()["fleet_health"]["next_due"]
        assert next_due is not None
        assert next_due["label"] == "Real next"

    async def test_fleet_health_next_due_mileage_only_fallback(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """With no dated pending reminder, a mileage-only reminder surfaces,
        ordered by due_mileage_km when the vehicle has no odometer (OQ1/finding 9)."""
        vin, headers = await _isolated_fleet(db_session)
        db_session.add_all(
            [
                Reminder(
                    vin=vin,
                    title="Brakes at 100k",
                    reminder_type="mileage",
                    due_date=None,
                    due_mileage_km=Decimal("100000.00"),
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="Belt at 160k",
                    reminder_type="mileage",
                    due_date=None,
                    due_mileage_km=Decimal("160000.00"),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200
        next_due = response.json()["fleet_health"]["next_due"]
        assert next_due is not None
        assert next_due["due_date"] is None
        # The isolated vehicle has no odometer record -> tier-2 ranks by
        # due_mileage_km ASC.
        assert next_due["label"] == "Brakes at 100k"
        assert next_due["due_mileage_km"] == "100000.00"

    async def test_fleet_health_excludes_out_of_scope_vehicles(
        self,
        client: AsyncClient,
        non_admin_headers,
        non_admin_user,
        test_vehicle,
        db_session: AsyncSession,
    ):
        """A non-admin's fleet_health never includes a vehicle they neither own
        nor have shared to them (review finding 7 — authorization scope)."""
        today = date.today()
        owned_vin = "5NPE24AF0FH000123"
        db_session.add(
            Vehicle(
                vin=owned_vin,
                user_id=non_admin_user["id"],
                nickname="Mine",
                vehicle_type="Car",
                year=2021,
                make="Hyundai",
                model="Sonata",
            )
        )
        db_session.add(
            Reminder(
                vin=owned_vin,
                title="Mine due later",
                reminder_type="date",
                due_date=today + timedelta(days=20),
                status="pending",
            )
        )
        # Out of scope: test_vehicle belongs to the ADMIN test_user, not shared
        # with the non-admin. Its EARLIER reminder must not leak into the fleet.
        db_session.add(
            Reminder(
                vin=test_vehicle["vin"],
                title="Not mine due sooner",
                reminder_type="date",
                due_date=today + timedelta(days=1),
                status="pending",
            )
        )
        await db_session.commit()

        response = await client.get("/api/dashboard", headers=non_admin_headers)
        assert response.status_code == 200
        data = response.json()
        vins = {v["vin"] for v in data["vehicles"]}
        assert owned_vin in vins
        assert test_vehicle["vin"] not in vins

        next_due = data["fleet_health"]["next_due"]
        assert next_due is not None
        # If scope leaked, the day+1 out-of-scope reminder (earlier) would win.
        assert next_due["vin"] == owned_vin
        assert next_due["label"] == "Mine due later"


@pytest.mark.integration
@pytest.mark.asyncio
class TestHomePageFuelEconomyAndTowing:
    """Issue #181: the home page quoted a towing-inclusive figure, unlabelled.

    `calculate_average_l_per_100km` defaults to `exclude_hauling=True` and the
    vehicle's own Fuel tab follows it, but `compute_full_tank_economy` defaults
    the other way and this route passed no argument. So a vehicle that tows read
    worse on the home page than on its own page, with nothing saying why.

    The reporter asked for the non-towing figure as the headline and a smaller
    towing one beside it, shown only when the vehicle actually tows. The second
    figure is towing ALONE (a blend of both says nothing), and every average is
    total fuel over total distance.
    """

    async def _tow_fleet(self, db_session: AsyncSession) -> tuple[str, dict[str, str]]:
        vin, headers = await _isolated_fleet(db_session)
        today = date.today()
        # Endpoints tile the odometer axis. The first yields no figure (nothing
        # before it); the second is a clean 500 km on 40 L; the third is a
        # hauling tank, 500 km on 80 L.
        #
        #   not towing -> [8.00]   -> average 8.00
        #   towing     -> [16.00]  -> average 16.00
        #
        # Two figures that cannot be confused for each other, which is the point:
        # an assertion that happens to hold under both settings proves nothing.
        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=today - timedelta(days=20),
                    odometer_km=Decimal("1000"),
                    liters=Decimal("40"),
                    is_full_tank=True,
                    is_hauling=False,
                ),
                FuelRecord(
                    vin=vin,
                    date=today - timedelta(days=10),
                    odometer_km=Decimal("1500"),
                    liters=Decimal("40"),
                    is_full_tank=True,
                    is_hauling=False,
                ),
                FuelRecord(
                    vin=vin,
                    date=today,
                    odometer_km=Decimal("2000"),
                    liters=Decimal("80"),
                    is_full_tank=True,
                    is_hauling=True,
                ),
            ]
        )
        await db_session.commit()
        return vin, headers

    async def _stats(self, client: AsyncClient, headers: dict[str, str], vin: str) -> dict:
        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200, response.text
        vehicles = [v for v in response.json()["vehicles"] if v["vin"] == vin]
        assert len(vehicles) == 1, "the isolated fleet should hold exactly this vehicle"
        return vehicles[0]

    async def test_the_headline_figure_excludes_towing(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        vin, headers = await self._tow_fleet(db_session)
        stats = await self._stats(client, headers, vin)
        assert Decimal(str(stats["average_l_per_100km"])) == Decimal("8.00")

    async def test_the_towing_figure_is_towing_alone(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        vin, headers = await self._tow_fleet(db_session)
        stats = await self._stats(client, headers, vin)
        assert Decimal(str(stats["towing_l_per_100km"])) == Decimal("16.00")
        assert "average_l_per_100km_with_towing" not in stats

    async def test_a_towing_tank_between_two_ordinary_ones_stays_out_of_the_headline(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The towing tank used to merge into the tank after it: 88 L over
        800 km = 11.0 joined the 8.0 in the "excluding towing" figure (9.50)."""
        vin, headers = await _isolated_fleet(db_session)
        today = date.today()
        for days, odo, litres, towing in [
            (30, "1000", "40", False),
            (20, "1500", "40", False),  # 8.0
            (10, "1800", "48", True),  # 16.0, towing
            (0, "2300", "40", False),  # 8.0
        ]:
            db_session.add(
                FuelRecord(
                    vin=vin,
                    date=today - timedelta(days=days),
                    odometer_km=Decimal(odo),
                    liters=Decimal(litres),
                    is_full_tank=True,
                    is_hauling=towing,
                )
            )
        await db_session.commit()

        stats = await self._stats(client, headers, vin)
        assert Decimal(str(stats["average_l_per_100km"])) == Decimal("8.00")
        assert Decimal(str(stats["towing_l_per_100km"])) == Decimal("16.00")

    async def test_averages_are_total_fuel_over_total_distance(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Tanks of 100 km at 10.0 and 400 km at 5.0, twice over. All four:
        60 L / 1000 km = 6.00 (a mean of figures says 7.50). The last three:
        50 L / 900 km = 5.56 (a mean says 6.67)."""
        vin, headers = await _isolated_fleet(db_session)
        today = date.today()
        for days, odo, litres in [
            (40, "1000", "40"),
            (30, "1100", "10"),
            (20, "1500", "20"),
            (10, "1600", "10"),
            (0, "2000", "20"),
        ]:
            db_session.add(
                FuelRecord(
                    vin=vin,
                    date=today - timedelta(days=days),
                    odometer_km=Decimal(odo),
                    liters=Decimal(litres),
                    is_full_tank=True,
                    is_hauling=False,
                )
            )
        await db_session.commit()

        stats = await self._stats(client, headers, vin)
        assert Decimal(str(stats["average_l_per_100km"])) == Decimal("6.00")
        assert Decimal(str(stats["recent_l_per_100km"])) == Decimal("5.56")
        assert stats["towing_l_per_100km"] is None

    async def test_the_last_three_tanks_skip_an_impossible_one(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A mistyped odometer sorts last. "Last 3 tanks" is the last three
        tanks that could be real: (20 + 10 + 20) L over 900 km = 5.56."""
        vin, headers = await _isolated_fleet(db_session)
        today = date.today()
        for days, odo, litres in [
            (50, "1000", "40"),
            (40, "1100", "10"),
            (30, "1500", "20"),
            (20, "1600", "10"),
            (10, "2000", "20"),
            (0, "200000", "20"),  # meant 2,500
        ]:
            db_session.add(
                FuelRecord(
                    vin=vin,
                    date=today - timedelta(days=days),
                    odometer_km=Decimal(odo),
                    liters=Decimal(litres),
                    is_full_tank=True,
                    is_hauling=False,
                )
            )
        await db_session.commit()

        stats = await self._stats(client, headers, vin)
        assert Decimal(str(stats["average_l_per_100km"])) == Decimal("6.00")
        assert Decimal(str(stats["recent_l_per_100km"])) == Decimal("5.56")

    async def test_a_vehicle_that_never_tows_has_no_towing_figure(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """No towing tank, no towing figure, so the card shows nothing extra."""
        vin, headers = await _isolated_fleet(db_session)
        today = date.today()
        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=today - timedelta(days=10),
                    odometer_km=Decimal("1000"),
                    liters=Decimal("40"),
                    is_full_tank=True,
                    is_hauling=False,
                ),
                FuelRecord(
                    vin=vin,
                    date=today,
                    odometer_km=Decimal("1500"),
                    liters=Decimal("40"),
                    is_full_tank=True,
                    is_hauling=False,
                ),
            ]
        )
        await db_session.commit()

        stats = await self._stats(client, headers, vin)
        assert Decimal(str(stats["average_l_per_100km"])) == Decimal("8.00")
        assert stats["towing_l_per_100km"] is None

    async def test_a_vehicle_that_only_ever_tows_still_reports_a_figure(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Every fill-up hauling means there is no non-towing figure to headline.
        Reporting nothing would hide a number the vehicle genuinely has, so the
        towing figure stands alone and the frontend labels it."""
        vin, headers = await _isolated_fleet(db_session)
        today = date.today()
        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=today - timedelta(days=10),
                    odometer_km=Decimal("1000"),
                    liters=Decimal("50"),
                    is_full_tank=True,
                    is_hauling=True,
                ),
                FuelRecord(
                    vin=vin,
                    date=today,
                    odometer_km=Decimal("1500"),
                    liters=Decimal("50"),
                    is_full_tank=True,
                    is_hauling=True,
                ),
            ]
        )
        await db_session.commit()

        stats = await self._stats(client, headers, vin)
        assert stats["average_l_per_100km"] is None
        assert Decimal(str(stats["towing_l_per_100km"])) == Decimal("10.00")


@pytest.mark.integration
@pytest.mark.asyncio
class TestTowableCards:
    """A fifth wheel's card names its tow vehicle and carries a propane rate."""

    async def _stats(self, client: AsyncClient, headers: dict[str, str]) -> dict[str, dict]:
        response = await client.get("/api/dashboard", headers=headers)
        assert response.status_code == 200, response.text
        return {v["vin"]: v for v in response.json()["vehicles"]}

    async def test_a_fifth_wheel_names_its_tow_vehicle_and_its_propane_rate(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        truck_vin, headers = await _isolated_fleet(db_session)
        truck = await db_session.get(Vehicle, truck_vin)
        assert truck is not None
        truck.year, truck.make, truck.model = 2025, "RAM", "3500"
        # "TOWED" + the fleet's 12 hex chars: 17 chars, unique per run.
        rv_vin = f"TOWED{truck_vin[5:]}"
        db_session.add(
            Vehicle(
                vin=rv_vin, user_id=truck.user_id, nickname="Durango", vehicle_type="FifthWheel"
            )
        )
        await db_session.commit()

        response = await client.post(
            f"/api/vehicles/{rv_vin}/trailer",
            json={"vin": rv_vin, "tow_vehicle_vin": truck_vin},
            headers=headers,
        )
        assert response.status_code == 201, response.text

        # Bottle refills carry no odometer. The first only starts the clock:
        # all five = 105 L over 120 days; the last three refills, anchored on
        # the one before them = 75 L over 90 days.
        d0 = date(2026, 1, 1)
        for days, liters in ((0, "30"), (30, "30"), (60, "30"), (90, "30"), (120, "15")):
            response = await client.post(
                f"/api/vehicles/{rv_vin}/fuel",
                json={
                    "vin": rv_vin,
                    "date": (d0 + timedelta(days=days)).isoformat(),
                    "propane_liters": liters,
                    "cost": "30",
                },
                headers=headers,
            )
            assert response.status_code == 201, response.text

        fleet = await self._stats(client, headers)
        rv, truck_stats = fleet[rv_vin], fleet[truck_vin]
        assert rv["tow_vehicle"] == {
            "vin": truck_vin,
            "year": 2025,
            "make": "RAM",
            "model": "3500",
        }
        assert Decimal(str(rv["propane_l_per_month"])) == Decimal("26.63")
        assert Decimal(str(rv["recent_propane_l_per_month"])) == Decimal("25.36")
        assert truck_stats["tow_vehicle"] is None
        assert truck_stats["propane_l_per_month"] is None
        assert truck_stats["recent_propane_l_per_month"] is None
