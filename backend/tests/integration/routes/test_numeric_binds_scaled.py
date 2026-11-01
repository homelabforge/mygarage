"""SQLite stores the number PostgreSQL stores, so SQL agrees on both.

PG rounds a number to its column's scale on the way in, and casts a comparison's
bound side to the column type too. SQLite kept the raw number: the browser posts
an imperial odometer as km to 12 significant digits, so a stored 19867.35168
compared against the 19867.35 the ORM reads back and the two never matched. The
fuel economy window took the previous full tank's own litres, the widget dropped
its anchor tank, and an import's duplicate check missed. `ScaledNumeric` rounds
every bind the way PG does, so each of those reads the same on both dialects.

Raw values are read with `text()`, which has no column type, so they're what the
database holds: a float on SQLite, a Decimal on PG.
"""

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.vehicle import Vehicle
from app.services.widget_aggregation import WidgetAggregationService
from app.utils.error_handlers import is_numeric_overflow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: The international mile, what the frontend converts with.
MILE_KM = Decimal("1.609344")
DAY = date(2026, 9, 1)


def _km(miles: int) -> Decimal:
    """What the browser posts for an imperial odometer: unrounded km."""
    return Decimal(miles) * MILE_KM


def _exact(raw: Any) -> Any:
    """A raw driver value as a Decimal, so both dialects compare alike."""
    return Decimal(repr(raw)) if isinstance(raw, float) else raw


async def _raw(db: AsyncSession, column: str, record_id: int) -> Any:
    result = await db.execute(
        text(f"SELECT {column} FROM fuel_records WHERE id = :id"), {"id": record_id}
    )
    return _exact(result.scalar_one())


# --- What gets stored ---------------------------------------------------------


async def test_an_orm_write_stores_the_column_scale(db_session, own_vehicle):
    record = FuelRecord(
        vin=own_vehicle.vin,
        date=DAY,
        odometer_km=_km(12345),  # 19867.35168
        liters=Decimal("40.0004"),
    )
    db_session.add(record)
    await db_session.commit()

    assert await _raw(db_session, "odometer_km", record.id) == Decimal("19867.35")
    assert await _raw(db_session, "liters", record.id) == Decimal("40.000")


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        pytest.param(Decimal("1.005"), Decimal("1.01"), id="decimal"),
        # The double nearest 1.005 sits below it; it still stores what was typed.
        pytest.param(1.005, Decimal("1.01"), id="float"),
        pytest.param(Decimal("-1.005"), Decimal("-1.01"), id="negative"),
    ],
)
async def test_a_tie_rounds_away_from_zero_on_both_dialects(
    db_session, own_vehicle, value: Any, stored: Decimal
):
    record = FuelRecord(vin=own_vehicle.vin, date=DAY, odometer_km=value)
    db_session.add(record)
    await db_session.commit()

    assert await _raw(db_session, "odometer_km", record.id) == stored
    await db_session.refresh(record)
    assert record.odometer_km == stored


@pytest.mark.parametrize("path", ["insert-values", "bulk-insert", "update-values"])
async def test_core_statements_round_too(db_session, own_vehicle, path: str):
    """Not only the ORM flush: Core insert/update and an executemany bulk insert
    all go through the column type."""
    vin = own_vehicle.vin
    raw_km = _km(12345)
    if path == "insert-values":
        await db_session.execute(insert(FuelRecord).values(vin=vin, date=DAY, odometer_km=raw_km))
    elif path == "bulk-insert":
        await db_session.execute(
            insert(FuelRecord),
            [
                {"vin": vin, "date": DAY, "odometer_km": raw_km},
                {"vin": vin, "date": DAY, "odometer_km": raw_km},
            ],
        )
    else:
        db_session.add(FuelRecord(vin=vin, date=DAY, odometer_km=Decimal(1)))
        await db_session.flush()
        await db_session.execute(
            update(FuelRecord).where(FuelRecord.vin == vin).values(odometer_km=raw_km)
        )
    await db_session.commit()

    ids = (
        (await db_session.execute(select(FuelRecord.id).where(FuelRecord.vin == vin)))
        .scalars()
        .all()
    )
    assert ids
    for record_id in ids:
        assert await _raw(db_session, "odometer_km", record_id) == Decimal("19867.35")


# --- What SQL computes from it ------------------------------------------------


async def test_the_economy_window_leaves_the_previous_full_tank_out(
    client: AsyncClient, auth_headers, own_vehicle
):
    """`window_sim.py`'s imperial fill-ups: full 40 L, partial 10 L, full 30 L.

    The window is (previous full, current], so 10 + 30 = 40 L over the 356 mi
    between the full tanks. With raw SQLite odometers the previous full tank's
    stored 19867.35168 sat above the 19867.35 it was compared with, and its
    40 L joined the window: 80 L, 13.96 L/100km.
    """
    base = f"/api/vehicles/{own_vehicle.vin}/fuel"
    ids = []
    for day, miles, litres, full in [
        (DAY, 12345, 40, True),
        (DAY + timedelta(days=7), 12500, 10, False),
        (DAY + timedelta(days=14), 12701, 30, True),
    ]:
        response = await client.post(
            base,
            json={
                "vin": own_vehicle.vin,
                "date": day.isoformat(),
                # A JSON number with every digit, as the form sends it.
                "odometer_km": float(_km(miles)),
                "liters": litres,
                "is_full_tank": full,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])

    response = await client.get(f"{base}/{ids[-1]}", headers=auth_headers)
    assert response.status_code == 200, response.text

    # 40 L over 20440.28 - 19867.35 = 572.93 km.
    expected = (Decimal(40) / (Decimal("20440.28") - Decimal("19867.35")) * 100).quantize(
        Decimal("0.0001")
    )
    assert expected == Decimal("6.9817")
    assert Decimal(str(response.json()["l_per_100km"])) == expected


async def test_the_widget_keeps_its_anchor_tank(db_session: AsyncSession, own_vehicle):
    """`widget_sim.py`: five full tanks about 300 mi apart, written raw.

    The span starts at the lowest of the newest full-tank odometers. Raw, the
    anchor's stored 17936.13888 sat below the 17936.14 the ORM read back, so
    `>= min(span_ends)` dropped it: 8.28 recent and average, not 9.6658 and 9.3206.
    """
    vin = own_vehicle.vin
    miles = [11145, 11445, 11745, 12045, 12345]
    for index, mi in enumerate(miles):
        db_session.add(
            FuelRecord(
                vin=vin,
                date=DAY + timedelta(days=7 * index),
                odometer_km=_km(mi),
                liters=Decimal("60.000") if index == len(miles) - 1 else Decimal("40.000"),
                is_full_tank=True,
            )
        )
    await db_session.commit()
    # A request's session starts empty, so the service reads what's stored.
    db_session.expunge_all()

    recent, average = await WidgetAggregationService(db_session)._consumption_l100km(vin)

    assert (recent, average) == (Decimal("9.6658"), Decimal("9.3206"))


async def test_an_import_skips_an_unrounded_duplicate(
    client: AsyncClient, auth_headers, db_session: AsyncSession, own_vehicle
):
    """The CSV's 1234.56 h is the stored 1234.6 h at the column's one place."""
    vin = own_vehicle.vin
    db_session.add(HoursRecord(vin=vin, date=DAY, engine_hours=Decimal("1234.6"), source="manual"))
    await db_session.commit()

    csv_content = f"Date,Engine Hours,Notes\n{DAY.isoformat()},1234.56,Again\n"
    response = await client.post(
        f"/api/import/vehicles/{vin}/hours/csv",
        headers=auth_headers,
        files={"file": ("hours.csv", BytesIO(csv_content.encode()), "text/csv")},
        data={"skip_duplicates": "true"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["skipped_count"], body["success_count"]) == (1, 0), body
    count = await db_session.scalar(
        select(func.count()).select_from(HoursRecord).where(HoursRecord.vin == vin)
    )
    assert count == 1


# --- Guards: inputs ScaledNumeric hands on untouched --------------------------


async def test_none_stores_null(db_session, own_vehicle):
    # Guard: passes before ScaledNumeric. Kills dropping its `is None` return.
    record = FuelRecord(vin=own_vehicle.vin, date=DAY, odometer_km=None, liters=None)
    db_session.add(record)
    await db_session.commit()

    assert await _raw(db_session, "odometer_km", record.id) is None


async def test_nan_stores_what_it_stored_before(db_session, own_vehicle):
    # Guard: passes before ScaledNumeric. SQLite has no NaN and stores NULL;
    # PG's NUMERIC keeps it. Kills turning a non-finite value into anything else.
    record = FuelRecord(vin=own_vehicle.vin, date=DAY, kwh=float("nan"))
    db_session.add(record)
    await db_session.commit()

    raw = await _raw(db_session, "kwh", record.id)
    if db_session.get_bind().dialect.name == "sqlite":
        assert raw is None
    else:
        assert raw.is_nan()


async def test_a_number_too_big_to_round_reaches_the_database(db_session, own_vehicle):
    """Guard (Fable F-8): passes before ScaledNumeric. Past 28 digits quantize
    raises; the value has to reach the database, so PG answers with its own
    overflow (a 422 from the handler) and SQLite stores it as it did. Kills
    letting `InvalidOperation` out, a StatementError and a 500 on both."""
    statement = (
        update(Vehicle).where(Vehicle.vin == own_vehicle.vin).values(msrp_total=Decimal("1e30"))
    )
    if db_session.get_bind().dialect.name == "sqlite":
        await db_session.execute(statement)
        await db_session.rollback()
        return
    with pytest.raises(DBAPIError) as caught:
        await db_session.execute(statement)
    await db_session.rollback()
    assert is_numeric_overflow(caught.value)
