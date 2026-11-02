"""The vehicle key: a real VIN, or a generated Q-key for a vehicle without one (#226)."""

import pytest
from app.utils.vehicle_key import (
    IDENTIFIER_TYPES,
    display_identifier,
    generate_vehicle_key,
    is_synthetic_key,
    is_vehicle_key,
)

from app.utils.vin import validate_vin


class _V:
    def __init__(self, vin: str, identifier_type: str = "vin", identifier: str | None = None):
        self.vin = vin
        self.identifier_type = identifier_type
        self.identifier = identifier


def test_generated_keys_never_pass_as_a_vin() -> None:
    for _ in range(500):
        key = generate_vehicle_key()
        assert validate_vin(key)[0] is False
        assert is_synthetic_key(key)


def test_generated_keys_fit_every_length_17_schema_and_the_delete_cleanup() -> None:
    for _ in range(500):
        key = generate_vehicle_key()
        assert len(key) == 17
        assert key.isalnum()
        assert key == key.upper()
        assert is_vehicle_key(key)


def test_generated_keys_are_not_repeated() -> None:
    assert len({generate_vehicle_key() for _ in range(2000)}) == 2000


@pytest.mark.parametrize(
    "key",
    ["1HGCM82633A004352", "QABCDEFGH12345678", "Q1234567890ABCDEF"],
)
def test_is_vehicle_key_accepts_vins_and_q_keys(key: str) -> None:
    assert is_vehicle_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../../etc/passwd",
        "1HGCM82633A00435",
        "QABCDEFGH1234567O",
        "qabcdefgh12345678",
        "Q/BCDEFGH12345678",
    ],
)
def test_is_vehicle_key_refuses_anything_else(key: str) -> None:
    assert not is_vehicle_key(key)


def test_a_real_vin_is_not_synthetic() -> None:
    assert not is_synthetic_key("1HGCM82633A004352")


def test_display_identifier_shows_the_vin_for_a_vin_vehicle() -> None:
    assert display_identifier(_V("1HGCM82633A004352")) == ("vin", "1HGCM82633A004352")


def test_display_identifier_never_shows_a_q_key() -> None:
    v = _V(generate_vehicle_key(), "serial", "KBT-55123")
    assert display_identifier(v) == ("serial", "KBT-55123")
    none = _V(generate_vehicle_key(), "none", None)
    assert display_identifier(none) == ("none", None)


def test_display_identifier_on_a_converted_fake_vin_shows_the_serial() -> None:
    # seanauff's workaround: a generated VIN, later switched to the real serial.
    v = _V("1HGCM82633A004352", "serial", "BX23S-10234")
    assert display_identifier(v) == ("serial", "BX23S-10234")


def test_identifier_types() -> None:
    assert IDENTIFIER_TYPES == ("vin", "serial", "hin", "chassis", "asset_tag", "none")
