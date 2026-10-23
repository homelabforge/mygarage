"""Fuel and DEF fidelity: every exported column comes back (batch 3a task 3)."""

import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DEFRecord, FuelRecord, Vehicle
from app.models.address_book import AddressBookEntry
from app.models.user import User

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# The v7 fuel export's metric header, verbatim.
_FUEL_V7_HEADER = (
    "units_version,unit_system,Date,Filled At,Odometer (km),Engine Hours,Volume (L),"
    "Price Per Unit (L),Rebate,Total Cost,Full Tank,Missed Fill-up,Is Hauling,Fuel Type Used,"
    "Octane,Diesel Grade,Station ID,Station,Driver ID,Driver,Payment Method,Trip Type,"
    "Outside Temp (c),OBC Economy (l_100km),OBC Avg Speed (kmh),OBC Trip Duration (s),"
    "SOC Start (%),SOC End (%),Charge Level,Charge Location,Battery SOH (%),Notes"
)


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
            model="Fuel",
            fuel_type="diesel",
        )
    )
    await db_session.commit()
    return vin


async def _station(db_session: AsyncSession, name: str) -> int:
    found = (
        await db_session.execute(
            select(AddressBookEntry).where(AddressBookEntry.business_name == name)
        )
    ).scalar()
    if found is None:
        found = AddressBookEntry(business_name=name, category="Gas Station")
        db_session.add(found)
        await db_session.commit()
    return found.id


async def _driver(db_session: AsyncSession, username: str) -> int:
    found = (await db_session.execute(select(User).where(User.username == username))).scalar()
    if found is None:
        found = User(username=username, email=f"{username}@example.com", is_active=True)
        db_session.add(found)
        await db_session.commit()
    return found.id


async def _post_csv(client: AsyncClient, headers: dict, vin: str, pair: str, body: str) -> dict:
    r = await client.post(
        f"/api/import/vehicles/{vin}/{pair}/csv",
        headers=headers,
        files={"file": (f"{pair}.csv", BytesIO(body.encode()), "text/csv")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _post_json(client: AsyncClient, headers: dict, vin: str, payload: dict) -> dict:
    r = await client.post(
        f"/api/import/vehicles/{vin}/json",
        headers=headers,
        files={"file": ("vehicle.json", json.dumps(payload).encode(), "application/json")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _one(sessionmaker: Any, model: Any, vin: str) -> Any:
    async with sessionmaker() as fresh:
        return (await fresh.execute(select(model).where(model.vin == vin))).scalars().one()


def _fuel_csv_row(**cells: str) -> str:
    """One v7 fuel CSV data row, every cell blank unless given (by header name)."""
    header = _FUEL_V7_HEADER.split(",")
    values = {"units_version": "7", "unit_system": "metric", **cells}
    return ",".join(values.get(name, "") for name in header)


# -- CSV: the fourteen columns the importer dropped ----------------------------


async def test_the_fuel_csv_import_reads_every_exported_column(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTFUELCSVALL001")
    station_id = await _station(db_session, "B3 Fuel Stop")
    driver_id = await _driver(db_session, "b3driver")
    row = _fuel_csv_row(
        **{
            "Date": "2026-08-01",
            "Filled At": "2026-08-01T07:45:00",
            "Odometer (km)": "10000.00",
            "Volume (L)": "40.000",
            "Price Per Unit (L)": "1.500",
            "Total Cost": "60.00",
            "Full Tank": "Yes",
            "Missed Fill-up": "No",
            "Is Hauling": "Yes",
            "Fuel Type Used": "diesel",
            "Station ID": str(station_id),
            "Station": "B3 Fuel Stop",
            "Driver ID": str(driver_id),
            "Driver": "b3driver",
            "Payment Method": "fleet_card",
            "Trip Type": "business",
            "OBC Trip Duration (s)": "5400",
            "SOC Start (%)": "20.0",
            "SOC End (%)": "80.0",
            "Charge Level": "L2",
            "Charge Location": "home",
            "Battery SOH (%)": "97.5",
            "Notes": "full",
        }
    )
    data = await _post_csv(client, auth_headers, vin, "fuel", f"{_FUEL_V7_HEADER}\n{row}\n")
    assert data["success_count"] == 1, data
    r = await _one(test_sessionmaker, FuelRecord, vin)
    # main: every one of these is None or False
    assert (
        r.filled_at,
        r.is_hauling,
        r.station_address_book_id,
        r.station_name_freetext,
        r.driver_user_id,
        r.driver_name_freetext,
        r.payment_method,
        r.trip_type,
        r.obc_trip_duration_s,
        r.soc_start_pct,
        r.soc_end_pct,
        r.charge_level,
        r.charge_location,
        r.battery_soh_pct,
    ) == (
        datetime(2026, 8, 1, 7, 45),
        True,
        station_id,
        None,
        driver_id,
        None,
        "fleet_card",
        "business",
        5400,
        Decimal("20.00"),
        Decimal("80.00"),
        "L2",
        "home",
        Decimal("97.50"),
    )
    assert data["warnings"] == []


async def test_a_fuel_csv_link_this_instance_cannot_confirm_is_kept_as_text(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """The ids came from another instance: the names don't match, so they're text."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTFUELCSVLINK01")
    station_id = await _station(db_session, "B3 Real Stop")
    driver_id = await _driver(db_session, "b3realdriver")
    row = _fuel_csv_row(
        **{
            "Date": "2026-08-02",
            "Odometer (km)": "10100.00",
            "Volume (L)": "40.000",
            "Station ID": str(station_id),
            "Station": "Elsewhere Gas",
            "Driver ID": str(driver_id),
            "Driver": "someone",
        }
    )
    data = await _post_csv(client, auth_headers, vin, "fuel", f"{_FUEL_V7_HEADER}\n{row}\n")
    assert data["success_count"] == 1, data
    # main: KeyError, no warnings in the response
    assert data["warnings"] == [
        "Row 2: station not in this address book, kept as text",
        "Row 2: driver not on this instance, kept as text",
    ]
    r = await _one(test_sessionmaker, FuelRecord, vin)
    assert (r.station_address_book_id, r.station_name_freetext) == (None, "Elsewhere Gas")
    assert (r.driver_user_id, r.driver_name_freetext) == (None, "someone")


async def test_a_fuel_csv_word_the_api_refuses_is_a_row_error_that_names_the_field(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTFUELCSVVOCAB1")
    row = _fuel_csv_row(
        **{
            "Date": "2026-08-03",
            "Odometer (km)": "10200.00",
            "Volume (L)": "40.000",
            "Payment Method": "bitcoin",
        }
    )
    data = await _post_csv(client, auth_headers, vin, "fuel", f"{_FUEL_V7_HEADER}\n{row}\n")
    # main: success_count 1 (the column was never read)
    assert data["errors"] == [
        "Row 2: payment_method must be one of cash, credit, debit, fleet_card, app, other"
    ]


async def test_the_fuel_csv_export_names_a_linked_driver(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    """Station already carries the resolved name; Driver now does too, so a restore can check it."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTFUELCSVDRVR01")
    driver_id = await _driver(db_session, "b3exportdriver")
    db_session.add(
        FuelRecord(
            vin=vin,
            date=date(2026, 8, 4),
            odometer_km=Decimal("10300.00"),
            liters=Decimal("40.000"),
            driver_user_id=driver_id,
        )
    )
    await db_session.commit()
    r = await client.get(f"/api/export/vehicles/{vin}/fuel/csv?units=metric", headers=auth_headers)
    assert r.status_code == 200, r.text
    (row,) = list(csv.DictReader(io.StringIO(r.text)))
    # main: "" (the freetext column only)
    assert (row["Driver ID"], row["Driver"]) == (str(driver_id), "b3exportdriver")


# -- JSON v9: every fuel column, stations and drivers by id plus name ----------


async def test_a_json_backup_round_trip_keeps_every_fuel_column(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    source = await _vehicle(db_session, test_user["id"], "B3RTFUELJSONSRC01")
    target = await _vehicle(db_session, test_user["id"], "B3RTFUELJSONDST01")
    station_id = await _station(db_session, "B3 Json Stop")
    driver_id = await _driver(db_session, "b3jsondriver")
    db_session.add(
        FuelRecord(
            vin=source,
            date=date(2026, 8, 5),
            filled_at=datetime(2026, 8, 5, 18, 30),
            odometer_km=Decimal("11000.00"),
            engine_hours=Decimal("80.5"),
            liters=Decimal("12.345"),
            propane_liters=Decimal("20.100"),
            tank_size_kg=Decimal("9.00"),
            tank_quantity=2,
            kwh=Decimal("30.500"),
            soc_start_pct=Decimal("15.00"),
            soc_end_pct=Decimal("85.00"),
            charge_level="DCFC",
            charge_location="public",
            battery_soh_pct=Decimal("96.00"),
            cost=Decimal("44.00"),
            rebate=Decimal("1.00"),
            price_per_unit=Decimal("1.234"),
            price_basis="per_volume",
            fuel_type_used="diesel",
            diesel_grade="offroad",
            is_full_tank=False,
            missed_fillup=True,
            is_hauling=True,
            notes="all of it",
            station_address_book_id=station_id,
            driver_user_id=driver_id,
            payment_method="credit",
            trip_type="commute",
            outside_temp_c=Decimal("-3.5"),
            obc_l_per_100km=Decimal("11.20"),
            obc_avg_speed_kmh=Decimal("54.5"),
            obc_trip_duration_s=3600,
        )
    )
    await db_session.commit()
    exported = await client.get(f"/api/export/vehicles/{source}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    data = await _post_json(client, auth_headers, target, exported.json())
    assert data["fuel_records"]["success_count"] == 1, data

    r = await _one(test_sessionmaker, FuelRecord, target)
    # main: filled_at, engine_hours, propane, tank, kwh, EV, station, driver,
    # payment, trip, temperature and OBC all come back None
    assert (
        r.filled_at,
        r.engine_hours,
        r.liters,
        r.propane_liters,
        r.tank_size_kg,
        r.tank_quantity,
        r.kwh,
        r.soc_start_pct,
        r.soc_end_pct,
        r.charge_level,
        r.charge_location,
        r.battery_soh_pct,
        r.cost,
        r.rebate,
        r.price_per_unit,
        r.price_basis,
        r.fuel_type_used,
        r.diesel_grade,
        r.is_full_tank,
        r.missed_fillup,
        r.is_hauling,
        r.notes,
        r.station_address_book_id,
        r.station_name_freetext,
        r.driver_user_id,
        r.driver_name_freetext,
        r.payment_method,
        r.trip_type,
        r.outside_temp_c,
        r.obc_l_per_100km,
        r.obc_avg_speed_kmh,
        r.obc_trip_duration_s,
    ) == (
        datetime(2026, 8, 5, 18, 30),
        Decimal("80.5"),
        Decimal("12.345"),
        Decimal("20.100"),
        Decimal("9.00"),
        2,
        Decimal("30.500"),
        Decimal("15.00"),
        Decimal("85.00"),
        "DCFC",
        "public",
        Decimal("96.00"),
        Decimal("44.00"),
        Decimal("1.00"),
        Decimal("1.234"),
        "per_volume",
        "diesel",
        "offroad",
        False,
        True,
        True,
        "all of it",
        station_id,
        None,
        driver_id,
        None,
        "credit",
        "commute",
        Decimal("-3.5"),
        Decimal("11.20"),
        Decimal("54.5"),
        3600,
    )
    assert data["warnings"] == []


async def test_a_json_link_this_instance_cannot_confirm_is_kept_as_text(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTFUELJSONLINK1")
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "9",
            "units": "metric",
            "fuel_records": [
                {
                    "date": "2026-08-06",
                    "odometer_km": 11100.0,
                    "liters": 40.0,
                    "station_address_book_id": 99999999,
                    "station_name": "Ghost Fuel",
                    "station_name_freetext": None,
                    "driver_user_id": 99999999,
                    "driver_username": "ghost",
                    "driver_name_freetext": None,
                }
            ],
        },
    )
    assert data["fuel_records"]["success_count"] == 1, data
    # main: KeyError, no warnings in the response
    assert data["warnings"] == [
        "Fuel record 0: station not in this address book, kept as text",
        "Fuel record 0: driver not on this instance, kept as text",
    ]
    r = await _one(test_sessionmaker, FuelRecord, vin)
    assert (r.station_address_book_id, r.station_name_freetext) == (None, "Ghost Fuel")
    assert (r.driver_user_id, r.driver_name_freetext) == (None, "ghost")


async def test_a_json_backup_round_trip_keeps_the_def_entry_type(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    source = await _vehicle(db_session, test_user["id"], "B3RTDEFJSONSRC001")
    target = await _vehicle(db_session, test_user["id"], "B3RTDEFJSONDST001")
    db_session.add(
        DEFRecord(
            vin=source,
            date=date(2026, 8, 7),
            odometer_km=Decimal("11200.00"),
            fill_level=Decimal("0.75"),
            entry_type="auto_fuel_sync",
        )
    )
    await db_session.commit()
    exported = await client.get(f"/api/export/vehicles/{source}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    data = await _post_json(client, auth_headers, target, exported.json())
    assert data["def_records"]["success_count"] == 1, data
    r = await _one(test_sessionmaker, DEFRecord, target)
    # main: "purchase", the column default
    assert (r.entry_type, r.origin_fuel_record_id, r.fill_level) == (
        "auto_fuel_sync",
        None,
        Decimal("0.75"),
    )


# -- R1-H1: same-day fill-ups keep their multiplicity ---------------------------


async def test_same_day_fill_ups_sharing_an_odometer_all_restore_and_a_reimport_adds_none(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Two share an odometer; four have none (an hours-only pair, a propane pair)."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTFUELMULTIPLE1")
    payload = {
        "export_version": "9",
        "units": "metric",
        "fuel_records": [
            {"date": "2026-08-08", "odometer_km": 5000.0, "liters": 40.0, "cost": 60.0},
            {"date": "2026-08-08", "odometer_km": 5000.0, "liters": 5.0, "cost": 8.0},
            {"date": "2026-08-08", "engine_hours": 10.0, "liters": 20.0},
            {"date": "2026-08-08", "engine_hours": 12.0, "liters": 25.0},
            {"date": "2026-08-08", "propane_liters": 20.1, "tank_size_kg": 9.0, "tank_quantity": 2},
            {"date": "2026-08-08", "propane_liters": 18.0},
        ],
    }
    first = await _post_json(client, auth_headers, vin, payload)
    # main: 2 imported, 4 skipped (date and odometer, a NULL odometer matching NULL)
    assert first["fuel_records"]["success_count"] == 6, first
    again = await _post_json(client, auth_headers, vin, payload)
    assert again["fuel_records"]["skipped_count"] == 6, again
    async with test_sessionmaker() as fresh:
        rows = (
            await fresh.execute(
                select(
                    FuelRecord.odometer_km,
                    FuelRecord.engine_hours,
                    FuelRecord.liters,
                    FuelRecord.propane_liters,
                ).where(FuelRecord.vin == vin)
            )
        ).all()
    assert sorted((str(o), str(h), str(v), str(p)) for o, h, v, p in rows) == [
        ("5000.00", "None", "40.000", "None"),
        ("5000.00", "None", "5.000", "None"),
        ("None", "10.0", "20.000", "None"),
        ("None", "12.0", "25.000", "None"),
        ("None", "None", "None", "18.000"),
        ("None", "None", "None", "20.100"),
    ]


# A guard kept from the plan: green since Task 1's one-to-one matcher.
async def test_two_fuel_csv_fill_ups_sharing_an_odometer_both_import(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTFUELCSVTWIN01")
    body = (
        "units_version,unit_system,Date,Odometer (km),Volume (L),Total Cost,Full Tank\n"
        "7,metric,2026-08-09,5100.00,40.000,60.00,Yes\n"
        "7,metric,2026-08-09,5100.00,5.000,8.00,No\n"
    )
    first = await _post_csv(client, auth_headers, vin, "fuel", body)
    # main: (1, 1), the second fill-up skipped on the day and odometer
    assert (first["success_count"], first["skipped_count"]) == (2, 0), first
    again = await _post_csv(client, auth_headers, vin, "fuel", body)
    assert (again["success_count"], again["skipped_count"]) == (0, 2), again


# -- Beyond the brief: the key parts no test above can miss ---------------------


async def test_a_stored_hours_only_fill_up_does_not_swallow_a_different_one(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    """With no odometer on either, the litres tell two same-day fill-ups apart (R5)."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTFUELHOURSONLY")
    db_session.add(
        FuelRecord(
            vin=vin,
            date=date(2026, 8, 10),
            engine_hours=Decimal("10.0"),
            liters=Decimal("20.000"),
        )
    )
    await db_session.commit()
    payload = {
        "export_version": "9",
        "units": "metric",
        "fuel_records": [{"date": "2026-08-10", "engine_hours": 12.0, "liters": 25.0}],
    }
    first = await _post_json(client, auth_headers, vin, payload)
    # 2d5d25bd: (0, 1), the day and a NULL odometer matching the stored row
    assert (first["fuel_records"]["success_count"], first["fuel_records"]["skipped_count"]) == (
        1,
        0,
    ), first
    again = await _post_json(client, auth_headers, vin, payload)
    assert (again["fuel_records"]["success_count"], again["fuel_records"]["skipped_count"]) == (
        0,
        1,
    ), again


@pytest.mark.parametrize(
    ("surface", "vin", "differs"),
    [
        ("json", "B3RTDEFKEYFILLJ01", {"fill_level": 0.9}),
        ("json", "B3RTDEFKEYTYPEJ01", {"entry_type": "auto_fuel_sync"}),
        ("csv", "B3RTDEFKEYFILLC01", {"Fill Level": "0.90"}),
    ],
)
async def test_a_def_row_differing_from_a_stored_one_only_in_its_key_imports(
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session: AsyncSession,
    surface: str,
    vin: str,
    differs: dict[str, Any],
):
    """Same day, odometer and litres; another fill level or entry type is another row (R5)."""
    await _vehicle(db_session, test_user["id"], vin)
    db_session.add(
        DEFRecord(
            vin=vin,
            date=date(2026, 8, 11),
            odometer_km=Decimal("11300.00"),
            liters=Decimal("10.000"),
            fill_level=Decimal("0.50"),
        )
    )
    await db_session.commit()

    async def post() -> tuple[int, int]:
        if surface == "csv":
            cells = {"Fill Level": "0.50", **differs}
            body = (
                "units_version,unit_system,Date,Odometer (km),Liters,Fill Level\n"
                f"7,metric,2026-08-11,11300.00,10.000,{cells['Fill Level']}\n"
            )
            data = await _post_csv(client, auth_headers, vin, "def", body)
            return data["success_count"], data["skipped_count"]
        row = {
            "date": "2026-08-11",
            "odometer_km": 11300.0,
            "liters": 10.0,
            "fill_level": 0.5,
            "entry_type": "purchase",
            **differs,
        }
        payload = {"export_version": "9", "units": "metric", "def_records": [row]}
        data = await _post_json(client, auth_headers, vin, payload)
        return data["def_records"]["success_count"], data["def_records"]["skipped_count"]

    # 2d5d25bd: (0, 1), the day and odometer alone matching the stored row
    assert await post() == (1, 0)
    assert await post() == (0, 1)


# -- Fix round 1: an older export's blank zero, text columns ----------------------


async def _store_zero_rows(db_session: AsyncSession, vin: str) -> None:
    """A 0 L fill-up and a DEF row read at an empty tank, as the API stores them."""
    db_session.add_all(
        [
            FuelRecord(
                vin=vin,
                date=date(2026, 8, 12),
                odometer_km=Decimal("11400.00"),
                liters=Decimal("0.000"),
                kwh=Decimal("20.000"),
            ),
            DEFRecord(
                vin=vin,
                date=date(2026, 8, 12),
                odometer_km=Decimal("11400.00"),
                liters=Decimal("0.000"),
                fill_level=Decimal("0.00"),
            ),
        ]
    )
    await db_session.commit()


async def test_a_v8_backup_s_null_zero_matches_the_stored_zero(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    """v8 wrote a 0 L fill-up and a 0.00 fill level as null; its re-import adds nothing (R5)."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTZEROV8JSON001")
    await _store_zero_rows(db_session, vin)
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "8",
            "units": "metric",
            # The v8 rows, as cb7c994e's export wrote them for those records.
            "fuel_records": [
                {"date": "2026-08-12", "odometer_km": 11400.0, "liters": None, "cost": None}
            ],
            "def_records": [
                {
                    "date": "2026-08-12",
                    "odometer_km": 11400.0,
                    "liters": None,
                    "cost": None,
                    "fill_level": None,
                }
            ],
        },
    )
    # 3c5eb849: both imported again, a null matching only NULL
    assert (data["fuel_records"]["skipped_count"], data["def_records"]["skipped_count"]) == (
        1,
        1,
    ), data


async def test_a_v9_backup_s_null_is_not_a_stored_zero(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    """v9 writes a 0 as 0, so its null is a missing figure, another row than the 0."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTZEROV9JSON001")
    await _store_zero_rows(db_session, vin)
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "9",
            "units": "metric",
            "fuel_records": [
                {"date": "2026-08-12", "odometer_km": 11400.0, "liters": None, "kwh": 20.0}
            ],
            "def_records": [
                {
                    "date": "2026-08-12",
                    "odometer_km": 11400.0,
                    "liters": 0.0,
                    "fill_level": None,
                }
            ],
        },
    )
    # A guard: green on 3c5eb849 too, it keeps the v8 rule to v8 files.
    assert (data["fuel_records"]["success_count"], data["def_records"]["success_count"]) == (
        1,
        1,
    ), data


@pytest.mark.parametrize(
    ("version", "skipped"),
    [
        # 3c5eb849: 0, the blank matching only NULL
        ("7", 1),
        # A guard: a v8 CSV writes a 0 as 0, so its blank is a missing figure.
        ("8", 0),
    ],
)
async def test_an_older_csv_s_blank_zero_matches_the_stored_zero(
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session: AsyncSession,
    version: str,
    skipped: int,
):
    """A v<=7 fuel and DEF CSV wrote a 0 L and a 0.00 fill level as a blank cell."""
    vin = await _vehicle(db_session, test_user["id"], f"B3RTZEROCSVV{version}001")
    await _store_zero_rows(db_session, vin)
    fuel = await _post_csv(
        client,
        auth_headers,
        vin,
        "fuel",
        f"units_version,unit_system,Date,Odometer (km),Liters\n{version},metric,2026-08-12,11400.00,\n",
    )
    def_ = await _post_csv(
        client,
        auth_headers,
        vin,
        "def",
        "units_version,unit_system,Date,Odometer (km),Liters,Fill Level\n"
        f"{version},metric,2026-08-12,11400.00,0.000,\n",
    )
    assert (fuel["skipped_count"], def_["skipped_count"]) == (skipped, skipped), (fuel, def_)


async def test_a_long_fuel_csv_driver_with_no_id_is_cut_to_the_column(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """driver_name_freetext is String(100); PostgreSQL refuses a longer one."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTFUELCSVLONGDR")
    row = _fuel_csv_row(**{"Date": "2026-08-13", "Odometer (km)": "11500.00", "Driver": "d" * 120})
    data = await _post_csv(client, auth_headers, vin, "fuel", f"{_FUEL_V7_HEADER}\n{row}\n")
    assert data["success_count"] == 1, data
    r = await _one(test_sessionmaker, FuelRecord, vin)
    # 3c5eb849: all 120, which SQLite keeps
    assert r.driver_name_freetext == "d" * 100


async def test_a_json_def_text_column_holding_a_number_is_a_row_error(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    """SQLite would store the number where PostgreSQL refuses it; both refuse the row now."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTDEFJSONTEXT01")
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "9",
            "units": "metric",
            "def_records": [{"date": "2026-08-14", "odometer_km": 11600.0, "brand": 5}],
        },
    )
    # 3c5eb849: success 1, the 5 stored as text on SQLite
    assert data["errors"] == ["DEF record 0: brand must be text"], data
