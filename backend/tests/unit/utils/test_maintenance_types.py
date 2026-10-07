"""The maintenance-type classifier: one code, or none, never a guess.

Every description here is either from the production database that
motivated the change, from the issue that asked for it (#165), from a
built-in pack, or a deliberate near-miss that a looser matcher would get
wrong. A description that two types could claim MUST come back `None`; a
wrong code links a service to the wrong rule silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.utils.maintenance_types import (
    CODE_RE,
    REGISTRY,
    all_types,
    classify,
    get_type,
    is_valid_code,
    label_for,
    normalise,
)

PACKS_DIR = Path(__file__).resolve().parents[3] / "app" / "data" / "reminder_packs"


@pytest.mark.unit
class TestNormalise:
    def test_ampersand_becomes_and(self):
        assert normalise("Oil & Filter Change") == "oil and filter change"

    def test_punctuation_collapses_to_single_spaces(self):
        assert normalise("Brake Pads, Front (OEM)") == "brake pads front oem"

    def test_slash_and_case(self):
        assert normalise("A/C Recharge") == "a c recharge"


@pytest.mark.unit
class TestClassifyOil:
    @pytest.mark.parametrize(
        "description",
        [
            "Oil Change",
            "Oil & Filter Change",
            "Engine Oil Service",
            "Change Engine Oil & Filter",
            "Engine Oil Change",
            "Oil Filter",
            "Full synthetic oil change",
        ],
    )
    def test_oil_service_wordings_share_one_code(self, description):
        assert classify(description) == "engine_oil_filter"

    @pytest.mark.parametrize(
        "description",
        [
            "Oil pressure sensor replacement",
            "Oil pan gasket",
            "Oil leak repair",
            "Oil pump replacement",
            "Oil cooler line",
        ],
    )
    def test_oil_parts_are_not_an_oil_service(self, description):
        assert classify(description) is None

    def test_transmission_oil_is_the_transmission(self):
        assert classify("Transmission oil change") == "transmission_service"

    def test_differential_oil_is_the_differential(self):
        assert classify("Rear differential oil change") == "differential_service"

    def test_two_services_in_one_line_is_ambiguous(self):
        assert classify("Oil change and air filter") is None


@pytest.mark.unit
class TestClassifyTires:
    @pytest.mark.parametrize("description", ["Tire Rotation", "Rotate tires", "Rotate & balance"])
    def test_rotation(self, description):
        assert classify(description) == "tire_rotation"

    @pytest.mark.parametrize(
        "description", ["Tire Replacement", "New tires mounted", "Install 4 tyres"]
    )
    def test_replacement_never_collides_with_rotation(self, description):
        assert classify(description) == "tire_replacement"

    def test_rotate_and_replace_is_ambiguous(self):
        assert classify("Rotate and replace tires") is None

    def test_tpms_sensor_is_not_a_tire_replacement(self):
        assert classify("Replace TPMS sensor in tire") is None

    def test_balance_alone(self):
        assert classify("Wheel balance") == "wheel_balance"

    def test_alignment(self):
        assert classify("Four wheel alignment") == "wheel_alignment"


@pytest.mark.unit
class TestClassifyBrakesAndFluids:
    def test_flush_is_fluid(self):
        assert classify("Brake System Flush") == "brake_fluid"

    def test_pads(self):
        assert classify("Brake Pads, Front") == "brake_pads"

    def test_check_is_inspection(self):
        assert classify("Check Brakes") == "brake_inspection"

    def test_coolant(self):
        assert classify("Coolant flush") == "coolant_service"

    def test_coolant_part_is_not_a_service(self):
        assert classify("Coolant reservoir replacement") is None

    def test_transmission_replacement_is_not_a_service(self):
        assert classify("Transmission Replacement") is None

    def test_spark_plugs(self):
        assert classify("Spark plugs and wires") == "spark_plugs"

    def test_air_filter_vs_cabin(self):
        assert classify("Air Filter Inspection") == "air_filter"
        assert classify("Cabin air filter") == "cabin_air_filter"


@pytest.mark.unit
class TestClassifyProductionCorpus:
    """Every distinct line item description on the production database at the
    time of the change, with the code migration 101 will store for it."""

    @pytest.mark.parametrize(
        ("description", "expected"),
        [
            ("Oil Change", "engine_oil_filter"),
            ("Tire Rotation", "tire_rotation"),
            ("Car Wash", None),
            ("Check Brakes", "brake_inspection"),
            ("AC Coil Cleaner", "hvac_service"),
            ("AC Service", "hvac_service"),
            ("Alternator Replacement", None),
            ("B&W Companion Reciever", None),
            ("Body Repair from hail damage", None),
            ("Brake Pads, Front", "brake_pads"),
            ("Brake System Flush", "brake_fluid"),
            ("Bumper Repair", None),
            ("Butyl Seal Tape", None),
            ("Ceramic Coating", None),
            ("Change batteries in RV Lock", None),
            ("Coleman A/C 08-7335", None),
            ("Engine Oil & Filter Change", "engine_oil_filter"),
            ("Labor", None),
            ("Multi-Point Vehicle Inspection", None),
            ("Perform Recall", None),
            ("Roof Vent Cap", None),
            ("Service Call", None),
            ("Thermostat 08-7654 9420A32 (x2)", None),
            ("Tire Replacement", "tire_replacement"),
            ("Tonneau Cover", None),
        ],
    )
    def test_corpus(self, description, expected):
        assert classify(description) == expected

    def test_empty_and_none(self):
        assert classify("") is None
        assert classify(None) is None
        assert classify("---") is None


@pytest.mark.unit
class TestRegistryShape:
    def test_codes_are_unique_and_well_formed(self):
        codes = [t.code for t in REGISTRY]
        assert len(codes) == len(set(codes))
        for code in codes:
            assert CODE_RE.fullmatch(code), code

    def test_every_type_claims_its_own_label(self):
        """A label that its own type does not classify would surprise anyone
        typing the label from the picker into a line item."""
        exempt = {"drain_plug_washer", "hvac_service", "brake_pads", "timing_belt"}
        for mtype in REGISTRY:
            if mtype.code in exempt:
                continue
            assert classify(mtype.label) == mtype.code, (mtype.code, mtype.label)

    def test_shipped_pack_items_declare_known_or_self_consistent_codes(self):
        """Each pack item's title classifies to the code it declares, or the
        code is one the registry does not know and is carried verbatim."""
        for path in sorted(PACKS_DIR.glob("*.json")):
            pack = json.loads(path.read_text(encoding="utf-8"))
            for item in pack["reminders"]:
                code = item["maintenance_type"]
                assert is_valid_code(code), (path.name, code)
                if get_type(code) is not None:
                    assert classify(item["title"]) == code, (path.name, item["title"], code)

    def test_label_for_falls_back(self):
        assert label_for("engine_oil_filter") == "Engine oil and filter"
        assert label_for("custom_thing", "My rule") == "My rule"
        assert label_for("custom_thing") == "custom_thing"
        assert label_for(None, "x") == "x"

    def test_is_valid_code(self):
        assert is_valid_code("engine_oil_filter")
        assert is_valid_code("a1")
        assert not is_valid_code("Engine Oil")
        assert not is_valid_code("a")
        assert not is_valid_code("../x")

    def test_all_types_is_the_registry(self):
        assert all_types() is REGISTRY


@pytest.mark.unit
class TestClassifyInspectionEurope:
    """#211 — the periodic roadworthiness test as European owners write it."""

    @pytest.mark.parametrize(
        "description",
        [
            "Contrôle technique",
            "Controle technique périodique",
            "Contre-visite",
            "CT",
            "Passage au CT",
            "TÜV",
            "TUV",
            "HU",
            "Hauptuntersuchung",
            "APK",
            "ITV",
            "Revisione",
            "Autokeuring",
            "SNCT",
            "MOT",
            "Technical inspection",
            "Periodic roadworthiness test",
            "State inspection",
        ],
    )
    def test_european_wordings_share_the_inspection_code(self, description):
        assert classify(description) == "state_inspection"

    @pytest.mark.parametrize(
        "description",
        ["Brake inspection", "Pre purchase inspection", "Tire inspection", "Duct cleaning"],
    )
    def test_other_inspections_are_not_the_periodic_test(self, description):
        assert classify(description) != "state_inspection"
