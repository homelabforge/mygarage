"""Make and model are normalized on the way in, never on the way out (#219 takeover)."""

from __future__ import annotations

import pytest

from app.schemas.external_vehicle import ExternalVehicleCreate, ExternalVehicleUpdate
from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate


@pytest.mark.unit
class TestVehicleWriters:
    def test_create_normalizes(self):
        body = VehicleCreate.model_validate(
            {"nickname": "Mirage", "vehicle_type": "Car", "identifier_type": "none",
             "make": "MITSUBISHI", "model": "MIRAGE G4"}
        )  # fmt: skip
        assert (body.make, body.model) == ("Mitsubishi", "Mirage G4")

    def test_update_normalizes(self):
        body = VehicleUpdate.model_validate({"make": "RAM", "model": "3500"})
        assert (body.make, body.model) == ("Ram", "3500")

    def test_mixed_case_model_is_kept(self):
        body = VehicleUpdate.model_validate({"make": "mclaren", "model": "720S"})
        assert (body.make, body.model) == ("McLaren", "720S")

    def test_blank_reads_as_none(self):
        body = VehicleUpdate.model_validate({"make": "  ", "model": ""})
        assert (body.make, body.model) == (None, None)

    def test_a_non_string_is_still_refused(self):
        with pytest.raises(ValueError):
            VehicleUpdate.model_validate({"make": 42})

    def test_the_response_reads_the_stored_text_raw(self):
        # A legacy row must still read; 159 rewrites it, the response never does.
        fields = VehicleResponse.model_fields
        assert "make" in fields
        validators = VehicleResponse.__pydantic_decorators__.field_validators
        assert not any({"make", "model"} & set(v.info.fields) for v in validators.values())


@pytest.mark.unit
class TestExternalVehicleWriters:
    def test_create_normalizes(self):
        body = ExternalVehicleCreate.model_validate(
            {"nickname": "Dad's", "make": "TOYOTA", "model": "RAV4"}
        )
        assert (body.make, body.model) == ("Toyota", "RAV4")

    def test_update_normalizes(self):
        body = ExternalVehicleUpdate.model_validate({"make": "SKODA", "model": "OCTAVIA"})
        assert (body.make, body.model) == ("Škoda", "Octavia")
