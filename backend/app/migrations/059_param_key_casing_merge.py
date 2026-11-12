"""Re-key all telemetry param_key values to the UPPERCASE canonical, merging
casing duplicates created by the historical MQTT(upper)/HTTPS(case-preserving)
split. Uppercase wins on collision.

Canonical form mirrors ``app.utils.autopid_normalizer.canonical_param_key``
exactly: ``key.upper().replace(" ", "_")`` == SQL ``REPLACE(UPPER(key), ' ', '_')``.

Three tables (``vehicle_telemetry``, ``vehicle_telemetry_latest``,
``livelink_parameters``) use a DROP+REKEY strategy: at each table's unique
"slot", every casing variant of a PID is collapsed to ONE survivor via a
window-function group-collapse keyed on ``(slot…, canonical_key)`` (an
already-canonical/uppercase row wins the survivor slot; ties fall back to the
lowest id), then survivors are re-keyed up. Collapsing ALL-but-one per group —
not just a mixed row that happens to have an exact canonical twin — is what
makes the subsequent blanket rekey collision-free: two *distinct* non-canonical
casings of the same PID at one slot (e.g. ``51-FuelType`` + ``51-fueltype``,
neither equal to ``51-FUELTYPE``) would otherwise both rekey up and violate the
UNIQUE slot. Dropping is acceptable here because those rows are reproducible
(raw/latest telemetry, re-discovered parameter rows).

``telemetry_daily_summary`` is handled SEPARATELY with a RE-AGGREGATION merge
(NOT drop): it is the durable long-term analytics record that survives raw
telemetry pruning, so a colliding day's aggregates must be merged, never
discarded. The merge runs row-wise in Python (the table is tiny — one row per
vin/param/date) to avoid gnarly dialect-portable weighted-average SQL.

Idempotent, dialect-aware (PostgreSQL + SQLite). HEAVY on vehicle_telemetry —
back up the DB first (see Task 10 deploy note). Forward-only.
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from sqlalchemy import Engine, bindparam, create_engine, inspect, text

# (table, key_col, the columns that define a duplicate "slot" besides key_col)
_TARGETS = [
    ("vehicle_telemetry", "param_key", ["device_id", "timestamp"]),
    ("vehicle_telemetry_latest", "param_key", ["vin"]),
    ("livelink_parameters", "param_key", []),  # param_key is unique on its own
]


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _canon_sql(col: str) -> str:
    """SQL for the canonical key: UPPER then space→underscore.

    Portable across SQLite and PostgreSQL, and identical to the Python
    ``canonical_param_key`` (``key.upper().replace(" ", "_")``).
    """
    return f"REPLACE(UPPER({col}), ' ', '_')"


def _canon_py(key: str) -> str:
    """Python twin of :func:`_canon_sql` for the row-wise daily-summary merge."""
    return key.upper().replace(" ", "_")


def _merge_daily_summary(engine: Engine) -> None:
    """Re-aggregate ``telemetry_daily_summary`` to canonical keys (merge, not drop).

    Groups every row by ``(vin, canonical_param_key, date)`` and, where a group
    has more than one physical row (a casing collision) or a non-canonical key,
    collapses it into a single canonical row with re-aggregated statistics:

    * ``sample_count`` = sum of the group's counts
    * ``min_value``   = min over non-NULL mins (NULL if all NULL)
    * ``max_value``   = max over non-NULL maxes (NULL if all NULL)
    * ``avg_value``   = sample-count-weighted mean over rows with a non-NULL
      avg AND ``sample_count > 0``; NULL if no such row / total weight 0
      (guards against zero-division)

    The surviving row is an existing already-canonical row if the group has one
    (lowest such id), else the lowest id in the group; it is UPDATEd in place and
    the other rows are DELETEd. Groups that are already a single canonical row
    are left untouched, which makes a second run a no-op.
    """
    if not inspect(engine).has_table("telemetry_daily_summary"):
        print("  → telemetry_daily_summary absent, skipping re-aggregation")
        return

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, vin, param_key, date, min_value, max_value, avg_value, sample_count "
                "FROM telemetry_daily_summary"
            )
        ).fetchall()

        # Group by (vin, canonical_key, date). Keyed on the *canonical* param_key
        # so casing twins land in the same bucket.
        groups: dict[tuple, list] = defaultdict(list)
        for r in rows:
            canon = _canon_py(r.param_key)
            groups[(r.vin, canon, r.date)].append(r)

        merged = 0
        for (_vin, canon, _date), members in groups.items():
            # No work for a group that is already a single canonical row.
            if len(members) == 1 and members[0].param_key == canon:
                continue

            # Survivor: prefer an existing canonical row (lowest such id), else lowest id.
            canon_members = [m for m in members if m.param_key == canon]
            survivor = min(canon_members or members, key=lambda m: m.id)

            counts = [m.sample_count or 0 for m in members]
            total_count = sum(counts)

            mins = [m.min_value for m in members if m.min_value is not None]
            maxes = [m.max_value for m in members if m.max_value is not None]
            merged_min = min(mins) if mins else None
            merged_max = max(maxes) if maxes else None

            # Weighted mean over rows with a usable avg AND positive weight.
            weighted = [
                (m.avg_value, m.sample_count)
                for m in members
                if m.avg_value is not None and (m.sample_count or 0) > 0
            ]
            weight_total = sum(w for _, w in weighted)
            merged_avg = (
                sum(a * w for a, w in weighted) / weight_total if weight_total > 0 else None
            )

            conn.execute(
                text(
                    "UPDATE telemetry_daily_summary SET param_key = :pk, min_value = :mn, "
                    "max_value = :mx, avg_value = :av, sample_count = :cnt WHERE id = :id"
                ),
                {
                    "pk": canon,
                    "mn": merged_min,
                    "mx": merged_max,
                    "av": merged_avg,
                    "cnt": total_count,
                    "id": survivor.id,
                },
            )
            loser_ids = [m.id for m in members if m.id != survivor.id]
            if loser_ids:
                conn.execute(
                    text("DELETE FROM telemetry_daily_summary WHERE id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": loser_ids},
                )
            merged += 1

    print(f"  ✓ Re-aggregated telemetry_daily_summary ({merged} group(s) merged)")


def upgrade(engine: Engine | None = None) -> None:
    """Canonicalize every param_key to UPPER(REPLACE(key,' ','_')), merging dups."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()
    inspector = inspect(engine)
    print("Migration 059: param_key casing-merge...")

    for table, col, slot in _TARGETS:
        if not inspector.has_table(table):
            print(f"  → {table} absent, skipping")
            continue
        canon = _canon_sql(col)
        # Partition = the table's slot columns followed by the CANONICAL key, so
        # every casing variant of a PID at a given slot lands in one partition.
        # No-slot table (livelink_parameters) partitions on the canon alone.
        partition_cols = ", ".join([*slot, canon])
        with engine.begin() as conn:
            # 1. Collapse each (slot…, canonical) group to ONE survivor, BEFORE
            #    rekeying. Without this, two *distinct* non-canonical casings of
            #    the same PID at the same slot (e.g. 51-FuelType + 51-fueltype,
            #    neither == 51-FUELTYPE) would both be rekeyed up in step 2 and
            #    collide on the UNIQUE slot → IntegrityError → blocked startup.
            #    ROW_NUMBER ranks an already-canonical row first (CASE → 0), so
            #    "uppercase wins"; ties (no canonical present) fall to lowest id.
            #    The ranking subquery is uncorrelated, so this is valid on both
            #    SQLite (≥3.25) and PostgreSQL.
            conn.execute(
                text(
                    f"DELETE FROM {table} WHERE id IN ("
                    f"  SELECT id FROM ("
                    f"    SELECT id, ROW_NUMBER() OVER ("
                    f"      PARTITION BY {partition_cols} "
                    f"      ORDER BY CASE WHEN {col} = {canon} THEN 0 ELSE 1 END, id"
                    f"    ) AS rn"
                    f"    FROM {table}"
                    f"  ) ranked"
                    f"  WHERE rn > 1)"
                )
            )
            # 2. Re-key the survivors up to canonical (no-op for already-uppercase).
            #    Safe now: each (slot, canon) group has exactly one survivor.
            conn.execute(text(f"UPDATE {table} SET {col} = {canon} WHERE {col} <> {canon}"))
        print(f"  ✓ Canonicalized {table}.{col}")

    # telemetry_daily_summary: re-aggregate (merge), never drop — durable record.
    _merge_daily_summary(engine)

    print("✓ Migration 059 complete")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 059 is forward-only (lossy merge). Restore from a pre-059 backup if needed."
    )


if __name__ == "__main__":
    upgrade()
