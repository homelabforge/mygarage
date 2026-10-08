"""European insurance formulas and the no-claims class (#211).

`insurance_policy_vehicles.policy_type` held one of six North American
formulas behind a CHECK (`check_policy_vehicle_type`). Europe insures « au
tiers », « tiers étendu » and « tous risques », so the vocabulary grows
(`app.constants.insurance.POLICY_TYPE_VALUES`, validated by the schemas on
every write path the way vehicle_type has been since 079 and tax_type since
128) and the CHECK goes:

1. drop the CHECK where present (`app.utils.check_constraint`): migrated
   installs and create_all databases from before this release both have it,
   a fresh install from now on has none. On SQLite that is a table rebuild;
   `uq_insurance_policy_vehicle` and the two indexes survive it, and the
   rows of `insurance_policy_fields` and `insurance_coverages` that point at
   the links are checked against the rebuilt table before commit;
2. add `no_claims_class` VARCHAR(10): the bonus-malus coefficient (FR, LU),
   Schadenfreiheitsklasse (DE), classe di merito (IT)… the vehicle is rated
   at. Plain text; the country profile names the scheme.

FATAL, because the ORM maps the new column. Idempotent: without the CHECK
step 1 is skipped, and the column is added once.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

from app.utils.check_constraint import drop_check_constraint

FATAL = True

_TABLE = "insurance_policy_vehicles"
_CHECKED_COLUMN = "policy_type"
_COLUMN = "no_claims_class"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Drop the policy_type CHECK, add no_claims_class."""
    if engine is None:
        engine = _get_fallback_engine()
    if not inspect(engine).has_table(_TABLE):
        return

    if drop_check_constraint(engine, _TABLE, _CHECKED_COLUMN):
        print(f"  ✓ Dropped the {_CHECKED_COLUMN} CHECK on {_TABLE}")
    else:
        print(f"  → no {_CHECKED_COLUMN} CHECK on {_TABLE}, skipping")

    existing = {col["name"] for col in inspect(engine).get_columns(_TABLE)}
    if _COLUMN in existing:
        print(f"  → {_TABLE}.{_COLUMN} already exists, skipping")
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} VARCHAR(10)"))
    print(f"  ✓ Added {_TABLE}.{_COLUMN}")


def downgrade() -> None:
    """Rollback not supported."""
    print("Downgrade not supported: the European formulas have no place in the old CHECK")


if __name__ == "__main__":
    upgrade()
