"""Euro class and Crit'Air (#211): the V.9 reader, the date estimate, the grid."""

from __future__ import annotations

from datetime import date

import pytest

from app.utils.lez import critair_class, estimated_euro_class, euro_class_number


@pytest.mark.unit
class TestEuroClassNumber:
    @pytest.mark.parametrize(
        "text,expected",
        [
            (None, None),
            ("", None),
            ("Euro 6d-TEMP", 6),
            ("EURO6", 6),
            ("euro-5", 5),
            ("715/2007*692/2008EURO5", 5),
            ("6d", 6),
            ("4", 4),
            ("Euro 7", None),
            ("Tier 2 Bin 5", None),
            ("Class C", None),
        ],
    )
    def test_reads_the_class(self, text, expected):
        assert euro_class_number(text) == expected


@pytest.mark.unit
class TestEstimatedEuroClass:
    @pytest.mark.parametrize(
        "first,expected",
        [
            (None, None),
            (date(1992, 12, 31), None),
            (date(1993, 1, 1), 1),
            (date(1996, 12, 31), 1),
            (date(1997, 1, 1), 2),
            (date(2000, 12, 31), 2),
            (date(2001, 1, 1), 3),
            (date(2005, 12, 31), 3),
            (date(2006, 1, 1), 4),
            (date(2010, 12, 31), 4),
            (date(2011, 1, 1), 5),
            (date(2015, 8, 31), 5),
            (date(2015, 9, 1), 6),
            (date(2026, 10, 7), 6),
        ],
    )
    def test_by_date(self, first, expected):
        assert estimated_euro_class(first) == expected


def _critair(**overrides):
    kwargs = {
        "fuel_type": "gasoline",
        "fuel_type_secondary": None,
        "vehicle_type": "Car",
        "euro_class": None,
        "first_registration": None,
    }
    kwargs.update(overrides)
    return critair_class(**kwargs)


@pytest.mark.unit
class TestCritAir:
    def test_electric_and_hydrogen_are_zero(self):
        assert _critair(fuel_type="electric") == ("0", "fuel")
        assert _critair(fuel_type="hydrogen", vehicle_type="SUV") == ("0", "fuel")
        # A vehicle typed Electric with no fuel on record.
        assert _critair(fuel_type=None, vehicle_type="Electric") == ("0", "fuel")

    def test_gas_and_plugin_hybrids_are_one_whatever_the_euro_class(self):
        assert _critair(fuel_type="cng", euro_class=3) == ("1", "fuel")
        assert _critair(fuel_type="propane_lpg", first_registration=date(1998, 1, 1)) == (
            "1",
            "fuel",
        )
        assert _critair(fuel_type="plugin_hybrid", euro_class=4) == ("1", "fuel")
        assert _critair(fuel_type="gasoline", fuel_type_secondary="propane_lpg", euro_class=3) == (
            "1",
            "fuel",
        )

    @pytest.mark.parametrize(
        "euro,expected",
        [(6, "1"), (5, "1"), (4, "2"), (3, "3"), (2, "3"), (1, None)],
    )
    def test_petrol_grid_by_euro_class(self, euro, expected):
        assert _critair(euro_class=euro) == (expected, "euro_class")

    @pytest.mark.parametrize(
        "euro,expected",
        [(6, "2"), (5, "2"), (4, "3"), (3, "4"), (2, "5"), (1, None)],
    )
    def test_diesel_grid_by_euro_class(self, euro, expected):
        assert _critair(fuel_type="diesel", euro_class=euro) == (expected, "euro_class")

    def test_hybrids_follow_their_combustion_engine(self):
        assert _critair(fuel_type="hybrid", euro_class=5) == ("1", "euro_class")
        assert _critair(fuel_type="hybrid", fuel_type_secondary="diesel", euro_class=5) == (
            "2",
            "euro_class",
        )
        assert _critair(fuel_type="e85", euro_class=4) == ("2", "euro_class")

    @pytest.mark.parametrize(
        "fuel,first,expected",
        [
            ("gasoline", date(2023, 3, 12), "1"),
            ("gasoline", date(2008, 6, 1), "2"),
            ("gasoline", date(1999, 6, 1), "3"),
            ("gasoline", date(1995, 6, 1), None),
            ("diesel", date(2015, 1, 1), "2"),
            ("diesel", date(2008, 6, 1), "3"),
            ("diesel", date(2003, 6, 1), "4"),
            ("diesel", date(1999, 6, 1), "5"),
            ("diesel", date(1996, 6, 1), None),
        ],
    )
    def test_estimated_from_the_first_registration(self, fuel, first, expected):
        assert _critair(fuel_type=fuel, first_registration=first) == (
            expected,
            "first_registration",
        )

    def test_the_recorded_euro_class_wins_over_the_date(self):
        # Approved to Euro 6 before it was mandatory.
        assert _critair(euro_class=6, first_registration=date(2013, 1, 1)) == ("1", "euro_class")

    def test_nothing_to_go_on(self):
        assert _critair() == (None, None)
        assert _critair(fuel_type="other", euro_class=6) == (None, None)

    def test_other_vehicle_kinds_are_not_classified_here(self):
        assert _critair(vehicle_type="Motorcycle", euro_class=5) == (None, None)
        assert _critair(vehicle_type="Boat", fuel_type="electric") == (None, None)
        assert _critair(vehicle_type="Truck", euro_class=6) == ("1", "euro_class")
