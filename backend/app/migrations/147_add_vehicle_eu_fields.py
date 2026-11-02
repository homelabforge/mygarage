"""Add the EU registration-certificate fields on vehicles (#211).

Seven nullable columns, each a field of the EU registration certificate
(Directive 1999/37/EC) or the low-emission-zone class derived from them:

- ``euro_emission_class`` VARCHAR(12): field V.9 (« Euro 6d-TEMP »).
- ``fiscal_power`` INTEGER: field P.6, the national fiscal rating (FR CV).
- ``co2_g_km`` INTEGER: field V.7, CO₂ in g/km.
- ``power_kw`` INTEGER: field P.2, maximum net power in kW.
- ``eu_category`` VARCHAR(5): field J, the EU vehicle category (M1, N1, L3e).
- ``national_category`` VARCHAR(10): field J.1, the national kind (FR VP, CTTE).
- ``lez_class`` VARCHAR(10): the low-emission-zone class a person sets by
  hand when the computed one is wrong (Crit'Air « 1 », Umweltplakette « 4 »).

Bounds and vocabularies are enforced by Pydantic, not by a CHECK. FATAL: the
ORM declares every column and selects it on every vehicle path, so a silent
failure would boot the app against a missing column. Idempotent: each column
is added only when absent. The types are the same on SQLite and PostgreSQL.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_TABLE = "vehicles"
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("euro_emission_class", "VARCHAR(12)"),
    ("fiscal_power", "INTEGER"),
    ("co2_g_km", "INTEGER"),
    ("power_kw", "INTEGER"),
    ("eu_category", "VARCHAR(5)"),
    ("national_category", "VARCHAR(10)"),
    ("lez_class", "VARCHAR(10)"),
)


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add the seven columns (see module docstring)."""
    if engine is None:
        engine = _get_fallback_engine()
    if not inspect(engine).has_table(_TABLE):
        return
    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns(_TABLE)}
        for name, ddl in _COLUMNS:
            if name in existing:
                print(f"  → {_TABLE}.{name} already exists, skipping")
                continue
            conn.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN {name} {ddl}"))
            print(f"  ✓ Added {_TABLE}.{name}")


def downgrade() -> None:
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()
