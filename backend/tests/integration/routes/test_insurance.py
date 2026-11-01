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
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insurance import InsuranceCoverage, InsurancePolicy
from app.models.user import User
from app.models.vehicle import Vehicle
from app.utils.household_time import household_today
from tests._policy_scope import PolicyScope

SECOND_VIN = "INS2NDVEH00000001"
FOREIGN_VIN = "INSFOREIGN0000001"
API = "/api/insurance/policies"


policies = PolicyScope()


@pytest_asyncio.fixture(autouse=True)
async def _clean_slate(db_session: AsyncSession):
    """Every policy a test makes goes afterwards, and the tests read only their
    own. Emptying the table instead would also delete other tests' leaked rows
    before the leak guard saw them."""
    await policies.start(db_session)
    yield
    await db_session.rollback()
    await policies.drop(db_session)
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
        listed = (await client.get(API, headers=unrelated_headers)).json()
        assert policy["id"] not in [p["id"] for p in listed]

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
        old = await _create(
            client,
            owner_headers,
            [_on(owned_vehicle.vin)],
            policy_number="OLD",
            start_date=(today - timedelta(days=400)).isoformat(),
            end_date=(today - timedelta(days=35)).isoformat(),
        )
        now = await _create(client, owner_headers, [_on(owned_vehicle.vin)], policy_number="NOW")

        # The owner's list may hold other tests' policies on the shared authz vehicle.
        ours = {old["id"], now["id"]}
        current = (await client.get(API, headers=owner_headers)).json()
        everything = (await client.get(f"{API}?status=all", headers=owner_headers)).json()

        assert [p["policy_number"] for p in current if p["id"] in ours] == ["NOW"]
        assert sorted(p["policy_number"] for p in everything if p["id"] in ours) == ["NOW", "OLD"]


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
                "end_old_on": today.isoformat(),
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
            "end_old_on": today.isoformat(),
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


@pytest.mark.integration
@pytest.mark.asyncio
class TestPrReviewRegressions:
    """The three findings from the PR #177 review."""

    @staticmethod
    def _switch(today, **over) -> dict:
        return {
            "provider": "GEICO",
            "policy_number": "G-PR",
            "start_date": (today + timedelta(days=150)).isoformat(),
            "end_date": (today + timedelta(days=330)).isoformat(),
            "premium_amount": "250.00",
        } | over

    async def test_moving_one_vehicle_to_a_new_insurer_leaves_the_old_policy_alive(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        # P1: the new policy superseded the WHOLE old one, so the vehicle left
        # behind could never be renewed and its expiry reminder went silent.
        old = await _create(client, owner_headers, [_on(owned_vehicle.vin), _on(SECOND_VIN)])
        today = household_today()

        moved = await client.post(
            f"{API}/{old['id']}/replace",
            json=self._switch(today, vins=[SECOND_VIN]),
            headers=owner_headers,
        )
        assert moved.status_code == 201, moved.text
        assert [v["vin"] for v in moved.json()["vehicles"]] == [SECOND_VIN]
        assert moved.json()["previous_policy_id"] is None, "a partial move supersedes nothing"

        still = (await client.get(f"{API}/{old['id']}", headers=owner_headers)).json()
        assert still["has_successor"] is False
        assert still["status"] == "active"
        # The moved vehicle stops costing on the old policy from the switch date.
        by_vin = {v["vin"]: v for v in still["vehicles"]}
        assert by_vin[SECOND_VIN]["effective_to"] == old["end_date"]
        assert by_vin[owned_vehicle.vin]["effective_to"] is None

        # ...and the old policy can still be renewed, for the vehicle that stayed.
        renewed = await client.post(f"{API}/{old['id']}/renew", json={}, headers=owner_headers)
        assert renewed.status_code == 201, renewed.text
        assert [v["vin"] for v in renewed.json()["vehicles"]] == [owned_vehicle.vin]

    async def test_a_mid_term_switch_does_not_bring_back_a_vehicle_that_already_left(
        self, client, owner_headers, owned_vehicle, second_vehicle
    ):
        # P2: with `end_old_on` and no explicit list, EVERY link was carried,
        # including one whose cover ended earlier in the term.
        old = await _create(client, owner_headers, [_on(owned_vehicle.vin), _on(SECOND_VIN)])
        today = household_today()
        left_on = (today - timedelta(days=10)).isoformat()
        edited = await client.put(
            f"{API}/{old['id']}",
            json={"vehicles": [_on(owned_vehicle.vin), _on(SECOND_VIN, effective_to=left_on)]},
            headers=owner_headers,
        )
        assert edited.status_code == 200, edited.text

        switched = await client.post(
            f"{API}/{old['id']}/replace",
            json=self._switch(today, start_date=today.isoformat(), end_old_on=today.isoformat()),
            headers=owner_headers,
        )

        assert switched.status_code == 201, switched.text
        assert [v["vin"] for v in switched.json()["vehicles"]] == [owned_vehicle.vin]
        # Every still-covered vehicle moved, so this one DOES supersede the old policy.
        assert switched.json()["previous_policy_id"] == old["id"]

    async def test_a_renewal_or_switch_may_not_overlap_the_term_it_follows(
        self, client, owner_headers, owned_vehicle
    ):
        # P2: an overlapping successor left both terms active, and analytics
        # accrued both premiums for the overlap.
        old = await _create(client, owner_headers, [_on(owned_vehicle.vin)])
        today = household_today()

        early = await client.post(
            f"{API}/{old['id']}/renew",
            json={
                "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=180)).isoformat(),
            },
            headers=owner_headers,
        )
        assert early.status_code == 422, early.text

        overlapping_switch = await client.post(
            f"{API}/{old['id']}/replace",
            json=self._switch(today, start_date=today.isoformat()),
            headers=owner_headers,
        )
        assert overlapping_switch.status_code == 422, overlapping_switch.text

        # Ending the old policy on the switch date is how a mid-term switch is said.
        clean = await client.post(
            f"{API}/{old['id']}/replace",
            json=self._switch(today, start_date=today.isoformat(), end_old_on=today.isoformat()),
            headers=owner_headers,
        )
        assert clean.status_code == 201, clean.text


def _coverage(key: str, **over) -> dict:
    return {"coverage_key": key, **over}


@pytest.mark.integration
@pytest.mark.asyncio
class TestStandardCoverages:
    """The catalogue in `app.utils.insurance_coverages`, over the API.

    A coverage ROW means the coverage is carried; its amounts say how much. The
    order they come back in is the catalogue's, never the order they were sent,
    so two vehicles on one policy can never render their coverage in a
    different sequence.
    """

    async def test_a_vehicle_keeps_the_coverages_it_was_created_with(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        policy = await _create(
            client,
            auth_headers,
            [
                _on(
                    owned_vehicle.vin,
                    coverages=[
                        _coverage(
                            "bodily_injury",
                            limit_primary="100000.00",
                            limit_secondary="300000.00",
                            premium="55.00",
                        ),
                        _coverage("roadside_assistance"),
                    ],
                )
            ],
        )
        coverages = policy["vehicles"][0]["coverages"]
        assert [c["coverage_key"] for c in coverages] == ["bodily_injury", "roadside_assistance"]
        assert coverages[0]["limit_secondary"] == "300000.00"
        # Carried, unpriced: the row alone is the fact.
        assert coverages[1]["limit_primary"] is None

    async def test_coverages_come_back_in_catalogue_order(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        policy = await _create(
            client,
            auth_headers,
            [
                _on(
                    owned_vehicle.vin,
                    coverages=[
                        _coverage("roadside_assistance"),
                        _coverage("collision", deductible="500.00"),
                        _coverage("bodily_injury", limit_primary="100000.00"),
                    ],
                )
            ],
        )
        assert [c["coverage_key"] for c in policy["vehicles"][0]["coverages"]] == [
            "bodily_injury",
            "collision",
            "roadside_assistance",
        ]

    async def test_an_amount_the_coverage_has_no_slot_for_is_refused(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        """Stored, it would be money no screen ever shows."""
        response = await client.post(
            API,
            json=_body(
                [_on(owned_vehicle.vin, coverages=[_coverage("collision", limit_primary="100.00")])]
            ),
            headers=auth_headers,
        )
        assert response.status_code == 422, response.text

    async def test_the_same_coverage_twice_is_refused_by_name(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        response = await client.post(
            API,
            json=_body(
                [
                    _on(
                        owned_vehicle.vin,
                        coverages=[_coverage("collision"), _coverage("collision")],
                    )
                ]
            ),
            headers=auth_headers,
        )
        assert response.status_code == 422, response.text
        assert "collision" in response.text

    async def test_a_fractional_count_is_refused(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        """ "Maximum days" is a count; the flat exports write counts whole, so
        a fraction accepted here could not be exported and read back."""
        response = await client.post(
            API,
            json=_body(
                [
                    _on(
                        owned_vehicle.vin,
                        coverages=[_coverage("rental_reimbursement", limit_secondary="30.50")],
                    )
                ]
            ),
            headers=auth_headers,
        )
        assert response.status_code == 422, response.text

    async def test_a_whole_count_is_accepted(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        policy = await _create(
            client,
            auth_headers,
            [
                _on(
                    owned_vehicle.vin,
                    coverages=[
                        _coverage("rental_reimbursement", limit_primary="50", limit_secondary="30")
                    ],
                )
            ],
        )
        assert policy["vehicles"][0]["coverages"][0]["limit_secondary"] == "30.00"

    async def test_a_key_outside_the_catalogue_is_refused(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        response = await client.post(
            API,
            json=_body([_on(owned_vehicle.vin, coverages=[_coverage("flood")])]),
            headers=auth_headers,
        )
        assert response.status_code == 422, response.text

    async def test_editing_a_vehicle_replaces_its_coverages_wholesale(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        """A coverage the user removed has to be gone, not merely unmentioned."""
        policy = await _create(
            client,
            auth_headers,
            [
                _on(
                    owned_vehicle.vin,
                    coverages=[_coverage("collision", deductible="500.00"), _coverage("glass")],
                )
            ],
        )
        link = policy["vehicles"][0]
        response = await client.patch(
            f"{API}/{policy['id']}/vehicles/{link['id']}",
            json={"coverages": [_coverage("collision", deductible="1000.00")]},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        coverages = response.json()["vehicles"][0]["coverages"]
        assert [c["coverage_key"] for c in coverages] == ["collision"]
        assert coverages[0]["deductible"] == "1000.00"

    async def test_omitting_coverages_on_a_patch_leaves_them_alone(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        policy = await _create(
            client,
            auth_headers,
            [_on(owned_vehicle.vin, coverages=[_coverage("collision", deductible="500.00")])],
        )
        link = policy["vehicles"][0]
        response = await client.patch(
            f"{API}/{policy['id']}/vehicles/{link['id']}",
            json={"notes": "just a note"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert len(response.json()["vehicles"][0]["coverages"]) == 1

    async def test_renewing_carries_the_coverages_into_the_next_term(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        """Same insurer, next term: the coverage is the thing that does not change."""
        policy = await _create(
            client,
            auth_headers,
            [
                _on(
                    owned_vehicle.vin,
                    coverages=[
                        _coverage("collision", deductible="500.00", premium="299.00"),
                        _coverage("roadside_assistance"),
                    ],
                )
            ],
        )
        response = await client.post(
            f"{API}/{policy['id']}/renew",
            json={"premium_amount": "700.00"},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        coverages = response.json()["vehicles"][0]["coverages"]
        assert [c["coverage_key"] for c in coverages] == ["collision", "roadside_assistance"]
        assert coverages[0]["deductible"] == "500.00"

    async def test_renewing_tolerates_a_coverage_key_outside_the_catalogue(
        self, client: AsyncClient, auth_headers, owned_vehicle, db_session: AsyncSession
    ):
        """A key a newer catalogue added, met after a downgrade.

        Reading such a policy already drops the row rather than failing the
        whole read. Renewing validated the STORED rows against the catalogue
        instead, so it answered 500 and the household got no next term at all.
        """
        policy = await _create(
            client,
            auth_headers,
            [
                _on(
                    owned_vehicle.vin,
                    coverages=[
                        _coverage("collision", deductible="500.00"),
                        _coverage("glass"),
                    ],
                )
            ],
        )
        # A downgrade is the only way to get such a row, so write it the way a
        # downgrade leaves it: in the table, behind the schema's back.
        await db_session.execute(
            update(InsuranceCoverage)
            .where(InsuranceCoverage.coverage_key == "glass")
            .values(coverage_key="pet_injury")
        )
        await db_session.commit()

        read = await client.get(f"{API}/{policy['id']}", headers=auth_headers)
        assert read.status_code == 200, read.text
        assert [c["coverage_key"] for c in read.json()["vehicles"][0]["coverages"]] == ["collision"]

        response = await client.post(
            f"{API}/{policy['id']}/renew",
            json={"premium_amount": "700.00"},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        carried = response.json()["vehicles"][0]["coverages"]
        assert [c["coverage_key"] for c in carried] == ["collision"]

    async def test_switching_insurers_does_not_carry_the_old_coverages(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        """A new insurer writes new coverage; carrying the old would invent it."""
        policy = await _create(
            client,
            auth_headers,
            [_on(owned_vehicle.vin, coverages=[_coverage("collision", deductible="500.00")])],
        )
        today = household_today()
        response = await client.post(
            f"{API}/{policy['id']}/replace",
            json={
                "provider": "State Farm",
                "policy_number": "SF-1",
                "start_date": (today + timedelta(days=150)).isoformat(),
                "end_date": (today + timedelta(days=330)).isoformat(),
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        assert response.json()["vehicles"][0]["coverages"] == []

    async def test_an_untouched_vehicle_needs_no_write_access(
        self, client: AsyncClient, auth_headers, owned_vehicle
    ):
        """The form resends every vehicle; resending identical coverages is not
        an edit, so a reader-on-one-vehicle creator can still fix the provider."""
        policy = await _create(
            client,
            auth_headers,
            [
                _on(
                    owned_vehicle.vin,
                    coverages=[
                        _coverage("bodily_injury", limit_primary="100000.00"),
                        _coverage("collision", deductible="500.00"),
                    ],
                )
            ],
        )
        resent = [
            _on(
                owned_vehicle.vin,
                coverages=[
                    _coverage("collision", deductible="500.00"),
                    _coverage("bodily_injury", limit_primary="100000.00"),
                ],
            )
        ]
        response = await client.put(
            f"{API}/{policy['id']}",
            json={"provider": "Progressive Direct", "vehicles": resent},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["provider"] == "Progressive Direct"
