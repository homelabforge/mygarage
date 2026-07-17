"""Parity diagnostics for the squash strategy.

STRUCTURAL parity: Base.metadata.create_all() must produce a schema structurally
identical to create_all + replaying all real migrations, WITHIN a dialect. This
guards the assumption a v3 baseline (§6a) rests on and catches model<->migration
drift. It does NOT prove data-losslessness.

SEED-DATA inventory: after a fresh create_all + migrations, some tables carry
rows a bare create_all baseline would drop (e.g. 033_seed_dtc_definitions). The
inventory surfaces that set — the manifest §6a must exclude-from-REPLACES or
reproduce. See the design spec.
"""

import importlib
from pathlib import Path

import pytest
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)

from app.migrations.runner import run_migrations

pytestmark = pytest.mark.migrations

_IGNORE_TABLES = {"schema_migrations"}  # runner bookkeeping, not part of the model


def _schema_snapshot(engine) -> dict:
    """Normalized structural snapshot; auto-generated object names excluded so
    create_all and hand-DDL schemas are comparable within a dialect."""
    insp = inspect(engine)
    snapshot: dict = {}
    for table in sorted(insp.get_table_names()):
        if table in _IGNORE_TABLES:
            continue
        columns = {
            col["name"]: {
                "type": str(col["type"]).upper(),
                "nullable": bool(col["nullable"]),
                "default": None
                if col.get("default") is None
                else str(col["default"]).upper().strip(),
            }
            for col in insp.get_columns(table)
        }
        pk = sorted(insp.get_pk_constraint(table).get("constrained_columns") or [])
        if len(pk) == 1:
            pk_col = columns.get(pk[0])
            if pk_col is not None and pk_col["type"] == "INTEGER":
                # SQLite rowid-alias reflection artifact: a sole `INTEGER PRIMARY
                # KEY` column reflects notnull=0 (nullable) even though it can
                # never actually hold NULL, while SQLAlchemy Core reports
                # nullable=False for `Column(Integer, primary_key=True)`. This is
                # a benign reflection quirk, not real drift — normalize to the
                # canonical (non-nullable) value so create_all and hand-DDL agree.
                pk_col["nullable"] = False
        fks = sorted(
            (
                tuple(fk.get("constrained_columns") or []),
                fk.get("referred_table"),
                tuple(fk.get("referred_columns") or []),
                (fk.get("options") or {}).get("ondelete"),
                (fk.get("options") or {}).get("onupdate"),
            )
            for fk in insp.get_foreign_keys(table)
        )
        uniques = sorted(
            tuple(sorted(uc.get("column_names") or [])) for uc in insp.get_unique_constraints(table)
        )
        try:
            checks = sorted(
                " ".join(str(cc.get("sqltext") or "").upper().split())
                for cc in insp.get_check_constraints(table)
            )
        except NotImplementedError:  # pragma: no cover — dialect lacks check reflection
            checks = []
        indexes = sorted(
            (tuple(sorted(ix.get("column_names") or [])), bool(ix.get("unique")))
            for ix in insp.get_indexes(table)
        )
        snapshot[table] = {
            "columns": columns,
            "pk": pk,
            "fks": fks,
            "uniques": uniques,
            "checks": checks,
            "indexes": indexes,
        }
    return snapshot


def _diff_snapshots(a: dict, b: dict) -> list[str]:
    """Readable structural differences (a = create_all, b = create_all+migrations)."""
    diffs: list[str] = []
    for t in sorted(set(a) - set(b)):
        diffs.append(f"table only in create_all: {t}")
    for t in sorted(set(b) - set(a)):
        diffs.append(f"table only in migrated: {t}")
    for t in sorted(set(a) & set(b)):
        for key in ("columns", "pk", "fks", "uniques", "checks", "indexes"):
            if a[t][key] != b[t][key]:
                diffs.append(f"{t}.{key}: create_all={a[t][key]!r} migrated={b[t][key]!r}")
    return diffs


def test_schema_snapshot_captures_structure(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'snap.db'}")
    md = MetaData()
    Table(
        "widget",
        md,
        Column("id", Integer, primary_key=True),
        Column("name", String(50), nullable=False),
        UniqueConstraint("name"),
    )
    md.create_all(engine)
    snap = _schema_snapshot(engine)
    engine.dispose()

    assert set(snap) == {"widget"}
    assert snap["widget"]["pk"] == ["id"]
    assert snap["widget"]["columns"]["name"]["nullable"] is False
    assert ("name",) in snap["widget"]["uniques"]
    assert "default" in snap["widget"]["columns"]["id"]  # default key always present


def test_schema_snapshot_normalizes_rowid_pk_nullable(tmp_path):
    """SQLite reflects a sole `INTEGER PRIMARY KEY` (rowid-alias) column as
    nullable=True (notnull=0) even though it can never hold NULL, while
    SQLAlchemy Core reports nullable=False for `Column(Integer,
    primary_key=True)`. A hand-DDL table and an ORM-created table must
    normalize to the identical (non-nullable) snapshot for that column."""
    ddl_engine = create_engine(f"sqlite:///{tmp_path / 'ddl.db'}")
    with ddl_engine.begin() as conn:
        conn.execute(text("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"))
    ddl_snap = _schema_snapshot(ddl_engine)
    ddl_engine.dispose()

    orm_engine = create_engine(f"sqlite:///{tmp_path / 'orm.db'}")
    md = MetaData()
    Table(
        "widget",
        md,
        Column("id", Integer, primary_key=True),
        Column("name", String(50)),
    )
    md.create_all(orm_engine)
    orm_snap = _schema_snapshot(orm_engine)
    orm_engine.dispose()

    assert ddl_snap["widget"]["columns"]["id"] == orm_snap["widget"]["columns"]["id"]
    assert ddl_snap["widget"]["columns"]["id"]["nullable"] is False
    assert orm_snap["widget"]["columns"]["id"]["nullable"] is False


def test_diff_snapshots_detects_extra_column():
    base = {
        "columns": {"id": {"type": "INTEGER", "nullable": False, "default": None}},
        "pk": ["id"],
        "fks": [],
        "uniques": [],
        "checks": [],
        "indexes": [],
    }
    a = {"t": base}
    b = {
        "t": {
            **base,
            "columns": {
                **base["columns"],
                "extra": {"type": "INTEGER", "nullable": True, "default": None},
            },
        }
    }
    diffs = _diff_snapshots(a, b)
    assert diffs and any("columns" in d for d in diffs)


def test_diff_snapshots_empty_when_identical():
    snap = {
        "t": {
            "columns": {"id": {"type": "INTEGER", "nullable": False, "default": None}},
            "pk": ["id"],
            "fks": [],
            "uniques": [],
            "checks": [],
            "indexes": [],
        }
    }
    assert _diff_snapshots(snap, {"t": dict(snap["t"])}) == []


def _register_all_models() -> MetaData:
    """Import EVERY app/models/*.py so Base.metadata is complete.

    app/models/__init__.py does not import all model modules (e.g. user,
    audit_log, toll); production only has them all registered because its full
    import graph has run by the time init_db() calls create_all. Importing every
    module here reproduces that completeness without depending on __init__.
    """
    import app.models as models_pkg

    pkg_dir = Path(models_pkg.__file__).parent
    for py in sorted(pkg_dir.glob("*.py")):
        if py.stem == "__init__":
            continue
        importlib.import_module(f"app.models.{py.stem}")
    from app.database import Base

    return Base.metadata


def _migrations_dir() -> Path:
    import app.migrations as m

    return Path(m.__file__).parent


def _reset(dialect: str, engine) -> None:
    """Return the DB to empty between building DB-A and DB-B."""
    if dialect == "pg":
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    else:
        insp = inspect(engine)
        with engine.begin() as conn:
            for t in insp.get_table_names():  # test engine has no FK pragma; any order is safe
                conn.execute(text(f'DROP TABLE IF EXISTS "{t}"'))


def _nonempty_tables(engine) -> dict:
    """Tables carrying rows, table -> row count."""
    insp = inspect(engine)
    counts: dict = {}
    with engine.connect() as conn:
        for t in sorted(insp.get_table_names()):
            if t in _IGNORE_TABLES:
                continue
            n = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0
            if n:
                counts[t] = n
    return counts


def test_structural_parity(engine_for_migration):
    """DIAGNOSTIC + standing guard: within a dialect, create_all's schema must
    equal create_all + replaying all real migrations (production init_db()'s real
    sequence: database.py:136 then :155).

    Green => collapsing history into a create_all baseline (§6a) loses no SCHEMA
    (data is covered separately by test_seed_data_inventory). A non-empty diff is
    model<->migration drift — do NOT edit the test to force green; the diff is the
    finding (see Step 5).
    """
    dialect, engine, url = engine_for_migration
    metadata = _register_all_models()

    metadata.create_all(engine)  # DB-A: create_all only
    snap_a = _schema_snapshot(engine)

    _reset(dialect, engine)

    metadata.create_all(engine)  # DB-B: create_all first (as init_db does)...
    run_migrations(url, _migrations_dir())  # ...then the migration runner
    snap_b = _schema_snapshot(engine)

    diffs = _diff_snapshots(snap_a, snap_b)
    assert not diffs, "create_all diverges from create_all + migrations:\n" + "\n".join(diffs)


def test_seed_data_inventory(engine_for_migration):
    """DIAGNOSTIC: after a fresh create_all + migrations, some tables carry rows a
    bare create_all baseline would DROP. This proves data-effect migrations exist
    and captures the exact table set — the manifest §6a must exclude-from-REPLACES
    or reproduce (e.g. 033_seed_dtc_definitions). See Step 5.
    """
    dialect, engine, url = engine_for_migration
    metadata = _register_all_models()
    metadata.create_all(engine)
    run_migrations(url, _migrations_dir())

    seeded = _nonempty_tables(engine)
    # A bare create_all baseline yields ZERO rows; a non-empty set is exactly what
    # such a baseline would lose. Recorded in the report as the §6a manifest.
    assert seeded, "expected fresh-install seed data (e.g. DTC definitions) but found none"
