"""Add ``livelink_devices.preset_key``: which preset created this device.

The integrations card names a preset-backed tab from its preset. Matching the
device ``label`` against a preset ``title`` at runtime would work today and
break the first time someone renames a device to something friendlier, so the
attribution is stored once instead of re-derived forever.

FATAL = True, like every other add-column migration here (096 and 112 both add
columns to this same table). ``create_all`` never ALTERs an existing table, so
a silent skip leaves the ORM SELECTing ``preset_key`` against a database that
has no such column, which breaks device management and all ingestion.

Two backfills ride along, because fixing the write paths cannot reach rows that
already exist:

1. ``preset_key`` for any generic_mqtt device whose label still equals a known
   preset title. This is the label-matching heuristic rejected for runtime use,
   applied once at migration time where it is safe: the branch is unreleased,
   so nobody can have renamed anything yet.
2. A ``livelink_parameters`` row for every topic map that has none. Mappings
   made through ``create_topic_map`` never registered a parameter, so the
   card's show-on-dashboard switch would PUT into a 404.

Preset titles are inlined rather than imported from ``app.services...presets``,
per the convention migration 096 states: a migration must keep working when the
live helper it would have imported has moved on.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_TABLE = "livelink_devices"
_COLUMN = "preset_key"

#: Inlined on purpose. See the module docstring.
_PRESET_TITLES = {"Mopeka propane (2 tanks)": "mopeka_two_tank"}


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _add_column(engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table(_TABLE):
        print(f"  → {_TABLE} missing; skip (run the earlier migrations first)")
        return

    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        print(f"✓ {_TABLE}.{_COLUMN} already present")
        return

    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} VARCHAR(50)"))
        print(f"✓ Added {_TABLE}.{_COLUMN}")


def _backfill_preset_key(engine) -> None:
    if not inspect(engine).has_table(_TABLE):
        return
    with engine.begin() as conn:
        for title, key in _PRESET_TITLES.items():
            result = conn.execute(
                text(
                    f"UPDATE {_TABLE} SET {_COLUMN} = :key "
                    f"WHERE label = :title AND kind = 'generic_mqtt' AND {_COLUMN} IS NULL"
                ),
                {"key": key, "title": title},
            )
            if result.rowcount:
                print(f"✓ Attributed {result.rowcount} device(s) to preset {key}")


def _backfill_parameters(engine) -> None:
    """Register a parameter for every mapped telemetry key that lacks one."""
    inspector = inspect(engine)
    if not (
        inspector.has_table("livelink_topic_maps") and inspector.has_table("livelink_parameters")
    ):
        return

    with engine.begin() as conn:
        # GROUP BY param_key, not DISTINCT on the triple: livelink_topic_maps
        # is only UNIQUE(topic, param_key) (app/models/livelink_topic_map.py),
        # so two rows can share one param_key under different topics with
        # different unit/param_class -- exactly the rows create_topic_map never
        # registered a parameter for. livelink_parameters.param_key is globally
        # unique, so a DISTINCT triple would issue two INSERTs for one key and
        # the second raises IntegrityError, rolling back the whole migration
        # (FATAL=True), which refuses to boot. MIN() picks a representative
        # unit/param_class deterministically on both SQLite and Postgres; when
        # two mappings disagree, one wins arbitrarily, mirroring
        # auto_register_parameter keeping whatever was registered first.
        orphans = conn.execute(
            text(
                "SELECT m.param_key, MIN(m.unit), MIN(m.param_class) "
                "FROM livelink_topic_maps m "
                "LEFT JOIN livelink_parameters p ON p.param_key = m.param_key "
                "WHERE m.role = 'telemetry' "
                "  AND m.param_key IS NOT NULL "
                "  AND p.param_key IS NULL "
                "GROUP BY m.param_key"
            )
        ).all()

        for param_key, unit, param_class in orphans:
            # Mirrors TelemetryService.auto_register_parameter's defaults AS
            # THEY WERE when this migration was written. Kept literal rather than
            # imported, per the inlining convention above. Migration 114 then
            # resets show_on_dashboard to TRUE on every row, so the FALSE this
            # writes for a diagnostic class does not survive a full upgrade.
            show = param_class in (
                "speed",
                "frequency",
                "temperature",
                "voltage",
                "battery",
                "propane",
            )
            conn.execute(
                text(
                    "INSERT INTO livelink_parameters "
                    "(param_key, display_name, unit, param_class, category, "
                    " show_on_dashboard, archive_only, storage_interval_seconds) "
                    "VALUES (:k, :d, :u, :c, 'other', :show, :archive, 0)"
                ),
                {
                    "k": param_key,
                    "d": param_key.replace("_", " ").title(),
                    "u": unit,
                    "c": param_class,
                    "show": show,
                    "archive": not show,
                },
            )
        if orphans:
            print(f"✓ Registered {len(orphans)} parameter(s) for existing mappings")


def upgrade(engine: Engine | None = None) -> None:
    """Add the column, then backfill preset attribution and parameters."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    _add_column(engine)
    _backfill_preset_key(engine)
    _backfill_parameters(engine)


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 113 is forward-only.")


if __name__ == "__main__":
    upgrade()
