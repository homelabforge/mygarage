"""Cascade-invariant assertion helpers.

What this catches
-----------------
The rc1 fuel-record delete path leaves orphan synced odometer rows
behind because the link is by attribute match (vin + date + reading)
with no FK enforcement. The existing fuel-delete tests only assert
the fuel record is gone — they don't sweep for orphans in related
tables. Phase 2.5 (migration 055) adds a real FK with ``ON DELETE
CASCADE``; this helper is what its tests use to prove the cascade
fires.

The helpers are deliberately small. Real cascade scenarios are
declared per-test as ``CascadeScenario`` instances and exercised
via ``assert_cascade_clean``, which:

1. Counts child rows linked to a parent before delete.
2. Deletes the parent.
3. Asserts zero child rows remain linked.

PG-only by convention. SQLite supports ``ON DELETE CASCADE`` only when
``PRAGMA foreign_keys = ON`` is set per-connection, and the production
app does not enable it. Running cascade tests on SQLite would silently
"pass" (rows survive), which would be worse than skipping. The
``pg_engine``-style fixtures used by callers handle the skip.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class CascadeScenario:
    """Describes a parent→child relationship with an expected cascade.

    Attributes:
        name: Human-readable label for test failure messages.
        child_model: SQLAlchemy model class on the child side.
        fk_attr_name: Name of the column on ``child_model`` that holds
            the parent's id/value. e.g. ``"vin"``, ``"fuel_record_id"``.
        on_delete: Either ``"cascade"`` (child rows deleted with parent)
            or ``"set_null"`` (child FK nulled). Drives the assertion.
    """

    name: str
    child_model: type[Any]
    fk_attr_name: str
    on_delete: str  # "cascade" | "set_null"


async def count_children(
    session: AsyncSession,
    scenario: CascadeScenario,
    parent_value: Any,
) -> int:
    """Count rows on the child side that point at the parent."""
    fk_col = getattr(scenario.child_model, scenario.fk_attr_name)
    result = await session.execute(
        select(func.count()).select_from(scenario.child_model).where(fk_col == parent_value)
    )
    count = result.scalar()
    return int(count or 0)


async def assert_cascade_clean(
    session: AsyncSession,
    scenario: CascadeScenario,
    parent_value: Any,
    delete_parent: Callable[[], Any],
    expected_pre_count_min: int = 1,
) -> None:
    """End-to-end cascade assertion.

    Args:
        session: Active async session bound to the same engine the test
            is using. Caller is responsible for committing prior to
            invocation; this helper does its own commit after the parent
            delete to flush the cascade.
        scenario: Description of the parent→child relationship.
        parent_value: Value of the FK on the child side that points at
            the parent (e.g. the parent's id or vin).
        delete_parent: Async/sync callable that deletes the parent row
            and commits. Caller writes this so the parent's primary
            identifier strategy (id, vin, composite) stays opaque to
            this helper.
        expected_pre_count_min: Minimum number of child rows that must
            exist before the delete. Sanity check that catches "the
            scenario is set up wrong, there were no children to cascade".
    """
    pre = await count_children(session, scenario, parent_value)
    assert pre >= expected_pre_count_min, (
        f"{scenario.name}: expected at least {expected_pre_count_min} child row(s) "
        f"before delete, found {pre}. Scenario probably set up wrong."
    )

    result = delete_parent()
    if hasattr(result, "__await__"):
        await result

    await session.commit()
    # Refresh — the cascade might be committed to disk but cached in the
    # session's identity map.
    await session.flush()

    post = await count_children(session, scenario, parent_value)

    if scenario.on_delete == "cascade":
        assert post == 0, (
            f"{scenario.name}: expected 0 child rows after parent delete (CASCADE), "
            f"found {post}. Either the FK lacks ON DELETE CASCADE, or the parent "
            f"delete didn't actually fire."
        )
    elif scenario.on_delete == "set_null":
        # Children should still exist, but with the FK set to NULL.
        fk_col = getattr(scenario.child_model, scenario.fk_attr_name)
        result = await session.execute(
            select(func.count()).select_from(scenario.child_model).where(fk_col == parent_value)
        )
        still_pointing = int(result.scalar() or 0)
        assert still_pointing == 0, (
            f"{scenario.name}: expected child rows to be NULL'd after parent delete "
            f"(SET NULL), but {still_pointing} still point at the deleted parent."
        )
    else:
        raise ValueError(
            f"{scenario.name}: unknown on_delete {scenario.on_delete!r} "
            f"(expected 'cascade' or 'set_null')"
        )


# Sync-engine variant for migration-level cascade tests. Phase 2.5's
# fuel→odometer cascade verification uses this path because migration
# tests already run on a sync engine via ``engine_for_migration`` /
# ``pg_engine``. The async helper above is now usable under PG too
# (issue #77 was fixed by aligning pytest-asyncio's test loop scope
# with the session-scoped fixture loop) — use the async helper from
# integration tests, this sync sibling from migration tests.


def assert_cascade_clean_sync(
    engine: Engine,
    parent_table: str,
    child_table: str,
    child_fk_column: str,
    parent_value: Any,
    delete_sql: str,
    delete_params: dict[str, Any] | None = None,
    expected_pre_count_min: int = 1,
    on_delete: str = "cascade",
) -> None:
    """Sync raw-SQL cascade assertion for migration-level tests.

    Args:
        engine: Sync SQLAlchemy engine (PG or SQLite). Caller is
            responsible for fixture setup and parent/child seeding.
        parent_table: Table name on the parent side (used in failure
            messages).
        child_table: Table name on the child side.
        child_fk_column: Column on ``child_table`` that points at the
            parent.
        parent_value: Value of the FK in the child rows.
        delete_sql: Raw SQL string that deletes the parent row(s).
            Use bind parameters; this helper passes ``delete_params``.
        delete_params: Optional bind parameters for ``delete_sql``.
        expected_pre_count_min: Minimum child rows before delete.
        on_delete: ``"cascade"`` or ``"set_null"``.
    """
    with engine.begin() as conn:
        pre = conn.execute(
            text(f"SELECT COUNT(*) FROM {child_table} WHERE {child_fk_column} = :v"),
            {"v": parent_value},
        ).scalar()
        assert pre is not None and pre >= expected_pre_count_min, (
            f"{parent_table}→{child_table}: expected at least "
            f"{expected_pre_count_min} child row(s) before delete, found {pre}. "
            f"Scenario probably set up wrong."
        )

        conn.execute(text(delete_sql), delete_params or {})

        post = conn.execute(
            text(f"SELECT COUNT(*) FROM {child_table} WHERE {child_fk_column} = :v"),
            {"v": parent_value},
        ).scalar()

    if on_delete == "cascade":
        assert post == 0, (
            f"{parent_table}→{child_table}: expected 0 child rows after "
            f"parent delete (CASCADE), found {post}. Either the FK lacks "
            f"ON DELETE CASCADE or the parent delete didn't actually fire."
        )
    elif on_delete == "set_null":
        assert post == 0, (
            f"{parent_table}→{child_table}: expected child rows to be NULL'd "
            f"after parent delete (SET NULL), but {post} still point at the "
            f"deleted parent."
        )
    else:
        raise ValueError(f"unknown on_delete {on_delete!r}")
