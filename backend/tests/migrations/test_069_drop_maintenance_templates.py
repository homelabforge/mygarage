"""Migration 069 — drop the retired maintenance_templates table (guarded)."""

from sqlalchemy import inspect, text

from tests.migrations._loader import load_migration

MIGRATION = "069_drop_maintenance_templates"


def _create(engine):
    with engine.begin() as conn:
        conn.execute(
            text('CREATE TABLE "maintenance_templates" (id INTEGER PRIMARY KEY, vin VARCHAR)')
        )


def test_drops_empty_table(engine_for_migration):
    _d, engine, _u = engine_for_migration
    _create(engine)
    load_migration(MIGRATION).upgrade(engine=engine)
    assert not inspect(engine).has_table("maintenance_templates")


def test_absent_is_noop(engine_for_migration):
    _d, engine, _u = engine_for_migration
    load_migration(MIGRATION).upgrade(engine=engine)  # must not raise
    assert not inspect(engine).has_table("maintenance_templates")


def test_populated_is_preserved(engine_for_migration):
    _d, engine, _u = engine_for_migration
    _create(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO \"maintenance_templates\" (id, vin) VALUES (1, 'X')"))
    load_migration(MIGRATION).upgrade(engine=engine)
    assert inspect(engine).has_table("maintenance_templates"), "populated table must be preserved"
