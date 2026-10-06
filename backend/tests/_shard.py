"""Split one pytest run across CI runners, a whole module at a time.

The shared CI workflow sets the PYTEST_SHARD_* vars on each runner. Without
them nothing changes, so local runs see the whole suite.
"""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

import pytest

INDEX_VAR = "PYTEST_SHARD_INDEX"
COUNT_VAR = "PYTEST_SHARD_COUNT"
REPORT_VAR = "PYTEST_SHARD_REPORT"
REPORT_SCHEMA = 1


class _HasNodeId(Protocol):
    # A property, because pytest.Item.nodeid is read-only and a plain
    # attribute here would make pyright reject real items.
    @property
    def nodeid(self) -> str: ...


def read_shard(environ: Mapping[str, str]) -> tuple[int, int] | None:
    """This runner's (index, count), 1-based, or None when CI didn't set them."""
    raw_index = environ.get(INDEX_VAR)
    raw_count = environ.get(COUNT_VAR)
    if raw_index is None and raw_count is None:
        return None
    if raw_index is None or raw_count is None:
        raise pytest.UsageError(f"set both {INDEX_VAR} and {COUNT_VAR}, or neither")
    try:
        index, count = int(raw_index), int(raw_count)
    except ValueError:
        raise pytest.UsageError(
            f"{INDEX_VAR}={raw_index!r} and {COUNT_VAR}={raw_count!r} must be whole numbers"
        ) from None
    if not 1 <= index <= count:
        raise pytest.UsageError(f"shard {index}/{count} is out of range")
    return index, count


def module_of(nodeid: str) -> str:
    """The test file a node id belongs to."""
    return nodeid.split("::", 1)[0]


def assign(modules: list[str], count: int) -> dict[str, int]:
    """Deal modules out round-robin in collection order.

    Order inside a shard is still collection order, so tests/migrations/ and
    pg_migration_path_test.py still run ahead of everything else in each shard.
    """
    unique = list(dict.fromkeys(modules))
    return {module: position % count + 1 for position, module in enumerate(unique)}


def apply_shard[ItemT: _HasNodeId](
    items: list[ItemT],
    *,
    rootpath: Path,
    deselect: Callable[[list[ItemT]], None],
    environ: Mapping[str, str],
) -> None:
    """Cut items down to this shard's modules and write the report CI checks."""
    shard = read_shard(environ)
    if shard is None:
        return
    index, count = shard
    modules = list(dict.fromkeys(module_of(item.nodeid) for item in items))
    owner = assign(modules, count)
    keep = [item for item in items if owner[module_of(item.nodeid)] == index]
    drop = [item for item in items if owner[module_of(item.nodeid)] != index]
    if drop:
        deselect(drop)
    items[:] = keep

    report = environ.get(REPORT_VAR)
    if report:
        path = Path(report)
        if not path.is_absolute():
            path = rootpath / path
        payload = {
            "schema": REPORT_SCHEMA,
            "index": index,
            "count": count,
            "modules": modules,
            "selected": [module for module in modules if owner[module] == index],
        }
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
