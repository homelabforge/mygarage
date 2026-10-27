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
    average_l_per_100km,
    calculate_average_l_per_100km,
    calculate_l_per_100km,
    compute_full_tank_economy,
    economy_periods,
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


# --- Issue #113: partial fill-ups must count toward the next full tank -------


def _fr(odo: str, liters: str | None, *, full: bool) -> FuelRecord:
    """Terse FuelRecord factory for the window/interval unit tests."""
    return FuelRecord(
        vin="PARTIAL0000000000",
        date=date(2026, 1, 1),
        odometer_km=Decimal(odo),
        liters=Decimal(liters) if liters is not None else None,
        is_full_tank=full,
    )


@pytest.mark.unit
def test_compute_full_tank_economy_folds_partials() -> None:
    """A partial fill-up between two full tanks folds into the next full tank's
    figure and yields no figure of its own (reporter's Example 2)."""
    prev = _fr("139530", "23.520", full=True)
    partial = _fr("140105", "24.790", full=False)
    cur = _fr("140354", "52.950", full=True)

    results = compute_full_tank_economy([prev, partial, cur])

    # Only the second full tank gets a figure; the first has no predecessor and
    # the partial is not an endpoint. (24.79 + 52.95) / 824 * 100 = 9.4345.
    assert [(r.odometer_km, v) for r, v in results] == [(Decimal("140354"), Decimal("9.4345"))]


@pytest.mark.unit
def test_excluding_towing_drops_the_towing_tank_rather_than_merging_it() -> None:
    """Issue #181 follow-up: a towing tank stays an endpoint and its figure is
    left out. It used to stop being an endpoint, so its fuel and distance merged
    into the NEXT tank's figure and the "excluding towing" average still
    carried the towing fuel."""
    a = _fr("1000", "40.000", full=True)
    towing = _fr("1500", "30.000", full=True)
    towing.is_hauling = True
    b = _fr("2000", "45.000", full=True)

    # a -> towing is 30 L / 500 km = 6.0 (towing); towing -> b is 45 / 500 = 9.0.
    excluded = compute_full_tank_economy([a, towing, b], exclude_hauling=True)
    assert [(r.odometer_km, v) for r, v in excluded] == [(Decimal("2000"), Decimal("9.00"))]

    included = compute_full_tank_economy([a, towing, b], exclude_hauling=False)
    assert [v for _, v in included] == [Decimal("6.00"), Decimal("9.00")]


@pytest.mark.unit
def test_a_towing_partial_fill_up_makes_its_tank_a_towing_tank() -> None:
    """Fuel bought mid-tank while towing was burned towing, so the tank it
    belongs to is a towing tank even when the closing fill-up is not marked."""
    a = _fr("10000", "40.000", full=True)
    partial = _fr("10200", "20.000", full=False)
    partial.is_hauling = True
    b = _fr("10500", "30.000", full=True)  # (20 + 30) / 500 km = 10.0, towing
    c = _fr("11000", "40.000", full=True)  # 40 / 500 km = 8.0

    periods = economy_periods([a, partial, b, c])
    assert [(p.l_per_100km, p.towing) for p in periods] == [
        (Decimal("10.00"), True),
        (Decimal("8.00"), False),
    ]
    excluded = compute_full_tank_economy([a, partial, b, c], exclude_hauling=True)
    assert [v for _, v in excluded] == [Decimal("8.00")]


@pytest.mark.unit
def test_the_average_is_total_fuel_over_total_distance() -> None:
    """A 100 km tank at 10 L/100km and a 400 km tank at 5 L/100km burned 30 L
    over 500 km: 6.0, not the 7.5 a mean of the two figures gives."""
    periods = economy_periods(
        [
            _fr("10000", "40.000", full=True),
            _fr("10100", "10.000", full=True),
            _fr("10500", "20.000", full=True),
        ]
    )
    assert [p.l_per_100km for p in periods] == [Decimal("10.00"), Decimal("5.00")]
    assert average_l_per_100km(periods) == Decimal("6.00")
    assert average_l_per_100km([]) is None


@pytest.mark.unit
def test_an_odometer_of_zero_is_treated_as_missing() -> None:
    """A 0 reading is far more often a placeholder than a brand-new vehicle.
    Anchoring on it would make the next real tank an 85,000 km period, which
    swamps a distance-weighted average."""
    results = compute_full_tank_economy(
        [
            _fr("0", "40.000", full=True),
            _fr("85000", "40.000", full=True),
            _fr("85500", "40.000", full=True),
        ]
    )
    assert [v for _, v in results] == [Decimal("8.00")]


@pytest.mark.unit
def test_an_impossible_tank_stays_out_of_the_average() -> None:
    """Weighting by distance lets one mistyped odometer swamp the average: a
    fill-up keyed as 900,000 instead of 90,000 is 40 L over 810,000 km. Tanks
    outside the realistic band are left out of it (they still get their own
    figure, so the fuel list shows the slip)."""
    records = [_fr(str(85000 + 500 * i), "40.000", full=True) for i in range(11)]
    records.append(_fr("900000", "40.000", full=True))
    periods = economy_periods(records)
    assert periods[-1].l_per_100km == Decimal("0.0049")
    assert not periods[-1].plausible
    assert average_l_per_100km(periods) == Decimal("8.00")
    assert average_l_per_100km(periods[-1:]) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vehicle_average_weights_by_distance_and_drops_towing(
    db_session: AsyncSession, test_user: dict[str, object]
) -> None:
    """The Fuel tab's average: towing tanks out, then total fuel over total
    distance. 10 L over 100 km and 20 L over 400 km -> 6.00; the towing tank
    between them (48 L over 300 km) must not leak in."""
    vin = "WEIGHTAVG00000001"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=int(test_user["id"]),  # type: ignore[arg-type]
            nickname="Weighted",
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Weighted",
        )
    )
    await db_session.flush()
    base = date.today() - timedelta(days=30)
    for days, odo, litres, towing in [
        (0, "10000", "40", False),
        (5, "10100", "10", False),
        (10, "10400", "48", True),
        (15, "10800", "20", False),
    ]:
        db_session.add(
            FuelRecord(
                vin=vin,
                date=base + timedelta(days=days),
                odometer_km=Decimal(odo),
                liters=Decimal(litres),
                is_full_tank=True,
                is_hauling=towing,
            )
        )
    await db_session.commit()

    assert await calculate_average_l_per_100km(db_session, vin) == Decimal("6.00")
    # With towing: 78 L over 800 km.
    assert await calculate_average_l_per_100km(db_session, vin, exclude_hauling=False) == Decimal(
        "9.75"
    )

    service = WidgetAggregationService(db_session)
    recent, average = await service._consumption_l100km(vin)
    assert recent is not None and average is not None
    assert abs(average - Decimal("6.00")) < Decimal("0.01"), average
    assert abs(recent - Decimal("6.00")) < Decimal("0.01"), recent


@pytest.mark.unit
def test_calculate_l_per_100km_uses_interval_liters() -> None:
    """#113 regression: the fallback numerator uses only the final full fill-up
    (valid only when no partials exist); the interval sum counts all fuel."""
    prev = _fr("139530", "23.520", full=True)
    cur = _fr("140354", "52.950", full=True)

    # No-partial base case — the fallback equals the correct answer: 52.95 / 824.
    assert calculate_l_per_100km(cur, prev) == Decimal("6.4260")
    # With a partial in between, the interval sum is the correct numerator.
    assert calculate_l_per_100km(cur, prev, Decimal("77.740")) == Decimal("9.4345")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_average_includes_partial_fillups(
    db_session: AsyncSession, test_user: dict[str, object]
) -> None:
    """#113 end-to-end (reporter's Example 2): full -> partial -> full."""
    vin = "PARTIALAVG0000001"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=int(test_user["id"]),  # type: ignore[arg-type]
            nickname="Partial Avg",
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Partial",
        )
    )
    await db_session.flush()
    base = date.today() - timedelta(days=30)
    db_session.add_all(
        [
            FuelRecord(
                vin=vin,
                date=base,
                odometer_km=Decimal("139530.00"),
                liters=Decimal("23.520"),
                is_full_tank=True,
            ),
            FuelRecord(
                vin=vin,
                date=base + timedelta(days=7),
                odometer_km=Decimal("140105.00"),
                liters=Decimal("24.790"),
                is_full_tank=False,
            ),
            FuelRecord(
                vin=vin,
                date=base + timedelta(days=14),
                odometer_km=Decimal("140354.00"),
                liters=Decimal("52.950"),
                is_full_tank=True,
            ),
        ]
    )
    await db_session.commit()

    avg = await calculate_average_l_per_100km(db_session, vin)

    # (24.79 + 52.95) / (140354 - 139530) * 100 = 77.74 / 824 * 100 = 9.4345
    assert avg == Decimal("9.4345"), (
        f"expected 9.4345 L/100km including the partial fill-up, got {avg} "
        "(issue #113: partial fill-up volume was ignored, using only the "
        "final full fill-up)"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_widget_consumption_includes_partial_fillups(
    db_session: AsyncSession, test_user: dict[str, object]
) -> None:
    """#113 parity: the homepage widget consumption must also count partials."""
    vin = "PARTIALWDG0000001"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=int(test_user["id"]),  # type: ignore[arg-type]
            nickname="Partial Widget",
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Partial",
        )
    )
    await db_session.flush()
    base = date.today() - timedelta(days=30)
    db_session.add_all(
        [
            FuelRecord(
                vin=vin,
                date=base,
                odometer_km=Decimal("139530.00"),
                liters=Decimal("23.520"),
                is_full_tank=True,
            ),
            FuelRecord(
                vin=vin,
                date=base + timedelta(days=7),
                odometer_km=Decimal("140105.00"),
                liters=Decimal("24.790"),
                is_full_tank=False,
            ),
            FuelRecord(
                vin=vin,
                date=base + timedelta(days=14),
                odometer_km=Decimal("140354.00"),
                liters=Decimal("52.950"),
                is_full_tank=True,
            ),
        ]
    )
    await db_session.commit()

    service = WidgetAggregationService(db_session)
    recent, average = await service._consumption_l100km(vin)

    assert recent is not None and average is not None
    # 77.74 L / 824 km * 100 = 9.43 (rounding differs from the Decimal path;
    # assert the float-ish Decimal is within a cent of the expected figure).
    assert abs(recent - Decimal("9.43")) < Decimal("0.01"), (
        f"widget recent consumption {recent} ignored the partial fill-up (#113)"
    )
    assert abs(average - Decimal("9.43")) < Decimal("0.01"), (
        f"widget average consumption {average} ignored the partial fill-up (#113)"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_widget_window_follows_the_odometer_not_the_date(
    db_session: AsyncSession, test_user: dict[str, object]
) -> None:
    """The widget's last-10 window is on the same axis the tanks are scored on.
    The newest tank by odometer, dated a year early, must still be in it: its
    recent figure covers the last three tanks by odometer, like the card's."""
    vin = "WIDGETODOAXIS0001"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=int(test_user["id"]),  # type: ignore[arg-type]
            nickname="Axis",
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Axis",
        )
    )
    await db_session.flush()
    base = date.today() - timedelta(days=200)
    # Twelve full tanks 500 km apart: 40 L each (8.0), except the last three,
    # which burn 50 L (10.0). The newest by odometer is dated first.
    for i in range(12):
        db_session.add(
            FuelRecord(
                vin=vin,
                date=base - timedelta(days=365) if i == 11 else base + timedelta(days=i),
                odometer_km=Decimal(10000 + 500 * i),
                liters=Decimal("50") if i >= 9 else Decimal("40"),
                is_full_tank=True,
            )
        )
    await db_session.commit()

    recent, _average = await WidgetAggregationService(db_session)._consumption_l100km(vin)
    assert recent == Decimal("10.00")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_widget_recent_skips_an_impossible_tank(
    db_session: AsyncSession, test_user: dict[str, object]
) -> None:
    """A mistyped odometer sorts last. The widget's recent figure is the last
    three tanks that could be real, as on the card: (20 + 10 + 20) L over
    900 km = 5.5556, and the average 60 L over 1,000 km = 6.00."""
    vin = "WIDGETTYPO0000001"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=int(test_user["id"]),  # type: ignore[arg-type]
            nickname="Typo",
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Typo",
        )
    )
    await db_session.flush()
    base = date.today() - timedelta(days=60)
    for i, (odo, litres) in enumerate(
        [
            ("1000", "40"),
            ("1100", "10"),
            ("1500", "20"),
            ("1600", "10"),
            ("2000", "20"),
            ("200000", "20"),
        ]
    ):
        db_session.add(
            FuelRecord(
                vin=vin,
                date=base + timedelta(days=10 * i),
                odometer_km=Decimal(odo),
                liters=Decimal(litres),
                is_full_tank=True,
            )
        )
    await db_session.commit()

    recent, average = await WidgetAggregationService(db_session)._consumption_l100km(vin)
    assert recent == Decimal("5.5556")
    assert average == Decimal("6.00")
