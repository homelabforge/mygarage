"""Turn each vehicle's free-text coverage limits into standard coverage rows.

Migration 107 made a policy a household record but left every vehicle's actual
coverage in one `insurance_policy_vehicles.coverage_limits` text box, where the
label and the amount run together ("Comprehensive Actual Cash Value $995") and
nothing can be totalled, sorted or corrected field by field. This replaces it
with `insurance_coverages`: one row per coverage from the catalogue in
`app.utils.insurance_coverages`, carrying its limits, deductible and premium.

FATAL, because the ORM no longer maps `coverage_limits`.

WHERE EACH LINE GOES, decided by the same parser the PDF import uses:

1. a line the catalogue recognises -> an `insurance_coverages` row
2. a leftover that splits into a label and an amount -> a named field on that
   vehicle, appended after any it already has
3. anything else, including a leftover too long for the named-field columns
   -> appended to that vehicle's notes, verbatim

A line is only read as a coverage when the read is unambiguous: one that says
a coverage is NOT carried, or that names a second coverage, is kept whole
under (3) rather than guessed at.

What this does NOT keep is prose trailing a line that WAS read as a coverage
("Collision $500 deductible, waived for hit-and-run" keeps the $500 and drops
the condition). The conversion is best-effort on free text, which is why the
release notes and the wiki both say to open each policy once afterwards.
"""

import os
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, inspect, text

from app.utils.insurance_coverages import coverage_row, parse_coverage_lines, place_leftovers

FATAL = True


# ============================================================================
#  The conversion (pure: no engine, no ORM, no dialect)
# ============================================================================


def plan_conversion(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Work out what each link's coverage text becomes.

    `links` carries `id`, `policy_id`, `coverage_limits`, `notes` and
    `next_sort_order` (one past that vehicle's highest existing named field, so
    converted lines land after the fields the user typed rather than among
    them). Links whose text is empty are left out of the result entirely.
    """
    planned = []
    for link in links:
        parse = parse_coverage_lines(link.get("coverage_limits"))
        if not (parse.coverages or parse.fields or parse.notes):
            continue
        converted_fields, kept_prose = place_leftovers(parse)

        notes = link.get("notes") or ""
        if kept_prose:
            notes = "\n".join(filter(None, [notes.rstrip(), *kept_prose]))

        planned.append(
            {
                "id": link["id"],
                "policy_id": link["policy_id"],
                "coverages": [coverage_row(item) for item in parse.coverages],
                "fields": [
                    {
                        "label": label,
                        "value": value,
                        "sort_order": link.get("next_sort_order", 0) + offset,
                    }
                    for offset, (label, value) in enumerate(converted_fields)
                ],
                "notes": notes or None,
                "notes_changed": bool(kept_prose),
            }
        )
    return planned


# ============================================================================
#  DDL
# ============================================================================


def _coverages_ddl(serial: str) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS insurance_coverages (
            id {serial},
            policy_vehicle_id INTEGER NOT NULL
                REFERENCES insurance_policy_vehicles(id) ON DELETE CASCADE,
            coverage_key VARCHAR(40) NOT NULL,
            limit_primary NUMERIC(12, 2),
            limit_secondary NUMERIC(12, 2),
            deductible NUMERIC(10, 2),
            premium NUMERIC(10, 2),
            CONSTRAINT uq_insurance_coverage UNIQUE (policy_vehicle_id, coverage_key)
        )
    """


#: `insurance_policy_vehicles` minus `coverage_limits`, for the SQLite rebuild.
#: Kept identical to migration 107's version in every other respect, so a
#: migrated database and a `create_all` one still reflect the same.
_LINKS_DDL_WITHOUT_TEXT = """
    CREATE TABLE insurance_policy_vehicles_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_id INTEGER NOT NULL REFERENCES insurance_policies(id) ON DELETE CASCADE,
        vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
        policy_type VARCHAR(30) NOT NULL,
        premium_share NUMERIC(10, 2),
        deductible NUMERIC(10, 2),
        notes TEXT,
        effective_to DATE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_insurance_policy_vehicle UNIQUE (policy_id, vin),
        CONSTRAINT check_policy_vehicle_type CHECK (policy_type IN
            ('Liability', 'Comprehensive', 'Collision', 'Full Coverage', 'Minimum', 'Other'))
    )
"""

_LINK_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_insurance_policy_vehicles_vin "
    "ON insurance_policy_vehicles (vin)",
    "CREATE INDEX IF NOT EXISTS idx_insurance_policy_vehicles_policy "
    "ON insurance_policy_vehicles (policy_id)",
)

_READ_LINKS = """
    SELECT l.id AS id, l.policy_id AS policy_id, l.coverage_limits AS coverage_limits,
           l.notes AS notes,
           COALESCE((SELECT MAX(f.sort_order) + 1 FROM insurance_policy_fields f
                     WHERE f.policy_vehicle_id = l.id), 0) AS next_sort_order
    FROM insurance_policy_vehicles l
    WHERE l.coverage_limits IS NOT NULL AND TRIM(l.coverage_limits) <> ''
    ORDER BY l.id
"""

#: One statement per operation, in named binds, which `sqlalchemy.text()` and
#: the raw `sqlite3` cursor both accept. Rendering a second positional variant
#: would mean a reordered column list still worked on PostgreSQL while SQLite
#: silently wrote one column into another, in a FATAL forward-only migration.
_INSERT_COVERAGE = (
    "INSERT INTO insurance_coverages (policy_vehicle_id, coverage_key, limit_primary, "
    "limit_secondary, deductible, premium) VALUES (:link_id, :coverage_key, :limit_primary, "
    ":limit_secondary, :deductible, :premium)"
)
_INSERT_FIELD = (
    "INSERT INTO insurance_policy_fields (policy_id, policy_vehicle_id, label, value, "
    "sort_order) VALUES (:policy_id, :link_id, :label, :value, :sort_order)"
)
_UPDATE_NOTES = "UPDATE insurance_policy_vehicles SET notes = :notes WHERE id = :id"


def _num(value: Any) -> Any:
    """SQLite's DB-API cannot bind a Decimal; its NUMERIC affinity takes a str."""
    return None if value is None else str(value)


def _report(planned: list[dict[str, Any]]) -> None:
    coverages = sum(len(p["coverages"]) for p in planned)
    fields = sum(len(p["fields"]) for p in planned)
    notes = sum(1 for p in planned if p["notes_changed"])
    print(
        f"  → 108: {len(planned)} vehicle(s) converted: {coverages} standard coverage(s), "
        f"{fields} named field(s), {notes} kept lines in notes"
    )


# ============================================================================
#  SQLite
# ============================================================================


def _run_sqlite(engine: Engine) -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("PRAGMA foreign_keys = OFF")
        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 0:
            raise RuntimeError(
                f"PRAGMA foreign_keys = OFF failed; got {fk_state}. Are we inside an "
                "active transaction? Proceeding would let the link rebuild cascade "
                "every coverage and named field away."
            )
        try:
            cur.execute("BEGIN")

            columns = ("id", "policy_id", "coverage_limits", "notes", "next_sort_order")
            rows: list[dict[str, Any]] = [
                dict(zip(columns, r, strict=True)) for r in cur.execute(_READ_LINKS).fetchall()
            ]
            planned = plan_conversion(rows)

            cur.execute(_coverages_ddl("INTEGER PRIMARY KEY AUTOINCREMENT"))
            for link in planned:
                for coverage in link["coverages"]:
                    cur.execute(
                        _INSERT_COVERAGE,
                        # SQLite's DB-API cannot bind a Decimal; PostgreSQL can,
                        # so only this path stringifies.
                        {
                            "link_id": link["id"],
                            **{
                                k: _num(v) if k != "coverage_key" else v
                                for k, v in coverage.items()
                            },
                        },
                    )
                for item in link["fields"]:
                    cur.execute(
                        _INSERT_FIELD,
                        {"policy_id": link["policy_id"], "link_id": link["id"], **item},
                    )
                if link["notes_changed"]:
                    cur.execute(_UPDATE_NOTES, {"notes": link["notes"], "id": link["id"]})

            # Drop the text column the SQLite way: rebuild, keeping every id,
            # because the coverages and named fields just written point at them.
            cur.execute("DROP TABLE IF EXISTS insurance_policy_vehicles_new")
            cur.execute(_LINKS_DDL_WITHOUT_TEXT)
            cur.execute(
                "INSERT INTO insurance_policy_vehicles_new (id, policy_id, vin, policy_type, "
                "premium_share, deductible, notes, effective_to, created_at) "
                "SELECT id, policy_id, vin, policy_type, premium_share, deductible, notes, "
                "effective_to, created_at FROM insurance_policy_vehicles"
            )
            cur.execute("DROP TABLE insurance_policy_vehicles")
            cur.execute(
                "ALTER TABLE insurance_policy_vehicles_new RENAME TO insurance_policy_vehicles"
            )
            for ddl in _LINK_INDEXES:
                cur.execute(ddl)

            violations = cur.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(
                    f"FK violations after the coverage rebuild (pre-commit): {violations!r}"
                )
            cur.execute("COMMIT")
            _report(planned)
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys = ON")

        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 1:
            raise RuntimeError(f"PRAGMA foreign_keys = ON failed; got {fk_state}.")
    finally:
        raw.close()


# ============================================================================
#  PostgreSQL
# ============================================================================


def _run_postgres(engine: Engine) -> None:
    with engine.begin() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text(_READ_LINKS)).fetchall()]
        planned = plan_conversion(rows)

        conn.execute(text(_coverages_ddl("SERIAL PRIMARY KEY")))
        for link in planned:
            for coverage in link["coverages"]:
                conn.execute(text(_INSERT_COVERAGE), {"link_id": link["id"], **coverage})
            for item in link["fields"]:
                conn.execute(
                    text(_INSERT_FIELD),
                    {"policy_id": link["policy_id"], "link_id": link["id"], **item},
                )
            if link["notes_changed"]:
                conn.execute(text(_UPDATE_NOTES), {"notes": link["notes"], "id": link["id"]})

        conn.execute(
            text("ALTER TABLE insurance_policy_vehicles DROP COLUMN IF EXISTS coverage_limits")
        )
        _report(planned)


# ============================================================================
#  Entry point
# ============================================================================


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _preflight_backup_marker() -> None:
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    backups = data_dir / "backups"
    if not backups.is_dir() or not any(backups.iterdir()):
        print(
            f"  → 108: WARNING — no backup found in {backups}. This migration cannot be "
            "reversed: it drops insurance_policy_vehicles.coverage_limits. Take one now "
            "(POST /api/backup/create-full) if you have not."
        )


def upgrade(engine: Engine | None = None) -> None:
    """Run the migration, or return cleanly if it has already been applied.

    RE-ENTRANCY keys on the column this migration REMOVES. Keying on
    `insurance_coverages` existing would be wrong: `create_all` builds it from
    the ORM before migrations run, so it is already there on a database that
    has converted nothing, and a fresh `create_all` database never had
    `coverage_limits` to convert.
    """
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    inspector = inspect(engine)
    if not inspector.has_table("insurance_policy_vehicles"):
        print("  → insurance_policy_vehicles missing; skip (run migration 107 first)")
        return

    columns = {c["name"] for c in inspector.get_columns("insurance_policy_vehicles")}
    if "coverage_limits" not in columns:
        print("  → 108 already applied (coverage_limits gone); nothing to do")
        return

    _preflight_backup_marker()

    if engine.dialect.name == "postgresql":
        _run_postgres(engine)
    else:
        _run_sqlite(engine)


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 108 is forward-only.")


if __name__ == "__main__":
    upgrade()
