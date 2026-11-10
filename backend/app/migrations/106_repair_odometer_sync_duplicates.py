"""Repair odometer rows duplicated by pre-fix auto-sync date edits (issue #171).

Before the fix, ``sync_odometer_from_record`` looked a source's own row up by
``(vin, date)`` only, so editing a fuel/service/DEF record's date left the
old-date row behind and inserted a second row with the same
``[AUTO-SYNC from <type> #<id>]`` marker. This migration collapses each such
group back to one row:

- The source record still exists (same vin): keep the row whose date matches
  the source's current date (newest id among ties); if none matches, keep the
  newest row and move it to the source's date. Delete the rest.
- The source is gone or belongs to another vin: keep the newest row, delete
  the rest (fuel orphans are already cascade-cleaned by migration 055's FK;
  this covers service/DEF leftovers).

Tire markers are excluded: tire rows are moved and deleted by the tire code
itself and may legitimately repeat the prefix across event kinds.

Not FATAL: this is a data repair. If it fails, the duplicates simply remain
(exactly the pre-migration state) and the app runs; the fixed sync also
self-heals a group the next time its source is edited.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = False

# ``service`` is the legacy pre-rename alias of ``service_visit``: old
# databases hold rows with either spelling for the SAME visit, so grouping is
# by normalized source identity, not by the raw note (codex PR review P1).
_MARKER = re.compile(r"^\[AUTO-SYNC from (fuel|service_visit|service|def) #(\d+)\]$")

_SOURCE_TABLES = {
    "fuel": "fuel_records",
    "service_visit": "service_visits",
    "def": "def_records",
}

_TYPE_ALIASES = {"service": "service_visit"}


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _day(value: object) -> str | None:
    """A DATE column as ``YYYY-MM-DD``: psycopg2 returns date objects, textual
    SQLite returns ISO strings; both stringify to the same first ten chars."""
    return str(value)[:10] if value is not None else None


def upgrade(engine: Engine | None = None) -> None:
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    # Best-effort repair, swallowed on ANY error: the runner stops the pending
    # chain on a raise and never stamps the failed migration, so a raise here
    # would retry 106 on every boot and block every later migration for the
    # sake of a cleanup the fixed sync self-heals anyway (codex PR review P2).
    try:
        _repair(engine)
    except Exception as e:  # noqa: BLE001 — deliberate: cleanup must never block the chain
        print(
            f"⚠ Migration 106 repair skipped ({e.__class__.__name__}: {e}); "
            "duplicates remain and the fixed sync self-heals them on edit"
        )


def _repair(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("odometer_records"):
        return

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, vin, date, notes FROM odometer_records "
                "WHERE notes LIKE '[AUTO-SYNC from %' "
                "AND notes NOT LIKE '[AUTO-SYNC from tire%' "
                "ORDER BY id"
            )
        ).fetchall()

        # Group by normalized SOURCE IDENTITY where the note parses (so the
        # legacy ``service`` alias and the current ``service_visit`` marker
        # for one visit land in ONE group), by raw note otherwise.
        groups: dict[tuple, list] = {}
        identities: dict[tuple, tuple[str, int] | None] = {}
        for row in rows:
            match = _MARKER.match(row.notes)
            if match:
                source_type = _TYPE_ALIASES.get(match.group(1), match.group(1))
                source_id = int(match.group(2))
                key = (row.vin, source_type, source_id)
                identities[key] = (source_type, source_id)
            else:
                key = (row.vin, row.notes)
                identities[key] = None
            groups.setdefault(key, []).append(row)

        repaired = 0
        for key, members in groups.items():
            if len(members) < 2:
                continue
            vin = key[0]
            identity = identities[key]
            source_date: str | None = None
            canonical_notes: str | None = None
            if identity is not None:
                source_type, source_id = identity
                canonical_notes = f"[AUTO-SYNC from {source_type} #{source_id}]"
                table = _SOURCE_TABLES[source_type]
                if inspector.has_table(table):
                    source = conn.execute(
                        text(f"SELECT vin, date FROM {table} WHERE id = :id"),  # noqa: S608
                        {"id": source_id},
                    ).fetchone()
                    if source is not None and source.vin == vin:
                        source_date = _day(source.date)

            matching = [m for m in members if source_date and _day(m.date) == source_date]
            keep = matching[-1] if matching else members[-1]
            if not matching and source_date is not None:
                conn.execute(
                    text("UPDATE odometer_records SET date = :date WHERE id = :id"),
                    {"date": source_date, "id": keep.id},
                )
            if canonical_notes is not None and keep.notes != canonical_notes:
                # Normalize a legacy-alias survivor so the runtime ownership
                # lookup (and a marker-only delete) find it by the current
                # spelling too.
                conn.execute(
                    text("UPDATE odometer_records SET notes = :notes WHERE id = :id"),
                    {"notes": canonical_notes, "id": keep.id},
                )
            drop_ids = [m.id for m in members if m.id != keep.id]
            for drop_id in drop_ids:
                conn.execute(text("DELETE FROM odometer_records WHERE id = :id"), {"id": drop_id})
            repaired += 1
            label = canonical_notes or key[1]
            print(f"✓ Collapsed {len(members)} rows to one for {label} on {vin}")

        if repaired == 0:
            print("✓ No duplicated auto-sync odometer rows found")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 106 is forward-only.")


if __name__ == "__main__":
    upgrade()
