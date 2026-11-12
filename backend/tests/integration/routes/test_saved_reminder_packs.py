"""Saving a vehicle's schedule as a reusable pack, and applying it back.

A pack item and a maintenance rule carry the same columns, so saving is a
projection of `vehicle_maintenance_rules` and applying feeds the existing
pipeline. What the columns do NOT capture is that the pipeline resolves an item
to a rule by `maintenance_type`, which is why a typeless rule and two rules of
one type are refused at save rather than silently reshaped. Most of this file is
that contract and the access rules around publishing a pack.
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder_pack import ReminderPack
from app.models.vehicle import Vehicle

PACKS = "/api/reminder-packs"
SOURCE_VIN = "PACKSRC0000000001"
TARGET_VIN = "PACKTGT0000000002"


@pytest_asyncio.fixture(autouse=True)
async def _clean_slate(db_session: AsyncSession):
    """Packs are instance-wide, so one left behind changes every other test's
    list and the next save's 409."""
    await db_session.execute(delete(ReminderPack))
    await db_session.commit()
    yield
    await db_session.execute(delete(ReminderPack))
    await db_session.execute(
        delete(MaintenanceRule).where(MaintenanceRule.vin.in_([SOURCE_VIN, TARGET_VIN]))
    )
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_([SOURCE_VIN, TARGET_VIN])))
    await db_session.commit()


async def _vehicle(client: AsyncClient, headers, vin: str, vehicle_type: str = "Truck") -> str:
    response = await client.post(
        "/api/vehicles",
        headers=headers,
        json={"vin": vin, "nickname": f"Pack {vin[-4:]}", "vehicle_type": vehicle_type},
    )
    assert response.status_code == 201, response.text
    return response.json()["vin"]


async def _rule(client: AsyncClient, headers, vin: str, **over) -> dict:
    body = {
        "maintenance_type": "engine_oil_filter",
        "title": "Oil & Filter Change",
        "interval_km": 8000,
        "interval_months": 6,
    } | over
    response = await client.post(
        f"/api/vehicles/{vin}/maintenance-rules", json=body, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _save(client: AsyncClient, headers, vin: str, rule_ids: list[int], **over) -> Response:
    body = {"vin": vin, "name": "Truck Standard", "rule_ids": rule_ids} | over
    return await client.post(PACKS, json=body, headers=headers)


@pytest.mark.integration
@pytest.mark.asyncio
class TestSavingAPack:
    async def test_a_saved_pack_round_trips_onto_another_vehicle(
        self, client: AsyncClient, auth_headers
    ):
        """The whole feature in one test: build a schedule once, reuse it."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        await _vehicle(client, auth_headers, TARGET_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        brakes = await _rule(
            client,
            auth_headers,
            SOURCE_VIN,
            maintenance_type="brake_fluid",
            title="Brake Fluid",
            interval_km=None,
            interval_months=24,
        )

        saved = await _save(client, auth_headers, SOURCE_VIN, [oil["id"], brakes["id"]])
        assert saved.status_code == 201, saved.text
        pack_id = saved.json()["id"]
        assert pack_id == "custom-truck-standard"

        applied = await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack",
            json={"pack_id": pack_id},
            headers=auth_headers,
        )
        assert applied.status_code == 201, applied.text

        rules = await client.get(
            f"/api/vehicles/{TARGET_VIN}/maintenance-rules", headers=auth_headers
        )
        copied = {r["maintenance_type"]: r for r in rules.json()}
        assert set(copied) == {"engine_oil_filter", "brake_fluid"}
        # Every interval, not just the row count: an unchecked interval is how a
        # round trip hides a unit or column bug.
        assert copied["engine_oil_filter"]["interval_km"] == "8000.00"
        assert copied["engine_oil_filter"]["interval_months"] == 6
        assert copied["brake_fluid"]["interval_km"] is None
        assert copied["brake_fluid"]["interval_months"] == 24
        assert copied["engine_oil_filter"]["title"] == "Oil & Filter Change"

    async def test_only_the_chosen_rules_enter_the_pack(self, client: AsyncClient, auth_headers):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        await _rule(
            client,
            auth_headers,
            SOURCE_VIN,
            maintenance_type="tire_rotation",
            title="Tire Rotation",
        )

        saved = await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])
        assert saved.status_code == 201, saved.text
        assert [i["maintenance_type"] for i in saved.json()["reminders"]] == ["engine_oil_filter"]

    async def test_a_rule_on_another_vehicle_is_refused_by_id(
        self, client: AsyncClient, auth_headers
    ):
        """Named, not skipped: a pack is visible to everyone, so a silent skip
        would let a caller probe for rules on vehicles they cannot see."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        await _vehicle(client, auth_headers, TARGET_VIN)
        mine = await _rule(client, auth_headers, SOURCE_VIN)
        theirs = await _rule(client, auth_headers, TARGET_VIN)

        refused = await _save(client, auth_headers, SOURCE_VIN, [mine["id"], theirs["id"]])
        assert refused.status_code == 422, refused.text
        assert str(theirs["id"]) in refused.json()["detail"]

    async def test_an_inactive_rule_is_refused(self, client: AsyncClient, auth_headers, db_session):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        row = await db_session.get(MaintenanceRule, oil["id"])
        row.is_active = False
        await db_session.commit()

        refused = await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])
        assert refused.status_code == 422, refused.text


@pytest.mark.integration
@pytest.mark.asyncio
class TestWhatAPackCannotRepresent:
    """The two limits the apply pipeline's type keying imposes.

    Neither is normalized quietly: `_plan_item` would retype a typeless item and
    `ensure_rule` would collapse a repeated type, so both are refused where the
    user can still do something about it.
    """

    async def test_a_typeless_rule_is_refused_with_its_reason(
        self, client: AsyncClient, auth_headers, db_session
    ):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        row = await db_session.get(MaintenanceRule, oil["id"])
        row.maintenance_type = None
        row.title = "Check the winch"
        await db_session.commit()

        refused = await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])
        assert refused.status_code == 422, refused.text
        # The REASON, not just the status: a bare 422 assertion passes if the
        # save breaks for any unrelated reason.
        detail = refused.json()["detail"]
        assert "no maintenance type" in detail
        assert "Check the winch" in detail

    async def test_two_rules_of_one_type_are_refused_together(
        self, client: AsyncClient, auth_headers
    ):
        """`create_rule` is what allows a second rule of a type; `ensure_rule`
        reuses by type, so both items would resolve to one rule on apply."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        first = await _rule(client, auth_headers, SOURCE_VIN)
        second = await _rule(
            client, auth_headers, SOURCE_VIN, title="Oil Change (winter)", interval_months=3
        )
        assert first["maintenance_type"] == second["maintenance_type"]

        refused = await _save(client, auth_headers, SOURCE_VIN, [first["id"], second["id"]])
        assert refused.status_code == 422, refused.text
        assert "engine_oil_filter" in refused.json()["detail"]

    async def test_one_rule_of_a_repeated_type_is_fine(self, client: AsyncClient, auth_headers):
        """The refusal is about the SELECTION, not the vehicle: picking one of
        the two is a pack that applies cleanly."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        first = await _rule(client, auth_headers, SOURCE_VIN)
        await _rule(client, auth_headers, SOURCE_VIN, title="Oil Change (winter)")

        saved = await _save(client, auth_headers, SOURCE_VIN, [first["id"]])
        assert saved.status_code == 201, saved.text

    async def test_applying_the_same_pack_twice_is_idempotent(
        self, client: AsyncClient, auth_headers
    ):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        await _vehicle(client, auth_headers, TARGET_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        saved = await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])
        pack_id = saved.json()["id"]

        for _ in range(2):
            applied = await client.post(
                f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack",
                json={"pack_id": pack_id},
                headers=auth_headers,
            )
            assert applied.status_code == 201, applied.text

        rules = await client.get(
            f"/api/vehicles/{TARGET_VIN}/maintenance-rules", headers=auth_headers
        )
        assert len(rules.json()) == 1


@pytest.mark.integration
@pytest.mark.asyncio
class TestNamingAndCollisions:
    async def test_a_name_with_no_letters_or_digits_is_refused(
        self, client: AsyncClient, auth_headers
    ):
        """Its slug would be empty, so its id would be a bare `custom-`: it
        would collide with the next such name and cannot be fetched by id."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        refused = await _save(client, auth_headers, SOURCE_VIN, [oil["id"]], name="???")
        assert refused.status_code == 422, refused.text

    async def test_a_blank_name_is_refused(self, client: AsyncClient, auth_headers):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        refused = await _save(client, auth_headers, SOURCE_VIN, [oil["id"]], name="   ")
        assert refused.status_code == 422, refused.text

    async def test_an_unknown_vehicle_type_is_refused(self, client: AsyncClient, auth_headers):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        refused = await _save(
            client, auth_headers, SOURCE_VIN, [oil["id"]], vehicle_types=["Spaceship"]
        )
        assert refused.status_code == 422, refused.text

    async def test_no_rules_at_all_is_refused(self, client: AsyncClient, auth_headers):
        """Blocked in the dialog too, but the dialog is not the only caller."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        refused = await _save(client, auth_headers, SOURCE_VIN, [])
        assert refused.status_code == 422, refused.text

    async def test_a_second_pack_of_the_same_name_is_a_conflict(
        self, client: AsyncClient, auth_headers
    ):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        assert (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).status_code == 201
        again = await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])
        assert again.status_code == 409, again.text


@pytest.mark.integration
@pytest.mark.asyncio
class TestChangingASavedPack:
    async def test_overwrite_replaces_everything_and_keeps_the_id(
        self, client: AsyncClient, auth_headers
    ):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        tires = await _rule(
            client,
            auth_headers,
            SOURCE_VIN,
            maintenance_type="tire_rotation",
            title="Tire Rotation",
        )
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).json()["id"]

        replaced = await client.put(
            f"{PACKS}/{pack_id}",
            json={
                "vin": SOURCE_VIN,
                "name": "Truck Standard",
                "description": "now with tires",
                "vehicle_types": ["Truck"],
                "rule_ids": [tires["id"]],
            },
            headers=auth_headers,
        )
        assert replaced.status_code == 200, replaced.text
        body = replaced.json()
        assert body["id"] == pack_id
        assert [i["maintenance_type"] for i in body["reminders"]] == ["tire_rotation"]
        assert body["description"] == "now with tires"
        assert body["vehicle_types"] == ["Truck"]

    async def test_overwrite_can_keep_a_maintenance_type_it_already_had(
        self, client: AsyncClient, auth_headers
    ):
        """The ordinary "save this vehicle over the pack again" case.

        `item_key` IS the maintenance type, so a retained type means the new row
        and the row it replaces share `(pack_id, item_key)`. SQLAlchemy orders the
        INSERTs before the delete-orphan DELETEs, so the unique constraint fires
        and a 500 comes back. The test above replaces oil with tires, a completely
        different key, which is why it never saw this.
        """
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        tires = await _rule(
            client,
            auth_headers,
            SOURCE_VIN,
            maintenance_type="tire_rotation",
            title="Tire Rotation",
        )
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).json()["id"]

        again = await client.put(
            f"{PACKS}/{pack_id}",
            json={
                "vin": SOURCE_VIN,
                "name": "Truck Standard",
                "description": "oil kept, tires added",
                "vehicle_types": ["Truck"],
                "rule_ids": [oil["id"], tires["id"]],
            },
            headers=auth_headers,
        )
        assert again.status_code == 200, again.text
        assert sorted(i["maintenance_type"] for i in again.json()["reminders"]) == [
            "engine_oil_filter",
            "tire_rotation",
        ]

    async def test_overwriting_with_the_identical_contents_is_not_an_error(
        self, client: AsyncClient, auth_headers
    ):
        """The narrowest form of the same bug: every key is retained."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).json()["id"]

        again = await client.put(
            f"{PACKS}/{pack_id}",
            json={
                "vin": SOURCE_VIN,
                "name": "Truck Standard",
                "description": "",
                "vehicle_types": ["Truck"],
                "rule_ids": [oil["id"]],
            },
            headers=auth_headers,
        )
        assert again.status_code == 200, again.text
        assert [i["maintenance_type"] for i in again.json()["reminders"]] == ["engine_oil_filter"]

    async def test_rename_returns_the_packs_items(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """The endpoint answers a full `ReminderPackDetail`, so it has to carry
        the reminders. Renaming does not touch them, and a client that re-renders
        from this response would blank the pack's contents on screen.

        ★ `expunge_all` IS THE TEST. Every request in this fixture shares one
        session, so the pack saved two lines up is still in the identity map with
        its items loaded, and a later query that skips loading them cannot empty
        a collection that is already populated. Production gives each request a
        FRESH session, where nothing is loaded unless the query loads it. Without
        this line the test passes against the bug.
        """
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).json()["id"]
        db_session.expunge_all()

        renamed = await client.patch(
            f"{PACKS}/{pack_id}", json={"name": "Fleet Standard"}, headers=auth_headers
        )
        assert renamed.status_code == 200, renamed.text
        assert [i["maintenance_type"] for i in renamed.json()["reminders"]] == ["engine_oil_filter"]

    async def test_rename_keeps_the_id_so_rules_still_resolve(
        self, client: AsyncClient, auth_headers, db_session
    ):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        await _vehicle(client, auth_headers, TARGET_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).json()["id"]
        await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack",
            json={"pack_id": pack_id},
            headers=auth_headers,
        )

        renamed = await client.patch(
            f"{PACKS}/{pack_id}", json={"name": "Fleet Standard"}, headers=auth_headers
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["id"] == pack_id
        assert renamed.json()["name"] == "Fleet Standard"

        result = await db_session.execute(
            select(MaintenanceRule.source_pack_id).where(MaintenanceRule.vin == TARGET_VIN)
        )
        assert result.scalars().all() == [pack_id]

    async def test_deleting_a_pack_leaves_the_rules_it_made(
        self, client: AsyncClient, auth_headers
    ):
        """A rule from a pack is the vehicle's own copy; that is already the
        documented contract and deleting the pack must not rewrite anyone's
        schedule."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        await _vehicle(client, auth_headers, TARGET_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).json()["id"]
        await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack",
            json={"pack_id": pack_id},
            headers=auth_headers,
        )

        deleted = await client.delete(f"{PACKS}/{pack_id}", headers=auth_headers)
        assert deleted.status_code == 204, deleted.text

        rules = await client.get(
            f"/api/vehicles/{TARGET_VIN}/maintenance-rules", headers=auth_headers
        )
        assert len(rules.json()) == 1
        gone = await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack",
            json={"pack_id": pack_id},
            headers=auth_headers,
        )
        # The id resolves only against the database now, so it 404s rather than
        # falling through to a file that happens to share the name.
        assert gone.status_code == 404, gone.text

    @pytest.mark.parametrize(
        "method,body",
        [
            ("put", {"vin": SOURCE_VIN, "name": "Mine", "rule_ids": [1]}),
            ("patch", {"name": "Mine"}),
            ("delete", None),
        ],
    )
    async def test_a_builtin_pack_cannot_be_changed(
        self, client: AsyncClient, auth_headers, method, body
    ):
        """409, not 404. The pack plainly exists; a 404 would send a reader
        hunting for a typo in an id they just read off the list."""
        call = getattr(client, method)
        kwargs = {"headers": auth_headers}
        if body is not None:
            kwargs["json"] = body
        response = await call(f"{PACKS}/oil_and_filter", **kwargs)
        assert response.status_code == 409, response.text


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheList:
    async def test_saved_packs_sit_in_the_same_list_and_are_marked(
        self, client: AsyncClient, auth_headers
    ):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])

        listed = await client.get(PACKS, headers=auth_headers)
        assert listed.status_code == 200, listed.text
        by_id = {p["id"]: p for p in listed.json()}
        assert by_id["custom-truck-standard"]["is_custom"] is True
        assert by_id["oil_and_filter"]["is_custom"] is False
        # A shipped file lives in git; an overwrite would be lost next release.
        assert by_id["oil_and_filter"]["can_edit"] is False

    async def test_the_vehicle_type_filter_covers_saved_packs_too(
        self, client: AsyncClient, auth_headers
    ):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        await _save(client, auth_headers, SOURCE_VIN, [oil["id"]], vehicle_types=["Boat"])

        listed = await client.get(f"{PACKS}?vehicle_type=Truck", headers=auth_headers)
        assert "custom-truck-standard" not in {p["id"] for p in listed.json()}

        listed = await client.get(f"{PACKS}?vehicle_type=Boat", headers=auth_headers)
        assert "custom-truck-standard" in {p["id"] for p in listed.json()}


async def _odometer(client: AsyncClient, headers, vin: str, on: str, km: float) -> None:
    response = await client.post(
        f"/api/vehicles/{vin}/odometer",
        headers=headers,
        json={"vin": vin, "date": on, "odometer_km": km},
    )
    assert response.status_code == 201, response.text


@pytest.mark.integration
@pytest.mark.asyncio
class TestIntervalOverrides:
    """Changing an interval while applying, which is the other half of #165.

    The override has to survive three separate places, and each one alone is
    insufficient: substitution into the item, the "the vehicle's own intervals
    win" branch standing down, and `update_intervals` on the rule write. So every
    test here checks the PREVIEW, the RULE ROW and the REMINDER threshold, not
    just whichever one is convenient.
    """

    async def test_an_override_reaches_the_preview_the_rule_and_the_reminder(
        self, client: AsyncClient, auth_headers
    ):
        await _vehicle(client, auth_headers, SOURCE_VIN)
        await _vehicle(client, auth_headers, TARGET_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).json()["id"]
        await _odometer(client, auth_headers, TARGET_VIN, "2026-01-01", 50000)

        body = {
            "pack_id": pack_id,
            "overrides": {"engine_oil_filter": {"interval_km": 10000, "interval_months": 6}},
        }
        preview = await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack/preview",
            json=body,
            headers=auth_headers,
        )
        assert preview.status_code == 200, preview.text
        # Decimal, not string: the preview echoes what was typed while the rule
        # row carries the column's scale, and the VALUE is what must agree.
        assert Decimal(preview.json()["items"][0]["interval_km"]) == Decimal(10000)

        applied = await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack", json=body, headers=auth_headers
        )
        assert applied.status_code == 201, applied.text
        assert applied.json()[0]["due_mileage_km"] == "60000.00"

        rules = await client.get(
            f"/api/vehicles/{TARGET_VIN}/maintenance-rules", headers=auth_headers
        )
        assert rules.json()[0]["interval_km"] == "10000.00"

    async def test_an_override_beats_the_vehicles_own_interval_on_reuse(
        self, client: AsyncClient, auth_headers
    ):
        """THE REGRESSION. `_plan_item` overwrites the plan's intervals from an
        ACTIVE rule, so an override substituted upstream was discarded before the
        thresholds were computed: previewed and persisted as the OLD number on
        exactly the path the override exists for.
        """
        await _vehicle(client, auth_headers, SOURCE_VIN)
        await _vehicle(client, auth_headers, TARGET_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).json()["id"]
        await _odometer(client, auth_headers, TARGET_VIN, "2026-01-01", 50000)
        # The destination already tracks this type, on its own numbers.
        await _rule(client, auth_headers, TARGET_VIN, interval_km=5000, interval_months=3)

        body = {
            "pack_id": pack_id,
            "overrides": {"engine_oil_filter": {"interval_km": 10000, "interval_months": 6}},
        }
        preview = await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack/preview",
            json=body,
            headers=auth_headers,
        )
        assert preview.json()["items"][0]["rule_action"] == "reuse"
        assert Decimal(preview.json()["items"][0]["interval_km"]) == Decimal(10000)

        applied = await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack", json=body, headers=auth_headers
        )
        assert applied.status_code == 201, applied.text
        assert applied.json()[0]["due_mileage_km"] == "60000.00"

        rules = await client.get(
            f"/api/vehicles/{TARGET_VIN}/maintenance-rules", headers=auth_headers
        )
        assert rules.json()[0]["interval_km"] == "10000.00"

    async def test_without_an_override_the_vehicles_own_interval_survives(
        self, client: AsyncClient, auth_headers
    ):
        """The other direction, and each is the other's regression: re-applying a
        pack must not undo a schedule its owner has tuned."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        await _vehicle(client, auth_headers, TARGET_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).json()["id"]
        await _rule(client, auth_headers, TARGET_VIN, interval_km=5000, interval_months=3)

        applied = await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack",
            json={"pack_id": pack_id},
            headers=auth_headers,
        )
        assert applied.status_code == 201, applied.text

        rules = await client.get(
            f"/api/vehicles/{TARGET_VIN}/maintenance-rules", headers=auth_headers
        )
        assert rules.json()[0]["interval_km"] == "5000.00"

    async def test_an_untouched_item_keeps_the_packs_interval(
        self, client: AsyncClient, auth_headers
    ):
        """An item the caller did not name sends nothing, so a form nobody typed
        in behaves exactly as it did before overrides existed."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        await _vehicle(client, auth_headers, TARGET_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        tires = await _rule(
            client,
            auth_headers,
            SOURCE_VIN,
            maintenance_type="tire_rotation",
            title="Tire Rotation",
            interval_km=10000,
            interval_months=None,
        )
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"], tires["id"]])).json()[
            "id"
        ]

        applied = await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack",
            json={
                "pack_id": pack_id,
                "overrides": {"engine_oil_filter": {"interval_km": 12000}},
            },
            headers=auth_headers,
        )
        assert applied.status_code == 201, applied.text

        rules = await client.get(
            f"/api/vehicles/{TARGET_VIN}/maintenance-rules", headers=auth_headers
        )
        by_type = {r["maintenance_type"]: r for r in rules.json()}
        assert by_type["engine_oil_filter"]["interval_km"] == "12000.00"
        assert by_type["tire_rotation"]["interval_km"] == "10000.00"

    async def test_an_override_naming_an_item_the_pack_lacks_is_refused(
        self, client: AsyncClient, auth_headers
    ):
        """422, the same answer `anchors` gives an unknown key."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        await _vehicle(client, auth_headers, TARGET_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).json()["id"]

        refused = await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack",
            json={"pack_id": pack_id, "overrides": {"not_a_real_item": {"interval_km": 1000}}},
            headers=auth_headers,
        )
        assert refused.status_code == 422, refused.text
        assert "not_a_real_item" in str(refused.json()["detail"])

    @pytest.mark.parametrize(
        "override",
        [
            {},
            {"interval_km": 5000, "interval_hours": 100},
        ],
        ids=["no interval at all", "distance and hours together"],
    )
    async def test_an_override_obeys_the_rules_a_rule_obeys(
        self, client: AsyncClient, auth_headers, override
    ):
        """`IntervalOverride` subclasses `RecurrenceSpec` so these two rules live
        in one place; this proves the subclassing actually carries them."""
        await _vehicle(client, auth_headers, SOURCE_VIN)
        await _vehicle(client, auth_headers, TARGET_VIN)
        oil = await _rule(client, auth_headers, SOURCE_VIN)
        pack_id = (await _save(client, auth_headers, SOURCE_VIN, [oil["id"]])).json()["id"]

        refused = await client.post(
            f"/api/vehicles/{TARGET_VIN}/reminders/apply-pack",
            json={"pack_id": pack_id, "overrides": {"engine_oil_filter": override}},
            headers=auth_headers,
        )
        assert refused.status_code == 422, refused.text
