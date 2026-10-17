"""Declared units are held per device until a value arrives (#223, fable-plan/F-3)."""

import pytest

from app.services import declared_units


@pytest.fixture(autouse=True)
def _empty_map():
    """The map is process-wide; start and leave it empty."""
    declared_units._BY_DEVICE.clear()
    yield
    declared_units._BY_DEVICE.clear()


def test_a_device_keeps_what_it_declared_and_only_it():
    declared_units.remember("tq_0000a004", {"K33": "kPa", "K3C": "°C"})
    declared_units.remember("tq_0000a004", {"K33": "Pa"})  # a later session start wins, key by key
    assert declared_units.unit_for("tq_0000a004", "K33") == "Pa"
    assert declared_units.unit_for("tq_0000a004", "K3C") == "°C"
    assert declared_units.unit_for("tq_0000b004", "K33") is None
    assert declared_units.unit_for("tq_0000a004", "K23") is None


def test_a_device_holds_at_most_512_keys_and_still_updates_those():
    """A stream of made-up PIDs stops at the cap; a key already held keeps updating."""
    declared_units.remember("tq_0000a004", {f"K{i:04X}": "kPa" for i in range(600)})
    held = declared_units._BY_DEVICE["tq_0000a004"]
    assert len(held) == 512
    assert declared_units.unit_for("tq_0000a004", "K01FF") == "kPa"  # the 512th
    assert declared_units.unit_for("tq_0000a004", "K0200") is None  # the 513th

    declared_units.remember("tq_0000a004", {"K0000": "psi", "KFFFF": "V"})
    assert declared_units.unit_for("tq_0000a004", "K0000") == "psi"
    assert declared_units.unit_for("tq_0000a004", "KFFFF") is None
    assert len(held) == 512

    declared_units.remember("tq_0000b004", {"K0200": "kPa"})  # per device
    assert declared_units.unit_for("tq_0000b004", "K0200") == "kPa"
