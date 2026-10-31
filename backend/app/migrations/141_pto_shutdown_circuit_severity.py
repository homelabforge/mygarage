"""Move the PTO engine shutdown circuit codes off critical (S1d-06, R1).

P251D/E/F ("PTO Engine Shutdown Circuit/Open", "... Low", "... High") are a
wiring fault on the PTO's shutdown input, but the generator's shutdown rule
read them as a forced engine shutdown and shipped them critical/4. The file
says warning/2 now; this moves the stored definitions to match, and every
vehicle DTC of those codes still at critical.

``upgrade(conn)``: both UPDATEs and the stamp commit together. Not FATAL: a
failure leaves three codes one tier too loud, and 141 retries next boot.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, bindparam, inspect, text

logger = logging.getLogger(__name__)

CODES = ("P251D", "P251E", "P251F")
# What the regenerated dtc_definitions.json says for all three; a test pins it.
NEW_SEVERITY = "warning"
NEW_LEVEL = 2

# Every vehicle DTC with one of these codes still at critical moves, a hand-set
# critical included: nothing records where a severity came from. Any other
# severity stays.
_MOVE_VEHICLE_DTCS = text(
    "UPDATE vehicle_dtcs SET severity = :new WHERE code IN :codes AND severity = 'critical'"
).bindparams(bindparam("codes", expanding=True))
_MOVE_DEFINITIONS = text(
    "UPDATE dtc_definitions SET severity = :new, estimated_severity_level = :level"
    " WHERE code IN :codes"
).bindparams(bindparam("codes", expanding=True))


def upgrade(conn: Connection) -> None:
    """Move P251D/E/F and the vehicle DTCs still critical under them, on the runner's connection."""
    inspector = inspect(conn)
    if inspector.has_table("vehicle_dtcs"):
        moved = conn.execute(
            _MOVE_VEHICLE_DTCS, {"new": NEW_SEVERITY, "codes": list(CODES)}
        ).rowcount
        logger.info("141: %d vehicle DTC(s) moved off critical", moved)
    else:
        logger.info("141: vehicle_dtcs missing; no vehicle DTCs to move")
    if inspector.has_table("dtc_definitions"):
        conn.execute(
            _MOVE_DEFINITIONS, {"new": NEW_SEVERITY, "level": NEW_LEVEL, "codes": list(CODES)}
        )
        logger.info("141: %s now %s/%d", ", ".join(CODES), NEW_SEVERITY, NEW_LEVEL)
    else:
        logger.info("141: dtc_definitions missing; no definitions to move")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 141 is forward-only.")
