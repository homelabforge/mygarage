"""Route tests keep their rows off the shared test vehicle and clean up after themselves.

The suite shares one database. A row a test leaves on `test_vehicle` turns up
in every later test's latest reading and trend window, so these checks stop
the three ways that kept happening.
"""

import ast
import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
TESTS_DIR = BACKEND_DIR / "tests"
ROUTES_DIR = TESTS_DIR / "integration" / "routes"

#: test_vehicle's VIN. Only its own fixture and the DB-free unit tests may spell it.
SHARED_VIN = "1HGBH41JXMN109186"
#: Calls that stamp a row with the day the suite runs.
TODAY_CALLS = {
    ("datetime", "now"),
    ("datetime", "today"),
    ("datetime", "utcnow"),
    ("date", "today"),
}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _is_fixture(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any("fixture" in ast.unparse(d) for d in fn.decorator_list)


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def _rel(path: Path) -> str:
    return str(path.relative_to(BACKEND_DIR))


def _is_today(node: ast.AST, names: set[str]) -> bool:
    """True if this expression reads today's date, directly or through a local name."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in names:
            return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            owner = sub.func.value
            # `datetime.now()` and `dt.datetime.now()` both count.
            name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", None)
            if (name, sub.func.attr) in TODAY_CALLS:
                return True
    return False


def _dates_a_row_today(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A `"date": <today>` entry in any dict this function builds."""
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and _is_today(node.value, names):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return any(
        isinstance(key, ast.Constant) and key.value == "date" and _is_today(value, names)
        for node in ast.walk(fn)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values, strict=True)
    )


def test_no_route_module_shadows_own_vehicle() -> None:
    """The routes conftest's own_vehicle deletes what it made; a local copy forgot to."""
    shadows = [
        f"{_rel(path)}:{fn.lineno}"
        for path in sorted(ROUTES_DIR.rglob("*.py"))
        if path.name != "conftest.py"
        for fn in _functions(_parse(path))
        if fn.name == "own_vehicle" and _is_fixture(fn)
    ]
    assert shadows == [], "use the conftest own_vehicle (mark it for other fields)"


def test_only_its_fixture_spells_the_shared_vin() -> None:
    """A test that writes to the shared VIN by hand never cleans up what it adds."""
    pattern = re.compile(SHARED_VIN, re.IGNORECASE)
    unit_dir = TESTS_DIR / "unit"
    found = [
        _rel(path)
        for path in sorted(TESTS_DIR.rglob("*.py"))
        if path != TESTS_DIR / "conftest.py"
        and not path.is_relative_to(unit_dir)
        and pattern.search(path.read_text())
    ]
    assert found == [], "take the VIN from test_vehicle or own_vehicle"


def test_no_route_test_dates_a_shared_vehicle_row_today() -> None:
    """A row dated today on test_vehicle turns up in every later test's latest figures."""
    found = [
        f"{_rel(path)}::{fn.name}"
        for path in sorted(ROUTES_DIR.rglob("test_*.py"))
        for fn in _functions(_parse(path))
        if fn.name.startswith("test_")
        and "test_vehicle" in {a.arg for a in fn.args.args}
        and _dates_a_row_today(fn)
    ]
    assert found == [], "write today's rows on own_vehicle"
