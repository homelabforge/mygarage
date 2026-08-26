"""Add per-quantity unit preference columns to users (issue #152).

Ten nullable ``unit_*`` override columns plus ``secondary_gallon``, a
``secondary_gallon`` backfill for every user, a UK materialisation, and a public
``default_unit_prefs`` settings row.

FATAL: the ORM model declares all eleven columns and SQLAlchemy selects them on
every user query, so a missing column fails authentication for every user rather
than degrading one feature.

NULL means "no override", not "derive from preset" (spec D3). On a US instance
this migration therefore writes only ``secondary_gallon``, and every existing
user resolves exactly as they did before, ``show_both_units`` included.

The UK case materialises rather than overrides: if the retiring
``imperial_gallon_standard`` setting is ``uk``, every ``unit_preference =
'imperial'`` user becomes ``custom`` with all eleven columns written, volume
``gal_uk`` and consumption ``mpg_uk``. Fully materialised so that a later preset
selection cannot silently revert them to US gallons. Metric users keep their
preset and receive only ``secondary_gallon = 'uk'``, which is what preserves
their show-both counterpart (D4b).

Ordering note: this migration runs inside ``init_db()``, BEFORE
``initialize_default_settings`` (``app/main.py:144``). On a fresh database the
``imperial_gallon_standard`` row does not exist yet, so its absence is treated
as ``us`` explicitly rather than failing or writing NULL. The later
``initialize_default_settings`` pass preserves the value written here because it
only fills in absent keys.

Dialect-aware: ``ALTER TABLE ... ADD COLUMN`` for a nullable column works
identically on SQLite and PostgreSQL, so no table rebuild is needed. What a
crash leaves behind is NOT identical, and the difference decides whether the
per-statement guards are load-bearing:

  - PostgreSQL: DDL is transactional. A failure anywhere in ``upgrade`` aborts
    the whole ``engine.begin()`` block, so a crashed run leaves nothing applied.
  - SQLite: pysqlite does not open a transaction for DDL, so each ``ALTER
    TABLE`` autocommits outside the enclosing block. A crash part-way through
    the loop leaves the columns added so far committed. Measured, not assumed:
    an abort before the 4th statement left three columns in place.

Production runs SQLite, so on the dialect that matters the ``missing`` filter
and the two ``IS NULL`` backfill predicates are the ONLY thing that makes a
crashed run recoverable, not an extra belt over a transactional brace. The
runner compounds this: it stamps ``schema_migrations`` in a separate
transaction from ``upgrade`` (``app/migrations/runner.py``), so a crash in that
window re-runs an already-committed migration on the next boot. Do not remove
the guards; ``TestRestartAfterPartialApplication`` and the two anti-restamp
tests in ``tests/migrations/test_093_unit_preferences.py`` each fail if you do.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.constants.units import (
    IMPERIAL_PRESET,
    UNIT_COLUMN_NAMES,
    UnitSet,
    field_to_column,
)

FATAL = True

GALLON_STANDARD_KEY = "imperial_gallon_standard"
DEFAULT_UNIT_PREFS_KEY = "default_unit_prefs"

# The UK flavour of the imperial preset. Everything imperial except the two
# gallon-bearing quantities and the show-both counterpart flavour.
#
# Built through model_validate rather than model_copy(update=...) so the three
# overridden values are validated against their vocabularies at import time. A
# typo here would otherwise be written to every UK user's row unchecked.
#
# app/utils/default_unit_prefs.py carries the same set as UK_IMPERIAL_PRESET for
# the live reseed path (a migration must stay standalone, so neither imports the
# other). TestUkImperialSetMatchesMigration093 fails if the two diverge.
UK_IMPERIAL_SET = UnitSet.model_validate(
    IMPERIAL_PRESET.model_dump()
    | {"volume": "gal_uk", "consumption": "mpg_uk", "secondary_gallon": "uk"}
)


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _read_gallon_standard(conn, has_settings: bool) -> str:
    """Return 'uk' or 'us'. Absent row, empty value, or typo all mean 'us'."""
    if not has_settings:
        return "us"
    value = conn.execute(
        text("SELECT value FROM settings WHERE key = :k"), {"k": GALLON_STANDARD_KEY}
    ).scalar_one_or_none()
    if value is not None and str(value).strip().lower() == "uk":
        return "uk"
    return "us"


def upgrade(engine=None) -> None:
    """Add unit preference columns, backfill them, and seed the public default."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("users"):
        print("  → users table missing; skip (run the earlier migrations first)")
        return

    existing = {c["name"] for c in inspector.get_columns("users")}
    missing = [name for name in UNIT_COLUMN_NAMES if name not in existing]
    has_settings = inspector.has_table("settings")

    with engine.begin() as conn:
        for name in missing:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} VARCHAR(12)"))
            print(f"  ✓ Added users.{name}")
        if not missing:
            print("  → unit preference columns already present")

        flavour = _read_gallon_standard(conn, has_settings)
        print(f"  → instance gallon standard: {flavour}")

        # Every user, every preset (D4b). Only fills NULLs, so a re-run and a
        # user who has since chosen their own flavour are both safe.
        filled = conn.execute(
            text("UPDATE users SET secondary_gallon = :f WHERE secondary_gallon IS NULL"),
            {"f": flavour},
        ).rowcount
        print(f"  ✓ secondary_gallon='{flavour}' written for {filled} user(s)")

        if flavour == "uk":
            _materialise_uk_imperial_users(conn)

        if has_settings:
            _seed_default_unit_prefs(conn, flavour)
        else:
            print("  → settings table missing; skipped default_unit_prefs seed")

    print("✓ Unit preference migration completed")


def _materialise_uk_imperial_users(conn) -> None:
    """Turn imperial users into fully-materialised custom users on a UK instance.

    Guarded on ``unit_volume IS NULL`` so a re-run, or a user who has since set
    their own volume, is left alone.
    """
    assignments = ", ".join(
        f"{field_to_column(field)} = :{field}" for field in UnitSet.model_fields
    )
    params = dict(UK_IMPERIAL_SET.model_dump())
    updated = conn.execute(
        text(
            f"UPDATE users SET unit_preference = 'custom', {assignments} "
            "WHERE unit_preference = 'imperial' AND unit_volume IS NULL"
        ),
        params,
    ).rowcount
    print(f"  ✓ Materialised {updated} imperial user(s) to custom UK units")


def _seed_default_unit_prefs(conn, flavour: str) -> None:
    """Create the public default unit set for anonymous and auth-none clients.

    Replaces the retiring public ``imperial_gallon_standard`` row (D5). An
    existing row is preserved: an admin may already have tuned it.
    """
    # Row existence, not value truthiness: settings.value is nullable, and
    # SELECT value would return None for a row that exists with a NULL value.
    # The INSERT below would then hit the primary key and, this migration being
    # FATAL, stop the application booting. Migration 042 sets the precedent.
    existing = conn.execute(
        text("SELECT key FROM settings WHERE key = :k"), {"k": DEFAULT_UNIT_PREFS_KEY}
    ).fetchone()
    if existing is not None:
        print("  → default_unit_prefs already present, preserved")
        return

    unit_set = UK_IMPERIAL_SET if flavour == "uk" else IMPERIAL_PRESET
    conn.execute(
        text(
            "INSERT INTO settings (key, value, category, description, encrypted) "
            "VALUES (:k, :v, 'general', :d, :e)"
        ),
        {
            "k": DEFAULT_UNIT_PREFS_KEY,
            "v": json.dumps(unit_set.model_dump(), sort_keys=True),
            "d": (
                "Default unit set for anonymous clients and new accounts (JSON, keyed by quantity)"
            ),
            "e": False,
        },
    )
    print(f"  ✓ Seeded default_unit_prefs from the {flavour} imperial set")


def downgrade() -> None:
    print("Downgrade not supported (would discard per-user unit choices)")


if __name__ == "__main__":
    upgrade()
