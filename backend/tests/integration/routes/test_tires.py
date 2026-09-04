"""Integration tests for tire tracking routes."""

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def test_vehicle(db_session, test_user):
    """A vehicle owned by THIS test alone, shadowing the shared conftest one.

    The suite shares one database with no per-test rollback, and the shared
    `test_vehicle` fixture hands every test the same VIN. That was survivable
    while `POST /tires` upserted by position: a second test claiming FL simply
    overwrote the first one's tire.

    v3.3.0 makes a corner claimable once -- a second POST to an occupied
    position is a 409 -- so tests in this file would collide with each other
    depending on execution order. Each gets its own vehicle instead, which is
    the fix the upsert semantics were previously hiding the need for.
    """
    import uuid

    from app.models.vehicle import Vehicle

    vin = f"TIRETEST{uuid.uuid4().hex[:9].upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Tire test",
            vehicle_type="Car",
            year=2020,
            make="Honda",
            model="Accord",
        )
    )
    await db_session.commit()

    yield {"vin": vin, "user_id": test_user["id"]}

    # Clean up. The suite shares one database, and leaving a vehicle behind per
    # test is not harmless: `test_list_vehicles` asserts a specific VIN appears
    # in a PAGINATED listing, so nine extra vehicles pushed it off the page and
    # failed a test in another file entirely.
    from sqlalchemy import delete

    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestTireRoutes:
    """Tire CRUD, readings, wear projection, and low-tread reminders."""

    async def test_list_empty(self, client: AsyncClient, auth_headers, test_vehicle):
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/tires",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tires"] == []
        assert data["total"] == 0

    async def test_upsert_list_and_delete(self, client: AsyncClient, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        create = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vin,
                "position": "FL",
                "brand": "Michelin",
                "model_name": "Pilot Sport 4",
                "size": "225/45R17",
                "dot_code": "2324",
                "tread_depth_mm": "6.5",
                "pressure_kpa": "230",
                "min_tread_mm": "2.0",
            },
        )
        assert create.status_code == 201
        tire = create.json()
        assert tire["position"] == "FL"
        assert tire["brand"] == "Michelin"
        assert float(tire["tread_depth_mm"]) == pytest.approx(6.5)
        assert tire["below_threshold"] is False

        listed = await client.get(f"/api/vehicles/{vin}/tires", headers=auth_headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        deleted = await client.delete(
            f"/api/vehicles/{vin}/tires/{tire['id']}",
            headers=auth_headers,
        )
        assert deleted.status_code == 204

        listed_again = await client.get(f"/api/vehicles/{vin}/tires", headers=auth_headers)
        assert listed_again.json()["total"] == 0

    async def test_invalid_position_rejected(self, client: AsyncClient, auth_headers, test_vehicle):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/tires",
            headers=auth_headers,
            json={
                "vin": test_vehicle["vin"],
                "position": "XX",
                "tread_depth_mm": "5.0",
            },
        )
        assert response.status_code == 422

    async def test_readings_project_wear(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        """A projection needs the tire's OWN distance, which needs bounds.

        The open mount period's upper bound is the vehicle's latest
        `OdometerRecord` -- there is no odometer column on `Vehicle`, and a
        tire reading's odometer does not create one. A vehicle with no odometer
        record therefore has no bounded distance for any tire still mounted on
        it, which is its own empty state rather than a zero.
        """
        import datetime as _dt

        from app.models.odometer import OdometerRecord

        vin = test_vehicle["vin"]
        db_session.add(
            OdometerRecord(vin=vin, date=_dt.date(2026, 6, 1), odometer_km=12000, source="manual")
        )
        await db_session.commit()
        created = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vin,
                "position": "FR",
                "brand": "Continental",
                "tread_depth_mm": "6.0",
                "min_tread_mm": "2.0",
                # v3.3.0: the projection is period-aware. Without an odometer
                # on the mount there is no bounded distance for this tire, and
                # the raw odometer delta between two readings -- which is what
                # the old code used -- is exactly the figure this release
                # exists to stop publishing. The status in that case is
                # `unverified_mount_history`, asserted separately below.
                "mounted_odometer_km": "10000",
            },
        )
        assert created.status_code == 201
        tire_id = created.json()["id"]

        first = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={
                "recorded_at": "2026-01-01",
                "odometer_km": "10000",
                "tread_depth_mm": "6.0",
            },
        )
        assert first.status_code == 201

        second = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={
                "recorded_at": "2026-06-01",
                "odometer_km": "12000",
                "tread_depth_mm": "4.0",
            },
        )
        assert second.status_code == 201
        data = second.json()
        assert float(data["tread_depth_mm"]) == pytest.approx(4.0)
        assert data["projected_km_remaining"] is not None
        assert float(data["projected_km_remaining"]) == pytest.approx(2000.0)
        assert data["projected_wear_date"] is not None
        assert len(data["readings"]) >= 2

    async def test_low_tread_creates_reminder(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        vin = test_vehicle["vin"]
        created = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vin,
                "position": "RR",
                "brand": "Michelin",
                "tread_depth_mm": "1.8",
                "min_tread_mm": "2.0",
            },
        )
        assert created.status_code == 201
        tire = created.json()
        assert tire["below_threshold"] is True

        reminders = await client.get(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
        )
        assert reminders.status_code == 200
        titles = [r["title"] for r in reminders.json()]
        assert "Tire tread low (RR)" in titles

    async def test_update_tire_metadata(self, client: AsyncClient, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        created = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vin,
                "position": "RL",
                "brand": "Goodyear",
                "tread_depth_mm": "5.0",
            },
        )
        tire_id = created.json()["id"]
        updated = await client.put(
            f"/api/vehicles/{vin}/tires/{tire_id}",
            headers=auth_headers,
            json={"brand": "Pirelli", "notes": "rotated"},
        )
        assert updated.status_code == 200
        assert updated.json()["brand"] == "Pirelli"
        assert updated.json()["notes"] == "rotated"

    async def test_low_tread_reminder_cleared_with_done_status(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        """A cleared low-tread reminder must stay findable in the UI.

        'completed' is not in the app vocabulary, so a reminder set to it drops
        out of every list filter and can never be reopened or deleted.
        """
        from sqlalchemy import select

        from app.models.reminder import Reminder

        vin = test_vehicle["vin"]
        # v3.3.0: a second POST to an occupied corner is a 409, not an upsert.
        # A tire is a thing you own, so changing its tread is a PUT on that tire.
        created = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={"vin": vin, "position": "RL", "tread_depth_mm": "2.0", "min_tread_mm": "3.0"},
        )
        assert created.status_code == 201, created.text
        await client.put(
            f"/api/vehicles/{vin}/tires/{created.json()['id']}",
            headers=auth_headers,
            json={"tread_depth_mm": "8.0"},
        )
        result = await db_session.execute(
            select(Reminder).where(Reminder.vin == vin, Reminder.title == "Tire tread low (RL)")
        )
        assert result.scalar_one().status == "done"

    async def test_upsert_does_not_wipe_unspecified_fields(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Re-saving a position must not erase the tire's identity.

        The UI opened a blank form, so a follow-up save sent brand/model/size/DOT
        as null and min_tread_mm as the schema default, and the service wrote
        every one of them.
        """
        vin = test_vehicle["vin"]
        created = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vin,
                "position": "FR",
                "brand": "Michelin",
                "model_name": "Pilot Sport 4",
                "size": "225/45R17",
                "dot_code": "2324",
                "tread_depth_mm": "7.5",
                "min_tread_mm": "3.0",
            },
        )
        assert created.status_code in (200, 201)

        # A later save that only carries a new tread reading. Before v3.3.0
        # this was a second POST to the same position; it is now a partial PUT,
        # because a POST to an occupied corner is a conflict. The property being
        # protected is unchanged: a save that omits a field must not erase it.
        updated = await client.put(
            f"/api/vehicles/{vin}/tires/{created.json()['id']}",
            headers=auth_headers,
            json={"tread_depth_mm": "6.0"},
        )
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["brand"] == "Michelin"
        assert body["model_name"] == "Pilot Sport 4"
        assert body["size"] == "225/45R17"
        assert body["dot_code"] == "2324"
        # Numeric(5, 2) round-trips as "3.00": compare values, not formatting.
        assert Decimal(str(body["min_tread_mm"])) == Decimal("3.0")
        assert Decimal(str(body["tread_depth_mm"])) == Decimal("6.0")

    async def test_backdated_reading_does_not_change_current_tread(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Backfilling history must not report a worn tire as healthy."""
        vin = test_vehicle["vin"]
        created = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={"vin": vin, "position": "RR", "tread_depth_mm": "4.0", "min_tread_mm": "3.0"},
        )
        tire_id = created.json()["id"]

        await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={"recorded_at": "2027-06-01", "tread_depth_mm": "4.0", "odometer_km": "80000"},
        )
        # An older reading arriving later.
        response = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={"recorded_at": "2027-01-01", "tread_depth_mm": "6.5", "odometer_km": "60000"},
        )
        assert response.status_code in (200, 201)
        # Numeric(5, 2) round-trips as "4.00": compare values, not formatting.
        assert Decimal(str(response.json()["tread_depth_mm"])) == Decimal("4.0")


@pytest.mark.integration
@pytest.mark.asyncio
class TestPressureOnlyTireReadings:
    """Readings that carry a pressure but no tread depth (issue #152).

    Issue #152's reporter tracks a slow leak and owns no tread gauge. Tread was
    NOT NULL on ``tire_readings`` while the odometer beside it was optional, so
    there was no way to record a pressure at all.

    Every test here builds its own vehicle. The backend suite shares one
    database with no per-test rollback, and a low-tread reminder is looked up by
    ``(vin, title, status='pending')``, so reusing ``test_vehicle`` would let a
    reminder created by an unrelated tire test decide the outcome here.
    """

    async def _vehicle(self, client: AsyncClient, auth_headers, vin: str) -> str:
        """Create an isolated vehicle and assert the setup actually landed.

        :param client: The test HTTP client.
        :param auth_headers: Auth headers for the test user.
        :param vin: The VIN to create.
        :returns: The VIN, once the vehicle exists.
        """
        response = await client.post(
            "/api/vehicles",
            headers=auth_headers,
            json={
                "vin": vin,
                "nickname": "Tire Reading Rig",
                "vehicle_type": "Car",
                "year": 2020,
                "make": "Honda",
                "model": "Civic",
            },
        )
        assert response.status_code == 201, response.text
        return vin

    async def _reminder_status(self, db_session, vin: str, title: str) -> str | None:
        """Read a reminder's status straight from the database.

        ``expire_all`` first: the API and this query share one session with
        ``expire_on_commit=False``, so an already-loaded Reminder would answer
        from the identity map with whatever it held before the request.

        :param db_session: The shared test session.
        :param vin: Vehicle the reminder belongs to.
        :param title: Reminder title to look for.
        :returns: The status string, or None when no such reminder exists.
        """
        from sqlalchemy import select

        from app.models.reminder import Reminder

        db_session.expire_all()
        result = await db_session.execute(
            select(Reminder).where(Reminder.vin == vin, Reminder.title == title)
        )
        reminders = result.scalars().all()
        assert len(reminders) <= 1, (
            f"expected at most one {title!r} for {vin}, got {len(reminders)}"
        )
        return reminders[0].status if reminders else None

    async def test_pressure_only_reading_keeps_tread_and_leaves_reminder_pending(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """★ The test this change exists for.

        Logging a tyre pressure must not silently dismiss a live low-tread
        warning. Against the naive change (column nullable, service untouched)
        the pressure-only reading falls through the unconditional
        ``tire.tread_depth_mm = data.tread_depth_mm`` assignment, nulls the
        parent tire's tread, and ``_sync_low_tread_reminder`` reads the missing
        measurement as "not below" and marks the reminder done.

        Both directions are asserted: the reminder must survive an unknown
        tread, and it must still complete when a tread is actually measured
        back above the threshold. A guard that simply never completes anything
        would pass the first half and fail the second.
        """
        vin = await self._vehicle(client, auth_headers, "1HGCM82633A152001")
        title = "Tire tread low (FL)"

        created = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vin,
                "position": "FL",
                "tread_depth_mm": "1.8",
                "min_tread_mm": "2.0",
                "pressure_kpa": "230",
            },
        )
        assert created.status_code == 201, created.text
        tire_id = created.json()["id"]
        # Setup assertions, not outcome assertions: without these a broken
        # create would leave "no reminder" looking like "reminder preserved".
        assert created.json()["below_threshold"] is True
        assert await self._reminder_status(db_session, vin, title) == "pending"

        reading = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-09-01", "pressure_kpa": "205"},
        )
        assert reading.status_code == 201, reading.text
        body = reading.json()

        # 1. the parent tire keeps the tread it was measured with
        assert body["tread_depth_mm"] is not None
        assert Decimal(str(body["tread_depth_mm"])) == Decimal("1.8")
        # the pressure the reading DID carry still lands
        assert Decimal(str(body["pressure_kpa"])) == Decimal("205")
        # 2. the tire is still reported as worn out
        assert body["below_threshold"] is True
        # 3. and the safety reminder is still pending
        assert await self._reminder_status(db_session, vin, title) == "pending"

        # The reading itself stored no tread: the row is a pressure observation.
        stored = [r for r in body["readings"] if r["recorded_at"] == "2026-09-01"]
        assert len(stored) == 1
        assert stored[0]["tread_depth_mm"] is None
        assert Decimal(str(stored[0]["pressure_kpa"])) == Decimal("205")

        # Other direction: a MEASURED tread back above the threshold must still
        # complete the reminder.
        healthy = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-09-02", "tread_depth_mm": "8.0"},
        )
        assert healthy.status_code == 201, healthy.text
        assert healthy.json()["below_threshold"] is False
        assert await self._reminder_status(db_session, vin, title) == "done"

    async def test_clearing_a_tire_tread_leaves_the_reminder_pending(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """An unknown tread is a third state, not "fine".

        This reaches ``_sync_low_tread_reminder`` through the upsert path rather
        than the reading path, where ``Tire.tread_depth_mm`` has been nullable
        since 085, so the "unknown completes a live reminder" defect is
        reachable today, before any part of this change. Clearing the tread
        field in the edit drawer sends an explicit null.
        """
        vin = await self._vehicle(client, auth_headers, "1HGCM82633A152002")
        title = "Tire tread low (RR)"

        created = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={"vin": vin, "position": "RR", "tread_depth_mm": "1.5", "min_tread_mm": "3.0"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["below_threshold"] is True
        assert await self._reminder_status(db_session, vin, title) == "pending"

        # v3.3.0: clearing a tread is an update to THAT tire, not a re-POST to
        # the corner it happens to occupy. A second POST there is a 409.
        cleared = await client.put(
            f"/api/vehicles/{vin}/tires/{created.json()['id']}",
            headers=auth_headers,
            json={"tread_depth_mm": None},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["tread_depth_mm"] is None
        assert await self._reminder_status(db_session, vin, title) == "pending"

    async def test_reading_without_tread_or_pressure_is_rejected(
        self, client: AsyncClient, auth_headers
    ):
        """A reading that measures nothing is not a reading.

        An odometer alone does not qualify: it is context for the wear
        projection, not an observation of the tire.
        """
        vin = await self._vehicle(client, auth_headers, "1HGCM82633A152003")
        created = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={"vin": vin, "position": "FR", "tread_depth_mm": "6.0"},
        )
        assert created.status_code == 201, created.text
        tire_id = created.json()["id"]

        empty = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-09-01"},
        )
        assert empty.status_code == 422, empty.text

        odometer_only = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-09-01", "odometer_km": "42000"},
        )
        assert odometer_only.status_code == 422, odometer_only.text

        # The accepting direction, so the 422s above cannot come from something
        # unrelated to the at-least-one rule.
        pressure_only = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-09-01", "pressure_kpa": "210"},
        )
        assert pressure_only.status_code == 201, pressure_only.text

    async def test_pressure_only_reading_round_trips_through_the_api(
        self, client: AsyncClient, auth_headers
    ):
        """The #152 flow end to end: no tread anywhere, pressure history only."""
        vin = await self._vehicle(client, auth_headers, "1HGCM82633A152004")
        created = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={"vin": vin, "position": "RL", "pressure_kpa": "240"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["tread_depth_mm"] is None
        tire_id = created.json()["id"]

        for day, kpa in (("2026-09-01", "235"), ("2026-09-08", "228")):
            response = await client.post(
                f"/api/vehicles/{vin}/tires/{tire_id}/readings",
                headers=auth_headers,
                json={"recorded_at": day, "pressure_kpa": kpa},
            )
            assert response.status_code == 201, response.text

        listed = await client.get(f"/api/vehicles/{vin}/tires", headers=auth_headers)
        assert listed.status_code == 200
        tire = next(t for t in listed.json()["tires"] if t["id"] == tire_id)
        assert tire["tread_depth_mm"] is None
        assert Decimal(str(tire["pressure_kpa"])) == Decimal("228")
        assert tire["below_threshold"] is False
        assert len(tire["readings"]) == 2
        assert all(r["tread_depth_mm"] is None for r in tire["readings"])
        # No tread history means no wear projection, rather than a bogus one.
        assert tire["projected_km_remaining"] is None
        assert tire["projected_wear_date"] is None
