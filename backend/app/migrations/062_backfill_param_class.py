"""Backfill `param_class` for existing livelink_parameters rows.

Task 10 added a conservative inference catalog (`infer_param_class` in
``app/utils/autopid_normalizer.py``) and Task 11 applies it at
auto-registration — but only for params seen again after deploy. Live
prod has rows registered before the catalog existed (33 of 38 rows carry
NULL param_class), which means the telemetry validator skips all
range/rate-of-change checks for them. This migration classifies those
EXISTING rows once, in place.

For each row with ``param_class IS NULL``: set ``param_class`` from the
frozen inference below (rows whose key matches no pattern are skipped —
a NULL class simply stays unvalidated, same as today). ``category`` is
recomputed ONLY when the current value is NULL or ``'other'`` — category
is user-editable in the admin UI and a hand-tuned value must survive the
backfill (mirrors Task 11's guard in
``TelemetryService.auto_register_parameter``). ``show_on_dashboard``,
``archive_only`` and ``display_order`` are user-visible dashboard state
and are NEVER touched.

INTENTIONAL DUPLICATION: this migration carries its own FROZEN copy of
the pattern catalog (``_PATTERNS``) and the class→category mapping
(``_category_for``) rather than importing ``infer_param_class`` /
``_PARAM_CLASS_PATTERNS`` / ``TelemetryService._classify_param`` from
app code. A historical migration's output must never change when the
runtime catalog evolves — migrations in this repo are self-contained by
precedent (054 froze its own fuel map, 059 its own canonicalizer, for
the same reason). The snapshot is correct as of the reviewed 2026-07-02
catalog; ``test_062_snapshot_matches_runtime_catalog`` asserts
snapshot↔runtime equivalence at this point in time (a drift guard that
documents rather than forbids future divergence — the runtime catalog
may evolve and that test may then be updated, but this file must not).

Idempotent (only NULL-class rows are candidates; a second run finds
none it can change), dialect-aware (SQLite + PostgreSQL), forward-only.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

# FROZEN snapshot of app.utils.autopid_normalizer._PARAM_CLASS_PATTERNS as of
# 2026-07-02. Ordered, first match wins, matched against the canonical
# (UPPERCASE, spaces→underscores) form of the key. Do NOT sync with the
# runtime catalog — see module docstring.
_PATTERNS: tuple[tuple[str, str], ...] = (
    ("FUELTANKLEVEL", "percentage"),
    ("FUELLEVEL", "percentage"),
    ("THROTTLE", "percentage"),
    ("PEDALPOS", "percentage"),
    ("ENGINELOAD", "percentage"),
    ("RPM", "frequency"),
    ("SPEED", "speed"),
    ("PRES", "pressure"),
    ("TEMP", "temperature"),
    ("VOLT", "voltage"),
    ("A6-", "distance"),
    ("ODOMETER", "distance"),
    ("ODO", "distance"),
    ("MILEAGE", "distance"),
    ("DISTANCE", "distance"),
)

# FROZEN snapshot of TelemetryService._classify_param as of 2026-07-02.
# 'percentage' has no branch there and falls through to 'other' (known gap,
# kept deliberately — freezing actual behavior, not intended behavior).
_CLASS_TO_CATEGORY: dict[str, str] = {
    "temperature": "temperature",
    "speed": "engine",
    "distance": "engine",
    "frequency": "engine",
    "voltage": "electrical",
    "battery": "electrical",
    "pressure": "engine",
    "vacuum": "engine",
    "power_factor": "engine",
}


def _infer(param_key: str) -> str | None:
    """Frozen re-derivation of infer_param_class (incl. canonicalization)."""
    canonical = param_key.upper().replace(" ", "_")
    for token, param_class in _PATTERNS:
        if token in canonical:
            return param_class
    return None


def _category_for(param_class: str | None) -> str:
    """Frozen re-derivation of TelemetryService._classify_param."""
    if not param_class:
        return "other"
    return _CLASS_TO_CATEGORY.get(param_class.lower(), "other")


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Backfill `param_class` (and guarded `category`) on livelink_parameters."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    print("Migration 062: backfill param_class for existing telemetry parameters...")

    if not inspect(engine).has_table("livelink_parameters"):
        print("  = livelink_parameters table absent, skipping")
        print("Migration 062 complete.")
        return

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT param_key, category FROM livelink_parameters WHERE param_class IS NULL")
        ).fetchall()

        backfilled = 0
        for param_key, category in rows:
            inferred = _infer(param_key)
            if inferred is None:
                print(f"  = {param_key}: no inference, left unclassified")
                continue

            # Category is recomputed ONLY when unset or still the 'other'
            # default — a hand-tuned category must survive (Task 11 guard).
            if not category or category == "other":
                conn.execute(
                    text(
                        "UPDATE livelink_parameters "
                        "SET param_class = :pc, category = :cat "
                        "WHERE param_key = :k AND param_class IS NULL"
                    ),
                    {"pc": inferred, "cat": _category_for(inferred), "k": param_key},
                )
                print(f"  - {param_key}: class={inferred}, category={_category_for(inferred)}")
            else:
                conn.execute(
                    text(
                        "UPDATE livelink_parameters SET param_class = :pc "
                        "WHERE param_key = :k AND param_class IS NULL"
                    ),
                    {"pc": inferred, "k": param_key},
                )
                print(f"  - {param_key}: class={inferred}, category={category!r} preserved")
            backfilled += 1

    print(f"  {backfilled} row(s) backfilled out of {len(rows)} NULL-class row(s)")
    print("Migration 062 complete.")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 062 is forward-only. It only fills previously-NULL "
        "param_class values (and NULL/'other' categories); there is no "
        "prior state worth restoring."
    )


if __name__ == "__main__":
    upgrade()
