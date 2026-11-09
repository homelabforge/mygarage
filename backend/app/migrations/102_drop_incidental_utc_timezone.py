"""Delete an incidental ``timezone=UTC`` settings row (household timezone fix).

Until this release nothing read the ``timezone`` settings row, and saving any
field on the Settings System tab wrote ``timezone=UTC`` as a side effect
(the select's seed default). Now the row drives every server-side calendar
date, so an incidental UTC row would silently pin a non-UTC container to UTC.

Policy (plan 4.3, a compatibility policy, not a preservation proof): delete
the row when its value is ``UTC`` AND the fallback chain without the row
(``MYGARAGE_TIMEZONE`` env, container zone, UTC) resolves to a zone other
than UTC. Every other row is kept and becomes live. The runner records this
migration, so a UTC value an owner saves afterwards is honoured. An owner who
deliberately picked UTC on a non-UTC container loses that choice once and
must re-select it; the release note says so.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = False


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    inspector = inspect(engine)
    if not inspector.has_table("settings"):
        return

    with engine.begin() as conn:
        value = conn.execute(text("SELECT value FROM settings WHERE key = 'timezone'")).scalar()
        if value != "UTC":
            print("✓ No incidental timezone=UTC row; nothing to do")
            return

        # The chain the installation would use WITHOUT the row.
        from app.utils.household_time import resolve_zone

        fallback = resolve_zone(None)
        if fallback.key == "UTC":
            print("✓ timezone=UTC matches the fallback zone; row kept")
            return

        conn.execute(text("DELETE FROM settings WHERE key = 'timezone' AND value = 'UTC'"))
        print(f"✓ Deleted incidental timezone=UTC row (fallback zone is {fallback.key})")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 102 is forward-only.")


if __name__ == "__main__":
    upgrade()
