"""Every MyGarage CSV reads the export's formula quote back off, once (P-2).

The export quotes text that starts like a formula, and since C-3 it quotes a
typed quote in front of one too. A pair that didn't unquote stored the quote,
so every round trip grew another one. Two cycles catch both that and a pair
that unquotes twice.
"""

from collections.abc import Callable
from io import BytesIO
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DEFRecord,
    FuelRecord,
    HoursRecord,
    InsurancePolicy,
    InsurancePolicyVehicle,
    Note,
    OdometerRecord,
    ServiceVisit,
    TaxRecord,
    Vehicle,
    WarrantyRecord,
)
from app.utils.csv_safe import sanitize_csv_cell

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: What a user typed: one starts like a formula, one has a quote in front of it.
_TYPED = ("'=example", "=example")

_INSURER = "B3 Quote Insure"


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    """The import and export limiters are per route; this module posts more than they allow."""
    from app.routes.export import limiter as export_limiter
    from app.routes.import_data import limiter as import_limiter

    export_limiter.reset()
    import_limiter.reset()


def _cell(text: str) -> str:
    """The text as the export writes it, CSV-quoted for the two commas-free cells here."""
    return str(sanitize_csv_cell(text))


#: pair -> (header, one row per typed text, where the text is stored)
_PAIRS: dict[str, tuple[str, Callable[[int, str], str], Any]] = {
    "service": (
        "units_version,unit_system,Visit,Date,Category,Description,Odometer (km),Cost,Visit Notes",
        lambda n, t: f"8,metric,{n},2026-03-0{n},Maintenance,Oil,{n}00.00,10.00,{_cell(t)}",
        ServiceVisit.notes,
    ),
    "fuel": (
        "Date,Odometer (km),Liters,Total Cost,Full Tank,Notes",
        lambda n, t: f"2026-03-0{n},{n}00.00,10.000,15.00,Yes,{_cell(t)}",
        FuelRecord.notes,
    ),
    # The station cell used to be unquoted on its own; once more would eat a typed quote.
    "fuel-station": (
        "Date,Odometer (km),Liters,Total Cost,Full Tank,Station",
        lambda n, t: f"2026-03-0{n},{n}00.00,10.000,15.00,Yes,{_cell(t)}",
        FuelRecord.station_name_freetext,
    ),
    "def": (
        "Date,Odometer (km),Liters,Total Cost,Notes",
        lambda n, t: f"2026-03-0{n},{n}00.00,5.000,9.00,{_cell(t)}",
        DEFRecord.notes,
    ),
    "odometer": (
        "Date,Reading (km),Notes",
        lambda n, t: f"2026-03-0{n},{n}00.00,{_cell(t)}",
        OdometerRecord.notes,
    ),
    "hours": (
        "Date,Engine Hours,Notes",
        lambda n, t: f"2026-03-0{n},{n}0.0,{_cell(t)}",
        HoursRecord.notes,
    ),
    "warranties": (
        "Provider,Type,Start Date,Notes",
        lambda n, t: f"B3 Quote Co {n},Extended,2026-03-0{n},{_cell(t)}",
        WarrantyRecord.notes,
    ),
    "insurance": (
        "Provider,Policy Number,Type,Start Date,End Date,Premium,Notes",
        lambda n, t: f"{_INSURER},B3-QUOTE-{n},Liability,2026-03-01,2026-09-01,100.00,{_cell(t)}",
        InsurancePolicyVehicle.notes,
    ),
    "tax": (
        "Date,Type,Amount,Notes",
        lambda n, t: f"2026-03-0{n},Registration,1{n}.00,{_cell(t)}",
        TaxRecord.notes,
    ),
    "notes": (
        "Date,Title,Content",
        lambda n, t: f"2026-03-0{n},{_cell(t)},{_cell(t)}",
        Note.content,
    ),
}


async def _vehicle(db_session: AsyncSession, owner_id: Any, vin: str) -> str:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname=vin,
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Quote",
            # Diesel, so the DEF importer's fuel-type gate accepts it.
            fuel_type="diesel",
        )
    )
    await db_session.commit()
    return vin


async def _import(client: AsyncClient, headers: dict, vin: str, pair: str, body: str) -> None:
    r = await client.post(
        f"/api/import/vehicles/{vin}/{pair}/csv",
        headers=headers,
        files={"file": (f"{pair}.csv", BytesIO(body.encode()), "text/csv")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["success_count"], r.json()["errors"]) == (2, []), r.json()


async def _export(client: AsyncClient, headers: dict, vin: str, pair: str) -> str:
    r = await client.get(f"/api/export/vehicles/{vin}/{pair}/csv?units=metric", headers=headers)
    assert r.status_code == 200, r.text
    return r.text


@pytest.mark.parametrize("case", list(_PAIRS))
async def test_a_quoted_cell_survives_two_round_trips(
    case: str,
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session: AsyncSession,
    test_sessionmaker,
):
    header, row, column = _PAIRS[case]
    pair = case.split("-")[0]
    tag = f"{case[:3].upper()}{case[-3:].upper()}"
    vins = [await _vehicle(db_session, test_user["id"], f"B3RTQUOTE{tag}{n}0") for n in "ABC"]
    body = "\n".join([header, *(row(n, t) for n, t in enumerate(_TYPED, start=1))]) + "\n"
    try:
        await _import(client, auth_headers, vins[0], pair, body)
        for source, target in zip(vins, vins[1:], strict=False):
            await _import(
                client,
                auth_headers,
                target,
                pair,
                await _export(client, auth_headers, source, pair),
            )

        model = column.class_
        async with test_sessionmaker() as fresh:
            for vin in vins:
                stored = (await fresh.execute(select(column).where(model.vin == vin))).scalars()
                # 4844e2f7: the pairs that didn't unquote kept a quote per cycle
                assert sorted(stored) == sorted(_TYPED), (pair, vin)
    finally:
        if pair == "insurance":
            # A policy is a household row, so it would outlive the vehicles.
            await db_session.execute(
                delete(InsurancePolicy).where(InsurancePolicy.provider == _INSURER)
            )
            await db_session.commit()
