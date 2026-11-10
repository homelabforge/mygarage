"""Migration 101: maintenance rules, reminder anchors, canonical types.

Runs on both dialects through `engine_for_migration`. Every test builds the
pre-101 shape of the tables it touches by hand and seeds the rows from the
production database that motivated the change (Jamey's Mirage: visit 20 on
2026-06-13 at 143063.89 km with "Oil Change" and "Tire Rotation", reminder 4
linked to the oil line item, pack reminders 8/9/10 linked to nothing).

The backfill is a classification, not a merge: the tests assert that no row
is deleted, no status changes, and running twice changes nothing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests.migrations._loader import load_migration

pytestmark = pytest.mark.migrations


def _migration():
    return load_migration("101_maintenance_rules_and_anchors")


def _pre_101_schema(engine, dialect: str) -> None:
    """The tables 101 touches, as a v3.4.0 database has them."""
    pk = "SERIAL PRIMARY KEY" if dialect == "pg" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if dialect == "pg" else "DATETIME"
    now = "NOW()" if dialect == "pg" else "CURRENT_TIMESTAMP"
    statements = [
        "CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, nickname VARCHAR(100))",
        f"""
        CREATE TABLE service_visits (
            id {pk},
            vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
            date DATE NOT NULL,
            odometer_km NUMERIC(10, 2),
            engine_hours NUMERIC(10, 1)
        )
        """,
        f"""
        CREATE TABLE service_line_items (
            id {pk},
            visit_id INTEGER NOT NULL REFERENCES service_visits(id) ON DELETE CASCADE,
            description VARCHAR(200) NOT NULL,
            category VARCHAR(30)
        )
        """,
        f"""
        CREATE TABLE vehicle_reminders (
            id {pk},
            vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
            line_item_id INTEGER REFERENCES service_line_items(id) ON DELETE SET NULL,
            title VARCHAR(200) NOT NULL,
            reminder_type VARCHAR(10) NOT NULL,
            due_date DATE,
            due_mileage_km NUMERIC(10, 2),
            due_hours NUMERIC(10, 1),
            tire_id INTEGER,
            source VARCHAR(20),
            status VARCHAR(10) NOT NULL DEFAULT 'pending',
            notes TEXT,
            last_notified_at {ts},
            created_at {ts} NOT NULL DEFAULT {now},
            updated_at {ts} NOT NULL DEFAULT {now}
        )
        """,
        "CREATE INDEX ix_reminders_vin_status ON vehicle_reminders (vin, status)",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


VIN = "ML32A5HJ9KH009478"


def _seed_mirage(engine) -> None:
    """Rows with explicit ids; on PostgreSQL the SERIAL sequences are then
    moved past them so later inserts without an id do not collide."""
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO vehicles (vin, nickname) VALUES (:vin, 'Mirage')"), {"vin": VIN}
        )
        conn.execute(
            text(
                "INSERT INTO service_visits (id, vin, date, odometer_km) VALUES "
                "(15, :vin, '2026-03-16', 141263.04), (20, :vin, '2026-06-13', 143063.89), "
                "(21, :vin, '2026-06-19', 143302.07)"
            ),
            {"vin": VIN},
        )
        conn.execute(
            text(
                "INSERT INTO service_line_items (id, visit_id, description, category) VALUES "
                "(53, 15, 'Oil Change', 'Maintenance'), "
                "(60, 20, 'Oil Change', 'Maintenance'), "
                "(61, 20, 'Tire Rotation', 'Maintenance'), "
                "(62, 21, 'Tire Replacement', 'Maintenance'), "
                "(63, 21, 'Car Wash', 'Detailing')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO vehicle_reminders "
                "(id, vin, line_item_id, title, reminder_type, due_date, due_mileage_km, status, source) VALUES "
                "(1, :vin, 53, 'Oil Change', 'smart', '2026-06-16', 149309.74, 'done', NULL), "
                "(4, :vin, 60, 'Oil Change', 'smart', '2027-06-13', 150925.52, 'pending', NULL), "
                "(8, :vin, NULL, 'Oil & Filter Change', 'smart', '2027-02-19', 152484.94, 'pending', NULL), "
                "(9, :vin, NULL, 'Inspect Drain Plug Washer', 'date', '2027-02-19', NULL, 'pending', NULL), "
                "(10, :vin, NULL, 'Tire Rotation', 'smart', '2027-02-19', 154484.94, 'pending', NULL), "
                "(11, :vin, NULL, 'Tire tread low (FL)', 'date', '2026-10-01', NULL, 'pending', 'low_tread'), "
                "(12, :vin, NULL, 'Registration renewal', 'date', '2027-01-01', NULL, 'dismissed', NULL)"
            ),
            {"vin": VIN},
        )
        if engine.dialect.name == "postgresql":
            for table in ("service_visits", "service_line_items", "vehicle_reminders"):
                conn.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"(SELECT MAX(id) FROM {table}))"
                    )
                )


def _as_date(value: object) -> date | None:
    """SQLite hands a DATE back as text through raw SQL; PostgreSQL as a date."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _reminder_rows(engine) -> dict[int, dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, status, maintenance_type, anchor_kind, anchor_date, anchor_odometer_km, "
                "anchor_hours, rule_id, due_date, due_mileage_km FROM vehicle_reminders ORDER BY id"
            )
        ).mappings()
        result = {}
        for r in rows:
            row = dict(r)
            row["anchor_date"] = _as_date(row["anchor_date"])
            row["due_date"] = _as_date(row["due_date"])
            result[int(row["id"])] = row
        return result


def _line_item_types(engine) -> dict[int, str | None]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, maintenance_type FROM service_line_items ORDER BY id")
        ).fetchall()
        return {int(i): t for i, t in rows}


class TestSchema:
    def test_adds_table_columns_and_indexes(self, engine_for_migration):
        dialect, engine, _url = engine_for_migration
        _pre_101_schema(engine, dialect)
        _migration().upgrade(engine)

        insp = inspect(engine)
        assert insp.has_table("vehicle_maintenance_rules")
        rule_cols = {c["name"] for c in insp.get_columns("vehicle_maintenance_rules")}
        assert {
            "id",
            "vin",
            "maintenance_type",
            "title",
            "interval_km",
            "interval_months",
            "interval_days",
            "interval_hours",
            "source",
            "source_pack_id",
            "source_pack_key",
            "notes",
            "is_active",
            "created_at",
            "updated_at",
        } <= rule_cols
        assert "ix_maintenance_rules_vin_type" in {
            ix["name"] for ix in insp.get_indexes("vehicle_maintenance_rules")
        }

        li_cols = {c["name"] for c in insp.get_columns("service_line_items")}
        assert "maintenance_type" in li_cols

        reminder_cols = {c["name"]: c for c in insp.get_columns("vehicle_reminders")}
        for name, _sqlite, _pg in _migration().REMINDER_COLUMNS:
            assert name in reminder_cols, name
            assert reminder_cols[name]["nullable"] is True, name
        indexes = {ix["name"]: ix for ix in insp.get_indexes("vehicle_reminders")}
        assert indexes["uq_reminders_rule_pending"]["unique"]
        assert indexes["uq_reminders_rule_pending"]["column_names"] == ["rule_id"]

        fks = {
            (tuple(fk["constrained_columns"]), fk["referred_table"])
            for fk in insp.get_foreign_keys("vehicle_reminders")
        }
        assert (("rule_id",), "vehicle_maintenance_rules") in fks
        assert (("completed_line_item_id",), "service_line_items") in fks
        assert (("superseded_by_id",), "vehicle_reminders") in fks

    def test_is_fatal(self):
        assert _migration().FATAL is True

    def test_missing_tables_skip(self, engine_for_migration):
        _dialect, engine, _url = engine_for_migration
        _migration().upgrade(engine)  # no vehicles table at all: nothing to do
        assert not inspect(engine).has_table("vehicle_maintenance_rules")


class TestBackfill:
    def test_classifies_line_items_conservatively(self, engine_for_migration):
        dialect, engine, _url = engine_for_migration
        _pre_101_schema(engine, dialect)
        _seed_mirage(engine)
        _migration().upgrade(engine)
        assert _line_item_types(engine) == {
            53: "engine_oil_filter",
            60: "engine_oil_filter",
            61: "tire_rotation",
            62: "tire_replacement",
            63: None,
        }

    def test_types_and_anchors_reminders_without_touching_status(self, engine_for_migration):
        dialect, engine, _url = engine_for_migration
        _pre_101_schema(engine, dialect)
        _seed_mirage(engine)
        _migration().upgrade(engine)
        rows = _reminder_rows(engine)

        assert set(rows) == {1, 4, 8, 9, 10, 11, 12}
        assert {i: r["status"] for i, r in rows.items()} == {
            1: "done",
            4: "pending",
            8: "pending",
            9: "pending",
            10: "pending",
            11: "pending",
            12: "dismissed",
        }
        # Linked reminders take the line item's type and the visit as anchor.
        assert rows[4]["maintenance_type"] == "engine_oil_filter"
        assert rows[4]["anchor_kind"] == "service"
        assert rows[4]["anchor_date"] == date(2026, 6, 13)
        assert Decimal(str(rows[4]["anchor_odometer_km"])) == Decimal("143063.89")
        assert rows[1]["anchor_kind"] == "service"
        assert rows[1]["anchor_date"] == date(2026, 3, 16)
        # Loose reminders are typed from their title, with no anchor invented.
        assert rows[8]["maintenance_type"] == "engine_oil_filter"
        assert rows[8]["anchor_kind"] is None
        assert rows[9]["maintenance_type"] == "drain_plug_washer"
        assert rows[10]["maintenance_type"] == "tire_rotation"
        assert rows[12]["maintenance_type"] is None
        # Tire-sourced reminders are identified by tire, never by type.
        assert rows[11]["maintenance_type"] is None
        assert rows[11]["anchor_kind"] is None
        # Thresholds are untouched: the migration classifies, it does not recompute.
        assert rows[4]["due_date"] == date(2027, 6, 13)
        assert Decimal(str(rows[4]["due_mileage_km"])) == Decimal("150925.52")
        assert all(r["rule_id"] is None for r in rows.values())

    def test_running_twice_changes_nothing_and_respects_hand_set_types(self, engine_for_migration):
        dialect, engine, _url = engine_for_migration
        _pre_101_schema(engine, dialect)
        _seed_mirage(engine)
        mod = _migration()
        mod.upgrade(engine)
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE service_line_items SET maintenance_type = 'custom_wash' WHERE id = 63")
            )
            conn.execute(
                text("UPDATE vehicle_reminders SET maintenance_type = 'registration' WHERE id = 12")
            )
        before_items = _line_item_types(engine)
        before_reminders = _reminder_rows(engine)
        mod.upgrade(engine)
        assert _line_item_types(engine) == before_items
        assert _reminder_rows(engine) == before_reminders
        assert before_items[63] == "custom_wash"
        assert before_reminders[12]["maintenance_type"] == "registration"


class TestConstraints:
    def test_one_pending_reminder_per_rule(self, engine_for_migration):
        dialect, engine, _url = engine_for_migration
        _pre_101_schema(engine, dialect)
        _seed_mirage(engine)
        _migration().upgrade(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO vehicle_maintenance_rules (vin, maintenance_type, title, interval_km, source) "
                    "VALUES (:vin, 'engine_oil_filter', 'Oil', 8000, 'pack')"
                ),
                {"vin": VIN},
            )
            rule_id = conn.execute(text("SELECT MAX(id) FROM vehicle_maintenance_rules")).scalar()
            # Many done rows and many NULL-rule pending rows are fine.
            conn.execute(
                text("UPDATE vehicle_reminders SET rule_id = :r WHERE id IN (1, 4)"),
                {"r": rule_id},
            )
            conn.execute(
                text(
                    "INSERT INTO vehicle_reminders (vin, title, reminder_type, status, rule_id) VALUES "
                    "(:vin, 'old one', 'date', 'done', :r), (:vin, 'older one', 'date', 'dismissed', :r)"
                ),
                {"vin": VIN, "r": rule_id},
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE vehicle_reminders SET rule_id = :r WHERE id = 8"), {"r": rule_id}
                )
        with engine.connect() as conn:
            pending = conn.execute(
                text(
                    "SELECT COUNT(*) FROM vehicle_reminders WHERE rule_id = :r AND status = 'pending'"
                ),
                {"r": rule_id},
            ).scalar()
            assert pending == 1

    def test_rule_delete_sets_reminder_rule_null_with_fks_enforced(self, engine_for_migration):
        dialect, engine, _url = engine_for_migration
        _pre_101_schema(engine, dialect)
        _seed_mirage(engine)
        _migration().upgrade(engine)
        with engine.begin() as conn:
            if dialect == "sqlite":
                conn.execute(text("PRAGMA foreign_keys = ON"))
                assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            conn.execute(
                text(
                    "INSERT INTO vehicle_maintenance_rules (vin, maintenance_type, title, interval_km, source) "
                    "VALUES (:vin, 'engine_oil_filter', 'Oil', 8000, 'pack')"
                ),
                {"vin": VIN},
            )
            rule_id = conn.execute(text("SELECT MAX(id) FROM vehicle_maintenance_rules")).scalar()
            conn.execute(
                text(
                    "UPDATE vehicle_reminders SET rule_id = :r, completed_line_item_id = 60, "
                    "superseded_by_id = 8 WHERE id = 4"
                ),
                {"r": rule_id},
            )
            conn.execute(
                text("DELETE FROM vehicle_maintenance_rules WHERE id = :r"), {"r": rule_id}
            )
            conn.execute(text("DELETE FROM service_line_items WHERE id = 60"))
            conn.execute(text("DELETE FROM vehicle_reminders WHERE id = 8"))
        rows = _reminder_rows(engine)
        assert rows[4]["rule_id"] is None
        with engine.connect() as conn:
            completed, superseded = conn.execute(
                text(
                    "SELECT completed_line_item_id, superseded_by_id FROM vehicle_reminders WHERE id = 4"
                )
            ).one()
        assert completed is None
        assert superseded is None
