"""Add ``tires.storage_location``: where a tire is kept while it is off the car.

Free text on purpose. A garage shelf, a friend's basement and "the shop keeps
them" are all storage locations, and a lookup table would need managing for
what is, for nearly everyone, one string typed once a season. Requested on
#153 by IanVinkHub, whose seasonal-set comment shaped the mount-period model.

FATAL for migration 099's reason: the Tire ORM maps this column, so every tire
SELECT includes it and a silent skip would 500 all tire reads after the model
change.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_COLUMNS: tuple[tuple[str, str], ...] = (("storage_location", "VARCHAR(120)"),)


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
    if not inspector.has_table("tires"):
        return

    existing = {c["name"] for c in inspector.get_columns("tires")}
    missing = [(name, ddl) for name, ddl in _COLUMNS if name not in existing]
    if not missing:
        print("✓ tires.storage_location already present")
        return

    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE tires ADD COLUMN {name} {ddl}"))
            print(f"✓ Added tires.{name}")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 100 is forward-only.")


if __name__ == "__main__":
    upgrade()
