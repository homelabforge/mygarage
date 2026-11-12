"""Migration 100: tires.storage_location.

FATAL for migration 099's reason: the Tire ORM maps the column, so a silent
skip would 500 every tire read. Parameterised over SQLite and PostgreSQL via
`engine_for_migration`.
"""

from sqlalchemy import String, inspect, text

from tests.migrations._loader import load_migration


def _make_tires_table(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE tires (
                    id INTEGER PRIMARY KEY,
                    vin VARCHAR(17) NOT NULL,
                    notes TEXT
                )
                """
            )
        )
        conn.execute(text("INSERT INTO tires (id, vin) VALUES (1, 'V')"))


def test_100_adds_the_column(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tires_table(engine)
    load_migration("100_add_tire_storage_location").upgrade(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("tires")}
    assert "storage_location" in cols
    assert cols["storage_location"]["nullable"] is True
    # The model, the five schemas and the OpenAPI contract all cap it at 120.
    # Pinned on both dialects: SQLite reflects the declared VARCHAR(120) and
    # PostgreSQL enforces it, and a regression to TEXT passes neither.
    column_type = cols["storage_location"]["type"]
    assert isinstance(column_type, String), column_type
    assert column_type.length == 120


def test_100_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tires_table(engine)
    mod = load_migration("100_add_tire_storage_location")
    mod.upgrade(engine)
    mod.upgrade(engine)
    cols = [c["name"] for c in inspect(engine).get_columns("tires")]
    assert cols.count("storage_location") == 1


def test_100_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    load_migration("100_add_tire_storage_location").upgrade(engine)


def test_100_leaves_existing_rows_null(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tires_table(engine)
    load_migration("100_add_tire_storage_location").upgrade(engine)
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT storage_location FROM tires WHERE id = 1")).scalar() is None
        )


def test_100_is_fatal():
    assert load_migration("100_add_tire_storage_location").FATAL is True
