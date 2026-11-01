"""Every app rate limiter is reset before every test, from one place.

The limiters are module globals keyed on the client address, and the whole
suite talks from 127.0.0.1, so a budget one file spends can 429 the next.
conftest resets the lot before each test; these checks make a new limiter
fail here until it's added to that list.
"""

import ast
import importlib
from pathlib import Path

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


def _limiter_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """What `Limiter` is called in this module: bare names, and module aliases for `slowapi`."""
    bare: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "slowapi":
            bare |= {a.asname or a.name for a in node.names if a.name == "Limiter"}
        elif isinstance(node, ast.Import):
            modules |= {a.asname or a.name for a in node.names if a.name == "slowapi"}
    return bare, modules


def _is_limiter_call(node: ast.AST, bare: set[str], modules: set[str]) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in bare
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "Limiter"
        and isinstance(func.value, ast.Name)
        and func.value.id in modules
    )


def _scan_app() -> tuple[set[str], list[str]]:
    """Dotted paths of module-level limiters, and any `Limiter(` call that isn't one."""
    found: set[str] = set()
    stray: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        bare, modules = _limiter_names(tree)
        if not bare and not modules:
            continue
        module_level: set[int] = set()
        for stmt in tree.body:
            value = stmt.value if isinstance(stmt, ast.Assign | ast.AnnAssign) else None
            if value is None or not _is_limiter_call(value, bare, modules):
                continue
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for target in targets:
                assert isinstance(target, ast.Name), f"{path}:{stmt.lineno} unpacks a Limiter"
                found.add(f"{_module_name(path)}.{target.id}")
            module_level.add(id(value))
        stray += [
            f"{path.relative_to(BACKEND_DIR)}:{node.lineno}"
            for node in ast.walk(tree)
            if _is_limiter_call(node, bare, modules) and id(node) not in module_level
        ]
    return found, stray


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
