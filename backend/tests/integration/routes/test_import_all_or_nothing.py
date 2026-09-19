"""An import writes all of its rows or none of them, on SQLite as on PostgreSQL.

Every import row runs in its own savepoint, so a row the database rejects is
reported alone. On production's SQLite configuration (pysqlite's legacy
transaction control) a SAVEPOINT issued with no transaction open starts one,
and its RELEASE commits it: each row was committed the moment it finished,
and a failure later in the request left the rows before it behind.
PostgreSQL rolled the same import back whole. Each import route now takes the
vehicle write lock before its first write. On SQLite that is `BEGIN
IMMEDIATE`, so every savepoint nests inside one transaction that the route's
single commit ends and a failure rolls back.

What survived a request is always read through a separate session, never the
route's own, which would see its uncommitted rows.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.routes.import_data as import_data_module
from app.database import get_db
from app.main import app
from app.models import (
    DEFRecord,
    FuelRecord,
    HoursRecord,
    InsurancePolicy,
    InsurancePolicyVehicle,
    Note,
    OdometerRecord,
    Reminder,
    ServiceLineItem,
    ServiceVisit,
    TaxRecord,
    Vendor,
    WarrantyRecord,
)
from app.models.vehicle import Vehicle
from app.services.vehicle_lock import lock_vehicle_for_write

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_VIN_TABLES = (
    ServiceVisit,
    FuelRecord,
    DEFRecord,
    OdometerRecord,
    HoursRecord,
    WarrantyRecord,
    # Insurance is a household record since migration 107: the vin-bearing row
    # an import writes is the vehicle's LINK to a policy.
    InsurancePolicyVehicle,
    TaxRecord,
    Note,
    Reminder,
)


@dataclass(frozen=True)
class ImportCall:
    """One upload to one import route, valid enough to import at least one row."""

    route: str
    filename: str
    body: str
    content_type: str = "text/csv"
    form: dict[str, str] = field(default_factory=dict[str, str])

    def url(self, vin: str) -> str:
        return self.route.replace("{vin}", vin)


def _backup(vin: str) -> str:
    """A vehicle JSON backup with one valid row in every section."""
    return json.dumps(
        {
            "export_version": "3",
            "units": "metric",
            "service_records": [
                {
                    "date": "2027-09-01",
                    "odometer_km": 1000,
                    "service_type": "Oil",
                    "cost": 10,
                    "vendor_name": f"{vin}-json",
                }
            ],
            "fuel_records": [{"date": "2027-09-02", "odometer_km": 1100, "liters": 40}],
            "def_records": [{"date": "2027-09-03", "odometer_km": 1200, "liters": 9}],
            "odometer_records": [{"date": "2027-09-04", "odometer_km": 1300}],
            "reminders": [{"description": "Oil", "is_recurring": True, "recurrence_miles": 5000}],
            "notes": [{"date": "2027-09-05", "title": "Note", "content": "body"}],
        }
    )


def _every_import(vin: str) -> list[ImportCall]:
    """One call to every import route, in the order the router declares them."""
    base = "/api/import/vehicles/{vin}"
    return [
        ImportCall(
            f"{base}/service/csv",
            "service.csv",
            f"Date,Category,Odometer (km),Cost,Vendor\n2027-08-01,Maintenance,1000,10,{vin}-csv\n",
        ),
        ImportCall(
            f"{base}/fuel/csv",
            "fuel.csv",
            "Date,Odometer (km),Liters,Price Per Liter,Total Cost,Full Tank\n"
            "2027-08-02,1100,40,1.50,60,True\n",
        ),
        ImportCall(
            f"{base}/def/csv",
            "def.csv",
            "Date,Odometer (km),Liters,Price Per Unit,Total Cost\n2027-08-03,1200,9,1.10,9.90\n",
        ),
        ImportCall(f"{base}/odometer/csv", "odometer.csv", "Date,Reading (km)\n2027-08-04,1300\n"),
        ImportCall(f"{base}/hours/csv", "hours.csv", "Date,Engine Hours\n2027-08-05,55.5\n"),
        ImportCall(
            f"{base}/warranties/csv",
            "warranties.csv",
            "Provider,Type,Start Date,End Date\nAtomCo,Extended,2027-01-01,2029-01-01\n",
        ),
        ImportCall(
            f"{base}/insurance/csv",
            "insurance.csv",
            "Provider,Policy Number,Type,Start Date,End Date\n"
            f"Atom,{vin},Liability,2027-01-01,2028-01-01\n",
        ),
        ImportCall(
            f"{base}/tax/csv",
            "tax.csv",
            "Date,Type,Amount,Renewal Date\n2027-08-06,Registration,212.00,2028-08-06\n",
        ),
        ImportCall(f"{base}/notes/csv", "notes.csv", "Date,Title,Content\n2027-08-07,Note,body\n"),
        ImportCall(f"{base}/json", "vehicle.json", _backup(vin), "application/json"),
        ImportCall(
            f"{base}/fuel/fuelio",
            "fuelio.csv",
            "Date,Odometer,Liters,Price,Total cost\n2027-08-08,1400,40,1.50,60.00\n",
        ),
        ImportCall(
            f"{base}/fuel/drivvo",
            "drivvo.csv",
            "Date,Odometer (km),Quantity (liters),Total cost\n2027-08-09,1500,40,60.00\n",
        ),
        ImportCall(
            f"{base}/fuel/tesla",
            "tesla.csv",
            "Charge Start Date,Charge End Date,Energy Added (kWh),Cost\n"
            "2027-08-10 08:00:00,2027-08-10 08:45:00,30.0,9.00\n",
        ),
        ImportCall(
            f"{base}/fuel/external",
            "external.csv",
            "Date,Odometer,Liters,Price,Total cost\n2027-08-11,1600,40,1.50,60.00\n",
            form={"format": "fuelio"},
        ),
    ]


def _imported_rows(response_json: dict[str, Any]) -> int:
    """How many rows a successful import reports, for either response shape."""
    if "success_count" in response_json:
        return int(response_json["success_count"])
    return sum(
        int(bucket["success_count"])
        for bucket in response_json.values()
        if isinstance(bucket, dict) and "success_count" in bucket
    )


async def _post(client: AsyncClient, headers: dict[str, str], vin: str, call: ImportCall):
    return await client.post(
        call.url(vin),
        headers=headers,
        files={"file": (call.filename, call.body.encode(), call.content_type)},
        data={"skip_duplicates": "true", **call.form},
    )


async def _rows_for(session: AsyncSession, vin: str) -> dict[str, int]:
    """Every table this file imports into that holds a row for `vin`, with its count."""
    found: dict[str, int] = {}
    for model in _VIN_TABLES:
        n = (
            await session.execute(select(func.count()).select_from(model).where(model.vin == vin))
        ).scalar_one()
        if n:
            found[model.__tablename__] = int(n)
    vendors = (
        await session.execute(
            select(func.count()).select_from(Vendor).where(Vendor.name.like(f"{vin}-%"))
        )
    ).scalar_one()
    if vendors:
        found["vendors"] = int(vendors)
    return found


async def _committed_rows(sessionmaker: async_sessionmaker[AsyncSession], vin: str):
    """`_rows_for`, read through a fresh session: only what was committed."""
    async with sessionmaker() as fresh:
        return await _rows_for(fresh, vin)


@pytest.fixture(autouse=True)
def _reset_import_rate_limit():
    """Clear the shared import limiter; one test here posts to every import route."""
    from app.routes.import_data import limiter

    storage = limiter._storage
    storage.storage.clear()
    storage.expirations.clear()
    if hasattr(storage, "events"):
        storage.events.clear()


@pytest_asyncio.fixture
async def vin(db_session: AsyncSession, test_user, test_sessionmaker) -> AsyncIterator[str]:
    """A committed diesel vehicle of the test user's, and every row imported into it removed."""
    value = f"ATOM{uuid.uuid4().hex[:13].upper()}"
    db_session.add(
        Vehicle(
            vin=value,
            user_id=test_user["id"],
            nickname="Atomic",
            vehicle_type="Car",
            fuel_type="diesel",
        )
    )
    await db_session.commit()
    yield value
    await db_session.rollback()
    async with test_sessionmaker() as cleanup:
        visit_ids = select(ServiceVisit.id).where(ServiceVisit.vin == value)
        await cleanup.execute(
            delete(ServiceLineItem).where(ServiceLineItem.visit_id.in_(visit_ids))
        )
        # Rows that point at a fuel record or a service visit go first.
        # The policies first, while their links still say which they are.
        await cleanup.execute(
            delete(InsurancePolicy).where(
                InsurancePolicy.id.in_(
                    select(InsurancePolicyVehicle.policy_id).where(
                        InsurancePolicyVehicle.vin == value
                    )
                )
            )
        )
        for model in (
            OdometerRecord,
            HoursRecord,
            DEFRecord,
            Reminder,
            ServiceVisit,
            FuelRecord,
            WarrantyRecord,
            InsurancePolicyVehicle,
            TaxRecord,
            Note,
        ):
            await cleanup.execute(delete(model).where(model.vin == value))
        await cleanup.execute(delete(Vendor).where(Vendor.name.like(f"{value}-%")))
        await cleanup.execute(delete(Vehicle).where(Vehicle.vin == value))
        await cleanup.commit()


@asynccontextmanager
async def _own_request_session(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[AsyncClient, AsyncSession]]:
    """A client whose requests run on one session this test holds, as `get_db` would.

    The route's exception rolls the session back, exactly as production's
    `get_db` does, and comes back as the 500 a user would see rather than
    being raised into the test.
    """
    async with sessionmaker() as session:

        async def override_get_db():
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

        previous = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = override_get_db
        try:
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client, session
        finally:
            if previous is not None:
                app.dependency_overrides[get_db] = previous
            else:
                app.dependency_overrides.pop(get_db, None)


def _post_json(client: AsyncClient, headers: dict[str, str], vin: str, payload: Any):
    return client.post(
        f"/api/import/vehicles/{vin}/json",
        headers=headers,
        files={"file": ("vehicle.json", json.dumps(payload).encode(), "application/json")},
        data={"skip_duplicates": "true"},
    )


_TWO_SERVICE_RECORDS = [
    {"date": "2027-10-01", "odometer_km": 1000, "service_type": "Oil", "cost": 10},
    {"date": "2027-10-02", "odometer_km": 2000, "service_type": "Oil", "cost": 10},
]


class TestJsonSectionsAreCheckedBeforeAnyWrite:
    @pytest.mark.parametrize("bad", [5, "records", {"date": "2027-10-03"}])
    async def test_a_section_that_is_not_a_list_is_refused_whole(
        self, vin, auth_headers, test_sessionmaker, bad
    ):
        """It used to fail after the service records loop had committed its rows."""
        payload = {
            "export_version": "3",
            "units": "metric",
            "service_records": _TWO_SERVICE_RECORDS,
            "fuel_records": bad,
        }
        async with _own_request_session(test_sessionmaker) as (client, _session):
            response = await _post_json(client, auth_headers, vin, payload)
        committed = await _committed_rows(test_sessionmaker, vin)
        assert (response.status_code, committed) == (400, {}), response.text
        assert "fuel_records" in response.json()["detail"]

    async def test_a_null_section_is_an_empty_one(self, vin, auth_headers, test_sessionmaker):
        payload = {
            "export_version": "3",
            "units": "metric",
            "service_records": _TWO_SERVICE_RECORDS,
            "fuel_records": None,
        }
        async with _own_request_session(test_sessionmaker) as (client, _session):
            response = await _post_json(client, auth_headers, vin, payload)
        assert response.status_code == 200, response.text
        assert response.json()["service_records"]["success_count"] == 2
        assert response.json()["fuel_records"]["success_count"] == 0
        assert await _committed_rows(test_sessionmaker, vin) == {"service_visits": 2}

    async def test_a_file_that_is_not_an_object_is_refused(
        self, vin, auth_headers, test_sessionmaker
    ):
        async with _own_request_session(test_sessionmaker) as (client, _session):
            response = await _post_json(client, auth_headers, vin, [_TWO_SERVICE_RECORDS])
        assert response.status_code == 400, response.text
        assert await _committed_rows(test_sessionmaker, vin) == {}


class TestAFailureAfterRowsAreWrittenLeavesNothing:
    @pytest.mark.parametrize(
        "index", range(len(_every_import("X"))), ids=[c.route for c in _every_import("X")]
    )
    async def test_every_import_route(
        self, vin, auth_headers, test_sessionmaker, monkeypatch, index
    ):
        """The commit fails after every row's savepoint has been released.

        Before the commit gives way, the route's own session is asked what it
        wrote, so an empty result afterwards cannot come from an import that
        never wrote anything.
        """
        call = _every_import(vin)[index]
        written_before_commit: list[dict[str, int]] = []
        async with _own_request_session(test_sessionmaker) as (client, session):

            async def commit_that_fails() -> None:
                written_before_commit.append(await _rows_for(session, vin))
                raise RuntimeError("the disk filled up at commit")

            monkeypatch.setattr(session, "commit", commit_that_fails)
            response = await _post(client, auth_headers, vin, call)

        committed = await _committed_rows(test_sessionmaker, vin)
        assert response.status_code == 500, response.text
        assert len(written_before_commit) == 1
        assert written_before_commit[0], "the import wrote nothing before its commit"
        assert committed == {}, f"written {written_before_commit[0]}, committed {committed}"


@pytest.fixture
def lock_calls(monkeypatch) -> list[str]:
    """Record every VIN an import route takes the lock for, without changing what it does."""
    calls: list[str] = []
    real: Callable[[AsyncSession, str], Awaitable[None]] = lock_vehicle_for_write

    async def recording(db: AsyncSession, vin: str) -> None:
        calls.append(vin)
        await real(db, vin)

    monkeypatch.setattr(import_data_module, "lock_vehicle_for_write", recording)
    return calls


class TestEveryImportRouteTakesTheLock:
    async def test_the_walk_covers_every_import_route(self):
        """A new import route that this file does not call fails here first."""
        declared = {
            path
            for path, operations in app.openapi()["paths"].items()
            if path.startswith("/api/import/") and "post" in operations
        }
        assert declared == {call.route for call in _every_import("X")}

    async def test_each_import_locks_once_for_its_vehicle(
        self, client: AsyncClient, auth_headers, vin, lock_calls
    ):
        for call in _every_import(vin):
            response = await _post(client, auth_headers, vin, call)
            assert response.status_code == 200, (call.route, response.text)
            assert _imported_rows(response.json()) >= 1, (call.route, response.json())
        assert lock_calls == [vin] * len(_every_import(vin)), lock_calls
