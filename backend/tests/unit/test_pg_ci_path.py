"""Every backend test must also run on PostgreSQL in CI.

SQLite ignores VARCHAR widths, so a test that only ever runs there can be green
and still wrong on PG (#200 was one). ci.yml names the PG paths one by one, and
these tests keep that list from going stale.
"""

import ast
import configparser
import fnmatch
import os
from pathlib import Path

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[2]
TESTS = BACKEND / "tests"
CI_YML = BACKEND.parent / ".github" / "workflows" / "ci.yml"

# Both drop the public schema, so they have to run before anything else.
MUST_RUN_FIRST = ["tests/migrations/", "tests/pg_migration_path_test.py"]


def _pg_paths() -> list[str]:
    """The PG jobs' pytest paths, as ci.yml passes them."""
    if not CI_YML.exists():
        # The docker runners mount backend/ only. CI's Backend Tests job has
        # the whole checkout, so this can't skip there.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail(f"{CI_YML} is missing in CI")
        pytest.skip("ci.yml isn't mounted in this runner")
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs", {})
    if "postgres-tests" in jobs:
        matrix_include = (
            jobs["postgres-tests"].get("strategy", {}).get("matrix", {}).get("include", [])
        )
        paths: list[str] = []
        for item in matrix_include:
            paths.extend(item.get("paths", "").split())
        return paths
    return workflow["jobs"]["ci"]["with"]["pg-migrations-pytest-path"].split()


def _ini_patterns(key: str) -> list[str]:
    """A pytest.ini naming option, e.g. python_files."""
    ini = configparser.ConfigParser(interpolation=None)
    ini.read(BACKEND / "pytest.ini", encoding="utf-8")
    return ini["pytest"][key].split()


def _matches(name: str, key: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in _ini_patterns(key))


def _defines_tests(module: Path) -> bool:
    """Whether the module has a top-level test function or class pytest would run."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    return any(
        (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and _matches(node.name, "python_functions")
        )
        or (isinstance(node, ast.ClassDef) and _matches(node.name, "python_classes"))
        for node in tree.body
    )


def _test_roots() -> set[str]:
    """Where each test module has to be named for the PG job to run it.

    Going by what a module defines, not its name: the pg_*_test.py suites don't
    match python_files, so walking a directory never collects them and only
    their own path runs them. Everything else rides in on its top-level dir.
    """
    roots: set[str] = set()
    for module in TESTS.rglob("*.py"):
        # Pytest never collects tests from a conftest, and its test_engine
        # fixture would otherwise read as a test.
        if module.name == "conftest.py" or not _defines_tests(module):
            continue
        rel = module.relative_to(TESTS)
        if len(rel.parts) == 1 or not _matches(module.name, "python_files"):
            roots.add(f"tests/{rel.as_posix()}")
        else:
            roots.add(f"tests/{rel.parts[0]}/")
    return roots


def test_every_test_root_runs_on_pg() -> None:
    """A new test dir or top-level file has to be added to ci.yml."""
    missing = sorted(_test_roots() - set(_pg_paths()))
    assert missing == [], f"add to postgres-tests in ci.yml: {missing}"


def test_postgres_matrix_jobs_have_descriptive_names() -> None:
    """Every PostgreSQL test job must have a descriptive, distinct name."""
    if not CI_YML.exists():
        pytest.skip("ci.yml isn't mounted in this runner")
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs", {})
    if "postgres-tests" in jobs:
        matrix_include = (
            jobs["postgres-tests"].get("strategy", {}).get("matrix", {}).get("include", [])
        )
        assert len(matrix_include) >= 2, "PostgreSQL tests must be partitioned into multiple jobs"
        names = [item.get("name", "") for item in matrix_include]
        assert len(names) == len(set(names)), "Each matrix partition must have a unique name"
        for name in names:
            assert name.startswith("PostgreSQL "), (
                f"Job name '{name}' must start with 'PostgreSQL '"
            )


def test_every_listed_path_exists() -> None:
    """A renamed or deleted file would make pytest exit 4 on the PG job."""
    gone = [p for p in _pg_paths() if not (BACKEND / p).exists()]
    assert gone == []


def test_schema_droppers_run_first() -> None:
    """Migrations wipe the public schema, so nothing may run ahead of them."""
    assert _pg_paths()[: len(MUST_RUN_FIRST)] == MUST_RUN_FIRST


def test_no_path_sits_inside_another() -> None:
    """Pytest folds nested paths into one walk, which reorders the run and
    drops an explicitly named file like pg_migration_path_test.py."""
    paths = _pg_paths()
    nested = [
        (a, b) for a in paths for b in paths if a != b and a.endswith("/") and b.startswith(a)
    ]
    assert nested == []
