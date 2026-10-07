"""Unit tests for fuel-tracking enums + NHTSA fuel-string normalization.

Covers:
- Direct enum value pass-through
- Common alias normalization (gas/petrol/octane grades, EV, PHEV, ...)
- NHTSA capitalized strings ("Gasoline", "Diesel", ...)
- Combined NHTSA strings ("Gasoline, Hybrid Electric", "Gasoline, E85 (Flex Fuel)")
- Unrecognized inputs return None (caller decides on 'other' fallback)
"""

import pytest

from app.constants.fuel import (
    CARTE_GRISE_ENERGY_CODES,
    FUEL_GRADE_VALUES,
    FUEL_TYPE_VALUES,
    GRADES_FOR_FUEL_TYPE,
    PAYMENT_METHOD_VALUES,
    TRIP_TYPE_VALUES,
    FuelGradeEnum,
    FuelTypeEnum,
    PaymentMethod,
    TripType,
    normalize_fuel_type,
    split_combined_fuel_type,
)


class TestEnumVocabularies:
    def test_payment_method_canonical_values(self):
        assert PaymentMethod.CASH.value == "cash"
        assert PaymentMethod.CREDIT.value == "credit"
        assert PaymentMethod.FLEET_CARD.value == "fleet_card"
        assert "cash" in PAYMENT_METHOD_VALUES
        assert "credit" in PAYMENT_METHOD_VALUES

    def test_trip_type_canonical_values(self):
        assert TripType.PRIVATE.value == "private"
        assert TripType.BUSINESS.value == "business"
        assert TripType.COMMUTE.value == "commute"
        assert "private" in TRIP_TYPE_VALUES

    def test_fuel_type_enum_complete(self):
        # Defensive: if a new enum value is added without backfill mapping,
        # existing migrations would happily skip it (since it's now valid)
        # but the test surface should still enumerate it.
        expected = {
            "gasoline",
            "diesel",
            "electric",
            "hybrid",
            "plugin_hybrid",
            "e85",
            "propane_lpg",
            "cng",
            "hydrogen",
            "other",
        }
        assert set(FUEL_TYPE_VALUES) == expected
        for value in expected:
            assert FuelTypeEnum(value).value == value


class TestNormalizeFuelType:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            # Direct enum values pass through
            ("gasoline", FuelTypeEnum.GASOLINE),
            ("diesel", FuelTypeEnum.DIESEL),
            ("electric", FuelTypeEnum.ELECTRIC),
            ("plugin_hybrid", FuelTypeEnum.PLUGIN_HYBRID),
            # Case-insensitive
            ("Gasoline", FuelTypeEnum.GASOLINE),
            ("DIESEL", FuelTypeEnum.DIESEL),
            ("Electric", FuelTypeEnum.ELECTRIC),
            # Common aliases
            ("gas", FuelTypeEnum.GASOLINE),
            ("petrol", FuelTypeEnum.GASOLINE),
            ("Premium", FuelTypeEnum.GASOLINE),
            ("Regular", FuelTypeEnum.GASOLINE),
            ("87", FuelTypeEnum.GASOLINE),
            ("91", FuelTypeEnum.GASOLINE),
            ("EV", FuelTypeEnum.ELECTRIC),
            ("phev", FuelTypeEnum.PLUGIN_HYBRID),
            ("Plug-In Hybrid", FuelTypeEnum.PLUGIN_HYBRID),
            ("Flex Fuel", FuelTypeEnum.E85),
            ("LPG", FuelTypeEnum.PROPANE_LPG),
            ("Propane", FuelTypeEnum.PROPANE_LPG),
            ("Compressed Natural Gas (CNG)", FuelTypeEnum.CNG),
            ("Fuel Cell", FuelTypeEnum.HYDROGEN),
            ("Biodiesel", FuelTypeEnum.DIESEL),
        ],
    )
    def test_recognizes(self, raw: str, expected: FuelTypeEnum):
        assert normalize_fuel_type(raw) is expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # #211 — the words on a European pump or registration certificate.
            # French
            ("Essence", FuelTypeEnum.GASOLINE),
            ("sans plomb", FuelTypeEnum.GASOLINE),
            ("SP95", FuelTypeEnum.GASOLINE),
            ("SP95-E10", FuelTypeEnum.GASOLINE),
            ("E10", FuelTypeEnum.GASOLINE),
            ("SP98", FuelTypeEnum.GASOLINE),
            ("Gazole", FuelTypeEnum.DIESEL),
            ("gasoil", FuelTypeEnum.DIESEL),
            ("B7", FuelTypeEnum.DIESEL),
            ("HVO", FuelTypeEnum.DIESEL),
            ("XTL", FuelTypeEnum.DIESEL),
            ("Électrique", FuelTypeEnum.ELECTRIC),
            ("Hybride", FuelTypeEnum.HYBRID),
            ("Hybride rechargeable", FuelTypeEnum.PLUGIN_HYBRID),
            ("Superéthanol", FuelTypeEnum.E85),
            ("GPL", FuelTypeEnum.PROPANE_LPG),
            ("GNV", FuelTypeEnum.CNG),
            ("Hydrogène", FuelTypeEnum.HYDROGEN),
            # German
            ("Benzin", FuelTypeEnum.GASOLINE),
            ("Super E10", FuelTypeEnum.GASOLINE),
            ("Super Plus", FuelTypeEnum.GASOLINE),
            ("Elektro", FuelTypeEnum.ELECTRIC),
            ("Erdgas", FuelTypeEnum.CNG),
            ("Autogas", FuelTypeEnum.PROPANE_LPG),
            ("Wasserstoff", FuelTypeEnum.HYDROGEN),
            # Italian
            ("Benzina", FuelTypeEnum.GASOLINE),
            ("Gasolio", FuelTypeEnum.DIESEL),
            ("Metano", FuelTypeEnum.CNG),
            ("Elettrica", FuelTypeEnum.ELECTRIC),
            ("Ibrida", FuelTypeEnum.HYBRID),
            # Dutch
            ("Benzine", FuelTypeEnum.GASOLINE),
            ("Aardgas", FuelTypeEnum.CNG),
            ("Waterstof", FuelTypeEnum.HYDROGEN),
            # Spanish
            ("Gasolina", FuelTypeEnum.GASOLINE),
            ("Gasóleo", FuelTypeEnum.DIESEL),
            ("Eléctrico", FuelTypeEnum.ELECTRIC),
            ("Híbrido", FuelTypeEnum.HYBRID),
            ("GLP", FuelTypeEnum.PROPANE_LPG),
            ("GNC", FuelTypeEnum.CNG),
        ],
    )
    def test_recognizes_european_aliases(self, raw: str, expected: FuelTypeEnum):
        assert normalize_fuel_type(raw) is expected

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            "Quantum Fluctuator",
            "Plutonium",
            "??",
        ],
    )
    def test_unrecognized_returns_none(self, raw):
        assert normalize_fuel_type(raw) is None


class TestFuelGrades:
    """EN 16942 pump labels (#211): the vocabulary of `fuel_records.fuel_grade`."""

    def test_en16942_vocabulary_complete(self):
        expected = {
            "E5",
            "E10",
            "E85",
            "B7",
            "B10",
            "B20",
            "B30",
            "B100",
            "XTL",
            "H2",
            "CNG",
            "LPG",
            "LNG",
        }
        assert set(FUEL_GRADE_VALUES) == expected
        for value in expected:
            assert FuelGradeEnum(value).value == value

    def test_every_grade_belongs_to_at_least_one_fuel_type(self):
        offered = {g for grades in GRADES_FOR_FUEL_TYPE.values() for g in grades}
        assert offered == set(FuelGradeEnum)

    @pytest.mark.parametrize(
        "fuel_type,grades",
        [
            (FuelTypeEnum.GASOLINE, ("E5", "E10")),
            (FuelTypeEnum.HYBRID, ("E5", "E10")),
            (FuelTypeEnum.PLUGIN_HYBRID, ("E5", "E10")),
            (FuelTypeEnum.E85, ("E85",)),
            (FuelTypeEnum.DIESEL, ("B7", "B10", "B20", "B30", "B100", "XTL")),
            (FuelTypeEnum.PROPANE_LPG, ("LPG",)),
            (FuelTypeEnum.CNG, ("CNG", "LNG")),
            (FuelTypeEnum.HYDROGEN, ("H2",)),
        ],
    )
    def test_grades_for_fuel_type(self, fuel_type, grades):
        assert tuple(g.value for g in GRADES_FOR_FUEL_TYPE[fuel_type]) == grades

    def test_electric_and_other_offer_no_grade(self):
        assert FuelTypeEnum.ELECTRIC not in GRADES_FOR_FUEL_TYPE
        assert FuelTypeEnum.OTHER not in GRADES_FOR_FUEL_TYPE


class TestCarteGriseEnergyCodes:
    """Field P.3 of the EU registration certificate (directive 1999/37/EC),
    as the French carte grise spells it. Consumed by the certificate import."""

    @pytest.mark.parametrize(
        "code,primary,secondary",
        [
            ("ES", FuelTypeEnum.GASOLINE, None),
            ("GO", FuelTypeEnum.DIESEL, None),
            ("EL", FuelTypeEnum.ELECTRIC, None),
            ("EE", FuelTypeEnum.PLUGIN_HYBRID, FuelTypeEnum.ELECTRIC),
            ("EH", FuelTypeEnum.HYBRID, FuelTypeEnum.ELECTRIC),
            ("GL", FuelTypeEnum.PLUGIN_HYBRID, FuelTypeEnum.ELECTRIC),
            ("GH", FuelTypeEnum.HYBRID, FuelTypeEnum.ELECTRIC),
            ("GP", FuelTypeEnum.PROPANE_LPG, None),
            ("GN", FuelTypeEnum.CNG, None),
            ("FE", FuelTypeEnum.E85, None),
            ("H2", FuelTypeEnum.HYDROGEN, None),
            ("EG", FuelTypeEnum.GASOLINE, FuelTypeEnum.PROPANE_LPG),
            ("EN", FuelTypeEnum.GASOLINE, FuelTypeEnum.CNG),
        ],
    )
    def test_code_maps_to_fuel_types(self, code, primary, secondary):
        assert CARTE_GRISE_ENERGY_CODES[code] == (primary, secondary)

    def test_codes_are_two_uppercase_characters_and_known_fuels(self):
        for code, (primary, secondary) in CARTE_GRISE_ENERGY_CODES.items():
            assert len(code) == 2 and code == code.upper()
            assert primary.value in FUEL_TYPE_VALUES
            assert secondary is None or secondary.value in FUEL_TYPE_VALUES


class TestSplitCombinedFuelType:
    @pytest.mark.parametrize(
        "raw,primary,secondary",
        [
            (
                "Gasoline, Hybrid Electric",
                FuelTypeEnum.HYBRID,
                FuelTypeEnum.ELECTRIC,
            ),
            (
                "Plug-In Hybrid",
                FuelTypeEnum.PLUGIN_HYBRID,
                FuelTypeEnum.ELECTRIC,
            ),
            ("PHEV", FuelTypeEnum.PLUGIN_HYBRID, FuelTypeEnum.ELECTRIC),
            (
                "Gasoline, E85 (Flex Fuel)",
                FuelTypeEnum.GASOLINE,
                FuelTypeEnum.E85,
            ),
        ],
    )
    def test_decodes_combined(self, raw, primary, secondary):
        p, s = split_combined_fuel_type(raw)
        assert p is primary
        assert s is secondary

    @pytest.mark.parametrize(
        "raw",
        [None, "", "Gasoline", "Diesel", "Electric", "garbage"],
    )
    def test_non_combined_returns_none_pair(self, raw):
        p, s = split_combined_fuel_type(raw)
        assert p is None
        assert s is None
