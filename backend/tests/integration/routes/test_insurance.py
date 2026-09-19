"""Household insurance policies: the API, its access rules and its money rules.

A policy is a household record covering several vehicles. Access DERIVES from
those vehicles (see `InsuranceService`), so most of this file is the matrix of
who may do what, plus the allocation invariant that keeps a policy's premium
and its vehicles' shares from drifting apart.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insurance import InsurancePolicy
from app.models.user import User
from app.models.vehicle import Vehicle
from app.utils.household_time import household_today

SECOND_VIN = "INS2NDVEH00000001"
FOREIGN_VIN = "INSFOREIGN0000001"
API = "/api/insurance/policies"


@pytest_asyncio.fixture(autouse=True)
async def _clean_slate(db_session: AsyncSession):
    """Tests share one database, and a leftover policy would change another
    test's list, totals and successor lookups."""
    await db_session.execute(delete(InsurancePolicy))
    await db_session.commit()
    yield
    await db_session.execute(delete(InsurancePolicy))
    # Every row these tests add goes again: a leftover vehicle changes other
    # suites' lists and counts.
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_([SECOND_VIN, FOREIGN_VIN])))
    await db_session.commit()


async def _vehicle(db: AsyncSession, vin: str, owner: User, nickname: str) -> Vehicle:
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.vin == vin))).scalar_one_or_none()
    if vehicle is None:
        vehicle = Vehicle(
            vin=vin, user_id=owner.id, nickname=nickname, vehicle_type="Car", year=2020
        )
        db.add(vehicle)
    vehicle.user_id = owner.id
    vehicle.archived_at = None
    await db.commit()
    return vehicle


@pytest_asyncio.fixture
async def second_vehicle(db_session: AsyncSession, owner_user: User, owned_vehicle) -> Vehicle:
    """Another vehicle of the SAME owner, with no shares at all."""
    return await _vehicle(db_session, SECOND_VIN, owner_user, "Second")


@pytest_asyncio.fixture
async def foreign_vehicle(db_session: AsyncSession, unrelated_user: User) -> Vehicle:
    """A vehicle the owner has nothing to do with."""
    return await _vehicle(db_session, FOREIGN_VIN, unrelated_user, "Foreign")


def _body(vehicles: list[dict] | None = None, **over) -> dict:
    today = household_today()
    return {
        "provider": "Progressive",
        "policy_number": "P-100",
        "start_date": (today - timedelta(days=30)).isoformat(),
        "end_date": (today + timedelta(days=150)).isoformat(),
        "premium_amount": "600.00",
        "premium_frequency": "Semi-Annual",
        "vehicles": vehicles or [],
    } | over


def _on(vin: str, **over) -> dict:
    return {"vin": vin, "policy_type": "Full Coverage"} | over


async def _create(client: AsyncClient, headers, vehicles=None, **over) -> dict:
    response = await client.post(API, json=_body(vehicles, **over), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.integration
@pytest.mark.asyncio
class TestOnePolicyManyVehicles:
    async def test_a_policy_lists_its_vehicles_beneath_it_with_an_even_split(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        policy = await _create(
            client,
            owner_headers,
            [_on(owned_vehicle.vin), _on(SECOND_VIN, policy_type="Liability")],
        )

        assert policy["premium_amount"] == "600.00"
        assert [(v["vin"], v["policy_type"], v["effective_share"]) for v in policy["vehicles"]] == [
            (owned_vehicle.vin, "Full Coverage", "300.00"),
            (SECOND_VIN, "Liability", "300.00"),
        ]
        assert policy["status"] == "active"

    async def test_the_vehicle_tab_sees_the_same_policy(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        created = await _create(client, owner_headers, [_on(owned_vehicle.vin), _on(SECOND_VIN)])

        response = await client.get(f"/api/vehicles/{SECOND_VIN}/insurance", headers=owner_headers)

        assert response.status_code == 200
        assert [p["id"] for p in response.json()] == [created["id"]]
        assert len(response.json()[0]["vehicles"]) == 2

    async def test_named_fields_live_at_both_levels_and_omitting_them_leaves_them_alone(
        self, client, owner_headers, owned_vehicle
    ):
        policy = await _create(
            client,
            owner_headers,
            [_on(owned_vehicle.vin, fields=[{"label": "Collision Deductible", "value": "$500"}])],
            fields=[{"label": "Agent Phone", "value": "555-0100"}],
        )
        assert policy["fields"] == [{"label": "Agent Phone", "value": "555-0100"}]
        assert policy["vehicles"][0]["fields"] == [
            {"label": "Collision Deductible", "value": "$500"}
        ]

        # A PUT that does not mention `fields` must not clear them...
        kept = await client.put(
            f"{API}/{policy['id']}", json={"notes": "renews in spring"}, headers=owner_headers
        )
        assert kept.json()["fields"] == [{"label": "Agent Phone", "value": "555-0100"}]
        assert kept.json()["vehicles"][0]["fields"][0]["label"] == "Collision Deductible"

        # ...and an explicit empty list does.
        cleared = await client.put(
            f"{API}/{policy['id']}", json={"fields": []}, headers=owner_headers
        )
        assert cleared.json()["fields"] == []
        assert cleared.json()["vehicles"][0]["fields"] != []

    async def test_validation_names_the_field(self, client, owner_headers, owned_vehicle):
        bad_type = await client.post(
            API,
            json=_body([_on(owned_vehicle.vin, policy_type="Umbrella")]),
            headers=owner_headers,
        )
        assert bad_type.status_code == 422, "a bad type used to surface as a 409 from the CHECK"

        today = household_today()
        backwards = await client.post(
            API,
            json=_body(
                start_date=today.isoformat(), end_date=(today - timedelta(days=1)).isoformat()
            ),
            headers=owner_headers,
        )
        assert backwards.status_code == 422

    async def test_requires_authentication(self, client):
        assert (await client.get(API)).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
class TestAllocationInvariant:
    async def test_fully_explicit_shares_must_add_up_to_the_premium(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        response = await client.post(
            API,
            json=_body(
                [
                    _on(owned_vehicle.vin, premium_share="300.00"),
                    _on(SECOND_VIN, premium_share="200.00"),
                ]
            ),
            headers=owner_headers,
        )
        assert response.status_code == 422
        assert "500" in response.text and "600" in response.text

    async def test_changing_the_premium_on_fixed_shares_needs_a_strategy(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        policy = await _create(
            client,
            owner_headers,
            [
                _on(owned_vehicle.vin, premium_share="400.00"),
                _on(SECOND_VIN, premium_share="200.00"),
            ],
        )
        url = f"{API}/{policy['id']}"

        refused = await client.put(url, json={"premium_amount": "900.00"}, headers=owner_headers)
        assert refused.status_code == 422

        rescaled = await client.put(
            url,
            json={"premium_amount": "900.00", "share_strategy": "rescale"},
            headers=owner_headers,
        )
        assert [v["premium_share"] for v in rescaled.json()["vehicles"]] == ["600.00", "300.00"]

        evened = await client.put(
            url,
            json={"premium_amount": "1000.00", "share_strategy": "reset_even"},
            headers=owner_headers,
        )
        assert [v["effective_share"] for v in evened.json()["vehicles"]] == ["500.00", "500.00"]

    async def test_the_form_can_add_a_vehicle_and_raise_the_premium_in_one_save(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        policy = await _create(
            client, owner_headers, [_on(owned_vehicle.vin, premium_share="600.00")]
        )

        saved = await client.put(
            f"{API}/{policy['id']}",
            json={
                "premium_amount": "900.00",
                "vehicles": [
                    _on(owned_vehicle.vin, premium_share="600.00"),
                    _on(SECOND_VIN, premium_share="300.00"),
                ],
            },
            headers=owner_headers,
        )

        assert saved.status_code == 200, saved.text
        assert [v["effective_share"] for v in saved.json()["vehicles"]] == ["600.00", "300.00"]

    async def test_attach_and_detach_leave_the_other_vehicles_shares_alone(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        policy = await _create(client, owner_headers, [_on(owned_vehicle.vin)])  # 600, even split
        url = f"{API}/{policy['id']}/vehicles"

        attached = (
            await client.post(
                url, json=_on(SECOND_VIN, premium_share="250.00"), headers=owner_headers
            )
        ).json()
        assert attached["premium_amount"] == "850.00"
        assert [v["effective_share"] for v in attached["vehicles"]] == ["600.00", "250.00"]

        link_id = attached["vehicles"][1]["id"]
        detached = (await client.delete(f"{url}/{link_id}", headers=owner_headers)).json()
        assert detached["premium_amount"] == "600.00"
        assert [v["effective_share"] for v in detached["vehicles"]] == ["600.00"]


@pytest.mark.integration
@pytest.mark.asyncio
class TestAccessDerivesFromTheVehicles:
    async def test_who_can_see_a_policy(
        self,
        client,
        owner_headers,
        reader_headers,
        writer_headers,
        unrelated_headers,
        admin_user_headers,
        owned_vehicle,
    ):
        policy = await _create(client, owner_headers, [_on(owned_vehicle.vin)])
        url = f"{API}/{policy['id']}"

        for headers in (owner_headers, reader_headers, writer_headers, admin_user_headers):
            assert (await client.get(url, headers=headers)).status_code == 200
        # 404, not 403: to someone with no covered vehicle the policy does not exist.
        assert (await client.get(url, headers=unrelated_headers)).status_code == 404
        assert (await client.get(API, headers=unrelated_headers)).json() == []

    async def test_a_vehicle_the_caller_cannot_see_is_only_a_count(
        self, client, owner_headers, reader_headers, owned_vehicle, second_vehicle
    ):
        policy = await _create(client, owner_headers, [_on(owned_vehicle.vin), _on(SECOND_VIN)])

        seen = (await client.get(f"{API}/{policy['id']}", headers=reader_headers)).json()

        assert [v["vin"] for v in seen["vehicles"]] == [owned_vehicle.vin]
        assert seen["other_vehicle_count"] == 1
        assert seen["can_edit"] is False

    async def test_policy_writes_need_write_on_every_covered_vehicle(
        self, client, owner_headers, writer_headers, reader_headers, owned_vehicle, second_vehicle
    ):
        # The writer can write `owned_vehicle` but has no access to the second.
        policy = await _create(client, owner_headers, [_on(owned_vehicle.vin), _on(SECOND_VIN)])
        url = f"{API}/{policy['id']}"

        assert (
            await client.put(url, json={"notes": "x"}, headers=writer_headers)
        ).status_code == 403
        assert (await client.delete(url, headers=writer_headers)).status_code == 403
        assert (
            await client.put(url, json={"notes": "x"}, headers=reader_headers)
        ).status_code == 403
        assert (
            await client.put(url, json={"notes": "x"}, headers=owner_headers)
        ).status_code == 200

    async def test_moving_money_is_a_policy_write_but_a_deductible_is_a_vehicle_write(
        self, client, owner_headers, writer_headers, reader_headers, owned_vehicle, second_vehicle
    ):
        policy = await _create(client, owner_headers, [_on(owned_vehicle.vin), _on(SECOND_VIN)])
        link_id = policy["vehicles"][0]["id"]
        link_url = f"{API}/{policy['id']}/vehicles/{link_id}"

        # Setting a share shrinks the OTHER vehicle's computed share, and the
        # writer has no business with that vehicle.
        money = await client.patch(
            link_url, json={"premium_share": "550.00"}, headers=writer_headers
        )
        assert money.status_code == 403

        plain = await client.patch(link_url, json={"deductible": "250.00"}, headers=writer_headers)
        assert plain.status_code == 200, plain.text
        assert plain.json()["vehicles"][0]["deductible"] == "250.00"

        read_only = await client.patch(
            link_url, json={"deductible": "1.00"}, headers=reader_headers
        )
        assert read_only.status_code == 403

    async def test_a_vehicle_you_cannot_write_cannot_be_put_on_your_policy(
        self, client, owner_headers, owned_vehicle, foreign_vehicle
    ):
        refused = await client.post(
            API, json=_body([_on(owned_vehicle.vin), _on(FOREIGN_VIN)]), headers=owner_headers
        )
        assert refused.status_code == 403

    async def test_a_policy_with_no_vehicles_belongs_to_its_creator_and_admins(
        self, client, owner_headers, writer_headers, admin_user_headers, owned_vehicle
    ):
        umbrella = await _create(client, owner_headers, provider="Umbrella Co")
        url = f"{API}/{umbrella['id']}"

        assert (await client.get(url, headers=owner_headers)).status_code == 200
        assert (await client.get(url, headers=admin_user_headers)).status_code == 200
        assert (await client.get(url, headers=writer_headers)).status_code == 404

    async def test_auth_disabled_has_full_access(
        self, client, owner_headers, owned_vehicle, set_auth_mode
    ):
        umbrella = await _create(client, owner_headers, provider="Umbrella Co")
        await set_auth_mode("none")

        assert (await client.get(f"{API}/{umbrella['id']}")).status_code == 200
        created = await client.post(API, json=_body([_on(owned_vehicle.vin)], policy_number="N-1"))
        assert created.status_code == 201
        assert created.json()["created_by_user_id"] is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestRenewReplaceAndHistory:
    async def test_a_renewal_can_be_entered_early_and_allocates_the_whole_new_premium(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        old = await _create(
            client,
            owner_headers,
            [
                _on(owned_vehicle.vin, premium_share="300.00", deductible="500.00"),
                _on(SECOND_VIN, premium_share="300.00"),
            ],
            fields=[{"label": "Agent Phone", "value": "555-0100"}],
        )

        response = await client.post(
            f"{API}/{old['id']}/renew", json={"premium_amount": "700.00"}, headers=owner_headers
        )

        assert response.status_code == 201, response.text
        new = response.json()
        assert new["status"] == "upcoming", "entered before the current term ends"
        assert new["start_date"] == old["end_date"]
        assert new["previous_policy_id"] == old["id"]
        assert [v["premium_share"] for v in new["vehicles"]] == ["350.00", "350.00"]
        assert new["vehicles"][0]["deductible"] == "500.00"
        assert new["fields"] == [{"label": "Agent Phone", "value": "555-0100"}]

        unchanged = (await client.get(f"{API}/{old['id']}", headers=owner_headers)).json()
        assert unchanged["premium_amount"] == "600.00"
        assert unchanged["status"] == "active"
        assert unchanged["has_successor"] is True

        again = await client.post(f"{API}/{old['id']}/renew", json={}, headers=owner_headers)
        assert again.status_code == 409

    async def test_switching_insurers_carries_the_vehicles_but_not_the_coverages(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        old = await _create(
            client,
            owner_headers,
            [_on(owned_vehicle.vin, deductible="500.00"), _on(SECOND_VIN)],
        )
        today = household_today()

        response = await client.post(
            f"{API}/{old['id']}/replace",
            json={
                "provider": "GEICO",
                "policy_number": "G-7",
                "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=180)).isoformat(),
                "premium_amount": "500.00",
                "premium_frequency": "Semi-Annual",
                "end_old_on": today.isoformat(),
            },
            headers=owner_headers,
        )

        assert response.status_code == 201, response.text
        new = response.json()
        assert new["provider"] == "GEICO"
        assert [v["vin"] for v in new["vehicles"]] == [owned_vehicle.vin, SECOND_VIN]
        assert new["vehicles"][0]["deductible"] is None
        assert [v["effective_share"] for v in new["vehicles"]] == ["250.00", "250.00"]

        ended = (await client.get(f"{API}/{old['id']}", headers=owner_headers)).json()
        assert ended["end_date"] == today.isoformat()
        # The shared boundary day: the successor has started, so the old one is over.
        assert ended["status"] == "expired"

    async def test_history_is_the_whole_chain_with_the_premium_change(
        self, client, owner_headers, owned_vehicle
    ):
        first = await _create(client, owner_headers, [_on(owned_vehicle.vin)])
        second = (
            await client.post(
                f"{API}/{first['id']}/renew",
                json={"premium_amount": "684.00"},
                headers=owner_headers,
            )
        ).json()

        for asked in (first["id"], second["id"]):
            history = (await client.get(f"{API}/{asked}/history", headers=owner_headers)).json()
            assert [h["id"] for h in history] == [first["id"], second["id"]]
            assert [h["premium_change"] for h in history] == [None, "84.00"]
            assert [h["is_current"] for h in history] == [h["id"] == asked for h in history]

    async def test_the_default_list_hides_expired_terms_and_status_all_shows_them(
        self, client, owner_headers, owned_vehicle
    ):
        today = household_today()
        await _create(
            client,
            owner_headers,
            [_on(owned_vehicle.vin)],
            policy_number="OLD",
            start_date=(today - timedelta(days=400)).isoformat(),
            end_date=(today - timedelta(days=35)).isoformat(),
        )
        await _create(client, owner_headers, [_on(owned_vehicle.vin)], policy_number="NOW")

        current = (await client.get(API, headers=owner_headers)).json()
        everything = (await client.get(f"{API}?status=all", headers=owner_headers)).json()

        assert [p["policy_number"] for p in current] == ["NOW"]
        assert sorted(p["policy_number"] for p in everything) == ["NOW", "OLD"]


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleLifecycle:
    async def test_deleting_a_vehicle_removes_its_link_and_keeps_the_policy(
        self, client, db_session, owner_headers, owned_vehicle, second_vehicle
    ):
        policy = await _create(client, owner_headers, [_on(owned_vehicle.vin), _on(SECOND_VIN)])

        deleted = await client.delete(f"/api/vehicles/{SECOND_VIN}", headers=owner_headers)
        assert deleted.status_code in (200, 204), deleted.text

        kept = (await client.get(f"{API}/{policy['id']}", headers=owner_headers)).json()
        assert [v["vin"] for v in kept["vehicles"]] == [owned_vehicle.vin]

    async def test_a_transferred_vehicle_leaves_the_old_owners_policy(
        self,
        client,
        db_session,
        owner_headers,
        unrelated_headers,
        unrelated_user,
        admin_user_headers,
        owned_vehicle,
        second_vehicle,
    ):
        policy = await _create(
            client,
            owner_headers,
            [
                _on(owned_vehicle.vin, premium_share="400.00"),
                _on(SECOND_VIN, premium_share="200.00"),
            ],
        )

        moved = await client.post(
            f"/api/family/vehicles/{SECOND_VIN}/transfer",
            json={"to_user_id": unrelated_user.id, "data_included": {}},
            headers=admin_user_headers,
        )
        assert moved.status_code in (200, 201), moved.text

        # The new owner must not inherit a window into the old owner's policy.
        assert (
            await client.get(f"{API}/{policy['id']}", headers=unrelated_headers)
        ).status_code == 404
        kept = (await client.get(f"{API}/{policy['id']}", headers=owner_headers)).json()
        assert [v["vin"] for v in kept["vehicles"]] == [owned_vehicle.vin]
        assert kept["premium_amount"] == "400.00"
        assert Decimal(kept["vehicles"][0]["effective_share"]) == Decimal("400.00")


@pytest.mark.integration
@pytest.mark.asyncio
class TestCodeReviewRegressions:
    """Each of these was a real defect the code review found."""

    async def test_deleting_a_vehicle_takes_its_share_out_of_the_premium(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        # CB-R1-H1: the cascade removed the link but left the premium counting it.
        policy = await _create(
            client,
            owner_headers,
            [
                _on(owned_vehicle.vin, premium_share="400.00"),
                _on(SECOND_VIN, premium_share="200.00"),
            ],
        )

        deleted = await client.delete(f"/api/vehicles/{SECOND_VIN}", headers=owner_headers)
        assert deleted.status_code in (200, 204), deleted.text

        kept = (await client.get(f"{API}/{policy['id']}", headers=owner_headers)).json()
        assert kept["premium_amount"] == "400.00"
        assert [v["effective_share"] for v in kept["vehicles"]] == ["400.00"]
        # And the policy is still editable: 400 explicit against a 600 premium
        # would be refused by the allocation rule forever after.
        edited = await client.put(
            f"{API}/{policy['id']}", json={"notes": "x"}, headers=owner_headers
        )
        assert edited.status_code == 200, edited.text

    async def test_money_is_whole_cents(self, client, owner_headers, owned_vehicle, second_vehicle):
        # CB-R1-H3: 0.005 + 0.005 validated as 0.01, then stored as 0.01 + 0.01.
        response = await client.post(
            API,
            json=_body(
                [
                    _on(owned_vehicle.vin, premium_share="0.005"),
                    _on(SECOND_VIN, premium_share="0.005"),
                ],
                premium_amount="0.01",
            ),
            headers=owner_headers,
        )
        assert response.status_code == 422

    async def test_renewing_after_a_vehicle_left_scales_against_what_is_still_covered(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        # CB-R1-M1: the survivor's 400 was scaled by 700/600 to 466.67 and the
        # renewal was refused, because the 600 still counted the departed 200.
        policy = await _create(
            client,
            owner_headers,
            [
                _on(owned_vehicle.vin, premium_share="400.00"),
                _on(SECOND_VIN, premium_share="200.00"),
            ],
        )
        left = await client.put(
            f"{API}/{policy['id']}",
            json={
                "vehicles": [
                    _on(owned_vehicle.vin, premium_share="400.00"),
                    _on(SECOND_VIN, premium_share="200.00", effective_to=policy["start_date"]),
                ]
            },
            headers=owner_headers,
        )
        assert left.status_code == 200, left.text

        renewed = await client.post(
            f"{API}/{policy['id']}/renew", json={"premium_amount": "700.00"}, headers=owner_headers
        )

        assert renewed.status_code == 201, renewed.text
        assert [(v["vin"], v["premium_share"]) for v in renewed.json()["vehicles"]] == [
            (owned_vehicle.vin, "700.00")
        ]

    async def test_a_creator_with_read_only_access_to_a_vehicle_can_still_edit_the_policy(
        self, client, db_session, reader_headers, reader_user, owned_vehicle, owner_headers
    ):
        # CF-R1-M1: the form always sends the whole vehicle list, and an
        # UNCHANGED vehicle demanded write access the creator did not have.
        policy = await _create(client, owner_headers, [_on(owned_vehicle.vin)])
        row = await db_session.get(InsurancePolicy, policy["id"])
        row.created_by_user_id = reader_user.id
        await db_session.commit()

        untouched = await client.put(
            f"{API}/{policy['id']}",
            json={"provider": "Progressive Direct", "vehicles": [_on(owned_vehicle.vin)]},
            headers=reader_headers,
        )
        assert untouched.status_code == 200, untouched.text
        assert untouched.json()["provider"] == "Progressive Direct"

        changed = await client.put(
            f"{API}/{policy['id']}",
            json={"vehicles": [_on(owned_vehicle.vin, deductible="250.00")]},
            headers=reader_headers,
        )
        assert changed.status_code == 403

    async def test_switching_insurers_can_carry_the_new_coverages_in_one_step(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        # CF-R1-H2: the form offered coverage edits the endpoint ignored.
        old = await _create(client, owner_headers, [_on(owned_vehicle.vin), _on(SECOND_VIN)])
        today = household_today()

        response = await client.post(
            f"{API}/{old['id']}/replace",
            json={
                "provider": "GEICO",
                "policy_number": "G-8",
                "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=180)).isoformat(),
                "premium_amount": "500.00",
                "vehicles": [
                    _on(
                        owned_vehicle.vin,
                        policy_type="Liability",
                        premium_share="500.00",
                        deductible="1000.00",
                    )
                ],
            },
            headers=owner_headers,
        )

        assert response.status_code == 201, response.text
        (vehicle,) = response.json()["vehicles"]
        assert (vehicle["vin"], vehicle["policy_type"], vehicle["deductible"]) == (
            owned_vehicle.vin,
            "Liability",
            "1000.00",
        )

    async def test_a_creator_who_can_only_read_a_vehicle_can_still_switch_insurers(
        self, client, db_session, reader_headers, reader_user, owned_vehicle, owner_headers
    ):
        # CF-R2-M1: CREATING a link needs write on the vehicle, so an explicit
        # vehicle list 403s for this user. CARRYING every vehicle over does not,
        # which is what the form sends when it cannot edit a vehicle.
        old = await _create(client, owner_headers, [_on(owned_vehicle.vin, deductible="500.00")])
        row = await db_session.get(InsurancePolicy, old["id"])
        row.created_by_user_id = reader_user.id
        await db_session.commit()
        today = household_today()
        switch = {
            "provider": "GEICO",
            "policy_number": "G-9",
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=180)).isoformat(),
        }

        explicit = await client.post(
            f"{API}/{old['id']}/replace",
            json=switch | {"vehicles": [_on(owned_vehicle.vin)]},
            headers=reader_headers,
        )
        assert explicit.status_code == 403

        carried = await client.post(
            f"{API}/{old['id']}/replace", json=switch, headers=reader_headers
        )
        assert carried.status_code == 201, carried.text
        assert [v["vin"] for v in carried.json()["vehicles"]] == [owned_vehicle.vin]
