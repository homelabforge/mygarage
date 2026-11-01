"""Tests keep their rows off the shared test vehicle and clean up after themselves.

The suite shares one database. A row a test leaves on `test_vehicle` turns up
in every later test's latest reading and trend window, so these checks stop
the three ways that kept happening.
"""

import ast
import re
from pathlib import Path

from sqlalchemy import Date, DateTime

BACKEND_DIR = Path(__file__).resolve().parents[2]
TESTS_DIR = BACKEND_DIR / "tests"

#: test_vehicle's VIN. Only its own fixture and the unit tests may spell it.
SHARED_VIN = "1HGBH41JXMN109186"
#: Calls that stamp a row with the day the suite runs.
TODAY_CALLS = {
    ("datetime", "now"),
    ("datetime", "today"),
    ("datetime", "utcnow"),
    ("date", "today"),
}
#: The app's own helpers for the same thing, called bare.
TODAY_FUNCS = {"household_today", "utc_now"}


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
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            if sub.func.id in TODAY_FUNCS:
                return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            owner = sub.func.value
            # `datetime.now()` and `dt.datetime.now()` both count.
            name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", None)
            if (name, sub.func.attr) in TODAY_CALLS:
                return True
    return False


def _bindings(node: ast.AST) -> list[tuple[ast.expr, ast.AST]]:
    """(target, value) for each way a statement or expression binds a local name."""
    if isinstance(node, ast.Assign):
        return [(target, node.value) for target in node.targets]
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        return [(node.target, node.value)]
    if isinstance(node, ast.NamedExpr):
        return [(node.target, node.value)]
    return []


def _today_names(fn: ast.AST) -> set[str]:
    """Local names holding today, followed through reassignments (`d = today`).

    Plain, annotated (`d: date = date.today()`) and walrus (`(d := date.today())`)
    bindings all count.
    """
    names: set[str] = set()
    while True:
        found = {
            target.id
            for node in ast.walk(fn)
            for target, value in _bindings(node)
            if isinstance(target, ast.Name) and _is_today(value, names)
        }
        if found <= names:
            return names
        names |= found


def _date_columns() -> frozenset[str]:
    """Every Date column name in the models: `date`, `due_date`, `end_date` and the rest."""
    import app.models  # noqa: F401  (registers every table on Base.metadata)
    from app.database import Base

    return frozenset(
        column.name
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Date) and not isinstance(column.type, DateTime)
    )


DATE_KEYS = _date_columns()


def _date_values(fn: ast.AST) -> list[ast.AST]:
    """Whatever a row's date columns are set to: `{"due_date": x}`, `Model(date=x)`
    or `row["end_date"] = x`, for every Date column in DATE_KEYS."""
    values: list[ast.AST] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            values += [
                value
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant) and key.value in DATE_KEYS
            ]
        elif isinstance(node, ast.Call):
            values += [kw.value for kw in node.keywords if kw.arg in DATE_KEYS]
        elif isinstance(node, ast.Assign):
            values += [
                node.value
                for target in node.targets
                if isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value in DATE_KEYS
            ]
    return values


def _dates_a_row_today(fn: ast.AST) -> bool:
    """A row with a date column reading today, in any of the forms `_date_values` knows."""
    names = _today_names(fn)
    return any(_is_today(value, names) for value in _date_values(fn))


def test_nothing_shadows_own_vehicle() -> None:
    """The tests conftest's own_vehicle deletes what it made; a local copy forgot to."""
    shadows = [
        f"{_rel(path)}:{fn.lineno}"
        for path in sorted(TESTS_DIR.rglob("*.py"))
        if path != TESTS_DIR / "conftest.py"
        for fn in _functions(_parse(path))
        if fn.name == "own_vehicle" and _is_fixture(fn)
    ]
    assert shadows == [], "use the conftest own_vehicle (mark it for other fields)"


#: How a test file gets at the shared database.
DB_HANDLES = re.compile(r"\b(db_session|test_sessionmaker|test_engine|get_db)\b")


def _vin_spellers(files: dict[str, str]) -> list[str]:
    """Files that spell the shared VIN and could write with it.

    A unit file that never touches the database may: there it's only a string
    on an object in memory. Anything that can reach the shared database can't.
    """
    pattern = re.compile(SHARED_VIN, re.IGNORECASE)
    return [
        name
        for name, text in files.items()
        if pattern.search(text)
        and not (name.startswith("tests/unit/") and not DB_HANDLES.search(text))
    ]


def test_only_its_fixture_spells_the_shared_vin() -> None:
    """A test that writes to the shared VIN by hand never cleans up what it adds."""
    files = {
        _rel(path): path.read_text()
        for path in sorted(TESTS_DIR.rglob("*.py"))
        if path not in {TESTS_DIR / "conftest.py", Path(__file__)}
    }
    assert _vin_spellers(files) == [], "take the VIN from test_vehicle or own_vehicle"


def test_a_unit_file_with_a_database_handle_cant_spell_the_shared_vin() -> None:
    vin = f'"{SHARED_VIN}"'
    files = {
        "tests/unit/test_pure.py": f"r = Reminder(vin={vin})\n",
        "tests/unit/test_writes.py": f"async def test_w(db_session):\n    add(Fuel(vin={vin}))\n",
        "tests/unit/test_engine.py": f"async def test_w(test_engine):\n    run({vin})\n",
        "tests/integration/test_any.py": f"r = Reminder(vin={vin})\n",
    }
    assert _vin_spellers(files) == [
        "tests/unit/test_writes.py",
        "tests/unit/test_engine.py",
        "tests/integration/test_any.py",
    ]


def _today_helpers(tree: ast.Module) -> set[str]:
    """This module's non-test functions that date a row today, followed through
    helpers that call them."""
    fns = [fn for fn in _functions(tree) if not fn.name.startswith("test_")]
    helpers = {fn.name for fn in fns if _dates_a_row_today(fn)}
    while True:
        found = {fn.name for fn in fns if _calls_any(fn, helpers)}
        if found <= helpers:
            return helpers
        helpers |= found


def _calls_any(fn: ast.AST, names: set[str]) -> bool:
    """A call to one of `names`, bare (`_reminder(...)`) or as a method (`self._smart(...)`)."""
    return any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in names)
            or (isinstance(node.func, ast.Attribute) and node.func.attr in names)
        )
        for node in ast.walk(fn)
    )


def _shared_vehicle_today_writers(tree: ast.Module) -> list[str]:
    """Tests taking test_vehicle that date a row today, themselves or through a helper."""
    helpers = _today_helpers(tree)
    return [
        fn.name
        for fn in _functions(tree)
        if fn.name.startswith("test_")
        and "test_vehicle" in {a.arg for a in fn.args.args}
        and (_dates_a_row_today(fn) or _calls_any(fn, helpers))
    ]


def test_no_test_dates_a_shared_vehicle_row_today() -> None:
    """A row dated today on test_vehicle turns up in every later test's latest figures."""
    found = [
        f"{_rel(path)}::{name}"
        for path in _today_scan_files()
        for name in _shared_vehicle_today_writers(_parse(path))
    ]
    assert found == [], "write today's rows on own_vehicle"


def _today_scan_files() -> list[Path]:
    return sorted(TESTS_DIR.rglob("test_*.py"))


def test_the_today_check_reads_every_test_file() -> None:
    """It once read only the route tests, and the leaks it missed sat elsewhere."""
    scanned = set(_today_scan_files())
    assert {
        TESTS_DIR / "unit" / "services" / "test_hours_service.py",
        TESTS_DIR / "integration" / "test_reminder_notified_at_naive.py",
        TESTS_DIR / "test_analytics_routes.py",
    } <= scanned


# Every form the today check has to see through, each as a test that writes a
# today-dated row on test_vehicle.
TODAY_WRITERS = {
    "date call": "def test_w(test_vehicle):\n    add(Fuel(date=date.today()))\n",
    "datetime call": "def test_w(test_vehicle):\n    add(Fuel(date=datetime.now().date()))\n",
    "app helper": "def test_w(test_vehicle):\n    add(Fuel(date=household_today()))\n",
    "utc_now": "def test_w(test_vehicle):\n    add(Fuel(date=utc_now().date()))\n",
    "plain name": "def test_w(test_vehicle):\n    d = date.today()\n    add(Fuel(date=d))\n",
    "annotated name": (
        "def test_w(test_vehicle):\n    d: date = date.today()\n    add(Fuel(date=d))\n"
    ),
    "walrus name": (
        "def test_w(test_vehicle):\n"
        "    if (d := date.today()):\n"
        "        pass\n"
        "    add(Fuel(date=d))\n"
    ),
    "renamed name": (
        "def test_w(test_vehicle):\n    d = date.today()\n    e = d\n    add(Fuel(date=e))\n"
    ),
    "due_date key": (
        "def test_w(test_vehicle):\n    add(Reminder(due_date=date.today() + timedelta(days=3)))\n"
    ),
    "end_date in a dict": (
        "def test_w(test_vehicle):\n    post({'end_date': date.today().isoformat()})\n"
    ),
    "subscript": "def test_w(test_vehicle):\n    row['date'] = date.today()\n",
    "helper": (
        "async def _remind(vin):\n    add(Reminder(vin=vin, due_date=household_today()))\n"
        "async def test_w(test_vehicle):\n    await _remind(test_vehicle['vin'])\n"
    ),
    "helper of a helper": (
        "async def _remind(vin):\n    add(Reminder(vin=vin, due_date=household_today()))\n"
        "async def _smart(vin):\n    return await _remind(vin)\n"
        "async def test_w(test_vehicle):\n    await _smart(test_vehicle['vin'])\n"
    ),
    "method helper": (
        "class T:\n"
        "    async def _remind(self, vin):\n"
        "        add(Reminder(vin=vin, due_date=date.today()))\n"
        "    async def test_w(self, test_vehicle):\n"
        "        await self._remind(test_vehicle['vin'])\n"
    ),
}

# And what it must leave alone.
NOT_TODAY_WRITERS = {
    "own vehicle": "def test_w(own_vehicle):\n    add(Fuel(date=date.today()))\n",
    "fixed date": "def test_w(test_vehicle):\n    add(Fuel(date=date(2024, 3, 1)))\n",
    "today in a query, not a row": (
        "def test_w(test_vehicle):\n    get(params={'start': date.today().isoformat()})\n"
    ),
    "helper never called": (
        "async def _remind(vin):\n    add(Reminder(vin=vin, due_date=date.today()))\n"
        "async def test_w(test_vehicle):\n    pass\n"
    ),
}


def test_the_today_check_sees_every_form() -> None:
    missed = [
        form
        for form, source in TODAY_WRITERS.items()
        if _shared_vehicle_today_writers(ast.parse(source)) != ["test_w"]
    ]
    assert missed == []


def test_the_today_check_leaves_the_rest_alone() -> None:
    flagged = [
        form
        for form, source in NOT_TODAY_WRITERS.items()
        if _shared_vehicle_today_writers(ast.parse(source))
    ]
    assert flagged == []


def test_the_date_keys_come_from_the_models() -> None:
    """A Date column added later is checked without touching this file."""
    assert {"date", "due_date", "end_date", "start_date", "performed_on"} <= DATE_KEYS
    assert "created_at" not in DATE_KEYS  # a DateTime, not a day
