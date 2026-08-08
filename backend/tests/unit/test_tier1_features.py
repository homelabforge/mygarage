"""Unit tests for third-party fuel CSV adapters, tire wear, and webhook fuel commands."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.routes.webhooks import _parse_fuel_command
from app.schemas.fuel import FuelRecordCreate
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


def test_detect_format_fuelio():
    csv_data = "Date,Odometer,Fuel Type,Volume(l),Price,Total cost\n2026-01-01,1,Gas,10,1,10\n"
    assert detect_format(csv_data) == "fuelio"


def test_detect_format_drivvo():
    csv_data = (
        "Date,Odometer (km),Quantity (liters),Price/liter,Total cost\n"
        "01/01/2026,1000,40,1.5,60\n"
    )
    assert detect_format(csv_data) == "drivvo"


def test_project_wear():
    readings = [
        _Reading(date(2026, 6, 1), Decimal("12000"), Decimal("4.0")),
        _Reading(date(2026, 1, 1), Decimal("10000"), Decimal("6.0")),
    ]
    km_left, wear_date = _project_wear(readings, Decimal("2.0"))
    assert km_left is not None
    assert km_left == Decimal("2000.0")
    assert wear_date is not None


def test_project_wear_needs_two_readings():
    readings = [_Reading(date(2026, 1, 1), Decimal("10000"), Decimal("6.0"))]
    assert _project_wear(readings, Decimal("2.0")) == (None, None)


def test_project_wear_already_below_threshold():
    readings = [
        _Reading(date(2026, 6, 1), Decimal("12000"), Decimal("1.5")),
        _Reading(date(2026, 1, 1), Decimal("10000"), Decimal("6.0")),
    ]
    km_left, wear_date = _project_wear(readings, Decimal("2.0"))
    assert km_left == Decimal("0")
    assert wear_date == date(2026, 6, 1)


def test_parse_fuel_command_metric():
    payload = _parse_fuel_command("fuel 1HGCM82633A004352 45000 40.5 1.55 62.78")
    assert payload.vin == "1HGCM82633A004352"
    assert payload.odometer_km == Decimal("45000")
    assert payload.liters == Decimal("40.5")
    assert payload.kwh is None
    assert payload.price_per_unit == Decimal("1.55")
    assert payload.cost == Decimal("62.78")
    assert payload.price_basis == "per_volume"


def test_parse_fuel_command_imperial_and_kwh():
    payload = _parse_fuel_command("fuel Model3 15000mi 42.5kWh 0.20 8.50")
    assert payload.vin == "Model3"
    assert payload.odometer_km == Decimal("15000") * Decimal("1.609344")
    assert payload.kwh == Decimal("42.5")
    assert payload.liters is None
    assert payload.price_basis == "per_kwh"
    assert payload.price_per_unit == Decimal("0.20")
    assert payload.cost == Decimal("8.50")


def test_parse_fuel_command_gal_converts_price_to_per_liter():
    payload = _parse_fuel_command("fuel Civic 10000mi 12gal 3.50")
    assert payload.liters == Decimal("12") * Decimal("3.785411784")
    assert payload.price_per_unit == Decimal("3.50") / Decimal("3.785411784")
    assert payload.price_basis == "per_volume"


def test_parse_fuel_command_rejects_garbage():
    with pytest.raises(HTTPException) as exc:
        _parse_fuel_command("charge now please")
    assert exc.value.status_code == 400


def test_fuel_record_create_accepts_ev_charge_session_fields():
    record = FuelRecordCreate(
        vin="5YJSA1E26MF123456",
        date=date(2026, 3, 1),
        odometer_km=Decimal("25000"),
        kwh=Decimal("42.5"),
        price_basis="per_kwh",
        price_per_unit=Decimal("0.20"),
        cost=Decimal("8.50"),
        soc_start_pct=Decimal("18"),
        soc_end_pct=Decimal("80"),
        charge_level="L2",
        charge_location="home",
        battery_soh_pct=Decimal("94"),
        fuel_type_used="electric",
    )
    assert record.soc_start_pct == Decimal("18")
    assert record.charge_level == "L2"
    assert record.charge_location == "home"


def test_fuel_record_create_rejects_bad_charge_level():
    with pytest.raises(Exception):
        FuelRecordCreate(
            vin="5YJSA1E26MF123456",
            date=date(2026, 3, 1),
            odometer_km=Decimal("25000"),
            kwh=Decimal("10"),
            charge_level="L3",
        )
