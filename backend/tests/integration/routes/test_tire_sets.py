"""Tire sets: naming a seasonal set, and fitting it in one action.

D6 of the mount-period design: sets are UX grouping only. No calculation
depends on membership -- distance, wear and position all read
`tire_mount_periods`. A set exists so a user can say "Winter studded" and swap
four tires at once instead of doing eight operations by hand.

The table and the `tires.set_id` column shipped with migration 097 and then sat
there: there was no schema to create a set, no way to put a tire in one, and no
endpoint to fit one. This is that surface.

The interesting behaviour is all in the fit: where each tire goes is REMEMBERED
rather than asked for, and everything the incoming set displaces has to come off
in the same transaction.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.odometer import OdometerRecord
from app.models.tire import Tire
from app.models.vehicle import Vehicle

TODAY = date(2026, 4, 1)


def _vin(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10].upper()}".replace("I", "X")[:17].ljust(17, "0")


@pytest_asyncio.fixture
async def vehicle(db_session, test_user):
    """A vehicle of this file's own, with a distinctive make/model."""
    vin = _vin("TIRESET")
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Set Rig",
            vehicle_type="Car",
            year=2021,
            make="Volvo",
            model="XC60",
        )
    )
    await db_session.commit()
    yield vin
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


@pytest_asyncio.fixture
async def other_vehicle(db_session, test_user):
    """A second vehicle, for the cross-VIN refusals."""
    vin = _vin("TIRESETB")
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Set Rig B",
            vehicle_type="Car",
            year=2021,
            make="Volvo",
            model="V90",
        )
    )
    await db_session.commit()
    yield vin
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


async def _set(client: AsyncClient, headers, vin: str, name: str) -> dict:
    response = await client.post(
        f"/api/vehicles/{vin}/tire-sets", headers=headers, json={"name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _mount(client: AsyncClient, headers, vin: str, position: str, **extra) -> dict:
    body = {"vin": vin, "position": position, "tread_depth_mm": "8.0", **extra}
    response = await client.post(
        f"/api/vehicles/{vin}/tires/create-and-mount", headers=headers, json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _stored(client: AsyncClient, headers, vin: str, **extra) -> dict:
    response = await client.post(
        f"/api/vehicles/{vin}/tires", headers=headers, json={"vin": vin, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _assign(client: AsyncClient, headers, vin: str, tire_id: int, set_id: int | None):
    response = await client.put(
        f"/api/vehicles/{vin}/tires/{tire_id}", headers=headers, json={"set_id": set_id}
    )
    return response


@pytest.mark.asyncio
class TestSetCrud:
    async def test_create_list_rename_and_delete(self, client: AsyncClient, auth_headers, vehicle):
        created = await _set(client, auth_headers, vehicle, "Winter studded")
        assert created["name"] == "Winter studded"
        assert created["tire_ids"] == []

        listed = await client.get(f"/api/vehicles/{vehicle}/tire-sets", headers=auth_headers)
        assert listed.status_code == 200, listed.text
        assert [s["name"] for s in listed.json()["sets"]] == ["Winter studded"]

        renamed = await client.put(
            f"/api/vehicles/{vehicle}/tire-sets/{created['id']}",
            headers=auth_headers,
            json={"name": "Winter studded (Nokian)"},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["name"] == "Winter studded (Nokian)"

        removed = await client.delete(
            f"/api/vehicles/{vehicle}/tire-sets/{created['id']}", headers=auth_headers
        )
        assert removed.status_code == 204, removed.text
        emptied = await client.get(f"/api/vehicles/{vehicle}/tire-sets", headers=auth_headers)
        assert emptied.json()["sets"] == []

    async def test_deleting_a_set_keeps_its_tires(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """ON DELETE SET NULL, not CASCADE. A set is a label, not a container.

        Cascading here would mean renaming your winter set wrong once and then
        deleting it takes four tires and a season of readings with it.
        """
        winter = await _set(client, auth_headers, vehicle, "Winter")
        tire = await _stored(client, auth_headers, vehicle, brand="Nokian")
        assert (
            await _assign(client, auth_headers, vehicle, tire["id"], winter["id"])
        ).status_code == 200

        await client.delete(
            f"/api/vehicles/{vehicle}/tire-sets/{winter['id']}", headers=auth_headers
        )

        stored = (
            await db_session.execute(select(Tire).where(Tire.id == tire["id"]))
        ).scalar_one_or_none()
        assert stored is not None
        assert stored.set_id is None

    async def test_a_set_lists_its_tires(self, client: AsyncClient, auth_headers, vehicle):
        winter = await _set(client, auth_headers, vehicle, "Winter")
        first = await _stored(client, auth_headers, vehicle, brand="Nokian")
        second = await _stored(client, auth_headers, vehicle, brand="Nokian")
        for tire in (first, second):
            await _assign(client, auth_headers, vehicle, tire["id"], winter["id"])

        listed = await client.get(f"/api/vehicles/{vehicle}/tire-sets", headers=auth_headers)
        row = listed.json()["sets"][0]
        assert sorted(row["tire_ids"]) == sorted([first["id"], second["id"]])
        assert row["mounted_count"] == 0


@pytest.mark.asyncio
class TestSetsAreScopedToTheirVehicle:
    """`tires.set_id` carries NO database constraint against the tire's vin.

    The design says so deliberately: a set is UX grouping no calculation
    depends on, so it is not worth a composite FK. That makes the service the
    only thing standing between a user and a tire filed under another
    vehicle's set, which is why it gets a test of its own.
    """

    async def test_a_tire_cannot_join_another_vehicles_set(
        self, client: AsyncClient, auth_headers, vehicle, other_vehicle
    ):
        theirs = await _set(client, auth_headers, other_vehicle, "Not mine")
        tire = await _stored(client, auth_headers, vehicle, brand="Nokian")

        response = await _assign(client, auth_headers, vehicle, tire["id"], theirs["id"])
        assert response.status_code == 404, response.text

    async def test_another_vehicles_set_cannot_be_renamed_through_this_vin(
        self, client: AsyncClient, auth_headers, vehicle, other_vehicle
    ):
        theirs = await _set(client, auth_headers, other_vehicle, "Not mine")
        response = await client.put(
            f"/api/vehicles/{vehicle}/tire-sets/{theirs['id']}",
            headers=auth_headers,
            json={"name": "Mine now"},
        )
        assert response.status_code == 404, response.text


@pytest.mark.asyncio
class TestFittingASet:
    """The one action that replaces eight."""

    async def test_each_tire_goes_back_where_it_last_was(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """Position is REMEMBERED, from each tire's own mount history.

        A seasonal set has been on this car before, and the periods already
        record which corner each tire sat on. Asking again would be asking the
        user to retype something the app knows.
        """
        summer = await _set(client, auth_headers, vehicle, "Summer")
        winter = await _set(client, auth_headers, vehicle, "Winter")

        # The winter set, mounted once and taken off: that is the history the
        # fit reads back.
        winter_tires = {}
        for position in ("FL", "FR"):
            tire = await _mount(
                client,
                auth_headers,
                vehicle,
                position,
                brand=f"Nokian {position}",
                mounted_on="2026-01-05",
                mounted_odometer_km="10000",
            )
            await _assign(client, auth_headers, vehicle, tire["id"], winter["id"])
            winter_tires[position] = tire["id"]
            dismounted = await client.post(
                f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
                headers=auth_headers,
                json={"dismounted_on": "2026-03-01", "dismounted_odometer_km": "16000"},
            )
            assert dismounted.status_code == 200, dismounted.text

        # The summer set is on the car now.
        summer_tires = {}
        for position in ("FL", "FR"):
            tire = await _mount(
                client,
                auth_headers,
                vehicle,
                position,
                brand=f"Michelin {position}",
                mounted_on="2026-03-01",
                mounted_odometer_km="16000",
            )
            await _assign(client, auth_headers, vehicle, tire["id"], summer["id"])
            summer_tires[position] = tire["id"]

        fitted = await client.post(
            f"/api/vehicles/{vehicle}/tire-sets/{winter['id']}/mount",
            headers=auth_headers,
            json={"mounted_on": TODAY.isoformat(), "odometer_km": "24000"},
        )
        assert fitted.status_code == 200, fitted.text

        by_id = {t["id"]: t for t in fitted.json()["tires"]}
        assert by_id[winter_tires["FL"]]["position"] == "FL"
        assert by_id[winter_tires["FR"]]["position"] == "FR"
        # And what they displaced came off in the same operation.
        assert by_id[summer_tires["FL"]]["position"] is None
        assert by_id[summer_tires["FR"]]["position"] is None

    async def test_the_displaced_set_keeps_a_bounded_period(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The swap's odometer closes the outgoing periods as well as opening
        the incoming ones. A dismount with no closing bound is a period whose
        distance can never be computed, which is the dead end the whole release
        exists to get out of."""
        winter = await _set(client, auth_headers, vehicle, "Winter")
        old = await _mount(
            client,
            auth_headers,
            vehicle,
            "RL",
            brand="Outgoing",
            mounted_on="2026-01-01",
            mounted_odometer_km="5000",
        )
        incoming = await _mount(
            client,
            auth_headers,
            vehicle,
            "RR",
            brand="Incoming",
            mounted_on="2025-01-01",
            mounted_odometer_km="1000",
        )
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{incoming['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2025-06-01", "dismounted_odometer_km": "4000"},
        )
        await _assign(client, auth_headers, vehicle, incoming["id"], winter["id"])

        # The incoming tire remembers RR, which is free, so `old` at RL is not
        # displaced -- the fit only touches the corners it needs.
        fitted = await client.post(
            f"/api/vehicles/{vehicle}/tire-sets/{winter['id']}/mount",
            headers=auth_headers,
            json={"mounted_on": TODAY.isoformat(), "odometer_km": "24000"},
        )
        assert fitted.status_code == 200, fitted.text
        by_id = {t["id"]: t for t in fitted.json()["tires"]}
        assert by_id[incoming["id"]]["position"] == "RR"
        assert by_id[old["id"]]["position"] == "RL"

        # One reading for the whole swap, like a rotation: the odometer is a
        # fact about the vehicle, not about each corner.
        rows = (
            (
                await db_session.execute(
                    select(OdometerRecord).where(
                        OdometerRecord.vin == vehicle, OdometerRecord.date == TODAY
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].odometer_km == 24000

    async def test_a_tire_that_has_never_been_mounted_refuses_the_fit(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """Named, and nothing is written.

        A brand-new set entered into storage has no history to read a corner
        from. Guessing one would put a tire somewhere the user did not choose,
        and doing three of four would leave an arrangement nobody asked for.
        """
        winter = await _set(client, auth_headers, vehicle, "Winter")
        known = await _mount(
            client, auth_headers, vehicle, "FL", brand="Known", mounted_odometer_km="1000"
        )
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{known['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_odometer_km": "2000"},
        )
        fresh = await _stored(client, auth_headers, vehicle, brand="NeverFitted")
        for tire in (known, fresh):
            await _assign(client, auth_headers, vehicle, tire["id"], winter["id"])

        response = await client.post(
            f"/api/vehicles/{vehicle}/tire-sets/{winter['id']}/mount",
            headers=auth_headers,
            json={"odometer_km": "24000"},
        )
        assert response.status_code == 409, response.text
        assert "NeverFitted" in response.text

        # All or nothing: the tire that DID have a corner stayed in storage.
        listed = await client.get(f"/api/vehicles/{vehicle}/tires", headers=auth_headers)
        by_id = {t["id"]: t for t in listed.json()["tires"]}
        assert by_id[known["id"]]["position"] is None

    async def test_two_tires_wanting_one_corner_refuses_the_fit(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """Two tires whose last corner was the same cannot both go back."""
        winter = await _set(client, auth_headers, vehicle, "Winter")
        for brand in ("First", "Second"):
            tire = await _mount(
                client, auth_headers, vehicle, "SPARE", brand=brand, mounted_odometer_km="1000"
            )
            await client.post(
                f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
                headers=auth_headers,
                json={"dismounted_odometer_km": "2000"},
            )
            await _assign(client, auth_headers, vehicle, tire["id"], winter["id"])

        response = await client.post(
            f"/api/vehicles/{vehicle}/tire-sets/{winter['id']}/mount",
            headers=auth_headers,
            json={"odometer_km": "24000"},
        )
        assert response.status_code == 409, response.text
        assert "SPARE" in response.text

    async def test_an_empty_set_refuses_the_fit(self, client: AsyncClient, auth_headers, vehicle):
        winter = await _set(client, auth_headers, vehicle, "Winter")
        response = await client.post(
            f"/api/vehicles/{vehicle}/tire-sets/{winter['id']}/mount",
            headers=auth_headers,
            json={"odometer_km": "24000"},
        )
        assert response.status_code == 409, response.text

    async def test_fitting_a_set_that_is_already_on_changes_nothing(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """A member already sitting on its own corner is left alone.

        Taking it off and putting it straight back would close a period and
        open an identical one, splitting the tire's history at a moment when
        nothing happened to it -- and the two fragments would each be bounded
        by the same odometer, so the split leg would read as 0 km driven.
        """
        winter = await _set(client, auth_headers, vehicle, "Winter")
        tire = await _mount(
            client, auth_headers, vehicle, "FL", brand="Nokian", mounted_odometer_km="1000"
        )
        await _assign(client, auth_headers, vehicle, tire["id"], winter["id"])

        first = await client.post(
            f"/api/vehicles/{vehicle}/tire-sets/{winter['id']}/mount",
            headers=auth_headers,
            json={"mounted_on": TODAY.isoformat(), "odometer_km": "24000"},
        )
        assert first.status_code == 200, first.text
        periods = first.json()["tires"][0]["mount_periods"]
        assert len(periods) == 1, periods
        assert periods[0]["dismounted_on"] is None

    async def test_the_most_recently_recorded_corner_wins(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """A tire that has been on two corners goes back to the later one.

        And "later" means most recently RECORDED, not the largest
        `mounted_on`: the period entered second below is BACKDATED to 2024,
        before the first one, so a rule that read dates would send this tire to
        FL. Someone filling in last winter's history must not have that
        backfill outrank the corner the tire actually came off.
        """
        winter = await _set(client, auth_headers, vehicle, "Winter")
        tire = await _mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            brand="TwoCorners",
            mounted_on="2026-01-01",
            mounted_odometer_km="1000",
        )
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-02-01", "dismounted_odometer_km": "2000"},
        )
        remount = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/mount",
            headers=auth_headers,
            json={"position": "RR", "mounted_on": "2024-01-01", "mounted_odometer_km": "500"},
        )
        assert remount.status_code == 200, remount.text
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2024-06-01", "dismounted_odometer_km": "800"},
        )
        await _assign(client, auth_headers, vehicle, tire["id"], winter["id"])

        fitted = await client.post(
            f"/api/vehicles/{vehicle}/tire-sets/{winter['id']}/mount",
            headers=auth_headers,
            json={"mounted_on": TODAY.isoformat(), "odometer_km": "24000"},
        )
        assert fitted.status_code == 200, fitted.text
        placed = {t["id"]: t["position"] for t in fitted.json()["tires"]}
        assert placed[tire["id"]] == "RR"

    async def test_a_retired_member_leaves_the_sets_membership(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """The set listing counts live tires only.

        A retired member left in `tire_ids` would offer to fit a tire the user
        has thrown away, and "3 of 4 fitted" would never reach 4.
        """
        winter = await _set(client, auth_headers, vehicle, "Winter")
        keeper = await _mount(
            client, auth_headers, vehicle, "FL", brand="Keeper", mounted_odometer_km="1000"
        )
        goner = await _mount(
            client, auth_headers, vehicle, "FR", brand="Goner", mounted_odometer_km="1000"
        )
        for tire in (keeper, goner):
            await _assign(client, auth_headers, vehicle, tire["id"], winter["id"])

        before = await client.get(f"/api/vehicles/{vehicle}/tire-sets", headers=auth_headers)
        assert before.json()["sets"][0]["mounted_count"] == 2

        await client.post(
            f"/api/vehicles/{vehicle}/tires/{goner['id']}/retire",
            headers=auth_headers,
            json={"dismounted_odometer_km": "2000"},
        )

        after = await client.get(f"/api/vehicles/{vehicle}/tire-sets", headers=auth_headers)
        row = after.json()["sets"][0]
        assert row["tire_ids"] == [keeper["id"]]
        assert row["mounted_count"] == 1

    async def test_a_retired_tire_is_not_fitted(self, client: AsyncClient, auth_headers, vehicle):
        """A retired tire is history, not inventory, so it is not in the set
        the fit operates on -- and it must not make the fit fail either."""
        winter = await _set(client, auth_headers, vehicle, "Winter")
        keeper = await _mount(
            client, auth_headers, vehicle, "FL", brand="Keeper", mounted_odometer_km="1000"
        )
        goner = await _mount(
            client, auth_headers, vehicle, "FR", brand="Goner", mounted_odometer_km="1000"
        )
        for tire in (keeper, goner):
            await _assign(client, auth_headers, vehicle, tire["id"], winter["id"])
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{keeper['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_odometer_km": "2000"},
        )
        retired = await client.post(
            f"/api/vehicles/{vehicle}/tires/{goner['id']}/retire",
            headers=auth_headers,
            json={"dismounted_odometer_km": "2000"},
        )
        assert retired.status_code == 200, retired.text

        fitted = await client.post(
            f"/api/vehicles/{vehicle}/tire-sets/{winter['id']}/mount",
            headers=auth_headers,
            json={"odometer_km": "24000"},
        )
        assert fitted.status_code == 200, fitted.text
        by_id = {t["id"]: t for t in fitted.json()["tires"]}
        assert by_id[keeper["id"]]["position"] == "FL"
        assert goner["id"] not in by_id
