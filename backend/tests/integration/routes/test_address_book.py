"""
Integration tests for address book routes.

Tests address book CRUD operations and vendor sync side-effects.
"""

import logging
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address_book import AddressBookEntry
from app.models.vendor import Vendor
from tests._logged import problems


async def _offered_to_fill_up(client: AsyncClient, headers: dict, search: str) -> list[str]:
    """The names the fill-up's station picker is offered for this search."""
    response = await client.get(
        "/api/address-book",
        params={"search": search, "poi_category": "gas_station"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return [e["business_name"] for e in response.json()["entries"]]


async def _stored_category(db_session: AsyncSession, entry_id: int) -> str | None:
    """The category as the database holds it, not as a response renders it."""
    result = await db_session.execute(
        select(AddressBookEntry.category).where(AddressBookEntry.id == entry_id)
    )
    return result.scalar_one()


async def _delete_named(db_session: AsyncSession, name: str) -> None:
    """Remove a test's entries and the vendor a non-station create syncs."""
    await db_session.rollback()
    await db_session.execute(delete(AddressBookEntry).where(AddressBookEntry.business_name == name))
    await db_session.execute(delete(Vendor).where(Vendor.name == name))
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestAddressBookRoutes:
    """Test address book API endpoints."""

    async def test_list_entries(self, client: AsyncClient, auth_headers):
        """Test listing address book entries."""
        response = await client.get("/api/address-book", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert "total" in data
        assert isinstance(data["entries"], list)

    async def test_create_entry(self, client: AsyncClient, auth_headers):
        """Test creating a new address book entry."""
        payload = {
            "name": "John Smith",
            "business_name": "Smith Auto Repair",
            "address": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip_code": "62701",
            "phone": "555-123-4567",
            "email": "john@smithauto.com",
            "website": "https://smithauto.com",
            "category": "service",
            "notes": "Great service, reasonable prices.",
        }
        response = await client.post(
            "/api/address-book",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == payload["name"]
        assert data["business_name"] == payload["business_name"]
        assert data["city"] == payload["city"]
        assert "id" in data

    async def test_get_entry_by_id(self, client: AsyncClient, auth_headers):
        """Test retrieving a specific address book entry."""
        # Create an entry
        create_response = await client.post(
            "/api/address-book",
            json={
                "business_name": "Test Shop",
                "city": "Test City",
                "category": "service",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        # Get the entry
        response = await client.get(
            f"/api/address-book/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        assert data["business_name"] == "Test Shop"

    async def test_update_entry(self, client: AsyncClient, auth_headers):
        """Test updating an address book entry."""
        # Create an entry
        create_response = await client.post(
            "/api/address-book",
            json={
                "business_name": "Original Name",
                "city": "Original City",
                "category": "parts",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update the entry
        update_data = {
            "business_name": "Updated Name",
            "city": "Updated City",
            "phone": "555-999-8888",
        }

        response = await client.put(
            f"/api/address-book/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["business_name"] == "Updated Name"
        assert data["city"] == "Updated City"
        assert data["phone"] == "555-999-8888"
        # Category unchanged
        assert data["category"] == "parts"

    async def test_delete_entry(self, client: AsyncClient, auth_headers):
        """Test deleting an address book entry."""
        # Create an entry
        create_response = await client.post(
            "/api/address-book",
            json={
                "business_name": "To Be Deleted",
                "city": "Deleteville",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Delete the entry
        response = await client.delete(
            f"/api/address-book/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/address-book/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_entry_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot access address book."""
        response = await client.get("/api/address-book")

        assert response.status_code == 401

    async def test_entry_not_found(self, client: AsyncClient, auth_headers):
        """Test get entry with non-existent ID."""
        response = await client.get(
            "/api/address-book/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_search_entries(self, client: AsyncClient, auth_headers):
        """Test searching address book entries."""
        # Create entries with different names
        await client.post(
            "/api/address-book",
            json={"business_name": "Acme Auto Parts", "city": "Chicago"},
            headers=auth_headers,
        )
        await client.post(
            "/api/address-book",
            json={"business_name": "Best Tire Shop", "city": "Chicago"},
            headers=auth_headers,
        )

        # Search for "Acme"
        response = await client.get(
            "/api/address-book",
            params={"search": "Acme"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Should find the Acme entry
        matching = [e for e in data["entries"] if "Acme" in e.get("business_name", "")]
        assert len(matching) >= 1

    async def test_filter_by_category(self, client: AsyncClient, auth_headers):
        """Test filtering entries by category."""
        # Create entries with different categories
        await client.post(
            "/api/address-book",
            json={"business_name": "Service Shop A", "category": "service"},
            headers=auth_headers,
        )
        await client.post(
            "/api/address-book",
            json={"business_name": "Parts Store B", "category": "parts"},
            headers=auth_headers,
        )

        # Filter by category
        response = await client.get(
            "/api/address-book",
            params={"category": "service"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All results should have category "service"
        for entry in data["entries"]:
            assert entry.get("category") == "service"

    async def test_create_minimal_entry(self, client: AsyncClient, auth_headers):
        """Test creating entry with minimal fields."""
        payload = {
            "business_name": "Minimal Entry",
        }
        response = await client.post(
            "/api/address-book",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["business_name"] == "Minimal Entry"
        assert data["name"] is None
        assert data["city"] is None

    async def test_update_partial(self, client: AsyncClient, auth_headers):
        """Test partial update of entry."""
        # Create an entry
        create_response = await client.post(
            "/api/address-book",
            json={
                "business_name": "Full Entry",
                "city": "Full City",
                "state": "FC",
                "phone": "111-222-3333",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update only phone
        response = await client.put(
            f"/api/address-book/{record['id']}",
            json={"phone": "999-888-7777"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Only phone changed
        assert data["phone"] == "999-888-7777"
        # Others unchanged
        assert data["business_name"] == "Full Entry"
        assert data["city"] == "Full City"
        assert data["state"] == "FC"

    async def test_delete_not_found(self, client: AsyncClient, auth_headers):
        """Test deleting non-existent entry."""
        response = await client.delete(
            "/api/address-book/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_update_not_found(self, client: AsyncClient, auth_headers):
        """Test updating non-existent entry."""
        response = await client.put(
            "/api/address-book/99999",
            json={"business_name": "Does Not Exist"},
            headers=auth_headers,
        )

        assert response.status_code == 404

    # --- Vendor sync side-effect tests ---

    async def test_create_syncs_to_vendor(self, client: AsyncClient, auth_headers):
        """Creating an address book entry with a business_name should create a matching vendor."""
        business_name = "B&T RV Repair Test Sync"
        response = await client.post(
            "/api/address-book",
            json={
                "business_name": business_name,
                "address": "100 Repair Rd",
                "city": "Camptown",
                "state": "TX",
                "zip_code": "77001",
                "phone": "555-700-1234",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201

        # Vendor should now appear in vendor search
        vendor_response = await client.get(
            "/api/vendors",
            params={"search": "B&T RV Repair Test Sync"},
            headers=auth_headers,
        )
        assert vendor_response.status_code == 200
        vendors = vendor_response.json()["vendors"]
        assert any(v["name"] == business_name for v in vendors)

    async def test_create_no_duplicate_vendor(self, client: AsyncClient, auth_headers):
        """Creating address book entries with the same business_name should produce only one vendor."""
        business_name = "Duplicate Shop Test"
        for _ in range(2):
            await client.post(
                "/api/address-book",
                json={"business_name": business_name, "city": "Anytown"},
                headers=auth_headers,
            )

        vendor_response = await client.get(
            "/api/vendors",
            params={"search": business_name},
            headers=auth_headers,
        )
        assert vendor_response.status_code == 200
        vendors = [v for v in vendor_response.json()["vendors"] if v["name"] == business_name]
        assert len(vendors) == 1, f"Expected 1 vendor, found {len(vendors)}"

    async def test_create_vendor_sync_failure_does_not_fail_create(
        self, client: AsyncClient, auth_headers, caplog, caplog_only
    ):
        """A failure in vendor sync (savepoint) must not abort the address book create."""
        with (
            caplog_only("app.routes.address_book"),
            patch(
                "app.routes.address_book._sync_to_vendor",
                new_callable=AsyncMock,
                side_effect=Exception("simulated vendor sync failure"),
            ),
        ):
            response = await client.post(
                "/api/address-book",
                json={"business_name": "Sync Failure Shop", "city": "Failtown"},
                headers=auth_headers,
            )

        # Address book entry must still be created despite sync failure
        assert response.status_code == 201
        assert response.json()["business_name"] == "Sync Failure Shop"
        (logged,) = problems(caplog, "app.routes.address_book")
        assert logged.levelno == logging.ERROR
        assert logged.exc_info is not None
        assert str(logged.exc_info[1]) == "simulated vendor sync failure"

    async def test_update_syncs_new_business_name_to_vendor(
        self, client: AsyncClient, auth_headers
    ):
        """Updating an address book entry's business_name should create a vendor for the new name."""
        # Create with initial name (will also create a vendor)
        create_response = await client.post(
            "/api/address-book",
            json={"business_name": "Old Shop Name Test", "city": "Oldtown"},
            headers=auth_headers,
        )
        entry_id = create_response.json()["id"]

        # Update to a new name
        new_name = "New Shop Name Test"
        await client.put(
            f"/api/address-book/{entry_id}",
            json={"business_name": new_name},
            headers=auth_headers,
        )

        # New name should appear as a vendor
        vendor_response = await client.get(
            "/api/vendors",
            params={"search": new_name},
            headers=auth_headers,
        )
        assert vendor_response.status_code == 200
        vendors = vendor_response.json()["vendors"]
        assert any(v["name"] == new_name for v in vendors)

    # --- poi_category clear/preserve/guard tests (#108) ---

    async def test_update_null_clears_gas_station(self, client: AsyncClient, auth_headers):
        """PUT poi_category=null clears an existing gas_station tag."""
        created = (
            await client.post(
                "/api/address-book",
                json={"business_name": "Shell", "poi_category": "gas_station"},
                headers=auth_headers,
            )
        ).json()
        resp = await client.put(
            f"/api/address-book/{created['id']}",
            json={"poi_category": None},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["poi_category"] is None

    async def test_update_null_does_not_clobber_non_gas_category(
        self, client: AsyncClient, auth_headers
    ):
        """A gas/clear payload must NOT erase an auto_shop tag (stale-snapshot guard)."""
        created = (
            await client.post(
                "/api/address-book",
                json={"business_name": "Joe Auto", "poi_category": "auto_shop"},
                headers=auth_headers,
            )
        ).json()
        resp = await client.put(
            f"/api/address-book/{created['id']}",
            json={"poi_category": None},  # what a stale gas-context form would send
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["poi_category"] == "auto_shop"  # preserved

    async def test_update_omitting_poi_category_preserves_it(
        self, client: AsyncClient, auth_headers
    ):
        """An ordinary edit that omits poi_category leaves it untouched."""
        created = (
            await client.post(
                "/api/address-book",
                json={"business_name": "EV Spot", "poi_category": "ev_charging"},
                headers=auth_headers,
            )
        ).json()
        resp = await client.put(
            f"/api/address-book/{created['id']}",
            json={"city": "Springfield"},  # no poi_category key
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["poi_category"] == "ev_charging"

    async def test_update_sets_gas_station(self, client: AsyncClient, auth_headers):
        """An explicit gas_station on an untagged entry sets it."""
        created = (
            await client.post(
                "/api/address-book", json={"business_name": "New Fuel"}, headers=auth_headers
            )
        ).json()
        resp = await client.put(
            f"/api/address-book/{created['id']}",
            json={"poi_category": "gas_station"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["poi_category"] == "gas_station"

    async def test_gas_station_filter_returns_canonical_entries(
        self, client: AsyncClient, auth_headers
    ):
        """Behavioral proof the canonical READ path works end-to-end: a
        gas_station entry is returned by the ?poi_category=gas_station filter
        (guards against any reader left on the retired value; Codex R1-H1)."""
        await client.post(
            "/api/address-book",
            json={"business_name": "Canonical Fuel", "poi_category": "gas_station"},
            headers=auth_headers,
        )
        resp = await client.get("/api/address-book?poi_category=gas_station", headers=auth_headers)
        assert resp.status_code == 200
        names = [e["business_name"] for e in resp.json()["entries"]]
        assert "Canonical Fuel" in names

    # --- A gas station saved on the Address Book page (#194) ---

    @pytest.mark.parametrize(
        "category", ["Gas Station", "  gas station "], ids=["chip-value", "padded-lowercase"]
    )
    async def test_a_manual_gas_station_is_offered_to_the_fill_up(
        self, client: AsyncClient, auth_headers, db_session, category
    ):
        """The Address Book page saves category "Gas Station" and no poi_category,
        and the fill-up's picker asks ?poi_category=gas_station, so it never saw it."""
        name = f"ZZ Manual Fuel {uuid.uuid4().hex[:8]}"
        try:
            created = await client.post(
                "/api/address-book",
                json={"business_name": name, "category": category},
                headers=auth_headers,
            )
            assert created.status_code == 201, created.text
            assert created.json()["poi_category"] is None

            response = await client.get(
                "/api/address-book",
                params={"search": "ZZ Manual Fuel", "poi_category": "gas_station"},
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert name in [e["business_name"] for e in body["entries"]]
            # The list isn't paged, so total has to count exactly what came back.
            assert body["total"] == len(body["entries"])
        finally:
            await db_session.rollback()
            await db_session.execute(
                delete(AddressBookEntry).where(AddressBookEntry.business_name == name)
            )
            # Before #194 the create copied the station into vendors too.
            await db_session.execute(delete(Vendor).where(Vendor.name == name))
            await db_session.commit()

    async def test_a_manual_gas_station_is_not_copied_into_vendors(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """Vendor sync skipped poi_category stations only, so every station added on
        the Address Book page landed in the vendor list as well."""
        name = f"ZZ Manual Fuel {uuid.uuid4().hex[:8]}"
        try:
            created = await client.post(
                "/api/address-book",
                json={"business_name": name, "category": "Gas Station"},
                headers=auth_headers,
            )
            assert created.status_code == 201, created.text

            vendors = (
                (await db_session.execute(select(Vendor).where(Vendor.name == name)))
                .scalars()
                .all()
            )
            assert vendors == []
        finally:
            await db_session.rollback()
            await db_session.execute(
                delete(AddressBookEntry).where(AddressBookEntry.business_name == name)
            )
            await db_session.execute(delete(Vendor).where(Vendor.name == name))
            await db_session.commit()

    # --- A category with whitespace round it (#194) ---

    @pytest.mark.parametrize(
        "category",
        ["Gas Station\t", " Gas Station", "Gas Station "],
        ids=["trailing-tab", "leading-space", "trailing-nbsp"],
    )
    async def test_create_strips_the_category_so_the_fill_up_offers_it(
        self, client: AsyncClient, auth_headers, db_session, category
    ):
        """SQL trim() strips spaces only, so a tab or NBSP from the API kept a station
        off the fill-up while the page, trimming in JS, showed it as a Gas Station."""
        name = f"ZZ Padded Fuel {uuid.uuid4().hex[:8]}"
        try:
            created = await client.post(
                "/api/address-book",
                json={"business_name": name, "category": category},
                headers=auth_headers,
            )
            assert created.status_code == 201, created.text
            assert await _stored_category(db_session, created.json()["id"]) == "Gas Station"
            assert name in await _offered_to_fill_up(client, auth_headers, "ZZ Padded Fuel")
        finally:
            await _delete_named(db_session, name)

    @pytest.mark.parametrize(
        "category",
        ["Gas Station\t", " Gas Station", "Gas Station "],
        ids=["trailing-tab", "leading-space", "trailing-nbsp"],
    )
    async def test_update_strips_the_category_so_the_fill_up_offers_it(
        self, client: AsyncClient, auth_headers, db_session, category
    ):
        """Same as the create, through an edit."""
        name = f"ZZ Padded Fuel {uuid.uuid4().hex[:8]}"
        try:
            created = await client.post(
                "/api/address-book",
                json={"business_name": name, "category": "Parts"},
                headers=auth_headers,
            )
            assert created.status_code == 201, created.text
            entry_id = created.json()["id"]
            updated = await client.put(
                f"/api/address-book/{entry_id}",
                json={"category": category},
                headers=auth_headers,
            )
            assert updated.status_code == 200, updated.text
            assert await _stored_category(db_session, entry_id) == "Gas Station"
            assert name in await _offered_to_fill_up(client, auth_headers, "ZZ Padded Fuel")
        finally:
            await _delete_named(db_session, name)

    async def test_an_all_whitespace_category_is_stored_as_none(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """Stripped to nothing, the optional category is none rather than an empty string."""
        name = f"ZZ Blank Category {uuid.uuid4().hex[:8]}"
        try:
            created = await client.post(
                "/api/address-book",
                json={"business_name": name, "category": " \t "},
                headers=auth_headers,
            )
            assert created.status_code == 201, created.text
            entry_id = created.json()["id"]
            assert await _stored_category(db_session, entry_id) is None

            await client.put(
                f"/api/address-book/{entry_id}", json={"category": "Parts"}, headers=auth_headers
            )
            updated = await client.put(
                f"/api/address-book/{entry_id}", json={"category": "\t "}, headers=auth_headers
            )
            assert updated.status_code == 200, updated.text
            assert await _stored_category(db_session, entry_id) is None
        finally:
            await _delete_named(db_session, name)

    async def test_a_gas_station_refiled_as_service_stops_being_one(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """What the Address Book form sends when a gas station is saved under another
        chip. The page reads it as Service, so the fill-up stops offering it and it
        syncs to vendors like any other Service entry."""
        name = f"ZZ Refiled Station {uuid.uuid4().hex[:8]}"
        vendors_named = select(Vendor.name).where(Vendor.name == name)
        try:
            created = await client.post(
                "/api/address-book",
                json={"business_name": name, "poi_category": "gas_station"},
                headers=auth_headers,
            )
            assert created.status_code == 201, created.text
            # Both halves have to start true, or the after-state proves nothing.
            assert name in await _offered_to_fill_up(client, auth_headers, "ZZ Refiled Station")
            assert (await db_session.execute(vendors_named)).scalars().all() == []

            updated = await client.put(
                f"/api/address-book/{created.json()['id']}",
                json={"category": "Service", "poi_category": None},
                headers=auth_headers,
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["category"] == "Service"
            assert updated.json()["poi_category"] is None
            assert name not in await _offered_to_fill_up(client, auth_headers, "ZZ Refiled Station")
            assert (await db_session.execute(vendors_named)).scalars().all() == [name]
        finally:
            await _delete_named(db_session, name)

    async def test_create_with_an_empty_poi_category_stores_none(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """The update route already mapped "" to NULL; create stored it as is."""
        name = f"Empty Create Category {uuid.uuid4().hex[:8]}"
        try:
            response = await client.post(
                "/api/address-book",
                json={"business_name": name, "poi_category": ""},
                headers=auth_headers,
            )
            assert response.status_code == 201, response.text
            stored = (
                await db_session.execute(
                    select(AddressBookEntry.poi_category).where(
                        AddressBookEntry.id == response.json()["id"]
                    )
                )
            ).one()
            assert stored.poi_category is None
        finally:
            await db_session.rollback()
            await db_session.execute(
                delete(AddressBookEntry).where(AddressBookEntry.business_name == name)
            )
            # The create syncs a vendor of the same name.
            await db_session.execute(delete(Vendor).where(Vendor.name == name))
            await db_session.commit()

    async def test_update_empty_string_poi_category_normalizes_to_null(
        self, client: AsyncClient, auth_headers
    ):
        """Explicit empty-string poi_category should normalize to NULL on update."""
        created = (
            await client.post(
                "/api/address-book",
                json={"business_name": "String Clear Test", "poi_category": "gas_station"},
                headers=auth_headers,
            )
        ).json()
        resp = await client.put(
            f"/api/address-book/{created['id']}",
            json={"poi_category": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["poi_category"] is None


_CLEARABLE = {
    "name": "Joe",
    "address": "1 Main St",
    "city": "Springfield",
    "state": "IL",
    "zip_code": "62701",
    "phone": "555-0100",
    "email": "joe@example.com",
    "website": "https://joe.example",
    "category": "service",
    "notes": "ask for Joe",
    "latitude": 39.78,
    "longitude": -89.65,
    "external_id": "osm-1",
    "rating": 4.5,
    "user_rating": 4,
    "poi_metadata": '{"k": 1}',
}


@pytest.mark.integration
@pytest.mark.asyncio
class TestAddressBookClearOnEdit:
    """An explicit null clears; an omitted field keeps. Every field used to be
    `if x is not None`, and email/website turn '' into None first, so a
    cleared email or website said saved and stayed."""

    async def _entry(self, client: AsyncClient, headers) -> dict:
        r = await client.post(
            "/api/address-book",
            json={"business_name": "Clear Test Shop", **_CLEARABLE},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        return r.json()

    async def _cleanup(self, client: AsyncClient, headers, entry_id: int) -> None:
        await client.delete(f"/api/address-book/{entry_id}", headers=headers)

    @pytest.mark.parametrize("field", sorted(_CLEARABLE))
    async def test_null_clears_the_field(self, client, auth_headers, field):
        entry = await self._entry(client, auth_headers)
        try:
            url = f"/api/address-book/{entry['id']}"
            r = await client.put(url, json={field: None}, headers=auth_headers)
            assert r.status_code == 200, r.text
            stored = (await client.get(url, headers=auth_headers)).json()
            assert stored[field] is None
            for other in _CLEARABLE:
                if other != field:
                    assert stored[other] is not None, other
        finally:
            await self._cleanup(client, auth_headers, entry["id"])

    @pytest.mark.parametrize("field", ["email", "website"])
    async def test_an_emptied_email_or_website_clears(self, client, auth_headers, field):
        # What the form actually posts for an emptied input.
        entry = await self._entry(client, auth_headers)
        try:
            url = f"/api/address-book/{entry['id']}"
            r = await client.put(url, json={field: ""}, headers=auth_headers)
            assert r.status_code == 200, r.text
            assert (await client.get(url, headers=auth_headers)).json()[field] is None
        finally:
            await self._cleanup(client, auth_headers, entry["id"])

    async def test_omitted_fields_are_kept(self, client, auth_headers):
        entry = await self._entry(client, auth_headers)
        try:
            url = f"/api/address-book/{entry['id']}"
            r = await client.put(url, json={"notes": "new"}, headers=auth_headers)
            assert r.status_code == 200, r.text
            stored = (await client.get(url, headers=auth_headers)).json()
            assert stored["notes"] == "new"
            assert stored["email"] == "joe@example.com"
            assert stored["source"] == entry["source"]
        finally:
            await self._cleanup(client, auth_headers, entry["id"])

    @pytest.mark.parametrize("field", ["business_name", "source"])
    async def test_null_on_a_required_field_is_a_422(self, client, auth_headers, field):
        entry = await self._entry(client, auth_headers)
        try:
            url = f"/api/address-book/{entry['id']}"
            r = await client.put(url, json={field: None}, headers=auth_headers)
            assert r.status_code == 422, r.text
            assert (await client.get(url, headers=auth_headers)).json()[field] == entry[field]
        finally:
            await self._cleanup(client, auth_headers, entry["id"])
