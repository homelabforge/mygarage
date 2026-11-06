"""Make and model Title Case (#219 takeover): canonical makes, the ALL-CAPS model rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.utils.vehicle_names import canonical_makes, fold_key, normalize_make, normalize_model

_MAKES_FILE = Path(__file__).resolve().parents[3] / "app" / "data" / "vehicle_makes.json"
_MODELS_FILE = Path(__file__).resolve().parents[3] / "app" / "data" / "vehicle_models.json"


@pytest.mark.unit
class TestNormalizeMake:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("MITSUBISHI", "Mitsubishi"),
            ("mitsubishi", "Mitsubishi"),
            ("RAM", "Ram"),
            ("BMW", "BMW"),
            ("bmw", "BMW"),
            ("GMC", "GMC"),
            ("MINI", "MINI"),
            ("Mini", "MINI"),
            ("SEAT", "SEAT"),
            ("SMART", "Smart"),
            ("smart", "Smart"),
            ("MERCEDES-BENZ", "Mercedes-Benz"),
            ("MERCEDES BENZ", "Mercedes-Benz"),
            ("MCLAREN", "McLaren"),
            ("LAND ROVER", "Land Rover"),
            ("ROLLS ROYCE", "Rolls-Royce"),
            ("SKODA", "Škoda"),
            ("Skoda", "Škoda"),
            ("CITROEN", "Citroën"),
            ("HARLEY DAVIDSON", "Harley-Davidson"),
            ("CAN-AM", "Can-Am"),
            ("vw", "Volkswagen"),
            ("VW", "Volkswagen"),
            ("CHEVY", "Chevrolet"),
            ("Chevy", "Chevrolet"),
            ("Mercedes", "Mercedes-Benz"),
            ("  Honda  ", "Honda"),
        ],
    )
    def test_known_makes_take_the_canonical_spelling(self, raw, expected):
        assert normalize_make(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("KZ-RV", "KZ-RV"),
            ("FOREST RIVER", "Forest River"),
            ("Some Small Maker", "Some Small Maker"),
            ("tinyco", "tinyco"),
        ],
    )
    def test_unknown_makes_get_the_word_rule_only_when_all_caps(self, raw, expected):
        assert normalize_make(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_blank_is_none(self, raw):
        assert normalize_make(raw) is None


@pytest.mark.unit
class TestNormalizeModel:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("MIRAGE", "Mirage"),
            ("MIRAGE G4", "Mirage G4"),
            ("GRAND CHEROKEE", "Grand Cherokee"),
            ("OUTLANDER SPORT", "Outlander Sport"),
            ("XC90", "XC90"),
            ("RAV4", "RAV4"),
            ("3500", "3500"),
            ("F-150", "F-150"),
            ("CR-V", "CR-V"),
            ("C-HR", "C-HR"),
            ("MX-5", "MX-5"),
            ("GTI", "GTI"),
            ("GT", "GT"),
            ("WRX", "WRX"),
            ("GLC", "GLC"),
            ("FIT", "Fit"),
            ("RIO", "Rio"),
            ("FOX", "Fox"),
            ("MODEL 3", "Model 3"),
            ("OUTLANDER / AIRTREK", "Outlander / Airtrek"),
            ("SANTA FE SPORT", "Santa Fe Sport"),
            ("DE VILLE", "De Ville"),
            ("LE", "LE"),
        ],
    )
    def test_all_caps_models_get_the_word_rule(self, raw, expected):
        assert normalize_model(raw) == expected

    def test_a_model_outside_the_catalog_gets_the_word_rule(self):
        assert normalize_model("ZORBLAX ONE GTX") == "Zorblax One Gtx"

    @pytest.mark.parametrize(
        "raw", ["McLaren", "e-tron", "328i", "Mirage", "iX", "up!", "Outlander / Airtrek"]
    )
    def test_mixed_case_is_never_touched(self, raw):
        assert normalize_model(raw) == raw

    def test_strips_surrounding_space(self):
        assert normalize_model("  Accord ") == "Accord"

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_blank_is_none(self, raw):
        assert normalize_model(raw) is None


@pytest.mark.unit
class TestCatalogModelSpellings:
    """Fable diff F-1: a model picked from the catalog is saved as the catalog spells it."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("DBS", "DBS"),
            ("ZOE", "ZOE"),
            ("296 GTB", "296 GTB"),
            ("308 GTB/GTS", "308 GTB/GTS"),
            ("UNI-K", "UNI-K"),
            ("ID.3 GTX", "ID.3 GTX"),
            ("A2 E-TRON", "A2 e-tron"),
            ("MIRAGE G4", "Mirage G4"),
        ],
    )
    def test_all_caps_input_takes_the_catalog_spelling(self, raw, expected):
        assert normalize_model(raw) == expected

    def test_a_model_two_makes_spell_differently_gets_the_word_rule(self):
        # Saturn Ion and Peugeot iOn: no one spelling to pick.
        assert normalize_model("ION") == "Ion"

    def test_mixed_case_still_wins_over_the_catalog(self):
        assert normalize_model("Zoe") == "Zoe"

    def test_every_catalog_model_saves_as_written(self):
        models: dict[str, list[str]] = json.loads(_MODELS_FILE.read_text(encoding="utf-8"))
        changed = [
            f"{make}: {model} -> {normalize_model(model)}"
            for make, names in models.items()
            for model in names
            if normalize_model(model) != model
        ]
        assert changed == []


@pytest.mark.unit
class TestFoldKey:
    def test_folds_case_diacritics_and_punctuation(self):
        assert fold_key("Škoda") == fold_key("SKODA") == "skoda"
        assert fold_key("Mercedes-Benz") == fold_key("MERCEDES BENZ") == "mercedesbenz"
        assert fold_key("Lynk & Co") == "lynkco"


@pytest.mark.unit
class TestCanonicalData:
    def test_every_canonical_make_is_a_fixed_point(self):
        makes = canonical_makes()
        assert len(makes) > 150
        for make in makes:
            assert normalize_make(make) == make
            assert normalize_make(make.upper()) == make
            assert normalize_make(make.lower()) == make

    def test_no_two_canonical_makes_share_a_folded_key(self):
        keys = [fold_key(m) for m in canonical_makes()]
        assert len(keys) == len(set(keys))

    def test_every_alias_points_at_a_canonical_make(self):
        data = json.loads(_MAKES_FILE.read_text(encoding="utf-8"))
        makes = set(data["makes"])
        for alias, target in data["aliases"].items():
            assert target in makes, alias
            assert fold_key(alias) == alias, alias

    def test_every_wmi_make_is_canonical(self):
        wmi = json.loads((_MAKES_FILE.parent / "wmi.json").read_text(encoding="utf-8"))
        makes = set(canonical_makes())
        for code, entry in wmi["wmi"].items():
            assert entry["make"] in makes, (code, entry["make"])

    @pytest.mark.parametrize(
        "make",
        [
            "Mitsubishi",
            "Ram",
            "Jeep",
            "Dodge",
            "Škoda",
            "Citroën",
            "MINI",
            "SEAT",
            "Smart",
            "McLaren",
            "Lynk & Co",
        ],
    )
    def test_anchor_makes_are_present(self, make):
        assert make in canonical_makes()

    def test_model_rule_is_idempotent(self):
        for raw in ["MIRAGE G4", "SANTA FE SPORT", "CR-V", "GRAND CHEROKEE", "FIT", "Mirage"]:
            once = normalize_model(raw)
            assert normalize_model(once) == once
