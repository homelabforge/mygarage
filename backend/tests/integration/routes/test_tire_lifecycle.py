"""Mounting, rotating, retiring and deleting a tire.

The distinction this file is mostly about: **retiring a tire is not deleting
it**. This release is the one that makes tire history worth keeping, and the
ordinary act of replacing a worn tire was a hard DELETE that cascaded through
every reading and every mount period. Shipping the mount-period model beside an
unchanged delete would mean the first thing a user does after collecting a
season of data is erase it.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.reminder import Reminder
from app.models.tire import Tire, TireMountPeriod, TireReading
from app.models.vehicle import Vehicle
from app.services import tire_service as tire_service_module


@pytest_asyncio.fixture
async def vehicle(db_session, test_user):
    """A vehicle for this test alone, cleaned up afterwards.

    Positions are claimable once per vehicle now, so a shared VIN would make
    these tests order-dependent; and leaving vehicles behind breaks a
    paginated assertion in test_vehicle.py.
    """
    vin = f"TIRELIFE{uuid.uuid4().hex[:9].upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Lifecycle",
            vehicle_type="Car",
            year=2020,
            make="Honda",
            model="Accord",
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
class TestMountAndDismount:
    async def test_dismounting_frees_the_corner_and_keeps_the_tire(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire = await _mount(client, auth_headers, vehicle, "FL")

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_odometer_km": "15000"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["position"] is None

        # The tire still exists, with its history.
        stored = (await db_session.execute(select(Tire).where(Tire.id == tire["id"]))).scalar_one()
        assert stored.position is None
        periods = (
            (
                await db_session.execute(
                    select(TireMountPeriod).where(TireMountPeriod.tire_id == tire["id"])
                )
            )
            .scalars()
            .all()
        )
        assert len(periods) == 1
        assert periods[0].dismounted_on is not None

        # And the corner is free for another tire.
        await _mount(client, auth_headers, vehicle, "FL")

    async def test_two_tires_cannot_hold_one_corner(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        await _mount(client, auth_headers, vehicle, "FR")
        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "FR", "tread_depth_mm": "8.0"},
        )
        assert response.status_code == 409, response.text

    async def test_a_failed_create_and_mount_leaves_no_orphan_tire(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The reason create-and-mount is one operation.

        A caller doing create-then-mount by hand and losing the mount would be
        left with a tire it did not ask for and cannot see.
        """
        await _mount(client, auth_headers, vehicle, "RL")
        before = len(
            (await db_session.execute(select(Tire).where(Tire.vin == vehicle))).scalars().all()
        )
        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "RL", "brand": "Orphan"},
        )
        assert response.status_code == 409
        after = (await db_session.execute(select(Tire).where(Tire.vin == vehicle))).scalars().all()
        assert len(after) == before
        assert not any(t.brand == "Orphan" for t in after)

    async def test_mounting_an_already_mounted_tire_is_refused(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire = await _mount(client, auth_headers, vehicle, "RR")
        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/mount",
            headers=auth_headers,
            json={"position": "SPARE"},
        )
        assert response.status_code == 409, response.text

    async def test_a_stored_tire_can_be_remounted_elsewhere(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The seasonal-swap case the whole model exists for: a tire comes off
        in autumn and goes back on in spring, keeping its history.

        Dated a season apart, as a seasonal swap is: each event then publishes
        the vehicle's odometer onto a day of its own."""
        tire = await _mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on="2025-04-01",
            mounted_odometer_km="1000",
        )
        dismounted = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2025-10-01", "dismounted_odometer_km": "9000"},
        )
        assert dismounted.status_code == 200, dismounted.text
        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/mount",
            headers=auth_headers,
            json={"position": "FR", "mounted_on": "2026-04-01", "mounted_odometer_km": "12000"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["position"] == "FR"

        periods = (
            (
                await db_session.execute(
                    select(TireMountPeriod)
                    .where(TireMountPeriod.tire_id == tire["id"])
                    .order_by(TireMountPeriod.id)
                )
            )
            .scalars()
            .all()
        )
        assert [p.position for p in periods] == ["FL", "FR"]
        # 8,000 km on the first period. The 3,000 km the vehicle drove while
        # this tire was in storage is NOT credited to it -- that is the whole
        # defect this release fixes.
        assert response.json()["distance_status"] == "complete"
        assert Decimal(response.json()["distance_km"]) == Decimal("8000")


@pytest.mark.asyncio
class TestDeleteAndRetire:
    async def test_deleting_a_tire_with_a_reminder_succeeds(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The composite FK carries no ON DELETE action on purpose.

        SET NULL would try to null `vin` too -- a referential action applies to
        every column in the FK -- and `vehicle_reminders.vin` is NOT NULL, so
        SQLite rejects the delete outright and retiring a tire becomes
        impossible. The service nulls `tire_id` explicitly instead.
        """
        tire = await _mount(
            client, auth_headers, vehicle, "FL", tread_depth_mm="1.0", min_tread_mm="3.0"
        )
        reminders = (
            (await db_session.execute(select(Reminder).where(Reminder.vin == vehicle)))
            .scalars()
            .all()
        )
        assert reminders, "a tire below its threshold should have raised a reminder"

        response = await client.delete(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}", headers=auth_headers
        )
        assert response.status_code in (200, 204), response.text

        # The reminder survives as history, detached from the deleted tire.
        await db_session.commit()
        surviving = (
            (await db_session.execute(select(Reminder).where(Reminder.vin == vehicle)))
            .scalars()
            .all()
        )
        assert surviving, "deleting a tire must not erase the record that it was flagged"
        assert all(r.tire_id is None for r in surviving)

    async def test_retiring_keeps_every_reading_and_period(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The ordinary act of replacing a worn tire.

        Before this release it was a hard DELETE that cascaded through the
        readings and mount periods -- erasing exactly the history the mount
        period model exists to collect.
        """
        tire = await _mount(client, auth_headers, vehicle, "FL", mounted_odometer_km="1000")
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-03-01", "tread_depth_mm": "5.0"},
        )

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/retire",
            headers=auth_headers,
            json={"dismounted_odometer_km": "20000"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["retired_on"] is not None
        assert body["position"] is None, "a retired tire is not on the vehicle"

        readings = (
            (await db_session.execute(select(TireReading).where(TireReading.tire_id == tire["id"])))
            .scalars()
            .all()
        )
        assert len(readings) == 1, "retiring must not erase readings"
        periods = (
            (
                await db_session.execute(
                    select(TireMountPeriod).where(TireMountPeriod.tire_id == tire["id"])
                )
            )
            .scalars()
            .all()
        )
        assert len(periods) == 1
        assert periods[0].dismounted_on is not None, "retiring closes the open period"

    async def test_a_retired_tire_is_out_of_the_default_list(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire = await _mount(client, auth_headers, vehicle, "FL")
        await _mount(client, auth_headers, vehicle, "FR")
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/retire",
            headers=auth_headers,
            json={},
        )

        listed = await client.get(f"/api/vehicles/{vehicle}/tires", headers=auth_headers)
        assert listed.status_code == 200
        ids = [t["id"] for t in listed.json()["tires"]]
        assert tire["id"] not in ids

        # But it is still there when asked for.
        with_retired = await client.get(
            f"/api/vehicles/{vehicle}/tires?include_retired=true", headers=auth_headers
        )
        assert with_retired.status_code == 200
        assert tire["id"] in [t["id"] for t in with_retired.json()["tires"]]

    async def test_retiring_frees_the_corner(self, client: AsyncClient, auth_headers, vehicle):
        """The replacement goes where the old one was."""
        tire = await _mount(client, auth_headers, vehicle, "FL")
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/retire",
            headers=auth_headers,
            json={},
        )
        await _mount(client, auth_headers, vehicle, "FL")


@pytest.mark.asyncio
class TestRotation:
    """A rotation moves several tires at once, and the order matters.

    `uq_tires_vin_position` is an IMMEDIATE unique index on both dialects, so
    moving FL to FR before FR has vacated violates it -- an X-pattern rotation
    fails even though the requested FINAL arrangement is perfectly legal. The
    service clears every affected position first, flushes, then assigns.
    """

    async def test_a_front_to_back_swap(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        fl = await _mount(client, auth_headers, vehicle, "FL", mounted_odometer_km="1000")
        rl = await _mount(client, auth_headers, vehicle, "RL", mounted_odometer_km="1000")

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/rotate",
            headers=auth_headers,
            json={
                "odometer_km": "20000",
                "moves": [
                    {"tire_id": fl["id"], "position": "RL"},
                    {"tire_id": rl["id"], "position": "FL"},
                ],
            },
        )
        assert response.status_code == 200, response.text

        tires = {t["id"]: t for t in response.json()["tires"]}
        assert tires[fl["id"]]["position"] == "RL"
        assert tires[rl["id"]]["position"] == "FL"

    async def test_an_x_pattern_rotation_does_not_trip_the_unique_index(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """The case that fails without the two-phase write.

        Every tire moves and every target is currently occupied, so a
        naive one-at-a-time assignment collides on the first move.
        """
        corners = {}
        for position in ("FL", "FR", "RL", "RR"):
            corners[position] = await _mount(
                client, auth_headers, vehicle, position, mounted_odometer_km="1000"
            )

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/rotate",
            headers=auth_headers,
            json={
                "odometer_km": "20000",
                "moves": [
                    {"tire_id": corners["FL"]["id"], "position": "RR"},
                    {"tire_id": corners["FR"]["id"], "position": "RL"},
                    {"tire_id": corners["RL"]["id"], "position": "FR"},
                    {"tire_id": corners["RR"]["id"], "position": "FL"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        placed = {t["id"]: t["position"] for t in response.json()["tires"]}
        assert placed[corners["FL"]["id"]] == "RR"
        assert placed[corners["RR"]["id"]] == "FL"

    async def test_rotation_closes_and_opens_periods(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """A rotation is a dismount and a remount, so the distance at each
        corner stays attributable."""
        fl = await _mount(client, auth_headers, vehicle, "FL", mounted_odometer_km="1000")
        rl = await _mount(client, auth_headers, vehicle, "RL", mounted_odometer_km="1000")

        await client.post(
            f"/api/vehicles/{vehicle}/tires/rotate",
            headers=auth_headers,
            json={
                "odometer_km": "20000",
                "moves": [
                    {"tire_id": fl["id"], "position": "RL"},
                    {"tire_id": rl["id"], "position": "FL"},
                ],
            },
        )

        periods = (
            (
                await db_session.execute(
                    select(TireMountPeriod)
                    .where(TireMountPeriod.tire_id == fl["id"])
                    .order_by(TireMountPeriod.id)
                )
            )
            .scalars()
            .all()
        )
        assert [p.position for p in periods] == ["FL", "RL"]
        assert periods[0].dismounted_odometer_km == Decimal("20000")
        assert periods[1].mounted_odometer_km == Decimal("20000")

    async def test_a_rotation_onto_an_unmoved_tire_is_refused(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """Moving FL to FR while FR stays put is a conflict, not a swap.

        Refused as a whole: a partial rotation would leave the vehicle in a
        state the user did not ask for and cannot easily read back.
        """
        fl = await _mount(client, auth_headers, vehicle, "FL")
        await _mount(client, auth_headers, vehicle, "FR")

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/rotate",
            headers=auth_headers,
            json={"moves": [{"tire_id": fl["id"], "position": "FR"}]},
        )
        assert response.status_code == 409, response.text

    async def test_nothing_moves_when_one_move_is_invalid(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Atomicity. Guards the guard on the two-phase write: a rotation that
        applied its valid moves and rejected the rest would pass the conflict
        test above while corrupting the vehicle."""
        fl = await _mount(client, auth_headers, vehicle, "FL")
        rl = await _mount(client, auth_headers, vehicle, "RL")

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/rotate",
            headers=auth_headers,
            json={
                "moves": [
                    {"tire_id": fl["id"], "position": "RL"},
                    {"tire_id": 999999, "position": "FL"},
                ]
            },
        )
        assert response.status_code == 404, response.text

        await db_session.commit()
        listed = await client.get(f"/api/vehicles/{vehicle}/tires", headers=auth_headers)
        placed = {t["id"]: t["position"] for t in listed.json()["tires"]}
        assert placed[fl["id"]] == "FL", "a refused rotation must move nothing"
        assert placed[rl["id"]] == "RL"


@pytest.mark.asyncio
class TestStorageLocation:
    async def test_storage_location_round_trips_and_survives_a_mount(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            base,
            headers=auth_headers,
            json={"vin": vehicle, "brand": "Nokian", "storage_location": "Garage shelf B"},
        )
        assert made.status_code == 201, made.text
        tire = made.json()
        assert tire["storage_location"] == "Garage shelf B"

        edited = await client.put(
            f"{base}/{tire['id']}", headers=auth_headers, json={"storage_location": "Basement"}
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["storage_location"] == "Basement"

        mounted = await client.post(
            f"{base}/{tire['id']}/mount", headers=auth_headers, json={"position": "FL"}
        )
        assert mounted.status_code == 200, mounted.text
        assert mounted.json()["storage_location"] == "Basement", (
            "a mount never clears where the tire goes back to"
        )

        off = await client.post(
            f"{base}/{tire['id']}/dismount", headers=auth_headers, json={"storage_location": "Shed"}
        )
        assert off.status_code == 200, off.text
        assert off.json()["storage_location"] == "Shed"

        # A PUT that omits storage_location must leave it unchanged. Without
        # exclude_unset, an unrelated edit would silently clear it to the field's
        # Pydantic default (None).
        unrelated_edit = await client.put(
            f"{base}/{tire['id']}", headers=auth_headers, json={"notes": "unrelated edit"}
        )
        assert unrelated_edit.status_code == 200, unrelated_edit.text
        assert unrelated_edit.json()["storage_location"] == "Shed", (
            "a PUT omitting storage_location must leave the stored location unchanged"
        )

        # An empty string clears; an absent key would have left "Shed" alone.
        cleared = await client.put(
            f"{base}/{tire['id']}", headers=auth_headers, json={"storage_location": ""}
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["storage_location"] is None

    async def test_every_writer_normalises_it_the_same_way(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """Stripped, and blank is no location, on all four paths that take one.

        The two creates stored it as sent while the edit and the dismount
        stripped it, so the same padded text read back differently depending on
        which form had saved it. The frontend trims, so only the API saw it.
        """
        base = f"/api/vehicles/{vehicle}/tires"
        stored = await client.post(
            base, headers=auth_headers, json={"vin": vehicle, "storage_location": "  Shelf B  "}
        )
        assert stored.status_code == 201, stored.text
        assert stored.json()["storage_location"] == "Shelf B"

        blank = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "FR", "storage_location": "   "},
        )
        assert blank.status_code == 201, blank.text
        assert blank.json()["storage_location"] is None
        padded = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "RL", "storage_location": " Loft "},
        )
        assert padded.status_code == 201, padded.text
        assert padded.json()["storage_location"] == "Loft"

        tire_id = stored.json()["id"]
        edited = await client.put(
            f"{base}/{tire_id}", headers=auth_headers, json={"storage_location": "  Basement "}
        )
        assert edited.json()["storage_location"] == "Basement"
        mounted = await client.post(
            f"{base}/{tire_id}/mount", headers=auth_headers, json={"position": "FL"}
        )
        assert mounted.status_code == 200, mounted.text
        off = await client.post(
            f"{base}/{tire_id}/dismount", headers=auth_headers, json={"storage_location": " Shed  "}
        )
        assert off.status_code == 200, off.text
        assert off.json()["storage_location"] == "Shed"

    async def test_retire_applies_a_location_it_is_sent_and_keeps_one_it_is_not(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """Retire takes the dismount body, which carries `storage_location`, and
        used to drop it. The Retire dialog renders no location field, so an
        absent key must leave the tire's location as it was."""
        base = f"/api/vehicles/{vehicle}/tires"
        sent = await _mount(client, auth_headers, vehicle, "FL", storage_location="Shelf A")
        retired = await client.post(
            f"{base}/{sent['id']}/retire",
            headers=auth_headers,
            json={"storage_location": "  Scrap pile "},
        )
        assert retired.status_code == 200, retired.text
        assert retired.json()["storage_location"] == "Scrap pile"

        absent = await _mount(client, auth_headers, vehicle, "FR", storage_location="Shelf B")
        kept = await client.post(f"{base}/{absent['id']}/retire", headers=auth_headers, json={})
        assert kept.status_code == 200, kept.text
        assert kept.json()["storage_location"] == "Shelf B"

    async def test_storage_location_is_capped(self, client: AsyncClient, auth_headers, vehicle):
        made = await client.post(
            f"/api/vehicles/{vehicle}/tires",
            headers=auth_headers,
            json={"vin": vehicle, "storage_location": "x" * 121},
        )
        assert made.status_code == 422, made.text


@pytest.mark.asyncio
class TestRestore:
    async def test_restore_puts_a_retired_tire_back_in_storage_with_its_history(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        # mounted_on pinned before the reading's date: left out, mounted_on
        # defaults to today (utc_now().date()), which in
        # this run postdates "2026-02-01" and makes the reading look like it
        # precedes the mount with a HIGHER odometer -- a genuine contradiction
        # (refuse_contradictions correctly 409s "run backwards"), not the
        # restore behaviour this test exists to check. Deviation recorded in
        # the task report.
        tire = await _mount(
            client, auth_headers, vehicle, "FL", mounted_on="2026-01-01", mounted_odometer_km="1000"
        )
        r = await client.post(
            f"{base}/{tire['id']}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-02-01", "tread_depth_mm": "7.0", "odometer_km": "1500"},
        )
        assert r.status_code == 201, r.text
        assert (
            await client.post(
                f"{base}/{tire['id']}/retire",
                headers=auth_headers,
                json={"dismounted_odometer_km": "2000"},
            )
        ).status_code == 200

        restored = await client.post(f"{base}/{tire['id']}/restore", headers=auth_headers)
        assert restored.status_code == 200, restored.text
        body = restored.json()
        assert body["retired_on"] is None and body["position"] is None
        assert len(body["readings"]) == 1 and len(body["mount_periods"]) == 1
        # Back in inventory, so the default list has it again.
        listed = await client.get(base, headers=auth_headers)
        assert tire["id"] in [t["id"] for t in listed.json()["tires"]]
        # And mountable again.
        assert (
            await client.post(
                f"{base}/{tire['id']}/mount", headers=auth_headers, json={"position": "FR"}
            )
        ).status_code == 200

    async def test_restoring_a_tire_that_is_not_retired_is_refused(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire = await _mount(client, auth_headers, vehicle, "RL")
        r = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/restore", headers=auth_headers
        )
        assert r.status_code == 409, r.text

    async def test_restore_raises_no_reminder_and_a_remount_does(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """D3a: restore puts the tire in storage, where it has no low-tread reminder.

        It still runs the sync (`_reload_and_sync`), which keeps it clear. Putting
        the tire back on a corner below its minimum raises a fresh one.
        """
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "RR", "tread_depth_mm": "1.0", "min_tread_mm": "2.0"},
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        assert (
            await client.post(f"{base}/{tire_id}/retire", headers=auth_headers, json={})
        ).status_code == 200
        await db_session.execute(delete(Reminder).where(Reminder.tire_id == tire_id))
        await db_session.commit()

        assert (
            await client.post(f"{base}/{tire_id}/restore", headers=auth_headers)
        ).status_code == 200
        assert [
            r for r in await _low_tread_rows(db_session, vehicle) if r.status == "pending"
        ] == []

        assert (
            await client.post(
                f"{base}/{tire_id}/mount", headers=auth_headers, json={"position": "RL"}
            )
        ).status_code == 200
        pending = [r for r in await _low_tread_rows(db_session, vehicle) if r.status == "pending"]
        assert [(r.tire_id, r.title) for r in pending] == [(tire_id, "Tire tread low (RL)")]


async def _low_tread_rows(db_session, vin: str) -> list[Reminder]:
    """Every reminder on the vehicle, as the requests committed them."""
    db_session.expire_all()
    return list(
        (
            await db_session.execute(
                select(Reminder).where(Reminder.vin == vin).order_by(Reminder.id)
            )
        )
        .scalars()
        .all()
    )


async def _worn(client: AsyncClient, headers, vin: str, position: str, **extra) -> dict:
    """A tire mounted below its minimum, which raises its low-tread reminder."""
    return await _mount(
        client, headers, vin, position, tread_depth_mm="1.0", min_tread_mm="3.0", **extra
    )


@pytest.mark.asyncio
class TestTheLowTreadReminderFollowsTheTire:
    """D3a (NEW-1): a low-tread reminder lives only while its tire is mounted.

    Dismount, retire, rotate and delete never ran the sync, so the reminder
    stayed pending on a tire that was off the car, or kept the old corner.
    """

    async def test_dismount_closes_it_dismissed(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire = await _worn(client, auth_headers, vehicle, "FL")
        (raised,) = await _low_tread_rows(db_session, vehicle)
        assert raised.status == "pending"

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={},
        )
        assert response.status_code == 200, response.text

        (row,) = await _low_tread_rows(db_session, vehicle)
        assert (row.id, row.status, row.tire_id) == (raised.id, "dismissed", tire["id"])
        assert row.completed_at is None

    async def test_retire_closes_it_done_on_the_retire_date(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire = await _worn(client, auth_headers, vehicle, "FL", mounted_on="2026-03-01")
        (raised,) = await _low_tread_rows(db_session, vehicle)
        raised.snoozed_until = date(2026, 12, 1)
        await db_session.commit()

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/retire",
            headers=auth_headers,
            json={"dismounted_on": "2026-04-02"},
        )
        assert response.status_code == 200, response.text

        (row,) = await _low_tread_rows(db_session, vehicle)
        assert (row.id, row.status, row.completed_date) == (raised.id, "done", date(2026, 4, 2))
        assert row.completed_at is not None
        assert row.snoozed_until is None

    async def test_rotation_renames_it_to_the_new_corner(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        worn = await _worn(client, auth_headers, vehicle, "FL")
        other = await _mount(client, auth_headers, vehicle, "RL")
        (raised,) = await _low_tread_rows(db_session, vehicle)

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/rotate",
            headers=auth_headers,
            json={
                "moves": [
                    {"tire_id": worn["id"], "position": "RL"},
                    {"tire_id": other["id"], "position": "FL"},
                ]
            },
        )
        assert response.status_code == 200, response.text

        (row,) = await _low_tread_rows(db_session, vehicle)
        assert (row.id, row.status, row.title) == (raised.id, "pending", "Tire tread low (RL)")

    async def test_a_refused_rotation_keeps_the_reminder_as_it_was(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Control: passes on main by design, where the rotation writes no reminder.

        Pins that the sync's writes ride the rotation's transaction: the
        rotation is backdated before both mounts, so `refuse_contradictions`
        409s after the sync has renamed the reminder, and the rename must go
        with the rest. Proved by mutation: a commit inside the sync fails it.
        """
        worn = await _worn(client, auth_headers, vehicle, "FL", mounted_on="2026-03-01")
        other = await _mount(client, auth_headers, vehicle, "RL", mounted_on="2026-03-01")

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/rotate",
            headers=auth_headers,
            json={
                "rotated_on": "2026-02-01",
                "moves": [
                    {"tire_id": worn["id"], "position": "RL"},
                    {"tire_id": other["id"], "position": "FL"},
                ],
            },
        )
        assert response.status_code == 409, response.text

        (row,) = await _low_tread_rows(db_session, vehicle)
        assert (row.status, row.title) == ("pending", "Tire tread low (FL)")

    async def test_a_failing_sync_rolls_back_the_whole_rotation(
        self, client: AsyncClient, auth_headers, vehicle, db_session, monkeypatch
    ):
        """R1-F1: the second tire's sync raises after the first one's has written.

        Every position, period and reminder change goes with it.
        """
        worn = await _worn(client, auth_headers, vehicle, "FL")
        other = await _mount(client, auth_headers, vehicle, "RL")
        real = getattr(tire_service_module, "sync_low_tread_reminder", None)
        calls: list[int] = []

        async def second_one_fails(db, tire):
            calls.append(tire.id)
            if len(calls) == 2:
                raise RuntimeError("sync failed")
            assert real is not None
            return await real(db, tire)

        monkeypatch.setattr(
            tire_service_module, "sync_low_tread_reminder", second_one_fails, raising=False
        )

        with pytest.raises(RuntimeError, match="sync failed"):
            await client.post(
                f"/api/vehicles/{vehicle}/tires/rotate",
                headers=auth_headers,
                json={
                    "moves": [
                        {"tire_id": worn["id"], "position": "RL"},
                        {"tire_id": other["id"], "position": "FL"},
                    ]
                },
            )

        db_session.expire_all()
        placed = {
            t.id: t.position
            for t in (await db_session.execute(select(Tire).where(Tire.vin == vehicle))).scalars()
        }
        assert placed == {worn["id"]: "FL", other["id"]: "RL"}
        periods = (
            (
                await db_session.execute(
                    select(TireMountPeriod).where(
                        TireMountPeriod.tire_id.in_([worn["id"], other["id"]])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(periods) == 2
        assert all(p.dismounted_on is None for p in periods)
        (row,) = await _low_tread_rows(db_session, vehicle)
        assert (row.status, row.title) == ("pending", "Tire tread low (FL)")

    async def test_delete_dismisses_the_pending_one_and_detaches_every_row(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """F-14: a done row of the deleted tire is detached too.

        The composite FK carries no ON DELETE action, so a row still pointing
        at the tire would block the delete.
        """
        tire = await _worn(client, auth_headers, vehicle, "FL")
        for status in ("done", "dismissed"):
            db_session.add(
                Reminder(
                    vin=vehicle,
                    tire_id=tire["id"],
                    source="low_tread",
                    title="Tire tread low (FL)",
                    reminder_type="date",
                    due_date=date(2026, 1, 1),
                    status=status,
                )
            )
        await db_session.commit()

        response = await client.delete(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}", headers=auth_headers
        )
        assert response.status_code in (200, 204), response.text

        rows = await _low_tread_rows(db_session, vehicle)
        assert sorted(r.status for r in rows) == ["dismissed", "dismissed", "done"]
        assert all((r.tire_id, r.source) == (None, None) for r in rows)

    async def test_a_remount_below_the_minimum_raises_a_fresh_one(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Control: passes on main by design. The mount path already syncs.

        Main renames the reminder it left pending at the dismount; here the
        dismount closed that one, and the mount raises a new one.
        """
        tire = await _worn(client, auth_headers, vehicle, "FL")
        assert (
            await client.post(
                f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
                headers=auth_headers,
                json={},
            )
        ).status_code == 200
        assert (
            await client.post(
                f"/api/vehicles/{vehicle}/tires/{tire['id']}/mount",
                headers=auth_headers,
                json={"position": "FR"},
            )
        ).status_code == 200

        pending = [r for r in await _low_tread_rows(db_session, vehicle) if r.status == "pending"]
        assert [(r.tire_id, r.title) for r in pending] == [(tire["id"], "Tire tread low (FR)")]

    async def test_a_stored_tire_read_below_the_minimum_raises_none(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        response = await client.post(
            f"/api/vehicles/{vehicle}/tires",
            headers=auth_headers,
            json={"vin": vehicle, "tread_depth_mm": "8.0", "min_tread_mm": "3.0"},
        )
        assert response.status_code == 201, response.text
        tire_id = response.json()["id"]

        reading = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-03-01", "tread_depth_mm": "1.0"},
        )
        assert reading.status_code == 201, reading.text

        assert await _low_tread_rows(db_session, vehicle) == []
