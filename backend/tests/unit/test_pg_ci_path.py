"""Every backend test must also run on PostgreSQL in CI.

SQLite ignores VARCHAR widths, so a test that only ever runs there can be green
and still wrong on PG (#200 was one). ci.yml names the PG paths one by one, and
these tests keep that list from going stale.
"""

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
    """The PG job's pytest paths, as ci.yml passes them."""
    if not CI_YML.exists():
        # The docker runners mount backend/ only. CI's Backend Tests job has
        # the whole checkout, so this can't skip there.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail(f"{CI_YML} is missing in CI")
        pytest.skip("ci.yml isn't mounted in this runner")
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    return workflow["jobs"]["ci"]["with"]["pg-migrations-pytest-path"].split()


def _test_roots() -> set[str]:
    """Each top-level test dir and file, spelled the way ci.yml lists them."""
    roots = {"tests/pg_migration_path_test.py"}
    for child in TESTS.iterdir():
        if child.is_dir() and any(child.rglob("test_*.py")):
            roots.add(f"tests/{child.name}/")
        elif child.is_file() and child.name.startswith("test_") and child.suffix == ".py":
            roots.add(f"tests/{child.name}")
    return roots


def test_every_test_root_runs_on_pg() -> None:
    """A new test dir or top-level file has to be added to ci.yml."""
    missing = sorted(_test_roots() - set(_pg_paths()))
    assert missing == [], f"add to pg-migrations-pytest-path in ci.yml: {missing}"


def test_every_listed_path_exists() -> None:
    """A renamed or deleted file would make pytest exit 4 on the PG job."""
    gone = [p for p in _pg_paths() if not (BACKEND / p).exists()]
    assert gone == []


def test_schema_droppers_run_first() -> None:
    """Migrations wipe the public schema, so nothing may run ahead of them."""
    assert _pg_paths()[: len(MUST_RUN_FIRST)] == MUST_RUN_FIRST


def test_no_path_sits_inside_another() -> None:
    """Pytest folds nested paths into one walk, which reorders the run and
    drops the explicitly named pg_migration_path_test.py."""
    paths = _pg_paths()
    nested = [
        (a, b) for a in paths for b in paths if a != b and a.endswith("/") and b.startswith(a)
    ]
    assert nested == []
