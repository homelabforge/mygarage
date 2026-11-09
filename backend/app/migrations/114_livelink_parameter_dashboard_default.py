"""Reset ``livelink_parameters.show_on_dashboard`` to TRUE everywhere.

The flag was written at registration by parameter class and read by no screen:
the Live tab has always drawn every latest value. So it drifted into meaning
nothing, and on a production copy it was FALSE on 36 of 53 parameters, most of
them WiCAN PIDs.

The integrations settings now expose a per-reading "show on dashboard" switch,
and the Live tab filters on this flag. Filtering on the drifted values would
hide those gauges on upgrade, with no switch anywhere to restore them: only
MQTT devices get switches. Setting every row TRUE reproduces exactly what the
Live tab showed before, so the filter changes nothing until someone flips one.

``archive_only`` is deliberately left alone. It has a real reader (the Charts
picker), and it is what keeps diagnostics out of it.

FATAL = True: the frontend filter ships in the same release. If this were
skipped, those gauges would vanish without an error anywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_TABLE = "livelink_parameters"


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Set show_on_dashboard TRUE on every parameter row."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    if not inspect(engine).has_table(_TABLE):
        print(f"  → {_TABLE} missing; skip (run the earlier migrations first)")
        return

    with engine.begin() as conn:
        # TRUE, not 1: a bare 1 is a DatatypeMismatch on a PostgreSQL boolean.
        # The column is NOT NULL, so IS NOT TRUE matches exactly the FALSE rows.
        result = conn.execute(
            text(
                f"UPDATE {_TABLE} SET show_on_dashboard = TRUE WHERE show_on_dashboard IS NOT TRUE"
            )
        )
        print(f"✓ show_on_dashboard reset on {result.rowcount} parameter(s)")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 114 is forward-only.")


if __name__ == "__main__":
    upgrade()
