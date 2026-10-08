"""The automatic periodic inspection reminder, end to end over HTTP (#211).

A vehicle registered in a profiled country with a first registration date
gets one rule of type `state_inspection` (`source='inspection'`) and one
pending reminder, through the same hooks every other rule uses: vehicle
create and update, a service visit, the owner's preference, archiving, the
explicit reconcile.

Dates are relative to the household's today so the file does not expire:
a car registered three and a half years ago is in its first cycle in every
profiled country (first inspection at four years, three in Germany and the
Dutch diesel grid). Every test creates its own vehicle (the shared
`test_vehicle` has no country and no date, so the engine leaves it alone).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from dateutil.relativedelta import relativedelta
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder import Reminder
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import maintenance_service
from app.services.inspection_schedule_service import (
    INSPECTION_SOURCE,
    INSPECTION_TYPE,
    sync_all,
    sync_vehicle,
)
from app.utils.household_time import household_today

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture(autouse=True)
async def _drop_inspection_vehicles(db_session):
    """Delete every vehicle this file created, after each test (cascades to
    visits, reminders and rules)."""
    yield
    await db_session.rollback()
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.like("MNSP%")))
    await db_session.commit()


def _vin() -> str:
    # 'M' is a non-North-American WMI, so no check digit applies.
    return ("MNSP" + uuid.uuid4().hex.upper())[:17]


def _today() -> date:
    return household_today()


def _first_cycle_registration() -> date:
    """Three and a half years ago: first inspection still ahead everywhere."""
    return _today() - relativedelta(years=3, months=6)


async def _vehicle(
    client: AsyncClient,
    headers: dict,
    *,
    country: str | None = "FR",
    first_registration: date | None = None,
    vehicle_type: str = "Car",
    **extra,
) -> str:
    vin = _vin()
    payload: dict = {"vin": vin, "nickname": f"insp-{vin[-4:]}", "vehicle_type": vehicle_type}
    if country is not None:
        payload["registration_country"] = country
    if first_registration is not None:
        payload["first_registration_date"] = first_registration.isoformat()
    payload.update(extra)
    r = await client.post("/api/vehicles", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()["vin"]


async def _pending(client: AsyncClient, headers: dict, vin: str) -> list[dict]:
    r = await client.get(
        f"/api/vehicles/{vin}/reminders", headers=headers, params={"status": "pending"}
    )
    assert r.status_code == 200, r.text
    return [x for x in r.json() if x.get("source") == INSPECTION_SOURCE]


async def _reminders(client: AsyncClient, headers: dict, vin: str, status: str) -> list[dict]:
    r = await client.get(
        f"/api/vehicles/{vin}/reminders", headers=headers, params={"status": status}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _rules(db_session, vin: str) -> list[MaintenanceRule]:
    db_session.expire_all()
    result = await db_session.execute(
        select(MaintenanceRule).where(
            MaintenanceRule.vin == vin, MaintenanceRule.maintenance_type == INSPECTION_TYPE
        )
    )
    return list(result.scalars().all())


async def _inspection_visit(
    client: AsyncClient, headers: dict, vin: str, *, on: date, result: str = "passed"
) -> dict:
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        headers=headers,
        json={
            "date": on.isoformat(),
            "line_items": [
                {
                    "description": "Contrôle technique",
                    "category": "Inspection",
                    "maintenance_type": INSPECTION_TYPE,
                    "is_inspection": True,
                    "inspection_result": result,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestScheduling:
    async def test_a_french_car_gets_its_contrôle_technique_from_the_registration(
        self, client, auth_headers, db_session
    ):
        first = _first_cycle_registration()
        vin = await _vehicle(client, auth_headers, first_registration=first)

        mine = await _pending(client, auth_headers, vin)
        assert len(mine) == 1, mine
        reminder = mine[0]
        assert reminder["title"] == "Contrôle technique"
        assert reminder["maintenance_type"] == INSPECTION_TYPE
        assert reminder["anchor_kind"] == "baseline"
        assert reminder["anchor_date"] == first.isoformat()
        assert reminder["due_date"] == (first + relativedelta(years=4)).isoformat()
        assert reminder["reminder_type"] == "date"
        assert reminder["rule"]["source"] == INSPECTION_SOURCE
        assert reminder["rule"]["interval_months"] == 48
        assert reminder["rule"]["lead_days"] == 180
        assert reminder["rule"]["is_active"] is True
        # Six months of lead window does not make it "due soon" today.
        assert reminder["due_status"] == "on_track"

    async def test_without_a_first_registration_date_nothing_is_scheduled(
        self, client, auth_headers, db_session
    ):
        vin = await _vehicle(client, auth_headers)
        assert await _pending(client, auth_headers, vin) == []
        assert await _rules(db_session, vin) == []

        # The date arrives later: the vehicle update schedules it.
        first = _first_cycle_registration()
        r = await client.put(
            f"/api/vehicles/{vin}",
            headers=auth_headers,
            json={"first_registration_date": first.isoformat()},
        )
        assert r.status_code == 200, r.text
        mine = await _pending(client, auth_headers, vin)
        assert (
            len(mine) == 1 and mine[0]["due_date"] == (first + relativedelta(years=4)).isoformat()
        )

    async def test_a_country_without_a_profile_schedules_nothing(
        self, client, auth_headers, db_session
    ):
        vin = await _vehicle(
            client, auth_headers, country="US", first_registration=_first_cycle_registration()
        )
        assert await _pending(client, auth_headers, vin) == []
        assert await _rules(db_session, vin) == []

    async def test_a_past_theoretical_cycle_counts_from_the_last_theoretical_date(
        self, client, auth_headers
    ):
        # Eleven years and a month ago: due at 4, 6, 8, 10 (past) and 12 years.
        first = _today() - relativedelta(years=11, months=1)
        vin = await _vehicle(client, auth_headers, first_registration=first)
        mine = await _pending(client, auth_headers, vin)
        assert len(mine) == 1
        assert mine[0]["anchor_date"] == (first + relativedelta(years=10)).isoformat()
        assert mine[0]["due_date"] == (first + relativedelta(years=12)).isoformat()
        assert mine[0]["rule"]["interval_months"] == 24

    async def test_double_reconcile_changes_nothing(self, client, auth_headers, db_session):
        vin = await _vehicle(client, auth_headers, first_registration=_first_cycle_registration())
        before = await _pending(client, auth_headers, vin)
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200, r.text
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200, r.text
        after = await _pending(client, auth_headers, vin)
        assert [(x["id"], x["due_date"], x["anchor_date"]) for x in after] == [
            (x["id"], x["due_date"], x["anchor_date"]) for x in before
        ]
        assert len(await _rules(db_session, vin)) == 1


class TestRecordedInspections:
    async def test_a_passed_inspection_completes_the_reminder_and_starts_the_next_cycle(
        self, client, auth_headers
    ):
        first = _today() - relativedelta(years=11, months=1)
        vin = await _vehicle(client, auth_headers, first_registration=first)
        placeholder = (await _pending(client, auth_headers, vin))[0]

        done_on = _today() - relativedelta(days=60)
        await _inspection_visit(client, auth_headers, vin, on=done_on)

        mine = await _pending(client, auth_headers, vin)
        assert len(mine) == 1
        successor = mine[0]
        assert successor["id"] != placeholder["id"]
        assert successor["anchor_kind"] == "service"
        assert successor["anchor_date"] == done_on.isoformat()
        assert successor["due_date"] == (done_on + relativedelta(months=24)).isoformat()
        assert successor["rule"]["interval_months"] == 24
        assert successor["source"] == INSPECTION_SOURCE

        done = await _reminders(client, auth_headers, vin, "done")
        assert [x["id"] for x in done] == [placeholder["id"]]
        assert done[0]["completed_date"] == done_on.isoformat()

    async def test_an_inspection_before_the_theoretical_date_re_anchors_without_completing(
        self, client, auth_headers
    ):
        first = _today() - relativedelta(years=11, months=1)
        vin = await _vehicle(client, auth_headers, first_registration=first)
        placeholder = (await _pending(client, auth_headers, vin))[0]

        # Done two months BEFORE the theoretical date the placeholder counts from.
        done_on = first + relativedelta(years=10) - relativedelta(months=2)
        await _inspection_visit(client, auth_headers, vin, on=done_on)

        mine = await _pending(client, auth_headers, vin)
        assert len(mine) == 1 and mine[0]["id"] == placeholder["id"]
        assert mine[0]["anchor_kind"] == "service"
        assert mine[0]["due_date"] == (done_on + relativedelta(months=24)).isoformat()

    async def test_a_failed_inspection_is_due_again_within_two_months(self, client, auth_headers):
        first = _today() - relativedelta(years=11, months=1)
        vin = await _vehicle(client, auth_headers, first_registration=first)

        failed_on = _today() - relativedelta(days=10)
        await _inspection_visit(client, auth_headers, vin, on=failed_on, result="failed")
        mine = await _pending(client, auth_headers, vin)
        assert len(mine) == 1
        assert mine[0]["due_date"] == (failed_on + relativedelta(months=2)).isoformat()
        assert mine[0]["rule"]["interval_months"] == 2

        # The re-test passes: back to the ordinary two-year cycle.
        passed_on = _today() - relativedelta(days=3)
        await _inspection_visit(client, auth_headers, vin, on=passed_on)
        mine = await _pending(client, auth_headers, vin)
        assert len(mine) == 1
        assert mine[0]["due_date"] == (passed_on + relativedelta(months=24)).isoformat()
        assert mine[0]["rule"]["interval_months"] == 24


class TestPreferenceAndCountry:
    async def test_the_owner_preference_pauses_and_resumes(self, client, auth_headers, db_session):
        vin = await _vehicle(client, auth_headers, first_registration=_first_cycle_registration())
        assert len(await _pending(client, auth_headers, vin)) == 1
        try:
            r = await client.put(
                "/api/auth/me", headers=auth_headers, json={"inspection_auto_schedule": False}
            )
            assert r.status_code == 200, r.text
            assert await _pending(client, auth_headers, vin) == []
            (rule,) = await _rules(db_session, vin)
            assert rule.is_active is False
            dismissed = await _reminders(client, auth_headers, vin, "dismissed")
            assert len(dismissed) == 1 and dismissed[0]["source"] == INSPECTION_SOURCE

            r = await client.put(
                "/api/auth/me", headers=auth_headers, json={"inspection_auto_schedule": True}
            )
            assert r.status_code == 200, r.text
            mine = await _pending(client, auth_headers, vin)
            assert len(mine) == 1 and mine[0]["rule"]["is_active"] is True
            assert len(await _rules(db_session, vin)) == 1
        finally:
            await client.put(
                "/api/auth/me", headers=auth_headers, json={"inspection_auto_schedule": True}
            )

    async def test_moving_the_registration_recomputes_or_pauses(
        self, client, auth_headers, db_session
    ):
        first = _today() - relativedelta(years=6, months=6)
        vin = await _vehicle(client, auth_headers, first_registration=first)
        fr = (await _pending(client, auth_headers, vin))[0]
        assert fr["due_date"] == (first + relativedelta(years=8)).isoformat()

        # Luxembourg: yearly from age six, so the next one is at seven.
        r = await client.put(
            f"/api/vehicles/{vin}", headers=auth_headers, json={"registration_country": "LU"}
        )
        assert r.status_code == 200, r.text
        lu = (await _pending(client, auth_headers, vin))[0]
        assert lu["title"] == "Contrôle technique (SNCT)"
        assert lu["due_date"] == (first + relativedelta(years=7)).isoformat()
        assert lu["rule"]["interval_months"] == 12
        assert lu["rule"]["lead_days"] is None

        # The United States: no profile, the engine stands down.
        r = await client.put(
            f"/api/vehicles/{vin}", headers=auth_headers, json={"registration_country": "US"}
        )
        assert r.status_code == 200, r.text
        assert await _pending(client, auth_headers, vin) == []
        (rule,) = await _rules(db_session, vin)
        assert rule.is_active is False

        # And back to France: recomputed, same rule.
        r = await client.put(
            f"/api/vehicles/{vin}", headers=auth_headers, json={"registration_country": "FR"}
        )
        assert r.status_code == 200, r.text
        again = (await _pending(client, auth_headers, vin))[0]
        assert again["due_date"] == fr["due_date"]
        assert again["rule"]["id"] == rule.id

    async def test_a_dismissed_reminder_stays_dismissed_on_a_routine_sync(
        self, client, auth_headers, db_session
    ):
        vin = await _vehicle(client, auth_headers, first_registration=_first_cycle_registration())
        (reminder,) = await _pending(client, auth_headers, vin)
        r = await client.post(
            f"/api/vehicles/{vin}/reminders/{reminder['id']}/dismiss", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        # The explicit reconcile and the daily sweep respect the stop.
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert await _pending(client, auth_headers, vin) == []
        await sync_all(db_session)
        assert await _pending(client, auth_headers, vin) == []
        (rule,) = await _rules(db_session, vin)
        assert rule.is_active is False


class TestArchiveAndRules:
    async def test_archiving_pauses_and_unarchiving_resumes(self, client, auth_headers, db_session):
        vin = await _vehicle(client, auth_headers, first_registration=_first_cycle_registration())
        assert len(await _pending(client, auth_headers, vin)) == 1
        r = await client.post(
            f"/api/vehicles/{vin}/archive",
            headers=auth_headers,
            json={"reason": "Sold", "visible": True},
        )
        assert r.status_code == 200, r.text
        assert await _pending(client, auth_headers, vin) == []
        (rule,) = await _rules(db_session, vin)
        assert rule.is_active is False

        r = await client.post(f"/api/vehicles/{vin}/unarchive", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert len(await _pending(client, auth_headers, vin)) == 1

    async def test_an_existing_manual_rule_of_the_type_is_adopted(
        self, client, auth_headers, db_session
    ):
        vin = await _vehicle(client, auth_headers)  # no date yet: no engine rule
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "CT at the garage",
                "reminder_type": "date",
                "due_date": (_today() + relativedelta(months=3)).isoformat(),
                "maintenance_type": INSPECTION_TYPE,
                "recurrence": {"interval_months": 12},
            },
        )
        assert r.status_code == 201, r.text
        first = _first_cycle_registration()
        r = await client.put(
            f"/api/vehicles/{vin}",
            headers=auth_headers,
            json={"first_registration_date": first.isoformat()},
        )
        assert r.status_code == 200, r.text
        rules = await _rules(db_session, vin)
        assert len(rules) == 1
        assert rules[0].source == INSPECTION_SOURCE
        # Adopted: the engine's cadence, and the test's proper name.
        assert rules[0].title == "Contrôle technique"
        assert rules[0].interval_months == 48
        assert rules[0].lead_days == 180
        mine = await _pending(client, auth_headers, vin)
        assert (
            len(mine) == 1 and mine[0]["due_date"] == (first + relativedelta(years=4)).isoformat()
        )

    async def test_two_rules_of_the_type_are_left_alone(self, client, auth_headers, db_session):
        vin = await _vehicle(client, auth_headers, first_registration=_first_cycle_registration())
        for title in ("Second CT rule", "Third CT rule"):
            r = await client.post(
                f"/api/vehicles/{vin}/maintenance-rules",
                headers=auth_headers,
                json={"title": title, "maintenance_type": INSPECTION_TYPE, "interval_months": 6},
            )
            assert r.status_code == 201, r.text
        rules_before = {(r.id, r.interval_months) for r in await _rules(db_session, vin)}
        assert len(rules_before) == 3
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert {(r.id, r.interval_months) for r in await _rules(db_session, vin)} == rules_before


class TestDailySync:
    async def test_sync_all_schedules_what_no_hook_saw_and_is_idempotent(
        self, client, auth_headers, db_session, test_user
    ):
        # A vehicle written straight to the database, as a backup restore or
        # an older release would leave it: no hook ran.
        vin = _vin()
        first = _first_cycle_registration()
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=test_user["id"],
                nickname="daily",
                vehicle_type="Car",
                registration_country="FR",
                first_registration_date=first,
            )
        )
        await db_session.commit()
        assert await _pending(client, auth_headers, vin) == []

        counts = await sync_all(db_session)
        assert counts.get("scheduled", 0) >= 1
        mine = await _pending(client, auth_headers, vin)
        assert (
            len(mine) == 1 and mine[0]["due_date"] == (first + relativedelta(years=4)).isoformat()
        )

        again = await sync_all(db_session)
        assert again.get("failed", 0) == 0
        assert [x["id"] for x in await _pending(client, auth_headers, vin)] == [mine[0]["id"]]

    async def test_sync_vehicle_reports_why_it_stands_down(self, db_session, test_user):
        vin = _vin()
        vehicle = Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="why",
            vehicle_type="Boat",
            registration_country="FR",
            first_registration_date=_today(),
        )
        db_session.add(vehicle)
        await db_session.commit()
        outcome = await sync_vehicle(db_session, vehicle)
        assert outcome.action == "skipped" and outcome.reason == "no_schedule"


class TestWindowNotification:
    async def test_one_notification_when_the_lead_window_opens(
        self, client, auth_headers, db_session, monkeypatch
    ):
        from app.services import reminder_service

        # Registered so that the first inspection is due in 100 days: inside
        # the French six-month window, outside the 30-day due-soon horizon.
        first = _today() + relativedelta(days=100) - relativedelta(years=4)
        vin = await _vehicle(client, auth_headers, first_registration=first)
        (reminder,) = await _pending(client, auth_headers, vin)
        assert reminder["due_status"] == "on_track"

        sent: list[tuple[str, str]] = []

        class _Dispatcher:
            def __init__(self, _db):
                pass

            async def dispatch(self, *, event_type: str, title: str, message: str) -> None:
                sent.append((title, message))

        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher", _Dispatcher
        )
        await reminder_service.check_due_reminders(db_session)
        mine = [s for s in sent if s[0].endswith("Contrôle technique")]
        assert len(mine) == 1, sent
        assert mine[0][0].startswith("Inspection window open")
        assert f"Due date: {reminder['due_date']}" in mine[0][1]

        # Once only: the next sweep sends nothing for it.
        sent.clear()
        await reminder_service.check_due_reminders(db_session)
        assert not [s for s in sent if s[0].endswith("Contrôle technique")]
        db_session.expire_all()
        row = await db_session.get(Reminder, reminder["id"])
        assert row is not None and row.last_notified_at is not None

    async def test_no_window_notification_before_the_window(
        self, client, auth_headers, db_session, monkeypatch
    ):
        from app.services import reminder_service

        # The vehicle only has to exist with a pending inspection reminder.
        await _vehicle(client, auth_headers, first_registration=_first_cycle_registration())
        sent: list[str] = []

        class _Dispatcher:
            def __init__(self, _db):
                pass

            async def dispatch(self, *, event_type: str, title: str, message: str) -> None:
                sent.append(title)

        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher", _Dispatcher
        )
        await reminder_service.check_due_reminders(db_session)
        assert not [s for s in sent if s.endswith("Contrôle technique")]


async def _owner_country(db_session, user_id: int) -> str | None:
    user = await db_session.get(User, user_id)
    return user.country if user else None


class TestOwnerCountry:
    async def test_the_owner_country_applies_when_the_vehicle_has_none(
        self, client, auth_headers, db_session, test_user
    ):
        assert await _owner_country(db_session, test_user["id"]) is None
        vin = await _vehicle(
            client, auth_headers, country=None, first_registration=_first_cycle_registration()
        )
        assert await _pending(client, auth_headers, vin) == []
        try:
            r = await client.put("/api/auth/me", headers=auth_headers, json={"country": "DE"})
            assert r.status_code == 200, r.text
            mine = await _pending(client, auth_headers, vin)
            assert len(mine) == 1
            assert mine[0]["title"] == "Hauptuntersuchung (HU)"
            # Germany tests at three years, so at three and a half the first
            # one is past: the second cycle, due at five.
            first = date.fromisoformat(
                (await client.get(f"/api/vehicles/{vin}", headers=auth_headers)).json()[
                    "first_registration_date"
                ]
            )
            assert mine[0]["due_date"] == (first + relativedelta(years=5)).isoformat()
            assert mine[0]["rule"]["interval_months"] == 24
            r = await client.put("/api/auth/me", headers=auth_headers, json={"country": None})
            assert r.status_code == 200, r.text
            assert await _pending(client, auth_headers, vin) == []
        finally:
            await client.put("/api/auth/me", headers=auth_headers, json={"country": None})
            # The engine's rule on the shared user's other vehicles, if any,
            # was paused by the country reset above; nothing else to undo.
            await maintenance_service.reconcile_vehicle(db_session, vin)
