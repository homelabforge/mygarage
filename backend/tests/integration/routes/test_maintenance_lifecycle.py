"""The maintenance lifecycle end to end, over HTTP.

    pack / rule (WHEN)  ->  typed service (WHAT HAPPENED)  ->  one pending reminder (WHAT IS NEXT)

The numbers are the ones from the report that motivated v3.5.0: an oil
service on 2026-06-13 at 88,896 mi (143,064.24 km with the exact factor), a
rule of 7,500 mi (12,070.08 km) or 6 months, due at 96,396 mi or on
2026-12-13, whichever the car reaches first. The letters in the class names
are the scenarios the design lists (section 9).

Every test creates its own vehicle: the shared `test_vehicle` accumulates
visits and reminders from other files, and this lifecycle is exactly the
thing that reacts to them.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from dateutil.relativedelta import relativedelta
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.vehicle import Vehicle
from app.schemas.maintenance import ReminderCompleteRequest
from app.services import maintenance_service
from app.services.reminder_pack_service import builtin_pack

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture(autouse=True)
async def _drop_lifecycle_vehicles(db_session):
    """Delete every vehicle this file created, after each test.

    The suite shares one database and `test_list_vehicles` reads the first
    page of it; thirty extra vehicles from here pushed the shared vehicle off
    that page. The delete cascades to visits, reminders and rules
    (`PRAGMA foreign_keys=ON` on SQLite, native on PostgreSQL).
    """
    yield
    await db_session.rollback()
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.like("MLCY%")))
    await db_session.commit()


SERVICE_DATE = "2026-06-13"
SERVICE_KM = 143064.24  # 88,896 mi
OLDER_DATE = "2026-03-16"
OLDER_KM = 141263.04  # 87,776 mi
INTERVAL_KM = 12070.08  # 7,500 mi
SIX_MONTHS_LATER = "2026-12-13"
PACK_KM = 8000.0


def _vin() -> str:
    # 'M' is a non-North-American WMI, so no check digit applies; hex digits
    # never contain I, O or Q.
    return ("MLCY" + uuid.uuid4().hex.upper())[:17]


async def _vehicle(client: AsyncClient, headers: dict, *, vehicle_type: str = "Car") -> str:
    vin = _vin()
    r = await client.post(
        "/api/vehicles",
        headers=headers,
        json={"vin": vin, "nickname": f"life-{vin[-4:]}", "vehicle_type": vehicle_type},
    )
    assert r.status_code == 201, r.text
    return r.json()["vin"]


async def _visit(
    client: AsyncClient,
    headers: dict,
    vin: str,
    *,
    on: str,
    odometer_km: float | None,
    items: list[dict],
    engine_hours: float | None = None,
) -> dict:
    payload: dict = {"date": on, "line_items": items}
    if odometer_km is not None:
        payload["odometer_km"] = odometer_km
    if engine_hours is not None:
        payload["engine_hours"] = engine_hours
    r = await client.post(f"/api/vehicles/{vin}/service-visits", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def _odometer(client: AsyncClient, headers: dict, vin: str, on: str, km: float) -> None:
    r = await client.post(
        f"/api/vehicles/{vin}/odometer",
        headers=headers,
        json={"vin": vin, "date": on, "odometer_km": km},
    )
    assert r.status_code == 201, r.text


async def _apply(
    client: AsyncClient, headers: dict, vin: str, pack_id: str, anchors: dict | None = None
) -> list[dict]:
    body: dict = {"pack_id": pack_id}
    if anchors is not None:
        body["anchors"] = anchors
    r = await client.post(f"/api/vehicles/{vin}/reminders/apply-pack", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _preview(
    client: AsyncClient, headers: dict, vin: str, pack_id: str, anchors: dict | None = None
) -> dict:
    body: dict = {"pack_id": pack_id}
    if anchors is not None:
        body["anchors"] = anchors
    r = await client.post(
        f"/api/vehicles/{vin}/reminders/apply-pack/preview", headers=headers, json=body
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _pending(client: AsyncClient, headers: dict, vin: str) -> list[dict]:
    r = await client.get(f"/api/vehicles/{vin}/reminders", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _all(client: AsyncClient, headers: dict, vin: str) -> list[dict]:
    r = await client.get(
        f"/api/vehicles/{vin}/reminders", headers=headers, params={"status": "all"}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _of_type(reminders: list[dict], code: str) -> list[dict]:
    return [r for r in reminders if r["maintenance_type"] == code]


async def _oil(client: AsyncClient, headers: dict, vin: str) -> dict:
    oil = _of_type(await _pending(client, headers, vin), "engine_oil_filter")
    assert len(oil) == 1, oil
    return oil[0]


async def _complete(client: AsyncClient, headers: dict, vin: str, rid: int, body: dict):
    return await client.post(
        f"/api/vehicles/{vin}/reminders/{rid}/complete", headers=headers, json=body
    )


def _km(value) -> float:
    return round(float(value), 2)


# ============================================================================
#  A. Pack + no history
# ============================================================================


class TestAPackWithoutHistory:
    async def test_one_rule_and_one_reminder_per_item_from_a_baseline(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        created = await _apply(client, auth_headers, vin, "oil_and_filter")
        assert {r["title"] for r in created} == {"Oil & Filter Change", "Inspect Drain Plug Washer"}
        assert all(r["status"] == "pending" for r in created)
        assert all(r["rule_id"] is not None for r in created)
        assert all(r["anchor_kind"] == "baseline" for r in created)
        assert all(r["anchor_date"] == date.today().isoformat() for r in created)

        rules = (
            await client.get(f"/api/vehicles/{vin}/maintenance-rules", headers=auth_headers)
        ).json()
        assert len(rules) == 2
        assert {r["source"] for r in rules} == {"pack"}
        assert {r["source_pack_id"] for r in rules} == {"oil_and_filter"}
        oil_rule = next(r for r in rules if r["maintenance_type"] == "engine_oil_filter")
        assert float(oil_rule["interval_km"]) == PACK_KM
        assert oil_rule["interval_months"] == 6


# ============================================================================
#  B. Pack + existing service
# ============================================================================


class TestBPackWithExistingService:
    async def test_anchor_is_the_most_recent_typed_service(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        older = await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Oil Change"}],
        )
        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}, {"description": "Car Wash"}],
        )
        assert visit["line_items"][0]["maintenance_type"] == "engine_oil_filter"
        assert visit["line_items"][1]["maintenance_type"] is None
        assert older["line_items"][0]["maintenance_type"] == "engine_oil_filter"

        await _apply(client, auth_headers, vin, "oil_and_filter")
        oil = await _oil(client, auth_headers, vin)
        assert oil["anchor_kind"] == "service"
        assert oil["anchor_date"] == SERVICE_DATE
        assert oil["line_item_id"] == visit["line_items"][0]["id"]
        assert _km(oil["anchor_odometer_km"]) == SERVICE_KM
        assert oil["due_date"] == SIX_MONTHS_LATER
        assert _km(oil["due_mileage_km"]) == _km(SERVICE_KM + PACK_KM)
        assert oil["reminder_type"] == "smart"


# ============================================================================
#  C. Pack + existing active reminder
# ============================================================================


class TestCPackWithActiveReminder:
    async def test_applying_twice_creates_nothing(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        first = await _apply(client, auth_headers, vin, "oil_and_filter")
        second = await _apply(client, auth_headers, vin, "oil_and_filter")
        assert sorted(r["id"] for r in first) == sorted(r["id"] for r in second)
        assert len(await _pending(client, auth_headers, vin)) == 2

    async def test_a_loose_reminder_of_the_type_is_adopted_not_duplicated(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        loose = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={"title": "Oil Change", "reminder_type": "date", "due_date": "2027-01-01"},
        )
        assert loose.status_code == 201, loose.text
        assert loose.json()["maintenance_type"] == "engine_oil_filter"
        assert loose.json()["rule_id"] is None

        await _apply(client, auth_headers, vin, "oil_and_filter")
        oil = await _oil(client, auth_headers, vin)
        assert oil["id"] == loose.json()["id"]
        assert oil["rule_id"] is not None
        # No anchor on record: it keeps its own due date until the first service.
        assert oil["anchor_kind"] is None
        assert oil["due_date"] == "2027-01-01"


# ============================================================================
#  D. Existing service + existing service-linked reminder
# ============================================================================


class TestDServiceLinkedReminderReconciles:
    async def test_pack_recomputes_the_linked_reminder_from_its_service(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        # The legacy shape: a one-off reminder typed on the visit form with an
        # absolute date and a mileage that was NOT the visit's own.
        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[
                {
                    "description": "Oil Change",
                    "reminder": {
                        "title": "Oil Change",
                        "reminder_type": "smart",
                        "due_date": "2027-06-13",
                        "due_mileage_km": 150925.52,
                    },
                }
            ],
        )
        linked = await _oil(client, auth_headers, vin)
        assert linked["line_item_id"] == visit["line_items"][0]["id"]
        assert linked["anchor_kind"] == "service"
        assert linked["due_date"] == "2027-06-13"  # untouched until a rule owns it

        await _apply(client, auth_headers, vin, "oil_and_filter")
        oil = await _oil(client, auth_headers, vin)
        assert oil["id"] == linked["id"]
        assert oil["rule_id"] is not None
        assert oil["due_date"] == SIX_MONTHS_LATER
        assert _km(oil["due_mileage_km"]) == _km(SERVICE_KM + PACK_KM)


# ============================================================================
#  E. Completing a recurring reminder
# ============================================================================


class TestECompleteRecurringReminder:
    async def test_create_visit_closes_it_and_starts_the_next_cycle(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Oil Change"}],
        )
        await _apply(client, auth_headers, vin, "oil_and_filter")
        before = await _oil(client, auth_headers, vin)
        assert before["anchor_date"] == OLDER_DATE

        r = await _complete(
            client,
            auth_headers,
            vin,
            before["id"],
            {
                "completed_date": SERVICE_DATE,
                "odometer_km": SERVICE_KM,
                "cost": 45.5,
                "mode": "create_visit",
                "notes": "DIY",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reminder"]["id"] == before["id"]
        assert body["reminder"]["status"] == "done"
        assert body["reminder"]["completed_date"] == SERVICE_DATE
        assert _km(body["reminder"]["completed_odometer_km"]) == SERVICE_KM
        assert body["reminder"]["completed_line_item_id"] == body["line_item_id"]
        assert body["service_visit_id"] is not None

        nxt = body["next_reminder"]
        assert nxt is not None and nxt["status"] == "pending"
        assert nxt["rule_id"] == before["rule_id"]
        assert nxt["anchor_kind"] == "service"
        assert nxt["anchor_date"] == SERVICE_DATE
        assert nxt["line_item_id"] == body["line_item_id"]
        assert nxt["due_date"] == SIX_MONTHS_LATER
        assert _km(nxt["due_mileage_km"]) == _km(SERVICE_KM + PACK_KM)

        visits = (
            await client.get(f"/api/vehicles/{vin}/service-visits", headers=auth_headers)
        ).json()
        created = next(v for v in visits["visits"] if v["id"] == body["service_visit_id"])
        assert created["date"] == SERVICE_DATE
        assert _km(created["odometer_km"]) == SERVICE_KM
        assert created["line_items"][0]["maintenance_type"] == "engine_oil_filter"
        assert float(created["line_items"][0]["cost"]) == 45.5
        assert len(_of_type(await _pending(client, auth_headers, vin), "engine_oil_filter")) == 1

    async def test_link_visit_and_mark_only(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        await _apply(client, auth_headers, vin, "oil_and_filter")
        first = await _oil(client, auth_headers, vin)
        # A visit logged without the type (say, "Labor") that the owner links.
        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=date.today().isoformat(),
            odometer_km=SERVICE_KM,
            items=[{"description": "Labor"}],
        )
        r = await _complete(
            client,
            auth_headers,
            vin,
            first["id"],
            {
                "completed_date": date.today().isoformat(),
                "mode": "link_visit",
                "service_visit_id": visit["id"],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["service_visit_id"] == visit["id"]
        linked = (
            await client.get(
                f"/api/vehicles/{vin}/service-visits/{visit['id']}", headers=auth_headers
            )
        ).json()
        # A typed line item was added to the visit, and the reading came from it.
        assert any(li["maintenance_type"] == "engine_oil_filter" for li in linked["line_items"])
        assert _km(body["reminder"]["completed_odometer_km"]) == SERVICE_KM
        second = body["next_reminder"]
        assert second is not None

        r = await _complete(
            client,
            auth_headers,
            vin,
            second["id"],
            {
                "completed_date": date.today().isoformat(),
                "odometer_km": SERVICE_KM + 10,
                "mode": "mark_only",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["service_visit_id"] is None
        assert body["reminder"]["status"] == "done"
        assert body["reminder"]["completed_line_item_id"] is None
        third = body["next_reminder"]
        assert third["anchor_kind"] == "completion"
        assert _km(third["due_mileage_km"]) == _km(SERVICE_KM + 10 + PACK_KM)

    async def test_a_visit_logged_by_completion_reconciles_the_other_rule_of_its_type(
        self, client, auth_headers
    ):
        """Completing a ONE-OFF typed reminder by logging a visit is a typed
        service like any other: the rule of that type sees it in the same
        request, not only at the next visit write."""
        vin = await _vehicle(client, auth_headers)
        await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Oil Change"}],
        )
        await _apply(client, auth_headers, vin, "oil_and_filter")
        ruled = await _oil(client, auth_headers, vin)
        assert ruled["rule_id"] is not None and ruled["anchor_date"] == OLDER_DATE

        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={"title": "Oil change", "reminder_type": "date", "due_date": SERVICE_DATE},
        )
        assert r.status_code == 201, r.text
        loose = r.json()
        assert loose["rule_id"] is None and loose["maintenance_type"] == "engine_oil_filter"

        r = await _complete(
            client,
            auth_headers,
            vin,
            loose["id"],
            {"completed_date": SERVICE_DATE, "odometer_km": SERVICE_KM, "mode": "create_visit"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["next_reminder"] is None  # the one-off has no rule of its own

        everything = {x["id"]: x for x in await _all(client, auth_headers, vin)}
        assert everything[ruled["id"]]["status"] == "done"
        assert everything[ruled["id"]]["completed_line_item_id"] == body["line_item_id"]
        pending = _of_type(await _pending(client, auth_headers, vin), "engine_oil_filter")
        assert len(pending) == 1, pending
        assert pending[0]["rule_id"] == ruled["rule_id"]
        assert pending[0]["anchor_date"] == SERVICE_DATE
        assert pending[0]["line_item_id"] == body["line_item_id"]


# ============================================================================
#  F. Service logged independently
# ============================================================================


class TestFServiceLoggedIndependently:
    async def test_a_newer_typed_service_completes_and_generates_the_next(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Oil Change"}],
        )
        await _apply(client, auth_headers, vin, "oil_and_filter")
        before = await _oil(client, auth_headers, vin)

        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Engine Oil & Filter Change", "cost": 60}],
        )
        everything = await _all(client, auth_headers, vin)
        done = next(r for r in everything if r["id"] == before["id"])
        assert done["status"] == "done"
        assert done["completed_date"] == SERVICE_DATE
        assert done["completed_line_item_id"] == visit["line_items"][0]["id"]

        after = await _oil(client, auth_headers, vin)
        assert after["id"] != before["id"]
        assert after["rule_id"] == before["rule_id"]
        assert after["anchor_date"] == SERVICE_DATE
        assert after["due_date"] == SIX_MONTHS_LATER
        assert _km(after["due_mileage_km"]) == _km(SERVICE_KM + PACK_KM)


# ============================================================================
#  G. Mileage + time rule; H. slow driving; I. a later reading
# ============================================================================


async def _rule_from_report(client, headers, vin) -> dict:
    visit = await _visit(
        client,
        headers,
        vin,
        on=SERVICE_DATE,
        odometer_km=SERVICE_KM,
        items=[{"description": "Oil Change"}],
    )
    r = await client.post(
        f"/api/vehicles/{vin}/reminders",
        headers=headers,
        json={
            "title": "Oil Change",
            "recurrence": {"interval_km": INTERVAL_KM, "interval_months": 6},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    body["_line_item_id"] = visit["line_items"][0]["id"]
    return body


class TestGMileageAndTimeRule:
    async def test_thresholds_from_the_service_date_and_odometer(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        reminder = await _rule_from_report(client, auth_headers, vin)
        assert reminder["maintenance_type"] == "engine_oil_filter"
        assert reminder["anchor_kind"] == "service"
        assert reminder["line_item_id"] == reminder["_line_item_id"]
        assert reminder["due_date"] == SIX_MONTHS_LATER
        assert _km(reminder["due_mileage_km"]) == 155134.32
        # 96,396 mi to the mile.
        assert round(float(reminder["due_mileage_km"]) / 1.609344) == 96396
        assert reminder["reminder_type"] == "smart"
        assert reminder["rule"]["interval_months"] == 6
        assert _km(reminder["rule"]["interval_km"]) == INTERVAL_KM


class TestHSlowDriving:
    async def test_projection_moves_but_the_date_threshold_does_not(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        reminder = await _rule_from_report(client, auth_headers, vin)
        today = date.today()
        # 36.7 km/day: 9,434 km to the target is 257 days away, deep in 2027.
        await _odometer(client, auth_headers, vin, (today - timedelta(days=60)).isoformat(), 143500)
        await _odometer(client, auth_headers, vin, today.isoformat(), 145700)

        oil = await _oil(client, auth_headers, vin)
        assert oil["id"] == reminder["id"]
        assert oil["due_date"] == SIX_MONTHS_LATER
        assert oil["projected_usage_date"] is not None
        assert date.fromisoformat(oil["projected_usage_date"]) > date(2027, 1, 31)
        assert oil["estimated_due_date"] == SIX_MONTHS_LATER


class TestIReadingAfterTheService:
    async def test_a_later_odometer_entry_does_not_move_the_anchor(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        reminder = await _rule_from_report(client, auth_headers, vin)
        await _odometer(client, auth_headers, vin, "2026-06-20", 143231.62)  # the fuel-up home
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200, r.text
        oil = await _oil(client, auth_headers, vin)
        assert oil["id"] == reminder["id"]
        assert _km(oil["anchor_odometer_km"]) == SERVICE_KM
        assert _km(oil["due_mileage_km"]) == 155134.32


# ============================================================================
#  J. Idempotency
# ============================================================================


class TestJIdempotency:
    async def test_repeats_change_nothing(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change", "cost": 40}],
        )
        await _apply(client, auth_headers, vin, "oil_and_filter")
        snapshot = await _oil(client, auth_headers, vin)

        # Re-save the visit unchanged.
        r = await client.put(
            f"/api/vehicles/{vin}/service-visits/{visit['id']}",
            headers=auth_headers,
            json={
                "date": SERVICE_DATE,
                "odometer_km": SERVICE_KM,
                "line_items": [
                    {
                        "id": visit["line_items"][0]["id"],
                        "description": "Oil Change",
                        "cost": 40,
                        "maintenance_type": "engine_oil_filter",
                        "supplies_used": [],
                    }
                ],
            },
        )
        assert r.status_code == 200, r.text
        # Reconcile twice, apply again.
        for _ in range(2):
            r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
            assert r.status_code == 200, r.text
        await _apply(client, auth_headers, vin, "oil_and_filter")

        after = await _oil(client, auth_headers, vin)
        for key in ("id", "rule_id", "due_date", "line_item_id", "anchor_date"):
            assert after[key] == snapshot[key], key
        assert _km(after["due_mileage_km"]) == _km(snapshot["due_mileage_km"])
        assert len(await _pending(client, auth_headers, vin)) == 2

    async def test_completing_twice_is_a_conflict(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        await _apply(client, auth_headers, vin, "oil_and_filter")
        oil = await _oil(client, auth_headers, vin)
        body = {
            "completed_date": date.today().isoformat(),
            "odometer_km": 1000,
            "mode": "mark_only",
        }
        first = await _complete(client, auth_headers, vin, oil["id"], body)
        assert first.status_code == 200, first.text
        second = await _complete(client, auth_headers, vin, oil["id"], body)
        assert second.status_code == 409
        assert len(_of_type(await _pending(client, auth_headers, vin), "engine_oil_filter")) == 1


# ============================================================================
#  K. Different canonical types never collide
# ============================================================================


class TestKTypesDoNotCollide:
    async def test_tire_replacement_and_transmission_oil_leave_other_rules_alone(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Oil Change"}, {"description": "Tire Rotation"}],
        )
        await _apply(client, auth_headers, vin, "oil_and_filter")
        await _apply(client, auth_headers, vin, "tire_rotation")
        before = {r["maintenance_type"]: r for r in await _pending(client, auth_headers, vin)}

        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Tire Replacement"}, {"description": "Transmission oil change"}],
        )
        assert [li["maintenance_type"] for li in visit["line_items"]] == [
            "tire_replacement",
            "transmission_service",
        ]
        after = {r["maintenance_type"]: r for r in await _pending(client, auth_headers, vin)}
        for code in ("engine_oil_filter", "tire_rotation"):
            assert after[code]["id"] == before[code]["id"]
            assert after[code]["anchor_date"] == OLDER_DATE
            assert after[code]["status"] == "pending"


# ============================================================================
#  L. Two rules of one type
# ============================================================================


class TestLTwoRulesOfOneType:
    async def test_services_attach_only_through_the_dialog(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        # A mileage-only rule needs a reading to anchor on; without one there
        # is no threshold and no reminder (design section 5.1).
        await _odometer(client, auth_headers, vin, date.today().isoformat(), 4000)
        rules = []
        for title in ("Port engine oil", "Starboard engine oil"):
            r = await client.post(
                f"/api/vehicles/{vin}/maintenance-rules",
                headers=auth_headers,
                json={"title": title, "maintenance_type": "engine_oil_filter", "interval_km": 8000},
            )
            assert r.status_code == 201, r.text
            rules.append(r.json())
        pending = _of_type(await _pending(client, auth_headers, vin), "engine_oil_filter")
        assert len(pending) == 2
        by_rule = {r["rule_id"]: r for r in pending}

        # A typed service advances NEITHER: the type cannot say which engine.
        await _visit(
            client,
            auth_headers,
            vin,
            on=date.today().isoformat(),
            odometer_km=5000,
            items=[{"description": "Oil Change"}],
        )
        pending = _of_type(await _pending(client, auth_headers, vin), "engine_oil_filter")
        assert {r["id"] for r in pending} == set(r["id"] for r in by_rule.values())
        assert all(r["anchor_kind"] == "baseline" for r in pending)

        # Completing B through the dialog advances only B.
        b = by_rule[rules[1]["id"]]
        r = await _complete(
            client,
            auth_headers,
            vin,
            b["id"],
            {"completed_date": date.today().isoformat(), "odometer_km": 6000},
        )
        assert r.status_code == 200, r.text
        pending = {
            r["rule_id"]: r
            for r in _of_type(await _pending(client, auth_headers, vin), "engine_oil_filter")
        }
        assert pending[rules[0]["id"]]["id"] == by_rule[rules[0]["id"]]["id"]
        assert pending[rules[1]["id"]]["id"] != b["id"]
        assert _km(pending[rules[1]["id"]]["due_mileage_km"]) == 14000.0

        # Deactivating B does not hand B's history to A.
        r = await client.delete(
            f"/api/vehicles/{vin}/maintenance-rules/{rules[1]['id']}", headers=auth_headers
        )
        assert r.status_code == 204
        listed = {
            r["id"]: r
            for r in (
                await client.get(f"/api/vehicles/{vin}/maintenance-rules", headers=auth_headers)
            ).json()
        }
        assert listed[rules[1]["id"]]["is_active"] is False  # referenced, so kept
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200
        a_after = next(
            x for x in await _pending(client, auth_headers, vin) if x["rule_id"] == rules[0]["id"]
        )
        assert a_after["id"] == by_rule[rules[0]["id"]]["id"]
        assert a_after["anchor_kind"] == "baseline"

        # The pack skips a type that has two rules.
        preview = await _preview(client, auth_headers, vin, "oil_and_filter")
        oil_item = next(i for i in preview["items"] if i["maintenance_type"] == "engine_oil_filter")
        assert oil_item["rule_action"] == "skip"
        applied = await _apply(client, auth_headers, vin, "oil_and_filter")
        assert all(r["maintenance_type"] != "engine_oil_filter" for r in applied)


# ============================================================================
#  M. Concurrency
# ============================================================================


class TestMConcurrency:
    async def test_two_completions_yield_one_visit_and_one_successor(
        self, client, auth_headers, test_sessionmaker, test_user
    ):
        vin = await _vehicle(client, auth_headers)
        await _apply(client, auth_headers, vin, "oil_and_filter")
        oil = await _oil(client, auth_headers, vin)
        req = ReminderCompleteRequest(
            completed_date=date.today(), odometer_km=Decimal("2000"), mode="create_visit"
        )

        async def _race():
            async with test_sessionmaker() as db:
                return await maintenance_service.complete_reminder(db, vin, oil["id"], req)

        results = await asyncio.gather(_race(), _race(), return_exceptions=True)
        statuses = sorted(
            getattr(r, "status_code", 200) if isinstance(r, Exception) else 200 for r in results
        )
        assert statuses == [200, 409], results

        async with test_sessionmaker() as db:
            visits = await db.scalar(
                select(func.count(ServiceVisit.id)).where(ServiceVisit.vin == vin)
            )
            items = await db.scalar(
                select(func.count(ServiceLineItem.id))
                .join(ServiceVisit, ServiceLineItem.visit_id == ServiceVisit.id)
                .where(ServiceVisit.vin == vin)
            )
            reminders = (
                (
                    await db.execute(
                        select(Reminder.status).where(
                            Reminder.vin == vin, Reminder.maintenance_type == "engine_oil_filter"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert visits == 1
        assert items == 1
        assert sorted(reminders) == ["done", "pending"]

    async def test_two_pack_applications_yield_one_rule_per_item(
        self, client, auth_headers, test_sessionmaker
    ):
        vin = await _vehicle(client, auth_headers)
        pack = builtin_pack("oil_and_filter")

        async def _race():
            async with test_sessionmaker() as db:
                return await maintenance_service.apply_pack(db, vin, pack, None)

        results = await asyncio.gather(_race(), _race(), return_exceptions=True)
        assert not any(isinstance(r, Exception) for r in results), results
        async with test_sessionmaker() as db:
            rules = await db.scalar(
                select(func.count(MaintenanceRule.id)).where(MaintenanceRule.vin == vin)
            )
            pending = await db.scalar(
                select(func.count(Reminder.id)).where(
                    Reminder.vin == vin, Reminder.status == "pending"
                )
            )
        assert rules == 2
        assert pending == 2


# ============================================================================
#  N. Explicit anchors survive; placeholders yield
# ============================================================================


class TestNAnchorPrecedence:
    async def test_a_completion_anchor_outlives_older_history_until_a_newer_service(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Oil Change"}],
        )
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "Oil Change",
                "recurrence": {"interval_km": PACK_KM, "interval_months": 6},
                "anchor": {"date": "2026-06-01", "odometer_km": 142900},
            },
        )
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["anchor_kind"] == "completion"
        assert created["anchor_date"] == "2026-06-01"

        for _ in range(2):
            await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        await _apply(client, auth_headers, vin, "oil_and_filter")  # reuses the rule
        oil = await _oil(client, auth_headers, vin)
        assert oil["id"] == created["id"]
        assert oil["anchor_kind"] == "completion"
        assert oil["anchor_date"] == "2026-06-01"
        assert oil["due_date"] == "2026-12-01"

        await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}],
        )
        oil = await _oil(client, auth_headers, vin)
        assert oil["id"] != created["id"]
        assert oil["anchor_date"] == SERVICE_DATE

    async def test_a_baseline_yields_to_an_older_real_service(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        await _apply(client, auth_headers, vin, "oil_and_filter")
        placeholder = await _oil(client, auth_headers, vin)
        assert placeholder["anchor_kind"] == "baseline"

        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}],
        )
        oil = await _oil(client, auth_headers, vin)
        assert oil["id"] == placeholder["id"]  # re-anchored, not completed
        assert oil["anchor_kind"] == "service"
        assert oil["line_item_id"] == visit["line_items"][0]["id"]
        assert oil["due_date"] == SIX_MONTHS_LATER

    async def test_done_today_choice_is_a_completion_anchor(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Oil Change"}],
        )
        await _odometer(client, auth_headers, vin, date.today().isoformat(), 145000)
        preview = await _preview(
            client, auth_headers, vin, "oil_and_filter", {"oil_filter": {"done_today": True}}
        )
        item = next(i for i in preview["items"] if i["key"] == "oil_filter")
        assert item["anchor"]["kind"] == "completion"
        assert item["anchor"]["date"] == date.today().isoformat()
        await _apply(
            client, auth_headers, vin, "oil_and_filter", {"oil_filter": {"done_today": True}}
        )
        oil = await _oil(client, auth_headers, vin)
        assert oil["anchor_kind"] == "completion"
        assert oil["anchor_date"] == date.today().isoformat()
        assert _km(oil["anchor_odometer_km"]) == 145000.0
        assert oil["due_date"] == (date.today() + relativedelta(months=6)).isoformat()
        # Later hooks respect it.
        await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert (await _oil(client, auth_headers, vin))["anchor_kind"] == "completion"


# ============================================================================
#  O. Duplicates on an upgraded installation
# ============================================================================


class TestODuplicates:
    async def test_detect_supersede_and_stay_resolved(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        await _apply(client, auth_headers, vin, "oil_and_filter")
        ruled = await _oil(client, auth_headers, vin)
        loose = (
            await client.post(
                f"/api/vehicles/{vin}/reminders",
                headers=auth_headers,
                json={
                    "title": "Oil & Filter Change",
                    "reminder_type": "date",
                    "due_date": "2027-02-19",
                },
            )
        ).json()

        listed = _of_type(await _pending(client, auth_headers, vin), "engine_oil_filter")
        assert len(listed) == 2
        # The pairing lives on GET /duplicates only (G5a-11).
        assert all("duplicate_of" not in r for r in listed)

        groups = (
            await client.get(f"/api/vehicles/{vin}/reminders/duplicates", headers=auth_headers)
        ).json()
        assert len(groups) == 1
        assert sorted(groups[0]["reminder_ids"]) == sorted([ruled["id"], loose["id"]])
        assert groups[0]["suggested_keep_id"] == ruled["id"]

        # Keep the LOOSE one: the rule moves to it rather than growing back.
        r = await client.post(
            f"/api/vehicles/{vin}/reminders/reconcile-duplicates",
            headers=auth_headers,
            json={"keep_id": loose["id"], "supersede_ids": [ruled["id"]]},
        )
        assert r.status_code == 200, r.text
        everything = {x["id"]: x for x in await _all(client, auth_headers, vin)}
        assert everything[ruled["id"]]["status"] == "dismissed"
        assert everything[ruled["id"]]["superseded_by_id"] == loose["id"]
        assert everything[loose["id"]]["rule_id"] == ruled["rule_id"]

        for _ in range(2):
            await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        oil = await _oil(client, auth_headers, vin)
        assert oil["id"] == loose["id"]

        await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}],
        )
        pending = _of_type(await _pending(client, auth_headers, vin), "engine_oil_filter")
        assert len(pending) == 1
        assert pending[0]["anchor_date"] == SERVICE_DATE


# ============================================================================
#  P. Authorization and id scoping
# ============================================================================


class TestPAuthz:
    async def test_reader_share_cannot_mutate(
        self, client, owner_headers, reader_headers, owned_vehicle
    ):
        vin = owned_vehicle.vin
        applied = await _apply(client, owner_headers, vin, "oil_and_filter")
        oil = next(r for r in applied if r["maintenance_type"] == "engine_oil_filter")
        for path, body in (
            (f"/reminders/{oil['id']}/complete", {"completed_date": date.today().isoformat()}),
            ("/reminders/apply-pack", {"pack_id": "tire_rotation"}),
            ("/reminders/reconcile", None),
            (
                "/reminders/reconcile-duplicates",
                {"keep_id": oil["id"], "supersede_ids": [oil["id"] + 999]},
            ),
            ("/maintenance-rules", {"title": "x", "interval_km": 1}),
        ):
            r = await client.post(f"/api/vehicles/{vin}{path}", headers=reader_headers, json=body)
            assert r.status_code == 403, (path, r.text)
        r = await client.get(f"/api/vehicles/{vin}/reminders/duplicates", headers=reader_headers)
        assert r.status_code == 200  # reads are shared

    async def test_foreign_ids_are_rejected_whole(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        other = await _vehicle(client, auth_headers)
        await _apply(client, auth_headers, vin, "oil_and_filter")
        await _apply(client, auth_headers, other, "oil_and_filter")
        mine = await _oil(client, auth_headers, vin)
        theirs = await _oil(client, auth_headers, other)
        their_visit = await _visit(
            client,
            auth_headers,
            other,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil change and air filter"}],
        )

        r = await client.post(
            f"/api/vehicles/{vin}/reminders/reconcile-duplicates",
            headers=auth_headers,
            json={"keep_id": mine["id"], "supersede_ids": [theirs["id"]]},
        )
        assert r.status_code == 404
        r = await _complete(
            client,
            auth_headers,
            vin,
            mine["id"],
            {
                "completed_date": date.today().isoformat(),
                "mode": "link_visit",
                "service_visit_id": their_visit["id"],
            },
        )
        assert r.status_code == 404
        r = await client.post(
            f"/api/vehicles/{vin}/reminders/apply-pack",
            headers=auth_headers,
            json={
                "pack_id": "oil_and_filter",
                "anchors": {"oil_filter": {"line_item_id": their_visit["line_items"][0]["id"]}},
            },
        )
        assert r.status_code == 422
        r = await client.post(
            f"/api/vehicles/{vin}/reminders/apply-pack",
            headers=auth_headers,
            json={"pack_id": "oil_and_filter", "anchors": {"nope": {"done_today": True}}},
        )
        assert r.status_code == 422
        r = await client.put(
            f"/api/vehicles/{vin}/maintenance-rules/{theirs['rule_id']}",
            headers=auth_headers,
            json={"title": "stolen"},
        )
        assert r.status_code == 404
        # Nothing moved on either side.
        assert (await _oil(client, auth_headers, vin))["status"] == "pending"
        assert (await _oil(client, auth_headers, other))["id"] == theirs["id"]
        assert (
            await client.get(
                f"/api/vehicles/{other}/service-visits/{their_visit['id']}", headers=auth_headers
            )
        ).json()["line_items"][0]["maintenance_type"] is None


# ============================================================================
#  Q. Inactive rules, legacy adoption, same-day events
# ============================================================================


class TestQEdges:
    async def test_inactive_rule_completes_without_a_successor(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        created = (
            await client.post(
                f"/api/vehicles/{vin}/reminders",
                headers=auth_headers,
                json={"title": "Coolant flush", "recurrence": {"interval_months": 24}},
            )
        ).json()
        assert created["maintenance_type"] == "coolant_service"
        r = await client.delete(
            f"/api/vehicles/{vin}/maintenance-rules/{created['rule_id']}", headers=auth_headers
        )
        assert r.status_code == 204
        r = await _complete(
            client,
            auth_headers,
            vin,
            created["id"],
            {"completed_date": date.today().isoformat(), "mode": "mark_only"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["next_reminder"] is None
        assert _of_type(await _pending(client, auth_headers, vin), "coolant_service") == []

    async def test_unreferenced_rule_is_deleted_outright(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        # A rule whose reminder never got created (no threshold: mileage-only
        # rule on a vehicle with no reading and no history) references nothing.
        r = await client.post(
            f"/api/vehicles/{vin}/maintenance-rules",
            headers=auth_headers,
            json={"title": "Belt", "maintenance_type": "drive_belt", "interval_km": 100000},
        )
        assert r.status_code == 201, r.text
        rule_id = r.json()["id"]
        assert _of_type(await _pending(client, auth_headers, vin), "drive_belt") == []
        r = await client.delete(
            f"/api/vehicles/{vin}/maintenance-rules/{rule_id}", headers=auth_headers
        )
        assert r.status_code == 204
        ids = {
            x["id"]
            for x in (
                await client.get(f"/api/vehicles/{vin}/maintenance-rules", headers=auth_headers)
            ).json()
        }
        assert rule_id not in ids

    async def test_legacy_loose_reminder_adopted_without_anchor_then_anchored(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        loose = (
            await client.post(
                f"/api/vehicles/{vin}/reminders",
                headers=auth_headers,
                json={
                    "title": "Tire Rotation",
                    "reminder_type": "mileage",
                    "due_mileage_km": 154484.94,
                },
            )
        ).json()
        await _apply(client, auth_headers, vin, "tire_rotation")
        adopted = _of_type(await _pending(client, auth_headers, vin), "tire_rotation")
        assert [r["id"] for r in adopted] == [loose["id"]]
        assert adopted[0]["anchor_kind"] is None
        assert _km(adopted[0]["due_mileage_km"]) == 154484.94

        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=date.today().isoformat(),
            odometer_km=SERVICE_KM,
            items=[{"description": "Tire Rotation"}],
        )
        rotation = _of_type(await _pending(client, auth_headers, vin), "tire_rotation")
        assert len(rotation) == 1
        assert rotation[0]["id"] == loose["id"]  # same day as its creation: adopted
        assert rotation[0]["anchor_kind"] == "service"
        assert rotation[0]["line_item_id"] == visit["line_items"][0]["id"]
        assert _km(rotation[0]["due_mileage_km"]) == _km(SERVICE_KM + 10000)

    async def test_rule_edit_recomputes_and_due_fields_are_derived(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        reminder = await _rule_from_report(client, auth_headers, vin)
        r = await client.put(
            f"/api/vehicles/{vin}/reminders/{reminder['id']}",
            headers=auth_headers,
            json={"due_date": "2027-01-01"},
        )
        assert r.status_code == 422
        r = await client.put(
            f"/api/vehicles/{vin}/maintenance-rules/{reminder['rule_id']}",
            headers=auth_headers,
            json={"recurrence": {"interval_km": PACK_KM, "interval_months": 3}},
        )
        assert r.status_code == 200, r.text
        oil = await _oil(client, auth_headers, vin)
        assert oil["due_date"] == "2026-09-13"
        assert _km(oil["due_mileage_km"]) == _km(SERVICE_KM + PACK_KM)
        # The reminder form edits the same rule through the reminder.
        r = await client.put(
            f"/api/vehicles/{vin}/reminders/{reminder['id']}",
            headers=auth_headers,
            json={"recurrence": {"interval_km": INTERVAL_KM, "interval_months": 6}},
        )
        assert r.status_code == 200, r.text
        assert r.json()["due_date"] == SIX_MONTHS_LATER
        # Stop recurring: the rule goes inactive and the due values stay.
        r = await client.put(
            f"/api/vehicles/{vin}/reminders/{reminder['id']}",
            headers=auth_headers,
            json={"recurrence": None},
        )
        assert r.status_code == 200, r.text
        assert r.json()["rule"]["is_active"] is False
        assert r.json()["due_date"] == SIX_MONTHS_LATER

    async def test_legacy_done_and_webhook_still_advance(self, client, auth_headers, db_session):
        from app.models.settings import Setting

        vin = await _vehicle(client, auth_headers)
        await _odometer(client, auth_headers, vin, date.today().isoformat(), 90000)
        await _apply(client, auth_headers, vin, "oil_and_filter")
        first = await _oil(client, auth_headers, vin)
        r = await client.post(
            f"/api/vehicles/{vin}/reminders/{first['id']}/done", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "done"
        assert r.json()["completed_date"] == date.today().isoformat()
        second = await _oil(client, auth_headers, vin)
        assert second["id"] != first["id"]
        assert second["anchor_kind"] == "completion"
        assert _km(second["due_mileage_km"]) == 98000.0

        existing = await db_session.scalar(
            select(Setting).where(Setting.key == "webhook_ingest_token")
        )
        if existing is None:
            db_session.add(Setting(key="webhook_ingest_token", value="secret-webhook"))
        else:
            existing.value = "secret-webhook"
        await db_session.commit()
        r = await client.post(
            "/api/v1/webhooks/reminders/complete",
            json={"vin": vin, "reminder_id": second["id"]},
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert r.status_code == 200, r.text
        third = await _oil(client, auth_headers, vin)
        assert third["id"] != second["id"]

    async def test_hours_rule_anchors_on_engine_hours(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers, vehicle_type="ATV")
        await _apply(client, auth_headers, vin, "atv_utv_service")
        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=date.today().isoformat(),
            odometer_km=None,
            items=[{"description": "Engine Oil Change"}],
            engine_hours=100,
        )
        oil = await _oil(client, auth_headers, vin)
        assert oil["line_item_id"] == visit["line_items"][0]["id"]
        assert float(oil["anchor_hours"]) == 100.0
        assert float(oil["due_hours"]) == 150.0
        assert oil["reminder_type"] == "hours"

    async def test_preview_offers_an_untyped_candidate_and_choosing_it_types_it(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil change and air filter"}],
        )
        item_id = visit["line_items"][0]["id"]
        assert visit["line_items"][0]["maintenance_type"] is None
        preview = await _preview(client, auth_headers, vin, "oil_and_filter")
        oil_item = next(i for i in preview["items"] if i["key"] == "oil_filter")
        assert oil_item["anchor"]["kind"] == "baseline"
        assert [c["line_item_id"] for c in oil_item["untyped_candidates"]] == [item_id]

        chosen = await _preview(
            client, auth_headers, vin, "oil_and_filter", {"oil_filter": {"line_item_id": item_id}}
        )
        oil_item = next(i for i in chosen["items"] if i["key"] == "oil_filter")
        assert oil_item["anchor"]["kind"] == "service"
        assert oil_item["anchor"]["date"] == SERVICE_DATE
        assert oil_item["due_date"] == SIX_MONTHS_LATER

        await _apply(
            client, auth_headers, vin, "oil_and_filter", {"oil_filter": {"line_item_id": item_id}}
        )
        typed = (
            await client.get(
                f"/api/vehicles/{vin}/service-visits/{visit['id']}", headers=auth_headers
            )
        ).json()
        assert typed["line_items"][0]["maintenance_type"] == "engine_oil_filter"
        oil = await _oil(client, auth_headers, vin)
        assert oil["line_item_id"] == item_id
        assert oil["due_date"] == SIX_MONTHS_LATER


# ============================================================================
#  S. Codex code review, round 1 (2026-09-17): each test failed before its fix
# ============================================================================


class TestSCodexRound1:
    async def test_h1_two_concurrent_recurring_creates_make_one_rule(
        self, client, auth_headers, test_sessionmaker
    ):
        """Both requests used to read zero rules of the type and create one each."""
        from app.schemas.maintenance import RecurrenceSpec
        from app.schemas.reminder import ReminderCreate

        vin = await _vehicle(client, auth_headers)
        data = ReminderCreate(title="Oil change", recurrence=RecurrenceSpec(interval_months=6))

        async def _race():
            async with test_sessionmaker() as db:
                reminder = await maintenance_service.create_recurring_reminder(db, vin, data)
                await db.commit()
                return reminder.id

        results = await asyncio.gather(_race(), _race(), return_exceptions=True)
        assert not [r for r in results if isinstance(r, Exception)], results
        async with test_sessionmaker() as db:
            rules = await db.scalar(
                select(func.count(MaintenanceRule.id)).where(MaintenanceRule.vin == vin)
            )
            pending = await db.scalar(
                select(func.count(Reminder.id)).where(
                    Reminder.vin == vin, Reminder.status == "pending"
                )
            )
        assert rules == 1
        assert pending == 1

    async def test_h1_two_concurrent_visits_with_recurring_items_make_one_rule(
        self, client, auth_headers, test_sessionmaker, test_user
    ):
        from app.models.user import User
        from app.schemas.maintenance import RecurrenceSpec
        from app.schemas.reminder import ReminderCreate
        from app.schemas.service_visit import ServiceLineItemCreate, ServiceVisitCreate
        from app.services.service_visit_service import ServiceVisitService

        vin = await _vehicle(client, auth_headers)

        def _payload(on: str, km: str) -> ServiceVisitCreate:
            return ServiceVisitCreate(
                date=date.fromisoformat(on),
                odometer_km=Decimal(km),
                line_items=[
                    ServiceLineItemCreate(
                        description="Oil Change",
                        reminder=ReminderCreate(
                            title="Oil Change", recurrence=RecurrenceSpec(interval_months=6)
                        ),
                    )
                ],
            )

        async def _race(on: str, km: str):
            async with test_sessionmaker() as db:
                user = await db.get(User, test_user["id"])
                return await ServiceVisitService(db).create_service_visit(
                    vin, _payload(on, km), user
                )

        results = await asyncio.gather(
            _race(OLDER_DATE, str(OLDER_KM)),
            _race(SERVICE_DATE, str(SERVICE_KM)),
            return_exceptions=True,
        )
        assert not [r for r in results if isinstance(r, Exception)], results
        async with test_sessionmaker() as db:
            rules = await db.scalar(
                select(func.count(MaintenanceRule.id)).where(MaintenanceRule.vin == vin)
            )
        assert rules == 1
        oil = await _oil(client, auth_headers, vin)
        assert oil["anchor_date"] == SERVICE_DATE

    async def test_h2_a_stale_loaded_reminder_is_not_completed_twice(
        self, client, auth_headers, test_sessionmaker
    ):
        vin = await _vehicle(client, auth_headers)
        await _apply(client, auth_headers, vin, "oil_and_filter")
        oil = await _oil(client, auth_headers, vin)
        first = ReminderCompleteRequest(
            completed_date=date.fromisoformat(SERVICE_DATE),
            odometer_km=Decimal(str(SERVICE_KM)),
            mode="mark_only",
        )
        second = ReminderCompleteRequest(
            completed_date=date.today(), odometer_km=Decimal("999999"), mode="mark_only"
        )
        async with test_sessionmaker() as stale, test_sessionmaker() as other:
            loaded = await stale.get(Reminder, oil["id"])
            assert loaded is not None and loaded.status == "pending"
            await maintenance_service.complete_reminder(other, vin, oil["id"], first)
            with pytest.raises(Exception) as caught:
                await maintenance_service.complete_reminder(stale, vin, oil["id"], second)
            assert getattr(caught.value, "status_code", None) == 409
        everything = {r["id"]: r for r in await _all(client, auth_headers, vin)}
        assert everything[oil["id"]]["completed_date"] == SERVICE_DATE
        assert _km(everything[oil["id"]]["completed_odometer_km"]) == SERVICE_KM

    async def test_h3_a_linked_visit_is_the_anchor_not_the_dialog_defaults(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        await _apply(client, auth_headers, vin, "oil_and_filter")
        oil = await _oil(client, auth_headers, vin)
        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Labor"}],
        )
        r = await _complete(
            client,
            auth_headers,
            vin,
            oil["id"],
            {
                "completed_date": date.today().isoformat(),
                "odometer_km": SERVICE_KM + 10000,
                "mode": "link_visit",
                "service_visit_id": visit["id"],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reminder"]["completed_date"] == SERVICE_DATE
        assert _km(body["reminder"]["completed_odometer_km"]) == SERVICE_KM
        nxt = body["next_reminder"]
        assert nxt["anchor_date"] == SERVICE_DATE
        assert _km(nxt["anchor_odometer_km"]) == SERVICE_KM
        assert nxt["due_date"] == SIX_MONTHS_LATER

    async def test_h3_correcting_the_completing_visit_moves_the_successor(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        await _apply(client, auth_headers, vin, "oil_and_filter")
        oil = await _oil(client, auth_headers, vin)
        r = await _complete(
            client,
            auth_headers,
            vin,
            oil["id"],
            {"completed_date": SERVICE_DATE, "odometer_km": SERVICE_KM, "mode": "create_visit"},
        )
        assert r.status_code == 200, r.text
        visit_id = r.json()["service_visit_id"]
        corrected = "2026-06-10"
        r = await client.put(
            f"/api/vehicles/{vin}/service-visits/{visit_id}",
            headers=auth_headers,
            json={"date": corrected},
        )
        assert r.status_code == 200, r.text
        nxt = await _oil(client, auth_headers, vin)
        assert nxt["anchor_date"] == corrected
        assert nxt["due_date"] == "2026-12-10"

    async def test_h4_retyping_a_rule_retypes_and_reanchors_its_reminder(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        tire_visit = await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Tire rotation"}],
        )
        await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}],
        )
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "Every six months",
                "maintenance_type": "engine_oil_filter",
                "recurrence": {"interval_months": 6},
            },
        )
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["anchor_date"] == SERVICE_DATE
        r = await client.put(
            f"/api/vehicles/{vin}/maintenance-rules/{created['rule_id']}",
            headers=auth_headers,
            json={"maintenance_type": "tire_rotation"},
        )
        assert r.status_code == 200, r.text
        pending = [
            x
            for x in await _pending(client, auth_headers, vin)
            if x["rule_id"] == created["rule_id"]
        ]
        assert len(pending) == 1
        assert pending[0]["maintenance_type"] == "tire_rotation"
        assert pending[0]["anchor_date"] == OLDER_DATE
        assert pending[0]["line_item_id"] == tire_visit["line_items"][0]["id"]

    async def test_h4_retyping_a_rule_backed_reminder_retypes_its_rule(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Tire rotation"}],
        )
        await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}],
        )
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "Every six months",
                "maintenance_type": "engine_oil_filter",
                "recurrence": {"interval_months": 6},
            },
        )
        created = r.json()
        r = await client.put(
            f"/api/vehicles/{vin}/reminders/{created['id']}",
            headers=auth_headers,
            json={"maintenance_type": "tire_rotation"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["maintenance_type"] == "tire_rotation"
        assert r.json()["anchor_date"] == OLDER_DATE
        rules = (
            await client.get(f"/api/vehicles/{vin}/maintenance-rules", headers=auth_headers)
        ).json()
        assert [x["maintenance_type"] for x in rules] == ["tire_rotation"]

    async def test_h5_done_today_beats_an_earlier_same_day_service(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        today = date.today().isoformat()
        await _visit(
            client,
            auth_headers,
            vin,
            on=today,
            odometer_km=10000.0,
            items=[{"description": "Oil Change"}],
        )
        await _odometer(client, auth_headers, vin, today, 15000.0)
        choice = {"oil_filter": {"done_today": True}}
        preview = await _preview(client, auth_headers, vin, "oil_and_filter", choice)
        planned = next(i for i in preview["items"] if i["key"] == "oil_filter")
        assert _km(planned["due_mileage_km"]) == 23000.0

        await _apply(client, auth_headers, vin, "oil_and_filter", choice)
        assert _km((await _oil(client, auth_headers, vin))["due_mileage_km"]) == 23000.0
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200, r.text
        await _apply(client, auth_headers, vin, "oil_and_filter")
        assert _km((await _oil(client, auth_headers, vin))["due_mileage_km"]) == 23000.0

    async def test_f1_recurring_create_returns_the_pending_successor(self, client, auth_headers):
        """A reactivated rule whose old pending reminder is completed by newer
        history must return the new pending reminder, not the done one."""
        vin = await _vehicle(client, auth_headers)
        await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Oil Change"}],
        )
        body = {
            "title": "Oil change",
            "maintenance_type": "engine_oil_filter",
            "recurrence": {"interval_months": 6},
        }
        r = await client.post(f"/api/vehicles/{vin}/reminders", headers=auth_headers, json=body)
        first = r.json()
        r = await client.put(
            f"/api/vehicles/{vin}/maintenance-rules/{first['rule_id']}",
            headers=auth_headers,
            json={"is_active": False},
        )
        assert r.status_code == 200, r.text
        await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}],
        )
        r = await client.post(f"/api/vehicles/{vin}/reminders", headers=auth_headers, json=body)
        assert r.status_code == 201, r.text
        again = r.json()
        assert again["status"] == "pending"
        assert again["anchor_date"] == SERVICE_DATE
        assert again["id"] != first["id"]


# ============================================================================
#  T. Codex code review, round 2
# ============================================================================


class TestTCodexRound2:
    async def test_r2_h1_retyping_ignores_mark_only_completions_of_the_old_type(
        self, client, auth_headers
    ):
        """An oil reminder completed mark-only is oil history. After the rule is
        retyped to tire rotation, it must not anchor the tire reminder."""
        vin = await _vehicle(client, auth_headers)
        await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Tire rotation"}],
        )
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "Six-monthly job",
                "maintenance_type": "engine_oil_filter",
                "recurrence": {"interval_months": 6},
            },
        )
        assert r.status_code == 201, r.text
        oil = r.json()
        r = await _complete(
            client,
            auth_headers,
            vin,
            oil["id"],
            {"completed_date": SERVICE_DATE, "odometer_km": SERVICE_KM, "mode": "mark_only"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["next_reminder"]["anchor_date"] == SERVICE_DATE

        r = await client.put(
            f"/api/vehicles/{vin}/maintenance-rules/{oil['rule_id']}",
            headers=auth_headers,
            json={"maintenance_type": "tire_rotation"},
        )
        assert r.status_code == 200, r.text
        pending = [
            x for x in await _pending(client, auth_headers, vin) if x["rule_id"] == oil["rule_id"]
        ]
        assert len(pending) == 1
        assert pending[0]["maintenance_type"] == "tire_rotation"
        assert pending[0]["anchor_date"] == OLDER_DATE
        assert pending[0]["due_date"] == "2026-09-16"

        # Reconciling again does not bring the oil completion back.
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200, r.text
        again = [
            x for x in await _pending(client, auth_headers, vin) if x["rule_id"] == oil["rule_id"]
        ]
        assert again[0]["anchor_date"] == OLDER_DATE


# ============================================================================
#  U. Codex review of PR #168
# ============================================================================


class TestUCodexPR168:
    async def test_p1_retyping_a_line_item_moves_the_old_rule_off_it(self, client, auth_headers):
        """Correcting a service's type must not leave the old type's reminder
        counting from it, and the new type's rule must be able to use it."""
        vin = await _vehicle(client, auth_headers)
        older = await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Oil Change"}],
        )
        newer = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}],
        )
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "Oil change",
                "maintenance_type": "engine_oil_filter",
                "recurrence": {"interval_months": 6},
            },
        )
        assert r.status_code == 201, r.text
        oil = r.json()
        assert oil["anchor_date"] == SERVICE_DATE
        retyped_item = newer["line_items"][0]["id"]
        assert oil["line_item_id"] == retyped_item

        # The owner corrects the newer visit: that work was a tire rotation.
        r = await client.put(
            f"/api/vehicles/{vin}/service-visits/{newer['id']}",
            headers=auth_headers,
            json={
                "line_items": [
                    {
                        "id": retyped_item,
                        "description": "Oil Change",
                        "maintenance_type": "tire_rotation",
                    }
                ]
            },
        )
        assert r.status_code == 200, r.text

        moved = await _oil(client, auth_headers, vin)
        assert moved["anchor_date"] == OLDER_DATE
        assert moved["line_item_id"] == older["line_items"][0]["id"]
        assert moved["due_date"] == "2026-09-16"

        # And the retyped service is available to the type it now belongs to.
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "Rotate tires",
                "maintenance_type": "tire_rotation",
                "recurrence": {"interval_months": 6},
            },
        )
        assert r.status_code == 201, r.text
        tires = r.json()
        assert tires["anchor_date"] == SERVICE_DATE
        assert tires["line_item_id"] == retyped_item

    async def test_p2_duplicate_reconciliation_refuses_two_different_types(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        made = []
        for title, code in (("Oil change", "engine_oil_filter"), ("Rotate tires", "tire_rotation")):
            r = await client.post(
                f"/api/vehicles/{vin}/reminders",
                headers=auth_headers,
                json={
                    "title": title,
                    "maintenance_type": code,
                    "recurrence": {"interval_months": 6},
                },
            )
            assert r.status_code == 201, r.text
            made.append(r.json())
        r = await client.post(
            f"/api/vehicles/{vin}/reminders/reconcile-duplicates",
            headers=auth_headers,
            json={"keep_id": made[0]["id"], "supersede_ids": [made[1]["id"]]},
        )
        assert r.status_code == 422, r.text
        statuses = {x["id"]: x["status"] for x in await _all(client, auth_headers, vin)}
        assert statuses[made[0]["id"]] == "pending"
        assert statuses[made[1]["id"]] == "pending"
        rules = (
            await client.get(f"/api/vehicles/{vin}/maintenance-rules", headers=auth_headers)
        ).json()
        assert [x["is_active"] for x in rules] == [True, True]

    async def test_p2_dismissing_a_recurring_reminder_stops_it_repeating(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}],
        )
        await _apply(client, auth_headers, vin, "oil_and_filter")
        oil = await _oil(client, auth_headers, vin)

        r = await client.post(
            f"/api/vehicles/{vin}/reminders/{oil['id']}/dismiss", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "dismissed"
        rule = next(
            x
            for x in (
                await client.get(f"/api/vehicles/{vin}/maintenance-rules", headers=auth_headers)
            ).json()
            if x["id"] == oil["rule_id"]
        )
        assert rule["is_active"] is False

        # Neither an explicit reconcile nor a later service brings it back.
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200, r.text
        await _visit(
            client,
            auth_headers,
            vin,
            on="2026-07-20",
            odometer_km=SERVICE_KM + 2000,
            items=[{"description": "Oil Change"}],
        )
        assert _of_type(await _pending(client, auth_headers, vin), "engine_oil_filter") == []

    async def test_p2_deleting_a_recurring_reminder_stops_it_repeating(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}],
        )
        await _apply(client, auth_headers, vin, "oil_and_filter")
        oil = await _oil(client, auth_headers, vin)
        rule_id = oil["rule_id"]

        r = await client.delete(f"/api/vehicles/{vin}/reminders/{oil['id']}", headers=auth_headers)
        assert r.status_code == 204, r.text
        rule = next(
            x
            for x in (
                await client.get(f"/api/vehicles/{vin}/maintenance-rules", headers=auth_headers)
            ).json()
            if x["id"] == rule_id
        )
        assert rule["is_active"] is False
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert _of_type(await _pending(client, auth_headers, vin), "engine_oil_filter") == []

    async def test_p2_dismissing_a_one_off_reminder_touches_no_rule(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        await _apply(client, auth_headers, vin, "oil_and_filter")
        oil = await _oil(client, auth_headers, vin)
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={"title": "Wash it", "reminder_type": "date", "due_date": SIX_MONTHS_LATER},
        )
        assert r.status_code == 201, r.text
        one_off = r.json()
        assert one_off["rule_id"] is None
        r = await client.post(
            f"/api/vehicles/{vin}/reminders/{one_off['id']}/dismiss", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        rule = next(
            x
            for x in (
                await client.get(f"/api/vehicles/{vin}/maintenance-rules", headers=auth_headers)
            ).json()
            if x["id"] == oil["rule_id"]
        )
        assert rule["is_active"] is True
        assert len(_of_type(await _pending(client, auth_headers, vin), "engine_oil_filter")) == 1

    async def test_deleting_the_anchoring_service_falls_back_to_the_previous_one(
        self, client, auth_headers
    ):
        """A reminder must not keep counting from a service that no longer
        exists (design section 13, resolved with the retype fix's rule)."""
        vin = await _vehicle(client, auth_headers)
        older = await _visit(
            client,
            auth_headers,
            vin,
            on=OLDER_DATE,
            odometer_km=OLDER_KM,
            items=[{"description": "Oil Change"}],
        )
        newer = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}],
        )
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "Oil change",
                "maintenance_type": "engine_oil_filter",
                "recurrence": {"interval_months": 6},
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["anchor_date"] == SERVICE_DATE

        r = await client.delete(
            f"/api/vehicles/{vin}/service-visits/{newer['id']}", headers=auth_headers
        )
        assert r.status_code == 204, r.text

        moved = await _oil(client, auth_headers, vin)
        assert moved["anchor_kind"] == "service"
        assert moved["anchor_date"] == OLDER_DATE
        assert moved["line_item_id"] == older["line_items"][0]["id"]
        assert moved["due_date"] == "2026-09-16"

    async def test_deleting_the_only_anchoring_service_falls_back_to_a_baseline(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        only = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM,
            items=[{"description": "Oil Change"}],
        )
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "Oil change",
                "maintenance_type": "engine_oil_filter",
                "recurrence": {"interval_months": 6},
            },
        )
        assert r.status_code == 201, r.text
        r = await client.delete(
            f"/api/vehicles/{vin}/service-visits/{only['id']}", headers=auth_headers
        )
        assert r.status_code == 204, r.text
        moved = await _oil(client, auth_headers, vin)
        assert moved["anchor_kind"] == "baseline"
        assert moved["line_item_id"] is None
        assert moved["anchor_date"] == date.today().isoformat()


# ============================================================================
#  T. Section-13 edge-case pins (plan 2026-09-18, feature D)
# ============================================================================


async def _hours(client: AsyncClient, headers: dict, vin: str, on: str, hours: float) -> None:
    r = await client.post(
        f"/api/vehicles/{vin}/hours",
        headers=headers,
        json={"vin": vin, "date": on, "engine_hours": hours},
    )
    assert r.status_code == 201, r.text


class TestT13EdgeCasePins:
    """Regression pins for the two section-13 edge cases.

    The behavior is correct by design ("dropped, not guessed" +
    "same date = same event"); these tests keep it that way. Extends the
    coverage of TestQEdges (hours) and TestNAnchorPrecedence (same-day).
    """

    async def test_hours_threshold_dropped_when_the_visit_has_only_an_odometer(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers, vehicle_type="ATV")
        visit = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=1000.0,
            items=[{"description": "Engine Oil Change"}],
        )
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "Engine Oil Change",
                "recurrence": {"interval_hours": 50, "interval_months": 6},
            },
        )
        assert r.status_code == 201, r.text
        oil = await _oil(client, auth_headers, vin)
        # Anchored on the odometer-only visit: the hours interval is dropped,
        # not guessed; the calendar half of the rule survives.
        assert oil["line_item_id"] == visit["line_items"][0]["id"]
        assert oil["due_hours"] is None
        assert oil["due_date"] == SIX_MONTHS_LATER
        assert oil["reminder_type"] == "date"

    async def test_a_later_hours_reading_backfills_the_dropped_threshold(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers, vehicle_type="ATV")
        await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=1000.0,
            items=[{"description": "Engine Oil Change"}],
        )
        r = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "Engine Oil Change",
                "recurrence": {"interval_hours": 50, "interval_months": 6},
            },
        )
        assert r.status_code == 201, r.text
        await _hours(client, auth_headers, vin, on=SERVICE_DATE, hours=100.0)
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200, r.text
        oil = await _oil(client, auth_headers, vin)
        assert float(oil["anchor_hours"]) == 100.0
        assert float(oil["due_hours"]) == 150.0
        assert oil["reminder_type"] == "smart"

    async def test_an_hours_only_rule_writes_no_reminder_until_a_reading_exists(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers, vehicle_type="ATV")
        r = await client.post(
            f"/api/vehicles/{vin}/maintenance-rules",
            headers=auth_headers,
            json={
                "title": "Engine Oil Change",
                "maintenance_type": "engine_oil_filter",
                "interval_hours": 50,
            },
        )
        assert r.status_code == 201, r.text
        # No hours anywhere: nothing to anchor an hours threshold on, so no
        # reminder row at all (the sharpest edge of "dropped, not guessed").
        assert _of_type(await _pending(client, auth_headers, vin), "engine_oil_filter") == []
        await _hours(client, auth_headers, vin, on=SERVICE_DATE, hours=100.0)
        r = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=auth_headers)
        assert r.status_code == 200, r.text
        oil = await _oil(client, auth_headers, vin)
        assert oil["anchor_kind"] == "baseline"
        assert float(oil["due_hours"]) == 150.0

    async def test_two_same_type_services_on_one_date_are_one_event(self, client, auth_headers):
        vin = await _vehicle(client, auth_headers)
        await _rule_from_report(client, auth_headers, vin)
        first = await _oil(client, auth_headers, vin)
        visit_b = await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM + 200,
            items=[{"description": "Oil Change"}],
        )
        after = await _oil(client, auth_headers, vin)
        # Same date = same event: re-anchor, no completion, no successor.
        assert after["id"] == first["id"]
        done = [
            x
            for x in _of_type(await _all(client, auth_headers, vin), "engine_oil_filter")
            if x["status"] == "done"
        ]
        assert done == []
        # The day's later event (_newer: higher odometer) is the anchor.
        assert after["line_item_id"] == visit_b["line_items"][0]["id"]
        assert _km(after["due_mileage_km"]) == _km(SERVICE_KM + 200 + INTERVAL_KM)

    async def test_pack_preview_never_calls_a_same_day_service_a_completion(
        self, client, auth_headers
    ):
        vin = await _vehicle(client, auth_headers)
        rule = await _rule_from_report(client, auth_headers, vin)
        # A same-day SECOND visit at a LOWER odometer: `_newer` keeps the
        # first visit as the anchor, so the pending reminder and the newest
        # typed history end up on DIFFERENT line items sharing one date.
        # That makes the strict `newest.date > current.date` predicate the
        # only thing standing between preview and a false "a newer service
        # completes this reminder" (the same-line-item guard is out of play).
        await _visit(
            client,
            auth_headers,
            vin,
            on=SERVICE_DATE,
            odometer_km=SERVICE_KM - 200,
            items=[{"description": "Oil Change"}],
        )
        oil = await _oil(client, auth_headers, vin)
        assert oil["line_item_id"] == rule["_line_item_id"]
        preview = await _preview(client, auth_headers, vin, "oil_and_filter")
        item = next(i for i in preview["items"] if i["key"] == "oil_filter")
        assert item["newer_service"] is None
