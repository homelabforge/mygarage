"""Every app rate limiter is reset before every test, from one place.

The limiters are module globals keyed on the client address, and the whole
suite talks from 127.0.0.1, so a budget one file spends can 429 the next.
conftest resets the lot before each test; these checks make a new limiter
fail here until it's added to that list.
"""

import ast
import importlib
from pathlib import Path

import pytest

from tests.conftest import APP_LIMITERS

BACKEND_DIR = Path(__file__).resolve().parents[2]
APP_DIR = BACKEND_DIR / "app"
TESTS_DIR = BACKEND_DIR / "tests"


def _module_name(path: Path) -> str:
    """`app/routes/auth.py` -> `app.routes.auth`; a package's `__init__` is the package."""
    parts = path.relative_to(BACKEND_DIR).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _dotted(node: ast.AST) -> str | None:
    """`a.b.c` as a string, or None if it isn't a plain name/attribute chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr}" if head else None
    return None


def _limiter_names(tree: ast.Module) -> set[str]:
    """Every spelling of `Limiter` this module could call, bare or dotted.

    slowapi re-exports it from `slowapi.extension`, so both homes count, and so
    does any alias for either module.
    """
    homes = {"slowapi", "slowapi.extension"}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in homes:
            for a in node.names:
                if a.name == "Limiter":
                    names.add(a.asname or a.name)
                elif f"{node.module}.{a.name}" in homes:
                    names.add(f"{a.asname or a.name}.Limiter")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in homes:
                    continue
                if a.asname:
                    names.add(f"{a.asname}.Limiter")
                else:
                    # `import slowapi.extension` binds `slowapi`, which reaches both homes.
                    names |= {f"{home}.Limiter" for home in homes}
    return names


def _is_limiter_call(node: ast.AST, names: set[str]) -> bool:
    return isinstance(node, ast.Call) and _dotted(node.func) in names


def _scan_source(source: str, module: str, filename: str) -> tuple[set[str], list[str]]:
    """One module's limiters: dotted paths of module-level ones, and `file:line` of any other."""
    tree = ast.parse(source, filename=filename)
    names = _limiter_names(tree)
    if not names:
        return set(), []
    found: set[str] = set()
    module_level: set[int] = set()
    for stmt in tree.body:
        value = stmt.value if isinstance(stmt, ast.Assign | ast.AnnAssign) else None
        if value is None or not _is_limiter_call(value, names):
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for target in targets:
            assert isinstance(target, ast.Name), f"{filename}:{stmt.lineno} unpacks a Limiter"
            found.add(f"{module}.{target.id}")
        module_level.add(id(value))
    stray = [
        f"{filename}:{node.lineno}"
        for node in ast.walk(tree)
        if _is_limiter_call(node, names) and id(node) not in module_level
    ]
    return found, stray


def _scan_app() -> tuple[set[str], list[str]]:
    """Dotted paths of module-level limiters, and any `Limiter(` call that isn't one."""
    found: set[str] = set()
    stray: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        f, s = _scan_source(
            path.read_text(), _module_name(path), str(path.relative_to(BACKEND_DIR))
        )
        found |= f
        stray += s
    return found, stray


# Every import form the scan must see through, so a limiter built any of these
# ways can't dodge the reset list.
IMPORT_FORMS = {
    "from slowapi": "from slowapi import Limiter\n{target} = Limiter(key_func=k)\n",
    "from slowapi alias": "from slowapi import Limiter as L\n{target} = L(key_func=k)\n",
    "import slowapi": "import slowapi\n{target} = slowapi.Limiter(key_func=k)\n",
    "import slowapi alias": "import slowapi as s\n{target} = s.Limiter(key_func=k)\n",
    "from slowapi.extension": "from slowapi.extension import Limiter\n{target} = Limiter(key_func=k)\n",
    "import slowapi.extension": (
        "import slowapi.extension\n{target} = slowapi.extension.Limiter(key_func=k)\n"
    ),
    "import slowapi.extension alias": (
        "import slowapi.extension as ext\n{target} = ext.Limiter(key_func=k)\n"
    ),
    "from slowapi import extension": (
        "from slowapi import extension\n{target} = extension.Limiter(key_func=k)\n"
    ),
}


@pytest.mark.parametrize("form", sorted(IMPORT_FORMS))
def test_the_scan_sees_a_module_level_limiter_in_every_import_form(form: str) -> None:
    source = IMPORT_FORMS[form].format(target="limiter")
    assert _scan_source(source, "app.fake", "fake.py") == ({"app.fake.limiter"}, [])


@pytest.mark.parametrize("form", sorted(IMPORT_FORMS))
def test_the_scan_flags_a_function_built_limiter_in_every_import_form(form: str) -> None:
    body = IMPORT_FORMS[form].format(target="    limiter").splitlines()
    source = f"{body[0]}\ndef build():\n{body[1]}\n"
    assert _scan_source(source, "app.fake", "fake.py") == (set(), ["fake.py:3"])


def test_the_scan_ignores_an_unrelated_limiter_class() -> None:
    source = "from mylib import Limiter\nlimiter = Limiter()\n"
    assert _scan_source(source, "app.fake", "fake.py") == (set(), [])


def test_every_app_limiter_is_in_the_reset_list() -> None:
    found, _ = _scan_app()
    assert found == set(APP_LIMITERS), (
        "tests/conftest.py APP_LIMITERS is out of step with app/: "
        f"missing {sorted(found - set(APP_LIMITERS))}, stale {sorted(set(APP_LIMITERS) - found)}"
    )


def test_the_reset_list_holds_the_live_objects() -> None:
    """A right name bound to the wrong object would reset nothing that matters."""
    for dotted, limiter in APP_LIMITERS.items():
        module, _, name = dotted.rpartition(".")
        assert getattr(importlib.import_module(module), name) is limiter, dotted


def test_no_limiter_is_built_outside_module_level() -> None:
    """One built in a function or a class is a fresh bucket the reset list can't name."""
    _, stray = _scan_app()
    assert stray == []


def test_no_test_reaches_into_limiter_storage() -> None:
    """`Limiter.reset()` is the API; `._storage` is slowapi's private state."""
    offenders = sorted(
        f"{path.relative_to(BACKEND_DIR)}:{node.lineno}"
        for path in TESTS_DIR.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path)))
        if isinstance(node, ast.Attribute) and node.attr == "_storage"
    )
    assert offenders == []
