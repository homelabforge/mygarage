"""Make an insurance policy a household record that covers many vehicles.

Before this migration a policy row WAS one vehicle's insurance:
`insurance_policies.vin` was NOT NULL, so one real policy covering three
vehicles had to be typed three times, and its premium, dates and deductible
drifted apart.

After it, `insurance_policies` is household-level (no `vin`), each covered
vehicle is a row in `insurance_policy_vehicles` carrying what genuinely differs
per vehicle (coverage type, premium share, deductible, coverage limits, notes),
`insurance_policy_fields` holds user-named fields at either level, and
`previous_policy_id` chains a policy to the term or insurer it succeeded.

FATAL, because the ORM no longer maps `insurance_policies.vin`.

THE MERGE
---------
Existing rows are grouped by
`(vehicle owner, provider, policy number, start, end, premium frequency)` and
each group becomes one policy with one link per source row.

- The OWNER is in the key so two users' look-alike rows never become one
  policy, which would hand one of them control of the other's coverage.
- The FREQUENCY is in the key so a monthly amount is never summed with an
  annual one.
- Two rows of one group for the SAME vehicle fold into one link only when they
  are compatible (every field equal, or NULL on one side). A conflicting
  duplicate becomes its own policy: nothing is discarded.

THE INVARIANT: every (vin, premium, deductible, type, coverage limits, notes)
a user could see before the upgrade is still on that vehicle after it. So each
link's `premium_share` is the source row's own premium, and the policy total is
their sum only when EVERY link has one; a policy with any unknown premium gets
a NULL total rather than a computed split that would turn "unknown" into 0.00.

History is chained only where it is unambiguous: a successor must start on or
after its predecessor ends, and exactly one candidate may qualify. Concurrent
policies, including the ones this migration deliberately kept apart, are never
chained, because a chained policy reads as superseded.

WHY ONE TRANSACTION / WHY THE PRAGMA IS READ BACK: see migration 097. The
runner executes and stamps in separate transactions, and `PRAGMA foreign_keys =
OFF` is a silent no-op inside a transaction.

Back up first with the backup API (`POST /api/backup/create-full`), not `cp`:
MyGarage runs in WAL mode and a copied file with a live WAL sidecar is torn but
plausible.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text

FATAL = True

POLICY_TYPES = ("Liability", "Comprehensive", "Collision", "Full Coverage", "Minimum", "Other")
PREMIUM_FREQUENCIES = ("Monthly", "Quarterly", "Semi-Annual", "Annual")

_LINK_FIELDS = ("policy_type", "premium_share", "deductible", "coverage_limits", "notes")


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _day(value: Any) -> str | None:
    """A DATE as ``YYYY-MM-DD``: psycopg2 yields date objects, SQLite strings."""
    return str(value)[:10] if value is not None else None


# ============================================================================
#  The merge plan (pure: no database, so it is tested directly)
# ============================================================================


def _compatible(link: dict[str, Any], row: dict[str, Any]) -> bool:
    """Whether `row` can fold into `link` without discarding a value."""
    for name in _LINK_FIELDS:
        a, b = link[name], row[name]
        if a is not None and b is not None and a != b:
            return False
    return True


def plan_merge(
    rows: list[dict[str, Any]], owner_by_vin: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn legacy per-vehicle rows into household policies with links.

    Returns `(policies, log)`. Each policy is a dict with the surviving `id`,
    the policy-level columns, `links` (one dict per covered vehicle) and
    `previous_policy_id`.
    """
    log: list[str] = []
    groups: dict[tuple, list[dict[str, Any]]] = {}

    for raw in sorted(rows, key=lambda r: r["id"]):
        row = dict(raw)
        if row["policy_type"] not in POLICY_TYPES:
            log.append(
                f"row {row['id']}: policy_type {row['policy_type']!r} is not a known "
                "type; stored as 'Other'"
            )
            row["policy_type"] = "Other"
        if row["premium_frequency"] is not None and (
            row["premium_frequency"] not in PREMIUM_FREQUENCIES
        ):
            log.append(
                f"row {row['id']}: premium_frequency {row['premium_frequency']!r} is "
                "not a known frequency; cleared"
            )
            row["premium_frequency"] = None
        row["premium_share"] = row["premium_amount"]
        key = (
            owner_by_vin.get(row["vin"]),
            (row["provider"] or "").strip().lower(),
            (row["policy_number"] or "").strip(),
            _day(row["start_date"]),
            _day(row["end_date"]),
            row["premium_frequency"],
        )
        groups.setdefault(key, []).append(row)

    policies: list[dict[str, Any]] = []
    for key, members in groups.items():
        buckets: list[dict[str, Any]] = []
        for row in members:
            placed = False
            for bucket in buckets:
                link = bucket["links"].get(row["vin"])
                if link is None:
                    bucket["links"][row["vin"]] = {n: row[n] for n in _LINK_FIELDS} | {
                        "vin": row["vin"]
                    }
                    bucket["rows"].append(row)
                    placed = True
                    break
                if _compatible(link, row):
                    for name in _LINK_FIELDS:
                        if link[name] is None:
                            link[name] = row[name]
                    bucket["rows"].append(row)
                    log.append(
                        f"row {row['id']}: duplicate of vehicle {row['vin']} on policy "
                        f"{bucket['rows'][0]['id']}; folded"
                    )
                    placed = True
                    break
            if not placed:
                buckets.append(
                    {
                        "rows": [row],
                        "links": {
                            row["vin"]: {n: row[n] for n in _LINK_FIELDS} | {"vin": row["vin"]}
                        },
                    }
                )
                if len(buckets) > 1:
                    log.append(
                        f"row {row['id']}: conflicts with another row for vehicle "
                        f"{row['vin']} on the same policy; kept as its own policy"
                    )

        for bucket in buckets:
            first = bucket["rows"][0]
            links = list(bucket["links"].values())
            shares = [link["premium_share"] for link in links]
            total = sum(shares) if all(s is not None for s in shares) else None
            notified = [r["last_notified_at"] for r in bucket["rows"] if r["last_notified_at"]]
            created = [r["created_at"] for r in bucket["rows"] if r["created_at"]]
            policies.append(
                {
                    "id": first["id"],
                    "owner": key[0],
                    "provider": first["provider"],
                    "policy_number": first["policy_number"],
                    "start_date": first["start_date"],
                    "end_date": first["end_date"],
                    "premium_amount": total,
                    "premium_frequency": first["premium_frequency"],
                    "created_at": min(created, key=str) if created else None,
                    "last_notified_at": max(notified, key=str) if notified else None,
                    "created_by_user_id": key[0],
                    "previous_policy_id": None,
                    "links": links,
                    "source_ids": [r["id"] for r in bucket["rows"]],
                }
            )

    _chain_history(policies)
    return policies, log


def _chain_history(policies: list[dict[str, Any]]) -> None:
    """Set `previous_policy_id` only where the sequence is unambiguous."""
    families: dict[tuple, list[dict[str, Any]]] = {}
    for policy in policies:
        family = (
            policy["owner"],
            (policy["provider"] or "").strip().lower(),
            (policy["policy_number"] or "").strip(),
        )
        families.setdefault(family, []).append(policy)

    for members in families.values():
        if len(members) < 2:
            continue
        chosen: dict[int, int] = {}
        for policy in members:
            start = _day(policy["start_date"])
            if start is None:
                continue
            earlier = [
                other
                for other in members
                if other is not policy
                and _day(other["end_date"]) is not None
                and _day(other["end_date"]) <= start
                and _day(other["start_date"]) < start
            ]
            if not earlier:
                continue
            latest_end = max(_day(o["end_date"]) for o in earlier)
            nearest = [o for o in earlier if _day(o["end_date"]) == latest_end]
            if len(nearest) == 1:
                chosen[policy["id"]] = nearest[0]["id"]
        # A predecessor claimed by two successors is two concurrent policies
        # following one term: ambiguous, so neither is chained.
        claims = Counter(chosen.values())
        for policy in members:
            predecessor = chosen.get(policy["id"])
            if predecessor is not None and claims[predecessor] == 1:
                policy["previous_policy_id"] = predecessor


# ============================================================================
#  DDL
# ============================================================================

_TYPE_CHECK = "policy_type IN ({})".format(", ".join(f"'{t}'" for t in POLICY_TYPES))
# Same expression the ORM declares (a NULL passes an IN check), so a migrated
# database and a create_all one reflect identically.
_FREQ_CHECK = "premium_frequency IN ({})".format(", ".join(f"'{f}'" for f in PREMIUM_FREQUENCIES))


def _links_ddl(serial: str, timestamp: str) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS insurance_policy_vehicles (
            id {serial},
            policy_id INTEGER NOT NULL REFERENCES insurance_policies(id) ON DELETE CASCADE,
            vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
            policy_type VARCHAR(30) NOT NULL,
            premium_share NUMERIC(10, 2),
            deductible NUMERIC(10, 2),
            coverage_limits TEXT,
            notes TEXT,
            effective_to DATE,
            created_at {timestamp} DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_insurance_policy_vehicle UNIQUE (policy_id, vin),
            CONSTRAINT check_policy_vehicle_type CHECK ({_TYPE_CHECK})
        )
    """


def _fields_ddl(serial: str) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS insurance_policy_fields (
            id {serial},
            policy_id INTEGER NOT NULL REFERENCES insurance_policies(id) ON DELETE CASCADE,
            policy_vehicle_id INTEGER REFERENCES insurance_policy_vehicles(id) ON DELETE CASCADE,
            label VARCHAR(60) NOT NULL,
            value VARCHAR(255) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
    """


_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_insurance_policy_vehicles_vin "
    "ON insurance_policy_vehicles (vin)",
    "CREATE INDEX IF NOT EXISTS idx_insurance_policy_vehicles_policy "
    "ON insurance_policy_vehicles (policy_id)",
    "CREATE INDEX IF NOT EXISTS idx_insurance_policy_fields_policy "
    "ON insurance_policy_fields (policy_id)",
    "CREATE INDEX IF NOT EXISTS idx_insurance_policies_end_date ON insurance_policies (end_date)",
    "CREATE INDEX IF NOT EXISTS idx_insurance_policies_previous "
    "ON insurance_policies (previous_policy_id)",
)

_LEGACY_SELECT = (
    "SELECT id, vin, provider, policy_number, policy_type, start_date, end_date, "
    "premium_amount, premium_frequency, deductible, coverage_limits, notes, "
    "created_at, last_notified_at FROM insurance_policies ORDER BY id"
)
_LEGACY_COLUMNS = (
    "id",
    "vin",
    "provider",
    "policy_number",
    "policy_type",
    "start_date",
    "end_date",
    "premium_amount",
    "premium_frequency",
    "deductible",
    "coverage_limits",
    "notes",
    "created_at",
    "last_notified_at",
)


def _report(policies: list[dict[str, Any]], log: list[str], source_rows: int) -> None:
    for line in log:
        print(f"  → 107: {line}")
    links = sum(len(p["links"]) for p in policies)
    chained = sum(1 for p in policies if p["previous_policy_id"] is not None)
    print(
        f"  → 107: {source_rows} per-vehicle row(s) became {len(policies)} "
        f"policy(ies) covering {links} vehicle link(s); {chained} chained to a prior term"
    )


# ============================================================================
#  SQLite
# ============================================================================


def _run_sqlite(engine) -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("PRAGMA foreign_keys = OFF")
        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 0:
            raise RuntimeError(
                f"PRAGMA foreign_keys = OFF failed; got {fk_state}. Are we inside an "
                "active transaction? Proceeding would let the insurance_policies "
                "rebuild cascade its new link rows away."
            )
        try:
            cur.execute("BEGIN")

            rows = [
                dict(zip(_LEGACY_COLUMNS, r, strict=True))
                for r in cur.execute(_LEGACY_SELECT).fetchall()
            ]
            owner_by_vin = dict(cur.execute("SELECT vin, user_id FROM vehicles").fetchall())
            policies, log = plan_merge(rows, owner_by_vin)

            cur.execute("DROP TABLE IF EXISTS insurance_policies_new")
            cur.execute(
                f"""
                CREATE TABLE insurance_policies_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider VARCHAR(100) NOT NULL,
                    policy_number VARCHAR(50) NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    premium_amount NUMERIC(10, 2),
                    premium_frequency VARCHAR(20),
                    notes TEXT,
                    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    previous_policy_id INTEGER REFERENCES insurance_policies(id)
                        ON DELETE SET NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_notified_at DATETIME,
                    CONSTRAINT check_premium_frequency CHECK ({_FREQ_CHECK})
                )
                """
            )
            cur.execute(_links_ddl("INTEGER PRIMARY KEY AUTOINCREMENT", "DATETIME"))
            cur.execute(_fields_ddl("INTEGER PRIMARY KEY AUTOINCREMENT"))

            for policy in policies:
                cur.execute(
                    "INSERT INTO insurance_policies_new (id, provider, policy_number, "
                    "start_date, end_date, premium_amount, premium_frequency, notes, "
                    "created_by_user_id, previous_policy_id, created_at, last_notified_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                    (
                        policy["id"],
                        policy["provider"],
                        policy["policy_number"],
                        policy["start_date"],
                        policy["end_date"],
                        _num(policy["premium_amount"]),
                        policy["premium_frequency"],
                        policy["created_by_user_id"],
                        policy["previous_policy_id"],
                        policy["created_at"],
                        policy["last_notified_at"],
                    ),
                )
                for link in policy["links"]:
                    cur.execute(
                        "INSERT INTO insurance_policy_vehicles (policy_id, vin, policy_type, "
                        "premium_share, deductible, coverage_limits, notes) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            policy["id"],
                            link["vin"],
                            link["policy_type"],
                            _num(link["premium_share"]),
                            _num(link["deductible"]),
                            link["coverage_limits"],
                            link["notes"],
                        ),
                    )

            cur.execute("DROP TABLE insurance_policies")
            cur.execute("ALTER TABLE insurance_policies_new RENAME TO insurance_policies")
            for ddl in _INDEXES:
                cur.execute(ddl)

            violations = cur.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(
                    f"FK violations after the insurance rebuild (pre-commit): {violations!r}"
                )
            cur.execute("COMMIT")
            _report(policies, log, len(rows))
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys = ON")

        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 1:
            raise RuntimeError(f"PRAGMA foreign_keys = ON failed; got {fk_state}.")
    finally:
        raw.close()


def _num(value: Any) -> Any:
    """SQLite's DB-API cannot bind a Decimal; its NUMERIC affinity takes a str."""
    return None if value is None else str(value)


# ============================================================================
#  PostgreSQL
# ============================================================================


def _run_postgres(engine) -> None:
    with engine.begin() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text(_LEGACY_SELECT)).fetchall()]
        owner_by_vin = {
            r.vin: r.user_id for r in conn.execute(text("SELECT vin, user_id FROM vehicles"))
        }
        policies, log = plan_merge(rows, owner_by_vin)

        conn.execute(
            text(
                "ALTER TABLE insurance_policies ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE insurance_policies ADD COLUMN IF NOT EXISTS previous_policy_id INTEGER"
            )
        )
        conn.execute(text(_links_ddl("SERIAL PRIMARY KEY", "TIMESTAMP")))
        conn.execute(text(_fields_ddl("SERIAL PRIMARY KEY")))

        survivors = [p["id"] for p in policies]
        for policy in policies:
            conn.execute(
                text(
                    "UPDATE insurance_policies SET premium_amount = :premium, "
                    "premium_frequency = :frequency, notes = NULL, "
                    "created_by_user_id = :creator, created_at = :created, "
                    "last_notified_at = :notified WHERE id = :id"
                ),
                {
                    "premium": policy["premium_amount"],
                    "frequency": policy["premium_frequency"],
                    "creator": policy["created_by_user_id"],
                    "created": policy["created_at"],
                    "notified": policy["last_notified_at"],
                    "id": policy["id"],
                },
            )
            for link in policy["links"]:
                conn.execute(
                    text(
                        "INSERT INTO insurance_policy_vehicles (policy_id, vin, policy_type, "
                        "premium_share, deductible, coverage_limits, notes) "
                        "VALUES (:policy_id, :vin, :policy_type, :premium_share, "
                        ":deductible, :coverage_limits, :notes)"
                    ),
                    {"policy_id": policy["id"], **link},
                )

        absorbed = [r["id"] for r in rows if r["id"] not in set(survivors)]
        if absorbed:
            conn.execute(
                text("DELETE FROM insurance_policies WHERE id = ANY(:ids)"), {"ids": absorbed}
            )
        # Pointers last: every predecessor row now certainly still exists.
        for policy in policies:
            if policy["previous_policy_id"] is not None:
                conn.execute(
                    text("UPDATE insurance_policies SET previous_policy_id = :prev WHERE id = :id"),
                    {"prev": policy["previous_policy_id"], "id": policy["id"]},
                )

        for column in ("vin", "policy_type", "deductible", "coverage_limits"):
            conn.execute(text(f"ALTER TABLE insurance_policies DROP COLUMN IF EXISTS {column}"))

        for name, ddl in (
            (
                "fk_insurance_policies_creator",
                "FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL",
            ),
            (
                "fk_insurance_policies_previous",
                "FOREIGN KEY (previous_policy_id) REFERENCES insurance_policies(id) "
                "ON DELETE SET NULL",
            ),
        ):
            conn.execute(
                text(
                    f"DO $$ BEGIN ALTER TABLE insurance_policies ADD CONSTRAINT {name} {ddl}; "
                    "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
                )
            )
        # The legacy CHECK rejected a NULL-less typo but allowed NULL already;
        # the cleared frequencies above satisfy it, so it is left in place.
        for ddl in _INDEXES:
            conn.execute(text(ddl))
        _report(policies, log, len(rows))


# ============================================================================
#  Entry point
# ============================================================================


def _preflight_backup_marker() -> None:
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    backups = data_dir / "backups"
    if not backups.is_dir() or not any(backups.iterdir()):
        print(
            f"  → 107: WARNING — no backup found in {backups}. This migration cannot be "
            "reversed: it drops insurance_policies.vin, which the previous release's "
            "ORM requires. Take one now (POST /api/backup/create-full) if you have not."
        )


def upgrade(engine=None) -> None:
    """Run the migration, or return cleanly if it has already been applied.

    RE-ENTRANCY. The whole thing is one transaction, so there are two
    observable states and the discriminator is the column this migration
    removes: `insurance_policies.vin`. Keying on the new tables would be wrong,
    because `create_all` creates them from the ORM before migrations run, so
    they exist on a database that has done nothing; and a fresh `create_all`
    database never had `vin` at all.
    """
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("insurance_policies"):
        print("  → insurance_policies missing; skip (run the earlier migrations first)")
        return

    columns = {c["name"] for c in inspector.get_columns("insurance_policies")}
    if "vin" not in columns:
        print("  → 107 already applied (insurance_policies.vin gone); nothing to do")
        return

    _preflight_backup_marker()

    if engine.dialect.name == "postgresql":
        _run_postgres(engine)
    else:
        _run_sqlite(engine)


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 107 is forward-only.")


if __name__ == "__main__":
    upgrade()
