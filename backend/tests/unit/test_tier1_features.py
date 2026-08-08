"""Unit tests for third-party fuel CSV adapters and tire wear projection."""

from datetime import date
from decimal import Decimal

from app.services.import_adapters.fuel_csv import (
    detect_format,
    parse_drivvo,
    parse_fuelio,
    parse_tesla,
)
from app.services.tire_service import _project_wear


class _Reading:
    def __init__(self, recorded_at, odometer_km, tread_depth_mm):
        self.recorded_at = recorded_at
        self.odometer_km = odometer_km
        self.tread_depth_mm = tread_depth_mm


def test_parse_fuelio_metric():
    csv_data = (
        "Date,Odometer,Fuel Type,Volume(l),Price,Total cost,Full tank,Notes\n"
        "2026-01-15,12345.0,Gasoline,40.5,1.499,60.71,1,Shell\n"
    )
    rows = parse_fuelio(csv_data)
    assert len(rows) == 1
    assert rows[0]["date"] == date(2026, 1, 15)
    assert rows[0]["liters"] == Decimal("40.5")
    assert rows[0]["odometer_km"] == Decimal("12345.0")
    assert rows[0]["is_full_tank"] is True


def test_parse_drivvo():
    csv_data = (
        "Date,Odometer (km),Quantity (liters),Price/liter,Total cost,Full tank,Notes\n"
        "15/01/2026,20000,35.2,1.55,54.56,yes,BP\n"
    )
    rows = parse_drivvo(csv_data)
    assert len(rows) == 1
    assert rows[0]["liters"] == Decimal("35.2")
    assert rows[0]["odometer_km"] == Decimal("20000")


def test_parse_tesla_charge():
    csv_data = (
        "Charge End Date,Energy Added (kWh),Odometer,Cost,Starting SOC,Ending SOC,"
        "Charge Type,Location\n"
        "2026-03-01,42.5,15000,8.50,20,80,L2,Home\n"
    )
    rows = parse_tesla(csv_data)
    assert len(rows) == 1
    assert rows[0]["kwh"] == Decimal("42.5")
    assert rows[0]["soc_start_pct"] == Decimal("20")
    assert rows[0]["soc_end_pct"] == Decimal("80")
    assert rows[0]["charge_level"] == "L2"
    assert rows[0]["charge_location"] == "home"
    assert rows[0]["price_basis"] == "per_kwh"


def test_detect_format_tesla():
    csv_data = "Charge Start Date,Charge End Date,Energy Added\n2026-01-01,2026-01-01,10\n"
    assert detect_format(csv_data) == "tesla"


def test_project_wear():
    readings = [
        _Reading(date(2026, 6, 1), Decimal("12000"), Decimal("4.0")),
        _Reading(date(2026, 1, 1), Decimal("10000"), Decimal("6.0")),
    ]
    km_left, wear_date = _project_wear(readings, Decimal("2.0"))
    assert km_left is not None
    assert km_left == Decimal("2000.0")
    assert wear_date is not None
