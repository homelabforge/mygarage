"""One rule, four surfaces: which vehicles a caller may see in a LIST.

This is the read side of the authz rubric, and it had almost no coverage. The
rule lives in `auth.visible_vehicles_filter` and was restated inline at four
places; making that helper return None unconditionally (a full visibility
escalation, every caller sees every vehicle) failed exactly ONE test in a suite
of 5133, `test_calendar.py::test_calendar_excludes_non_owned_vehicles`. The main
vehicle list, garage analytics and the search/inbox pair caught nothing.

That is the same gap that let the admin branch go missing twice: search and the
notification inbox each grew a byte-identical copy of this condition WITHOUT it,
so an admin could open a vehicle's page but could not find it in search or
receive its reminder alerts. A rule with one test and four call sites is a rule
that gets re-derived slightly wrong.

So every surface is asserted here, in both directions, because the two failures
are opposites and a test for one does not see the other:

* a caller who should NOT see the vehicle does not (a leak), and
* a caller who SHOULD see it does (the admin branch going missing).

Calendar is listed for completeness and tested in `test_calendar.py`; it is the
one surface that was already pinned.
"""

import pytest

from app.services.auth import accessible_vehicles, visible_vehicles_filter

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class TestTheFilterItself:
    """The two cases that mean "no restriction" have to stay together.

    A caller that reads None as "deny" locks `auth_mode='none'` shut; one that
    forgets the admin half hides the garage from the only account meant to see
    all of it. Asserted on the helper directly because neither case is reachable
    through an authenticated request.
    """

    async def test_auth_disabled_is_unrestricted(self):
        assert visible_vehicles_filter(None) is None

    async def test_an_admin_is_unrestricted(self, admin_user):
        assert visible_vehicles_filter(admin_user) is None

    async def test_an_ordinary_user_is_restricted(self, owner_user):
        assert visible_vehicles_filter(owner_user) is not None


class TestTheVehicleList:
    """`GET /api/vehicles`, via `VehicleService.list_vehicles`.

    ★ The vin checks walk EVERY page, not one. The shared test database holds
    more vehicles than even the route's 500 maximum, so an admin's page 1 does
    not reach this fixture's vin. Worse than the false failure: an ABSENCE
    assertion on a truncated page passes for the wrong reason, because a leaked
    vehicle sitting on page 2 looks exactly like a vehicle that was correctly
    filtered out.
    """

    PAGE = "/api/vehicles?limit=500"

    async def _every_vin(self, client, headers) -> list[str]:
        """Every vin the caller's list returns, page by page up to its total."""
        vins: list[str] = []
        while True:
            resp = await client.get(f"{self.PAGE}&skip={len(vins)}", headers=headers)
            assert resp.status_code == 200
            body = resp.json()
            vins += [v["vin"] for v in body["vehicles"]]
            if not body["vehicles"] or len(vins) >= body["total"]:
                return vins

    async def test_a_stranger_does_not_see_it(self, client, owned_vehicle, unrelated_headers):
        assert owned_vehicle.vin not in await self._every_vin(client, unrelated_headers)

    async def test_the_total_is_scoped_like_the_list(
        self, client, owned_vehicle, unrelated_headers, admin_user_headers
    ):
        """The count is a SEPARATE query taking the same filter, so it can be
        scoped wrongly while the list beside it is scoped right. A scoped list
        reported with an unscoped total leaks how many vehicles exist and
        paginates the caller through pages that render empty.

        Compared against an admin rather than against the owner: the owner sees
        one vehicle and so might a stranger who owns one from another test, which
        made an earlier version of this assertion fail on a full-suite run for a
        reason that had nothing to do with scoping.
        """
        stranger = await client.get(self.PAGE, headers=unrelated_headers)
        admin = await client.get(self.PAGE, headers=admin_user_headers)
        assert stranger.status_code == 200 and admin.status_code == 200

        stranger_body, admin_body = stranger.json(), admin.json()
        assert stranger_body["total"] == len(stranger_body["vehicles"])
        # An unscoped count would report the admin's number to the stranger.
        assert stranger_body["total"] < admin_body["total"]

    async def test_a_read_share_sees_it(self, client, owned_vehicle, reader_headers):
        assert owned_vehicle.vin in await self._every_vin(client, reader_headers)

    async def test_an_admin_sees_it(self, client, owned_vehicle, admin_user_headers):
        assert owned_vehicle.vin in await self._every_vin(client, admin_user_headers)


class TestGarageAnalytics:
    """`GET /api/analytics/garage`.

    Asserted on `cost_by_vehicle`, which carries a vin per visible vehicle and
    is built unconditionally, rather than on `vehicle_count`: the count moves
    with whatever else the shared test database holds, and a leak has to be
    provable against one known vin.
    """

    async def test_a_stranger_does_not_see_it(self, client, owned_vehicle, unrelated_headers):
        resp = await client.get("/api/analytics/garage", headers=unrelated_headers)
        assert resp.status_code == 200
        assert owned_vehicle.vin not in [v["vin"] for v in resp.json()["cost_by_vehicle"]]

    async def test_an_admin_sees_it(self, client, owned_vehicle, admin_user_headers):
        resp = await client.get("/api/analytics/garage", headers=admin_user_headers)
        assert resp.status_code == 200
        assert owned_vehicle.vin in [v["vin"] for v in resp.json()["cost_by_vehicle"]]


class TestSearchAndTheInbox:
    """`GET /api/search` and `GET /api/notifications/inbox`.

    Both call `accessible_vehicles`, which is where their shared history of
    getting this wrong lives. Search is driven end to end; the inbox is covered
    at `accessible_vehicles` rather than through its endpoint, because an inbox
    item needs a pending reminder and it is the VEHICLE SET, not the reminder
    projection, that this file is about.
    """

    async def test_search_does_not_return_a_strangers_vehicle(
        self, client, owned_vehicle, unrelated_headers
    ):
        resp = await client.get("/api/search?q=Authz", headers=unrelated_headers)
        assert resp.status_code == 200
        hits = resp.json()["results"]
        assert owned_vehicle.vin not in [h.get("vin") for h in hits]

    async def test_search_returns_it_for_an_admin(self, client, owned_vehicle, admin_user_headers):
        """The exact bug the helper's docstring records: the copy in search
        omitted the admin branch, so an admin could open a vehicle's page and
        still not find it here."""
        resp = await client.get("/api/search?q=Authz", headers=admin_user_headers)
        assert resp.status_code == 200
        assert owned_vehicle.vin in [h.get("vin") for h in resp.json()["results"]]

    async def test_the_shared_reader_excludes_a_stranger(
        self, db_session, owned_vehicle, unrelated_user
    ):
        vins = [v.vin for v in await accessible_vehicles(db_session, unrelated_user)]
        assert owned_vehicle.vin not in vins

    async def test_the_shared_reader_includes_an_admin(self, db_session, owned_vehicle, admin_user):
        vins = [v.vin for v in await accessible_vehicles(db_session, admin_user)]
        assert owned_vehicle.vin in vins

    async def test_the_shared_reader_includes_a_read_share(
        self, db_session, owned_vehicle, reader_user
    ):
        vins = [v.vin for v in await accessible_vehicles(db_session, reader_user)]
        assert owned_vehicle.vin in vins
