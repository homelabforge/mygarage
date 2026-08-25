"""Structural guard: gallon flavour must never become ambient again.

Phase 0 removed process-global mutable gallon state. Per-user volume units
(phase 1) make its return a correctness bug rather than a style problem: one
request's flavour would leak into another's concurrent conversion. Coverage
cannot see this, so it is asserted structurally.
"""

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[3] / "app"

FORBIDDEN_NAMES = {
    "set_gallon_standard",
    "get_gallon_standard",
    "GALLONS_TO_LITERS",
    "MPG_TO_L100KM_NUMERATOR",
}

# Migrations are frozen historical records and may legitimately embed a literal
# factor for the data they transformed. 053 does exactly that.
EXEMPT_DIRS = {"migrations"}


def _python_sources() -> list[Path]:
    return [
        path
        for path in APP_ROOT.rglob("*.py")
        if not EXEMPT_DIRS & set(path.relative_to(APP_ROOT).parts)
    ]


# If a future refactor breaks APP_ROOT's path resolution, _python_sources()
# silently returns [], pytest.mark.parametrize collects zero cases, and this
# whole module reports a single SKIPPED test -- CI stays green while the guard
# scans nothing. Assert a plausible lower bound at collection time so that
# failure is loud instead. 277 files existed under app/ (excluding
# migrations/) at the time of writing; 100 is comfortably below any real count
# (which only grows as the app does) and comfortably above zero, so this trips
# the moment resolution breaks without being pinned to the exact file count.
_MIN_PLAUSIBLE_SOURCE_COUNT = 100
_SOURCES = _python_sources()
assert len(_SOURCES) >= _MIN_PLAUSIBLE_SOURCE_COUNT, (
    f"_python_sources() found only {len(_SOURCES)} file(s) under {APP_ROOT} "
    f"(expected at least {_MIN_PLAUSIBLE_SOURCE_COUNT}). APP_ROOT resolution is "
    "probably broken, which would make this guard silently scan nothing and "
    "report a single SKIPPED test instead of failing."
)


@pytest.mark.parametrize("path", _SOURCES, ids=lambda p: str(p.name))
def test_no_ambient_gallon_identifier(path: Path) -> None:
    """No module may reference the deleted ambient accessors or aliases.

    US_GALLONS_TO_LITERS and UK_GALLONS_TO_LITERS are explicit and allowed; the
    bare aliases are not, because they were the mutable ones.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            offenders.append(f"{path.name}:{node.lineno} .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            offenders.append(f"{path.name}:{node.lineno} {node.id}")
    assert not offenders, (
        "ambient gallon state reintroduced: "
        + ", ".join(offenders)
        + ". Pass flavour explicitly instead (see app/utils/gallon_flavour.py)."
    )
