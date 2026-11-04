"""Wheel layouts (#272): the table, the position codes, and which layout a vehicle gets."""

from __future__ import annotations

import logging
from typing import get_args

import pytest

from app.constants.wheel_layouts import (
    BRAKE_AXLE_OF,
    WHEEL_LAYOUTS,
    BrakePosition,
    TirePosition,
    WheelLayoutId,
    default_wheel_layout,
    resolve_wheel_layout,
)
from app.schemas.vehicle import VehicleType
from app.utils import lenient_vocab

_LOGGER = "app.utils.lenient_vocab"


@pytest.fixture(autouse=True)
def _nothing_warned_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with an empty once-only set."""
    monkeypatch.setattr(lenient_vocab, "_warned", set())


@pytest.mark.unit
class TestTable:
    def test_layout_positions_are_exactly_the_vocabulary(self) -> None:
        used = {p for lay in WHEEL_LAYOUTS.values() for p in lay.tire_positions}
        assert used == set(get_args(TirePosition))
        used_b = {p for lay in WHEEL_LAYOUTS.values() for p in lay.brake_positions}
        assert used_b == set(get_args(BrakePosition))

    def test_every_layout_id_has_a_row_keyed_by_its_own_id(self) -> None:
        assert list(WHEEL_LAYOUTS) == list(get_args(WheelLayoutId))
        for layout_id, layout in WHEEL_LAYOUTS.items():
            assert layout.id == layout_id

    def test_every_brake_position_has_an_axle(self) -> None:
        assert set(BRAKE_AXLE_OF) == set(get_args(BrakePosition))
        assert BRAKE_AXLE_OF["F"] == "front" and BRAKE_AXLE_OF["R"] == "rear"
        front = {p for p, axle in BRAKE_AXLE_OF.items() if axle == "front"}
        assert front == {"FL", "FR", "F"}

    def test_layout_table_pins(self) -> None:
        # The plan's table, every row.
        rows = {i: (lay.tire_positions, lay.brake_positions) for i, lay in WHEEL_LAYOUTS.items()}
        assert rows == {
            "four": (("FL", "FR", "RL", "RR", "SPARE"), ("FL", "FR", "RL", "RR")),
            "two": (("F", "R"), ("F", "R")),
            "trike_2f1r": (("FL", "FR", "R"), ("FL", "FR", "R")),
            "trike_1f2r": (("F", "RL", "RR"), ("F", "RL", "RR")),
            "dually": (
                ("FL", "FR", "RLO", "RLI", "RRI", "RRO", "SPARE"),
                ("FL", "FR", "RL", "RR"),
            ),
            "none": ((), ()),
        }
        assert [i for i, lay in WHEEL_LAYOUTS.items() if lay.rotates] == ["four"]

    def test_old_homes_re_export_the_same_vocabularies(self) -> None:
        from app.schemas import brake as brake_schemas
        from app.schemas import tire as tire_schemas
        from app.services import brake_wear

        assert tire_schemas.TirePosition is TirePosition
        assert brake_schemas.BrakePosition is BrakePosition
        assert brake_wear.AXLE_OF is BRAKE_AXLE_OF


@pytest.mark.unit
class TestDefaults:
    def test_default_pins(self) -> None:
        assert default_wheel_layout("Motorcycle") == "two"
        assert default_wheel_layout("EBike") == "two"
        assert default_wheel_layout("Boat") == "none"
        assert default_wheel_layout("RV") == "four"
        assert default_wheel_layout(None) == "four"

    def test_every_type_off_four_is_pinned(self) -> None:
        off_four = {t: default_wheel_layout(t) for t in get_args(VehicleType)}
        off_four = {t: lay for t, lay in off_four.items() if lay != "four"}
        assert off_four == {
            "Motorcycle": "two",
            "Bicycle": "two",
            "EBike": "two",
            "Boat": "none",
            "Snowmobile": "none",
            "Generator": "none",
            "SmallEngine": "none",
            "Attachment": "none",
        }

    def test_an_unknown_type_is_four(self) -> None:
        assert default_wheel_layout("Hovercraft") == "four"
        assert default_wheel_layout("") == "four"


@pytest.mark.unit
class TestResolve:
    def test_resolve_prefers_stored_and_survives_garbage(self) -> None:
        assert resolve_wheel_layout("dually", "Truck").id == "dually"
        assert resolve_wheel_layout(None, "Motorcycle").id == "two"
        assert resolve_wheel_layout("hovercraft", "Motorcycle").id == "two"

    def test_a_stored_layout_beats_the_type_default(self) -> None:
        assert resolve_wheel_layout("four", "Boat").id == "four"
        assert resolve_wheel_layout("none", "Car").id == "none"

    def test_garbage_is_logged_once(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            resolve_wheel_layout("hovercraft", "Motorcycle")
            resolve_wheel_layout("hovercraft", "Motorcycle")
        warnings = [r for r in caplog.records if r.name == _LOGGER]
        assert len(warnings) == 1
        assert "wheel_layout" in warnings[0].getMessage()
        assert "hovercraft" in warnings[0].getMessage()

    def test_a_missing_layout_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            resolve_wheel_layout(None, "Car")
            resolve_wheel_layout("two", "Car")
        assert [r for r in caplog.records if r.name == _LOGGER] == []

    def test_the_warning_names_the_vehicle(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            resolve_wheel_layout("hovercraft", "Motorcycle", vin="1HGCM82633A004352")
        (warning,) = [r for r in caplog.records if r.name == _LOGGER]
        assert "1HGCM82633A004352" in warning.getMessage()
        assert "Motorcycle" in warning.getMessage()

    def test_an_empty_layout_reads_as_none(self, caplog: pytest.LogCaptureFixture) -> None:
        # A blank cell from a hand-edited restore is "nothing stored", not garbage.
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            assert resolve_wheel_layout("", "Motorcycle").id == "two"
            assert resolve_wheel_layout("", "Car").id == "four"
        assert [r for r in caplog.records if r.name == _LOGGER] == []
