"""An edit can't leave a fill-up that create would refuse.

Create requires a reading (odometer, or engine hours) and a fuel amount,
bar the propane-refill and missed-fill-up exemptions. Update never checked
the merged record, which went unnoticed while the forms couldn't clear a
field. Once they could, an emptied propane refill vanished from the only
list that shows it. Only an edit that CHANGES one of those fields is held
to the rule: the forms send them all on every save, and a legacy record that
already falls short must still take a notes edit.
"""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.own_vehicle(vehicle_type="Truck", make="Ram", model="2500", fuel_type="diesel"),
]


async def _create(client: AsyncClient, headers: dict, vin: str, **fields) -> dict:
    r = await client.post(
        f"/api/vehicles/{vin}/fuel",
        json={"vin": vin, "date": "2032-01-10", **fields},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _put(client: AsyncClient, headers: dict, vin: str, record_id: int, body: dict):
    return await client.put(f"/api/vehicles/{vin}/fuel/{record_id}", json=body, headers=headers)


class TestUpdateKeepsAValidFillUp:
    async def test_emptying_a_propane_refill_is_refused(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        record = await _create(client, auth_headers, vin, propane_liters=30.0)

        r = await _put(client, auth_headers, vin, record["id"], {"propane_liters": None})

        assert r.status_code == 422, r.text
        reread = await client.get(f"/api/vehicles/{vin}/fuel/{record['id']}", headers=auth_headers)
        assert float(reread.json()["propane_liters"]) == 30.0

    async def test_clearing_the_volume_of_a_fill_up_is_refused(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        record = await _create(client, auth_headers, vin, odometer_km=5000, liters=40.0)

        r = await _put(client, auth_headers, vin, record["id"], {"liters": None})

        assert r.status_code == 422, r.text

    async def test_clearing_the_only_reading_is_refused(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        record = await _create(client, auth_headers, vin, odometer_km=5000, liters=40.0)

        r = await _put(client, auth_headers, vin, record["id"], {"odometer_km": None})

        assert r.status_code == 422, r.text

    async def test_clearing_the_odometer_with_engine_hours_left_is_fine(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        record = await _create(
            client, auth_headers, vin, odometer_km=5000, engine_hours=120.5, liters=40.0
        )

        r = await _put(client, auth_headers, vin, record["id"], {"odometer_km": None})

        assert r.status_code == 200, r.text
        assert r.json()["odometer_km"] is None

    async def test_a_legacy_record_can_still_have_its_notes_edited(
        self, client: AsyncClient, auth_headers, own_vehicle, db_session: AsyncSession
    ):
        """Already short of create's rule (an old import), and an API client's
        edit doesn't send the rule's fields at all."""
        vin = own_vehicle.vin
        legacy = FuelRecord(vin=vin, date=date(2032, 1, 11), cost=Decimal("20.00"))
        db_session.add(legacy)
        await db_session.commit()

        r = await _put(client, auth_headers, vin, legacy.id, {"notes": "found the receipt"})

        assert r.status_code == 200, r.text

    async def test_a_legacy_record_saves_from_the_form_when_the_rule_fields_are_unchanged(
        self, client: AsyncClient, auth_headers, own_vehicle, db_session: AsyncSession
    ):
        """The form sends every rule field on every save, unchanged or not. A
        webhook or pre-rule fill-up with a volume and no reading must still
        take a station or notes edit, or it could never be saved again."""
        vin = own_vehicle.vin
        legacy = FuelRecord(vin=vin, date=date(2032, 1, 12), liters=Decimal("40.000"))
        db_session.add(legacy)
        await db_session.commit()

        r = await _put(
            client,
            auth_headers,
            vin,
            legacy.id,
            {
                "odometer_km": None,
                "engine_hours": None,
                "liters": 40,
                "propane_liters": None,
                "kwh": None,
                "missed_fillup": False,
                "notes": "added the station",
            },
        )

        assert r.status_code == 200, r.text
        assert r.json()["notes"] == "added the station"
