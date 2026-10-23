"""Shared import plumbing (batch 3a task 1): dedup, sync, markers, cache, scale, warnings."""

import json
import re
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FuelRecord,
    HoursRecord,
    InsurancePolicy,
    Note,
    OdometerRecord,
    Reminder,
    TaxRecord,
    Vehicle,
    WarrantyRecord,
)
from app.utils.cache import cache

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    """The import and export limiters are per route; this module posts more than they allow."""
    from app.routes.export import limiter as export_limiter
    from app.routes.import_data import limiter as import_limiter

    export_limiter.reset()
    import_limiter.reset()


async def _vehicle(db_session: AsyncSession, owner_id: Any, vin: str) -> str:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname=vin,
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Plumbing",
            # Diesel, so the DEF CSV importer's fuel-type gate accepts it.
            fuel_type="diesel",
        )
    )
    await db_session.commit()
    return vin


async def _post_json(client: AsyncClient, headers: dict, vin: str, payload: dict) -> dict:
    r = await client.post(
        f"/api/import/vehicles/{vin}/json",
        headers=headers,
        files={"file": ("vehicle.json", json.dumps(payload).encode(), "application/json")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _post_csv(client: AsyncClient, headers: dict, vin: str, pair: str, body: str) -> dict:
    r = await client.post(
        f"/api/import/vehicles/{vin}/{pair}/csv",
        headers=headers,
        files={"file": (f"{pair}.csv", BytesIO(body.encode()), "text/csv")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    return r.json()


_MARKER = re.compile(r"^\[AUTO-SYNC from (\w+) #\d+\]$")


def _note(notes: str | None) -> str | None:
    """A sync marker as `<marker:source>`, since its id is the new row's; other notes as they are."""
    match = _MARKER.match(notes or "")
    return f"<marker:{match.group(1)}>" if match else notes


async def _odometer_rows(
    sessionmaker: Any, vin: str
) -> list[tuple[date, Decimal, str | None, str]]:
    async with sessionmaker() as fresh:
        rows = (
            await fresh.execute(
                select(OdometerRecord)
                .where(OdometerRecord.vin == vin)
                .order_by(OdometerRecord.date, OdometerRecord.id)
            )
        ).scalars()
        return [(r.date, r.odometer_km, _note(r.notes), r.source) for r in rows]


async def _hours_rows(sessionmaker: Any, vin: str) -> list[tuple[date, Decimal, str | None, str]]:
    async with sessionmaker() as fresh:
        rows = (
            await fresh.execute(
                select(HoursRecord)
                .where(HoursRecord.vin == vin)
                .order_by(HoursRecord.date, HoursRecord.id)
            )
        ).scalars()
        return [(r.date, r.engine_hours, _note(r.notes), r.source) for r in rows]


# -- G4-77: a duplicate pair already stored is a skip, not a row error ------------

_DUPLICATE_PAIRS = {
    "hours": (
        lambda vin: [
            HoursRecord(
                vin=vin, date=date(2026, 2, 1), engine_hours=Decimal("10.0"), source="manual"
            )
            for _ in range(2)
        ],
        "Date,Engine Hours,Notes\n2026-02-01,10.0,\n",
    ),
    "warranties": (
        lambda vin: [
            WarrantyRecord(
                vin=vin,
                warranty_type="Extended",
                provider="B3 Warranty Co",
                start_date=date(2026, 1, 1),
            )
            for _ in range(2)
        ],
        "Provider,Type,Policy Number,Coverage Details,Start Date,End Date,"
        "Mileage Limit (km),Notes\nB3 Warranty Co,Extended,,,2026-01-01,,,\n",
    ),
    "tax": (
        lambda vin: [
            TaxRecord(
                vin=vin, date=date(2026, 3, 1), tax_type="Registration", amount=Decimal("50.00")
            )
            for _ in range(2)
        ],
        "Date,Type,Amount,Renewal Date,Notes\n2026-03-01,Registration,50.00,,\n",
    ),
    "notes": (
        lambda vin: [
            Note(vin=vin, date=date(2026, 4, 1), title="B3 dup", content="x") for _ in range(2)
        ],
        "Date,Title,Content\n2026-04-01,B3 dup,x\n",
    ),
}


@pytest.mark.parametrize("pair", list(_DUPLICATE_PAIRS))
async def test_a_duplicate_pair_already_stored_is_skipped_not_an_error(
    pair: str, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    """Two identical rows on file made the duplicate check raise, so the row errored."""
    vin = await _vehicle(
        db_session, test_user["id"], f"B3RTDUPPAIR0000{list(_DUPLICATE_PAIRS).index(pair)}X"
    )
    seed, body = _DUPLICATE_PAIRS[pair]
    db_session.add_all(seed(vin))
    await db_session.commit()

    data = await _post_csv(client, auth_headers, vin, pair, body)

    # main: (0, 0, 1), "Row 2: Invalid record data" (MultipleResultsFound)
    assert (data["success_count"], data["skipped_count"], data["error_count"]) == (0, 1, 0), data


# -- S3-01 / R3: the end-of-import sync -----------------------------------------


async def test_a_legacy_fuel_only_backup_gives_a_mileage_reminder(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """The fill-up's odometer is synced before the reminders read the current reading.

    31,068.56 mi is 50,000.00 km; an interval of 621.37 mi is 999.998 km, due at 51,000.00.
    """
    vin = await _vehicle(db_session, test_user["id"], "B3RTLEGACYFUEL001")
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "fuel_records": [
                {"date": "2026-01-10", "mileage": 31068.56, "gallons": 10, "price_per_unit": 3}
            ],
            "reminders": [
                {"description": "Oil change", "is_recurring": True, "recurrence_miles": 621.37}
            ],
        },
    )
    # main: success_count 0, "Reminder 0: no odometer reading to count from"
    assert data["reminders"]["success_count"] == 1, data
    assert await _odometer_rows(test_sessionmaker, vin) == [
        (date(2026, 1, 10), Decimal("50000.00"), "<marker:fuel>", "fuel")
    ]
    async with test_sessionmaker() as fresh:
        (reminder,) = (await fresh.execute(select(Reminder).where(Reminder.vin == vin))).scalars()
    assert reminder.due_mileage_km == Decimal("51000.00")
    assert reminder.start_odometer_km == Decimal("50000.00")


async def test_a_fuel_csv_import_syncs_the_odometer_once_per_day(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Two fill-ups on one day leave that day's highest reading, owned by its fill-up."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTFUELCSVSYNC01")
    body = (
        "units_version,unit_system,Date,Odometer (km),Volume (L),Total Cost,Full Tank\n"
        "7,metric,2026-02-01,1000.00,40.000,60.00,Yes\n"
        "7,metric,2026-02-01,1010.00,5.000,8.00,Yes\n"
        "7,metric,2026-02-05,1400.00,40.000,60.00,Yes\n"
    )
    data = await _post_csv(client, auth_headers, vin, "fuel", body)
    assert data["success_count"] == 3, data
    # main: [] (the fuel CSV import never synced the odometer)
    assert await _odometer_rows(test_sessionmaker, vin) == [
        (date(2026, 2, 1), Decimal("1010.00"), "<marker:fuel>", "fuel"),
        (date(2026, 2, 5), Decimal("1400.00"), "<marker:fuel>", "fuel"),
    ]


async def test_a_service_csv_import_syncs_the_odometer_and_hours(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCCSVSYNC001")
    body = (
        "units_version,unit_system,Date,Category,Description,Odometer (km),"
        "Engine Hours,Cost,Vendor,Notes\n"
        "7,metric,2026-02-10,Maintenance,Oil,2000.00,40.5,50.00,,\n"
    )
    data = await _post_csv(client, auth_headers, vin, "service", body)
    assert data["success_count"] == 1, data
    # main: [] and [] (no sync on the service CSV import)
    assert await _odometer_rows(test_sessionmaker, vin) == [
        (date(2026, 2, 10), Decimal("2000.00"), "<marker:service_visit>", "service_visit")
    ]
    assert await _hours_rows(test_sessionmaker, vin) == [
        (date(2026, 2, 10), Decimal("40.5"), "<marker:service_visit>", "service_visit")
    ]


async def test_an_imported_visit_adds_no_hours_reading_to_a_day_that_reads_higher(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """The hours sync has no same-day rule of its own, so the import's skip is the only
    thing between a restored reading and a second row beside it (T-1)."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCHOURSKEEP1")
    db_session.add(
        HoursRecord(vin=vin, date=date(2026, 2, 11), engine_hours=Decimal("41.0"), source="manual")
    )
    await db_session.commit()
    body = (
        "units_version,unit_system,Date,Category,Description,Odometer (km),"
        "Engine Hours,Cost,Vendor,Notes\n"
        "7,metric,2026-02-11,Maintenance,Oil,2000.00,40.5,50.00,,\n"
    )
    data = await _post_csv(client, auth_headers, vin, "service", body)
    assert data["success_count"] == 1, data
    assert await _hours_rows(test_sessionmaker, vin) == [
        (date(2026, 2, 11), Decimal("41.0"), None, "manual")
    ]


async def test_a_def_json_import_syncs_the_odometer(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTDEFJSONSYNC01")
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "8",
            "units": "metric",
            "def_records": [{"date": "2026-02-12", "odometer_km": 2500.0, "liters": 9.5}],
        },
    )
    assert data["def_records"]["success_count"] == 1, data
    # main: []
    assert await _odometer_rows(test_sessionmaker, vin) == [
        (date(2026, 2, 12), Decimal("2500.00"), "<marker:def>", "def")
    ]


async def test_a_backup_round_trip_keeps_one_reading_per_day(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """A fill-up's synced readings travel twice, in the fuel row and in the reading
    sections; the target ends with one odometer and one hours row for the day."""
    source = await _vehicle(db_session, test_user["id"], "B3RTROUNDSRC00001")
    target = await _vehicle(db_session, test_user["id"], "B3RTROUNDDST00001")
    created = await client.post(
        f"/api/vehicles/{source}/fuel",
        headers=auth_headers,
        json={
            "vin": source,
            "date": "2026-03-03",
            "odometer_km": "3000.00",
            "engine_hours": "75.5",
            "liters": 40.0,
            "cost": 60.0,
            "is_full_tank": True,
        },
    )
    assert created.status_code == 201, created.text
    exported = await client.get(f"/api/export/vehicles/{source}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text

    data = await _post_json(client, auth_headers, target, exported.json())
    assert data["fuel_records"]["success_count"] == 1, data
    # The reading sections land as manual rows with no marker (R4); the fill-up's own
    # sync then finds the day already read and adds nothing (R3).
    # main: notes "[AUTO-SYNC from fuel #<source id>]" copied into the target
    assert await _odometer_rows(test_sessionmaker, target) == [
        (date(2026, 3, 3), Decimal("3000.00"), None, "manual")
    ]
    assert await _hours_rows(test_sessionmaker, target) == [
        (date(2026, 3, 3), Decimal("75.5"), None, "manual")
    ]


# -- N-2 / R4: imported readings lose sync markers and keep a portable source ----


async def test_an_imported_synced_odometer_row_is_never_taken_over(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """A copied marker made the row look auto-synced, so the next same-day fill-up
    took it over and a delete of that fill-up would cascade it away."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTMARKERODO0001")
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "8",
            "units": "metric",
            "odometer_records": [
                {"date": "2026-04-01", "reading": 42000.0, "notes": "[AUTO-SYNC from fuel #987654]"}
            ],
        },
    )
    assert data["odometer_records"]["success_count"] == 1, data
    created = await client.post(
        f"/api/vehicles/{vin}/fuel",
        headers=auth_headers,
        json={
            "vin": vin,
            "date": "2026-04-01",
            "odometer_km": "42050.00",
            "liters": 40.0,
            "cost": 60.0,
            "is_full_tank": True,
        },
    )
    assert created.status_code == 201, created.text
    # main: [(2026-04-01, 42050.00, "[AUTO-SYNC from fuel #<new id>]", "fuel")]
    assert await _odometer_rows(test_sessionmaker, vin) == [
        (date(2026, 4, 1), Decimal("42000.00"), None, "manual")
    ]


async def test_imported_odometer_sources_are_kept_or_made_manual(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTODOSOURCES001")
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "9",
            "units": "metric",
            "odometer_records": [
                {"date": "2026-05-01", "odometer_km": 1000.0, "source": "manual", "notes": None},
                {
                    "date": "2026-05-02",
                    "odometer_km": 1100.0,
                    "source": "livelink",
                    "notes": "Auto-recorded from LiveLink (ODO)",
                },
                {"date": "2026-05-03", "odometer_km": 1200.0, "source": "webhook", "notes": None},
                {
                    "date": "2026-05-04",
                    "odometer_km": 1300.0,
                    "source": "fuel",
                    "notes": "[AUTO-SYNC from fuel #5]",
                },
                {
                    "date": "2026-05-05",
                    "odometer_km": 1400.0,
                    "source": "tire_mount",
                    "notes": "Rotated [AUTO-SYNC from tire_mount #7]",
                },
            ],
        },
    )
    assert data["odometer_records"]["success_count"] == 5, data
    # main: every source 'manual', both markers copied
    assert await _odometer_rows(test_sessionmaker, vin) == [
        (date(2026, 5, 1), Decimal("1000.00"), None, "manual"),
        (date(2026, 5, 2), Decimal("1100.00"), "Auto-recorded from LiveLink (ODO)", "livelink"),
        (date(2026, 5, 3), Decimal("1200.00"), None, "webhook"),
        (date(2026, 5, 4), Decimal("1300.00"), None, "manual"),
        (date(2026, 5, 5), Decimal("1400.00"), "Rotated", "manual"),
    ]


async def test_an_imported_hours_row_loses_its_marker(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTMARKERHRS0001")
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "8",
            "units": "metric",
            "hours_records": [
                {
                    "date": "2026-05-06",
                    "engine_hours": 50.0,
                    "notes": "[AUTO-SYNC from tire_mount #7]",
                    "source": "tire_mount",
                },
                {
                    "date": "2026-05-07",
                    "engine_hours": 51.0,
                    "notes": "Checked [AUTO-SYNC from fuel #3]",
                    "source": "fuel",
                },
            ],
        },
    )
    assert data["hours_records"]["success_count"] == 2, data
    # main: both markers copied
    assert await _hours_rows(test_sessionmaker, vin) == [
        (date(2026, 5, 6), Decimal("50.0"), None, "manual"),
        (date(2026, 5, 7), Decimal("51.0"), "Checked", "manual"),
    ]


@pytest.mark.parametrize(
    ("pair", "body"),
    [
        (
            "odometer",
            "units_version,unit_system,Date,Reading (km),Notes\n"
            "7,metric,2026-05-08,1500.00,[AUTO-SYNC from fuel #12]\n",
        ),
        (
            "hours",
            "Date,Engine Hours,Notes,Source\n2026-05-08,52.0,[AUTO-SYNC from fuel #12],fuel\n",
        ),
    ],
)
async def test_a_reading_csv_row_loses_its_marker(
    pair: str,
    body: str,
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session: AsyncSession,
    test_sessionmaker,
):
    vin = await _vehicle(db_session, test_user["id"], f"B3RTMARKERCSV{pair[:4].upper()}")
    data = await _post_csv(client, auth_headers, vin, pair, body)
    assert data["success_count"] == 1, data
    rows = await (_odometer_rows if pair == "odometer" else _hours_rows)(test_sessionmaker, vin)
    # main: notes "[AUTO-SYNC from fuel #12]"
    assert [(notes, source) for _d, _v, notes, source in rows] == [(None, "manual")]


# -- N-6: every native import clears the analytics cache -----------------------

_ONE_ROW = {
    "service": "Date,Category,Description,Odometer (km),Cost,Vendor,Notes\n"
    "2026-06-01,Maintenance,Oil,100.00,10.00,,\n",
    "fuel": "Date,Odometer (km),Liters,Total Cost,Full Tank\n2026-06-01,100.00,10.000,15.00,Yes\n",
    "def": "Date,Odometer (km),Liters,Total Cost\n2026-06-01,100.00,5.000,9.00\n",
    "odometer": "Date,Reading (km),Notes\n2026-06-01,100.00,\n",
    "hours": "Date,Engine Hours,Notes\n2026-06-01,5.0,\n",
    "warranties": "Provider,Type,Start Date\nB3 Cache Co,Extended,2026-06-01\n",
    "insurance": "Provider,Policy Number,Type,Start Date,End Date,Premium,Premium Frequency,"
    "Deductible,Coverage Limits,Notes\n"
    "B3 Cache Insure,B3-CACHE-1,Liability,2026-06-01,2026-12-01,100.00,Semi-Annual,,,\n",
    "tax": "Date,Type,Amount\n2026-06-01,Registration,10.00\n",
    "notes": "Date,Title,Content\n2026-06-01,Cache,probe\n",
}


@pytest.mark.parametrize("pair", ["json", *_ONE_ROW])
async def test_an_import_clears_the_analytics_cache(
    pair: str, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    vin = await _vehicle(db_session, test_user["id"], f"B3RTCACHE{pair[:8].upper():0<8}")
    await cache.set("b3-cache-probe", "stale", 300)
    if pair == "json":
        await _post_json(
            client,
            auth_headers,
            vin,
            {
                "export_version": "8",
                "units": "metric",
                "notes": [{"date": "2026-06-01", "title": "Cache", "content": "probe"}],
            },
        )
    else:
        await _post_csv(client, auth_headers, vin, pair, _ONE_ROW[pair])
    # main: "stale" (no native import invalidated the cache)
    assert await cache.get("b3-cache-probe") is None
    if pair == "insurance":
        # A policy is a household row, so it would outlive the vehicle.
        await db_session.execute(
            delete(InsurancePolicy).where(InsurancePolicy.provider == "B3 Cache Insure")
        )
        await db_session.commit()


# -- R7: a converted figure is stored at the column's scale --------------------


async def test_a_converted_odometer_is_stored_at_the_column_scale(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """100 mi is 160.9344 km. SQLite kept all four places; PostgreSQL rounded to two."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSCALEODO00001")
    body = "units_version,unit_system,Date,Reading (mi),Notes\n7,imperial,2026-06-02,100,\n"
    data = await _post_csv(client, auth_headers, vin, "odometer", body)
    assert data["success_count"] == 1, data
    async with test_sessionmaker() as fresh:
        raw = (
            await fresh.execute(
                text("SELECT odometer_km FROM odometer_records WHERE vin = :vin"), {"vin": vin}
            )
        ).scalar_one()
    # main on SQLite: 160.9344
    assert Decimal(str(raw)) == Decimal("160.93")


# -- J2: every import response carries a warnings list -------------------------


async def test_every_import_response_carries_a_warnings_list(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTWARNINGSKEY01")
    csv_data = await _post_csv(client, auth_headers, vin, "notes", _ONE_ROW["notes"])
    json_data = await _post_json(
        client, auth_headers, vin, {"export_version": "8", "units": "metric"}
    )
    # main: KeyError, neither response has the key
    assert csv_data["warnings"] == []
    assert json_data["warnings"] == []


# -- R1-H2: an imported fill-up never takes over a restored reading -------------


async def test_a_restored_livelink_reading_survives_an_imported_fill_up(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """The sync doesn't claim on import: a same-day reading at or above the fill-up's stays
    as it was, and deleting the fill-up later can't take it along."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTLIVELINKKEEP1")
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "9",
            "units": "metric",
            "fuel_records": [{"date": "2026-04-10", "odometer_km": 1000.0, "liters": 40.0}],
            "odometer_records": [
                {
                    "date": "2026-04-10",
                    "odometer_km": 1200.0,
                    "source": "livelink",
                    "notes": "Auto-recorded from LiveLink (ODO)",
                }
            ],
        },
    )
    assert data["fuel_records"]["success_count"] == 1, data
    kept = [
        (date(2026, 4, 10), Decimal("1200.00"), "Auto-recorded from LiveLink (ODO)", "livelink")
    ]
    # main: source 'manual' (the import dropped the source; main never synced)
    assert await _odometer_rows(test_sessionmaker, vin) == kept

    async with test_sessionmaker() as fresh:
        fuel_id = (
            await fresh.execute(select(FuelRecord.id).where(FuelRecord.vin == vin))
        ).scalar_one()
    deleted = await client.delete(f"/api/vehicles/{vin}/fuel/{fuel_id}", headers=auth_headers)
    assert deleted.status_code in (200, 204), deleted.text
    assert await _odometer_rows(test_sessionmaker, vin) == kept


# -- R1-H1: duplicates match the stored rows one to one -------------------------


async def test_a_target_holding_one_of_two_identical_readings_ends_with_two(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """The stored reading is the duplicate of one file row, not of both."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTONETOONEODO01")
    db_session.add(OdometerRecord(vin=vin, date=date(2026, 4, 11), odometer_km=Decimal("1500")))
    await db_session.commit()
    payload = {
        "export_version": "9",
        "units": "metric",
        "odometer_records": [
            {"date": "2026-04-11", "odometer_km": 1500.0, "source": "manual", "notes": None},
            {"date": "2026-04-11", "odometer_km": 1500.0, "source": "manual", "notes": None},
        ],
    }
    first = await _post_json(client, auth_headers, vin, payload)
    # main: (0, 2), both file rows matched the one stored reading
    assert (
        first["odometer_records"]["success_count"],
        first["odometer_records"]["skipped_count"],
    ) == (1, 1), first
    again = await _post_json(client, auth_headers, vin, payload)
    assert (
        again["odometer_records"]["success_count"],
        again["odometer_records"]["skipped_count"],
    ) == (0, 2), again
    assert len(await _odometer_rows(test_sessionmaker, vin)) == 2


# -- Fable F-1, F-7: a number stored past its column's scale still matches ------


async def test_a_reimport_matches_readings_and_amounts_stored_past_their_scale(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    """SQLite keeps a REAL as given; the export writes it at the column's scale.

    120.55 hours in a NUMERIC(10,1) exports as 120.5, $45.678 in a NUMERIC(12,2)
    as 45.68. Re-importing the backup into the same vehicle must skip both (T-20).
    """
    vin = await _vehicle(db_session, test_user["id"], "B3RTSCALEREIMPRT1")
    db_session.add_all(
        [
            HoursRecord(
                vin=vin, date=date(2026, 2, 2), engine_hours=Decimal("120.55"), source="manual"
            ),
            FuelRecord(
                vin=vin,
                date=date(2026, 2, 1),
                odometer_km=Decimal("1000.00"),
                liters=Decimal("30.000"),
                cost=Decimal("45.678"),
            ),
        ]
    )
    await db_session.commit()
    exported = await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text

    data = await _post_json(client, auth_headers, vin, exported.json())
    # main: hours (1, 0), the exported 120.5 never equals the stored 120.55
    assert (data["hours_records"]["success_count"], data["hours_records"]["skipped_count"]) == (
        0,
        1,
    ), data
    # The cost is in the fuel key (Task 3), so this is its band's test too.
    assert (data["fuel_records"]["success_count"], data["fuel_records"]["skipped_count"]) == (
        0,
        1,
    ), data
