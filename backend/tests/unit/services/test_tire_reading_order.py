"""Same-day readings sort by (recorded_at, id), the order the tire's tread uses (TR L-1).

`_newest_with` already broke a same-day tie on id, but `project_wear`,
`_to_response` and the analytics readiness list sorted on the date alone. A
stable descending sort keeps equal dates in load order, and the database usually
hands readings over lowest id first, so the OLDER entry of a same-day pair came out
on top. The projection then read the pair backwards.

Both load orders run. The lowest-id-first half is the one red on 7cd960cf; the
other half passed there too and stays as a guard.
"""

from __future__ import annotations

import datetime as dt
from datetime import datetime
from decimal import Decimal

import pytest

from app.models.tire import Tire, TireMountPeriod, TireReading
from app.schemas.tire import TireReadingResponse, TireResponse
from app.services.analytics_service.tires import _tread_bearing, tire_readiness
from app.services.tire_results import WearStatus
from app.services.tire_service import TireService, project_wear
from app.services.usage_axis import VehicleAxes

DAY = dt.date(2026, 5, 1)
VIN = "V" * 17

# guard: the highest-id-first case passed on 7cd960cf too. Lowest-id-first is the defect.
LOAD_ORDERS = pytest.mark.parametrize(
    "lowest_id_first",
    [True, False],
    ids=["lowest-id-first", "highest-id-first"],
)


def _reading(rid: int, odo: str, tread: str) -> TireReading:
    return TireReading(
        id=rid,
        tire_id=1,
        vin=VIN,
        position="FL",
        recorded_at=DAY,
        odometer_km=Decimal(odo),
        tread_depth_mm=Decimal(tread),
        created_at=datetime(2026, 5, 1),
    )


def _tire(lowest_id_first: bool) -> Tire:
    """One open period from zero, two readings on one day. Id 2 is the later one:
    500 km further on and 0.5 mm thinner."""
    tire = Tire(
        id=1,
        vin=VIN,
        position="FL",
        min_tread_mm=Decimal("2.0"),
        tread_depth_mm=Decimal("5.5"),
        created_at=datetime(2026, 1, 1),
    )
    tire.mount_periods = [
        TireMountPeriod(
            id=1,
            position="FL",
            mounted_on=dt.date(2026, 1, 1),
            dismounted_on=None,
            mounted_odometer_km=Decimal("0"),
            is_assumed=False,
        )
    ]
    pair = [_reading(1, "10000", "6.0"), _reading(2, "10500", "5.5")]
    tire.readings = pair if lowest_id_first else pair[::-1]
    return tire


class TestProjectWear:
    @LOAD_ORDERS
    def test_the_higher_id_is_the_newer_reading(self, lowest_id_first: bool):
        tire = _tire(lowest_id_first)
        result = project_wear(tire, Decimal("10500"), axis=VehicleAxes.distance_only().primary)
        # 0.5 mm over 500 km, 3.5 mm left above the minimum. Read backwards the
        # tread goes UP and the figure disappears as tread_not_decreasing.
        assert result.status is WearStatus.PROJECTED
        assert result.km_remaining == Decimal("3500.0")
        # Same day, so no rate per day and no date.
        assert result.wear_date is None


class TestToResponse:
    @LOAD_ORDERS
    def test_the_higher_id_is_listed_first(self, lowest_id_first: bool):
        tire = _tire(lowest_id_first)
        # Pure formatting, no session needed.
        service = TireService.__new__(TireService)
        payload = service._to_response(
            tire, VehicleAxes.distance_only(), current_odometer=Decimal("10500")
        )
        assert [r.id for r in payload.readings] == [2, 1]
        assert payload.wear_status == "projected"
        assert payload.projected_km_remaining == Decimal("3500.0")


def _response_reading(rid: int, day: dt.date, odo: str | None) -> TireReadingResponse:
    return TireReadingResponse(
        id=rid,
        tire_id=1,
        vin=VIN,
        position="FL",
        recorded_at=day,
        odometer_km=None if odo is None else Decimal(odo),
        tread_depth_mm=Decimal("6.0"),
        pressure_kpa=None,
        notes=None,
        created_at=datetime(2026, 1, 1),
    )


def _response_tire(readings: list[TireReadingResponse]) -> TireResponse:
    return TireResponse(
        id=1,
        vin=VIN,
        position="FL",
        min_tread_mm=Decimal("2.0"),
        below_threshold=False,
        retired_on=None,
        wear_status="projected",
        distance_status="complete",
        created_at=datetime(2026, 1, 1),
        readings=readings,
    )


class TestAnalyticsReadiness:
    @LOAD_ORDERS
    def test_the_higher_id_comes_first(self, lowest_id_first: bool):
        pair = [_response_reading(1, DAY, "10000"), _response_reading(2, DAY, "10500")]
        tire = _response_tire(pair if lowest_id_first else pair[::-1])
        assert [r.id for r in _tread_bearing(tire)] == [2, 1]

    @LOAD_ORDERS
    def test_the_odometer_prompt_reads_the_same_pair_project_wear_does(self, lowest_id_first: bool):
        # Newest is id 3 on its own day. Ids 1 and 2 tie for second, and only
        # id 2 (the newer of the tie) is the reading project_wear differences.
        # It has an odometer, so nothing needs one.
        tied = [
            _response_reading(1, DAY, None),
            _response_reading(2, DAY, "10500"),
        ]
        newest = _response_reading(3, dt.date(2026, 6, 1), "12000")
        readings = [*tied, newest] if lowest_id_first else [newest, *tied[::-1]]
        result = tire_readiness([_response_tire(readings)])
        assert result.can_trend == 1
        assert result.needs_reading_odometer == 0
