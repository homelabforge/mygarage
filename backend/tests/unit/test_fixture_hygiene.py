"""Tests keep their rows off the shared test vehicle and clean up after themselves.

The suite shares one database. A row a test leaves on `test_vehicle` turns up
in every later test's latest reading and trend window, so these checks stop
the three ways that kept happening.
"""

import ast
import re
from collections.abc import Set
from dataclasses import dataclass
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


def _getfixturevalue_calls(node: ast.AST) -> list[ast.Call]:
    return [
        sub
        for sub in ast.walk(node)
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == "getfixturevalue"
    ]


def _fixturevalue_name(node: ast.AST) -> str | None:
    """The fixture a `getfixturevalue("name")` call asks for, if it's that call with a literal."""
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "getfixturevalue"
    ):
        return None
    arg = (
        node.args[0]
        if node.args
        else next((kw.value for kw in node.keywords if kw.arg == "argname"), None)
    )
    return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None


def _is_today(node: ast.AST, names: Set[str]) -> bool:
    """True if this expression reads today's date, directly or through a local name."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in names:
            return True
        # `request.getfixturevalue("x")` holds what a parameter `x` would.
        if (literal := _fixturevalue_name(sub)) is not None and literal in names:
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


def _today_names(fn: ast.AST, seed: Set[str] = frozenset()) -> set[str]:
    """Local names holding today, followed through reassignments (`d = today`).

    Plain, annotated (`d: date = date.today()`) and walrus (`(d := date.today())`)
    bindings all count. `seed` names hold today from the start, like a parameter
    filled by a fixture whose value is today.
    """
    names: set[str] = set(seed)
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


def _dates_a_row_today(fn: ast.AST, seed: Set[str] = frozenset()) -> bool:
    """A row with a date column reading today, in any of the forms `_date_values` knows."""
    names = _today_names(fn, seed)
    return any(_is_today(value, names) for value in _date_values(fn))


def _returns_today(fn: ast.AST, seed: Set[str] = frozenset()) -> bool:
    """A function whose returned or yielded value is today: `return date.today()`.

    A container that holds today (a payload) isn't a date itself;
    `_dates_a_row_today` sees those as rows.
    """
    names = _today_names(fn, seed)
    return any(
        isinstance(node, ast.Return | ast.Yield)
        and node.value is not None
        and not isinstance(node.value, ast.Dict | ast.List | ast.Tuple | ast.Set)
        and _is_today(node.value, names)
        for node in ast.walk(fn)
    )


def _wiped_tables() -> tuple[frozenset[str], frozenset[str]]:
    """Model and table names no test may empty: the leak guard's tables, and vehicles.

    Read off FAR_FUTURE_GUARDED itself, so a table the guard gains is covered here too.
    """
    from app.models.vehicle import Vehicle
    from tests.conftest import FAR_FUTURE_GUARDED

    models = [model for model, _ in FAR_FUTURE_GUARDED] + [Vehicle]
    return frozenset(m.__name__ for m in models), frozenset(m.__tablename__ for m in models)


#: Calls that narrow a delete to some rows.
FILTERS = {"where", "filter", "filter_by"}
RAW_DELETE = re.compile(r"\bDELETE\s+FROM\s+(\w+)([^;]*)", re.IGNORECASE)


def _table_wide_deletes(tree: ast.Module, models: Set[str], tables: Set[str]) -> list[int]:
    """Lines that empty a guarded table: `delete(Model)`, `sa.delete(Model)` or
    `Model.__table__.delete()` never narrowed by `.where`, or a raw `DELETE FROM
    table` with no WHERE. An ORM `session.delete(obj)` deletes one row and isn't one."""
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def narrowed(call: ast.Call) -> bool:
        parent = parents.get(call)
        return isinstance(parent, ast.Attribute) and parent.attr in FILTERS

    def deletes_a_whole_model(call: ast.Call) -> bool:
        func = call.func
        if (
            isinstance(func, ast.Name | ast.Attribute)
            and (func.id if isinstance(func, ast.Name) else func.attr) == "delete"
        ):
            # delete(Model) or sa.delete(Model)
            if call.args and isinstance(call.args[0], ast.Name) and call.args[0].id in models:
                return True
            # Model.__table__.delete()
            owner = func.value if isinstance(func, ast.Attribute) else None
            return (
                isinstance(owner, ast.Attribute)
                and owner.attr == "__table__"
                and isinstance(owner.value, ast.Name)
                and owner.value.id in models
            )
        return False

    lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and deletes_a_whole_model(node) and not narrowed(node)
    ]
    lines += [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and any(
            match.group(1).lower() in tables and not re.search(r"\bWHERE\b", match.group(2), re.I)
            for match in RAW_DELETE.finditer(node.value)
        )
    ]
    return sorted(lines)


def test_no_test_empties_a_guarded_table() -> None:
    """Emptying a guarded table deletes other tests' leaks along with your own, so
    the far-future guard never sees them (a warranty wipe hid a leak until CI
    sharded the suite). Delete your own rows, by VIN or by id."""
    models, tables = _wiped_tables()
    found = [
        f"{_rel(path)}:{line}"
        for path in sorted(TESTS_DIR.rglob("*.py"))
        if path != Path(__file__)
        for line in _table_wide_deletes(_parse(path), models, tables)
    ]
    assert found == []


def test_the_wipe_check_covers_the_guarded_tables_and_vehicles() -> None:
    models, tables = _wiped_tables()
    assert {"WarrantyRecord", "Reminder", "FuelRecord", "Vehicle"} <= models
    assert {"warranty_records", "vehicle_reminders", "fuel_records", "vehicles"} <= tables


WIPES = {
    "delete(Model)": "await db.execute(delete(WarrantyRecord))\n",
    "sa.delete(Model)": "await db.execute(sa.delete(Reminder))\n",
    "delete(Vehicle)": "await db.execute(delete(Vehicle))\n",
    "__table__.delete()": "await db.execute(FuelRecord.__table__.delete())\n",
    "raw DELETE FROM": "await db.execute(text('DELETE FROM warranty_records'))\n",
    "raw lowercase": "await db.execute(text('delete from vehicles'))\n",
}
NOT_WIPES = {
    "narrowed delete": "await db.execute(delete(WarrantyRecord).where(WarrantyRecord.vin == v))\n",
    "narrowed __table__": "await db.execute(FuelRecord.__table__.delete().where(c))\n",
    "unguarded table": "await db.execute(delete(InsurancePolicy))\n",
    "one ORM row": "await db.delete(vehicle)\n",
    "raw with WHERE": "await db.execute(text('DELETE FROM vehicles WHERE vin = :vin'))\n",
    "raw unguarded": "await db.execute(text('DELETE FROM settings'))\n",
}


def test_the_wipe_check_sees_every_form_and_nothing_else() -> None:
    models, tables = _wiped_tables()
    missed = [
        form
        for form, src in WIPES.items()
        if _table_wide_deletes(ast.parse(src), models, tables) != [1]
    ]
    flagged = [
        form
        for form, src in NOT_WIPES.items()
        if _table_wide_deletes(ast.parse(src), models, tables)
    ]
    assert (missed, flagged) == ([], [])


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
#: Fixtures that reach it through the API. Matched as parameters, not words:
#: plenty of tests say "client" in prose.
API_HANDLES = {"client"}


def _reaches_the_database(text: str) -> bool:
    """A database handle anywhere in the file, or a test that takes the API client."""
    if DB_HANDLES.search(text):
        return True
    return any(arg.arg in API_HANDLES for fn in _functions(ast.parse(text)) for arg in fn.args.args)


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
        and not (name.startswith("tests/unit/") and not _reaches_the_database(text))
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
        "tests/unit/test_api.py": f"async def test_w(client):\n    await client.post(json={{'vin': {vin}}})\n",
        "tests/unit/test_prose.py": f"# the client never sees this\nr = Reminder(vin={vin})\n",
        "tests/integration/test_any.py": f"r = Reminder(vin={vin})\n",
    }
    assert _vin_spellers(files) == [
        "tests/unit/test_writes.py",
        "tests/unit/test_engine.py",
        "tests/unit/test_api.py",
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


Fn = ast.FunctionDef | ast.AsyncFunctionDef


def _fixture_name(fn: Fn) -> str:
    """The name a test asks for: `@pytest.fixture(name="x")` wins over the function's."""
    for decorator in fn.decorator_list:
        if isinstance(decorator, ast.Call) and "fixture" in ast.unparse(decorator.func):
            for keyword in decorator.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
    return fn.name


def _params(fn: Fn) -> set[str]:
    """The fixtures a test or fixture takes: its parameters, and every
    `request.getfixturevalue("name")` it makes with a literal name."""
    named = {a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]}
    return named | {
        name
        for call in _getfixturevalue_calls(fn)
        if (name := _fixturevalue_name(call)) is not None
    }


def _asks_for_an_unnamed_fixture(fn: Fn) -> bool:
    """A `getfixturevalue` whose name the guard can't read: a variable or an f-string."""
    return any(_fixturevalue_name(call) is None for call in _getfixturevalue_calls(fn))


#: What the guard says when it can't tell which fixture a writer takes.
UNNAMED_FIXTURE = "getfixturevalue with a non-literal name: use a literal, or own_vehicle"


@dataclass(frozen=True)
class TodaySources:
    """Fixtures that hand a test today: as a value (`date.today()`), or as a row
    already dated today (a payload with today's date)."""

    values: frozenset[str]
    rows: frozenset[str]


NO_SOURCES = TodaySources(frozenset(), frozenset())


def _today_sources(fixtures: list[Fn], known: TodaySources = NO_SOURCES) -> TodaySources:
    """Which fixtures hand out today, followed through fixtures built on fixtures.
    `known` are sources already found, like the conftests' for a module."""
    values: set[str] = set(known.values)
    rows: set[str] = set(known.rows)
    while True:
        new_values = {
            _fixture_name(fn) for fn in fixtures if _returns_today(fn, _params(fn) & values)
        }
        new_rows = {
            _fixture_name(fn)
            for fn in fixtures
            if _dates_a_row_today(fn, _params(fn) & values) or _params(fn) & rows
        }
        if new_values <= values and new_rows <= rows:
            return TodaySources(frozenset(values), frozenset(rows))
        values |= new_values
        rows |= new_rows


def _fixtures(tree: ast.Module) -> list[Fn]:
    return [fn for fn in _functions(tree) if _is_fixture(fn)]


def _conftest_sources() -> TodaySources:
    """Every conftest's today sources, which any test below it can take. A conftest
    fixture can't take a test module's, so these settle on their own."""
    return _today_sources(
        [fn for path in sorted(TESTS_DIR.rglob("conftest.py")) for fn in _fixtures(_parse(path))]
    )


def _shared_vehicle_today_writers(tree: ast.Module, known: TodaySources = NO_SOURCES) -> list[str]:
    """Tests, and fixtures, that take test_vehicle and date a row today: themselves,
    through a helper, or with a fixture that hands them today."""
    helpers = _today_helpers(tree)
    sources = _today_sources(_fixtures(tree), known)
    found = []
    for fn in _functions(tree):
        is_fixture = _is_fixture(fn)
        params = _params(fn)
        if not (fn.name.startswith("test_") or is_fixture) or "test_vehicle" not in params:
            continue
        name = _fixture_name(fn) if is_fixture else fn.name
        if _asks_for_an_unnamed_fixture(fn):
            # It writes on test_vehicle with a fixture nobody can name, so it can't be cleared.
            found.append(f"{name} ({UNNAMED_FIXTURE})")
        elif (
            _dates_a_row_today(fn, params & sources.values)
            or _calls_any(fn, helpers)
            or params & sources.rows
        ):
            found.append(name)
    return found


def test_no_test_dates_a_shared_vehicle_row_today() -> None:
    """A row dated today on test_vehicle turns up in every later test's latest figures."""
    conftest_sources = _conftest_sources()
    found = [
        f"{_rel(path)}::{name}"
        for path in _today_scan_files()
        for name in _shared_vehicle_today_writers(_parse(path), conftest_sources)
    ]
    assert found == [], "write today's rows on own_vehicle"


def _today_scan_files() -> list[Path]:
    """Every test module, and every conftest, whose fixtures can write rows too."""
    return sorted([*TESTS_DIR.rglob("test_*.py"), *TESTS_DIR.rglob("conftest.py")])


def test_the_today_check_reads_every_test_file() -> None:
    """It once read only the route tests, and the leaks it missed sat elsewhere."""
    scanned = set(_today_scan_files())
    assert {
        TESTS_DIR / "unit" / "services" / "test_hours_service.py",
        TESTS_DIR / "integration" / "test_reminder_notified_at_naive.py",
        TESTS_DIR / "test_analytics_routes.py",
        # Fixtures write rows too, and the conftests hold most of them.
        TESTS_DIR / "integration" / "conftest.py",
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
    "module fixture": (
        "@pytest.fixture\n"
        "def payload():\n    return {'date': date.today().isoformat()}\n"
        "async def test_w(test_vehicle, payload):\n    post(json=payload)\n"
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


def test_the_today_check_sees_a_conftest_fixtures_today() -> None:
    """A payload fixture in a conftest hands its today to every test that takes it."""
    conftest = _fixtures(
        ast.parse(
            "@pytest.fixture\ndef sample_payload():\n"
            "    return {'date': datetime.now().date().isoformat()}\n"
            "@pytest.fixture\ndef fixed_payload():\n    return {'date': '2024-05-15'}\n"
        )
    )
    sources = _today_sources(conftest)
    assert sources == TodaySources(frozenset(), frozenset({"sample_payload"}))
    tests = ast.parse(
        "async def test_today(test_vehicle, sample_payload):\n    post(json=sample_payload)\n"
        "async def test_fixed(test_vehicle, fixed_payload):\n    post(json=fixed_payload)\n"
        "async def test_own(own_vehicle, sample_payload):\n    post(json=sample_payload)\n"
    )
    assert _shared_vehicle_today_writers(tests, sources) == ["test_today"]


# The fixture shapes the check follows (R5). Each source has one writer, `test_w`
# or a fixture named `writer`, and nothing else it should flag.
FIXTURE_SHAPES = {
    "registered name": (
        "@pytest.fixture(name='payload')\n"
        "def _payload_fixture():\n    return {'date': date.today().isoformat()}\n"
        "async def test_w(test_vehicle, payload):\n    post(json=payload)\n"
    ),
    "bare today value": (
        "@pytest.fixture\ndef today():\n    return date.today()\n"
        "async def test_w(test_vehicle, today):\n    add(Fuel(date=today))\n"
    ),
    "bare datetime value": (
        "@pytest.fixture\ndef now():\n    return datetime.now()\n"
        "async def test_w(test_vehicle, now):\n    add(Fuel(date=now.date()))\n"
    ),
    "app helper value, yielded": (
        "@pytest.fixture\ndef today():\n    yield household_today()\n"
        "async def test_w(test_vehicle, today):\n    add(Reminder(due_date=today))\n"
    ),
    "value built on a value": (
        "@pytest.fixture\ndef today():\n    return date.today()\n"
        "@pytest.fixture\ndef soon(today):\n    return today + timedelta(days=3)\n"
        "async def test_w(test_vehicle, soon):\n    add(Reminder(due_date=soon))\n"
    ),
    "payload built on a value": (
        "@pytest.fixture\ndef today():\n    return date.today()\n"
        "@pytest.fixture\ndef payload(today):\n    return {'date': today.isoformat()}\n"
        "async def test_w(test_vehicle, payload):\n    post(json=payload)\n"
    ),
    "payload built on a payload": (
        "@pytest.fixture\ndef base():\n    return {'date': date.today().isoformat()}\n"
        "@pytest.fixture\ndef payload(base):\n    return {**base, 'cost': 1}\n"
        "async def test_w(test_vehicle, payload):\n    post(json=payload)\n"
    ),
    "getfixturevalue payload": (
        "@pytest.fixture\ndef payload():\n    return {'date': date.today().isoformat()}\n"
        "async def test_w(test_vehicle, request):\n"
        "    post(json=request.getfixturevalue('payload'))\n"
    ),
    "getfixturevalue value": (
        "@pytest.fixture\ndef today():\n    return date.today()\n"
        "async def test_w(test_vehicle, request):\n"
        "    add(Fuel(date=request.getfixturevalue(argname='today')))\n"
    ),
    "getfixturevalue value, bound to a name": (
        "@pytest.fixture\ndef today():\n    return date.today()\n"
        "async def test_w(test_vehicle, request):\n"
        "    d = request.getfixturevalue('today')\n    add(Fuel(date=d))\n"
    ),
    "getfixturevalue test_vehicle": (
        "@pytest.fixture\ndef today():\n    return date.today()\n"
        "async def test_w(request, today):\n"
        "    vin = request.getfixturevalue('test_vehicle')['vin']\n"
        "    add(Fuel(vin=vin, date=today))\n"
    ),
    "fixture that writes on test_vehicle": (
        "@pytest_asyncio.fixture\n"
        "async def writer(db_session, test_vehicle):\n"
        "    db_session.add(Fuel(vin=test_vehicle['vin'], date=date.today()))\n"
        "    await db_session.commit()\n"
    ),
}

# A writer that asks for a fixture by a name the guard can't read fails outright.
UNNAMED_FIXTURE_WRITERS = {
    "variable": (
        "async def test_w(test_vehicle, request):\n"
        "    name = 'payload'\n    post(json=request.getfixturevalue(name))\n"
    ),
    "f-string": (
        "async def test_w(test_vehicle, request, kind):\n"
        "    post(json=request.getfixturevalue(f'{kind}_payload'))\n"
    ),
}

# And the near misses each shape must leave alone.
FIXTURE_NEAR_MISSES = {
    "getfixturevalue of a fixed-date payload": (
        "@pytest.fixture\ndef payload():\n    return {'date': '2024-05-15'}\n"
        "async def test_w(test_vehicle, request):\n"
        "    post(json=request.getfixturevalue('payload'))\n"
    ),
    "unnamed getfixturevalue on own_vehicle": (
        "async def test_w(own_vehicle, request, kind):\n"
        "    post(json=request.getfixturevalue(f'{kind}_payload'))\n"
    ),
    "today value used in a query": (
        "@pytest.fixture\ndef today():\n    return date.today()\n"
        "async def test_w(test_vehicle, today):\n    get(params={'start': today.isoformat()})\n"
    ),
    "today value on own_vehicle": (
        "@pytest.fixture\ndef today():\n    return date.today()\n"
        "async def test_w(own_vehicle, today):\n    add(Fuel(date=today))\n"
    ),
    "fixture that writes a fixed date": (
        "@pytest_asyncio.fixture\n"
        "async def writer(db_session, test_vehicle):\n"
        "    db_session.add(Fuel(vin=test_vehicle['vin'], date=date(2024, 3, 1)))\n"
    ),
}


def test_the_today_check_follows_every_fixture_shape() -> None:
    missed = {
        shape: found
        for shape, source in FIXTURE_SHAPES.items()
        if (found := _shared_vehicle_today_writers(ast.parse(source)))
        not in (["test_w"], ["writer"])
    }
    assert missed == {}


def test_a_writer_asking_for_an_unnamed_fixture_fails_with_a_way_out() -> None:
    found = {
        shape: _shared_vehicle_today_writers(ast.parse(source))
        for shape, source in UNNAMED_FIXTURE_WRITERS.items()
    }
    assert found == {shape: [f"test_w ({UNNAMED_FIXTURE})"] for shape in UNNAMED_FIXTURE_WRITERS}


def test_the_today_check_leaves_fixture_near_misses_alone() -> None:
    flagged = {
        shape: found
        for shape, source in FIXTURE_NEAR_MISSES.items()
        if (found := _shared_vehicle_today_writers(ast.parse(source)))
    }
    assert flagged == {}


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
