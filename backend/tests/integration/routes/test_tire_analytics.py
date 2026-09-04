"""`GET /api/analytics/vehicles/{vin}/tires`.

Read-only, no migration, and deliberately thin: the tires come from
`TireService.list_tires`, so this endpoint and the tire card cannot disagree
about a distance or a projection. What it adds is the readiness block, which is
the part worth shipping on an instance that has no tire data yet.

The unit counts have their own file (`tests/unit/services/test_tire_readiness.py`).
What is tested here is the wiring: scoping, retired inclusion, and the
vehicle-level odometer flag that makes every open period unbounded when it is
false.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.models.odometer import OdometerRecord
from app.models.vehicle import Vehicle

ENDPOINT = "/api/analytics/vehicles/{vin}/tires"


@pytest_asyncio.fixture
async def vehicle(db_session, test_user):
    vin = f"TXREANL{uuid.uuid4().hex[:10].upper()}".replace("I", "X")[:17]
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Analytics Rig",
            vehicle_type="Car",
            year=2022,
            make="Mazda",
            model="CX5",
        )
    )
    await db_session.commit()
    yield vin
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


async def _mount(client: AsyncClient, headers, vin: str, position: str, **extra) -> dict:
    body = {"vin": vin, "position": position, "tread_depth_mm": "8.0", **extra}
    response = await client.post(
        f"/api/vehicles/{vin}/tires/create-and-mount", headers=headers, json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
class TestTheEndpoint:
    async def test_a_vehicle_with_no_tires_answers_empty(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """200 and nothing, not a 404. The section is gated client-side on
        `tires.length`, so the endpoint has to be safe to call for anything."""
        response = await client.get(ENDPOINT.format(vin=vehicle), headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["tires"] == []
        assert body["readiness"]["total"] == 0
        assert body["has_odometer_record"] is False

    async def test_it_reports_the_same_figures_the_tire_card_does(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """Not an assertion about a number, an assertion about AGREEMENT.

        A second serialisation of distance or wear that can drift from the card
        is worse than no analytics page, so the two are compared field by field
        rather than each being pinned to a literal.
        """
        await _mount(client, auth_headers, vehicle, "FL", mounted_odometer_km="1000")

        card = await client.get(f"/api/vehicles/{vehicle}/tires", headers=auth_headers)
        page = await client.get(ENDPOINT.format(vin=vehicle), headers=auth_headers)
        assert page.status_code == 200, page.text

        card_tire = card.json()["tires"][0]
        page_tire = page.json()["tires"][0]
        for field in (
            "distance_status",
            "distance_km",
            "known_distance_km",
            "known_distance_since",
            "wear_status",
            "projected_km_remaining",
            "projected_wear_date",
            "blocking_period_ids",
        ):
            assert page_tire[field] == card_tire[field], field

    async def test_the_odometer_flag_follows_the_vehicle_not_the_tire(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Its own empty state (B3).

        An OPEN mount period's upper bound is the vehicle's latest
        `OdometerRecord`, so a vehicle with none returns an unbounded distance
        for every tire however complete its mount history is. The page explains
        that once rather than per tire, which it can only do if it is told.
        """
        before = await client.get(ENDPOINT.format(vin=vehicle), headers=auth_headers)
        assert before.json()["has_odometer_record"] is False

        db_session.add(OdometerRecord(vin=vehicle, date=dt.date(2026, 3, 1), odometer_km=42000))
        await db_session.commit()

        after = await client.get(ENDPOINT.format(vin=vehicle), headers=auth_headers)
        assert after.json()["has_odometer_record"] is True

    async def test_a_retired_tire_is_in_the_list_and_out_of_readiness(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """B10, end to end.

        The default tire listing hides retired tires; this endpoint asks for
        them, because a retired tire's final distance and wear are the most
        complete data the app will ever hold about it. It is the readiness
        counts it stays out of.
        """
        keeper = await _mount(client, auth_headers, vehicle, "FL", mounted_odometer_km="1000")
        goner = await _mount(client, auth_headers, vehicle, "FR", mounted_odometer_km="1000")
        retired = await client.post(
            f"/api/vehicles/{vehicle}/tires/{goner['id']}/retire",
            headers=auth_headers,
            json={"dismounted_odometer_km": "2000"},
        )
        assert retired.status_code == 200, retired.text

        body = (await client.get(ENDPOINT.format(vin=vehicle), headers=auth_headers)).json()
        ids = {t["id"] for t in body["tires"]}
        assert ids == {keeper["id"], goner["id"]}
        assert body["readiness"]["total"] == 1

    async def test_readiness_counts_the_tires_that_can_answer(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """One tire that can trend and one that cannot, so the count is 1.

        Seeded rather than asserted against an empty vehicle: a count of 0 on
        no data is true whatever the code does.
        """
        trending = await _mount(client, auth_headers, vehicle, "FL", mounted_odometer_km="1000")
        await _mount(client, auth_headers, vehicle, "FR", mounted_odometer_km="1000")
        for day, tread in (("2026-01-01", "8.0"), ("2026-02-01", "7.0")):
            logged = await client.post(
                f"/api/vehicles/{vehicle}/tires/{trending['id']}/readings",
                headers=auth_headers,
                json={"recorded_at": day, "tread_depth_mm": tread, "odometer_km": "5000"},
            )
            assert logged.status_code == 201, logged.text

        readiness = (await client.get(ENDPOINT.format(vin=vehicle), headers=auth_headers)).json()[
            "readiness"
        ]
        assert readiness["total"] == 2
        assert readiness["can_trend"] == 1
        assert readiness["needs_second_reading"] == 1

    async def test_an_unknown_vin_is_refused(self, client: AsyncClient, auth_headers):
        """Through the access gate, not around it.

        Without one this endpoint would answer 200 with an empty summary for
        any string at all, which is the shape that leaks whether a VIN exists.

        Deliberately NOT "another user's vehicle": the shared `test_user`
        fixture is an admin, and `get_vehicle_or_403` grants admins every
        vehicle, so that test would assert a refusal that correctly never
        happens.
        """
        response = await client.get(ENDPOINT.format(vin="1HGCM82633A999999"), headers=auth_headers)
        assert response.status_code in (403, 404), response.text
