"""Migration 157: invoice, PO and work order numbers on service_visits.

Three nullable VARCHAR(50) columns, no backfill. FATAL, because the model maps
them and every visit SELECT reads them. Parameterised over SQLite and
PostgreSQL via `engine_for_migration`.
"""

import importlib
import importlib.util
import types
from pathlib import Path

import pytest
from sqlalchemy import Engine, MetaData, inspect, text

import app.migrations as _m

pytestmark = pytest.mark.migrations

_NAME = "157_add_visit_reference_numbers"
_COLUMNS = ("invoice_number", "po_number", "work_order_number")


def _load(name: str = _NAME) -> types.ModuleType:
    """Load a migration module by file, as the runner does."""
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _metadata() -> MetaData:
    """Every model registered, so create_all builds the whole schema the FKs need."""
    import app.models as models_pkg

    for py in sorted(Path(models_pkg.__file__).parent.glob("*.py")):
        if py.stem != "__init__":
            importlib.import_module(f"app.models.{py.stem}")
    from app.database import Base

    return Base.metadata


def _make_156_visits(engine: Engine) -> None:
    """service_visits as 156 leaves it (the columns 157 cares about), with one visit."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE service_visits (id INTEGER PRIMARY KEY, vin VARCHAR(17) NOT NULL, "
                "date DATE NOT NULL, insurance_claim_number VARCHAR(50))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO service_visits (id, vin, date, insurance_claim_number) "
                "VALUES (1, '1HGCM82633A004352', '2026-03-01', 'CLM-1')"
            )
        )


def test_157_adds_three_nullable_columns_old_row_reads_null(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_156_visits(engine)
    _load().upgrade(engine)

    cols = {c["name"]: c for c in inspect(engine).get_columns("service_visits")}
    for name in _COLUMNS:
        assert name in cols, name
        assert cols[name]["nullable"] is True
        assert getattr(cols[name]["type"], "length", None) == 50
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT invoice_number, po_number, work_order_number, insurance_claim_number "
                "FROM service_visits WHERE id = 1"
            )
        ).one()
    assert tuple(row) == (None, None, None, "CLM-1")


def test_157_is_idempotent(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_156_visits(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)  # must not raise "duplicate column"
    names = [c["name"] for c in inspect(engine).get_columns("service_visits")]
    for name in _COLUMNS:
        assert names.count(name) == 1, name


def test_157_on_a_fresh_create_all_schema_is_a_no_op(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    before = [c["name"] for c in inspect(engine).get_columns("service_visits")]
    assert set(_COLUMNS) <= set(before)
    _load().upgrade(engine)
    assert [c["name"] for c in inspect(engine).get_columns("service_visits")] == before


def test_157_missing_table_skips(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("service_visits")


def test_157_is_fatal() -> None:
    assert _load().FATAL is True
