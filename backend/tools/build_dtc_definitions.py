"""Build app/data/dtc_definitions.json from pinned upstream DTC lists.

Codes and descriptions: the SAE-controlled (generic) ranges of
Wal33D/dtc-database (MIT) at SOURCE_SHA. Cross-check: lennykean/OBDII.DTC
(MIT) at CROSS_CHECK_SHA, the older copy of the same list, has to agree on
every code both carry except CROSS_CHECK_KNOWN_DIFFS. Maker ranges are left
out on purpose: one maker's meaning shown for another maker's car is worse
than none.

The derived fields follow the first data set's rules (category from the
letter, P0 subcategory from the third character, the rest from words in the
description), matched on whole words now so "Integrated" isn't EGR.

Run from backend/ with the pinned files downloaded (plan 1d, Task 1):
    python -m tools.build_dtc_definitions SOURCE_DIR CROSS_CHECK_DTC_CS OUT_JSON
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import TypedDict

SOURCE_SHA = "04c43d72e7db7197658b6f72fe582c5076d9eee8"
SOURCE_FILES: dict[str, str] = {
    "p_codes.txt": "1e51ce1f30da167e8bd44066fbdc26b516742c7cdec4f2e8948ae6b4fdb45aa2",
    "b_codes.txt": "bd72c03dfff40a042d368fe6243070f1f7a14f4d7c718c6d889b3d9c1f669715",
    "c_codes.txt": "e831ef7b16cbaf0cb27a779cdf5b64c34643ae68e82e4df38c292aa7da5b7853",
    "u_codes.txt": "07f4b56500ec2038b9b06b4033af300c9a5450d95ff05eb01de36734ed13faae",
}
CROSS_CHECK_SHA = "bdd618ea487e9e85c7f3b4d142ce783337752f3b"
CROSS_CHECK_SHA256 = "93ecf019cce8bcc419e662dfe62de54988774a980bd644420eda09985e66c3c0"
#: Codes where the two lists still disagree after normalising; ours is kept.
CROSS_CHECK_KNOWN_DIFFS: frozenset[str] = frozenset({"C0071"})
#: 9,343 SAE-range lines at SOURCE_SHA, less one duplicate (P3400's stray
#: "P34C8" line) and one placeholder (B3000-B3999 ISO/SAE Reserved).
EXPECTED_CODES = 9341

_CODE = re.compile(r"[PBCU][0-9A-F]{4}")
_PLACEHOLDER = re.compile(r"\breserved\b|manufacturer controlled", re.IGNORECASE)
_CS_ENTRY = re.compile(r'Description\("((?:[^"\\]|\\.)*)"\)\]\s*\n\s*([PBCU][0-9A-F]{4}) = ')


class DTCEntry(TypedDict):
    """One row of dtc_definitions.json: exactly the keys migration 033 reads."""

    code: str
    description: str
    category: str
    subcategory: str | None
    severity: str
    estimated_severity_level: int
    is_emissions_related: bool


def _words(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


CATEGORY = {"P": "powertrain", "B": "body", "C": "chassis", "U": "network"}
P0_BLOCKS = {
    "1": "fuel_air_metering",
    "2": "fuel_injection",
    "3": "ignition",
    "4": "emissions",
    "5": "vehicle_speed",
    "6": "computer",
    "7": "transmission",
}
SUBCATEGORY_RULES: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    "P": (
        ("oxygen_sensor", _words("O2", "HO2S", "oxygen")),
        ("ignition", _words("misfire")),
        ("fuel_system", _words("fuel")),
        ("cooling", _words("temperature", "coolant")),
        ("emissions", _words("EVAP", "evaporative", "catalyst", "emissions?")),
        ("transmission", _words("transmission", "gears?")),
    ),
    "B": (
        ("airbag", _words("airbags?")),
        ("safety", _words("seats?")),
        ("climate", _words("climate", "heater", "A/C")),
        ("access", _words("doors?", "windows?", "locks?")),
        ("lighting", _words("lamps?", "lights?", "bulbs?")),
    ),
    "C": (
        ("brakes", _words("ABS", "brakes?")),
        ("steering", _words("steering")),
        ("suspension", _words("suspension", "shocks?")),
        ("traction_control", _words("traction", "stability")),
    ),
    "U": (("can_bus", re.compile(r"\bbus\b|\(CAN\)", re.IGNORECASE)),),
}
SEVERITY_RULES: tuple[tuple[str, int, re.Pattern[str]], ...] = (
    # "Disabled", not "Disable": "Starter Disable Circuit" names a part.
    ("critical", 4, re.compile(r"\bfailure\b|\bdisabled\b|\bshut\s?down\b", re.IGNORECASE)),
    ("warning", 3, _words("malfunction", "fault", "faulty", "stuck", "problem")),
    ("info", 2, _words("intermittent")),
)
DEFAULT_SEVERITY = ("warning", 2)
EMISSIONS_WORDS = _words(
    "O2",
    "HO2S",
    "EGR",
    "catalyst",
    "EVAP",
    "evaporative",
    "exhaust",
    "particulate",
    "NOx",
    "reductant",
)


def is_sae_range(code: str) -> bool:
    """The SAE-controlled ranges: P0, P2, P34-P39, B0, B3, C0, C3, U0, U3."""
    letter, first = code[0], code[1]
    if letter == "P":
        return first in "02" or (first == "3" and code[2] in "456789")
    return first in "03"


def normalize_description(text: str) -> str:
    """Single-spaced ASCII: the stray curly quotes go, an en dash becomes a hyphen."""
    text = text.replace("\u201c", "").replace("\u201d", "").replace("\u2013", "-")
    text = " ".join(text.split())
    if not text.isascii():
        raise ValueError(f"non-ASCII description: {text!r}")
    return text


def parse_source(text: str) -> dict[str, str]:
    """SAE-range codes from one `CODE - Description` file, first real description each.

    Splits on the FIRST " - ": descriptions contain it too. A description that
    is itself a code (P3400's stray "P34C8" line) or a placeholder is skipped,
    so the next line for that code wins.
    """
    codes: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        code, sep, raw = line.partition(" - ")
        code = code.strip()
        if not sep or not _CODE.fullmatch(code):
            raise ValueError(f"unparseable line: {line!r}")
        if not is_sae_range(code) or code in codes:
            continue
        description = normalize_description(raw)
        if not description or _CODE.fullmatch(description) or _PLACEHOLDER.search(description):
            continue
        codes[code] = description
    return codes


def parse_cross_check(text: str) -> dict[str, str]:
    """SAE-range codes and descriptions from lennykean's DTC.cs enum."""
    codes: dict[str, str] = {}
    for raw, code in _CS_ENTRY.findall(text):
        if is_sae_range(code):
            codes[code] = normalize_description(raw.replace('\\"', '"'))
    return codes


def _compare_key(text: str) -> str:
    # Words only: the two lists differ in punctuation (C0559 "- Rear" vs
    # "Rear", quote styles) and that isn't a disagreement about the meaning.
    return " ".join(re.findall(r"[0-9a-z]+", text.casefold()))


def disagreements(ours: dict[str, str], theirs: dict[str, str]) -> set[str]:
    """Codes both lists carry with different words, ignoring case and punctuation."""
    return {
        c for c in ours.keys() & theirs.keys() if _compare_key(ours[c]) != _compare_key(theirs[c])
    }


def derive(code: str, description: str) -> DTCEntry:
    """The row for one code, with the derived fields."""
    letter = code[0]
    if code.startswith("P0"):
        subcategory = P0_BLOCKS.get(code[2])
    else:
        subcategory = next(
            (name for name, rule in SUBCATEGORY_RULES[letter] if rule.search(description)), None
        )
    severity, level = next(
        ((s, lv) for s, lv, rule in SEVERITY_RULES if rule.search(description)), DEFAULT_SEVERITY
    )
    return DTCEntry(
        code=code,
        description=description,
        category=CATEGORY[letter],
        subcategory=subcategory,
        severity=severity,
        estimated_severity_level=level,
        is_emissions_related=subcategory == "emissions"
        or bool(EMISSIONS_WORDS.search(description)),
    )


def render(entries: list[DTCEntry]) -> str:
    """A JSON array, one entry per line, so a diff reads per code."""
    lines = [json.dumps(e, ensure_ascii=True) for e in entries]
    return "[\n" + ",\n".join(lines) + "\n]\n"


def _read_pinned(path: Path, sha256: str) -> str:
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != sha256:
        raise ValueError(f"{path.name}: sha256 {actual}, expected {sha256}")
    return data.decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    """Build the file; non-zero and nothing written on any refusal."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        sys.stderr.write(__doc__ or "")
        return 64
    source_dir, cross_check_path, out = (Path(a) for a in args)
    try:
        codes: dict[str, str] = {}
        for name, sha in SOURCE_FILES.items():
            codes.update(parse_source(_read_pinned(source_dir / name, sha)))
        if len(codes) != EXPECTED_CODES:
            raise ValueError(f"{len(codes)} codes, expected {EXPECTED_CODES}")
        theirs = parse_cross_check(_read_pinned(cross_check_path, CROSS_CHECK_SHA256))
        diffs = disagreements(codes, theirs)
        if frozenset(diffs) != CROSS_CHECK_KNOWN_DIFFS:
            raise ValueError(f"cross-check changed: {sorted(diffs ^ CROSS_CHECK_KNOWN_DIFFS)}")
        entries = [derive(c, codes[c]) for c in sorted(codes)]
        out.write_text(render(entries), encoding="utf-8")
    except (OSError, ValueError) as e:
        sys.stderr.write(f"refused: {e}\n")
        return 1
    sys.stdout.write(f"wrote {len(entries)} codes to {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
