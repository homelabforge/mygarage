"""Tests for migration 109 - the tables that hold user-saved reminder packs.

Additive only, so most of the risk is not in the data (there is none to move)
but in the ORDERING: `metadata.create_all` runs BEFORE migrations, so these
tables may already exist, may not, or may exist as only one of the two after an
interrupted run. All four states are exercised here, on both dialects.
"""

import pytest
from sqlalchemy import inspect, text

from tests.migrations._loader import load_migration

PACKS = "reminder_packs"
ITEMS = "reminder_pack_items"


def _load():
    return load_migration("109_user_defined_reminder_packs")


def _make_users(engine) -> None:
    """The one table 109 references. Nothing else is needed: 109 touches no
    existing table, which is the whole reason it is not FATAL."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50))"))


@pytest.mark.migrations
class TestMigration109:
    def test_it_creates_both_tables(self, engine_for_migration):
        _dialect, engine, _url = engine_for_migration
        _make_users(engine)

        _load().upgrade(engine)

        inspector = inspect(engine)
        assert inspector.has_table(PACKS)
        assert inspector.has_table(ITEMS)
        columns = {c["name"] for c in inspector.get_columns(PACKS)}
        assert {"pack_id", "name", "description", "vehicle_types", "created_by_user_id"} <= columns
        item_columns = {c["name"] for c in inspector.get_columns(ITEMS)}
        assert {
            "item_key",
            "title",
            "maintenance_type",
            "interval_km",
            "interval_months",
            "interval_days",
            "interval_hours",
            "notes",
            "sort_order",
        } <= item_columns

    def test_running_it_twice_changes_nothing(self, engine_for_migration):
        _dialect, engine, _url = engine_for_migration
        _make_users(engine)
        module = _load()

        module.upgrade(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {PACKS} (pack_id, name, description, vehicle_types) "
                    "VALUES ('custom-a', 'A', '', '[]')"
                )
            )
        module.upgrade(engine)

        with engine.connect() as conn:
            rows = conn.execute(text(f"SELECT pack_id FROM {PACKS}")).scalars().all()
        assert rows == ["custom-a"], "the second run must not drop or duplicate anything"

    def test_it_finishes_a_half_created_schema(self, engine_for_migration):
        """`create_all` may have made one table and not the other, and an
        interrupted earlier run leaves the same shape. Keying re-entrancy on
        "both present" rather than "either present" is what covers it."""
        _dialect, engine, _url = engine_for_migration
        _make_users(engine)
        module = _load()
        with engine.begin() as conn:
            conn.execute(text(module._packs_ddl("INTEGER PRIMARY KEY", "TIMESTAMP")))

        module.upgrade(engine)

        assert inspect(engine).has_table(ITEMS)

    def test_it_skips_cleanly_without_users(self, engine_for_migration):
        """No `users` table means the earlier migrations have not run. Skipping
        beats failing: 109 is not FATAL, and a raise here would stop the whole
        pending chain without stamping."""
        _dialect, engine, _url = engine_for_migration

        _load().upgrade(engine)

        assert not inspect(engine).has_table(PACKS)

    def test_an_item_needs_an_interval(self, engine_for_migration):
        """The CHECK mirrors `vehicle_maintenance_rules`: the table must not be
        able to hold what `ReminderPackItem` refuses."""
        _dialect, engine, _url = engine_for_migration
        _make_users(engine)
        _load().upgrade(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {PACKS} (id, pack_id, name, description, vehicle_types) "
                    "VALUES (1, 'custom-a', 'A', '', '[]')"
                )
            )

        with pytest.raises(Exception):  # noqa: B017 - dialects raise different types
            with engine.begin() as conn:
                conn.execute(
                    text(f"INSERT INTO {ITEMS} (pack_id, item_key, title) VALUES (1, 'oil', 'Oil')")
                )

    def test_an_item_cannot_mix_distance_and_hours(self, engine_for_migration):
        """The rule table leaves this to its request schema; here both ends are
        ours, so the database holds the line."""
        _dialect, engine, _url = engine_for_migration
        _make_users(engine)
        _load().upgrade(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {PACKS} (id, pack_id, name, description, vehicle_types) "
                    "VALUES (1, 'custom-a', 'A', '', '[]')"
                )
            )

        with pytest.raises(Exception):  # noqa: B017 - dialects raise different types
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"INSERT INTO {ITEMS} "
                        "(pack_id, item_key, title, interval_km, interval_hours) "
                        "VALUES (1, 'oil', 'Oil', 8000, 100)"
                    )
                )

    def test_two_items_cannot_share_a_key_in_one_pack(self, engine_for_migration):
        _dialect, engine, _url = engine_for_migration
        _make_users(engine)
        _load().upgrade(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {PACKS} (id, pack_id, name, description, vehicle_types) "
                    "VALUES (1, 'custom-a', 'A', '', '[]')"
                )
            )
            conn.execute(
                text(
                    f"INSERT INTO {ITEMS} (pack_id, item_key, title, interval_months) "
                    "VALUES (1, 'oil', 'Oil', 6)"
                )
            )

        with pytest.raises(Exception):  # noqa: B017 - dialects raise different types
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"INSERT INTO {ITEMS} (pack_id, item_key, title, interval_months) "
                        "VALUES (1, 'oil', 'Oil again', 12)"
                    )
                )

    def test_two_packs_cannot_share_an_id(self, engine_for_migration):
        _dialect, engine, _url = engine_for_migration
        _make_users(engine)
        _load().upgrade(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {PACKS} (pack_id, name, description, vehicle_types) "
                    "VALUES ('custom-a', 'A', '', '[]')"
                )
            )

        with pytest.raises(Exception):  # noqa: B017 - dialects raise different types
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"INSERT INTO {PACKS} (pack_id, name, description, vehicle_types) "
                        "VALUES ('custom-a', 'Different name', '', '[]')"
                    )
                )
