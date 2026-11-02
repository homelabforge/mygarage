"""How a policy names its vehicles: never by a generated key (#226)."""

from __future__ import annotations

from app.models.vehicle import Vehicle
from app.services.insurance_service import _vehicle_name

Q_KEY = "QABCDEFGH12345678"


def test_a_vehicle_without_a_name_falls_back_to_its_identifier() -> None:
    tractor = Vehicle(vin=Q_KEY, nickname="", identifier_type="serial", identifier="KBT-1")
    assert _vehicle_name(tractor, Q_KEY) == "KBT-1"


def test_nothing_at_all_says_vehicle_rather_than_the_key() -> None:
    head = Vehicle(vin=Q_KEY, nickname="", identifier_type="none")
    assert _vehicle_name(head, Q_KEY) == "Vehicle"
    assert _vehicle_name(None, Q_KEY) == "Vehicle"


def test_a_vin_still_names_a_vehicle_with_nothing_else() -> None:
    vin = "1FTFW1E50NFA00001"
    assert _vehicle_name(Vehicle(vin=vin, nickname="", identifier_type="vin"), vin) == vin
    assert _vehicle_name(None, vin) == vin
    named = Vehicle(vin=vin, nickname="F-150", identifier_type="vin")
    assert _vehicle_name(named, vin) == "F-150"
