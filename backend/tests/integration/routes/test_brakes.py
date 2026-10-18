"""Integration tests for brake tracking routes (#202)."""

import datetime as dt
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brake import BrakeAxle, BrakeJob, BrakeMeasurement, BrakeReminderMark
from app.models.reminder import Reminder
from app.models.vehicle import Vehicle
from app.services import brake_service
from app.services.brake_service import BrakeService
from app.utils.datetime_utils import utc_now
from app.utils.household_time import household_today
from tests.integration.routes.conftest import AUTHZ_VIN


async def _vehicle(db_session: AsyncSession, user_id: object, **fields: object) -> str:
    vin = f"BRAKE{uuid.uuid4().hex[:12].upper()}"
    values: dict[str, object] = {
        "nickname": "Brake test",
        "vehicle_type": "Car",
        "year": 2020,
        "make": "Honda",
        "model": "Fit",
        **fields,
    }
    db_session.add(Vehicle(vin=vin, user_id=user_id, **values))
    await db_session.commit()
    return vin


@pytest_asyncio.fixture
async def vin(db_session: AsyncSession, test_user) -> AsyncGenerator[str]:
    """A vehicle owned by THIS test alone. The suite shares one database with no rollback."""
    made = await _vehicle(db_session, test_user["id"])
    yield made
    await db_session.rollback()
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == made))
    await db_session.commit()


@pytest_asyncio.fixture
async def hours_vin(db_session: AsyncSession, test_user) -> AsyncGenerator[str]:
    """A vehicle that runs on the hour meter only."""
    made = await _vehicle(db_session, test_user["id"], vehicle_type="ATV", usage_unit="hours")
    yield made
    await db_session.rollback()
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == made))
    await db_session.commit()


@pytest_asyncio.fixture
async def other_vin(db_session: AsyncSession, test_user) -> AsyncGenerator[str]:
    """A second vehicle of this test's own."""
    made = await _vehicle(db_session, test_user["id"])
    yield made
    await db_session.rollback()
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == made))
    await db_session.commit()


def _corner(body: dict, position: str) -> dict:
    return next(c for c in body["corners"] if c["position"] == position)


async def _log(client: AsyncClient, headers, vin: str, day: str, km: str | None, **corners):
    payload: dict = {
        "recorded_at": day,
        "corners": [{"position": pos, **figures} for pos, figures in corners.items()],
    }
    if km is not None:
        payload["odometer_km"] = km
    return await client.post(
        f"/api/vehicles/{vin}/brakes/measurements", headers=headers, json=payload
    )


async def _pending(db_session: AsyncSession, vin: str, source: str) -> list[Reminder]:
    db_session.expire_all()
    result = await db_session.execute(
        select(Reminder).where(
            Reminder.vin == vin, Reminder.source == source, Reminder.status == "pending"
        )
    )
    return list(result.scalars().all())


@pytest.mark.integration
@pytest.mark.asyncio
class TestOverview:
    async def test_a_new_vehicle_has_default_axles_and_four_unknown_corners(
        self, client: AsyncClient, auth_headers, vin
    ):
        response = await client.get(f"/api/vehicles/{vin}/brakes", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert [a["axle"] for a in body["axles"]] == ["front", "rear"]
        assert all(a["brake_type"] == "disc" and not a["configured"] for a in body["axles"])
        assert Decimal(body["axles"][0]["min_thickness_mm"]) == Decimal("3.00")
        assert [c["position"] for c in body["corners"]] == ["FL", "FR", "RL", "RR"]
        assert {c["condition"] for c in body["corners"]} == {"unknown"}
        assert {c["wear_status"] for c in body["corners"]} == {"no_measurements"}
        assert body["usage_axis"] == "distance"

    async def test_unknown_vehicle_is_404(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/vehicles/NOPE0000000000000/brakes", headers=auth_headers)
        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
class TestAxleSetup:
    async def test_set_the_rear_axle_to_drum(self, client: AsyncClient, auth_headers, vin):
        response = await client.put(
            f"/api/vehicles/{vin}/brakes/axles/rear",
            headers=auth_headers,
            json={
                "brake_type": "drum",
                "min_thickness_mm": "1.5",
                "new_thickness_mm": "4.5",
                "drum_max_mm": "230.5",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        rear = body["axles"][1]
        assert rear["configured"] and rear["brake_type"] == "drum"
        assert Decimal(rear["drum_max_mm"]) == Decimal("230.50")
        assert _corner(body, "RL")["brake_type"] == "drum"
        assert _corner(body, "FL")["brake_type"] == "disc"

        again = await client.put(
            f"/api/vehicles/{vin}/brakes/axles/rear",
            headers=auth_headers,
            json={"brake_type": "disc", "min_thickness_mm": "2", "new_thickness_mm": "11"},
        )
        assert again.status_code == 200
        assert again.json()["axles"][1]["brake_type"] == "disc"

    @pytest.mark.parametrize(
        "payload",
        [
            {"brake_type": "disc", "min_thickness_mm": "5", "new_thickness_mm": "5"},
            {
                "brake_type": "disc",
                "min_thickness_mm": "3",
                "new_thickness_mm": "10",
                "drum_max_mm": "230",
            },
            {
                "brake_type": "drum",
                "min_thickness_mm": "1.5",
                "new_thickness_mm": "5",
                "rotor_min_mm": "20",
            },
            {"brake_type": "band", "min_thickness_mm": "1.5", "new_thickness_mm": "5"},
        ],
        ids=["new-not-above-min", "disc-with-drum-max", "drum-with-rotor-min", "unknown-type"],
    )
    async def test_refuses_a_setup_that_does_not_fit(
        self, client: AsyncClient, auth_headers, vin, payload
    ):
        response = await client.put(
            f"/api/vehicles/{vin}/brakes/axles/front", headers=auth_headers, json=payload
        )
        assert response.status_code == 422

    async def test_unknown_axle_is_422(self, client: AsyncClient, auth_headers, vin):
        response = await client.put(
            f"/api/vehicles/{vin}/brakes/axles/middle",
            headers=auth_headers,
            json={"brake_type": "disc", "min_thickness_mm": "3", "new_thickness_mm": "10"},
        )
        assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
class TestMeasurements:
    async def test_log_all_four_corners_in_one_go(self, client: AsyncClient, auth_headers, vin):
        response = await _log(
            client,
            auth_headers,
            vin,
            "2026-09-04",
            "46050",
            FL={"inner_pad_mm": "6.5", "outer_pad_mm": "7.0", "rotor_mm": "21.4"},
            FR={"inner_pad_mm": "6.0", "outer_pad_mm": "6.8"},
            RL={"inner_pad_mm": "5.5"},
            RR={"outer_pad_mm": "5.8", "notes": "squeaks"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        fl = _corner(body, "FL")
        assert Decimal(fl["thinnest_mm"]) == Decimal("6.50")
        assert Decimal(fl["surface_mm"]) == Decimal("21.40")
        assert fl["measured_on"] == "2026-09-04"
        assert Decimal(fl["measured_odometer_km"]) == Decimal("46050.00")
        assert fl["wear_status"] == "insufficient_measurements"
        assert fl["condition"] == "ok"
        assert _corner(body, "RR")["measurements"][0]["notes"] == "squeaks"

    async def test_two_measurements_project_the_wear(self, client: AsyncClient, auth_headers, vin):
        await _log(client, auth_headers, vin, "2026-01-01", "10000", FL={"inner_pad_mm": "10"})
        response = await _log(
            client, auth_headers, vin, "2026-04-11", "20000", FL={"inner_pad_mm": "9"}
        )
        fl = _corner(response.json(), "FL")
        assert fl["wear_status"] == "projected"
        assert Decimal(fl["projected_usage_remaining"]) == Decimal("60000.0")
        assert fl["projected_wear_date"] == "2027-12-02"
        assert fl["worn_by"] == "2027-12-02"
        # Newest first.
        assert [m["recorded_at"] for m in fl["measurements"]] == ["2026-04-11", "2026-01-01"]

    async def test_names_the_measurement_that_needs_an_odometer(
        self, client: AsyncClient, auth_headers, vin
    ):
        both = {"inner_pad_mm": "10", "outer_pad_mm": "10"}
        await _log(client, auth_headers, vin, "2026-01-01", "10000", FL=both)
        await _log(
            client,
            auth_headers,
            vin,
            "2026-04-01",
            None,
            FL={"inner_pad_mm": "5", "outer_pad_mm": "7"},
        )
        body = (
            await _log(client, auth_headers, vin, "2026-06-01", "30000", FL={"outer_pad_mm": "6"})
        ).json()
        fl = _corner(body, "FL")
        # The thin inner pad was last read in April, without an odometer.
        assert fl["wear_status"] == "no_usage_figures"
        assert fl["reading_needed_on"] == "2026-04-01"

    @pytest.mark.parametrize(
        "corners",
        [
            [],
            [{"position": "FL", "inner_pad_mm": "6"}, {"position": "FL", "inner_pad_mm": "7"}],
            [{"position": "FL"}],
            [{"position": "SPARE", "inner_pad_mm": "6"}],
            [{"position": "FL", "inner_pad_mm": "-1"}],
            [{"position": "FL", "inner_pad_mm": "6", "tread_depth_mm": "6"}],
        ],
        ids=["empty", "duplicate", "nothing-measured", "spare", "negative", "unknown-field"],
    )
    async def test_refuses_a_bad_batch(self, client: AsyncClient, auth_headers, vin, corners):
        response = await client.post(
            f"/api/vehicles/{vin}/brakes/measurements",
            headers=auth_headers,
            json={"recorded_at": "2026-09-04", "corners": corners},
        )
        assert response.status_code == 422

    async def test_refuses_a_shoe_on_a_disc_corner_and_writes_nothing(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        response = await _log(
            client,
            auth_headers,
            vin,
            "2026-09-04",
            None,
            FR={"inner_pad_mm": "6"},
            FL={"shoe_mm": "3"},
        )
        assert response.status_code == 422
        assert "FL" in response.json()["detail"]
        count = (
            await db_session.execute(select(BrakeMeasurement).where(BrakeMeasurement.vin == vin))
        ).all()
        assert count == []

    async def test_refuses_a_date_in_the_future(self, client: AsyncClient, auth_headers, vin):
        later = (household_today() + dt.timedelta(days=2)).isoformat()
        response = await _log(client, auth_headers, vin, later, None, FL={"inner_pad_mm": "6"})
        assert response.status_code == 422
        response = await client.post(
            f"/api/vehicles/{vin}/brakes/jobs",
            headers=auth_headers,
            json={
                "performed_on": later,
                "friction_replaced": True,
                "corners": [{"position": "FL"}],
            },
        )
        assert response.status_code == 422

    async def test_refuses_an_odometer_on_an_hours_vehicle(
        self, client: AsyncClient, auth_headers, hours_vin
    ):
        response = await _log(
            client, auth_headers, hours_vin, "2026-09-04", "1000", FL={"inner_pad_mm": "6"}
        )
        assert response.status_code == 422
        assert "brake" in response.json()["detail"]

    async def test_refuses_hours_on_a_distance_vehicle(
        self, client: AsyncClient, auth_headers, vin
    ):
        response = await client.post(
            f"/api/vehicles/{vin}/brakes/measurements",
            headers=auth_headers,
            json={
                "recorded_at": "2026-09-04",
                "engine_hours": "12.5",
                "corners": [{"position": "FL", "inner_pad_mm": "6"}],
            },
        )
        assert response.status_code == 422

    async def test_an_hours_vehicle_projects_on_the_hour_meter(
        self, client: AsyncClient, auth_headers, hours_vin
    ):
        for day, hours, pad in (("2026-01-01", "100", "10"), ("2026-03-01", "200", "9")):
            response = await client.post(
                f"/api/vehicles/{hours_vin}/brakes/measurements",
                headers=auth_headers,
                json={
                    "recorded_at": day,
                    "engine_hours": hours,
                    "corners": [{"position": "FL", "inner_pad_mm": pad}],
                },
            )
            assert response.status_code == 201
        body = response.json()
        assert body["usage_axis"] == "hours"
        assert body["tracks_distance"] is False
        assert Decimal(_corner(body, "FL")["projected_usage_remaining"]) == Decimal("600.0")

    async def test_edit_and_delete(self, client: AsyncClient, auth_headers, vin):
        body = (
            await _log(client, auth_headers, vin, "2026-09-04", "1000", FL={"inner_pad_mm": "6"})
        ).json()
        mid = _corner(body, "FL")["measurements"][0]["id"]

        fixed = await client.put(
            f"/api/vehicles/{vin}/brakes/measurements/{mid}",
            headers=auth_headers,
            json={"inner_pad_mm": "6.2", "outer_pad_mm": "6.4", "notes": "re-measured"},
        )
        assert fixed.status_code == 200, fixed.text
        assert Decimal(_corner(fixed.json(), "FL")["thinnest_mm"]) == Decimal("6.20")

        wrong_type = await client.put(
            f"/api/vehicles/{vin}/brakes/measurements/{mid}",
            headers=auth_headers,
            json={"shoe_mm": "3"},
        )
        assert wrong_type.status_code == 422

        emptied = await client.put(
            f"/api/vehicles/{vin}/brakes/measurements/{mid}",
            headers=auth_headers,
            json={"inner_pad_mm": None, "outer_pad_mm": None},
        )
        assert emptied.status_code == 422

        no_date = await client.put(
            f"/api/vehicles/{vin}/brakes/measurements/{mid}",
            headers=auth_headers,
            json={"recorded_at": None},
        )
        assert no_date.status_code == 422

        gone = await client.delete(
            f"/api/vehicles/{vin}/brakes/measurements/{mid}", headers=auth_headers
        )
        assert gone.status_code == 204
        after = (await client.get(f"/api/vehicles/{vin}/brakes", headers=auth_headers)).json()
        assert _corner(after, "FL")["measurements"] == []

    async def test_history_from_before_a_type_change_stays_editable(
        self, client: AsyncClient, auth_headers, vin
    ):
        body = (
            await _log(client, auth_headers, vin, "2026-09-04", None, RL={"inner_pad_mm": "6"})
        ).json()
        mid = _corner(body, "RL")["measurements"][0]["id"]
        await client.put(
            f"/api/vehicles/{vin}/brakes/axles/rear",
            headers=auth_headers,
            json={"brake_type": "drum", "min_thickness_mm": "1.5", "new_thickness_mm": "5"},
        )
        response = await client.put(
            f"/api/vehicles/{vin}/brakes/measurements/{mid}",
            headers=auth_headers,
            json={"notes": "from when it had discs"},
        )
        assert response.status_code == 200, response.text
        rl = _corner(response.json(), "RL")
        # Kept in history, but no use to a drum corner's figures.
        assert rl["measurements"][0]["inner_pad_mm"] is not None
        assert rl["wear_status"] == "no_measurements"

    async def test_another_vehicles_measurement_is_404(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession, test_user
    ):
        other = await _vehicle(db_session, test_user["id"])
        try:
            body = (
                await _log(
                    client, auth_headers, other, "2026-09-04", None, FL={"inner_pad_mm": "6"}
                )
            ).json()
            mid = _corner(body, "FL")["measurements"][0]["id"]
            response = await client.put(
                f"/api/vehicles/{vin}/brakes/measurements/{mid}",
                headers=auth_headers,
                json={"notes": "not mine"},
            )
            assert response.status_code == 404
            response = await client.delete(
                f"/api/vehicles/{vin}/brakes/measurements/{mid}", headers=auth_headers
            )
            assert response.status_code == 404
        finally:
            await db_session.rollback()
            await db_session.execute(delete(Vehicle).where(Vehicle.vin == other))
            await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestJobs:
    async def _job(self, client: AsyncClient, headers, vin: str, **body):
        payload = {
            "performed_on": "2026-09-10",
            "odometer_km": "47000",
            "friction_replaced": True,
            "corners": [
                {"position": "FL", "new_thickness_mm": "10"},
                {"position": "FR", "new_thickness_mm": "10"},
            ],
            **body,
        }
        return await client.post(f"/api/vehicles/{vin}/brakes/jobs", headers=headers, json=payload)

    async def test_a_pad_job_starts_the_corner_over(self, client: AsyncClient, auth_headers, vin):
        await _log(client, auth_headers, vin, "2026-01-01", "30000", FL={"inner_pad_mm": "6"})
        await _log(client, auth_headers, vin, "2026-09-10", "47000", FL={"inner_pad_mm": "2.5"})
        response = await self._job(client, auth_headers, vin)
        assert response.status_code == 201, response.text
        fl = _corner(response.json(), "FL")
        # The same-day 2.5 mm is the old pads; the job's own 10 mm is the new ones.
        assert Decimal(fl["thinnest_mm"]) == Decimal("10.00")
        assert fl["condition"] == "ok"
        assert fl["last_job"]["friction_replaced"] is True
        assert fl["last_job"]["brake_type"] == "disc"
        linked = [m for m in fl["measurements"] if m["brake_job_id"] == fl["last_job"]["id"]]
        assert len(linked) == 1
        assert (
            Decimal(linked[0]["inner_pad_mm"])
            == Decimal(linked[0]["outer_pad_mm"])
            == Decimal("10.00")
        )

    async def test_a_drum_job_writes_the_shoe(self, client: AsyncClient, auth_headers, vin):
        await client.put(
            f"/api/vehicles/{vin}/brakes/axles/rear",
            headers=auth_headers,
            json={"brake_type": "drum", "min_thickness_mm": "1.5", "new_thickness_mm": "5"},
        )
        response = await self._job(
            client,
            auth_headers,
            vin,
            surface="resurfaced",
            corners=[{"position": "RL", "new_thickness_mm": "5"}],
        )
        rl = _corner(response.json(), "RL")
        assert rl["last_job"]["brake_type"] == "drum"
        assert rl["last_job"]["surface"] == "resurfaced"
        assert Decimal(rl["shoe_mm"]) == Decimal("5.00")

    @pytest.mark.parametrize(
        "body",
        [
            {"friction_replaced": False, "corners": [{"position": "FL"}]},
            {
                "friction_replaced": False,
                "surface": "replaced",
                "corners": [{"position": "FL", "new_thickness_mm": "10"}],
            },
            {"corners": []},
            {"corners": [{"position": "FL"}, {"position": "FL"}]},
            {"surface": "polished"},
        ],
        ids=[
            "does-nothing",
            "new-thickness-without-pads",
            "no-corners",
            "duplicate",
            "bad-surface",
        ],
    )
    async def test_refuses_a_bad_job(self, client: AsyncClient, auth_headers, vin, body):
        response = await self._job(client, auth_headers, vin, **body)
        assert response.status_code == 422

    async def test_the_new_pads_figure_follows_the_job(
        self, client: AsyncClient, auth_headers, vin
    ):
        body = (await self._job(client, auth_headers, vin)).json()
        fl = _corner(body, "FL")
        job_id = fl["last_job"]["id"]
        mid = fl["measurements"][0]["id"]

        moved = await client.put(
            f"/api/vehicles/{vin}/brakes/jobs/{job_id}",
            headers=auth_headers,
            json={"performed_on": "2026-09-12", "odometer_km": "47100"},
        )
        assert moved.status_code == 200, moved.text
        linked = _corner(moved.json(), "FL")["measurements"][0]
        assert linked["recorded_at"] == "2026-09-12"
        assert Decimal(linked["odometer_km"]) == Decimal("47100.00")

        # Its date belongs to the job, not to it.
        refused = await client.put(
            f"/api/vehicles/{vin}/brakes/measurements/{mid}",
            headers=auth_headers,
            json={"recorded_at": "2026-09-01"},
        )
        assert refused.status_code == 422
        figure = await client.put(
            f"/api/vehicles/{vin}/brakes/measurements/{mid}",
            headers=auth_headers,
            json={"inner_pad_mm": "11", "outer_pad_mm": "11"},
        )
        assert figure.status_code == 200

        rotor_only = await client.put(
            f"/api/vehicles/{vin}/brakes/jobs/{job_id}",
            headers=auth_headers,
            json={"friction_replaced": False, "surface": "replaced"},
        )
        assert rotor_only.status_code == 200
        assert _corner(rotor_only.json(), "FL")["measurements"] == []

        nothing = await client.put(
            f"/api/vehicles/{vin}/brakes/jobs/{job_id}",
            headers=auth_headers,
            json={"surface": None},
        )
        assert nothing.status_code == 422

    async def test_deleting_a_job_deletes_its_new_pads_figure(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        body = (await self._job(client, auth_headers, vin)).json()
        job_id = _corner(body, "FL")["last_job"]["id"]
        response = await client.delete(
            f"/api/vehicles/{vin}/brakes/jobs/{job_id}", headers=auth_headers
        )
        assert response.status_code == 204
        db_session.expire_all()
        left = (
            await db_session.execute(
                select(BrakeMeasurement).where(BrakeMeasurement.brake_job_id == job_id)
            )
        ).all()
        assert left == []
        assert (await db_session.get(BrakeJob, job_id)) is None
        # FR's job and figure are untouched.
        after = (await client.get(f"/api/vehicles/{vin}/brakes", headers=auth_headers)).json()
        assert len(_corner(after, "FR")["measurements"]) == 1


@pytest.mark.integration
@pytest.mark.asyncio
class TestAxleReminder:
    async def test_a_low_pad_raises_the_axle_reminder_and_a_pad_job_completes_it(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        # 4.0 mm is inside the due-soon band (3.0 + 25% of 7.0 = 4.75).
        response = await _log(
            client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"}
        )
        assert _corner(response.json(), "FL")["condition"] == "due_soon"
        pending = await _pending(db_session, vin, "low_brakes_front")
        assert len(pending) == 1
        reminder = pending[0]
        assert reminder.title == "Front brake pads low"
        assert reminder.reminder_type == "date"
        # No projection yet: a pad in the band wants a look within 90 days of the check.
        assert reminder.due_date == dt.date(2026, 12, 3)
        assert await _pending(db_session, vin, "low_brakes_rear") == []

        # FR was never measured. It must not hold the reminder open after FL's job.
        await client.post(
            f"/api/vehicles/{vin}/brakes/jobs",
            headers=auth_headers,
            json={
                "performed_on": "2026-09-10",
                "friction_replaced": True,
                "corners": [{"position": "FL"}],
            },
        )
        assert await _pending(db_session, vin, "low_brakes_front") == []

    async def test_replace_now_is_due_the_day_it_was_measured(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-01-01", "1000", RR={"inner_pad_mm": "2.5"})
        pending = await _pending(db_session, vin, "low_brakes_rear")
        assert [r.due_date for r in pending] == [dt.date(2026, 1, 1)]
        assert pending[0].title == "Rear brake pads low"

    async def test_due_date_follows_the_projection(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        today = household_today()
        start = today - dt.timedelta(days=100)
        # 10 -> 6 mm over 100 days: 3 mm left lasts another 75 days.
        await _log(client, auth_headers, vin, start.isoformat(), "10000", FL={"inner_pad_mm": "10"})
        response = await _log(
            client, auth_headers, vin, today.isoformat(), "20000", FL={"inner_pad_mm": "6"}
        )
        fl = _corner(response.json(), "FL")
        assert fl["condition"] == "due_soon"
        pending = await _pending(db_session, vin, "low_brakes_front")
        assert [r.due_date for r in pending] == [today + dt.timedelta(days=75)]
        assert fl["projected_wear_date"] == (today + dt.timedelta(days=75)).isoformat()

    async def test_nothing_known_leaves_the_reminder_alone(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        body = (
            await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        ).json()
        mid = _corner(body, "FL")["measurements"][0]["id"]
        await client.delete(f"/api/vehicles/{vin}/brakes/measurements/{mid}", headers=auth_headers)
        # Not knowing is not a measurement of healthy pads.
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_deleting_the_low_figure_never_completes_it(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        # FR is measured and fine; FL's low figure goes so it can be re-entered.
        await _log(client, auth_headers, vin, "2026-03-01", None, FR={"inner_pad_mm": "8"})
        body = (
            await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "2.8"})
        ).json()
        raised = await _pending(db_session, vin, "low_brakes_front")
        mid = _corner(body, "FL")["measurements"][0]["id"]
        await client.delete(f"/api/vehicles/{vin}/brakes/measurements/{mid}", headers=auth_headers)
        await _log(client, auth_headers, vin, "2026-09-04", "1000", FL={"inner_pad_mm": "2.8"})
        # The same reminder, not a new one: its snooze and notified state stay.
        assert [r.id for r in await _pending(db_session, vin, "low_brakes_front")] == [
            r.id for r in raised
        ]

    async def test_an_axle_with_nothing_known_keeps_its_reminder(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        raised = await _pending(db_session, vin, "low_brakes_front")
        # Not a delete: the front axle becomes drum, so the disc pads no longer
        # count and every front corner is unknown. Unknown is not healthy.
        response = await client.put(
            f"/api/vehicles/{vin}/brakes/axles/front",
            headers=auth_headers,
            json={"brake_type": "drum", "min_thickness_mm": "1.5", "new_thickness_mm": "5"},
        )
        assert {c["condition"] for c in response.json()["corners"][:2]} == {"unknown"}
        pending = await _pending(db_session, vin, "low_brakes_front")
        assert [r.id for r in pending] == [r.id for r in raised]
        # It names the axle's brakes as they're set up now.
        assert pending[0].title == "Front brake shoes low"

    async def test_a_healthy_measurement_completes_it(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-09-04", None, FR={"inner_pad_mm": "4"})
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1
        body = (
            await _log(client, auth_headers, vin, "2026-09-05", None, FR={"inner_pad_mm": "4"})
        ).json()
        mid = _corner(body, "FR")["measurements"][0]["id"]
        await client.put(
            f"/api/vehicles/{vin}/brakes/measurements/{mid}",
            headers=auth_headers,
            json={"inner_pad_mm": "8"},
        )
        assert await _pending(db_session, vin, "low_brakes_front") == []

    async def test_extra_pending_rows_collapse_and_a_persons_reminder_is_left_alone(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        for _ in range(2):
            db_session.add(
                Reminder(
                    vin=vin,
                    source="low_brakes_front",
                    title="Front brake pads low",
                    reminder_type="date",
                    due_date=dt.date(2026, 1, 1),
                    status="pending",
                )
            )
        db_session.add(
            Reminder(
                vin=vin,
                title="Front brake pads low",
                reminder_type="date",
                due_date=dt.date(2026, 1, 1),
                status="pending",
            )
        )
        await db_session.commit()
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1
        mine = (
            await db_session.execute(
                select(Reminder).where(Reminder.vin == vin, Reminder.source.is_(None))
            )
        ).scalar_one()
        assert mine.status == "pending" and mine.due_date == dt.date(2026, 1, 1)

    async def test_done_stays_closed_through_a_write_with_nothing_new(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        done = await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/done", headers=auth_headers
        )
        assert done.status_code == 200
        # Saving the axle setup as it is adds nothing about the pads.
        await client.put(
            f"/api/vehicles/{vin}/brakes/axles/front",
            headers=auth_headers,
            json={"brake_type": "disc", "min_thickness_mm": "3", "new_thickness_mm": "10"},
        )
        assert await _pending(db_session, vin, "low_brakes_front") == []

    async def test_a_check_entered_after_the_close_raises_it_again(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        # Most likely the same second as the dismissal: told apart by id, not the clock.
        await _log(client, auth_headers, vin, "2026-09-20", None, FL={"inner_pad_mm": "3.9"})
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_a_check_logged_while_pending_is_not_news_after_the_close(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        # Worse while it was pending: the reminder already says so.
        await _log(client, auth_headers, vin, "2026-09-10", None, FL={"inner_pad_mm": "2.8"})
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        await client.put(
            f"/api/vehicles/{vin}/brakes/axles/front",
            headers=auth_headers,
            json={"brake_type": "disc", "min_thickness_mm": "3", "new_thickness_mm": "10"},
        )
        assert await _pending(db_session, vin, "low_brakes_front") == []

    async def test_dismissed_and_then_marked_done_stays_closed(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        reminders = f"/api/vehicles/{vin}/reminders/{raised.id}"
        await client.post(f"{reminders}/dismiss", headers=auth_headers)
        # Done on a reminder that isn't pending sets no completed_at.
        done = await client.post(f"{reminders}/done", headers=auth_headers)
        assert done.json()["status"] == "done"
        await client.put(
            f"/api/vehicles/{vin}/brakes/axles/front",
            headers=auth_headers,
            json={"brake_type": "disc", "min_thickness_mm": "3", "new_thickness_mm": "10"},
        )
        await BrakeService(db_session).refresh_reminders()
        assert await _pending(db_session, vin, "low_brakes_front") == []

    async def test_a_deleted_reminder_stays_gone_until_there_is_news(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        gone = await client.delete(
            f"/api/vehicles/{vin}/reminders/{raised.id}", headers=auth_headers
        )
        assert gone.status_code == 204
        await BrakeService(db_session).refresh_reminders()
        assert await _pending(db_session, vin, "low_brakes_front") == []
        await _log(client, auth_headers, vin, "2026-09-20", None, FL={"inner_pad_mm": "3.9"})
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_a_check_logged_again_after_deleting_the_newest_is_news(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        body = (
            await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        ).json()
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        mid = _corner(body, "FL")["measurements"][0]["id"]
        await client.delete(f"/api/vehicles/{vin}/brakes/measurements/{mid}", headers=auth_headers)
        # Re-entered: a new id, never the deleted one's.
        again = (
            await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        ).json()
        assert _corner(again, "FL")["measurements"][0]["id"] > mid
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_a_rotor_check_or_older_history_is_not_news(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await client.post(
            f"/api/vehicles/{vin}/brakes/jobs",
            headers=auth_headers,
            json={
                "performed_on": "2026-08-01",
                "friction_replaced": True,
                "corners": [{"position": "FL"}],
            },
        )
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        # A rotor-only look, and last year's pads from before the job.
        await _log(client, auth_headers, vin, "2026-09-10", None, FL={"rotor_mm": "25"})
        await _log(client, auth_headers, vin, "2025-10-01", None, FL={"inner_pad_mm": "6"})
        assert await _pending(db_session, vin, "low_brakes_front") == []

    async def test_a_setup_change_to_replace_now_raises_it_again(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        # A 4.5 mm minimum: the 4.0 mm pad is past it now, with nothing measured.
        response = await client.put(
            f"/api/vehicles/{vin}/brakes/axles/front",
            headers=auth_headers,
            json={"brake_type": "disc", "min_thickness_mm": "4.5", "new_thickness_mm": "10"},
        )
        assert _corner(response.json(), "FL")["condition"] == "replace_now"
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_undoing_a_job_made_while_pending_is_not_news(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        # FR's check gets the higher id; both are LOW, so the reminder covers both.
        await _log(
            client,
            auth_headers,
            vin,
            "2026-09-04",
            None,
            FL={"inner_pad_mm": "4"},
            FR={"inner_pad_mm": "3.9"},
        )
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        # FR's pads done with nothing measured: FR has no checks now, FL holds it open.
        job = await client.post(
            f"/api/vehicles/{vin}/brakes/jobs",
            headers=auth_headers,
            json={
                "performed_on": "2026-09-10",
                "friction_replaced": True,
                "corners": [{"position": "FR"}],
            },
        )
        job_id = _corner(job.json(), "FR")["last_job"]["id"]
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        # Entered by mistake: FR's old check is back, and the reminder told of it.
        await client.delete(f"/api/vehicles/{vin}/brakes/jobs/{job_id}", headers=auth_headers)
        await BrakeService(db_session).refresh_reminders()
        assert await _pending(db_session, vin, "low_brakes_front") == []

    async def test_deleting_the_newest_check_while_pending_does_not_lower_the_mark(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        rotor = (
            await _log(client, auth_headers, vin, "2026-09-06", None, FL={"rotor_mm": "25"})
        ).json()
        rotor_id = _corner(rotor, "FL")["measurements"][0]["id"]
        newest = (
            await _log(client, auth_headers, vin, "2026-09-08", None, FL={"inner_pad_mm": "3.9"})
        ).json()
        newest_id = _corner(newest, "FL")["measurements"][0]["id"]
        await client.delete(
            f"/api/vehicles/{vin}/brakes/measurements/{newest_id}", headers=auth_headers
        )
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        # The rotor look gets its pad figure: older than what was told, and an edit.
        await client.put(
            f"/api/vehicles/{vin}/brakes/measurements/{rotor_id}",
            headers=auth_headers,
            json={"inner_pad_mm": "3.8"},
        )
        assert await _pending(db_session, vin, "low_brakes_front") == []

    async def test_replace_now_it_already_covered_is_not_news(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        axle = f"/api/vehicles/{vin}/brakes/axles/front"
        strict = {"brake_type": "disc", "min_thickness_mm": "4.5", "new_thickness_mm": "10"}
        await client.put(axle, headers=auth_headers, json=strict)
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        # Eased to due soon while pending, then the user closes it and puts it back.
        await client.put(
            axle,
            headers=auth_headers,
            json={"brake_type": "disc", "min_thickness_mm": "3", "new_thickness_mm": "10"},
        )
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        response = await client.put(axle, headers=auth_headers, json=strict)
        assert _corner(response.json(), "FL")["condition"] == "replace_now"
        assert await _pending(db_session, vin, "low_brakes_front") == []

    async def test_replace_now_on_the_other_corner_is_news(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(
            client,
            auth_headers,
            vin,
            "2026-09-04",
            None,
            FL={"inner_pad_mm": "2.5"},
            FR={"inner_pad_mm": "4"},
        )
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        # FL's pads done; FR still due soon, which the closed reminder covered.
        await client.post(
            f"/api/vehicles/{vin}/brakes/jobs",
            headers=auth_headers,
            json={
                "performed_on": "2026-09-10",
                "friction_replaced": True,
                "corners": [{"position": "FL", "new_thickness_mm": "10"}],
            },
        )
        assert await _pending(db_session, vin, "low_brakes_front") == []
        # Only FL was ever replace now: FR getting there is news.
        response = await client.put(
            f"/api/vehicles/{vin}/brakes/axles/front",
            headers=auth_headers,
            json={"brake_type": "disc", "min_thickness_mm": "4.5", "new_thickness_mm": "10"},
        )
        assert _corner(response.json(), "FR")["condition"] == "replace_now"
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_a_corner_it_never_covered_going_low_is_news(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        # FR had nothing measured when it was told.
        await _log(client, auth_headers, vin, "2026-09-20", None, FR={"inner_pad_mm": "4.2"})
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_an_edit_that_takes_a_fine_corner_low_after_the_close_is_news(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        # FR measured fine while it was pending: it was never told FR is low.
        body = (
            await _log(client, auth_headers, vin, "2026-09-06", None, FR={"inner_pad_mm": "8.5"})
        ).json()
        assert _corner(body, "FR")["condition"] == "ok"
        fr_id = _corner(body, "FR")["measurements"][0]["id"]
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        # A typo: it read 4.
        await client.put(
            f"/api/vehicles/{vin}/brakes/measurements/{fr_id}",
            headers=auth_headers,
            json={"inner_pad_mm": "4"},
        )
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_completing_one_axle_leaves_the_other_closed(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await _log(
            client,
            auth_headers,
            vin,
            "2026-09-04",
            None,
            FL={"inner_pad_mm": "4"},
            RL={"inner_pad_mm": "4"},
        )
        [rear] = await _pending(db_session, vin, "low_brakes_rear")
        await client.post(f"/api/vehicles/{vin}/reminders/{rear.id}/dismiss", headers=auth_headers)
        # The front's pads done: its reminder completes, and the rear's marks stay.
        await client.post(
            f"/api/vehicles/{vin}/brakes/jobs",
            headers=auth_headers,
            json={
                "performed_on": "2026-09-10",
                "friction_replaced": True,
                "corners": [{"position": "FL"}],
            },
        )
        assert await _pending(db_session, vin, "low_brakes_front") == []
        await BrakeService(db_session).refresh_reminders()
        assert await _pending(db_session, vin, "low_brakes_rear") == []

    async def test_its_own_completion_does_not_hold_it_closed(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        body = (
            await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        ).json()
        mid = _corner(body, "FL")["measurements"][0]["id"]
        url = f"/api/vehicles/{vin}/brakes/measurements/{mid}"
        # A typo fixed and then put back: the sync closed it, not the user.
        await client.put(url, headers=auth_headers, json={"inner_pad_mm": "8"})
        assert await _pending(db_session, vin, "low_brakes_front") == []
        await client.put(url, headers=auth_headers, json={"inner_pad_mm": "4"})
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_going_ok_after_the_close_and_low_again_raises_it(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        body = (
            await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        ).json()
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        mid = _corner(body, "FL")["measurements"][0]["id"]
        url = f"/api/vehicles/{vin}/brakes/measurements/{mid}"
        # OK after the user closed it, then back: an axle seen OK forgets, so
        # the undo raises it again. Better twice than never.
        await client.put(url, headers=auth_headers, json={"inner_pad_mm": "8"})
        assert await _pending(db_session, vin, "low_brakes_front") == []
        await client.put(url, headers=auth_headers, json={"inner_pad_mm": "4"})
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_drum_reminder_says_shoes(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        await client.put(
            f"/api/vehicles/{vin}/brakes/axles/rear",
            headers=auth_headers,
            json={"brake_type": "drum", "min_thickness_mm": "1.5", "new_thickness_mm": "5"},
        )
        await _log(client, auth_headers, vin, "2026-09-04", None, RL={"shoe_mm": "1.8"})
        assert [r.title for r in await _pending(db_session, vin, "low_brakes_rear")] == [
            "Rear brake shoes low"
        ]


async def _wearing_well(client: AsyncClient, headers, vin: str, position: str = "FL") -> dt.date:
    """One corner at 10 then 8 mm, 100 days apart: OK today, worn out in 250 days."""
    today = household_today()
    start = today - dt.timedelta(days=100)
    await _log(
        client, headers, vin, start.isoformat(), "10000", **{position: {"inner_pad_mm": "10"}}
    )
    body = (
        await _log(
            client, headers, vin, today.isoformat(), "20000", **{position: {"inner_pad_mm": "8"}}
        )
    ).json()
    corner = _corner(body, position)
    assert corner["condition"] == "ok"
    return dt.date.fromisoformat(corner["projected_wear_date"])


def _on(monkeypatch: pytest.MonkeyPatch, day: dt.date) -> None:
    """The brake rules' today, moved without writing anything."""
    monkeypatch.setattr(brake_service, "household_today", lambda: day)


@pytest.mark.integration
@pytest.mark.asyncio
class TestDailyRefresh:
    """The 08:00 pass: a corner can turn due soon with nothing written."""

    async def test_time_alone_raises_the_reminder(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession, monkeypatch
    ):
        wear_date = await _wearing_well(client, auth_headers, vin)
        assert await _pending(db_session, vin, "low_brakes_front") == []

        _on(monkeypatch, wear_date - dt.timedelta(days=91))
        await BrakeService(db_session).refresh_reminders()
        assert await _pending(db_session, vin, "low_brakes_front") == []

        _on(monkeypatch, wear_date - dt.timedelta(days=90))
        await BrakeService(db_session).refresh_reminders()
        pending = await _pending(db_session, vin, "low_brakes_front")
        assert [r.title for r in pending] == ["Front brake pads low"]
        # Due on the wear date, 90 days out, not 90 days after the last check:
        # that was 70 days before the reminder was raised.
        assert pending[0].due_date == wear_date

    async def test_a_second_run_leaves_a_pending_reminder_as_it_is(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession, monkeypatch
    ):
        wear_date = await _wearing_well(client, auth_headers, vin)
        _on(monkeypatch, wear_date - dt.timedelta(days=30))
        await BrakeService(db_session).refresh_reminders()
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        notified = dt.datetime(2026, 9, 1, 8, 0)
        later = wear_date + dt.timedelta(days=14)
        # Snoozed, notified, and edited by the user.
        raised.snoozed_until = wear_date
        raised.last_notified_at = notified
        raised.title = "Front pads at the rotation"
        raised.due_date = later
        await db_session.commit()

        _on(monkeypatch, wear_date - dt.timedelta(days=29))
        await BrakeService(db_session).refresh_reminders()
        [kept] = await _pending(db_session, vin, "low_brakes_front")
        assert (kept.id, kept.snoozed_until, kept.last_notified_at) == (
            raised.id,
            wear_date,
            notified,
        )
        assert (kept.title, kept.due_date) == ("Front pads at the rotation", later)

    async def test_a_dismissed_reminder_stays_dismissed(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession, monkeypatch
    ):
        wear_date = await _wearing_well(client, auth_headers, vin)
        _on(monkeypatch, wear_date - dt.timedelta(days=30))
        await BrakeService(db_session).refresh_reminders()
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )

        # Next morning, nothing new measured: still due soon, still dismissed.
        _on(monkeypatch, wear_date - dt.timedelta(days=29))
        await BrakeService(db_session).refresh_reminders()
        assert await _pending(db_session, vin, "low_brakes_front") == []

    async def test_a_corner_that_was_fine_while_pending_going_low_is_news(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession, monkeypatch
    ):
        # FR wearing well while FL's reminder is pending: it only ever told FL.
        wear_date = await _wearing_well(client, auth_headers, vin, "FR")
        today = household_today().isoformat()
        await _log(client, auth_headers, vin, today, None, FL={"inner_pad_mm": "4"})
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        # FR's wear date comes inside the 90 days with nothing new measured.
        _on(monkeypatch, wear_date - dt.timedelta(days=90))
        await BrakeService(db_session).refresh_reminders()
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_editing_a_closed_reminder_does_not_hide_what_came_after(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession, monkeypatch
    ):
        today = household_today()
        await _log(
            client,
            auth_headers,
            vin,
            (today - dt.timedelta(days=120)).isoformat(),
            "5000",
            FL={"inner_pad_mm": "4"},
        )
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        reminder = f"/api/vehicles/{vin}/reminders/{raised.id}"
        await client.post(f"{reminder}/done", headers=auth_headers)
        # New pads, wearing well since.
        await client.post(
            f"/api/vehicles/{vin}/brakes/jobs",
            headers=auth_headers,
            json={
                "performed_on": (today - dt.timedelta(days=110)).isoformat(),
                "friction_replaced": True,
                "corners": [{"position": "FL"}],
            },
        )
        wear_date = await _wearing_well(client, auth_headers, vin)
        # A note on the old reminder, after all of that.
        edited = await client.put(reminder, headers=auth_headers, json={"notes": "pads at 4 mm"})
        assert edited.status_code == 200, edited.text

        _on(monkeypatch, wear_date - dt.timedelta(days=30))
        await BrakeService(db_session).refresh_reminders()
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 1

    async def test_a_pending_reminder_without_a_mark_gets_one(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession, monkeypatch
    ):
        wear_date = await _wearing_well(client, auth_headers, vin)
        _on(monkeypatch, wear_date - dt.timedelta(days=30))
        await BrakeService(db_session).refresh_reminders()
        [raised] = await _pending(db_session, vin, "low_brakes_front")
        # As a reminder raised before the marks existed.
        await db_session.execute(delete(BrakeReminderMark).where(BrakeReminderMark.vin == vin))
        await db_session.commit()

        _on(monkeypatch, wear_date - dt.timedelta(days=29))
        await BrakeService(db_session).refresh_reminders()
        await client.post(
            f"/api/vehicles/{vin}/reminders/{raised.id}/dismiss", headers=auth_headers
        )
        _on(monkeypatch, wear_date - dt.timedelta(days=28))
        await BrakeService(db_session).refresh_reminders()
        assert await _pending(db_session, vin, "low_brakes_front") == []

    async def test_it_never_completes_a_reminder(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession
    ):
        # FR is measured and fine. FL's low figure is deleted, which leaves the
        # reminder pending; a day passing is no news that the pads are fine.
        await _log(client, auth_headers, vin, "2026-03-01", None, FR={"inner_pad_mm": "8"})
        body = (
            await _log(client, auth_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "4"})
        ).json()
        mid = _corner(body, "FL")["measurements"][0]["id"]
        await client.delete(f"/api/vehicles/{vin}/brakes/measurements/{mid}", headers=auth_headers)
        raised = await _pending(db_session, vin, "low_brakes_front")
        assert len(raised) == 1
        # Renamed by the user, which the pass leaves as it is too.
        raised[0].title = "Front pads, ask the shop"
        await db_session.commit()

        await BrakeService(db_session).refresh_reminders()
        kept = await _pending(db_session, vin, "low_brakes_front")
        assert [(r.id, r.title) for r in kept] == [(raised[0].id, "Front pads, ask the shop")]

    async def test_it_leaves_extra_pending_rows_to_the_next_write(
        self, client: AsyncClient, auth_headers, vin, db_session: AsyncSession, monkeypatch
    ):
        wear_date = await _wearing_well(client, auth_headers, vin)
        _on(monkeypatch, wear_date - dt.timedelta(days=30))
        await BrakeService(db_session).refresh_reminders()
        db_session.add(
            Reminder(
                vin=vin,
                source="low_brakes_front",
                title="Front brake pads low",
                reminder_type="date",
                due_date=wear_date,
                status="pending",
            )
        )
        await db_session.commit()
        await BrakeService(db_session).refresh_reminders()
        assert len(await _pending(db_session, vin, "low_brakes_front")) == 2

    async def test_an_archived_vehicle_is_skipped(
        self,
        client: AsyncClient,
        auth_headers,
        vin,
        other_vin,
        db_session: AsyncSession,
        monkeypatch,
    ):
        wear_date = await _wearing_well(client, auth_headers, vin)
        await _wearing_well(client, auth_headers, other_vin)
        # The pass runs in VIN order; the first one is archived.
        archived, fine = sorted((vin, other_vin))
        vehicle = await db_session.get(Vehicle, archived)
        assert vehicle is not None
        vehicle.archived_at = utc_now()
        await db_session.commit()

        _on(monkeypatch, wear_date - dt.timedelta(days=30))
        await BrakeService(db_session).refresh_reminders()
        assert await _pending(db_session, archived, "low_brakes_front") == []
        # Its lock let go, so the next vehicle took its own.
        assert len(await _pending(db_session, fine, "low_brakes_front")) == 1

    async def test_a_vehicle_deleted_while_it_runs_is_skipped_quietly(
        self,
        client: AsyncClient,
        auth_headers,
        vin,
        other_vin,
        db_session: AsyncSession,
        monkeypatch,
        caplog,
    ):
        wear_date = await _wearing_well(client, auth_headers, vin)
        await _wearing_well(client, auth_headers, other_vin)
        gone, fine = sorted((vin, other_vin))
        lock = brake_service.lock_vehicle_for_write

        async def deleted_first(db: AsyncSession, at_vin: str) -> None:
            # Deleted by someone else after the list was read.
            if at_vin == gone:
                await db.execute(delete(Vehicle).where(Vehicle.vin == gone))
                await db.commit()
            await lock(db, at_vin)

        monkeypatch.setattr(brake_service, "lock_vehicle_for_write", deleted_first)
        _on(monkeypatch, wear_date - dt.timedelta(days=30))
        await BrakeService(db_session).refresh_reminders()
        assert len(await _pending(db_session, fine, "low_brakes_front")) == 1
        assert "Brake reminder refresh failed" not in caplog.text

    async def test_one_vehicle_failing_leaves_the_rest_to_run(
        self,
        client: AsyncClient,
        auth_headers,
        vin,
        other_vin,
        db_session: AsyncSession,
        monkeypatch,
    ):
        wear_date = await _wearing_well(client, auth_headers, vin)
        await _wearing_well(client, auth_headers, other_vin)
        # The pass runs in VIN order; the first one fails.
        broken, fine = sorted((vin, other_vin))
        corners = BrakeService._corners

        async def failing(self, at_vin, axes):
            if at_vin == broken:
                raise RuntimeError("boom")
            return await corners(self, at_vin, axes)

        monkeypatch.setattr(BrakeService, "_corners", failing)
        _on(monkeypatch, wear_date - dt.timedelta(days=30))
        await BrakeService(db_session).refresh_reminders()
        assert await _pending(db_session, broken, "low_brakes_front") == []
        assert len(await _pending(db_session, fine, "low_brakes_front")) == 1


@pytest.mark.integration
@pytest.mark.asyncio
class TestAccess:
    @pytest_asyncio.fixture(autouse=True)
    async def _clean(self, db_session: AsyncSession) -> AsyncGenerator[None]:
        yield
        await db_session.rollback()
        for model in (BrakeMeasurement, BrakeJob, BrakeAxle):
            await db_session.execute(delete(model).where(model.vin == AUTHZ_VIN))
        await db_session.execute(
            delete(Reminder).where(Reminder.vin == AUTHZ_VIN, Reminder.source.like("low_brakes_%"))
        )
        await db_session.commit()

    async def test_a_read_share_reads_and_cannot_write(
        self, client: AsyncClient, owned_vehicle, reader_headers
    ):
        vin = owned_vehicle.vin
        assert (
            await client.get(f"/api/vehicles/{vin}/brakes", headers=reader_headers)
        ).status_code == 200
        writes = [
            client.put(
                f"/api/vehicles/{vin}/brakes/axles/front",
                headers=reader_headers,
                json={"brake_type": "disc", "min_thickness_mm": "3", "new_thickness_mm": "10"},
            ),
            _log(client, reader_headers, vin, "2026-09-04", None, FL={"inner_pad_mm": "6"}),
            client.post(
                f"/api/vehicles/{vin}/brakes/jobs",
                headers=reader_headers,
                json={
                    "performed_on": "2026-09-04",
                    "friction_replaced": True,
                    "corners": [{"position": "FL"}],
                },
            ),
            client.put(
                f"/api/vehicles/{vin}/brakes/measurements/1", headers=reader_headers, json={}
            ),
            client.delete(f"/api/vehicles/{vin}/brakes/measurements/1", headers=reader_headers),
            client.put(f"/api/vehicles/{vin}/brakes/jobs/1", headers=reader_headers, json={}),
            client.delete(f"/api/vehicles/{vin}/brakes/jobs/1", headers=reader_headers),
        ]
        for write in writes:
            assert (await write).status_code == 403

    async def test_a_write_share_writes(self, client: AsyncClient, owned_vehicle, writer_headers):
        response = await _log(
            client, writer_headers, owned_vehicle.vin, "2026-09-04", None, FL={"inner_pad_mm": "6"}
        )
        assert response.status_code == 201

    async def test_an_unrelated_user_sees_nothing(
        self, client: AsyncClient, owned_vehicle, unrelated_headers
    ):
        response = await client.get(
            f"/api/vehicles/{owned_vehicle.vin}/brakes", headers=unrelated_headers
        )
        assert response.status_code == 403
