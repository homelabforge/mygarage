"""Unit tests for the diesel/DEF-capability predicate and HTTP gate.

Covers `is_diesel_vehicle` (app/constants/fuel.py) and `ensure_def_capable`
(app/utils/def_sync.py). Both must normalize internally so gates work
against legacy, non-canonical DB values even before migration 061 runs.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.constants.fuel import is_diesel_vehicle
from app.utils.def_sync import ensure_def_capable


class TestIsDieselVehicle:
    """Pure predicate: True iff either fuel slot normalizes to diesel."""

    def test_diesel_primary(self) -> None:
        assert is_diesel_vehicle("diesel", "gasoline") is True

    def test_diesel_secondary(self) -> None:
        assert is_diesel_vehicle("gasoline", "diesel") is True

    def test_legacy_cased_diesel_primary(self) -> None:
        assert is_diesel_vehicle("Diesel", None) is True

    def test_legacy_biodiesel_alias(self) -> None:
        assert is_diesel_vehicle("biodiesel", None) is True

    def test_gasoline_only_is_false(self) -> None:
        assert is_diesel_vehicle("gasoline", None) is False

    def test_none_none_is_false(self) -> None:
        assert is_diesel_vehicle(None, None) is False

    def test_secondary_defaults_to_none(self) -> None:
        assert is_diesel_vehicle("gasoline") is False


class TestEnsureDefCapable:
    """HTTP gate: raises 400 unless the vehicle can use DEF."""

    def test_no_raise_on_diesel_primary(self) -> None:
        vehicle = SimpleNamespace(fuel_type="diesel", fuel_type_secondary=None)
        ensure_def_capable(vehicle)  # should not raise

    def test_no_raise_on_diesel_secondary(self) -> None:
        vehicle = SimpleNamespace(fuel_type="gasoline", fuel_type_secondary="diesel")
        ensure_def_capable(vehicle)  # should not raise

    def test_raises_400_on_gasoline(self) -> None:
        vehicle = SimpleNamespace(fuel_type="gasoline", fuel_type_secondary=None)
        with pytest.raises(HTTPException) as exc_info:
            ensure_def_capable(vehicle)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "DEF tracking applies only to diesel vehicles"
