"""Unit tests for third-party fuel CSV adapters, tire wear, and webhook fuel commands."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

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
        "Date,Odometer (km),Quantity (liters),Price/liter,Total cost\n01/01/2026,1000,40,1.5,60\n"
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
    vehicle_key, payload = _parse_fuel_command("fuel 1HGCM82633A004352 45000 40.5 1.55 62.78")
    assert vehicle_key == "1HGCM82633A004352"
    assert payload.odometer_km == Decimal("45000")
    assert payload.liters == Decimal("40.5")
    assert payload.kwh is None
    assert payload.price_per_unit == Decimal("1.55")
    assert payload.cost == Decimal("62.78")
    assert payload.price_basis == "per_volume"


def test_parse_fuel_command_imperial_and_kwh():
    vehicle_key, payload = _parse_fuel_command("fuel Model3 15000mi 42.5kWh 0.20 8.50")
    assert vehicle_key == "Model3"
    assert payload.odometer_km == Decimal("15000") * Decimal("1.609344")
    assert payload.kwh == Decimal("42.5")
    assert payload.liters is None
    assert payload.price_basis == "per_kwh"
    assert payload.price_per_unit == Decimal("0.20")
    assert payload.cost == Decimal("8.50")


def test_parse_fuel_command_gal_converts_price_to_per_liter():
    _key, payload = _parse_fuel_command("fuel Civic 10000mi 12gal 3.50")
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


class TestChargeFieldValidation:
    """Create was validated; update and the webhook payload were not."""

    def test_update_rejects_bad_charge_level(self):
        from app.schemas.fuel import FuelRecordUpdate

        with pytest.raises(ValidationError):
            FuelRecordUpdate(charge_level="L3")

    def test_update_rejects_bad_charge_location(self):
        from app.schemas.fuel import FuelRecordUpdate

        with pytest.raises(ValidationError):
            FuelRecordUpdate(charge_location="work")

    def test_update_accepts_valid_values(self):
        from app.schemas.fuel import FuelRecordUpdate

        assert FuelRecordUpdate(charge_level="DCFC").charge_level == "DCFC"
        assert FuelRecordUpdate(charge_location="home").charge_location == "home"

    def test_webhook_payload_rejects_bad_charge_level(self):
        from app.routes.webhooks import WebhookFuelPayload

        with pytest.raises(ValidationError):
            WebhookFuelPayload(vin="1HGCM82633A004352", charge_level="L4")

    @pytest.mark.parametrize(
        "field,value",
        [
            ("soc_start_pct", 101),
            ("soc_end_pct", -1),
            ("battery_soh_pct", 150),
            ("liters", -5),
            ("odometer_km", -1),
        ],
    )
    def test_webhook_payload_rejects_out_of_range(self, field, value):
        from app.routes.webhooks import WebhookFuelPayload

        with pytest.raises(ValidationError):
            WebhookFuelPayload(vin="1HGCM82633A004352", **{field: value})

    def test_webhook_payload_allows_charge_session_without_odometer_or_amount(self):
        """The webhook contract is deliberately looser than FuelRecordCreate."""
        from app.routes.webhooks import WebhookFuelPayload

        payload = WebhookFuelPayload(vin="1HGCM82633A004352", kwh=45)
        assert payload.odometer_km is None


def test_parse_fuel_command_accepts_long_nickname():
    """Vehicle.nickname is String(100); the payload's vin is capped at 17.

    Building the payload straight from the raw key raised a bare pydantic
    ValidationError inside the handler, surfacing as a 500 rather than a 400,
    and Telegram then retried the same update forever.
    """
    vehicle_key, payload = _parse_fuel_command("fuel MyOtherDailyDriver 45000 40")
    assert vehicle_key == "MyOtherDailyDriver"
    assert payload.odometer_km == Decimal("45000")


class TestParseOptions:
    """Odometer unit and decimal separator are declared, never guessed."""

    def test_comma_decimal_is_not_multiplied(self):
        from app.services.import_adapters.fuel_csv import ParseOptions

        csv_data = (
            "Data,Odômetro,Quantidade (litros),Preço/litro,Total\n"
            '2026-01-15,45000,"35,2","1,55","54,56"\n'
        )
        rows = parse_drivvo(csv_data, ParseOptions(decimal_separator="comma"))
        assert rows[0]["liters"] == Decimal("35.2")
        assert rows[0]["price_per_unit"] == Decimal("1.55")

    def test_dot_separator_strips_thousands_commas(self):
        from app.services.import_adapters.fuel_csv import _dec

        assert _dec("1,234.5") == Decimal("1234.5")

    def test_comma_separator_converts_to_dot(self):
        from app.services.import_adapters.fuel_csv import _dec

        assert _dec("35,2", sep="comma") == Decimal("35.2")
        assert _dec("1.234,5", sep="comma") == Decimal("1234.5")

    def test_miles_odometer_is_converted(self):
        from app.services.import_adapters.fuel_csv import ParseOptions

        csv_data = "Date,Odometer,Gallons,Price,Total cost\n2026-01-15,12345,10,3.50,35.00\n"
        rows = parse_fuelio(csv_data, ParseOptions(odometer_unit="mi"))
        assert rows[0]["odometer_km"] == Decimal("12345") * Decimal("1.609344")

    def test_unambiguous_header_overrides_the_option(self):
        from app.services.import_adapters.fuel_csv import ParseOptions

        csv_data = "Date,Odometer (mi),Liters\n2026-01-15,12345,40\n"
        rows = parse_drivvo(csv_data, ParseOptions(odometer_unit="km"))
        assert rows[0]["odometer_km"] == Decimal("12345") * Decimal("1.609344")

    def test_km_header_ignores_a_miles_declaration(self):
        from app.services.import_adapters.fuel_csv import ParseOptions

        csv_data = "Date,Odometer (km),Liters\n2026-01-15,12345,40\n"
        rows = parse_drivvo(csv_data, ParseOptions(odometer_unit="mi"))
        assert rows[0]["odometer_km"] == Decimal("12345")

    def test_defaults_are_metric_and_dot(self):
        from app.services.import_adapters.fuel_csv import ParseOptions

        assert ParseOptions().odometer_unit == "km"
        assert ParseOptions().decimal_separator == "dot"

    def test_parsers_still_work_without_options(self):
        csv_data = "Date,Odometer,Liters,Price,Total cost\n2026-01-15,45000,40,1.50,60.00\n"
        rows = parse_fuelio(csv_data)
        assert rows[0]["odometer_km"] == Decimal("45000")


def test_odometro_alone_is_not_classified_drivvo():
    """`a and b or c` binds as `(a and b) or c`.

    Any header set containing 'odometro' was classified Drivvo regardless of the
    intended 'data' guard, so the file went to a parser that finds none of its
    columns and silently imported zero rows. After the fix it is unrecognized,
    which the endpoint reports as an explicit 400 instead.
    """
    assert detect_format("Fecha,odometro,Gallons,Price\n2026-01-15,45000,10,3.50\n") is None


def test_drivvo_pt_still_detected():
    assert detect_format("Data,Odômetro,Quantidade (litros)\n2026-01-15,45000,35.2\n") == "drivvo"
