"""settings.updated_at and address_book.last_used are written in UTC (N-1).

Every other stamp is naive UTC, but these took the container's local clock, so
a container with a TZ stored them hours off on any database. Each test runs
with the process clock five hours west of UTC (`local_clock_off_utc`), where a
bare `datetime.now()` lands well outside the UTC window the test brackets.
"""

import datetime as dt
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address_book import AddressBookEntry
from app.models.settings import Setting
from app.services.oidc.config import write_oidc_config
from app.utils.datetime_utils import utc_now
from app.utils.fuel_station_sync import resolve_fuel_station
from app.utils.gas_station import GAS_STATION_POI

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: The shared `keep_rows` fixture: snapshot these settings keys, restore after.
KeepRows = Callable[..., Awaitable[None]]


def assert_utc_between(stamp: dt.datetime | None, before: dt.datetime, after: dt.datetime) -> None:
    """The stored stamp is inside the UTC window around the write."""
    assert stamp is not None
    assert before <= stamp <= after, (
        f"stored {stamp}, UTC window {before}..{after}: written in local time, not UTC"
    )


async def stored_setting(db: AsyncSession, key: str) -> tuple[str | None, dt.datetime]:
    """A settings row's value and updated_at as stored, not from the identity map.

    Plain values out, because the next call expires every loaded row.
    """
    db.expire_all()
    row = await db.get(Setting, key)
    assert row is not None
    return row.value, row.updated_at


async def drop_setting(db: AsyncSession, key: str) -> None:
    """Remove a row so the write under test has to create it."""
    await db.execute(delete(Setting).where(Setting.key == key))
    await db.commit()


async def seed_setting(db: AsyncSession, key: str, value: str) -> None:
    """Make sure a row exists, so the write under test updates it."""
    await drop_setting(db, key)
    db.add(Setting(key=key, value=value))
    await db.commit()


class AddressBookRows:
    """Address-book rows a test made or expects, deleted by the fixture after."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ids: list[int] = []
        # The fuel-station resolver can create its own row, so cleanup also
        # takes the names a test expects it to use.
        self.names: list[str] = []

    async def make(self, **fields: object) -> AddressBookEntry:
        """Insert and commit one row."""
        entry = AddressBookEntry(**fields)
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)
        self.ids.append(entry.id)
        return entry


@pytest_asyncio.fixture
async def address_book(db_session: AsyncSession) -> AsyncIterator[AddressBookRows]:
    """Track a test's address-book rows and delete them afterwards."""
    rows = AddressBookRows(db_session)
    yield rows
    await db_session.rollback()
    await db_session.execute(
        delete(AddressBookEntry).where(
            AddressBookEntry.id.in_(rows.ids) | AddressBookEntry.business_name.in_(rows.names)
        )
    )
    await db_session.commit()


def unique(prefix: str) -> str:
    """A business name no other test uses."""
    return f"{prefix} {uuid.uuid4().hex[:8]}"


@pytest.mark.usefixtures("local_clock_off_utc")
class TestSettingsUpdatedAtIsUtc:
    """The three generic settings writers and the OIDC writer."""

    async def test_create(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        keep_rows: KeepRows,
    ) -> None:
        await keep_rows("ntfy_server")
        await drop_setting(db_session, "ntfy_server")

        before = utc_now()
        response = await client.post(
            "/api/settings",
            headers=auth_headers,
            json={"key": "ntfy_server", "value": "https://ntfy.example"},
        )
        after = utc_now()

        assert response.status_code == 201, response.text
        _, updated_at = await stored_setting(db_session, "ntfy_server")
        assert_utc_between(updated_at, before, after)

    async def test_update(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        keep_rows: KeepRows,
    ) -> None:
        await keep_rows("ntfy_server")
        await seed_setting(db_session, "ntfy_server", "https://old.example")

        before = utc_now()
        response = await client.put(
            "/api/settings/ntfy_server",
            headers=auth_headers,
            json={"value": "https://ntfy.example"},
        )
        after = utc_now()

        assert response.status_code == 200, response.text
        value, updated_at = await stored_setting(db_session, "ntfy_server")
        assert value == "https://ntfy.example"
        assert_utc_between(updated_at, before, after)

    async def test_batch_updates_and_creates(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        keep_rows: KeepRows,
    ) -> None:
        # One key with a row (the update branch), one without (the create branch).
        await keep_rows("ntfy_server", "ntfy_topic")
        await seed_setting(db_session, "ntfy_server", "https://old.example")
        await drop_setting(db_session, "ntfy_topic")

        before = utc_now()
        response = await client.post(
            "/api/settings/batch",
            headers=auth_headers,
            json={"settings": {"ntfy_server": "https://ntfy.example", "ntfy_topic": "garage"}},
        )
        after = utc_now()

        assert response.status_code == 200, response.text
        updated_value, updated_at = await stored_setting(db_session, "ntfy_server")
        created_value, created_at = await stored_setting(db_session, "ntfy_topic")
        assert updated_value == "https://ntfy.example"
        assert created_value == "garage"
        assert_utc_between(updated_at, before, after)
        assert_utc_between(created_at, before, after)

    async def test_oidc_writer(self, db_session: AsyncSession, keep_rows: KeepRows) -> None:
        # Same two branches: provider_name has a row, admin_group doesn't.
        await keep_rows("oidc_provider_name", "oidc_admin_group")
        await seed_setting(db_session, "oidc_provider_name", "Old IdP")
        await drop_setting(db_session, "oidc_admin_group")

        before = utc_now()
        await write_oidc_config(db_session, {"provider_name": "Test IdP", "admin_group": "admins"})
        after = utc_now()

        updated_value, updated_at = await stored_setting(db_session, "oidc_provider_name")
        created_value, created_at = await stored_setting(db_session, "oidc_admin_group")
        assert updated_value == "Test IdP"
        assert created_value == "admins"
        assert_utc_between(updated_at, before, after)
        assert_utc_between(created_at, before, after)


@pytest.mark.usefixtures("local_clock_off_utc")
class TestAddressBookLastUsedIsUtc:
    """Every writer of address_book.last_used."""

    async def stored_last_used(self, db: AsyncSession, entry_id: int) -> dt.datetime | None:
        """An entry's last_used as stored, not from the identity map."""
        db.expire_all()
        entry = await db.get(AddressBookEntry, entry_id)
        assert entry is not None
        return entry.last_used

    async def test_fuel_station_pick(
        self, db_session: AsyncSession, address_book: AddressBookRows
    ) -> None:
        # Case 1: the caller picked an existing station by id.
        entry = await address_book.make(
            business_name=unique("Pick Station"), poi_category=GAS_STATION_POI
        )

        before = utc_now()
        resolved, _ = await resolve_fuel_station(
            db_session,
            station_address_book_id=entry.id,
            station_name_freetext=None,
            one_time_visit=False,
        )
        await db_session.commit()
        after = utc_now()

        assert resolved == entry.id
        assert_utc_between(await self.stored_last_used(db_session, entry.id), before, after)

    async def test_fuel_station_typed_name_matches_a_station(
        self, db_session: AsyncSession, address_book: AddressBookRows
    ) -> None:
        # Case 3, existing: a typed name that matches a saved station reuses it.
        name = unique("Typed Station")
        entry = await address_book.make(business_name=name, poi_category=GAS_STATION_POI)

        before = utc_now()
        resolved, _ = await resolve_fuel_station(
            db_session,
            station_address_book_id=None,
            station_name_freetext=name,
            one_time_visit=False,
        )
        await db_session.commit()
        after = utc_now()

        assert resolved == entry.id
        assert_utc_between(await self.stored_last_used(db_session, entry.id), before, after)

    async def test_fuel_station_typed_name_is_new(
        self, db_session: AsyncSession, address_book: AddressBookRows
    ) -> None:
        # Case 3, new: nothing matches, so the resolver creates the station.
        name = unique("New Station")
        address_book.names.append(name)

        before = utc_now()
        resolved, _ = await resolve_fuel_station(
            db_session,
            station_address_book_id=None,
            station_name_freetext=name,
            one_time_visit=False,
        )
        await db_session.commit()
        after = utc_now()

        assert resolved is not None
        assert_utc_between(await self.stored_last_used(db_session, resolved), before, after)

    @pytest.mark.parametrize(
        "route", ["/api/poi/increment-usage", "/api/shop-discovery/increment-usage"]
    )
    async def test_increment_usage(
        self,
        route: str,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        address_book: AddressBookRows,
    ) -> None:
        entry = await address_book.make(business_name=unique("Usage Shop"), category="service")

        before = utc_now()
        response = await client.post(f"{route}/{entry.id}", headers=auth_headers)
        after = utc_now()

        assert response.status_code == 204, response.text
        assert_utc_between(await self.stored_last_used(db_session, entry.id), before, after)
