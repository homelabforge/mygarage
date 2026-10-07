"""Tax types become codes (#211).

`tax_records.tax_type` held one of four display strings behind a CHECK
(`Registration`, `Inspection`, `Property Tax`, `Tolls`). The EU work needs
more kinds (registration tax, CO₂ malus, circulation tax, vignette, LEZ
sticker…), so the column now holds a snake_case code from
`app.constants.tax.TAX_TYPE_VALUES`, validated by the schemas on every write
path the way vehicle_type has been since 079, and the CHECK goes:

1. drop the CHECK where present (`app.utils.check_constraint`): migrated
   installs and create_all databases from before this release both have it,
   a fresh install from now on has none;
2. rewrite the four legacy values to their codes.

Idempotent: without the CHECK step 1 is skipped, and the UPDATE matches
nothing the second time.

Not FATAL, on purpose: a failure here leaves the CHECK in place, and the
database then refuses every code the schemas now send (the request fails
with a constraint error) until the migration is re-run; nothing outside tax
records is affected and the app is better up than down for it. The runner
stops the run on the exception either way, so the migrations queued behind
this one wait for the re-run too.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

from app.constants.tax import LEGACY_TAX_TYPES
from app.utils.check_constraint import drop_check_constraint

FATAL = False

_TABLE = "tax_records"
_COLUMN = "tax_type"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Drop the tax_type CHECK and rewrite the legacy values to codes."""
    if engine is None:
        engine = _get_fallback_engine()
    if not inspect(engine).has_table(_TABLE):
        return

    if drop_check_constraint(engine, _TABLE, _COLUMN):
        print(f"  ✓ Dropped the {_COLUMN} CHECK on {_TABLE}")
    else:
        print(f"  → no {_COLUMN} CHECK on {_TABLE}, skipping")

    with engine.begin() as conn:
        for legacy, code in LEGACY_TAX_TYPES.items():
            result = conn.execute(
                text(f"UPDATE {_TABLE} SET {_COLUMN} = :code WHERE {_COLUMN} = :legacy"),
                {"code": code, "legacy": legacy},
            )
            if result.rowcount:
                print(f"  ✓ {result.rowcount} row(s) {legacy!r} -> {code!r}")


def downgrade() -> None:
    """Rollback not supported."""
    print("Downgrade not supported: the codes have no single legacy spelling to go back to")


if __name__ == "__main__":
    upgrade()
