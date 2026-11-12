"""Tests for migration 061 — backfill-normalize existing vehicle fuel types.

Why the migration exists: Task 1 (commit 1c66f27) added a normalizing
validator on VehicleCreate/VehicleUpdate, but legacy rows written before
that validator existed may still carry mixed-case values ("Diesel") or
aliases ("Gas") in `vehicles.fuel_type` / `vehicles.fuel_type_secondary`.
This migration normalizes those in place via the same
`normalize_fuel_type()` vocabulary, leaving unrecognized values untouched.

Runs on SQLite and PostgreSQL via ``engine_for_migration``.
"""

from sqlalchemy import text

from tests.migrations._loader import load_migration

MIGRATION = "061_normalize_vehicle_fuel_types"


def _create_vehicles_table(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE vehicles ("
                "vin VARCHAR(17) PRIMARY KEY, "
                "fuel_type VARCHAR(50), "
                "fuel_type_secondary VARCHAR(20)"
                ")"
            )
        )


def _seed_vehicles(engine) -> None:
    rows = [
        # (vin, fuel_type, fuel_type_secondary)
        ("VIN0000000000001", "Diesel", "Gas"),  # mixed-case + alias -> both normalize
        ("VIN0000000000002", "unknown-slime", "unknown-slime"),  # unrecognized -> untouched
        ("VIN0000000000003", None, None),  # NULL -> untouched
        ("VIN0000000000004", "gasoline", "diesel"),  # already-canonical -> untouched
        ("VIN0000000000005", "", ""),  # empty string -> untouched
    ]
    with engine.begin() as conn:
        for vin, fuel_type, fuel_type_secondary in rows:
            conn.execute(
                text(
                    "INSERT INTO vehicles (vin, fuel_type, fuel_type_secondary) "
                    "VALUES (:vin, :fuel_type, :fuel_type_secondary)"
                ),
                {"vin": vin, "fuel_type": fuel_type, "fuel_type_secondary": fuel_type_secondary},
            )


def _fetch(engine) -> dict[str, tuple[str | None, str | None]]:
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT vin, fuel_type, fuel_type_secondary FROM vehicles ORDER BY vin")
        ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def test_normalizes_mixed_case_and_aliases(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _create_vehicles_table(engine)
    _seed_vehicles(engine)

    load_migration(MIGRATION).upgrade(engine=engine)

    result = _fetch(engine)
    assert result["VIN0000000000001"] == ("diesel", "gasoline")


def test_unrecognized_values_left_untouched(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _create_vehicles_table(engine)
    _seed_vehicles(engine)

    load_migration(MIGRATION).upgrade(engine=engine)

    result = _fetch(engine)
    assert result["VIN0000000000002"] == ("unknown-slime", "unknown-slime")


def test_null_values_left_untouched(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _create_vehicles_table(engine)
    _seed_vehicles(engine)

    load_migration(MIGRATION).upgrade(engine=engine)

    result = _fetch(engine)
    assert result["VIN0000000000003"] == (None, None)


def test_already_canonical_values_left_untouched(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _create_vehicles_table(engine)
    _seed_vehicles(engine)

    load_migration(MIGRATION).upgrade(engine=engine)

    result = _fetch(engine)
    assert result["VIN0000000000004"] == ("gasoline", "diesel")


def test_empty_string_left_untouched(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _create_vehicles_table(engine)
    _seed_vehicles(engine)

    load_migration(MIGRATION).upgrade(engine=engine)

    result = _fetch(engine)
    assert result["VIN0000000000005"] == ("", "")


def test_idempotent_on_double_run(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _create_vehicles_table(engine)
    _seed_vehicles(engine)
    migration = load_migration(MIGRATION)

    migration.upgrade(engine=engine)
    first_pass = _fetch(engine)
    migration.upgrade(engine=engine)  # must not raise, must not change anything
    second_pass = _fetch(engine)

    assert first_pass == second_pass


def test_noop_when_vehicles_table_absent(engine_for_migration):
    """A fresh test DB with no `vehicles` table yet must not raise."""
    _dialect, engine, _url = engine_for_migration

    load_migration(MIGRATION).upgrade(engine=engine)  # must not raise
