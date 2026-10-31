"""The shipped DTC definitions file, the one 033 seeds from and 125 corrects to.

The first file was shifted (P0300 read "Cylinder 12 Contribution") and nothing
checked a meaning, only the shape. These pin the shape 033 reads AND what known
codes say, so a regenerated file can't drop a key, a code, or a row's meaning.
"""

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_DATA = Path(__file__).resolve().parents[2] / "app" / "data"
_KEYS = {
    "code",
    "description",
    "category",
    "subcategory",
    "severity",
    "estimated_severity_level",
    "is_emissions_related",
}
_CODE_RE = re.compile(r"^[PBCU][0-9A-F]{4}$")
_MAKER_RANGE = re.compile(r"^(P1|P3[0-3]|[BCU][12])")
_CATEGORY = {"P": "powertrain", "B": "body", "C": "chassis", "U": "network"}
# The subcategory names in the plan's Design (a); anything else is a typo.
_SUBCATEGORIES = {
    "fuel_air_metering",
    "fuel_injection",
    "ignition",
    "emissions",
    "vehicle_speed",
    "computer",
    "transmission",
    "oxygen_sensor",
    "fuel_system",
    "cooling",
    "airbag",
    "safety",
    "climate",
    "access",
    "lighting",
    "brakes",
    "steering",
    "suspension",
    "traction_control",
    "can_bus",
}

N = r"(?:cylinder|cyl\.?|#)\s*"
AIRFLOW = r"(mass or volume air ?flow|mass air ?flow|\bmaf\b|air ?flow)"
EVAP = r"(evap|evaporative)"
# code: ([all-of patterns], [none-of patterns]), from the research's anchor table.
ANCHORS: dict[str, tuple[list[str], list[str]]] = {
    "P0010": ([r"cam", r"actuator"], [r"bank\s*2", r"\b(low|high)\b"]),
    "P0011": ([r"cam", r"(timing|advanc)"], [r"bank\s*2", r"retard"]),
    "P0100": ([AIRFLOW, r"circuit"], [r"range|perf|\blow\b|\bhigh\b|intermit"]),
    "P0101": ([AIRFLOW, r"(range|perf)"], []),
    "P0113": ([r"intake air", r"temp", r"high"], [r"too high"]),
    "P0118": ([r"coolant", r"temp", r"high"], []),
    "P0125": ([r"insufficient coolant", r"closed loop"], []),
    "P0126": ([r"insufficient coolant", r"stable"], []),
    "P0127": ([r"intake air", r"temp", r"too high"], []),
    "P0128": ([r"thermostat"], []),
    "P0130": (
        [r"(o2|oxygen|ho2s)", r"bank\s*1\b", r"sensor\s*1"],
        [r"heater|\blow\b|\bhigh\b|slow|no activity"],
    ),
    "P0171": ([r"lean", r"bank\s*1\b"], []),
    "P0172": ([r"rich", r"bank\s*1\b"], []),
    "P0174": ([r"lean", r"bank\s*2"], []),
    "P0201": ([r"injector", N + r"1\b"], []),
    "P0299": ([r"(turbo|super ?charger)", r"underboost"], []),
    "P0300": ([r"(random|multiple)", r"misfire"], []),
    "P0301": ([N + r"1\b", r"misfire"], []),
    "P0306": ([N + r"6\b", r"misfire"], []),
    "P0325": (
        [r"knock", r"circuit"],
        [r"sensor\s*2|bank\s*2|\blow\b|\bhigh\b|range|perf|intermit"],
    ),
    "P0335": (
        [r"crank", r"position", r"circuit"],
        [r"range|perf|\blow\b|\bhigh\b|intermit|\bb\b"],
    ),
    "P0340": (
        [r"cam", r"position", r"(sensor|circuit)"],
        [r"range|perf|\blow\b|\bhigh\b|intermit|actuator|bank\s*2"],
    ),
    "P0401": ([r"(egr|exhaust gas recirculation)", r"insufficient"], []),
    "P0420": ([r"catalyst", r"efficiency", r"threshold", r"bank\s*1\b"], [r"warm|heated"]),
    "P0430": ([r"catalyst", r"efficiency", r"threshold", r"bank\s*2"], [r"warm|heated"]),
    "P0440": ([EVAP], [r"leak|purge|vent|pressure|switch|flow"]),
    "P0442": ([EVAP, r"small"], [r"very small"]),
    "P0455": ([EVAP, r"(large|gross|no flow)"], []),
    "P0456": ([EVAP, r"very small"], []),
    "P0500": ([r"vehicle speed"], [r"range|perf|intermit|\blow\b|\bhigh\b|\bb\b"]),
    "P0505": ([r"idle", r"(air control|control system|idle control)"], [r"\blow\b|\bhigh\b|rpm"]),
    "P0507": ([r"idle", r"higher than expected"], []),
    "P0562": ([r"system voltage", r"low"], []),
    "P0606": ([r"(module|ecm|pcm)", r"processor"], []),
    "P0700": ([r"transmission control"], []),
    "P0715": (
        [r"(input|turbine)", r"speed sensor"],
        [r"range|perf|\blow\b|\bhigh\b|intermit|\bb\b"],
    ),
    "P0741": ([r"torque converter clutch", r"(perf|stuck off)"], []),
    "P2000": ([r"nox", r"(trap|adsorber|absorber)", r"efficiency"], []),
    "P2002": ([r"particulate", r"efficiency"], []),
    "P2096": ([r"post cat", r"trim", r"lean"], []),
    "P2135": ([r"(throttle|pedal)", r"correlation"], []),
    "P0A80": ([r"replace hybrid(/ev)? battery"], []),
    "P3400": ([r"cylinder deactivation", r"bank\s*1\b"], []),
    "U0073": ([r"bus", r"off"], []),
    "U0100": ([r"lost comm", r"(ecm|pcm)"], []),
    "U0101": ([r"lost comm", r"tcm"], []),
    "U0121": ([r"lost comm", r"(abs|anti.?lock)"], []),
    "B0001": ([r"driver", r"frontal", r"stage\s*1"], []),
}


@pytest.fixture(scope="module")
def entries() -> list[dict[str, object]]:
    """The parsed dtc_definitions.json."""
    return json.loads((_DATA / "dtc_definitions.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def descriptions(entries: list[dict[str, object]]) -> dict[str, str]:
    """Code to description, with straight quotes dropped for matching."""
    return {str(e["code"]): str(e["description"]).replace('"', "") for e in entries}


def _says(description: str, pattern: str) -> bool:
    return re.search(pattern, description, re.IGNORECASE) is not None


def test_file_has_9341_entries(entries: list[dict[str, object]]) -> None:
    assert isinstance(entries, list)
    assert len(entries) == 9341


def test_codes_are_unique_well_formed_and_sorted(entries: list[dict[str, object]]) -> None:
    codes = [e["code"] for e in entries]
    assert len(set(codes)) == len(codes)
    bad = [c for c in codes if not (isinstance(c, str) and _CODE_RE.match(c))]
    assert bad == []
    assert codes == sorted(codes)


def test_only_sae_ranges(entries: list[dict[str, object]]) -> None:
    """Maker ranges mean different things per maker, so none ship."""
    maker = [e["code"] for e in entries if _MAKER_RANGE.match(str(e["code"]))]
    assert maker == []


def test_every_entry_has_exactly_the_seven_keys(entries: list[dict[str, object]]) -> None:
    wrong = [e.get("code") for e in entries if set(e) != _KEYS]
    assert wrong == []


def test_field_values(entries: list[dict[str, object]]) -> None:
    for e in entries:
        code = str(e["code"])
        description = e["description"]
        assert isinstance(description, str) and description.strip(), code
        assert description.isascii(), code
        assert not _CODE_RE.match(description), code
        assert not _says(description, r"reserved|manufacturer controlled"), code
        assert e["category"] == _CATEGORY[code[0]], code
        assert e["severity"] in {"critical", "warning", "info"}, code
        level = e["estimated_severity_level"]
        # bool is an int subclass, so rule it out explicitly.
        assert isinstance(level, int) and not isinstance(level, bool), code
        assert level in {2, 3, 4}, code
        assert isinstance(e["is_emissions_related"], bool), code
        assert e["subcategory"] is None or e["subcategory"] in _SUBCATEGORIES, code


def test_every_enrichment_code_is_present(entries: list[dict[str, object]]) -> None:
    enrichment = json.loads((_DATA / "dtc_phase2_enrichment.json").read_text(encoding="utf-8"))
    codes = {e["code"] for e in entries}
    missing = [r["code"] for r in enrichment if r["code"] not in codes]
    assert enrichment
    assert missing == []


def test_license_ships_beside_the_data() -> None:
    text = (_DATA / "dtc_definitions.LICENSE.txt").read_text(encoding="utf-8")
    assert "Copyright (c) 2024 Wal33D (Waleed Judah)" in text
    assert "Copyright (c) 2023 Lenny Kean" in text
    assert "04c43d72e7db7197658b6f72fe582c5076d9eee8" in text
    assert "bdd618ea487e9e85c7f3b4d142ce783337752f3b" in text
    assert "SAE J2012" in text


@pytest.mark.parametrize(("code", "patterns"), sorted(ANCHORS.items()))
def test_anchor_meanings(
    descriptions: dict[str, str], code: str, patterns: tuple[list[str], list[str]]
) -> None:
    all_of, none_of = patterns
    assert code in descriptions
    description = descriptions[code]
    assert [p for p in all_of if not _says(description, p)] == [], description
    assert [p for p in none_of if _says(description, p)] == [], description


def test_patterned_ranges(descriptions: dict[str, str]) -> None:
    """Runs of codes that number cylinders or coils: a shifted file breaks the count."""
    for n in range(1, 13):
        misfire = descriptions[f"P03{n:02d}"]
        assert _says(misfire, N + rf"{n}\b") and _says(misfire, r"misfire"), misfire
        injector = descriptions[f"P02{n:02d}"]
        assert _says(injector, r"injector") and _says(injector, N + rf"{n}\b"), injector
        coil = descriptions[f"P03{50 + n}"]
        assert _says(coil, rf"coil {'ABCDEFGHIJKL'[n - 1]}\b"), coil
    lost = {code: d for code, d in descriptions.items() if code.startswith("U01")}
    assert lost
    assert [code for code, d in lost.items() if not _says(d, r"lost communication")] == []


def test_c0035_c0040_follow_the_sae_layout(descriptions: dict[str, str]) -> None:
    """C0035/C0040 carry the SAE J2012-DA meanings (D3).

    Older GM vehicles use the legacy layout (C0035 left front wheel speed
    sensor), so a GM owner may see a different code meaning than the shop's.
    """
    c0035 = descriptions["C0035"]
    assert all(_says(c0035, p) for p in (r"right front", r"wheel speed", r"supply")), c0035
    assert _says(descriptions["C0040"], r"brake pedal switch"), descriptions["C0040"]


def test_the_shift_is_gone(descriptions: dict[str, str]) -> None:
    """The three most-cited wrong rows of the first file."""
    assert not _says(descriptions["P0300"], r"cylinder 12 contribution")
    assert not _says(descriptions["P0420"], r"secondary air")
    assert not _says(descriptions["P0700"], r"fuel level")


# code: (description, severity, level). S1d-06: the PTO shutdown circuit codes
# are wire faults, not a forced shutdown; P23A9 and U3001 are real shutdowns.
SEVERITY_ANCHORS: dict[str, tuple[str, str, int]] = {
    "P251D": ("PTO Engine Shutdown Circuit/Open", "warning", 2),
    "P251E": ("PTO Engine Shutdown Circuit Low", "warning", 2),
    "P251F": ("PTO Engine Shutdown Circuit High", "warning", 2),
    "P23A9": ("Communication Fault - Forced Engine Shutdown", "critical", 4),
    "U3001": ("Control Module Improper Shutdown Performance", "critical", 4),
}


@pytest.mark.parametrize(("code", "expected"), sorted(SEVERITY_ANCHORS.items()))
def test_severity_anchors(
    entries: list[dict[str, object]], code: str, expected: tuple[str, str, int]
) -> None:
    by_code = {e["code"]: e for e in entries}
    e = by_code[code]
    assert (e["description"], e["severity"], e["estimated_severity_level"]) == expected
