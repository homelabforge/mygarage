"""Fuel-economy pairing tests across a missed fill-up (audit finding F9).

A ``missed_fillup=True`` record means "the fill BEFORE this one was never
recorded" - the distance since the last recorded fill-up covers fuel that
was never measured. Correct handling:

- the missed record itself yields no economy figure, and
- it RE-ANCHORS the sequence: the next fill-up pairs against the missed
  record's odometer, never bridging across it.

The per-record list path re-anchors correctly. The vehicle-wide average
(``calculate_average_l_per_100km``) filters missed rows out of the
sequence entirely and bridges the gap, understating consumption; the
widget consumption helper computes a pair FOR a missed-flagged record
when it happens to carry liters. Both are pinned here.

Scenario used throughout (metric canonical):
    full 40 L @ 1000 km -> missed @ 1500 km -> full 45 L @ 2000 km
Correct average: 45 L / 500 km = 9.0 L/100km. Bridged (wrong): 4.5.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord
from app.models.vehicle import Vehicle
from app.services.fuel_service import (
    calculate_average_l_per_100km,
    calculate_l_per_100km,
)
from app.services.widget_aggregation import WidgetAggregationService


async def _seed(
    db_session: AsyncSession,
    user_id: int,
    vin: str,
    missed_liters: Decimal | None,
) -> None:
    """Seed the 3-record scenario; the middle record is the missed fill-up."""
    base = date.today() - timedelta(days=30)
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=user_id,
            nickname="Pairing Test",
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Pairing",
        )
    )
    await db_session.flush()
    db_session.add_all(
        [
            FuelRecord(
                vin=vin,
                date=base,
                odometer_km=Decimal("1000.00"),
                liters=Decimal("40.000"),
                is_full_tank=True,
                missed_fillup=False,
            ),
            FuelRecord(
                vin=vin,
                date=base + timedelta(days=15),
                odometer_km=Decimal("1500.00"),
                liters=missed_liters,
                is_full_tank=True,
                missed_fillup=True,
            ),
            FuelRecord(
                vin=vin,
                date=base + timedelta(days=30),
                odometer_km=Decimal("2000.00"),
                liters=Decimal("45.000"),
                is_full_tank=True,
                missed_fillup=False,
            ),
        ]
    )
    await db_session.commit()


@pytest.mark.unit
def test_missed_fillup_record_yields_no_economy() -> None:
    """A record flagged missed_fillup covers unmeasured fuel: no pair for it."""
    prev = FuelRecord(
        vin="PAIRING0000000000",
        date=date(2026, 1, 1),
        odometer_km=Decimal("1000.00"),
        liters=Decimal("40.000"),
        is_full_tank=True,
    )
    missed = FuelRecord(
        vin="PAIRING0000000000",
        date=date(2026, 1, 15),
        odometer_km=Decimal("1500.00"),
        liters=Decimal("20.000"),  # user knew the amount but missed the previous fill
        is_full_tank=True,
        missed_fillup=True,
    )
    assert calculate_l_per_100km(missed, prev) is None, (
        "missed_fillup record produced an economy figure - the distance since "
        "the previous record includes unrecorded fuel (audit finding F9)"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_average_does_not_bridge_missed_fillup(
    db_session: AsyncSession, test_user: dict[str, object]
) -> None:
    """F9 core: vehicle-wide average must re-anchor at the missed record."""
    vin = "PAIRAVG0000000001"
    await _seed(db_session, int(test_user["id"]), vin, missed_liters=None)  # type: ignore[arg-type]

    avg = await calculate_average_l_per_100km(db_session, vin)

    assert avg == Decimal("9.00"), (
        f"expected 9.00 L/100km (45 L over the 500 km since the missed "
        f"fill-up), got {avg} - the average bridged across the missed "
        "fill-up and understated consumption (audit finding F9)"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_widget_consumption_skips_missed_fillup_pair(
    db_session: AsyncSession, test_user: dict[str, object]
) -> None:
    """Widget parity: no pair may be computed FOR a missed-flagged record.

    The missed record carries absurd liters (999) so a wrongly-computed
    pair poisons the averages unmistakably.
    """
    vin = "PAIRWDG0000000001"
    await _seed(db_session, int(test_user["id"]), vin, missed_liters=Decimal("999.000"))  # type: ignore[arg-type]

    service = WidgetAggregationService(db_session)
    recent, average = await service._consumption_l100km(vin)

    assert recent is not None and average is not None
    assert recent == Decimal("9"), (
        f"widget recent consumption {recent} included the missed-fill-up pair "
        "(audit finding F9, widget path)"
    )
    assert average == Decimal("9"), (
        f"widget average consumption {average} included the missed-fill-up pair "
        "(audit finding F9, widget path)"
    )
