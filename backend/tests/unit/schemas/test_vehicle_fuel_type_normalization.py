"""Unit tests for the fuel-type normalizing validator on Vehicle input schemas.

Task 1 of the fuel-type hardening plan: `vehicles.fuel_type` /
`fuel_type_secondary` are free text today. `VehicleCreate` / `VehicleUpdate`
must normalize recognized free-text/NHTSA spellings to the canonical
`FuelTypeEnum` vocabulary and reject unrecognized values with a 422 (via
`ValueError` -> Pydantic `ValidationError`), while `VehicleResponse` (which
validates from DB attributes) must remain permissive so a legacy
unrecognized value already sitting in the database does not 500 a read.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate

VIN = "1HGBH41JXMN109186"


def _create_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "vin": VIN,
        "nickname": "Test Car",
        "vehicle_type": "Car",
    }
    kwargs.update(overrides)
    return kwargs


class TestVehicleCreateFuelTypeNormalization:
    def test_normalizes_capitalized_diesel(self):
        v = VehicleCreate.model_validate({**_create_kwargs(fuel_type="Diesel")})
        assert v.fuel_type == "diesel"

    def test_normalizes_uppercase_with_trailing_whitespace(self):
        v = VehicleCreate.model_validate({**_create_kwargs(fuel_type="GASOLINE ")})
        assert v.fuel_type == "gasoline"

    def test_normalizes_phev_alias(self):
        v = VehicleCreate.model_validate({**_create_kwargs(fuel_type="PHEV")})
        assert v.fuel_type == "plugin_hybrid"

    def test_normalizes_octane_grade(self):
        v = VehicleCreate.model_validate({**_create_kwargs(fuel_type="87")})
        assert v.fuel_type == "gasoline"

    def test_empty_string_becomes_none(self):
        v = VehicleCreate.model_validate({**_create_kwargs(fuel_type="")})
        assert v.fuel_type is None

    def test_whitespace_only_becomes_none(self):
        v = VehicleCreate.model_validate({**_create_kwargs(fuel_type="   ")})
        assert v.fuel_type is None

    def test_none_stays_none(self):
        v = VehicleCreate.model_validate({**_create_kwargs(fuel_type=None)})
        assert v.fuel_type is None

    def test_unrecognized_value_raises_422(self):
        with pytest.raises(ValidationError) as excinfo:
            VehicleCreate.model_validate({**_create_kwargs(fuel_type="warp-core")})
        message = str(excinfo.value)
        assert "warp-core" in message
        # Canonical values must be listed to guide the caller.
        assert "gasoline" in message
        assert "diesel" in message

    def test_secondary_fuel_type_is_also_normalized(self):
        v = VehicleCreate.model_validate({**_create_kwargs(fuel_type_secondary="Electric")})
        assert v.fuel_type_secondary == "electric"

    def test_secondary_fuel_type_unrecognized_raises_422(self):
        with pytest.raises(ValidationError):
            VehicleCreate.model_validate({**_create_kwargs(fuel_type_secondary="unobtanium")})


class TestVehicleUpdateFuelTypeNormalization:
    def test_normalizes_capitalized_diesel(self):
        v = VehicleUpdate(fuel_type="Diesel")
        assert v.fuel_type == "diesel"

    def test_normalizes_phev_alias(self):
        v = VehicleUpdate(fuel_type="PHEV")
        assert v.fuel_type == "plugin_hybrid"

    def test_empty_string_becomes_none(self):
        v = VehicleUpdate(fuel_type="")
        assert v.fuel_type is None

    def test_none_stays_none(self):
        v = VehicleUpdate(fuel_type=None)
        assert v.fuel_type is None

    def test_unrecognized_value_raises_422(self):
        with pytest.raises(ValidationError):
            VehicleUpdate(fuel_type="warp-core")


class TestVehicleResponseAcceptsLegacyValues:
    """VehicleResponse must NOT validate fuel_type — it reads from the DB.

    A vehicle row written before this validator existed (or backfilled from
    a free-text CSV import) may carry an unrecognized fuel_type string.
    Reading that vehicle must not 500.
    """

    def test_model_validate_with_bogus_fuel_type_does_not_raise(self):
        class _FakeVehicleRow:
            vin = VIN
            nickname = "Legacy Car"
            vehicle_type = "Car"
            year = None
            make = None
            model = None
            license_plate = None
            color = None
            purchase_date = None
            purchase_price = None
            sold_date = None
            sold_price = None
            trim = None
            body_class = None
            drive_type = None
            doors = None
            gvwr_class = None
            displacement_l = None
            cylinders = None
            fuel_type = "Ye Olde Petrol"
            fuel_type_secondary = None
            transmission_type = None
            transmission_speeds = None
            def_tank_capacity_liters = None
            main_photo = None
            created_at = datetime(2025, 1, 1)
            updated_at = None
            window_sticker_file_path = None
            window_sticker_uploaded_at = None
            msrp_base = None
            msrp_options = None
            msrp_total = None
            fuel_economy_city_l_per_100km = None
            fuel_economy_highway_l_per_100km = None
            fuel_economy_combined_l_per_100km = None
            standard_equipment = None
            optional_equipment = None
            assembly_location = None
            destination_charge = None
            window_sticker_options_detail = None
            window_sticker_packages = None
            exterior_color = None
            interior_color = None
            sticker_engine_description = None
            sticker_transmission_description = None
            sticker_drivetrain = None
            wheel_specs = None
            tire_specs = None
            warranty_powertrain = None
            warranty_basic = None
            environmental_rating_ghg = None
            environmental_rating_smog = None
            window_sticker_parser_used = None
            window_sticker_confidence_score = None
            window_sticker_extracted_vin = None
            archived_at = None
            archive_reason = None
            archive_sale_price = None
            archive_sale_date = None
            archive_notes = None
            archived_visible = True

        response = VehicleResponse.model_validate(_FakeVehicleRow(), from_attributes=True)
        assert response.fuel_type == "Ye Olde Petrol"
