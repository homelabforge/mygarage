"""The CI shard hook: who runs which module, and the report CI checks."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests._shard import (
    COUNT_VAR,
    INDEX_VAR,
    REPORT_VAR,
    apply_shard,
    assign,
    read_shard,
)

BACKEND = Path(__file__).resolve().parents[2]


@dataclass
class FakeItem:
    """Just enough of a pytest item for the hook."""

    nodeid: str


ITEMS = [
    "tests/migrations/test_a.py::test_one",
    "tests/migrations/test_a.py::test_two",
    "tests/pg_migration_path_test.py::test_fresh",
    "tests/routes/test_b.py::test_x",
    "tests/routes/test_c.py::test_y[1]",
    "tests/routes/test_c.py::test_y[2]",
    "tests/unit/test_d.py::TestThing::test_z",
]


def _items() -> list[FakeItem]:
    return [FakeItem(nodeid) for nodeid in ITEMS]


def _run(index: int, count: int, tmp_path: Path) -> tuple[list[str], list[str], dict]:
    """Apply one shard and return kept ids, deselected ids and the report."""
    items = _items()
    dropped: list[FakeItem] = []
    report = tmp_path / f"report-{index}.json"
    apply_shard(
        items,
        rootpath=tmp_path,
        deselect=dropped.extend,
        environ={INDEX_VAR: str(index), COUNT_VAR: str(count), REPORT_VAR: report.name},
    )
    return (
        [item.nodeid for item in items],
        [item.nodeid for item in dropped],
        json.loads(report.read_text(encoding="utf-8")),
    )


def test_unset_env_means_no_sharding() -> None:
    assert read_shard({}) is None


def test_reads_index_and_count() -> None:
    assert read_shard({INDEX_VAR: "2", COUNT_VAR: "3"}) == (2, 3)


@pytest.mark.parametrize(
    "environ",
    [
        {INDEX_VAR: "1"},
        {COUNT_VAR: "2"},
        {INDEX_VAR: "one", COUNT_VAR: "2"},
        {INDEX_VAR: "0", COUNT_VAR: "2"},
        {INDEX_VAR: "3", COUNT_VAR: "2"},
        {INDEX_VAR: "1", COUNT_VAR: "0"},
        {INDEX_VAR: "-1", COUNT_VAR: "2"},
    ],
)
def test_bad_shard_env_stops_the_run(environ: dict[str, str]) -> None:
    with pytest.raises(pytest.UsageError):
        read_shard(environ)


def test_modules_are_dealt_round_robin_in_order() -> None:
    assert assign(["a", "b", "c", "d", "e"], 2) == {"a": 1, "b": 2, "c": 1, "d": 2, "e": 1}


def test_a_module_keeps_its_first_position() -> None:
    assert assign(["a", "a", "b"], 2) == {"a": 1, "b": 2}


def test_unset_env_leaves_the_run_alone(tmp_path: Path) -> None:
    items = _items()
    dropped: list[FakeItem] = []
    apply_shard(items, rootpath=tmp_path, deselect=dropped.extend, environ={})
    assert [item.nodeid for item in items] == ITEMS
    assert dropped == []
    assert list(tmp_path.iterdir()) == []


def test_a_shard_keeps_whole_modules_in_collection_order(tmp_path: Path) -> None:
    kept, dropped, _ = _run(1, 2, tmp_path)
    # Modules in order: migrations/test_a (1), pg_migration_path (2), routes/test_b (1),
    # routes/test_c (2), unit/test_d (1).
    assert kept == [ITEMS[0], ITEMS[1], ITEMS[3], ITEMS[6]]
    assert dropped == [ITEMS[2], ITEMS[4], ITEMS[5]]


def test_the_report_names_every_module_and_this_shards_share(tmp_path: Path) -> None:
    _, _, report = _run(2, 2, tmp_path)
    assert report == {
        "schema": 1,
        "index": 2,
        "count": 2,
        "modules": [
            "tests/migrations/test_a.py",
            "tests/pg_migration_path_test.py",
            "tests/routes/test_b.py",
            "tests/routes/test_c.py",
            "tests/unit/test_d.py",
        ],
        "selected": ["tests/pg_migration_path_test.py", "tests/routes/test_c.py"],
    }


@pytest.mark.parametrize("count", [1, 2, 3, 4, 6, 9])
def test_every_test_runs_in_exactly_one_shard(count: int, tmp_path: Path) -> None:
    seen: list[str] = []
    for index in range(1, count + 1):
        kept, _, _ = _run(index, count, tmp_path)
        seen.extend(kept)
    assert sorted(seen) == sorted(ITEMS)


def test_an_absolute_report_path_is_used_as_is(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "elsewhere" / "r.json"
    target.parent.mkdir()
    apply_shard(
        _items(),
        rootpath=root,
        deselect=lambda items: None,
        environ={INDEX_VAR: "1", COUNT_VAR: "1", REPORT_VAR: str(target)},
    )
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["selected"] == report["modules"]
    assert list(root.iterdir()) == []


def _collect(index: int, count: int, report: Path) -> tuple[int, str]:
    """Collect tests/routes in a child pytest with the shard env set."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_SHARD_")}
    env.update({INDEX_VAR: str(index), COUNT_VAR: str(count), REPORT_VAR: str(report)})
    # pytest.ini's addopts has -v, so -qq nets out to -q: one node id per line.
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/routes",
            "--collect-only",
            "-qq",
            "-p",
            "no:cacheprovider",
        ],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return done.returncode, done.stdout


def test_conftest_wires_the_hook_into_real_runs(tmp_path: Path) -> None:
    """The unit tests above call apply_shard directly; this proves pytest does too."""
    reports = []
    for index in (1, 2):
        report = tmp_path / f"shard-{index}.json"
        code, out = _collect(index, 2, report)
        assert code == 0, out
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["selected"], data
        for module in data["modules"]:
            assert (f"{module}::" in out) == (module in data["selected"]), module
        reports.append(data)
    first, second = reports
    assert first["modules"] == second["modules"]
    assert len(first["modules"]) >= 2
    assert set(first["selected"]).isdisjoint(second["selected"])
    assert set(first["selected"]) | set(second["selected"]) == set(first["modules"])
