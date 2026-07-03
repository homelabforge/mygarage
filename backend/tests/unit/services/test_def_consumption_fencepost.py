"""DEF consumption-rate fence-post test (audit finding F10).

``liters_per_1000_km`` divides purchased liters by the odometer span of
the purchase records. Fuel bought at the FINAL record sits in the tank
unconsumed at the end of the span, so including it overstates
consumption by ~N/(N-1) - with the 3-record minimum that is +50%.

Scenario: 10 L purchased at 0 km, 500 km, and 1000 km. Fuel consumed
across the 1000 km span is the first two purchases (20 L), so the rate
is 20 L/1000km - not 30.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.def_service import DEFRecordService


def _record(record_date: date, odometer_km: str, liters: str) -> MagicMock:
    record = MagicMock()
    record.date = record_date
    record.odometer_km = Decimal(odometer_km)
    record.liters = Decimal(liters)
    record.cost = Decimal("10.00")
    record.fill_level = None  # avoids the tank-capacity lookup path
    record.entry_type = "purchase"
    return record


@pytest.mark.unit
@pytest.mark.def_records
@pytest.mark.asyncio
async def test_liters_per_1000_km_excludes_final_unconsumed_purchase() -> None:
    records = [
        _record(date(2026, 1, 1), "0.00", "10.000"),
        _record(date(2026, 2, 1), "500.00", "10.000"),
        _record(date(2026, 3, 1), "1000.00", "10.000"),
    ]

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = records
    mock_db.execute.return_value = mock_result

    service = DEFRecordService(mock_db)
    with patch(
        "app.services.auth.get_vehicle_or_403",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        result = await service.get_def_analytics("FENCEPOST00000001", MagicMock())

    assert result.liters_per_1000_km == Decimal("20"), (
        f"expected 20 L/1000km (final 10 L purchase is unconsumed at the end "
        f"of the span), got {result.liters_per_1000_km} - fence-post error "
        "overstating DEF consumption (audit finding F10)"
    )


@pytest.mark.unit
@pytest.mark.def_records
@pytest.mark.asyncio
async def test_purchases_tied_at_final_odometer_are_all_excluded() -> None:
    """Two purchases logged at the same final odometer are BOTH unconsumed.

    Exclusion is by odometer value, not list position (codex review R1-H2):
    dropping only one of a tie would count the other endpoint purchase as
    consumed and overstate the rate.
    """
    records = [
        _record(date(2026, 1, 1), "0.00", "10.000"),
        _record(date(2026, 2, 1), "500.00", "10.000"),
        # Two 10 L boxes bought at the same 1000 km stop.
        _record(date(2026, 3, 1), "1000.00", "10.000"),
        _record(date(2026, 3, 1), "1000.00", "10.000"),
    ]

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = records
    mock_db.execute.return_value = mock_result

    service = DEFRecordService(mock_db)
    with patch(
        "app.services.auth.get_vehicle_or_403",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        result = await service.get_def_analytics("FENCEPOST00000002", MagicMock())

    assert result.liters_per_1000_km == Decimal("20"), (
        f"expected 20 L/1000km (both endpoint purchases unconsumed), got "
        f"{result.liters_per_1000_km}"
    )
