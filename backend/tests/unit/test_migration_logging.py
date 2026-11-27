"""Migrations from 124 on log through `logging`, not `print`.

print() goes to stdout with no level or logger name, so it skips the app's log
config. The older printers are pinned by name below; that list only shrinks.
"""

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "app" / "migrations"

#: First migration the rule covers.
FIRST_COVERED = 124

#: Migrations at or past FIRST_COVERED that already printed when the rule landed.
#: Convert one and drop it from here; never add to it.
PRINT_ALLOWLIST = frozenset(
    {
        "133_record_wican_legacy_odometer_unit.py",
        "143_add_country_fields.py",
        "144_add_fuel_grade.py",
        "145_add_rule_lead_days.py",
        "146_tax_type_codes.py",
        "147_add_vehicle_eu_fields.py",
        "149_insurance_eu_policy_types.py",
        "150_add_vehicle_identifier.py",
        "151_add_fuel_octane_scale.py",
        "156_add_date_format.py",
        "157_add_visit_reference_numbers.py",
    }
)

_MIGRATION_NAME = re.compile(r"^(\d{3})_\w+\.py$")


def _covered_migrations() -> list[Path]:
    """Every NNN_*.py migration numbered FIRST_COVERED or later."""
    found = []
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        match = _MIGRATION_NAME.match(path.name)
        if match and int(match.group(1)) >= FIRST_COVERED:
            found.append(path)
    return found


def _print_lines(path: Path) -> list[int]:
    """Line numbers of every bare print(...) call in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    )


def test_the_scan_sees_the_covered_migrations() -> None:
    """A glob that matched nothing would pass the real check for free."""
    names = {p.name for p in _covered_migrations()}
    assert "124_supply_volume_unit.py" in names
    assert "165_categorize_percentage_parameters.py" in names


def test_covered_migrations_do_not_print() -> None:
    """Nothing outside the allowlist calls print()."""
    offenders = {
        path.name: lines
        for path in _covered_migrations()
        if path.name not in PRINT_ALLOWLIST and (lines := _print_lines(path))
    }
    assert offenders == {}, f"use logger.info, not print: {offenders}"


def test_the_allowlist_has_no_stale_entries() -> None:
    """Each allowlisted file exists and still prints, so the list can only shrink."""
    by_name = {p.name: p for p in _covered_migrations()}
    missing = sorted(PRINT_ALLOWLIST - by_name.keys())
    assert missing == [], f"allowlisted migrations not found: {missing}"
    clean = sorted(name for name in PRINT_ALLOWLIST if not _print_lines(by_name[name]))
    assert clean == [], f"these no longer print; drop them from PRINT_ALLOWLIST: {clean}"
