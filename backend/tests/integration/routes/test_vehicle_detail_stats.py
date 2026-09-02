from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
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
from app.models.vehicle_share import VehicleShare


async def _seed_vehicle(db_session: AsyncSession, owner_id, vin: str) -> str:
    """Create a fresh vehicle owned by `owner_id` with a unique VIN (pollution-proof counts)."""
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname="Stats Rig",
            vehicle_type="Car",
            year=2020,
            make="Test",
            model="Rig",
        )
    )
    await db_session.commit()
    return vin


@pytest.mark.asyncio
class TestVehicleDetailStats:
    # --- Positive data tests run as the NON-ADMIN OWNER (B1) — admin would bypass
    #     ownership/share checks in get_vehicle_or_403 and mask a broken scope.

    async def test_structure_and_types(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
    ):
        """detail-stats carries the full contract; year is this year; Decimals
        serialize to JSON strings; a records-free vehicle reads zeros/nulls.
        Runs as the non-admin owner, so it also proves the owner branch grants
        access (not the admin bypass)."""
        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100001")
        response = await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {
            "overdue_count",
            "upcoming_count",
            "usage_unit",
            "current_hours",
            "latest_hours",
            "average_l_per_hr",
            "average_cost_per_hr",
            "secondary_usage_enabled",
            "latest_odometer_km",
            "latest_odometer_date",
            "last_service_date",
            "last_fillup_date",
            "spent_this_year",
            "year",
        }
        assert isinstance(body["overdue_count"], int)
        assert isinstance(body["upcoming_count"], int)
        assert body["year"] == date.today().year
        # Decimal -> JSON string.
        assert isinstance(body["spent_this_year"], str)
        # Required-but-nullable (M2): the keys are PRESENT and null on an empty vehicle.
        assert body["overdue_count"] == 0
        assert body["upcoming_count"] == 0
        assert body["latest_odometer_km"] is None
        assert body["latest_odometer_date"] is None
        assert body["last_service_date"] is None
        assert body["last_fillup_date"] is None
        assert body["spent_this_year"] == "0.00"
        # Usage tracking defaults to distance; no hours reading on a fresh vehicle.
        assert body["usage_unit"] == "distance"
        assert body["current_hours"] is None
        # Part A: hours stats fields, null/false for a pure-distance vehicle
        # with no hours_records.
        assert body["latest_hours"] is None
        assert body["average_l_per_hr"] is None
        assert body["average_cost_per_hr"] is None
        assert body["secondary_usage_enabled"] is False

    async def test_read_share_grants_access(
        self,
        client: AsyncClient,
        non_admin_headers,
        non_admin_user,
        test_user,
        db_session: AsyncSession,
    ):
        """A read-share (permission='read') on the ADMIN's vehicle grants the
        non-admin 200 (auth.py:417-424). Breaks if the share branch is dropped."""
        vin = await _seed_vehicle(db_session, test_user["id"], "5NPE24AF0FH100009")
        db_session.add(
            VehicleShare(
                vehicle_vin=vin,
                user_id=non_admin_user["id"],
                permission="read",
                shared_by=test_user["id"],
            )
        )
        await db_session.commit()
        response = await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        assert response.status_code == 200
        assert set(response.json().keys()) >= {"overdue_count", "spent_this_year", "year"}

    async def test_overdue_and_upcoming_disjoint(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
    ):
        """Predicate mirrors dashboard.calculate_vehicle_stats (G8): overdue =
        due_date<=today; upcoming = ALL pending non-overdue (broad partition);
        a completed reminder counts as neither; a pending reminder with neither a
        due_date NOR a due_mileage_km is upcoming. Breaks if the <=/< boundary
        flips, the status filter is dropped, or 'upcoming' is narrowed to a
        strict future window."""
        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100002")
        today = date.today()
        db_session.add_all(
            [
                Reminder(
                    vin=vin,
                    title="Due today",
                    reminder_type="date",
                    due_date=today,
                    status="pending",
                ),  # overdue (<= today)
                Reminder(
                    vin=vin,
                    title="Overdue 3d",
                    reminder_type="date",
                    due_date=today - timedelta(days=3),
                    status="pending",
                ),  # overdue
                Reminder(
                    vin=vin,
                    title="In 10 days",
                    reminder_type="date",
                    due_date=today + timedelta(days=10),
                    status="pending",
                ),  # upcoming
                Reminder(
                    vin=vin,
                    title="No date/mileage",
                    reminder_type="date",
                    due_date=None,
                    status="pending",
                ),  # upcoming (broad partition)
                Reminder(
                    vin=vin,
                    title="Done",
                    reminder_type="date",
                    due_date=today + timedelta(days=1),
                    # 'done', not 'completed': check_reminder_status has always
                    # been (pending, done, dismissed) in the migrated schema, and
                    # nothing in the app writes "completed". This fixture only
                    # passed because the ORM declared no CHECK, so create_all
                    # databases accepted a value production rejects.
                    status="done",
                ),  # neither
            ]
        )
        await db_session.commit()
        body = (
            await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        ).json()
        assert body["overdue_count"] == 2
        assert body["upcoming_count"] == 2  # 10-days + the undated pending reminder

    async def test_overdue_by_mileage_boundaries(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
    ):
        """Mileage predicate (G8): due_mileage_km <= current odometer is overdue
        (>= boundary — exactly-at-due is overdue); a mileage-only reminder with
        NO odometer reading on the vehicle is upcoming (mileage branch cannot
        fire). Breaks if the mileage branch is dropped or the boundary flips."""
        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100003")
        db_session.add_all(
            [
                OdometerRecord(vin=vin, date=date.today(), odometer_km=Decimal("50000.00")),
                Reminder(
                    vin=vin,
                    title="Brakes at 40k",
                    reminder_type="mileage",
                    due_date=None,
                    due_mileage_km=Decimal("40000.00"),
                    status="pending",
                ),  # overdue (40k<=50k)
                Reminder(
                    vin=vin,
                    title="Exactly 50k",
                    reminder_type="mileage",
                    due_date=None,
                    due_mileage_km=Decimal("50000.00"),
                    status="pending",
                ),  # overdue (>= boundary)
                Reminder(
                    vin=vin,
                    title="Belt at 60k",
                    reminder_type="mileage",
                    due_date=None,
                    due_mileage_km=Decimal("60000.00"),
                    status="pending",
                ),  # upcoming
            ]
        )
        await db_session.commit()
        body = (
            await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        ).json()
        assert body["overdue_count"] == 2  # 40k + exactly-50k
        assert body["upcoming_count"] == 1  # 60k still upcoming

    async def test_mileage_reminder_without_odometer_is_upcoming(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
    ):
        """A mileage-only reminder on a vehicle with NO odometer reading cannot be
        overdue (current_odometer_km is None) → upcoming (G8)."""
        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100010")
        db_session.add(
            Reminder(
                vin=vin,
                title="Belt at 60k",
                reminder_type="mileage",
                due_date=None,
                due_mileage_km=Decimal("60000.00"),
                status="pending",
            )
        )
        await db_session.commit()
        body = (
            await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        ).json()
        assert body["overdue_count"] == 0
        assert body["upcoming_count"] == 1

    async def test_overdue_and_upcoming_hours_boundaries(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
    ):
        """Phase 6b parity fix: detail-stats must use the SAME hours-aware
        is_reminder_overdue predicate as the dashboard, family dashboard, and
        calendar — a pure `hours` reminder can no longer show overdue on the
        dashboard card but 'upcoming' on this SAME vehicle's detail page.
        Mirrors test_dashboard.test_dashboard_mixed_date_mileage_hours_reminders_all_evaluated:
        pre-existing date/mileage behavior stays exactly as-is (G8) while the
        new hours branch is exercised alongside them on one vehicle."""
        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100020")
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
                ),  # overdue (date/mileage behavior unchanged)
                Reminder(
                    vin=vin,
                    title="Not overdue by mileage",
                    reminder_type="mileage",
                    due_mileage_km=Decimal("100000"),
                    status="pending",
                ),  # upcoming (date/mileage behavior unchanged)
                Reminder(
                    vin=vin,
                    title="Overdue by hours",
                    reminder_type="hours",
                    due_hours=Decimal("40.0"),
                    status="pending",
                ),  # overdue: current_hours (50.0) >= due_hours (40.0)
                Reminder(
                    vin=vin,
                    title="Not overdue by hours",
                    reminder_type="hours",
                    due_hours=Decimal("500.0"),
                    status="pending",
                ),  # upcoming: current_hours (50.0) < due_hours (500.0)
            ]
        )
        await db_session.commit()

        body = (
            await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        ).json()
        # 2 overdue (date + hours), 2 upcoming (mileage + hours).
        assert body["overdue_count"] == 2
        assert body["upcoming_count"] == 2

    async def test_spent_this_year_is_ytd_scoped(
        self,
        client: AsyncClient,
        non_admin_headers,
        non_admin_user,
        db_session: AsyncSession,
        monkeypatch,
    ):
        """Spent = service + fuel + DEF dated year_start..today; prior-year AND
        later-this-year records are both excluded (true YTD, <= today upper
        bound).

        The route clock is FROZEN to a fixed mid-year date (m3) so the
        'later-this-year' record stays a strictly-in-year future date on EVERY
        calendar day. Unfrozen `today + 1 day` rolls into next year on Dec 31,
        where it no longer distinguishes the correct `<= today` bound from a
        buggy `< next_year_start` one — the test would silently stop
        discriminating. Freezing `app.routes.vehicles.date` (a date subclass
        whose today() is fixed) makes the assertion calendar-independent."""
        import app.routes.vehicles as vehicles_route

        frozen = date(2026, 6, 15)

        class _FrozenDate(date):
            @classmethod
            def today(cls) -> date:
                return frozen

        monkeypatch.setattr(vehicles_route, "date", _FrozenDate)

        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100004")
        db_session.add_all(
            [
                # In range (frozen today): service 100 + fuel 40 + DEF 20 = 160.
                ServiceVisit(
                    vin=vin,
                    date=frozen,
                    service_category="Maintenance",
                    shop_supplies=Decimal("100.00"),
                ),
                FuelRecord(vin=vin, date=frozen, cost=Decimal("40.00")),
                DEFRecord(vin=vin, date=frozen, cost=Decimal("20.00")),
                # Prior calendar year — excluded.
                FuelRecord(vin=vin, date=date(frozen.year - 1, 6, 1), cost=Decimal("999.00")),
                # Later THIS year (strictly after frozen today, still in-year) —
                # excluded by `<= today`; a buggy `< next_year_start` WOULD include it.
                ServiceVisit(
                    vin=vin,
                    date=date(frozen.year, 12, 31),
                    service_category="Maintenance",
                    shop_supplies=Decimal("777.00"),
                ),
            ]
        )
        await db_session.commit()
        body = (
            await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        ).json()
        assert body["spent_this_year"] == "160.00"
        assert body["year"] == 2026

    async def test_latest_odometer_is_canonical_km_and_most_recent(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
    ):
        """latest_odometer_km is the most-recent reading in raw canonical km
        (NOT converted to miles), and latest_odometer_date tracks it. Breaks if
        the query converts units or orders wrong."""
        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100005")
        today = date.today()
        db_session.add_all(
            [
                OdometerRecord(
                    vin=vin, date=today - timedelta(days=30), odometer_km=Decimal("100000.00")
                ),
                OdometerRecord(vin=vin, date=today, odometer_km=Decimal("160000.00")),
            ]
        )
        await db_session.commit()
        body = (
            await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        ).json()
        # Canonical km, string; if the endpoint ever returned miles this would be ~99419.
        assert body["latest_odometer_km"] == "160000.00"
        assert body["latest_odometer_date"] == today.isoformat()

    async def test_same_date_readings_use_id_tiebreak_for_display_and_mileage(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
    ):
        """Two odometer readings on the SAME date: the id-desc tie-break picks the
        later-inserted row deterministically on SQLite AND PG (B2). The SAME row
        drives both the displayed reading and the mileage-reminder evaluation —
        one fetch, reused — so they can never disagree. Seed 50000 then 50100 on
        today; the 50100 row (higher id) must win, and a reminder due at 50050
        must be OVERDUE (would be upcoming if the 50000 row leaked in)."""
        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100007")
        today = date.today()
        first = OdometerRecord(vin=vin, date=today, odometer_km=Decimal("50000.00"))
        db_session.add(first)
        await db_session.commit()  # lower id
        second = OdometerRecord(vin=vin, date=today, odometer_km=Decimal("50100.00"))
        db_session.add(second)
        db_session.add(
            Reminder(
                vin=vin,
                title="Between the two",
                reminder_type="mileage",
                due_date=None,
                due_mileage_km=Decimal("50050.00"),
                status="pending",
            )
        )
        await db_session.commit()  # higher id -> the id-desc tie-break winner
        body = (
            await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        ).json()
        assert body["latest_odometer_km"] == "50100.00"  # display picks the higher-id same-date row
        assert body["overdue_count"] == 1  # mileage-eval used the SAME 50100 row
        assert body["upcoming_count"] == 0

    async def test_dashboard_and_detail_agree_on_same_date_counts(
        self,
        client: AsyncClient,
        non_admin_headers,
        non_admin_user,
        db_session: AsyncSession,
        monkeypatch,
    ):
        """R2-B1 / R3-B1 (cross-route): the locked decision — SAME vehicle => SAME
        overdue/upcoming on the dashboard card AND the detail hero. Both routes MUST
        derive the latest odometer from the ONE shared helper
        (`odometer_service.latest_odometer_km_and_date`, date DESC, id DESC).

        R3-B1 — a data-only assertion is NOT discriminating: on the default SQLite
        test schema the `(vin, date)` index reverse-scan returns the higher-id row
        even for a bare `ORDER BY date DESC`, so reverting EITHER route to an inline
        date-only query would STILL pass the count assertions below. To prove both
        routes actually go through the shared helper we wrap it with an AsyncMock in
        BOTH route modules' namespaces (each imports it as a bare name — see Step
        3b-ii / Step 4 — so the lookup is the module attribute) and assert each was
        awaited for the target vin. Reverting either call site to an inline query
        then leaves that route's spy un-awaited and fails deterministically,
        independent of the engine's same-date row choice. The behavioural equality
        assertions are kept as the correctness check."""
        from unittest.mock import AsyncMock

        import app.routes.dashboard as dashboard_routes
        import app.routes.vehicles as vehicle_routes
        from app.services.odometer_service import (
            latest_odometer_km_and_date as real_helper,
        )

        detail_spy = AsyncMock(wraps=real_helper)
        dashboard_spy = AsyncMock(wraps=real_helper)
        monkeypatch.setattr(vehicle_routes, "latest_odometer_km_and_date", detail_spy)
        monkeypatch.setattr(dashboard_routes, "latest_odometer_km_and_date", dashboard_spy)

        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100008")
        today = date.today()
        db_session.add(OdometerRecord(vin=vin, date=today, odometer_km=Decimal("50000.00")))
        await db_session.commit()  # lower id
        db_session.add(OdometerRecord(vin=vin, date=today, odometer_km=Decimal("50100.00")))
        db_session.add(
            Reminder(
                vin=vin,
                title="Between the two",
                reminder_type="mileage",
                due_date=None,
                due_mileage_km=Decimal("50050.00"),
                status="pending",
            )
        )
        await db_session.commit()  # higher id -> the id-desc tie-break winner

        detail = (
            await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        ).json()
        dashboard = (await client.get("/api/dashboard", headers=non_admin_headers)).json()
        card = next(v for v in dashboard["vehicles"] if v["vin"] == vin)

        # (1) STRUCTURAL (R3-B1): both routes went through the shared helper for
        # this vin. Reverting EITHER call site to an inline query leaves that
        # route's spy un-awaited -> this fails deterministically, independent of the
        # engine's same-date row choice. (The dashboard iterates all of the user's
        # vehicles, so `any(... vin ...)` matches the target's call among them.)
        assert any(
            vin in call.args or vin in call.kwargs.values() for call in detail_spy.await_args_list
        )
        assert any(
            vin in call.args or vin in call.kwargs.values()
            for call in dashboard_spy.await_args_list
        )
        # (2) BEHAVIOURAL: same row on both routes -> identical, correct counts
        # (dashboard exposes overdue_maintenance_count / upcoming_maintenance_count;
        # detail-stats exposes overdue_count / upcoming_count — the same values).
        assert detail["overdue_count"] == card["overdue_maintenance_count"] == 1
        assert detail["upcoming_count"] == card["upcoming_maintenance_count"] == 0

    async def test_last_service_and_fillup_pick_latest(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
    ):
        """last_service_date / last_fillup_date are the most-recent record dates."""
        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100006")
        today = date.today()
        db_session.add_all(
            [
                ServiceVisit(
                    vin=vin, date=today - timedelta(days=60), service_category="Maintenance"
                ),
                ServiceVisit(
                    vin=vin, date=today - timedelta(days=5), service_category="Maintenance"
                ),
                FuelRecord(vin=vin, date=today - timedelta(days=40), cost=Decimal("30.00")),
                FuelRecord(vin=vin, date=today - timedelta(days=2), cost=Decimal("35.00")),
            ]
        )
        await db_session.commit()
        body = (
            await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        ).json()
        assert body["last_service_date"] == (today - timedelta(days=5)).isoformat()
        assert body["last_fillup_date"] == (today - timedelta(days=2)).isoformat()

    async def test_out_of_scope_vehicle_403(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """A non-admin requesting a vehicle they neither own nor share gets 403,
        not the stats (get_vehicle_or_403 gate). test_vehicle is the admin's and
        is NOT shared to the non-admin."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/detail-stats", headers=non_admin_headers
        )
        assert response.status_code == 403

    async def test_nonexistent_vehicle_404(self, client: AsyncClient, auth_headers):
        """A well-formed but absent VIN returns 404."""
        response = await client.get(
            "/api/vehicles/1G1YY22G965104385/detail-stats", headers=auth_headers
        )
        assert response.status_code == 404

    async def test_requires_auth(self, client: AsyncClient, test_vehicle):
        """No token -> 401 (require_auth). Never leaks stats to anonymous callers."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/detail-stats")
        assert response.status_code == 401

    async def test_hours_fields_present_and_agree_with_dashboard(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
    ):
        """Part A: latest_hours (via latest_engine_hours_and_date — the MAX
        reading, not the newest-dated one) + average_l_per_hr/average_cost_per_hr
        (via the fuel hours-economy average) + secondary_usage_enabled must be
        populated identically on BOTH the detail-stats payload AND the
        garage-list VehicleStatistics card."""
        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100013")
        vehicle = (await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))).scalar_one()
        vehicle.usage_unit = "hours"
        vehicle.secondary_usage_enabled = True
        await db_session.commit()

        today = date.today()
        db_session.add_all(
            [
                # A lower reading dated LATER must still lose to the max reading
                # (the helper's ORDER BY engine_hours DESC rule) — proves this
                # isn't just picking the newest-dated row.
                HoursRecord(vin=vin, date=today, engine_hours=Decimal("90.0"), source="manual"),
                HoursRecord(
                    vin=vin,
                    date=today - timedelta(days=10),
                    engine_hours=Decimal("150.0"),
                    source="manual",
                ),
                FuelRecord(
                    vin=vin,
                    date=today - timedelta(days=10),
                    engine_hours=Decimal("100.0"),
                    liters=Decimal("20.000"),
                    cost=Decimal("30.00"),
                    is_full_tank=True,
                ),
                FuelRecord(
                    vin=vin,
                    date=today,
                    engine_hours=Decimal("150.0"),
                    liters=Decimal("25.000"),
                    cost=Decimal("40.00"),
                    is_full_tank=True,
                ),
            ]
        )
        await db_session.commit()

        detail = (
            await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        ).json()
        dashboard = (await client.get("/api/dashboard", headers=non_admin_headers)).json()
        card = next(v for v in dashboard["vehicles"] if v["vin"] == vin)

        # Max reading wins (150.0), not the newest date's lower reading (90.0).
        assert detail["latest_hours"] == "150.0"
        assert card["latest_hours"] == "150.0"
        # Δ=50h; l_per_hr = 25/50 = 0.50; cost_per_hr = 40/50 = 0.80.
        assert detail["average_l_per_hr"] == "0.50"
        assert card["average_l_per_hr"] == "0.50"
        assert detail["average_cost_per_hr"] == "0.80"
        assert card["average_cost_per_hr"] == "0.80"
        assert detail["secondary_usage_enabled"] is True
        assert card["secondary_usage_enabled"] is True

    async def test_latest_hours_ignores_stale_current_hours_column(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
    ):
        """R2-H1: latest_hours must be derived from hours_records via the
        canonical helper, NEVER from the retired vehicles.current_hours
        column — even when that column holds a stale legacy value with no
        matching hours_records row. current_hours is kept in the response
        for API compat only, unrelated to latest_hours."""
        vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH100014")
        vehicle = (await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))).scalar_one()
        vehicle.current_hours = Decimal("999.9")  # stale legacy value, no hours_records row
        await db_session.commit()

        body = (
            await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
        ).json()
        assert body["latest_hours"] is None
        assert body["current_hours"] == "999.9"
