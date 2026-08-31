"""Add livelink_devices.odometer_unit and backfill it from observed param keys.

Storage is metric-canonical, but a device's raw odometer reading is only metric
if it came from the standard SAE J1979 PID ``A6-ODOMETER``. WiCAN also supports
*autopids* — user-defined CAN expressions under an arbitrary name — and on a
US-market car a bare ``ODOMETER`` autopid reads the dash odometer in miles.

`6f04e53` ("Fix/v2.26.2 currency and metric canonical") collapsed both cases to
``int(round(value))``. For a miles-reporting device the result lands *below* the
vehicle's real odometer, so the monotonic guard in
``TelemetryService._sync_odometer_from_telemetry`` discarded every reading with
no log line: odometer auto-recording died on 2026-04-23 and stayed dead.

FATAL: the ORM model declares ``odometer_unit`` and SQLAlchemy selects it on
every device query, so a missing column breaks the whole LiveLink surface —
ingest, device admin and session tracking alike — not one feature.

Backfill: units are a property of the device, and the only evidence available is
the key shape it has actually published, so each device is classified from its
own rows in ``vehicle_telemetry``:

  - has published an OBD2-PID-prefixed odometer key (``A6-ODOMETER``) -> ``km``
  - has published only a bare/custom odometer key (``ODOMETER``)      -> ``mi``
  - has published no odometer key at all -> left NULL, and the service infers
    from the key shape on first sight.

Writing the inferred value rather than leaving it NULL is deliberate: it makes
the guess visible and editable in the device admin UI instead of an invisible
default, which matters because it IS only a guess about hardware.

The PID prefix regex is inlined rather than imported from
``app/utils/odometer_units.py``. A migration is a snapshot of intent at a point
in time; importing the live helper would silently re-interpret this backfill if
the heuristic is ever tuned.

Dialect-aware: ``ALTER TABLE ... ADD COLUMN`` for a nullable column is identical
on SQLite and PostgreSQL, so no table rebuild is needed. Idempotent: the column
is added only when absent and the backfill only writes ``odometer_unit IS NULL``
rows, so a crash between ``upgrade`` and the runner's separate
``schema_migrations`` stamp re-runs safely (see 093 for why that window exists).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True

# A standard OBD2 PID key is two hex digits then a dash: "A6-ODOMETER".
# Anything else is a user-named autopid. Inlined on purpose — see module docstring.
_OBD2_PID_PREFIX_RE = re.compile(r"^[0-9A-F]{2}-")

# Matched case-insensitively against param_key to find odometer-bearing rows.
_ODOMETER_SUBSTRINGS = ("ODOMETER", "ODO", "MILEAGE", "DISTANCE_TOTAL", "TOTAL_DISTANCE")


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _is_odometer_key(param_key: str) -> bool:
    upper = param_key.upper()
    return any(s in upper for s in _ODOMETER_SUBSTRINGS)


def _infer_unit(param_keys: set[str]) -> str:
    """A standard PID key means metric; only bare autopid keys mean miles."""
    if any(_OBD2_PID_PREFIX_RE.match(k.upper()) for k in param_keys):
        return "km"
    return "mi"


def upgrade(engine=None) -> None:
    """Add the column, then classify each device from the keys it has published."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("livelink_devices"):
        print("  → livelink_devices missing; skip (run the earlier migrations first)")
        return

    existing = {c["name"] for c in inspector.get_columns("livelink_devices")}
    has_telemetry = inspector.has_table("vehicle_telemetry")

    with engine.begin() as conn:
        if "odometer_unit" not in existing:
            conn.execute(text("ALTER TABLE livelink_devices ADD COLUMN odometer_unit VARCHAR(4)"))
            print("  ✓ Added livelink_devices.odometer_unit")
        else:
            print("  → livelink_devices.odometer_unit already present")

        if not has_telemetry:
            print("  → vehicle_telemetry missing; leaving odometer_unit NULL (inferred at ingest)")
            return

        # Group the odometer keys each device has actually published.
        keys_by_device: dict[str, set[str]] = {}
        for device_id, param_key in conn.execute(
            text("SELECT DISTINCT device_id, param_key FROM vehicle_telemetry")
        ):
            if device_id and param_key and _is_odometer_key(param_key):
                keys_by_device.setdefault(device_id, set()).add(param_key)

        if not keys_by_device:
            print("  → no odometer telemetry on record; leaving odometer_unit NULL")
            return

        updated = 0
        for device_id, param_keys in sorted(keys_by_device.items()):
            unit = _infer_unit(param_keys)
            # Only fills NULLs, so a re-run and an operator who has since set
            # the unit by hand are both safe.
            rows = conn.execute(
                text(
                    "UPDATE livelink_devices SET odometer_unit = :u "
                    "WHERE device_id = :d AND odometer_unit IS NULL"
                ),
                {"u": unit, "d": device_id},
            ).rowcount
            if rows:
                updated += rows
                print(f"  ✓ {device_id}: odometer_unit='{unit}' from {sorted(param_keys)}")

        print(f"  ✓ Classified {updated} device(s); devices without odometer rows stay NULL")
