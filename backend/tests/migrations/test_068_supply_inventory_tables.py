import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "app" / "migrations"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, MIGRATIONS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_deps(engine):
    """Create the FK-target tables the inventory tables reference."""
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(text(f"CREATE TABLE users (id {pk})"))
        conn.execute(text(f"CREATE TABLE address_book (id {pk})"))
        conn.execute(text(f"CREATE TABLE service_visits (id {pk})"))
        conn.execute(
            text(
                f"CREATE TABLE service_line_items (id {pk}, visit_id INTEGER "
                "REFERENCES service_visits(id))"
            )
        )


def test_068_creates_inventory_tables(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _load("068_supply_inventory_tables").upgrade(engine)
    insp = inspect(engine)
    assert insp.has_table("supplies")
    assert insp.has_table("supply_purchases")
    assert insp.has_table("supply_usages")
    supply_cols = {c["name"] for c in insp.get_columns("supplies")}
    assert {"id", "name", "unit_type", "vin", "is_active", "created_by_user_id"} <= supply_cols
    idx = {i["name"] for i in insp.get_indexes("supplies")}
    assert "idx_supplies_vin" in idx
    usage_idx = {i["name"] for i in insp.get_indexes("supply_usages")}
    assert "idx_supply_usages_line_item" in usage_idx


def test_068_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    mod = _load("068_supply_inventory_tables")
    mod.upgrade(engine)
    mod.upgrade(engine)  # must not raise
    assert inspect(engine).has_table("supplies")


def test_068_create_all_matches_migration(engine_for_migration):
    """Prod runs Base.metadata.create_all BEFORE the migration runner, so the
    model-built schema is authoritative on a fresh boot — assert column parity
    and that is_active carries a server default (R1-F3 / recommended edit 6)."""
    import app.models  # noqa: F401 — register all models on Base.metadata
    from app.database import Base

    _dialect, mig_engine, _url = engine_for_migration
    _make_deps(mig_engine)
    _load("068_supply_inventory_tables").upgrade(mig_engine)
    mig = inspect(mig_engine)

    model_engine = create_engine("sqlite://")
    Base.metadata.create_all(model_engine)
    model = inspect(model_engine)

    for table in ("supplies", "supply_purchases", "supply_usages"):
        mig_cols = {c["name"] for c in mig.get_columns(table)}
        model_cols = {c["name"] for c in model.get_columns(table)}
        assert mig_cols == model_cols, f"{table}: migration {mig_cols} != model {model_cols}"
    assert {c["name"]: c for c in mig.get_columns("supplies")}["is_active"]["default"] is not None
    assert {c["name"]: c for c in model.get_columns("supplies")}["is_active"]["default"] is not None
