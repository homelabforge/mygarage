"""The DTC definitions generator: parsing, the cross-check, the derived fields.

The shipped file is built from pinned upstream lists, so these pin the rules
that turn a `CODE - Description` line into a row, and the refusals that stop a
changed or unreadable input from becoming a quietly wrong file.
"""

import json
from pathlib import Path

import pytest

from tools.build_dtc_definitions import (
    derive,
    disagreements,
    is_sae_range,
    main,
    parse_cross_check,
    parse_source,
    render,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("code", "sae"),
    [
        ("P0100", True),
        ("P0A80", True),
        ("P1000", False),
        ("P2000", True),
        ("P3000", False),
        ("P33FF", False),
        ("P3400", True),
        ("P39FF", True),
        ("B0001", True),
        ("B1000", False),
        ("B2000", False),
        ("B3001", True),
        ("C0035", True),
        ("C1000", False),
        ("C2000", False),
        ("C3000", True),
        ("U0100", True),
        ("U1000", False),
        ("U2000", False),
        ("U3000", True),
    ],
)
def test_is_sae_range(code: str, sae: bool) -> None:
    assert is_sae_range(code) is sae


def test_parse_splits_on_the_first_separator_and_normalises() -> None:
    text = (
        "P23A9 - Communication Fault \u2013 Forced Engine Shutdown\n"
        "C0619 - Brake Pedal Position Sensor \u201cA\u201d Offset Exceeded Learning Limit\n"
    )
    assert parse_source(text) == {
        "P23A9": "Communication Fault - Forced Engine Shutdown",
        "C0619": "Brake Pedal Position Sensor A Offset Exceeded Learning Limit",
    }


def test_parse_skips_a_description_that_is_a_code_then_keeps_the_next() -> None:
    text = "P3400 - P34C8\nP3400 - Cylinder Deactivation System Bank 1\n"
    assert parse_source(text) == {"P3400": "Cylinder Deactivation System Bank 1"}


def test_parse_keeps_the_first_real_description() -> None:
    text = "P0100 - Mass Air Flow Circuit\nP0100 - Something Later\n"
    assert parse_source(text) == {"P0100": "Mass Air Flow Circuit"}


def test_parse_drops_placeholders_and_maker_ranges() -> None:
    text = "B3000 - B3000-B3999 ISO/SAE Reserved\nP1000 - OBD System Readiness Test Not Complete\n"
    assert parse_source(text) == {}


@pytest.mark.parametrize(
    "line", ["P0100 Mass Air Flow", "XX100 - Bad code", "P0100 - Caf\u00e9 Sensor"]
)
def test_parse_refuses_what_it_cannot_read(line: str) -> None:
    with pytest.raises(ValueError):
        parse_source(line + "\n")


def test_cross_check_parses_the_enum_and_unescapes_quotes() -> None:
    cs = (
        '    [Category(Categories.Chassis), Description("Brake Booster Motor \\"B\\" Performance")]\n'
        "    C062C = 0x462C,\n"
        '    [Category(Categories.Powertrain), Description("Manufacturer Controlled DTC")]\n'
        "    P1000 = 0x1000,\n"
    )
    assert parse_cross_check(cs) == {"C062C": 'Brake Booster Motor "B" Performance'}


def test_disagreements_ignore_case_quotes_and_punctuation() -> None:
    ours = {
        "C062C": "Brake Booster Motor B Performance",
        "C0559": "Power Steering Control Module Range/Performance - Rear",
        "C0071": "2/4 Wheel Drive Status Input",
    }
    theirs = {
        "C062C": 'brake booster motor "B" performance',
        "C0559": "Power Steering Control Module Range/Performance Rear",
        "C0071": "Something Else",
        "B0999": "x",
    }
    assert disagreements(ours, theirs) == {"C0071"}


@pytest.mark.parametrize(
    ("code", "description", "category", "subcategory"),
    [
        ("P0301", "Cylinder 1 Misfire Detected", "powertrain", "ignition"),
        ("P0A80", "Replace Hybrid/EV Battery Pack", "powertrain", None),
        ("P0800", "Transfer Case Control System (MIL Request)", "powertrain", None),
        ("P2096", "Post Catalyst Fuel Trim System Too Lean Bank 1", "powertrain", "fuel_system"),
        (
            "P2A00",
            "O2 Sensor Circuit Range/Performance Bank 1 Sensor 1",
            "powertrain",
            "oxygen_sensor",
        ),
        ("P2999", "CO2 Sensor Circuit", "powertrain", None),
        ("B0001", "Driver Frontal Stage 1 Deployment Control", "body", None),
        ("B0100", "Clock Spring Circuit", "body", None),
        ("B0200", "Driver Door Lock Switch", "body", "access"),
        ("C0040", "Brake Pedal Switch A", "chassis", "brakes"),
        ("U0100", "Lost Communication With ECM/PCM A", "network", None),
        ("U0073", "Control Module Communication Bus A Off", "network", "can_bus"),
    ],
)
def test_derive_category_and_subcategory(
    code: str, description: str, category: str, subcategory: str | None
) -> None:
    entry = derive(code, description)
    assert (entry["category"], entry["subcategory"]) == (category, subcategory)


@pytest.mark.parametrize(
    ("description", "severity", "level"),
    [
        ("Fuel Pump Module Failure", "critical", 4),
        ("Cylinder Deactivation Disabled", "critical", 4),
        ("Communication Fault - Forced Engine Shutdown", "critical", 4),
        # S1d-06: a shutdown CIRCUIT is a wire fault on the PTO's shutdown input,
        # not the engine shutting down (P251D/E/F).
        ("PTO Engine Shutdown Circuit/Open", "warning", 2),
        ("PTO Engine Shutdown Circuit Low", "warning", 2),
        ("PTO Engine Shutdown Circuit High", "warning", 2),
        ("Engine Shut Down Circuit Low", "warning", 2),
        # guards: a shutdown not followed by "Circuit" stays critical, spelled
        # either way (U3001 is a real one).
        ("Control Module Improper Shutdown Performance", "critical", 4),
        ("Engine Shut Down Request", "critical", 4),
        # A part named "Disable" is not a disabled system.
        ("Starter Disable Circuit/Open", "warning", 2),
        ("TCS Disable Switch", "warning", 2),
        ("Fuel Pump Circuit Malfunction", "warning", 3),
        ("Throttle Actuator Stuck Open", "warning", 3),
        ("Mass or Volume Air Flow Sensor A Circuit Intermittent", "info", 2),
        ("Catalyst System Efficiency Below Threshold Bank 1", "warning", 2),
    ],
)
def test_derive_severity(description: str, severity: str, level: int) -> None:
    entry = derive("P2000", description)
    assert (entry["severity"], entry["estimated_severity_level"]) == (severity, level)


@pytest.mark.parametrize(
    ("code", "description", "emissions"),
    [
        ("P0420", "Catalyst System Efficiency Below Threshold Bank 1", True),  # P04 block
        ("P2002", "Diesel Particulate Filter Efficiency Below Threshold Bank 1", True),
        ("P2000", "NOx Adsorber Efficiency Below Threshold Bank 1", True),
        ("P2BAD", "Reductant Pump Control Circuit", True),
        ("P2100", "Throttle Actuator Control Motor Circuit/Open", False),
        ("P2400", "EVAP System Leak Detection Pump Control Circuit/Open", True),
        ("P2401", "EGR B Control Circuit Low", True),
        ("U3005", "Integrated Control Module Circuit", False),
        ("B0400", "Evaporator Temperature Sensor Circuit", False),
        ("P2A00", "O2 Sensor Circuit Range/Performance Bank 1 Sensor 1", True),
    ],
)
def test_derive_emissions_matches_whole_words(code: str, description: str, emissions: bool) -> None:
    assert derive(code, description)["is_emissions_related"] is emissions


def test_render_is_one_entry_per_line_and_round_trips() -> None:
    entries = [
        derive("P0300", "Random/Multiple Cylinder Misfire Detected"),
        derive("U0100", "Lost Communication With ECM/PCM A"),
    ]
    text = render(entries)
    assert text.count("\n") == 4  # "[", two entries, "]", trailing newline
    assert json.loads(text) == entries


def test_a_pinned_file_with_the_wrong_hash_is_refused(tmp_path: Path) -> None:
    (tmp_path / "p_codes.txt").write_text("P0100 - Mass or Volume Air Flow Sensor A Circuit\n")
    for name in ("b_codes.txt", "c_codes.txt", "u_codes.txt"):
        (tmp_path / name).write_text("")
    (tmp_path / "DTC.cs").write_text("")
    assert main([str(tmp_path), str(tmp_path / "DTC.cs"), str(tmp_path / "out.json")]) != 0
    assert not (tmp_path / "out.json").exists()


@pytest.fixture
def tiny_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two-code inputs with the module's pins pointed at them."""
    import hashlib

    from tools import build_dtc_definitions as gen

    files = {
        "p_codes.txt": "P0300 - Random/Multiple Cylinder Misfire Detected\nP1000 - Maker Code\n",
        "b_codes.txt": "",
        "c_codes.txt": "",
        "u_codes.txt": "U0100 - Lost Communication With ECM/PCM A\n",
    }
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    cs = (
        '    [Category(Categories.Powertrain), Description("Random/Multiple Cylinder Misfire'
        ' Detected")]\n    P0300 = 0x0300,\n'
    )
    (tmp_path / "DTC.cs").write_text(cs, encoding="utf-8")

    def sha(name: str) -> str:
        return hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()

    monkeypatch.setattr(gen, "SOURCE_FILES", {name: sha(name) for name in files})
    monkeypatch.setattr(gen, "CROSS_CHECK_SHA256", sha("DTC.cs"))
    monkeypatch.setattr(gen, "CROSS_CHECK_KNOWN_DIFFS", frozenset[str]())
    monkeypatch.setattr(gen, "EXPECTED_CODES", 2)
    return tmp_path


def test_main_writes_the_sorted_generic_codes(tiny_inputs: Path) -> None:
    out = tiny_inputs / "out.json"
    assert main([str(tiny_inputs), str(tiny_inputs / "DTC.cs"), str(out)]) == 0
    assert [e["code"] for e in json.loads(out.read_text())] == ["P0300", "U0100"]


def test_main_refuses_an_unwritable_output(tiny_inputs: Path) -> None:
    """Codex R1-F2: a failed write is a refusal like any other, not a traceback."""
    assert main([str(tiny_inputs), str(tiny_inputs / "DTC.cs"), str(tiny_inputs)]) == 1


def test_a_changed_input_is_refused_on_its_hash_alone(
    tiny_inputs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An extra maker line changes nothing in the output, only the bytes."""
    with (tiny_inputs / "p_codes.txt").open("a", encoding="utf-8") as f:
        f.write("P1001 - Another Maker Code\n")
    out = tiny_inputs / "out.json"
    assert main([str(tiny_inputs), str(tiny_inputs / "DTC.cs"), str(out)]) == 1
    assert "p_codes.txt: sha256" in capsys.readouterr().err
    assert not out.exists()


def test_a_code_count_change_is_refused(
    tiny_inputs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools import build_dtc_definitions as gen

    monkeypatch.setattr(gen, "EXPECTED_CODES", 3)
    out = tiny_inputs / "out.json"
    assert main([str(tiny_inputs), str(tiny_inputs / "DTC.cs"), str(out)]) == 1
    assert "2 codes, expected 3" in capsys.readouterr().err
    assert not out.exists()


def test_a_known_difference_that_went_away_is_refused(
    tiny_inputs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The known set has to match exactly, both ways, so it can't go stale."""
    from tools import build_dtc_definitions as gen

    monkeypatch.setattr(gen, "CROSS_CHECK_KNOWN_DIFFS", frozenset({"U0100"}))
    out = tiny_inputs / "out.json"
    assert main([str(tiny_inputs), str(tiny_inputs / "DTC.cs"), str(out)]) == 1
    assert "cross-check changed: ['U0100']" in capsys.readouterr().err
    assert not out.exists()
